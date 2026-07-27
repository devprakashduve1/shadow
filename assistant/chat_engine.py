"""Orchestrates retrieval + prompting + streaming + history for the Assistant tab.

`ask()` is a generator so `gui/workers.py`'s `ChatWorker` can forward chunks to
the UI as they arrive (see `assistant/streaming.py`). Citations for the just-
answered question are exposed via `last_citations` once the generator is
exhausted, since a generator can't both `yield` text and `return` a value that
callers naturally consume via a `for` loop.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterator, List, Optional

from database.json_store import EventStore
from events.schema import Event, EventType

from .citations import build_citations
from .manual_projects import ManualProjectRegistry
from .prompts import build_prompt, build_suggested_questions_prompt
from .retrieval import retrieve, retrieve_for_project
from .streaming import AssistantError, stream_chat

_DEFAULT_SUGGESTIONS = ["What did I work on today?", "What should I finish tomorrow?"]

# Strips leading "1.", "1)", "-", "*", "•" list markers a small model might add
# despite being told not to — see _parse_questions.
_LIST_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def _parse_questions(text: str, limit: int = 8) -> List[str]:
    """Extracts one question per line from a suggested-questions completion.

    Deliberately simple/permissive rather than requiring strict JSON — small
    local models are inconsistent about following exact output-format
    instructions, so this just takes any line that, once a list marker is
    stripped, ends in "?" and treats everything else (preambles, sign-offs)
    as noise to discard.
    """
    questions: List[str] = []
    for line in text.splitlines():
        line = _LIST_PREFIX_RE.sub("", line).strip()
        if not line or not line.endswith("?") or line in questions:
            continue
        questions.append(line)
        if len(questions) >= limit:
            break
    return questions


class ChatEngine:
    def __init__(
        self,
        event_store: EventStore,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "gemma4",
        timeout_seconds: float = 180.0,
        retrieval_days: int = 7,
        max_context_chars: int = 12000,
        history_limit: int = 10,
        manual_project_registry: Optional[ManualProjectRegistry] = None,
    ):
        self._store = event_store
        self._base_url = base_url
        self._model = model
        self._timeout = timeout_seconds
        self._retrieval_days = retrieval_days
        self._max_context_chars = max_context_chars
        self._history_limit = history_limit
        # Same underlying file the Code tab (`gui/ide/`) writes to
        # when the user browses a folder (both point at `event_store.base_dir`
        # by default), so a just-added folder is immediately chattable.
        self._manual_projects = manual_project_registry or ManualProjectRegistry(
            event_store.base_dir / "manual_projects.json"
        )
        self.last_citations: List[Dict[str, Any]] = []

    @classmethod
    def from_settings(cls, event_store: EventStore, settings) -> "ChatEngine":
        return cls(
            event_store,
            base_url=settings.get("assistant.base_url", "http://localhost:11434"),
            model=settings.get("assistant.model", "gemma4"),
            timeout_seconds=settings.get("assistant.timeout_seconds", 180.0),
            retrieval_days=settings.get("assistant.retrieval_days", 7),
            max_context_chars=settings.get("assistant.max_context_chars", 12000),
        )

    @staticmethod
    def _thread_for(project: Optional[str]) -> str:
        return f"project:{project}" if project else "default"

    def ask(
        self,
        question: str,
        project: Optional[str] = None,
        model: Optional[str] = None,
        free_chat: bool = False,
    ) -> Iterator[str]:
        """Streams the answer to `question`, then records the exchange in history.

        `project`, when set (the Coding Agent tab), scopes retrieval to just
        that project's tagged events (see `retrieval.retrieve_for_project`)
        instead of the main Assistant tab's recent-window + keyword search,
        and keeps its conversation history in its own thread
        (`f"project:{project}"`) so it never mixes with the main Assistant
        tab's history or another project's.

        `model`, when set, overrides this engine's configured `self._model`
        for just this call — lets the Coding Agent tab's model dropdown
        (see `gui/ide/ai_panel.py`) apply to chat replies too,
        not just Plan Fix/Apply, so every LLM call in that tab consistently
        uses whichever model the user picked.

        `free_chat`, when True, skips retrieval entirely and prompts the
        model to chat naturally instead of restricting answers to retrieved
        activity (see `prompts.build_prompt`'s `free_chat`) — used by the
        Coding Agent tab, whose retrieved "context" is often noisy OCR of the
        user's own screen and isn't what a conversational chat should be
        grounded in. `matched_events` stays empty, so no citations/"Sources"
        get recorded or shown for these answers.
        """
        thread = self._thread_for(project)
        history = self._store.get_history(limit=self._history_limit, thread=thread)

        if free_chat:
            context, matched_events, scope_label = "", [], None
        elif project:
            context, matched_events = retrieve_for_project(
                self._store, project, manual_registry=self._manual_projects, max_chars=self._max_context_chars
            )
            scope_label = f'the "{project}" project'
        else:
            context, matched_events = retrieve(
                self._store,
                question,
                retrieval_days=self._retrieval_days,
                max_chars=self._max_context_chars,
            )
            scope_label = None

        prompt = build_prompt(question, context, history, scope_label=scope_label, free_chat=free_chat)
        self._store.append_history("user", question, thread=thread)

        answer_parts: List[str] = []
        try:
            for chunk in stream_chat(
                prompt, base_url=self._base_url, model=model or self._model, timeout_seconds=self._timeout
            ):
                answer_parts.append(chunk)
                yield chunk
        finally:
            answer = "".join(answer_parts)
            citations = build_citations(matched_events)
            self.last_citations = citations
            if answer:
                self._store.append_history("assistant", answer, citations, thread=thread)

    def new_session(self, project: Optional[str] = None) -> None:
        """Clears the conversation history for "New Session" — the main
        Assistant tab's if `project` is None, otherwise that one project's.

        Only clears persisted history/citations (`assistant_history.jsonl`);
        it's the caller's job to also clear the visible transcript and, for
        the Coding Agent tab, any in-progress plan — see
        `gui/dashboard.py`'s `AssistantTab` and `gui/ide/tab.py`'s `_new_session()`.
        """
        self._store.clear_history(thread=self._thread_for(project))
        self.last_citations = []

    def suggested_questions(self, today: Optional[str] = None) -> List[str]:
        """Returns today's suggested questions, generating+caching them once per day.

        Generation calls the local LLM so questions are grounded in what
        actually happened today (real names/errors/tickets/times), rather
        than fixed templates — see `_generate_suggestions`. This can block on
        a slow/first-load Ollama call, so callers on the GUI thread should run
        it off-thread (see `gui/workers.py`'s `SuggestedQuestionsWorker`).
        """
        today = today or date.today().isoformat()
        return self._store.get_or_generate_suggested_questions(today, self._generate_suggestions)

    def _generate_suggestions(self) -> List[str]:
        events = self._store.recent_events(within_hours=24)
        if not events:
            return list(_DEFAULT_SUGGESTIONS)

        # Empty question -> retrieval.retrieve()'s keyword filter is a no-op,
        # so this just returns all of today's events (within the char budget)
        # formatted as context — the same "today's activity" window
        # `_fallback_suggestions` below also uses.
        context, _ = retrieve(self._store, "", retrieval_days=1, max_chars=self._max_context_chars)
        if not context:
            return self._fallback_suggestions(events)

        prompt = build_suggested_questions_prompt(context)
        try:
            answer = "".join(
                stream_chat(prompt, base_url=self._base_url, model=self._model, timeout_seconds=self._timeout)
            )
        except AssistantError:
            return self._fallback_suggestions(events)

        return _parse_questions(answer) or self._fallback_suggestions(events)

    def _fallback_suggestions(self, events: List[Event]) -> List[str]:
        """Rule-based templates, used when the LLM is unreachable or returns nothing usable."""
        recent_types = {event.type for event in events}
        questions = list(_DEFAULT_SUGGESTIONS)
        if EventType.ERROR in recent_types or EventType.BUG in recent_types:
            questions.insert(1, "What bugs appeared today?")
        if EventType.MEETING in recent_types:
            questions.insert(1, "What meetings need follow-up?")
        if EventType.DECISION in recent_types:
            questions.insert(1, "What decisions were made today?")
        return questions
