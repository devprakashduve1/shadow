"""Assembles bounded, relevant context for a prompt from the Knowledge Bank.

This is what the whole bank exists for. The alternative it replaces —
`project_files.find_relevant_files` — reads *every file in the project* on every
call to score them, which is O(n) disk I/O per question and unusable past a few
hundred files.

Here, ranking happens entirely over the in-memory index (paths, symbol names,
imports) with **zero file reads**; only the handful of winning files are then
read from disk. On a 10k-file repo that's ~6 reads instead of ~10,000.

Sections are assembled in priority order and dropped whole when the character
budget runs out, so the highest-value context survives truncation. Same idea as
`retrieval._truncate_to_budget`, but that one is coupled to `Event` objects, so
the pattern is reimplemented here rather than shared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .depth import render_depth
from .indexer import KnowledgeBank
from .manifests import summarize_dependencies
from .schema import FileEntry
from .summaries import SUMMARY_ARCHITECTURE, SUMMARY_PATTERNS, summary_text_for_context

DEFAULT_MAX_CHARS = 12_000
DEFAULT_MAX_FILES = 6

# How much of any single file to include. A 3000-line file would otherwise eat
# the whole budget on its own.
MAX_FILE_CHARS = 4000

# Fraction of the total budget that file bodies may use. The remainder is held
# back for the compact sections (impact analysis, frameworks, team decisions),
# which are small but disproportionately useful — see assemble_context.
FILE_BODY_BUDGET_SHARE = 0.55

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "i", "me", "my",
    "on", "in", "at", "to", "of", "for", "and", "or", "that", "this", "what", "when",
    "who", "how", "about", "with", "please", "can", "you", "it", "fix", "issue", "add",
    "make", "use", "using", "should", "would", "need", "want", "get", "set", "why",
    "code", "file", "function", "class", "method", "test", "tests",
}

# Relative weights for where a term matched. Symbol names score highest: matching
# a defined name is a much stronger signal than the word appearing in a path.
_WEIGHT_SYMBOL = 4
_WEIGHT_PATH = 3
_WEIGHT_IMPORT = 2
_WEIGHT_LANGUAGE = 1

# Regex-derived symbols include false positives (see symbols.py), so a match
# against one counts for less than a match against a parsed symbol.
_REGEX_SYMBOL_PENALTY = 0.5


@dataclass
class ContextResult:
    text: str
    files_used: List[str] = field(default_factory=list)
    symbols_used: List[str] = field(default_factory=list)
    truncated: bool = False
    sections_dropped: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _keywords(text: str) -> List[str]:
    """Extracts scoring terms, including the parts of camelCase/snake_case names.

    Splitting compound identifiers matters: a question about "user auth" should
    match a symbol called `authenticateUser`, which a whole-word match misses.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    expanded: List[str] = []
    for word in words:
        expanded.append(word)
        # snake_case is already split by the regex; split camelCase too.
        for part in re.findall(r"[a-z]+|[0-9]+", word):
            if part != word:
                expanded.append(part)
    return [w for w in dict.fromkeys(expanded) if len(w) > 2 and w not in _STOPWORDS]


def _score_entry(entry: FileEntry, keywords: Sequence[str]) -> Tuple[float, List[str]]:
    """Scores one indexed file against the query. Reads nothing from disk."""
    if not keywords:
        return 0.0, []

    score = 0.0
    matched_symbols: List[str] = []
    path_lower = entry.path.lower()
    symbol_penalty = _REGEX_SYMBOL_PENALTY if entry.parse == "regex" else 1.0

    for keyword in keywords:
        if keyword in path_lower:
            score += _WEIGHT_PATH
        for symbol in entry.symbols:
            if keyword in symbol.name.lower():
                score += _WEIGHT_SYMBOL * symbol_penalty
                matched_symbols.append(symbol.name)
                break  # one hit per keyword per file is enough
        for imported in entry.imports:
            if keyword in imported.lower():
                score += _WEIGHT_IMPORT
                break
        if keyword == entry.language:
            score += _WEIGHT_LANGUAGE

    return score, matched_symbols


def _importers_of(entries: Dict[str, FileEntry], target: str) -> List[str]:
    """Files whose imports plausibly refer to `target`.

    Import strings are language-specific and often relative ("./helper",
    "..pkg.mod"), so this matches on the module stem rather than trying to
    resolve them properly. Approximate on purpose — it's a ranking hint, not a
    dependency graph.
    """
    stem = Path(target).stem.lower()
    if not stem or stem in ("index", "__init__", "mod"):
        return []  # too generic to be a useful signal
    return [
        path
        for path, entry in entries.items()
        if path != target and any(stem == Path(i).stem.lower() for i in entry.imports)
    ]


def rank_files(
    entries: Dict[str, FileEntry],
    instruction: str,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    open_file: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """Returns (ranked paths, matched symbol names) using only the index.

    `open_file` and the files that import it are pinned to the front: whatever
    the user is looking at is almost always the most relevant thing, regardless
    of keyword overlap.
    """
    keywords = _keywords(instruction)
    pinned: List[str] = []
    if open_file and open_file in entries:
        pinned.append(open_file)
        pinned.extend(_importers_of(entries, open_file)[:2])

    scored: List[Tuple[float, str]] = []
    all_symbols: List[str] = []
    for path, entry in entries.items():
        if path in pinned or entry.skipped:
            continue
        score, matched = _score_entry(entry, keywords)
        if score > 0:
            scored.append((score, path))
            all_symbols.extend(matched)

    # Sort by score, then path, so equal scores produce a stable order rather
    # than dict-iteration order.
    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = pinned + [path for _score, path in scored]
    return ranked[:max_files], list(dict.fromkeys(all_symbols))[:40]


def _outline_text(entries: Dict[str, FileEntry], paths: Sequence[str]) -> str:
    """Renders the symbol outline for the chosen files."""
    lines: List[str] = []
    for path in paths:
        entry = entries.get(path)
        if entry is None or not entry.symbols:
            continue
        approximate = " (approximate)" if entry.parse == "regex" else ""
        lines.append(f"{path}{approximate}:")
        for symbol in entry.symbols[:25]:
            signature = symbol.signature or f"{symbol.kind} {symbol.name}"
            doc = f"  # {symbol.doc}" if symbol.doc else ""
            lines.append(f"  {signature}{doc}")
    return "\n".join(lines)


def _budgeted(sections: List[Tuple[str, str]], max_chars: int) -> Tuple[str, List[str]]:
    """Joins labelled sections, dropping whole low-priority ones to fit.

    Sections arrive highest-priority first and are dropped from the end, so
    running out of budget costs the least valuable context rather than
    truncating mid-file (which would hand the model a syntactically broken
    snippet).
    """
    kept: List[str] = []
    dropped: List[str] = []
    used = 0
    for label, body in sections:
        if not body.strip():
            continue
        block = f"\n--- {label} ---\n{body}"
        if used + len(block) > max_chars and kept:
            dropped.append(label)
            continue
        if used + len(block) > max_chars and not kept:
            # The first section alone exceeds the budget; include a trimmed
            # version rather than returning nothing at all.
            block = block[:max_chars]
        kept.append(block)
        used += len(block)
    return "".join(kept).strip(), dropped


def assemble_context(
    bank: KnowledgeBank,
    instruction: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_files: int = DEFAULT_MAX_FILES,
    open_file: Optional[str] = None,
    selection: str = "",
    read_file: Optional[Callable[[str], Optional[str]]] = None,
    general_context: str = "",
) -> ContextResult:
    """Builds prompt context for `instruction` from the bank.

    `read_file` is injectable so callers (and tests) control disk access; it
    defaults to reading from the bank's project root. It is called **only** for
    the top-ranked files — that bound is the point of the whole module.

    `general_context` is organizational knowledge from the General Knowledge Bank
    (`general.py`): decisions, action items, vocabulary drawn from meetings and
    screen capture. It's included at a lower priority than the code itself —
    useful for *why*, but the code is the authority on *what*.
    """
    entries = bank.load_files()
    if not entries:
        return ContextResult(text="")

    ranked, symbols = rank_files(
        entries, instruction, max_files=max_files, open_file=open_file
    )
    reader = read_file or (lambda rel: _default_reader(bank, rel))

    # File bodies get a share of the budget rather than all of it. Without this
    # cap they always win: six files at up to MAX_FILE_CHARS each is ~24k, so at
    # any realistic budget the small-but-high-value sections below (impact
    # analysis, frameworks, team decisions — a few hundred characters each) would
    # never survive. Pure priority ordering assumed comparably-sized sections;
    # they aren't.
    body_budget = int(max_chars * FILE_BODY_BUDGET_SHARE)
    per_file = max(400, body_budget // max(len(ranked), 1))

    bodies: List[str] = []
    files_used: List[str] = []
    body_used = 0
    for path in ranked:
        content = reader(path)
        if not content:
            continue
        if body_used >= body_budget:
            break
        allowance = min(per_file, MAX_FILE_CHARS, body_budget - body_used)
        files_used.append(path)
        clipped = content[:allowance]
        suffix = "\n... (truncated)" if len(content) > allowance else ""
        block = f"{path}:\n{clipped}{suffix}"
        bodies.append(block)
        body_used += len(block)

    readme, _docs = bank.load_docs()
    manifests = bank.load_manifests()
    meta = bank.load_meta()
    depth = bank.load_depth()

    # Priority order. Everything above a given line survives truncation before
    # anything below it does. The ranking reflects what a coding question actually
    # needs: the exact code first, then how it connects, then why it exists.
    sections: List[Tuple[str, str]] = [
        ("selected code", selection.strip()),
        ("relevant files", "\n\n".join(bodies)),
        # Structural facts — dependents, routes, frameworks. Deterministic, and
        # what makes impact analysis possible at all. Sized proportionally: a
        # fixed 2500 would simply never fit at a small budget, so the section
        # would be skipped entirely while smaller lower-priority ones slipped in.
        (
            "project structure",
            render_depth(depth, max_chars=max(600, max_chars // 6), focus=open_file or ""),
        ),
        ("symbol outline", _outline_text(entries, files_used)),
        ("dependencies", summarize_dependencies(manifests)),
        ("architecture", summary_text_for_context(bank, SUMMARY_ARCHITECTURE)[:1500]),
        ("conventions", summary_text_for_context(bank, SUMMARY_PATTERNS)[:1200]),
        ("project overview", readme.excerpt[:1500] if readme else ""),
        # Organizational context last: it explains intent, but the code above is
        # authoritative about behaviour.
        ("team context", general_context.strip()),
        ("project shape", _shape_text(meta, entries)),
    ]
    text, dropped = _budgeted(sections, max_chars)

    return ContextResult(
        text=text,
        files_used=files_used,
        symbols_used=symbols,
        truncated=bool(dropped),
        sections_dropped=dropped,
    )


def _default_reader(bank: KnowledgeBank, rel_path: str) -> Optional[str]:
    from ..project_files import read_file as read_project_file

    return read_project_file(bank.project_path, rel_path, max_bytes=MAX_FILE_CHARS)


def _shape_text(meta, entries: Dict[str, FileEntry]) -> str:
    """A one-liner about size and language mix, for orientation."""
    if meta is None:
        return ""
    languages: Dict[str, int] = {}
    for entry in entries.values():
        languages[entry.language] = languages.get(entry.language, 0) + 1
    top = sorted(languages.items(), key=lambda kv: -kv[1])[:5]
    mix = ", ".join(f"{name} ×{count}" for name, count in top if name != "unknown")
    parts = [f"{meta.file_count} indexed files"]
    if mix:
        parts.append(mix)
    if meta.truncated:
        parts.append("index truncated at the file limit")
    return "; ".join(parts)


def context_for_edit(
    project_path,
    instruction: str,
    *,
    open_file: Optional[str] = None,
    selection: str = "",
    shadow_root=None,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_files: int = DEFAULT_MAX_FILES,
    event_store=None,
) -> str:
    """Convenience wrapper returning just the context string.

    Combines both banks: repository knowledge always, plus organizational
    knowledge from the General Knowledge Bank when `event_store` is given.

    Returns "" when neither bank has anything, so callers can fall back to their
    previous behaviour (`project_files.find_relevant_files`) rather than
    special-casing the not-yet-indexed state.
    """
    general = ""
    if event_store is not None:
        try:
            from .general import assemble_general_context

            general = assemble_general_context(
                event_store, instruction, shadow_root=shadow_root, max_chars=2500
            )
        except Exception:
            general = ""  # organizational context is a bonus, never a blocker

    bank = KnowledgeBank(project_path, shadow_root)
    if not bank.exists:
        # No repo index yet, but team context alone is still worth sending.
        return f"[team context]\n{general}" if general else ""

    result = assemble_context(
        bank,
        instruction,
        open_file=open_file,
        selection=selection,
        max_chars=max_chars,
        max_files=max_files,
        general_context=general,
    )
    return result.text
