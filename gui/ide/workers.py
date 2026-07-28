"""QThread workers for the Code tab.

Kept out of `gui/workers.py` (already ~700 lines) but following its conventions
exactly: constructors take plain values plus `parent=None`, `run()` wraps
everything in try/except and reports failures via `error`, and callers must
`wait()` a worker before dropping their last reference to it (see the note in
`gui/dashboard.py`'s `_StreamingChatMixin`).

Git and file I/O are both here because both block: `git status` on a large repo
and reading a 2MB file are each long enough to stutter the UI if run inline.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from assistant import git_ops
from assistant.edits.actions import (
    StaleFileError,
    apply_proposal,
    propose_edit,
    revert,
    stream_discussion,
    stream_explanation,
)
from assistant.knowledge.export import export_general, export_repo, write_index
from assistant.knowledge.general import GeneralKnowledgeBank
from assistant.knowledge.indexer import KnowledgeBank, build_index
from assistant.ollama_models import resolve_choices
from assistant.ollama_runtime import unload_all
from assistant.knowledge.summaries import generate_summary
from assistant.project_files import MAX_EDITABLE_BYTES, atomic_write_file, list_dir, read_text_file


class FileReadWorker(QThread):
    """Reads one file for the editor.

    `finished_ok` carries (rel_path, text, mtime) — the mtime is what the editor
    later hands to `FileSaveWorker` to detect a concurrent change, so it has to
    come from the same stat as the read.
    """

    finished_ok = pyqtSignal(str, str, float)
    error = pyqtSignal(str, str)  # (rel_path, message)

    def __init__(
        self, project_path: str, rel_path: str, max_bytes: int = MAX_EDITABLE_BYTES, parent=None
    ):
        super().__init__(parent)
        self._project_path = project_path
        self._rel_path = rel_path
        self._max_bytes = max_bytes

    def run(self) -> None:
        try:
            text, mtime = read_text_file(self._project_path, self._rel_path, max_bytes=self._max_bytes)
            self.finished_ok.emit(self._rel_path, text, mtime)
        except Exception as exc:
            self.error.emit(self._rel_path, str(exc))


class FileSaveWorker(QThread):
    """Saves one editor buffer to disk.

    `conflict` is separate from `error` because it isn't a failure so much as a
    question for the user (overwrite, reload, or cancel), and the UI handles the
    two very differently.
    """

    finished_ok = pyqtSignal(str, float)  # (rel_path, new_mtime)
    conflict = pyqtSignal(str, str)  # (rel_path, message)
    error = pyqtSignal(str, str)  # (rel_path, message)

    def __init__(
        self,
        project_path: str,
        rel_path: str,
        content: str,
        expected_mtime: Optional[float] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._project_path = project_path
        self._rel_path = rel_path
        self._content = content
        self._expected_mtime = expected_mtime

    def run(self) -> None:
        # Imported here rather than at module scope to keep the exception type
        # colocated with the one place that distinguishes it.
        from assistant.project_files import FileConflictError

        try:
            new_mtime = atomic_write_file(
                self._project_path, self._rel_path, self._content, expected_mtime=self._expected_mtime
            )
            self.finished_ok.emit(self._rel_path, new_mtime)
        except FileConflictError as exc:
            self.conflict.emit(self._rel_path, str(exc))
        except Exception as exc:
            self.error.emit(self._rel_path, str(exc))


class DirListWorker(QThread):
    """Lists one directory level for the file tree.

    Threaded because a cold directory on a network or FileVault-backed volume
    can take hundreds of milliseconds to stat, and the tree lists on every
    expand.
    """

    finished_ok = pyqtSignal(str, object)  # (rel_dir, list[tuple[str, bool]])
    error = pyqtSignal(str, str)

    def __init__(self, project_path: str, rel_dir: str, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._rel_dir = rel_dir

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._rel_dir, list_dir(self._project_path, self._rel_dir))
        except Exception as exc:
            self.error.emit(self._rel_dir, str(exc))


class RepoStatus:
    """Snapshot of a repository's git state, as shown in the repo bar and git panel."""

    def __init__(
        self,
        is_repo: bool,
        branch: str = "",
        branches: Optional[List[str]] = None,
        files: Optional[List[git_ops.FileStatus]] = None,
        head: str = "",
    ):
        self.is_repo = is_repo
        self.branch = branch
        self.branches = branches or []
        self.files = files or []
        self.head = head

    @property
    def is_clean(self) -> bool:
        return not self.files

    @property
    def summary(self) -> str:
        if not self.is_repo:
            return "not a git repo"
        if self.is_clean:
            return "clean"
        staged = sum(1 for f in self.files if f.is_staged)
        unstaged = sum(1 for f in self.files if not f.is_staged and not f.is_untracked)
        untracked = sum(1 for f in self.files if f.is_untracked)
        parts = []
        if staged:
            parts.append(f"{staged} staged")
        if unstaged:
            parts.append(f"{unstaged} modified")
        if untracked:
            parts.append(f"{untracked} untracked")
        return ", ".join(parts)


class GitStatusWorker(QThread):
    """Collects branch + status in one pass so the UI updates atomically."""

    finished_ok = pyqtSignal(object)  # RepoStatus
    error = pyqtSignal(str)

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self._project_path = project_path

    def run(self) -> None:
        try:
            if not git_ops.is_git_repo(self._project_path):
                self.finished_ok.emit(RepoStatus(is_repo=False))
                return
            self.finished_ok.emit(
                RepoStatus(
                    is_repo=True,
                    branch=git_ops.current_branch(self._project_path),
                    branches=git_ops.list_branches(self._project_path),
                    files=git_ops.status(self._project_path),
                    head=git_ops.head_sha(self._project_path),
                )
            )
        except Exception as exc:
            self.error.emit(str(exc))


class GitCommandWorker(QThread):
    """Runs one mutating git command.

    Deliberately one command per worker, and the tab runs at most one at a time:
    concurrent git invocations on the same repository contend for `index.lock`
    and fail with confusing errors.
    """

    _OPS = {
        "checkout": lambda path, p: git_ops.checkout(path, p["branch"]),
        "create_branch": lambda path, p: git_ops.create_branch(path, p["name"], p.get("base")),
        "stage": lambda path, p: git_ops.stage(path, p["paths"]),
        "unstage": lambda path, p: git_ops.unstage(path, p["paths"]),
        "discard": lambda path, p: git_ops.discard(path, p["paths"]),
        "commit": lambda path, p: git_ops.commit(path, p["message"]),
        "stash": lambda path, p: git_ops.stash(path, p.get("message", "")),
        "stash_pop": lambda path, p: git_ops.stash_pop(path),
    }

    finished_ok = pyqtSignal(str, object)  # (op, result)
    error = pyqtSignal(str, str)  # (op, message)

    def __init__(self, project_path: str, op: str, params: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._op = op
        self._params = params or {}

    def run(self) -> None:
        try:
            handler = self._OPS.get(self._op)
            if handler is None:
                raise ValueError(f"Unknown git operation: {self._op!r}")
            self.finished_ok.emit(self._op, handler(self._project_path, self._params))
        except Exception as exc:
            self.error.emit(self._op, str(exc))


class ExplainWorker(QThread):
    """Streams an explanation of the current file or selection."""

    chunk_ready = pyqtSignal(str)
    finished_ok = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, request, llm_cfg: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._request = request
        self._llm_cfg = llm_cfg
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            for chunk in stream_explanation(self._request, **self._llm_cfg):
                if self._cancelled:
                    break
                self.chunk_ready.emit(chunk)
            self.finished_ok.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class DiscussionWorker(QThread):
    """Streams an answer about the project without editing anything.

    Separate from `ExplainWorker` because discussion doesn't require an open file —
    the question is often about the project as a whole.
    """

    chunk_ready = pyqtSignal(str)
    finished_ok = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, request, llm_cfg: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._request = request
        self._llm_cfg = llm_cfg
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            for chunk in stream_discussion(self._request, **self._llm_cfg):
                if self._cancelled:
                    break
                self.chunk_ready.emit(chunk)
            self.finished_ok.emit()
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


class EditProposalWorker(QThread):
    """Generates an edit proposal without writing anything.

    `stop()` sets a flag checked between streamed chunks. It can't abort the
    in-flight HTTP read, but it does mean a user who changes their mind isn't
    stuck for the remainder of a 600-second timeout.
    """

    chunk_ready = pyqtSignal(str)  # raw model output, for a progress read-out
    finished_ok = pyqtSignal(object)  # EditProposal
    error = pyqtSignal(str)

    def __init__(self, request, llm_cfg: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._request = request
        self._llm_cfg = llm_cfg
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            proposal = propose_edit(
                self._request,
                on_chunk=self.chunk_ready.emit,
                should_cancel=lambda: self._cancelled,
                **self._llm_cfg,
            )
            if not self._cancelled:
                self.finished_ok.emit(proposal)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


class ApplyEditWorker(QThread):
    """Writes an accepted proposal to disk.

    `stale` is separate from `error` because it means "the world moved, re-run
    the action", which the UI explains differently from a genuine failure.
    """

    finished_ok = pyqtSignal(object)  # AppliedEdit
    stale = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        proposal,
        project_path: str,
        override_content: Optional[str] = None,
        shadow_root: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._proposal = proposal
        self._project_path = project_path
        self._override_content = override_content
        self._shadow_root = shadow_root

    def run(self) -> None:
        try:
            applied = apply_proposal(
                self._proposal,
                self._project_path,
                override_content=self._override_content,
                shadow_root=self._shadow_root,
            )
            self.finished_ok.emit(applied)
        except StaleFileError as exc:
            self.stale.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))


class RevertEditWorker(QThread):
    """Restores a file from its pre-edit backup."""

    finished_ok = pyqtSignal(str)  # rel_path
    error = pyqtSignal(str)

    def __init__(self, applied, parent=None):
        super().__init__(parent)
        self._applied = applied

    def run(self) -> None:
        try:
            revert(self._applied)
            self.finished_ok.emit(self._applied.rel_path)
        except Exception as exc:
            self.error.emit(str(exc))


class ModelListWorker(QThread):
    """Asks Ollama which models are installed.

    Threaded because the HTTP call blocks: if Ollama isn't running the connection
    sits until it times out, and doing that inline would freeze the window for
    seconds every time a repository is opened.
    """

    finished_ok = pyqtSignal(object)  # list[ModelInfo]

    def __init__(
        self,
        base_url: str,
        include_remote: bool = False,
        fallback: Optional[List[str]] = None,
        timeout_seconds: float = 5.0,
        parent=None,
    ):
        super().__init__(parent)
        self._base_url = base_url
        self._include_remote = include_remote
        self._fallback = fallback
        self._timeout = timeout_seconds

    def run(self) -> None:
        # No `error` signal: `resolve_choices` already degrades to a fallback
        # list, so there's nothing for a caller to handle differently.
        self.finished_ok.emit(
            resolve_choices(
                self._base_url,
                timeout_seconds=self._timeout,
                include_remote=self._include_remote,
                fallback=self._fallback,
            )
        )


class ModelUnloadWorker(QThread):
    """Releases Ollama's resident models from memory.

    Threaded for the same reason as `ModelListWorker`: the HTTP call blocks, and
    evicting a multi-gigabyte model is not instant.
    """

    finished_ok = pyqtSignal(object)  # list[str] — models actually unloaded
    error = pyqtSignal(str)

    def __init__(self, base_url: str, timeout_seconds: float = 30.0, parent=None):
        super().__init__(parent)
        self._base_url = base_url
        self._timeout = timeout_seconds

    def run(self) -> None:
        try:
            self.finished_ok.emit(
                unload_all(self._base_url, timeout_seconds=self._timeout)
            )
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


class GeneralBankWorker(QThread):
    """Folds newly captured activity into the General Knowledge Bank.

    Incremental (only events past the stored watermark), but reading the event
    history and re-scoring text still belongs off the GUI thread once capture has
    been running for a while.
    """

    finished_ok = pyqtSignal(object)  # GeneralDigest
    error = pyqtSignal(str)

    def __init__(self, event_store, shadow_root: Optional[str] = None,
                 force_full: bool = False, text_export_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._event_store = event_store
        self._shadow_root = shadow_root
        self._force_full = force_full
        self._text_export_dir = text_export_dir

    def run(self) -> None:
        try:
            bank = GeneralKnowledgeBank(self._event_store, self._shadow_root)
            digest = bank.build(force_full=self._force_full)
            try:
                export_general(self._event_store, self._shadow_root, self._text_export_dir)
                write_index(self._text_export_dir)
            except Exception:
                pass  # the text copy is a convenience, never a reason to fail
            self.finished_ok.emit(digest)
        except Exception as exc:
            self.error.emit(str(exc))


class KnowledgeIndexWorker(QThread):
    """Builds or updates a repository's Knowledge Bank index.

    The only writer to a bank's files, so there's no cross-writer contention to
    coordinate. No LLM calls — this is the fast static half, but a first index of
    a large repo still means thousands of reads and AST parses, so it belongs off
    the GUI thread and reports progress.
    """

    progress = pyqtSignal(int, int)  # (done, total)
    finished_ok = pyqtSignal(object)  # IndexResult
    error = pyqtSignal(str)

    def __init__(
        self,
        project_path: str,
        shadow_root: Optional[str] = None,
        max_files: int = 20_000,
        max_file_bytes: int = 512 * 1024,
        force_full: bool = False,
        text_export_dir: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._project_path = project_path
        self._shadow_root = shadow_root
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._force_full = force_full
        self._text_export_dir = text_export_dir
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = build_index(
                self._project_path,
                self._shadow_root,
                max_files=self._max_files,
                max_file_bytes=self._max_file_bytes,
                progress=self._report,
                force_full=self._force_full,
            )
            # Human-readable copy alongside the JSON. Done here rather than in the
            # UI so the file is already current when `finished_ok` lands, and a
            # failure to write it can't fail the index itself.
            try:
                export_repo(self._project_path, self._shadow_root, self._text_export_dir)
                write_index(self._text_export_dir)
            except Exception:
                pass
            if not self._cancelled:
                self.finished_ok.emit(result)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))

    def _report(self, done: int, total: int) -> None:
        if not self._cancelled:
            self.progress.emit(done, total)


class KnowledgeSummaryWorker(QThread):
    """Generates one LLM prose summary of the project, lazily.

    Separate from the index worker because it's slow (tens of seconds on a local
    model) and writes only `summaries.json`, so the two never contend.
    """

    chunk_ready = pyqtSignal(str)
    finished_ok = pyqtSignal(object)  # SummaryEntry
    error = pyqtSignal(str)

    def __init__(
        self,
        project_path: str,
        kind: str,
        llm_cfg: Dict[str, Any],
        shadow_root: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._project_path = project_path
        self._kind = kind
        self._llm_cfg = llm_cfg
        self._shadow_root = shadow_root
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            bank = KnowledgeBank(self._project_path, self._shadow_root)
            entry = generate_summary(
                bank,
                self._kind,
                on_chunk=self.chunk_ready.emit,
                should_cancel=lambda: self._cancelled,
                **self._llm_cfg,
            )
            if not self._cancelled:
                self.finished_ok.emit(entry)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))


class GitDiffWorker(QThread):
    """Reads a unified diff for one file (or the whole tree when rel_path is None)."""

    finished_ok = pyqtSignal(str, str)  # (rel_path, diff_text)
    error = pyqtSignal(str)

    def __init__(self, project_path: str, rel_path: Optional[str] = None, staged: bool = False, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._rel_path = rel_path
        self._staged = staged

    def run(self) -> None:
        try:
            diff = git_ops.diff_text(self._project_path, self._rel_path, staged=self._staged)
            self.finished_ok.emit(self._rel_path or "", diff)
        except Exception as exc:
            self.error.emit(str(exc))
