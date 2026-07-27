"""Tests for assistant/git_ops.py against real git repositories.

Follows the same approach as tests/test_coding_agent.py — real `git` in a
tmp_path rather than mocks, since the whole point of this module is that its
subprocess invocations are correct.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assistant.git_ops import (
    GitError,
    file_at_head,
    log,
    stash,
    stash_list,
    stash_pop,
    checkout,
    commit,
    create_branch,
    current_branch,
    diff_text,
    discard,
    head_sha,
    is_git_repo,
    list_branches,
    stage,
    status,
    tracked_files,
    unstage,
    working_tree_clean,
)


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _commit_all(path: Path, message: str) -> None:
    _git(path, "add", "-A")
    _git(path, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    _init_repo(path)
    (path / "app.py").write_text("print('hello')\n")
    _commit_all(path, "initial")
    return path


# -- is_git_repo ------------------------------------------------------------


def test_is_git_repo_true_for_a_repo(repo: Path) -> None:
    assert is_git_repo(repo) is True


def test_is_git_repo_false_for_a_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(plain) is False


def test_is_git_repo_false_for_a_missing_directory(tmp_path: Path) -> None:
    assert is_git_repo(tmp_path / "nope") is False


def test_is_git_repo_true_for_a_worktree(repo: Path, tmp_path: Path) -> None:
    """The case the old `.git`-is-a-directory check got wrong.

    In a linked worktree, `.git` is a *file* holding a gitdir pointer, so a
    directory check reports False and the Coding Agent would refuse to work in
    a perfectly valid repository.
    """
    worktree = tmp_path / "wt"
    result = _git(repo, "worktree", "add", str(worktree), "-b", "wt-branch")
    assert result.returncode == 0, result.stderr

    assert (worktree / ".git").is_file()  # precondition: a file, not a dir
    assert (worktree / ".git").is_dir() is False
    assert is_git_repo(worktree) is True


# -- branches ---------------------------------------------------------------


def test_current_branch_returns_the_checked_out_branch(repo: Path) -> None:
    assert current_branch(repo) in ("main", "master")


def test_current_branch_is_empty_when_detached(repo: Path) -> None:
    _git(repo, "checkout", "--detach", "HEAD")
    assert current_branch(repo) == ""


def test_list_branches_includes_created_branches(repo: Path) -> None:
    create_branch(repo, "feature/x")
    assert "feature/x" in list_branches(repo)


def test_create_branch_switches_to_it(repo: Path) -> None:
    create_branch(repo, "feature/y")
    assert current_branch(repo) == "feature/y"


def test_create_branch_rejects_an_empty_name(repo: Path) -> None:
    with pytest.raises(GitError):
        create_branch(repo, "   ")


def test_create_branch_refuses_when_dirty(repo: Path) -> None:
    (repo / "app.py").write_text("modified\n")
    with pytest.raises(GitError, match="uncommitted changes"):
        create_branch(repo, "feature/z")


def test_checkout_switches_branches(repo: Path) -> None:
    original = current_branch(repo)
    create_branch(repo, "feature/a")
    checkout(repo, original)
    assert current_branch(repo) == original


def test_checkout_refuses_when_dirty(repo: Path) -> None:
    """Switching would rewrite files under the editor's open buffers."""
    create_branch(repo, "feature/b")
    original_branch = "main" if "main" in list_branches(repo) else "master"
    (repo / "app.py").write_text("work in progress\n")

    with pytest.raises(GitError, match="uncommitted changes"):
        checkout(repo, original_branch)
    assert (repo / "app.py").read_text() == "work in progress\n"  # untouched


# -- status -----------------------------------------------------------------


def test_working_tree_clean_reflects_state(repo: Path) -> None:
    assert working_tree_clean(repo) is True
    (repo / "app.py").write_text("changed\n")
    assert working_tree_clean(repo) is False


def test_status_reports_modified_and_untracked(repo: Path) -> None:
    (repo / "app.py").write_text("changed\n")
    (repo / "new.py").write_text("new\n")

    by_path = {entry.path: entry for entry in status(repo)}

    assert by_path["app.py"].worktree_status == "M"
    assert by_path["app.py"].is_staged is False
    assert by_path["new.py"].is_untracked is True


def test_status_reports_staged_separately_from_unstaged(repo: Path) -> None:
    (repo / "app.py").write_text("staged change\n")
    stage(repo, ["app.py"])
    (repo / "app.py").write_text("and an unstaged one\n")

    entry = {e.path: e for e in status(repo)}["app.py"]

    assert entry.index_status == "M"
    assert entry.worktree_status == "M"
    assert entry.is_staged is True


def test_status_handles_paths_with_spaces(repo: Path) -> None:
    """The reason for `-z`: the plain porcelain form quotes such paths."""
    (repo / "my file.py").write_text("x\n")

    assert "my file.py" in {entry.path for entry in status(repo)}


def test_status_handles_renames(repo: Path) -> None:
    _git(repo, "mv", "app.py", "renamed.py")

    entry = {e.path: e for e in status(repo)}["renamed.py"]

    assert entry.index_status == "R"
    assert entry.orig_path == "app.py"


def test_status_is_empty_for_a_clean_repo(repo: Path) -> None:
    assert status(repo) == []


# -- staging / commit -------------------------------------------------------


def test_stage_then_unstage_round_trips(repo: Path) -> None:
    (repo / "app.py").write_text("changed\n")

    stage(repo, ["app.py"])
    assert {e.path: e for e in status(repo)}["app.py"].is_staged is True

    unstage(repo, ["app.py"])
    assert {e.path: e for e in status(repo)}["app.py"].is_staged is False


def test_stage_with_no_paths_is_a_noop(repo: Path) -> None:
    stage(repo, [])
    assert working_tree_clean(repo) is True


def test_commit_only_includes_staged_changes(repo: Path) -> None:
    """Guards the deliberate absence of `-a`: an unstaged file must not ride along."""
    (repo / "app.py").write_text("staged\n")
    (repo / "other.py").write_text("unstaged\n")
    stage(repo, ["app.py"])

    commit(repo, "only app.py")

    remaining = {entry.path for entry in status(repo)}
    assert "other.py" in remaining  # still uncommitted


def test_commit_returns_the_new_sha(repo: Path) -> None:
    before = head_sha(repo)
    (repo / "app.py").write_text("changed\n")
    stage(repo, ["app.py"])

    after = commit(repo, "a change")

    assert after != before
    assert after == head_sha(repo)


def test_commit_rejects_an_empty_message(repo: Path) -> None:
    (repo / "app.py").write_text("changed\n")
    stage(repo, ["app.py"])

    with pytest.raises(GitError):
        commit(repo, "  ")


# -- diff / discard ---------------------------------------------------------


def test_diff_text_shows_unstaged_changes(repo: Path) -> None:
    (repo / "app.py").write_text("print('goodbye')\n")

    diff = diff_text(repo, "app.py")

    assert "-print('hello')" in diff
    assert "+print('goodbye')" in diff


def test_diff_text_staged_requires_the_cached_flag(repo: Path) -> None:
    (repo / "app.py").write_text("print('goodbye')\n")
    stage(repo, ["app.py"])

    assert diff_text(repo, "app.py", staged=False) == ""
    assert "+print('goodbye')" in diff_text(repo, "app.py", staged=True)


def test_discard_reverts_a_file(repo: Path) -> None:
    (repo / "app.py").write_text("oops\n")

    discard(repo, ["app.py"])

    assert (repo / "app.py").read_text() == "print('hello')\n"


# -- tracked_files ----------------------------------------------------------


def test_tracked_files_honours_gitignore(repo: Path) -> None:
    (repo / ".gitignore").write_text("build/\n*.log\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.js").write_text("x")
    (repo / "debug.log").write_text("x")
    (repo / "src.py").write_text("x")

    found = set(tracked_files(repo))

    assert "src.py" in found
    assert "app.py" in found
    assert "build/out.js" not in found
    assert "debug.log" not in found


def test_tracked_files_empty_for_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert tracked_files(plain) == []


# -- log / stash / file_at_head ---------------------------------------------


def test_log_returns_commits_newest_first(repo: Path) -> None:
    (repo / "app.py").write_text("second\n")
    _commit_all(repo, "second commit")

    commits = log(repo)

    assert [c.subject for c in commits] == ["second commit", "initial"]
    assert commits[0].author == "Test"
    assert commits[0].short_sha and commits[0].sha.startswith(commits[0].short_sha)


def test_log_respects_the_limit(repo: Path) -> None:
    for i in range(5):
        (repo / "app.py").write_text(f"v{i}\n")
        _commit_all(repo, f"commit {i}")

    assert len(log(repo, limit=3)) == 3


def test_log_handles_subjects_with_separators(repo: Path) -> None:
    """Subjects can contain anything, so the field separator must be exotic."""
    (repo / "app.py").write_text("x\n")
    _commit_all(repo, "fix: a | b, c\tand more")

    assert log(repo)[0].subject == "fix: a | b, c\tand more"


def test_log_empty_for_a_repo_with_no_commits(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    _init_repo(fresh)
    assert log(fresh) == []


def test_log_empty_for_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert log(plain) == []


def test_stash_includes_untracked_files(repo: Path) -> None:
    """The usual reason to stash here is to unblock a branch switch, which
    leftover untracked files would not achieve."""
    (repo / "app.py").write_text("modified\n")
    (repo / "brand_new.py").write_text("untracked\n")

    stash(repo)

    assert working_tree_clean(repo) is True
    assert not (repo / "brand_new.py").exists()


def test_stash_then_pop_restores_everything(repo: Path) -> None:
    (repo / "app.py").write_text("modified\n")
    (repo / "brand_new.py").write_text("untracked\n")

    stash(repo)
    stash_pop(repo)

    assert (repo / "app.py").read_text() == "modified\n"
    assert (repo / "brand_new.py").read_text() == "untracked\n"


def test_stash_list_reports_entries(repo: Path) -> None:
    (repo / "app.py").write_text("modified\n")
    stash(repo, message="wip work")

    entries = stash_list(repo)

    assert len(entries) == 1
    assert "wip work" in entries[0]


def test_stash_on_a_clean_tree_raises(repo: Path) -> None:
    with pytest.raises(GitError, match="Nothing to stash"):
        stash(repo)


def test_stash_pop_with_nothing_stashed_raises(repo: Path) -> None:
    with pytest.raises(GitError):
        stash_pop(repo)


def test_file_at_head_returns_committed_content(repo: Path) -> None:
    (repo / "app.py").write_text("uncommitted change\n")

    assert file_at_head(repo, "app.py") == "print('hello')\n"


def test_file_at_head_empty_for_an_untracked_file(repo: Path) -> None:
    (repo / "new.py").write_text("new\n")
    assert file_at_head(repo, "new.py") == ""
