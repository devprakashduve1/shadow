"""Selection-scoped AI edit actions: propose, preview, apply, revert.

The flow is deliberately three-phase so nothing is written until the user has
seen it:

1. `propose_edit()` — asks the model, applies its edits **in memory**, returns an
   `EditProposal` carrying both texts and a diff. Touches no files.
2. the UI shows the diff and the user accepts, rejects, or hand-edits it
3. `apply_proposal()` — re-checks the file hasn't changed, backs it up, writes
   atomically, and journals what it did.

`revert()` undoes step 3 from the journal, independently of git and of the
editor's undo stack.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Union

from ..project_files import (
    ProjectFileError,
    atomic_write_file,
    read_text_file,
    resolve_in_project,
)
from ..prompts import (
    SELECTION_END,
    SELECTION_START,
    build_edit_prompt,
    build_explain_prompt,
    build_patch_retry_prompt,
    build_tests_prompt,
)
from ..shadow_home import backups_dir, ensure_dir, flatten_rel_path, journal_path
from ..streaming import stream_chat
from .atomic_io import append_jsonl, read_jsonl
from .diffs import DiffStats, diff_stats, unified_diff_text
from .patcher import PatchError, apply_raw_edits, strip_code_fence

# Files below this many lines get a whole-file rewrite instead of search/replace
# blocks: small models produce a correct whole file more reliably than correct
# SEARCH sections, and for a short file the extra tokens are cheap.
WHOLE_FILE_MAX_LINES = 300

STRATEGY_SEARCH_REPLACE = "search_replace"
STRATEGY_WHOLE_FILE = "whole_file"


class EditError(RuntimeError):
    """Raised when an edit can't be proposed or applied."""


class StaleFileError(EditError):
    """Raised when the file changed between proposing an edit and applying it.

    Applying anyway would discard whatever the other writer did. Likely in
    practice, not theoretical: a local model can take minutes, and the user is
    often still typing in the same file.
    """


class EditAction(str, Enum):
    EXPLAIN = "explain"
    REFACTOR = "refactor"
    OPTIMISE = "optimise"
    FIX = "fix"
    GENERATE_TESTS = "tests"
    ADD_COMMENTS = "comments"
    IMPLEMENT = "implement"

    @property
    def label(self) -> str:
        return {
            EditAction.EXPLAIN: "Explain",
            EditAction.REFACTOR: "Refactor",
            EditAction.OPTIMISE: "Optimise",
            EditAction.FIX: "Fix Bug",
            EditAction.GENERATE_TESTS: "Generate Tests",
            EditAction.ADD_COMMENTS: "Add Comments",
            EditAction.IMPLEMENT: "Implement",
        }[self]

    @property
    def edits_files(self) -> bool:
        """False for EXPLAIN, which only ever streams prose."""
        return self is not EditAction.EXPLAIN


@dataclass
class EditRequest:
    project_path: str
    rel_path: str
    action: EditAction
    instruction: str = ""
    selection: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    context: str = ""
    # When True and a Knowledge Bank exists, `context` is filled in from it —
    # see `_resolve_context`. Off for callers that supply their own.
    use_knowledge_bank: bool = True
    # Optional EventStore. When given, organizational context from the General
    # Knowledge Bank (meetings, decisions) is blended in alongside repo knowledge.
    event_store: object = None
    # Where the knowledge banks live. Must be threaded through rather than left
    # to default: `knowledge_bank.root` is configurable, and without this the edit
    # path would silently read a different location than the indexer wrote to.
    shadow_root: Optional[str] = None

    @property
    def has_selection(self) -> bool:
        return bool(self.selection.strip())


def _resolve_context(request: EditRequest) -> str:
    """Returns the project context to include, preferring the Knowledge Bank.

    The bank gives relevant context after reading only a handful of files; without
    one there's no cheap alternative, so we send none rather than falling back to
    scanning the whole project on a path where the user is waiting.
    """
    if request.context.strip():
        return request.context
    if not request.use_knowledge_bank:
        return ""
    try:
        from ..knowledge.context import context_for_edit

        return context_for_edit(
            request.project_path,
            f"{request.action.value} {request.instruction}".strip(),
            open_file=request.rel_path,
            selection=request.selection,
            event_store=request.event_store,
            shadow_root=request.shadow_root,
        )
    except Exception:
        # Context is an optimisation; a broken bank must not block an edit.
        return ""


@dataclass
class EditProposal:
    """A proposed change, not yet written anywhere."""

    rel_path: str
    original: str
    proposed: str
    action: EditAction
    strategy: str
    diff_text: str
    stats: DiffStats
    raw: str = ""
    is_new: bool = False
    # sha1 of `original`; re-checked at apply time to detect a concurrent write.
    original_sha1: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return self.original == self.proposed


@dataclass
class AppliedEdit:
    """Record of a completed write, enough to undo it."""

    project_path: str
    rel_path: str
    backup_path: Optional[str]
    sha1_before: str
    sha1_after: str
    action: str
    applied_at: str


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _choose_strategy(content: str) -> str:
    """Whole-file rewrite for short files, search/replace for long ones."""
    if content.count("\n") + 1 <= WHOLE_FILE_MAX_LINES:
        return STRATEGY_WHOLE_FILE
    return STRATEGY_SEARCH_REPLACE


def _mark_selection(content: str, selection: str) -> str:
    """Wraps the selected text in sentinels so the model can see its context.

    Falls back to the unmarked file if the selection can't be located (the user
    edited it after selecting, or it appears more than once) — the model then has
    the whole file and the instruction, which is worse but not wrong.
    """
    if not selection.strip():
        return content
    if content.count(selection) != 1:
        return content
    return content.replace(
        selection, f"{SELECTION_START}\n{selection}\n{SELECTION_END}", 1
    )


def _strip_selection_markers(text: str) -> str:
    """Removes sentinels a model echoed back into its output."""
    lines = [
        line for line in text.splitlines()
        if SELECTION_START not in line and SELECTION_END not in line
    ]
    return "\n".join(lines)


def _read_for_edit(project_path: Union[str, Path], rel_path: str) -> str:
    try:
        text, _mtime = read_text_file(project_path, rel_path)
        return text
    except ProjectFileError as exc:
        raise EditError(str(exc)) from exc


def stream_explanation(
    request: EditRequest,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 600.0,
) -> Iterator[str]:
    """Streams an explanation of the selection (or the whole file)."""
    content = _read_for_edit(request.project_path, request.rel_path)
    code = request.selection if request.has_selection else content
    prompt = build_explain_prompt(
        request.rel_path,
        code,
        instruction=request.instruction,
        context=_resolve_context(request),
        is_selection=request.has_selection,
    )
    return stream_chat(prompt, base_url=base_url, model=model, timeout_seconds=timeout_seconds)


def suggest_test_path(project_path: Union[str, Path], rel_path: str) -> str:
    """Guesses where a test file for `rel_path` should go.

    Follows whatever the project already does, since a test in the wrong place
    won't be collected: a top-level `tests/` directory if one exists, otherwise a
    sibling file using the ecosystem's convention.
    """
    source = Path(rel_path)
    suffix = source.suffix.lower()
    root = Path(project_path)

    if suffix in (".py", ".pyi"):
        if (root / "tests").is_dir():
            return f"tests/test_{source.stem}.py"
        return str(source.with_name(f"test_{source.stem}.py"))
    if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if (root / "__tests__").is_dir():
            return f"__tests__/{source.stem}.test{suffix}"
        return str(source.with_name(f"{source.stem}.test{suffix}"))
    if suffix == ".go":
        return str(source.with_name(f"{source.stem}_test.go"))
    if suffix == ".rs":
        return str(source.with_name(f"{source.stem}_test.rs"))
    return str(source.with_name(f"{source.stem}_test{suffix or '.txt'}"))


def propose_edit(
    request: EditRequest,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 600.0,
    on_chunk: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> EditProposal:
    """Asks the model for an edit and returns it as an in-memory proposal.

    Nothing is written. On a malformed search/replace reply this retries once
    with the parse error fed back, then falls back to a whole-file rewrite —
    small local models get the SEARCH sections wrong often enough that without
    the fallback the feature would fail routinely.
    """
    if not request.action.edits_files:
        raise EditError(f"{request.action.label} does not produce file edits.")

    if request.action is EditAction.GENERATE_TESTS:
        return _propose_new_test_file(
            request, base_url=base_url, model=model, timeout_seconds=timeout_seconds, on_chunk=on_chunk
        )

    original = _read_for_edit(request.project_path, request.rel_path)
    strategy = _choose_strategy(original)
    file_for_prompt = _mark_selection(original, request.selection) if request.has_selection else original
    project_context = _resolve_context(request)

    prompt = build_edit_prompt(
        request.action.value,
        request.rel_path,
        file_for_prompt,
        instruction=request.instruction,
        has_selection=request.has_selection,
        context=project_context,
        strategy=strategy,
    )

    warnings: List[str] = []
    raw = _collect(prompt, base_url, model, timeout_seconds, on_chunk, should_cancel)

    if strategy == STRATEGY_WHOLE_FILE:
        proposed = _strip_selection_markers(strip_code_fence(raw)).rstrip("\n") + "\n"
    else:
        try:
            proposed = apply_raw_edits(original, raw)
        except PatchError as first_error:
            warnings.append(f"First attempt couldn't be applied ({first_error}); retried.")
            retry_prompt = build_patch_retry_prompt(prompt, raw, str(first_error))
            retry_raw = _collect(
                retry_prompt, base_url, model, timeout_seconds, on_chunk, should_cancel
            )
            try:
                proposed = apply_raw_edits(original, retry_raw)
                raw = retry_raw
            except PatchError as second_error:
                warnings.append(
                    f"Retry also failed ({second_error}); fell back to a whole-file rewrite."
                )
                fallback_prompt = build_edit_prompt(
                    request.action.value,
                    request.rel_path,
                    file_for_prompt,
                    instruction=request.instruction,
                    has_selection=request.has_selection,
                    context=project_context,
                    strategy=STRATEGY_WHOLE_FILE,
                )
                raw = _collect(
                    fallback_prompt, base_url, model, timeout_seconds, on_chunk, should_cancel
                )
                proposed = _strip_selection_markers(strip_code_fence(raw)).rstrip("\n") + "\n"
                strategy = STRATEGY_WHOLE_FILE

    if not proposed.strip():
        raise EditError(
            "The model returned an empty file. Nothing was changed — try again, or use a "
            "different model."
        )

    return EditProposal(
        rel_path=request.rel_path,
        original=original,
        proposed=proposed,
        action=request.action,
        strategy=strategy,
        diff_text=unified_diff_text(original, proposed, request.rel_path),
        stats=diff_stats(original, proposed),
        raw=raw,
        original_sha1=_sha1(original),
        warnings=warnings,
    )


def _propose_new_test_file(
    request: EditRequest,
    *,
    base_url: str,
    model: str,
    timeout_seconds: float,
    on_chunk: Optional[Callable[[str], None]],
) -> EditProposal:
    """Generates a brand-new test file rather than editing the source."""
    source = _read_for_edit(request.project_path, request.rel_path)
    test_path = suggest_test_path(request.project_path, request.rel_path)

    existing = ""
    try:
        existing, _mtime = read_text_file(request.project_path, test_path)
    except ProjectFileError:
        pass  # no test file yet, which is the normal case

    prompt = build_tests_prompt(
        request.rel_path,
        source,
        test_path,
        instruction=request.instruction,
        context=_resolve_context(request),
    )
    raw = _collect(prompt, base_url, model, timeout_seconds, on_chunk, None)
    proposed = strip_code_fence(raw).rstrip("\n") + "\n"

    if not proposed.strip():
        raise EditError("The model returned no test content.")

    warnings = []
    if existing:
        warnings.append(f"{test_path} already exists — accepting will replace its contents.")

    return EditProposal(
        rel_path=test_path,
        original=existing,
        proposed=proposed,
        action=request.action,
        strategy=STRATEGY_WHOLE_FILE,
        diff_text=unified_diff_text(existing, proposed, test_path),
        stats=diff_stats(existing, proposed),
        raw=raw,
        is_new=not existing,
        original_sha1=_sha1(existing),
        warnings=warnings,
    )


def _collect(
    prompt: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    on_chunk: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> str:
    """Drains a stream_chat generator into one string, forwarding chunks.

    `should_cancel` is checked between chunks so a worker can abandon a slow
    generation without waiting out the full timeout.
    """
    parts: List[str] = []
    for chunk in stream_chat(prompt, base_url=base_url, model=model, timeout_seconds=timeout_seconds):
        parts.append(chunk)
        if on_chunk is not None:
            on_chunk(chunk)
        if should_cancel is not None and should_cancel():
            raise EditError("Cancelled.")
    return "".join(parts)


def apply_proposal(
    proposal: EditProposal,
    project_path: Union[str, Path],
    *,
    override_content: Optional[str] = None,
    backup: bool = True,
    shadow_root: Optional[Union[str, Path]] = None,
) -> AppliedEdit:
    """Writes a proposal to disk, backing up the previous content first.

    Deliberately does NOT require a clean git tree or create a branch, unlike
    `coding_agent.apply_plan` — the user is editing files here, so demanding a
    clean tree would make the feature unusable. Reversibility comes from the
    backup + journal instead.

    `override_content` is how "edit manually" lands: the UI passes the text the
    user adjusted, and that is written instead of the model's version.

    Raises `StaleFileError` (writing nothing) if the file changed since the
    proposal was made.
    """
    project_path = Path(project_path)
    content = proposal.proposed if override_content is None else override_content

    # Re-read and compare hashes rather than trusting the proposal's snapshot.
    current = ""
    try:
        current, _mtime = read_text_file(project_path, proposal.rel_path)
    except ProjectFileError:
        # Missing is expected for a new file, and a problem for anything else.
        if not (proposal.is_new or not proposal.original):
            raise StaleFileError(
                f"{proposal.rel_path} no longer exists — it may have been deleted or renamed "
                "since this change was proposed."
            )

    if _sha1(current) != proposal.original_sha1:
        raise StaleFileError(
            f"{proposal.rel_path} changed on disk since this change was proposed, so applying it "
            "would discard that other edit. Re-run the action to work from the current version."
        )

    backup_path: Optional[Path] = None
    if backup and current:
        backup_path = _write_backup(project_path, proposal.rel_path, current, shadow_root)

    try:
        atomic_write_file(project_path, proposal.rel_path, content)
    except ProjectFileError as exc:
        raise EditError(str(exc)) from exc

    applied = AppliedEdit(
        project_path=str(project_path),
        rel_path=proposal.rel_path,
        backup_path=str(backup_path) if backup_path else None,
        sha1_before=proposal.original_sha1,
        sha1_after=_sha1(content),
        action=proposal.action.value,
        applied_at=datetime.now().isoformat(timespec="seconds"),
    )
    _journal(project_path, applied, shadow_root)
    return applied


def _write_backup(
    project_path: Path, rel_path: str, content: str, shadow_root: Optional[Union[str, Path]]
) -> Path:
    directory = ensure_dir(backups_dir(project_path, shadow_root))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{_sha1(content)[:8]}-{flatten_rel_path(rel_path)}"
    target = directory / name
    target.write_text(content, encoding="utf-8")
    return target


def _journal(
    project_path: Path, applied: AppliedEdit, shadow_root: Optional[Union[str, Path]]
) -> None:
    append_jsonl(
        journal_path(project_path, shadow_root),
        {
            "applied_at": applied.applied_at,
            "rel_path": applied.rel_path,
            "action": applied.action,
            "backup_path": applied.backup_path,
            "sha1_before": applied.sha1_before,
            "sha1_after": applied.sha1_after,
        },
    )


def revert(applied: AppliedEdit) -> None:
    """Restores the file to its pre-edit content from the backup.

    Refuses if the file changed again after the edit — reverting then would throw
    away work done since, which is exactly the kind of silent loss this module
    exists to prevent.
    """
    if not applied.backup_path:
        raise EditError(
            f"No backup was kept for {applied.rel_path} (it was a new file), so there is nothing "
            "to restore. Delete it manually if it isn't wanted."
        )
    backup = Path(applied.backup_path)
    if not backup.is_file():
        raise EditError(f"Backup {backup} is missing — cannot revert.")

    project_path = Path(applied.project_path)
    try:
        current, _mtime = read_text_file(project_path, applied.rel_path)
    except ProjectFileError as exc:
        raise EditError(f"Cannot read {applied.rel_path} to revert it: {exc}") from exc

    if _sha1(current) != applied.sha1_after:
        raise StaleFileError(
            f"{applied.rel_path} has been modified since this edit was applied. Reverting now "
            "would discard those later changes."
        )

    atomic_write_file(project_path, applied.rel_path, backup.read_text(encoding="utf-8"))


def edit_history(
    project_path: Union[str, Path], shadow_root: Optional[Union[str, Path]] = None, limit: int = 50
) -> List[dict]:
    """Returns the most recent journalled edits, newest first."""
    records = read_jsonl(journal_path(project_path, shadow_root))
    return list(reversed(records))[:limit]
