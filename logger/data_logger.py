"""Date-partitioned logging of OCR text and transcripts.

Every generated file name is prefixed with "Shadow_" — both so all of this
app's own output is easy to spot/filter, and so the screen-capture exclusion
rule for windows/files starting with "Shadow" (see gui/workers.py
ScreenOcrWorker._is_excluded) reliably covers this app's own note files too.

Layout under base_dir:
    2026-07-14/
        Shadow_screen.jsonl                                # all screen OCR text for the day, one file
        Shadow_screen.txt                                  # same, human-readable
        Shadow_meeting_google_meet_20260714_103000.jsonl   # one file per detected meeting
        Shadow_meeting_google_meet_20260714_103000.txt

The "screen" channel (OCR) always writes to one single, fixed file pair for
the day — no per-window, per-tab, or per-app splitting. The "speech" channel
(voice transcripts) instead splits per meeting: call start_session("speech",
label) when a new call/meeting is detected to redirect subsequent
log_transcript() calls to a freshly-named file pair, until the next
start_session() call (or reset_session(), which reverts to the channel's
fixed default file). The two channels are always in separate files from
each other either way.

Consecutive duplicate text within the same channel (e.g. repeated OCR reads
of an unchanged screen) is skipped: log_event()/log_ocr()/log_transcript()
return None instead of writing anything when the text is identical to the
immediately preceding entry logged on that channel. Starting a new session
resets this dedup check, since a fresh meeting file has no prior entries to
compare against.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator, Optional

if TYPE_CHECKING:
    from database.json_store import EventStore

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_FILENAME_PREFIX = "Shadow_"

_CHANNEL_FILENAMES = {
    "screen": (f"{_FILENAME_PREFIX}screen.jsonl", f"{_FILENAME_PREFIX}screen.txt"),
    "speech": (f"{_FILENAME_PREFIX}speech.jsonl", f"{_FILENAME_PREFIX}speech.txt"),
}
_DEFAULT_FILENAMES = (f"{_FILENAME_PREFIX}events.jsonl", f"{_FILENAME_PREFIX}notes.txt")


def _slugify(label: str) -> str:
    slug = _SLUG_RE.sub("_", label.strip().lower()).strip("_")
    return slug or "session"


@dataclass
class LogEntry:
    timestamp: str  # ISO 8601
    source: str  # "screen_ocr" | "speech" | "manual"
    text: str
    extra: Dict[str, Any] = field(default_factory=dict)


class DataLogger:
    def __init__(self, base_dir: str = "output/logs", event_store: Optional["EventStore"] = None):
        self.base_dir = Path(base_dir).expanduser()
        self._last_text: Dict[str, str] = {}  # channel -> last text logged, for dedup
        self._session_stems: Dict[str, str] = {}  # channel -> filename stem override (no extension)
        # Optional: when set, every logged entry is also redacted, classified,
        # and persisted as a structured Event (see events/ and database/json_store.py).
        # None by default so existing callers/tests see no behavior change.
        self._event_store = event_store

    def _day_dir(self, when: Optional[datetime] = None) -> Path:
        when = when or datetime.now()
        day_dir = self.base_dir / when.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def start_session(self, channel: str, label: str, when: Optional[datetime] = None) -> str:
        """Redirects `channel` to a new dynamically-named file pair; returns the filename stem."""
        when = when or datetime.now()
        stem = f"{_FILENAME_PREFIX}{_slugify(label)}_{when.strftime('%Y%m%d_%H%M%S')}"
        self._session_stems[channel] = stem
        self._last_text.pop(channel, None)  # fresh file — don't dedup against the previous session
        return stem

    def reset_session(self, channel: str) -> None:
        """Reverts `channel` to its fixed default file pair."""
        self._session_stems.pop(channel, None)
        self._last_text.pop(channel, None)

    def _filenames(self, channel: str) -> tuple[str, str]:
        stem = self._session_stems.get(channel)
        if stem:
            return f"{stem}.jsonl", f"{stem}.txt"
        return _CHANNEL_FILENAMES.get(channel, _DEFAULT_FILENAMES)

    def log_event(
        self,
        source: str,
        text: str,
        extra: Optional[Dict[str, Any]] = None,
        channel: str = "default",
    ) -> Optional[LogEntry]:
        if self._last_text.get(channel) == text:
            return None  # duplicate of the immediately preceding entry on this channel — skip
        self._last_text[channel] = text

        now = datetime.now()
        entry = LogEntry(timestamp=now.isoformat(), source=source, text=text, extra=extra or {})
        day_dir = self._day_dir(now)
        events_filename, notes_filename = self._filenames(channel)
        with open(day_dir / events_filename, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        title = entry.extra.get("title")
        label = f"{source} — {title}" if title else source
        with open(day_dir / notes_filename, "a") as f:
            f.write(f"{now.strftime('%H:%M:%S')} [{label}] {text}\n")

        if self._event_store is not None:
            self._record_structured_event(now, source, text, entry.extra, channel)

        return entry

    def _record_structured_event(
        self, when: datetime, source: str, text: str, extra: Dict[str, Any], channel: str
    ) -> None:
        """Redacts + classifies a logged entry and persists it as a structured Event.

        Only ever touches the separate `events.jsonl` file (via EventStore) — the
        raw JSONL/.txt files written above are unaffected by redaction.
        """
        from events.classifier import classify
        from events.redaction import redact
        from events.schema import Event as StructuredEvent

        application = extra.get("title") or extra.get("application") or ""
        clean_text = redact(text)
        result = classify(clean_text, channel=channel, application=application)
        structured = StructuredEvent(
            timestamp=when.isoformat(),
            type=result.type,
            title=application or source,
            application=application,
            severity=result.severity,
            source=source,
            content=clean_text,
            entities=result.entities,
            tags=result.tags,
        )
        self._event_store.insert_event(structured)

    def log_ocr(self, text: str, extra: Optional[Dict[str, Any]] = None) -> Optional[LogEntry]:
        return self.log_event("screen_ocr", text, extra, channel="screen")

    def log_transcript(self, text: str, extra: Optional[Dict[str, Any]] = None) -> Optional[LogEntry]:
        return self.log_event("speech", text, extra, channel="speech")

    def iter_days(self) -> Iterator[Path]:
        if not self.base_dir.exists():
            return
        for day_dir in sorted(self.base_dir.iterdir()):
            if day_dir.is_dir():
                yield day_dir

    def iter_entries(self, day_dir: Optional[Path] = None) -> Iterator[LogEntry]:
        dirs = [day_dir] if day_dir else list(self.iter_days())
        for d in dirs:
            for events_file in sorted(d.glob(f"{_FILENAME_PREFIX}*.jsonl")):
                with open(events_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        yield LogEntry(**data)
