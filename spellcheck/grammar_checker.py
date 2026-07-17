"""Grammar checking via a local language_tool_python (LanguageTool) server.

Requires a JRE on PATH (or JAVA_HOME set) — language_tool_python launches a
local Java process and downloads the LanguageTool bundle (~250MB) on first
use, cached afterward. Runs fully offline/locally once downloaded; nothing is
sent to languagetool.org's public API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class GrammarIssue:
    message: str
    replacements: List[str]


class GrammarChecker:
    def __init__(self, language: str = "en-US"):
        import language_tool_python

        self._tool = language_tool_python.LanguageTool(language)

    def check(self, text: str, max_issues: int = 3) -> List[GrammarIssue]:
        matches = self._tool.check(text)
        return [
            GrammarIssue(message=m.message, replacements=list(m.replacements[:3]))
            for m in matches[:max_issues]
        ]

    def close(self) -> None:
        self._tool.close()
