"""Flat-file (JSON/JSONL) store for structured events and assistant state.

No database — same "plain files under output/" approach
`logger/data_logger.py` already uses for OCR/speech logs, just for the
processed/classified layer instead of raw text:

    output/events/
        2026-07-20/
            events.jsonl          # one JSON object per line, newest appended last
        assistant_history.jsonl   # one JSON object per line, all days in one file
        suggested_questions.json  # {"2026-07-20": ["question", ...], ...}

Queries are a linear scan + filter in Python, same convention
`search/search_engine.py` already uses over `DataLogger.iter_entries()` —
no index, but this is a local single-user desktop app, not a data warehouse.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from events.schema import Event, EventType


class EventStore:
    def __init__(self, base_dir: Union[str, Path] = "output/events"):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self.base_dir / "assistant_history.jsonl"
        self._suggested_path = self.base_dir / "suggested_questions.json"

    # -- events -----------------------------------------------------------

    def _events_path(self, when: datetime) -> Path:
        day_dir = self.base_dir / when.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / "events.jsonl"

    def insert_event(self, event: Event) -> None:
        with open(self._events_path(event.when), "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def _iter_all_events(self) -> Iterator[Event]:
        if not self.base_dir.exists():
            return
        for day_dir in sorted(self.base_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            events_path = day_dir / "events.jsonl"
            if not events_path.exists():
                continue
            with open(events_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    yield Event.from_dict(json.loads(line))

    def query_events(
        self,
        *,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        event_type: Optional[Union[EventType, str]] = None,
        start: Optional[Union[str, datetime]] = None,
        end: Optional[Union[str, datetime]] = None,
        limit: int = 200,
    ) -> List[Event]:
        start_s = start.isoformat() if isinstance(start, datetime) else start
        end_s = end.isoformat() if isinstance(end, datetime) else end
        type_s = event_type.value if isinstance(event_type, EventType) else event_type
        keyword_l = keyword.lower() if keyword else None

        matched = []
        for event in self._iter_all_events():
            if start_s and event.timestamp < start_s:
                continue
            if end_s and event.timestamp > end_s:
                continue
            if source and event.source != source:
                continue
            if type_s and event.type.value != type_s:
                continue
            if keyword_l and keyword_l not in event.title.lower() and keyword_l not in event.content.lower():
                continue
            matched.append(event)

        matched.sort(key=lambda e: e.timestamp, reverse=True)
        return matched[:limit]

    def recent_events(self, within_hours: float = 24.0, limit: int = 500) -> List[Event]:
        cutoff = (datetime.now() - timedelta(hours=within_hours)).isoformat()
        return self.query_events(start=cutoff, limit=limit)

    # -- assistant history --------------------------------------------------

    def append_history(
        self,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        thread: str = "default",
    ) -> None:
        """`thread` keeps conversations logically separate within one file.

        The main Assistant tab uses the default thread; the Coding Agent tab
        (scoped to one project) uses `f"project:{key}"` so a project-scoped
        conversation's history never bleeds unrelated turns from the main
        Assistant tab (or another project) into its context — see
        `assistant.chat_engine.ChatEngine.ask`.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "citations": citations or [],
            "thread": thread,
        }
        with open(self._history_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_history(self, limit: int = 20, thread: str = "default") -> List[Dict[str, Any]]:
        if not self._history_path.exists():
            return []
        with open(self._history_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        entries = [e for e in entries if e.get("thread", "default") == thread]
        return entries[-limit:]

    def clear_history(self, thread: str = "default") -> None:
        """Removes `thread`'s history — used by "New Session" in the Assistant/
        Coding Agent tabs. Other threads (the main Assistant tab's `default`
        thread, or another project's `project:<key>`) are left untouched,
        since they all share this one file."""
        if not self._history_path.exists():
            return
        with open(self._history_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        remaining = [e for e in entries if e.get("thread", "default") != thread]
        with open(self._history_path, "w") as f:
            for entry in remaining:
                f.write(json.dumps(entry) + "\n")

    # -- suggested questions ------------------------------------------------

    def _load_suggested_questions(self) -> Dict[str, List[str]]:
        if not self._suggested_path.exists():
            return {}
        with open(self._suggested_path) as f:
            return json.load(f)

    def get_or_generate_suggested_questions(
        self, date: str, generator_fn: Callable[[], List[str]]
    ) -> List[str]:
        """Returns today's cached suggested questions, generating+caching them once per `date`."""
        cache = self._load_suggested_questions()
        if date in cache:
            return cache[date]

        questions = generator_fn()
        cache[date] = questions
        with open(self._suggested_path, "w") as f:
            json.dump(cache, f, indent=2)
        return questions
