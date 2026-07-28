"""Tests for gui.ide.tab._classify_intent — the heuristic that replaced the
explicit Plan/Discussion/Code Fix mode picker in the Code tab's AI panel.
"""
from __future__ import annotations

import pytest

from gui.ide.tab import _classify_intent


@pytest.mark.parametrize(
    "prompt",
    [
        "what does this function do?",
        "why is this test flaky?",
        "how does the retry logic work",
        "explain the caching layer",
        "is this thread-safe?",
        "should I use a dataclass here?",
    ],
)
def test_questions_are_classified_as_discussion(prompt: str) -> None:
    assert _classify_intent(prompt) == "discussion"


@pytest.mark.parametrize(
    "prompt",
    [
        "plan a migration off the old auth module",
        "we need a plan for splitting this into microservices",
        "think through a change across the project",
        "this needs work across multiple files",
    ],
)
def test_multi_file_requests_are_classified_as_plan(prompt: str) -> None:
    assert _classify_intent(prompt) == "plan"


@pytest.mark.parametrize(
    "prompt",
    [
        "add a --dry-run flag",
        "fix the off-by-one error in the paginator",
        "charges are off by a cent",
        "refactor this into smaller functions",
    ],
)
def test_actionable_instructions_are_classified_as_code_fix(prompt: str) -> None:
    assert _classify_intent(prompt) == "code_fix"


def test_plan_keyword_wins_over_a_question_mark() -> None:
    """An explicit multi-file signal should still route to Plan even if phrased
    as a question — the wording that matters most is "plan"/"across the
    project", not sentence shape."""
    assert _classify_intent("can we plan a migration off the old auth module?") == "plan"
