"""Lightweight offline spelling suggestions via pyspellchecker.

Spelling only (no grammar) — pyspellchecker is a pure-Python, fully offline
word-frequency dictionary with no heavy runtime dependencies (unlike a real
grammar engine, which would need a local LanguageTool/Java server).
"""
from __future__ import annotations

from typing import List

from spellchecker import SpellChecker as _SpellChecker


class SpellChecker:
    def __init__(self, language: str = "en"):
        self._checker = _SpellChecker(language=language)

    def check_word(self, word: str, max_suggestions: int = 5) -> List[str]:
        """Returns up to `max_suggestions` corrections if `word` looks misspelled, else []."""
        clean = word.strip().lower()
        if len(clean) < 3 or not clean.isalpha():
            return []
        if clean in self._checker:
            return []
        candidates = self._checker.candidates(clean)
        if not candidates:
            return []
        return sorted(candidates, key=lambda c: -self._checker[c])[:max_suggestions]
