"""Ticket-key-shaped project identity extraction.

Used by `events/classifier.py` (tags extracted keys onto an event's
`entities`) and re-used directly by `assistant/projects.py` /
`assistant/retrieval.py`, which re-extract from each event's own content
rather than trusting the stored entities — see those modules' docstrings for
why (in short: it makes project detection work retroactively over data
captured before this feature existed).

Heuristic, not a real Jira/tracker integration — same "good enough, not
perfect" tradeoff as `callwatch/call_detector.py`'s call detection.
"""
from __future__ import annotations

import re
from typing import List

# Jira-style ticket key, e.g. "PROJ-1139", "PLAT-204" — the prefix (letters
# before the dash) becomes the project's identity.
_TICKET_KEY_RE = re.compile(r"\b([A-Z]{2,10})-\d{1,6}\b")


def extract_project_keys(text: str) -> List[str]:
    """Returns the distinct ticket-key prefixes found in `text`, e.g. ["PROJ"]."""
    return sorted({match.group(1) for match in _TICKET_KEY_RE.finditer(text)})
