"""Unified diffs for previewing an AI edit before it touches disk.

Uses stdlib `difflib` — no new dependency. The Code tab renders changes with
Monaco's own diff editor (which takes the two texts, not a diff), so this text
form is for the chat transcript, logging, and tests.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Tuple


@dataclass
class DiffStats:
    added: int
    removed: int

    @property
    def is_empty(self) -> bool:
        return self.added == 0 and self.removed == 0

    def summary(self) -> str:
        if self.is_empty:
            return "no changes"
        parts = []
        if self.added:
            parts.append(f"+{self.added}")
        if self.removed:
            parts.append(f"-{self.removed}")
        return " ".join(parts)


def unified_diff_text(original: str, proposed: str, rel_path: str = "file", context: int = 3) -> str:
    """Returns a unified diff, or "" when the two texts are identical.

    `keepends=True` on the splits so lines that differ only in their trailing
    newline still show up — a model dropping the final newline is a real change
    worth seeing rather than an invisible one.
    """
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        n=context,
    )
    text = "".join(diff)
    # A file missing its trailing newline makes the last diff line run into the
    # next one when printed.
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def diff_stats(original: str, proposed: str) -> DiffStats:
    """Counts changed lines, ignoring diff headers and context lines."""
    added = removed = 0
    for line in difflib.unified_diff(
        original.splitlines(), proposed.splitlines(), lineterm="", n=0
    ):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return DiffStats(added=added, removed=removed)


def split_for_display(original: str, proposed: str, rel_path: str) -> Tuple[str, DiffStats]:
    """Returns (diff_text, stats) in one pass for the UI."""
    return unified_diff_text(original, proposed, rel_path), diff_stats(original, proposed)
