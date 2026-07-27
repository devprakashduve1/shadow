"""Applies search/replace edit blocks produced by a local model.

Why this format rather than a unified diff: a unified diff requires exact line
numbers and hunk line counts, and small local models get those wrong constantly.
A search/replace block needs neither — the model just quotes the lines it wants
changed::

    <<<<<<< SEARCH
    def old(x):
        return x
    =======
    def new(x):
        return x + 1
    >>>>>>> REPLACE

The whole design principle here is **refuse rather than guess**. Applying an edit
at the wrong location silently corrupts a source file, which is far worse than
reporting a failure and letting the caller retry or fall back to a whole-file
rewrite. So: zero matches raises, *multiple* matches raises (ambiguous), and
overlapping blocks raise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

SEARCH_MARKER = "<<<<<<< SEARCH"
DIVIDER_MARKER = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"

# Tolerant of the marker-length drift small models produce ("<<<<<< SEARCH",
# "<<<<<<<< SEARCH") and of trailing whitespace, but still anchored to the line
# start so a marker inside a string literal in the payload isn't mistaken for a
# real one.
_SEARCH_RE = re.compile(r"^<{3,}\s*SEARCH\s*$", re.MULTILINE)
_DIVIDER_RE = re.compile(r"^={3,}\s*$", re.MULTILINE)
_REPLACE_RE = re.compile(r"^>{3,}\s*REPLACE\s*$", re.MULTILINE)

# A fence the model added around the whole response despite being told not to.
_FENCE_RE = re.compile(r"^\s*```[\w.-]*\s*$", re.MULTILINE)


class PatchError(RuntimeError):
    """Raised when edit blocks can't be parsed or applied unambiguously."""


@dataclass
class EditBlock:
    """One search/replace pair.

    `search` empty means "insert into a new/empty file" — the only case where
    there is nothing to match against.
    """

    search: str
    replace: str

    @property
    def is_insertion(self) -> bool:
        return self.search.strip() == ""


def strip_code_fence(text: str) -> str:
    """Removes a single ``` fence wrapping the entire response.

    Only strips when the first and last non-blank lines are both fences, so a
    fenced snippet *inside* an otherwise-unfenced reply is left alone.
    """
    lines = text.strip().splitlines()
    if len(lines) >= 2 and _FENCE_RE.match(lines[0]) and _FENCE_RE.match(lines[-1]):
        return "\n".join(lines[1:-1])
    return text


def parse_edit_blocks(raw: str) -> List[EditBlock]:
    """Extracts every well-formed SEARCH/REPLACE block from a model response.

    Prose before, between, or after blocks is ignored — models routinely add
    "Here's the change:" no matter what the prompt says. Raises `PatchError` if
    a block is started but malformed, since silently dropping a half-parsed edit
    would apply an incomplete change.
    """
    text = strip_code_fence(raw)
    blocks: List[EditBlock] = []
    position = 0

    while True:
        search_match = _SEARCH_RE.search(text, position)
        if search_match is None:
            break

        divider_match = _DIVIDER_RE.search(text, search_match.end())
        if divider_match is None:
            raise PatchError(
                "An edit block started with SEARCH but has no '=======' divider. "
                "The model's output was cut off or malformed."
            )

        replace_match = _REPLACE_RE.search(text, divider_match.end())
        if replace_match is None:
            raise PatchError(
                "An edit block has no '>>>>>>> REPLACE' terminator. "
                "The model's output was cut off or malformed."
            )

        search_body = text[search_match.end() : divider_match.start()]
        replace_body = text[divider_match.end() : replace_match.start()]
        blocks.append(
            EditBlock(search=_strip_edge_newlines(search_body), replace=_strip_edge_newlines(replace_body))
        )
        position = replace_match.end()

    return blocks


def _strip_edge_newlines(body: str) -> str:
    """Drops the single newline adjoining each marker, preserving inner blanks.

    The markers are on their own lines, so the captured body always has a leading
    and trailing newline that is punctuation, not content. Using `.strip()` here
    would instead eat meaningful leading indentation and trailing blank lines.
    """
    if body.startswith("\n"):
        body = body[1:]
    elif body.startswith("\r\n"):
        body = body[2:]
    if body.endswith("\n"):
        body = body[:-1]
        if body.endswith("\r"):
            body = body[:-1]
    return body


def _find_all(haystack: str, needle: str) -> List[int]:
    """Returns every start offset of `needle` in `haystack` (non-overlapping)."""
    offsets = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return offsets
        offsets.append(index)
        start = index + max(len(needle), 1)


def _normalize_trailing_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def _dedent_uniformly(text: str) -> str:
    """Removes the common leading whitespace from every non-blank line."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    indent = min(len(line) - len(line.lstrip()) for line in lines)
    if indent == 0:
        return text
    return "\n".join(line[indent:] if line.strip() else line for line in text.splitlines())


@dataclass
class _Match:
    start: int
    end: int
    strategy: str


def _locate(content: str, search: str) -> _Match:
    """Finds the one place `search` occurs, trying progressively looser matches.

    The ladder exists because models reproduce code *almost* exactly — usually
    differing only in trailing whitespace or overall indentation. Each rung is
    still an exact match on *some* normalization of the text; none of them guess.
    A rung that finds several candidates raises rather than picking one.
    """
    attempts = (
        ("exact", content, search),
        ("trailing-whitespace", _normalize_trailing_ws(content), _normalize_trailing_ws(search)),
    )

    for strategy, haystack, needle in attempts:
        offsets = _find_all(haystack, needle)
        if len(offsets) == 1:
            if strategy == "exact":
                return _Match(offsets[0], offsets[0] + len(needle), strategy)
            # Offsets from a normalized haystack don't map back to the original
            # string, so re-find the corresponding original span by line.
            return _locate_by_lines(content, search, strategy)
        if len(offsets) > 1:
            raise PatchError(
                f"The SEARCH text appears {len(offsets)} times in the file, so there's no way to "
                "tell which one was meant. Refusing to guess — include more surrounding context "
                "to make it unique."
            )

    # Last rung: indentation-insensitive, matched line-wise.
    return _locate_by_lines(content, search, "reindented")


def _locate_by_lines(content: str, search: str, strategy: str) -> _Match:
    """Finds `search` as a run of lines, ignoring indentation and trailing space.

    Returns the span in the *original* `content` so the replacement lands in the
    right place regardless of which normalization matched.
    """
    content_lines = content.splitlines(keepends=True)
    search_lines = _dedent_uniformly(_normalize_trailing_ws(search)).splitlines()
    if not search_lines:
        raise PatchError("The SEARCH text is empty.")

    def normalized(line: str) -> str:
        return line.strip()

    needle = [normalized(line) for line in search_lines]
    hits: List[_Match] = []
    offsets: List[int] = []
    running = 0
    for line in content_lines:
        offsets.append(running)
        running += len(line)
    offsets.append(running)

    haystack = [normalized(line) for line in content_lines]
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i : i + len(needle)] == needle:
            hits.append(_Match(offsets[i], offsets[i + len(needle)], strategy))

    if not hits:
        preview = search.strip().splitlines()[0][:80] if search.strip() else "(empty)"
        raise PatchError(
            f"Could not find the SEARCH text in the file. It must match the current contents "
            f"exactly (ignoring indentation and trailing spaces). First line looked for: {preview!r}"
        )
    if len(hits) > 1:
        raise PatchError(
            f"The SEARCH text matches {len(hits)} places in the file (ignoring whitespace), so "
            "there's no way to tell which was meant. Refusing to guess."
        )
    return hits[0]


def apply_edit_blocks(original: str, blocks: List[EditBlock]) -> str:
    """Applies every block to `original`, returning the new content.

    All blocks are located against the *original* text first, then applied back
    to front. Locating as we go would mean each successful edit shifts the offsets
    for the rest — and worse, an edit could match text that a previous
    replacement just introduced.

    Raises `PatchError` without returning anything partial if any block can't be
    located, is ambiguous, or overlaps another. Callers get all-or-nothing.
    """
    if not blocks:
        raise PatchError("No edit blocks to apply.")

    # An insertion block ("" -> content) only makes sense for an empty file; for
    # a non-empty one there's no way to know where it goes.
    insertions = [b for b in blocks if b.is_insertion]
    if insertions:
        if original.strip():
            raise PatchError(
                "An edit block had an empty SEARCH section, which only means 'write this whole "
                "file' for a new or empty file. This file already has content."
            )
        if len(blocks) > 1:
            raise PatchError("Multiple edit blocks with an empty SEARCH section — can't order them.")
        return blocks[0].replace

    located = []
    for block in blocks:
        match = _locate(original, block.search)
        located.append((match, block))

    located.sort(key=lambda pair: pair[0].start)
    for (earlier, _), (later, _) in zip(located, located[1:]):
        if earlier.end > later.start:
            raise PatchError(
                "Two edit blocks overlap the same lines. Applying them would corrupt the file."
            )

    result = original
    for match, block in reversed(located):  # back to front keeps offsets valid
        result = result[: match.start] + block.replace + result[match.end :]
    return result


def apply_raw_edits(original: str, raw: str) -> str:
    """Parses a model response and applies it. Convenience for the common path."""
    blocks = parse_edit_blocks(raw)
    if not blocks:
        raise PatchError(
            "The model's response contained no SEARCH/REPLACE blocks. It may have replied with "
            "prose or a whole file instead."
        )
    return apply_edit_blocks(original, blocks)
