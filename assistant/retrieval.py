"""Lexical/date-filtered retrieval over the `events` files.

No embeddings/vector search here — that's Phase 2 of the project plan
(needs an embedding model + vector store). This does the same job
`search/search_engine.py` does for the Search tab, against `EventStore`
instead of a linear JSONL scan, plus a simple keyword overlap filter so a
specific question narrows to relevant events rather than just "everything
recent".

`retrieve_for_project` is the Coding Agent tab's variant: instead of a
recency window + question keywords, it's scoped to every event whose content
matches one project — either a ticket key (see `events/project_keys.py`) or
a manually browsed folder's name (see `assistant/manual_projects.py`) — with
no time limit, since a project's whole captured history is in scope, budget
permitting.
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

from database.json_store import EventStore
from events.project_keys import extract_project_keys
from events.schema import Event

from .manual_projects import ManualProjectRegistry, name_matches_content

# Trimmed to fit a small local model's context window alongside the prompt/
# history — same budget and "keep the tail" truncation convention as
# summarize/log_summarizer.py's _format_entries.
_MAX_CONTEXT_CHARS = 12000

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "i", "me", "my",
    "on", "in", "at", "to", "of", "for", "and", "or", "that", "this", "what", "when",
    "who", "how", "about", "with", "today", "yesterday", "please", "can", "you",
}

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def _keywords(question: str) -> List[str]:
    words = _WORD_RE.findall(question.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _format_line(event: Event, *, include_date: bool = False) -> str:
    if include_date:
        time_part = event.timestamp.replace("T", " ")[:16]  # "YYYY-MM-DD HH:MM"
    else:
        time_part = event.timestamp.split("T")[-1][:8]  # "HH:MM:SS"
    label = f"{event.type.value}: {event.title}" if event.title else event.type.value
    return f"[{time_part}] ({label}) {event.content}"


def _truncate_to_budget(
    events_oldest_first: List[Event], line_for: Callable[[Event], str], max_chars: int
) -> Tuple[str, List[Event]]:
    """Drops whole lines from the oldest end to fit `max_chars`, keeping the
    returned events aligned with the returned text so citations only ever
    reference text the model actually saw."""
    lines = [line_for(e) for e in events_oldest_first]

    total = 0
    kept: List[Tuple[str, Event]] = []
    for line, event in zip(reversed(lines), reversed(events_oldest_first)):
        total += len(line) + 1
        if kept and total > max_chars:
            break
        kept.append((line, event))
    kept.reverse()

    text = "\n".join(line for line, _ in kept)
    events_used = [event for _, event in kept]
    return text, events_used


def retrieve(
    event_store: EventStore,
    question: str,
    *,
    retrieval_days: int = 7,
    max_chars: int = _MAX_CONTEXT_CHARS,
) -> Tuple[str, List[Event]]:
    """Returns (formatted context text, events used) for `question`."""
    candidates = event_store.recent_events(within_hours=retrieval_days * 24, limit=1000)

    keywords = _keywords(question)
    if keywords:
        matched = [
            e for e in candidates
            if any(kw in e.title.lower() or kw in e.content.lower() for kw in keywords)
        ]
        # Fall back to the unfiltered recent set for vague questions ("what did I do today?")
        # rather than returning empty context just because no keyword matched.
        selected = matched or candidates
    else:
        selected = candidates

    # candidates/selected are newest-first (EventStore.query_events orders DESC);
    # build the context oldest-first so the most recent entries anchor the end.
    selected = list(reversed(selected))
    return _truncate_to_budget(selected, _format_line, max_chars)


def retrieve_for_project(
    event_store: EventStore,
    project_key: str,
    *,
    manual_registry: Optional[ManualProjectRegistry] = None,
    max_chars: int = _MAX_CONTEXT_CHARS,
    limit: int = 100_000,
) -> Tuple[str, List[Event]]:
    """Returns (formatted context text, events used) for one Coding Agent project.

    An event matches if its content contains `project_key`'s ticket-key
    pattern (re-checked live via `extract_project_keys`, same as
    `assistant.projects.list_projects` — see its docstring for why this
    doesn't just trust `event.entities`), OR — if `project_key` is a manually
    browsed folder's name (`manual_registry`) — if every word in the folder
    name shows up in the content (see `manual_projects.name_matches_content`;
    a repo directory name like "user-profile-mfe" rarely appears verbatim
    in Slack/Jira text, which is far more likely to say "Offer Selection
    MFE"). There's no recency window and no question-keyword filter, since
    being "in" a project scopes the whole conversation, not just one question.
    """
    manual_name = None
    if manual_registry is not None:
        for project in manual_registry.list():
            if project.name == project_key:
                manual_name = project.name
                break

    def _matches(event: Event) -> bool:
        if project_key in extract_project_keys(event.content):
            return True
        if manual_name and name_matches_content(manual_name, event.content):
            return True
        return False

    candidates = event_store.query_events(limit=limit)
    matches = [e for e in candidates if _matches(e)]
    matches = list(reversed(matches))  # oldest first, same convention as retrieve()

    def _line(event: Event) -> str:
        return _format_line(event, include_date=True)

    return _truncate_to_budget(matches, _line, max_chars)
