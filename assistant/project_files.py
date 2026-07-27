"""Safe, bounded filesystem access to a Coding Agent project's folder.

Used by `assistant/coding_agent.py` to gather context for a plan and to
write approved changes. Every read/write is confined to the project root —
see `_resolve_within_root` — since a plan's file list ultimately comes from
an LLM completion and must never be trusted to stay inside the project on
its own.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

DEFAULT_IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", "coverage", ".turbo", ".cache", ".pytest_cache", ".mypy_cache",
    "egg-info", ".idea", ".vscode",
}

# Skip binary/asset files — not useful as text context and often huge.
_IGNORED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".tar", ".gz", ".jar", ".pdf",
    ".mp3", ".mp4", ".mov", ".avi",
    ".pyc", ".so", ".dylib", ".dll",
    ".lock",
}

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "i", "me", "my",
    "on", "in", "at", "to", "of", "for", "and", "or", "that", "this", "what", "when",
    "who", "how", "about", "with", "please", "can", "you", "it", "fix", "issue",
}


# Editor opens read the whole file (unlike prompt context, which is truncated to
# a few KB), so this only exists to refuse pathologically large files rather than
# to trim them — see read_text_file, which raises instead of truncating.
MAX_EDITABLE_BYTES = 2_000_000

# How much of a file to sniff for NUL bytes before deciding it's binary.
_BINARY_SNIFF_BYTES = 8192


class ProjectFileError(RuntimeError):
    """Raised when a file path would resolve outside the project root."""


class FileConflictError(ProjectFileError):
    """Raised when a file changed on disk since the caller last read it.

    Signals a lost-update: the editor's buffer is based on content that is no
    longer what's on disk (another tool, a git checkout, or another editor
    wrote to it), so overwriting would silently discard that other change.
    """


class FileTooLargeError(ProjectFileError):
    """Raised when a file is too large to open in the editor."""


class BinaryFileError(ProjectFileError):
    """Raised when a file isn't decodable text and so can't be edited."""


def _resolve_within_root(root: Path, rel_path: str) -> Path:
    root = root.resolve()
    resolved = (root / rel_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ProjectFileError(f"Refusing to access path outside the project: {rel_path!r}")
    return resolved


def resolve_in_project(root: Path, rel_path: str) -> Path:
    """Returns the absolute path of `rel_path`, guaranteed inside `root`.

    The public form of `_resolve_within_root`, for callers that need the real
    path to do something this module doesn't wrap — creating a directory,
    renaming, deleting, revealing in Finder (see `gui/ide/file_tree.py`). Going
    through this rather than joining paths by hand is what keeps those
    operations from escaping the project via a `..` or a symlink.
    """
    return _resolve_within_root(Path(root), rel_path)


def _keywords(text: str) -> List[str]:
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def list_files(root: Path, max_files: int = 500) -> List[Path]:
    """Returns project-relative file paths, skipping ignored dirs/extensions.

    A bounded, materialized view of `iter_files` — see there for the walk
    itself. Ordering differs subtly from a flat sort: entries come out
    directory-by-directory (each internally sorted) rather than globally
    sorted, which only matters if a caller depends on exact ordering across
    directory boundaries. None do; prompts just need a stable file list.
    """
    return list(iter_files(root, max_files=max_files))


def build_file_tree_text(root: Path, max_files: int = 500) -> str:
    """Indented file-tree text for prompt context."""
    return "\n".join(str(p) for p in list_files(root, max_files=max_files))


def find_relevant_files(
    root: Path, issue_text: str, *, max_files: int = 6, max_bytes_per_file: int = 6000
) -> List[Tuple[str, str]]:
    """Returns up to `max_files` (relative_path, truncated_content) pairs,
    ranked by how many `issue_text` keywords appear in the file's content."""
    root = Path(root).resolve()
    keywords = _keywords(issue_text)
    if not keywords:
        return []

    scored: List[Tuple[int, str, str]] = []
    for rel_path in list_files(root):
        content = read_file(root, str(rel_path), max_bytes=max_bytes_per_file)
        if content is None:
            continue
        content_lower = content.lower()
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scored.append((score, str(rel_path), content))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [(rel_path, content) for _, rel_path, content in scored[:max_files]]


def read_file(root: Path, rel_path: str, max_bytes: int = 6000) -> str | None:
    """Returns up to `max_bytes` of `rel_path`'s text content, or None if it
    doesn't exist / isn't decodable as text / would escape the project root."""
    try:
        resolved = _resolve_within_root(Path(root), rel_path)
    except ProjectFileError:
        return None
    if not resolved.is_file():
        return None
    try:
        with open(resolved, "r", encoding="utf-8", errors="strict") as f:
            return f.read(max_bytes)
    except (UnicodeDecodeError, OSError):
        return None


def write_file(root: Path, rel_path: str, content: str) -> None:
    """Writes `content` to `rel_path`, creating parent directories as needed.

    Raises ProjectFileError rather than writing anything if `rel_path` would
    resolve outside the project root.

    Non-atomic and unconditional — kept as-is for `coding_agent.apply_plan`,
    which writes to a fresh git branch where a torn write is recoverable. The
    editor uses `atomic_write_file` instead; see its docstring.
    """
    resolved = _resolve_within_root(Path(root), rel_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)


# -- editor-facing helpers -------------------------------------------------
#
# The three functions above (`list_files`, `read_file`, `write_file`) exist to
# build LLM prompts: they cap sizes aggressively, silence errors by returning
# None, and never need to write safely because `apply_plan` works on a throwaway
# git branch. An editor needs the opposite of all three — whole files, errors
# explained to the user, and writes that can't lose data. Hence these.


def list_dir(root: Path, rel_dir: str = ".") -> List[Tuple[str, bool]]:
    """Lists one directory level as (name, is_dir) pairs, directories first.

    Shallow, unlike `list_files`, so a file tree can populate lazily per
    expanded node instead of walking (and capping) the whole project up front.
    Applies the same `DEFAULT_IGNORED_DIRS` / `_IGNORED_SUFFIXES` filtering, so
    `node_modules` and friends never show up in the tree.
    """
    resolved = _resolve_within_root(Path(root), rel_dir)
    if not resolved.is_dir():
        raise ProjectFileError(f"Not a directory: {rel_dir!r}")

    dirs: List[Tuple[str, bool]] = []
    files: List[Tuple[str, bool]] = []
    for entry in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            if entry.name in DEFAULT_IGNORED_DIRS:
                continue
            dirs.append((entry.name, True))
        elif entry.is_file():
            if entry.suffix.lower() in _IGNORED_SUFFIXES:
                continue
            files.append((entry.name, False))
    return dirs + files


def read_text_file(root: Path, rel_path: str, max_bytes: int = MAX_EDITABLE_BYTES) -> Tuple[str, float]:
    """Reads a whole file for editing, returning (text, mtime).

    Deliberately unlike `read_file`, which caps at 6000 bytes and returns None
    on any problem. Truncating here then saving would silently delete the rest
    of the user's file, so this reads in full and raises a specific error the UI
    can explain instead:

    - `FileTooLargeError` over `max_bytes`
    - `BinaryFileError` if it sniffs a NUL byte or won't decode as UTF-8
    - `ProjectFileError` if missing or outside the project root

    The returned mtime is what to hand back to `atomic_write_file` as
    `expected_mtime` to detect a concurrent change on save.
    """
    resolved = _resolve_within_root(Path(root), rel_path)
    if not resolved.is_file():
        raise ProjectFileError(f"No such file: {rel_path!r}")

    stat = resolved.stat()
    if stat.st_size > max_bytes:
        raise FileTooLargeError(
            f"{rel_path} is {stat.st_size:,} bytes — too large to open (limit {max_bytes:,})."
        )

    # A NUL byte in the first few KB is the cheap, reliable binary tell. Relying
    # on UnicodeDecodeError alone misses UTF-16 and anything that happens to be
    # latin-1-decodable, which would then render as mojibake and be saved back
    # corrupted.
    with open(resolved, "rb") as f:
        if b"\x00" in f.read(_BINARY_SNIFF_BYTES):
            raise BinaryFileError(f"{rel_path} looks like a binary file — not editable as text.")

    try:
        text = resolved.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise BinaryFileError(f"Could not read {rel_path} as UTF-8 text: {exc}") from exc
    return text, stat.st_mtime


def atomic_write_file(
    root: Path, rel_path: str, content: str, expected_mtime: Optional[float] = None
) -> float:
    """Writes `content` atomically, returning the new mtime.

    Two protections `write_file` doesn't have, both mandatory for editor saves:

    1. Atomicity — writes to a temp file in the *same directory* (so `os.replace`
       stays on one filesystem and is therefore atomic) and fsyncs before the
       rename. A crash or full disk mid-write leaves the original intact rather
       than truncated.
    2. Lost-update detection — if `expected_mtime` is given and the file's mtime
       no longer matches, raises `FileConflictError` without writing, so a change
       made outside the editor isn't silently clobbered.

    Passing `expected_mtime=None` means "create or overwrite unconditionally",
    which is correct for a brand-new file but not for saving one that was read.
    """
    resolved = _resolve_within_root(Path(root), rel_path)

    if expected_mtime is not None:
        if not resolved.is_file():
            raise FileConflictError(f"{rel_path} no longer exists on disk — it may have been deleted.")
        actual = resolved.stat().st_mtime
        if actual != expected_mtime:
            raise FileConflictError(
                f"{rel_path} changed on disk since it was opened. Reload it, or overwrite to "
                "discard the other change."
            )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = resolved.stat().st_mode if resolved.is_file() else None

    # delete=False because we rename it into place; the finally block cleans up
    # only if the rename never happened.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(resolved.parent), prefix=f".{resolved.name}.", suffix=".tmp",
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        if existing_mode is not None:
            shutil.copymode(str(resolved), str(tmp_path))
        os.replace(str(tmp_path), str(resolved))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return resolved.stat().st_mtime


def iter_files(root: Path, max_files: Optional[int] = None) -> Iterator[Path]:
    """Yields project-relative file paths, skipping ignored dirs/extensions.

    The generator `list_files` wraps. Exists because indexing a whole repo for
    the Knowledge Bank can't use `list_files`' 500-file cap, and shouldn't have
    to materialize a 20k-element list before starting on the first file.

    Prunes ignored directories during the walk (`os.walk` with an in-place
    `dirnames` edit) rather than filtering afterwards, so it never descends into
    `node_modules` at all — `rglob("*")` would walk every file inside it first.
    """
    root = Path(root).resolve()
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_IGNORED_DIRS)
        current = Path(dirpath)
        for name in sorted(filenames):
            if Path(name).suffix.lower() in _IGNORED_SUFFIXES:
                continue
            yield (current / name).relative_to(root)
            count += 1
            if max_files is not None and count >= max_files:
                return
