"""Tests for assistant/edits/patcher.py.

The governing rule under test is "refuse rather than guess": every case where the
intended location is not uniquely determined must raise, because applying an edit
to the wrong lines silently corrupts a source file.
"""
from __future__ import annotations

import pytest

from assistant.edits.patcher import (
    EditBlock,
    PatchError,
    apply_edit_blocks,
    apply_raw_edits,
    parse_edit_blocks,
    strip_code_fence,
)


def _block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


# -- parsing ----------------------------------------------------------------


def test_parses_a_single_block() -> None:
    blocks = parse_edit_blocks(_block("old line", "new line"))

    assert blocks == [EditBlock(search="old line", replace="new line")]


def test_parses_multiple_blocks() -> None:
    raw = _block("a", "A") + "\n" + _block("b", "B")

    assert parse_edit_blocks(raw) == [
        EditBlock(search="a", replace="A"),
        EditBlock(search="b", replace="B"),
    ]


def test_ignores_prose_around_blocks() -> None:
    """Models add commentary regardless of what the prompt says."""
    raw = f"Sure! Here's the change:\n\n{_block('a', 'A')}\n\nLet me know if that helps."

    assert parse_edit_blocks(raw) == [EditBlock(search="a", replace="A")]


def test_tolerates_marker_length_drift() -> None:
    raw = "<<<<<< SEARCH\nold\n========\nnew\n>>>>>>>> REPLACE"

    assert parse_edit_blocks(raw) == [EditBlock(search="old", replace="new")]


def test_preserves_indentation_and_inner_blank_lines() -> None:
    search = "    def f():\n\n        return 1"
    blocks = parse_edit_blocks(_block(search, "    pass"))

    assert blocks[0].search == search, "leading indentation must survive parsing"


def test_missing_divider_raises() -> None:
    with pytest.raises(PatchError, match="divider"):
        parse_edit_blocks("<<<<<<< SEARCH\nold\n>>>>>>> REPLACE")


def test_missing_terminator_raises() -> None:
    with pytest.raises(PatchError, match="REPLACE"):
        parse_edit_blocks("<<<<<<< SEARCH\nold\n=======\nnew")


def test_no_blocks_returns_empty_list() -> None:
    assert parse_edit_blocks("I don't think any change is needed.") == []


def test_strip_code_fence_removes_a_wrapping_fence() -> None:
    assert strip_code_fence("```python\ncode here\n```") == "code here"


def test_strip_code_fence_leaves_inner_fences_alone() -> None:
    text = "Here:\n```py\nx\n```\ndone"
    assert strip_code_fence(text) == text


# -- applying ---------------------------------------------------------------


def test_applies_an_exact_match() -> None:
    original = "line one\nline two\nline three\n"

    result = apply_edit_blocks(original, [EditBlock("line two", "LINE TWO")])

    assert result == "line one\nLINE TWO\nline three\n"


def test_applies_multiple_non_overlapping_blocks() -> None:
    original = "alpha\nbeta\ngamma\n"

    result = apply_edit_blocks(
        original, [EditBlock("alpha", "ALPHA"), EditBlock("gamma", "GAMMA")]
    )

    assert result == "ALPHA\nbeta\nGAMMA\n"


def test_applies_blocks_given_out_of_order() -> None:
    """Blocks are sorted by position, so the model's ordering doesn't matter."""
    original = "one\ntwo\nthree\n"

    result = apply_edit_blocks(original, [EditBlock("three", "THREE"), EditBlock("one", "ONE")])

    assert result == "ONE\ntwo\nTHREE\n"


def test_multiline_replacement() -> None:
    original = "def f():\n    return 1\n"

    result = apply_edit_blocks(
        original, [EditBlock("def f():\n    return 1", "def f():\n    # doubled\n    return 2")]
    )

    assert result == "def f():\n    # doubled\n    return 2\n"


def test_ambiguous_match_raises_and_changes_nothing() -> None:
    """The core safety property: two candidate locations means refuse."""
    original = "x = 1\ny = 2\nx = 1\n"

    with pytest.raises(PatchError, match="appears 2 times"):
        apply_edit_blocks(original, [EditBlock("x = 1", "x = 99")])


def test_ambiguity_is_resolved_by_more_context() -> None:
    original = "x = 1\ny = 2\nx = 1\n"

    result = apply_edit_blocks(original, [EditBlock("y = 2\nx = 1", "y = 2\nx = 99")])

    assert result == "x = 1\ny = 2\nx = 99\n"


def test_missing_search_text_raises() -> None:
    with pytest.raises(PatchError, match="Could not find"):
        apply_edit_blocks("hello\n", [EditBlock("goodbye", "farewell")])


def test_overlapping_blocks_raise() -> None:
    original = "one\ntwo\nthree\n"

    with pytest.raises(PatchError, match="overlap"):
        apply_edit_blocks(
            original, [EditBlock("one\ntwo", "1\n2"), EditBlock("two\nthree", "2\n3")]
        )


def test_empty_block_list_raises() -> None:
    with pytest.raises(PatchError):
        apply_edit_blocks("content", [])


# -- fuzzy matching ---------------------------------------------------------


def test_tolerates_differing_trailing_whitespace() -> None:
    """Models routinely drop or add trailing spaces when quoting code."""
    original = "def f():   \n    return 1\n"

    result = apply_edit_blocks(original, [EditBlock("def f():\n    return 1", "def g():\n    return 2")])

    assert "def g():" in result


def test_tolerates_uniformly_shifted_indentation() -> None:
    """A model quoting a method body often loses the class-level indentation."""
    original = "class C:\n    def f(self):\n        return 1\n"

    result = apply_edit_blocks(
        original, [EditBlock("def f(self):\n    return 1", "def f(self):\n    return 2")]
    )

    assert "return 2" in result
    assert result.startswith("class C:")


def test_fuzzy_match_still_refuses_ambiguity() -> None:
    """Loosening whitespace must not loosen the uniqueness requirement."""
    original = "  foo()\n  bar()\n  foo()\n"

    with pytest.raises(PatchError):
        apply_edit_blocks(original, [EditBlock("foo()", "baz()")])


# -- insertions into empty files -------------------------------------------


def test_empty_search_writes_whole_content_for_an_empty_file() -> None:
    result = apply_edit_blocks("", [EditBlock("", "brand new content\n")])

    assert result == "brand new content\n"


def test_empty_search_on_a_non_empty_file_raises() -> None:
    """There's no way to know where it should go."""
    with pytest.raises(PatchError, match="already has content"):
        apply_edit_blocks("existing\n", [EditBlock("", "new")])


# -- apply_raw_edits --------------------------------------------------------


def test_apply_raw_edits_end_to_end() -> None:
    original = "greeting = 'hello'\n"
    block = _block("greeting = 'hello'", "greeting = 'hi'")
    raw = "Here you go:\n" + block

    assert apply_raw_edits(original, raw) == "greeting = 'hi'\n"


def test_apply_raw_edits_raises_when_the_model_wrote_prose() -> None:
    with pytest.raises(PatchError, match="no SEARCH/REPLACE blocks"):
        apply_raw_edits("code\n", "I don't think this needs changing.")


def test_apply_raw_edits_handles_a_fenced_response() -> None:
    original = "a = 1\n"
    raw = "```\n" + _block("a = 1", "a = 2") + "\n```"

    assert apply_raw_edits(original, raw) == "a = 2\n"
