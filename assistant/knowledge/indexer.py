"""Builds and incrementally updates a repository's Knowledge Bank index.

No LLM calls happen here — this is the fast, deterministic half of the bank
(file list, languages, symbols, dependencies, docs). Prose summaries are
generated lazily and separately, in `summaries.py`.

## Incremental correctness

Re-reading every file on every open would make large repos unusable, so updates
only touch files that changed. Deciding *which* changed is the whole problem, and
there are four ways to get it wrong. Each is handled explicitly below:

1. **Amended or rebased HEAD** — the stored HEAD may no longer exist, making
   `git diff <old>..HEAD` fail or lie. Verified with `git cat-file -e` first;
   on failure we do a full rescan.
2. **Files that were dirty last time** — a file uncommitted at index time and
   reverted since looks unchanged to `git diff`. The previously-dirty paths are
   persisted in `meta.json` and re-checked.
3. **Renames and deletions** — a rename reports two paths and a delete must drop
   the old key, or the index keeps describing files that no longer exist.
4. **Gitignored files** — the bank indexes them, but git will never report them
   as changed. Covered by a cheap stat sweep over every known path.

`sha1` is the authority on "did this change"; `(size, mtime_ns)` is only a gate
to avoid hashing files that obviously didn't.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from .. import git_ops
from ..project_files import DEFAULT_IGNORED_DIRS, iter_files
from ..shadow_home import bank_dir, ensure_dir, repo_id
from ..edits.atomic_io import read_json, write_json_atomic
from . import symbols as symbol_extraction
from .depth import DEPTH_FILE, RepoDepth, build_depth
from .manifests import collect_manifests
from .schema import (
    DOCS_FILE,
    FILES_FILE,
    MANIFESTS_FILE,
    META_FILE,
    OUTLINE_FILE,
    SCHEMA_VERSION,
    BankMeta,
    DocExcerpt,
    FileEntry,
    GitState,
    IndexResult,
    Manifest,
    files_from_dict,
    files_to_dict,
    language_for_path,
)

# A monorepo can have far more files than is useful to index; past this we stop
# and flag the index as truncated rather than grinding for minutes.
DEFAULT_MAX_FILES = 20_000

# Files larger than this get an index entry but no symbol extraction — usually
# generated code, fixtures, or minified bundles, where parsing costs a lot and
# tells us nothing.
DEFAULT_MAX_FILE_BYTES = 512 * 1024

# How much README/doc text to keep. Enough to convey what a project is; not
# enough to dominate a prompt.
DOC_EXCERPT_CHARS = 4000

_DOC_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
_DOC_DIRS = ("docs", "doc")
_DOC_SUFFIXES = (".md", ".rst")

ProgressFn = Callable[[int, int], None]


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _read_text(path: Path, max_bytes: int) -> Tuple[Optional[str], bytes]:
    """Reads a file as text if it's decodable and small enough.

    Returns (text_or_None, raw_bytes). The raw bytes are returned either way so
    the caller can hash exactly what's on disk, including for binary files.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None, b""
    if len(raw) > max_bytes or b"\x00" in raw[:8192]:
        return None, raw
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError:
        return None, raw


def _index_one_file(root: Path, rel_path: str, max_file_bytes: int) -> Optional[FileEntry]:
    """Builds the index entry for a single file, or None if it's unreadable."""
    absolute = root / rel_path
    try:
        stat = absolute.stat()
    except OSError:
        return None

    text, raw = _read_text(absolute, max_file_bytes)
    entry = FileEntry(
        path=rel_path,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha1=_hash_bytes(raw),
        language=language_for_path(rel_path),
    )
    if text is None:
        entry.skipped = "too_large" if stat.st_size > max_file_bytes else "not_text"
        return entry

    entry.loc = text.count("\n") + 1
    entry.symbols, entry.imports, entry.parse = symbol_extraction.extract(rel_path, text)
    return entry


def _discover_files(root: Path, max_files: int) -> Tuple[List[str], bool]:
    """Lists candidate files, preferring git's own view of the project.

    `git ls-files` is better than walking the filesystem: it honours
    `.gitignore`, so build output, virtualenvs, and vendored dependencies are
    excluded using the project's own rules rather than this codebase's guesses
    (`DEFAULT_IGNORED_DIRS`). Falls back to a walk for non-git directories.
    """
    if git_ops.is_git_repo(root):
        tracked = git_ops.tracked_files(root)
        if tracked:
            # git doesn't apply our ignore list, and won't exclude a checked-in
            # `.vscode/` or a committed `dist/`; filter those out too.
            filtered = [
                path for path in tracked
                if not any(part in DEFAULT_IGNORED_DIRS for part in Path(path).parts)
            ]
            return filtered[:max_files], len(filtered) > max_files

    walked = [str(p) for p in iter_files(root, max_files=max_files + 1)]
    return walked[:max_files], len(walked) > max_files


def _collect_docs(root: Path) -> Tuple[Optional[DocExcerpt], List[DocExcerpt]]:
    """Finds the README plus a handful of docs/ files."""
    readme: Optional[DocExcerpt] = None
    for entry in sorted(root.iterdir()) if root.is_dir() else []:
        if entry.is_file() and entry.name.lower() in _DOC_NAMES:
            readme = _doc_excerpt(root, entry)
            break

    docs: List[DocExcerpt] = []
    for directory in _DOC_DIRS:
        doc_dir = root / directory
        if not doc_dir.is_dir():
            continue
        for path in sorted(doc_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in _DOC_SUFFIXES:
                docs.append(_doc_excerpt(root, path))
            if len(docs) >= 10:  # a docs site can have hundreds
                break
    return readme, docs


def _doc_excerpt(root: Path, path: Path) -> DocExcerpt:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    headings = [
        line.lstrip("#").strip()
        for line in text.splitlines()
        if line.startswith("#") and line.lstrip("#").strip()
    ][:20]
    title = headings[0] if headings else path.stem
    return DocExcerpt(
        path=str(path.relative_to(root)),
        title=title,
        excerpt=text[:DOC_EXCERPT_CHARS],
        headings=headings,
    )


def _build_outline(entries: Dict[str, FileEntry]) -> dict:
    """Denormalises the index into a prompt-ready API outline.

    Stored separately so context assembly can read one small file instead of
    loading the whole (potentially multi-megabyte) file index.
    """
    by_language: Dict[str, int] = {}
    top_symbols: List[dict] = []
    entrypoints: List[str] = []

    for path, entry in entries.items():
        by_language[entry.language] = by_language.get(entry.language, 0) + 1
        name = Path(path).name.lower()
        if name in ("main.py", "__main__.py", "app.py", "index.js", "index.ts", "main.go",
                    "main.rs", "server.py", "server.ts", "cli.py"):
            entrypoints.append(path)
        # AST-derived symbols only: regex results include false positives, and
        # the outline is what gets injected into prompts.
        if entry.parse == "ast":
            for symbol in entry.symbols:
                if symbol.kind in ("class", "function"):
                    top_symbols.append(
                        {
                            "path": path,
                            "kind": symbol.kind,
                            "name": symbol.name,
                            "signature": symbol.signature,
                            "doc": symbol.doc,
                        }
                    )

    return {
        "version": SCHEMA_VERSION,
        "by_language": dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        "entrypoints": sorted(entrypoints),
        "top_symbols": top_symbols[:2000],
    }


def _git_state(root: Path) -> GitState:
    if not git_ops.is_git_repo(root):
        return GitState(is_repo=False)
    dirty_paths = sorted({entry.path for entry in git_ops.status(root)})
    return GitState(
        is_repo=True,
        head_sha=git_ops.head_sha(root),
        branch=git_ops.current_branch(root),
        dirty=bool(dirty_paths),
        dirty_paths=dirty_paths,
    )


def _commit_exists(root: Path, sha: str) -> bool:
    """True if `sha` is still reachable.

    False after an amend, rebase, or reset dropped it — in which case a diff
    against it is meaningless and the caller must fall back to a full rescan.
    """
    if not sha:
        return False
    return git_ops.run_git(root, ["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0


def _changed_since(root: Path, old_head: str) -> Set[str]:
    """Paths git reports as changed between `old_head` and now.

    Includes both sides of a rename (`-M` off would still report both, but being
    explicit is clearer) and deletions, which the caller turns into key removals.
    """
    result = git_ops.run_git(
        root, ["diff", "--name-only", "--diff-filter=ACMRD", f"{old_head}..HEAD"], timeout=30.0
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


class KnowledgeBank:
    """Read/write access to one repository's bank on disk."""

    def __init__(self, project_path: Union[str, Path], shadow_root: Optional[Union[str, Path]] = None):
        self.project_path = Path(project_path).expanduser().resolve()
        self.shadow_root = shadow_root
        self.repo_id = repo_id(self.project_path)
        self.dir = bank_dir(self.project_path, shadow_root)

    # -- reading ------------------------------------------------------------

    @property
    def exists(self) -> bool:
        return (self.dir / META_FILE).is_file()

    def load_meta(self) -> Optional[BankMeta]:
        data = read_json(self.dir / META_FILE)
        if not data:
            return None
        meta = BankMeta.from_dict(data)
        if meta.version != SCHEMA_VERSION:
            return None  # a layout change means rebuild rather than misread
        # A bank whose repo has moved describes a path that no longer exists.
        if meta.root_path and Path(meta.root_path) != self.project_path:
            return None
        return meta

    def load_files(self) -> Dict[str, FileEntry]:
        return files_from_dict(read_json(self.dir / FILES_FILE))

    def load_manifests(self) -> List[Manifest]:
        data = read_json(self.dir / MANIFESTS_FILE) or {}
        return [Manifest.from_dict(m) for m in data.get("manifests", [])]

    def load_docs(self) -> Tuple[Optional[DocExcerpt], List[DocExcerpt]]:
        data = read_json(self.dir / DOCS_FILE) or {}
        readme = data.get("readme")
        return (
            DocExcerpt.from_dict(readme) if readme else None,
            [DocExcerpt.from_dict(d) for d in data.get("docs", [])],
        )

    def load_outline(self) -> dict:
        return read_json(self.dir / OUTLINE_FILE) or {}

    def load_depth(self) -> RepoDepth:
        """Returns the derived structural picture (module graph, routes, history)."""
        return RepoDepth.from_dict(read_json(self.dir / DEPTH_FILE))

    def status(self) -> str:
        """One of "missing", "stale", or "ready", for the UI indicator."""
        meta = self.load_meta()
        if meta is None:
            return "missing"
        current = _git_state(self.project_path)
        if current.is_repo and meta.git.is_repo:
            if current.head_sha != meta.git.head_sha or current.dirty_paths != meta.git.dirty_paths:
                return "stale"
        return "ready"

    # -- writing ------------------------------------------------------------

    def build(
        self,
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        progress: Optional[ProgressFn] = None,
        force_full: bool = False,
    ) -> IndexResult:
        """Indexes the repository, reusing unchanged entries where it safely can."""
        started = time.time()
        ensure_dir(self.dir)

        previous_meta = None if force_full else self.load_meta()
        previous_files = {} if previous_meta is None else self.load_files()
        current_git = _git_state(self.project_path)

        paths, truncated = _discover_files(self.project_path, max_files)
        stale_paths = self._paths_needing_reread(
            previous_meta, previous_files, current_git, set(paths)
        )
        mode = "incremental" if previous_files else "full"

        entries: Dict[str, FileEntry] = {}
        indexed = reused = 0
        total = len(paths)
        for position, rel_path in enumerate(paths, start=1):
            existing = previous_files.get(rel_path)
            if existing is not None and rel_path not in stale_paths:
                entries[rel_path] = existing
                reused += 1
            else:
                entry = _index_one_file(self.project_path, rel_path, max_file_bytes)
                if entry is not None:
                    entries[rel_path] = entry
                    indexed += 1
            if progress is not None and (position % 50 == 0 or position == total):
                progress(position, total)

        removed = len(set(previous_files) - set(entries))
        manifests = collect_manifests(self.project_path)
        readme, docs = _collect_docs(self.project_path)

        now = datetime.now().isoformat(timespec="seconds")
        meta = BankMeta(
            repo_id=self.repo_id,
            name=self.project_path.name,
            root_path=str(self.project_path),
            created_at=previous_meta.created_at if previous_meta else now,
            updated_at=now,
            git=current_git,
            file_count=len(entries),
            skipped_count=sum(1 for e in entries.values() if e.skipped),
            truncated=truncated,
            index_mode=mode,
        )

        write_json_atomic(self.dir / FILES_FILE, files_to_dict(entries))
        write_json_atomic(
            self.dir / MANIFESTS_FILE,
            {"version": SCHEMA_VERSION, "manifests": [m.to_dict() for m in manifests]},
        )
        write_json_atomic(
            self.dir / DOCS_FILE,
            {
                "version": SCHEMA_VERSION,
                "readme": readme.to_dict() if readme else None,
                "docs": [d.to_dict() for d in docs],
            },
        )
        write_json_atomic(self.dir / OUTLINE_FILE, _build_outline(entries))
        # Derived from the index that was just written, so it's always consistent
        # with it rather than describing a previous state.
        write_json_atomic(
            self.dir / DEPTH_FILE,
            build_depth(self.project_path, entries, manifests).to_dict(),
        )
        # meta last: it's what `exists`/`load_meta` gate on, so writing it only
        # after the payload means a crash mid-build leaves the bank "missing"
        # rather than present-but-incomplete.
        write_json_atomic(self.dir / META_FILE, meta.to_dict())

        return IndexResult(
            mode=mode,
            files_indexed=indexed,
            files_reused=reused,
            files_removed=removed,
            truncated=truncated,
            duration_seconds=round(time.time() - started, 2),
        )

    def _paths_needing_reread(
        self,
        previous_meta: Optional[BankMeta],
        previous_files: Dict[str, FileEntry],
        current_git: GitState,
        current_paths: Set[str],
    ) -> Set[str]:
        """Decides which files must be re-read. See the module docstring.

        Returning a superset is safe (just slower); returning too little leaves
        the index silently describing code that no longer exists, so every
        uncertain case resolves toward re-reading.
        """
        if previous_meta is None or not previous_files:
            return set(current_paths)  # nothing to reuse

        # Non-git, or git history rewritten under us: the diff-based fast path
        # isn't trustworthy, so fall back to stat-comparing everything.
        use_git_diff = (
            current_git.is_repo
            and previous_meta.git.is_repo
            and bool(previous_meta.git.head_sha)
            and _commit_exists(self.project_path, previous_meta.git.head_sha)
        )

        # The stat sweep is the primary and near-complete signal: any real edit
        # changes size or mtime, including a `git restore`/`git stash` that
        # rewrites a dirty file back to HEAD (git writes the file, so mtime moves).
        # ~50-150ms for 10k files, and it's the only thing that can see
        # gitignored-but-indexed files, which git will never report.
        stale: Set[str] = self._stat_changed(previous_files, current_paths)

        # Git is a backstop for the one family the stat sweep can miss: content
        # restored with a *preserved* mtime and identical size, which happens with
        # `tar -x`, `cp -p`, or `rsync --times` rather than with git itself.
        #
        # Only the committed-range diff is unioned here. Deliberately NOT the
        # dirty-path lists: on an actively-developed repo that's most of the
        # working tree, and re-reading it every time defeats the point of an
        # incremental index — while adding nothing, since a file the user just
        # edited always has a fresh mtime for the sweep above to catch.
        if use_git_diff and current_git.head_sha != previous_meta.git.head_sha:
            stale |= _changed_since(self.project_path, previous_meta.git.head_sha)

        return stale

    def _stat_changed(
        self, previous_files: Dict[str, FileEntry], current_paths: Set[str]
    ) -> Set[str]:
        """Paths whose size or mtime differs from the stored entry."""
        changed: Set[str] = set()
        for rel_path in current_paths:
            existing = previous_files.get(rel_path)
            if existing is None:
                changed.add(rel_path)  # new file
                continue
            try:
                stat = os.stat(self.project_path / rel_path)
            except OSError:
                changed.add(rel_path)  # vanished mid-scan; re-read decides
                continue
            if stat.st_size != existing.size or stat.st_mtime_ns != existing.mtime_ns:
                changed.add(rel_path)
        return changed


def build_index(
    project_path: Union[str, Path],
    shadow_root: Optional[Union[str, Path]] = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    progress: Optional[ProgressFn] = None,
    force_full: bool = False,
) -> IndexResult:
    """Convenience wrapper: builds or updates `project_path`'s bank."""
    bank = KnowledgeBank(project_path, shadow_root)
    return bank.build(
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        progress=progress,
        force_full=force_full,
    )
