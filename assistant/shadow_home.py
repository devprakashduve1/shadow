"""Locates Shadow's per-repository private data under ~/Desktop/.shadow/.

Everything Shadow stores *about* a repository — edit backups, and later the
Knowledge Bank index — lives outside that repository, so opening a project never
adds untracked files to it and nothing here can end up in a commit by accident.

Layout::

    ~/Desktop/.shadow/
        registry.json                    # repo_id -> {name, root_path, ...}
        <repo-id>/
            backups/
                journal.jsonl            # one record per applied AI edit
                <timestamp>-<sha>-<flattened-path>
            ...                          # Knowledge Bank files land here later

`repo_id` is the interesting part — see `repo_id()` for why it isn't just the
folder name.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Union

DEFAULT_SHADOW_HOME = Path("~/Desktop/.shadow")

# Anything not safe/predictable in a directory name gets collapsed to a dash.
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Enough to make accidental collisions negligible while keeping the directory
# name readable; this is not a security boundary.
_PATH_HASH_CHARS = 8


def shadow_home(root: Optional[Union[str, Path]] = None) -> Path:
    """Returns the ~/Desktop/.shadow root (or an override, for tests)."""
    return Path(root or DEFAULT_SHADOW_HOME).expanduser()


def _sanitize_name(name: str) -> str:
    cleaned = _UNSAFE_NAME_RE.sub("-", name).strip("-.")
    # A repo at "/" or named only of punctuation would otherwise produce "".
    return cleaned or "repo"


def repo_id(project_path: Union[str, Path]) -> str:
    """Returns a stable, collision-free directory name for a repository.

    The folder's basename alone is not usable: plenty of people have several
    repositories called `web`, `api`, or `frontend`, and they would all share one
    Knowledge Bank and one backup directory — silently mixing unrelated projects.

    Appending a hash of the *absolute* path fixes that while keeping the name
    recognizable (`web-3f2a1b9c`). Being path-derived it's also stable across
    runs with no registry lookup needed, and it changes if the repo moves, which
    is the correct trigger for a rebuild.
    """
    resolved = Path(project_path).expanduser().resolve()
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:_PATH_HASH_CHARS]
    return f"{_sanitize_name(resolved.name)}-{digest}"


def bank_dir(project_path: Union[str, Path], root: Optional[Union[str, Path]] = None) -> Path:
    """Returns (without creating) this repository's private data directory."""
    return shadow_home(root) / repo_id(project_path)


def backups_dir(project_path: Union[str, Path], root: Optional[Union[str, Path]] = None) -> Path:
    """Returns (without creating) where pre-edit file backups are kept."""
    return bank_dir(project_path, root) / "backups"


def journal_path(project_path: Union[str, Path], root: Optional[Union[str, Path]] = None) -> Path:
    """Returns the append-only log of applied AI edits."""
    return backups_dir(project_path, root) / "journal.jsonl"


def ensure_dir(path: Path) -> Path:
    """Creates `path` (and parents) if needed and returns it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def flatten_rel_path(rel_path: str) -> str:
    """Turns "src/app/main.py" into "src__app__main.py" for a flat backup dir.

    Keeps backups in one directory per repo rather than mirroring the project's
    tree, so listing them is one `iterdir()` and a partially-deleted source tree
    can't strand backups in empty subdirectories.
    """
    return _sanitize_name(rel_path.replace(os.sep, "__").replace("/", "__"))
