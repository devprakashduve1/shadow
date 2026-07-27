"""Git operations for the Code tab's git panel and branch switching.

Plain subprocess wrappers, deliberately free of Qt so they stay unit-testable
against real repositories (see tests/test_git_ops.py). Every call is
synchronous and can block for as long as git takes, so GUI callers must run
these on a worker thread — see `gui/ide/workers.py`.

`run_git` here is the same helper `assistant/coding_agent.py` uses; it lives in
this module now so both the batch agent and the interactive panel share one
definition of how git is invoked.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

# git's porcelain status codes, mapped to something displayable.
_STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "conflicted",
    "?": "untracked",
    "!": "ignored",
    " ": "",
}


class GitError(RuntimeError):
    """Raised when a git command fails."""


@dataclass
class FileStatus:
    """One entry from `git status`.

    `index_status` is the staged column, `worktree_status` the unstaged one —
    a file can be both (staged edit plus further unstaged edits), which is why
    they're kept separate rather than collapsed into a single state.
    """

    path: str
    index_status: str
    worktree_status: str
    orig_path: Optional[str] = None  # set for renames/copies

    @property
    def is_staged(self) -> bool:
        return self.index_status not in (" ", "?")

    @property
    def is_untracked(self) -> bool:
        return self.index_status == "?"

    @property
    def label(self) -> str:
        primary = self.index_status if self.is_staged else self.worktree_status
        return _STATUS_LABELS.get(primary, primary)


def run_git(
    project_path: Union[str, Path], args: List[str], timeout: float = 10.0
) -> subprocess.CompletedProcess:
    """Runs one git command in `project_path` and returns the completed process.

    Never raises on a nonzero exit — callers decide whether a failure is fatal
    (a failed `commit` is) or expected (`rev-parse` on a non-repo is how
    `is_git_repo` answers). Raises only on timeout or a missing git binary.
    """
    return subprocess.run(
        ["git", *args], cwd=str(project_path), capture_output=True, text=True, timeout=timeout
    )


def _checked(project_path: Union[str, Path], args: List[str], what: str, timeout: float = 10.0) -> str:
    """Runs a git command that must succeed, returning its stdout."""
    result = run_git(project_path, args, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(f"{what} failed: {detail}")
    return result.stdout


def is_git_repo(project_path: Union[str, Path]) -> bool:
    """True if `project_path` is inside a git working tree.

    Uses `rev-parse` rather than checking for a `.git` directory: in a git
    worktree or a submodule, `.git` is a *file* containing a gitdir pointer,
    so a directory check reports False for perfectly valid repositories.
    """
    if not Path(project_path).is_dir():
        return False
    try:
        return run_git(project_path, ["rev-parse", "--git-dir"]).returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def current_branch(project_path: Union[str, Path]) -> str:
    """Returns the checked-out branch name, or "" when in detached HEAD."""
    result = run_git(project_path, ["symbolic-ref", "--short", "-q", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else ""


def head_sha(project_path: Union[str, Path]) -> str:
    """Returns the full HEAD commit sha, or "" in a repo with no commits yet."""
    result = run_git(project_path, ["rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else ""


def list_branches(project_path: Union[str, Path]) -> List[str]:
    """Returns local branch names, sorted by most recent commit first."""
    out = _checked(
        project_path,
        ["for-each-ref", "--sort=-committerdate", "--format=%(refname:short)", "refs/heads"],
        "Listing branches",
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def working_tree_clean(project_path: Union[str, Path]) -> bool:
    """True if there is nothing to commit (no staged, unstaged, or untracked changes)."""
    result = run_git(project_path, ["status", "--porcelain"])
    return result.returncode == 0 and result.stdout.strip() == ""


def status(project_path: Union[str, Path]) -> List[FileStatus]:
    """Returns the working tree's per-file status.

    Parses `--porcelain=v1 -z`. The `-z` matters: the human-readable form
    quotes and escapes paths containing spaces or non-ASCII, and renders
    renames as `old -> new` inside a single field, both of which are ambiguous
    to parse. With `-z`, entries are NUL-terminated and a rename's original
    path is its own following NUL-terminated field.
    """
    out = _checked(project_path, ["status", "--porcelain=v1", "-z"], "Reading status")

    entries: List[FileStatus] = []
    # Trailing NUL yields a final empty field; drop it rather than parsing it.
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        field = fields[i]
        if not field:
            i += 1
            continue
        # "XY <path>" — two status chars, a space, then the path.
        index_status, worktree_status, path = field[0], field[1], field[3:]
        orig_path = None
        if index_status in ("R", "C"):
            # Rename/copy: the source path is the next NUL-separated field.
            i += 1
            orig_path = fields[i] if i < len(fields) else None
        entries.append(
            FileStatus(
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                orig_path=orig_path,
            )
        )
        i += 1
    return entries


def diff_text(project_path: Union[str, Path], rel_path: Optional[str] = None, staged: bool = False) -> str:
    """Returns a unified diff for one file, or the whole tree if `rel_path` is None."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    if rel_path is not None:
        args += ["--", rel_path]
    return _checked(project_path, args, "Reading diff", timeout=30.0)


def stage(project_path: Union[str, Path], rel_paths: List[str]) -> None:
    if not rel_paths:
        return
    _checked(project_path, ["add", "--", *rel_paths], "Staging")


def unstage(project_path: Union[str, Path], rel_paths: List[str]) -> None:
    if not rel_paths:
        return
    _checked(project_path, ["restore", "--staged", "--", *rel_paths], "Unstaging")


def discard(project_path: Union[str, Path], rel_paths: List[str]) -> None:
    """Throws away unstaged changes to `rel_paths` — destructive and unrecoverable."""
    if not rel_paths:
        return
    _checked(project_path, ["restore", "--", *rel_paths], "Discarding changes")


def commit(project_path: Union[str, Path], message: str) -> str:
    """Commits what is already staged and returns the new commit sha.

    Never passes `-a`: staging is an explicit user action in the git panel, and
    `-a` would sweep in unrelated modified files the user didn't select.
    """
    if not message.strip():
        raise GitError("Commit message is empty.")
    _checked(project_path, ["commit", "-m", message], "Commit", timeout=30.0)
    return head_sha(project_path)


def checkout(project_path: Union[str, Path], branch: str) -> None:
    """Switches to an existing branch.

    Refuses when the working tree is dirty. git itself would sometimes allow
    this (carrying changes across), but in an editor that silently rewrites
    files under open buffers, so the stricter rule is the safer one.
    """
    if not working_tree_clean(project_path):
        raise GitError(
            "This repository has uncommitted changes. Commit, stash, or discard them before "
            "switching branches — switching would rewrite files you have open."
        )
    _checked(project_path, ["checkout", branch], f"Switching to {branch!r}", timeout=30.0)


def create_branch(project_path: Union[str, Path], name: str, base: Optional[str] = None) -> None:
    """Creates a branch and switches to it."""
    if not name.strip():
        raise GitError("Branch name is empty.")
    if not working_tree_clean(project_path):
        raise GitError(
            "This repository has uncommitted changes. Commit, stash, or discard them before "
            "creating a branch."
        )
    args = ["checkout", "-b", name]
    if base:
        args.append(base)
    _checked(project_path, args, f"Creating branch {name!r}", timeout=30.0)


@dataclass
class Commit:
    """One entry from `git log`."""

    sha: str
    short_sha: str
    author: str
    when: str  # relative, e.g. "3 hours ago"
    subject: str


# Field separator for log parsing. A literal control character rather than a
# printable one, because commit subjects and author names can contain anything.
_LOG_SEPARATOR = "\x1f"


def log(project_path: Union[str, Path], limit: int = 30) -> List[Commit]:
    """Returns recent commits, newest first."""
    fields = _LOG_SEPARATOR.join(["%H", "%h", "%an", "%ar", "%s"])
    result = run_git(
        project_path, ["log", f"-{limit}", f"--format={fields}"], timeout=15.0
    )
    if result.returncode != 0:
        return []  # no commits yet, or not a repo
    commits = []
    for line in result.stdout.splitlines():
        parts = line.split(_LOG_SEPARATOR)
        if len(parts) == 5:
            commits.append(
                Commit(sha=parts[0], short_sha=parts[1], author=parts[2], when=parts[3], subject=parts[4])
            )
    return commits


def stash(project_path: Union[str, Path], message: str = "", include_untracked: bool = True) -> None:
    """Stashes the working tree.

    Includes untracked files by default: the common reason to stash here is to
    unblock a branch switch, and leaving untracked files behind wouldn't achieve
    that.
    """
    args = ["stash", "push"]
    if include_untracked:
        args.append("--include-untracked")
    if message.strip():
        args += ["-m", message.strip()]
    result = run_git(project_path, args, timeout=30.0)
    if result.returncode != 0:
        raise GitError(f"Stash failed: {(result.stderr or result.stdout).strip()}")
    if "No local changes" in result.stdout:
        raise GitError("Nothing to stash — the working tree is already clean.")


def stash_list(project_path: Union[str, Path]) -> List[str]:
    result = run_git(project_path, ["stash", "list"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def stash_pop(project_path: Union[str, Path]) -> None:
    """Restores the most recent stash and drops it."""
    result = run_git(project_path, ["stash", "pop"], timeout=30.0)
    if result.returncode != 0:
        raise GitError(f"Could not pop the stash: {(result.stderr or result.stdout).strip()}")


def file_at_head(project_path: Union[str, Path], rel_path: str) -> str:
    """Returns a file's committed content, or "" if it isn't in HEAD.

    Used to show a diff for a file the editor has open but that git can't diff
    normally (e.g. comparing against a staged version).
    """
    result = run_git(project_path, ["show", f"HEAD:{rel_path}"], timeout=15.0)
    return result.stdout if result.returncode == 0 else ""


def tracked_files(project_path: Union[str, Path]) -> List[str]:
    """Returns files git knows about, honouring .gitignore.

    The Knowledge Bank indexer prefers this over walking the filesystem: it
    excludes build output and vendored dependencies for free, using the
    project's own ignore rules rather than this codebase's guess at them
    (`DEFAULT_IGNORED_DIRS`). Falls back to an empty list for a non-repo, where
    callers should walk with `project_files.iter_files` instead.
    """
    result = run_git(project_path, ["ls-files", "-z", "--cached", "--other", "--exclude-standard"],
                     timeout=30.0)
    if result.returncode != 0:
        return []
    return [p for p in result.stdout.split("\0") if p]
