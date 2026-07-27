"""Turns retrieved Events into citation dicts for display under an answer."""
from __future__ import annotations

from typing import Any, Dict, List

from events.schema import Event

_SNIPPET_CHARS = 160


def build_citations(matched_events: List[Event]) -> List[Dict[str, Any]]:
    citations = []
    for event in matched_events:
        snippet = event.content.strip().replace("\n", " ")
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[:_SNIPPET_CHARS].rstrip() + "…"
        citations.append(
            {
                "type": event.type.value,
                "source": event.source,
                "timestamp": event.timestamp,
                "application": event.application,
                "snippet": snippet,
            }
        )
    return citations
