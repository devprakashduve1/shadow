"""Best-effort secret/PII redaction, applied before text enters the `events` table.

This is a regex-based heuristic (same "good enough, not perfect" spirit as
`callwatch/call_detector.py`'s call detection) — not a guarantee that every
secret is caught. It only ever runs on the copy of text that gets classified
into a structured `Event`; the existing raw JSONL/`.txt` log written by
`DataLogger` is left untouched, since that's already-documented, local-only
behavior this change doesn't alter.
"""
from __future__ import annotations

import re
from typing import Pattern, Tuple

# Each rule: (compiled pattern, replacement placeholder). Order matters — more
# specific patterns (named cloud provider key formats) run before the generic
# "key/token/password = value" catch-all so they get their own descriptive tag.
_RULES: Tuple[Tuple[Pattern[str], str], ...] = (
    # OpenAI-style secret keys: sk-..., sk-proj-...
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # AWS access key IDs
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # GitHub personal access tokens
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    # Bearer authorization headers
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{8,}\b"), "Bearer [REDACTED_TOKEN]"),
    # Generic key=value / key: value assignments for common secret-ish names
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9/+._-]{6,}[\"']?"
        ),
        r"\1=[REDACTED]",
    ),
    # Credit-card-like sequences (13-19 digits, optionally grouped by spaces/dashes)
    (
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "[REDACTED_CARD_NUMBER]",
    ),
    # Email addresses — kept coarse (full mask) rather than partial, simplest to reason about
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
)


def redact(text: str) -> str:
    """Returns `text` with recognizable secrets/PII replaced by placeholders."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
