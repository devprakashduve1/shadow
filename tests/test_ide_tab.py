"""Qt-level tests for the Code tab's non-Monaco widgets.

Follows tests/test_chat_input.py's approach for the QApplication fixture.

Monaco itself is deliberately NOT tested here: it needs a real Chromium event
loop, is slow to start, and is flaky under a headless CI. The Python<->JS surface
is kept to a handful of functions (see gui/ide/monaco.py) precisely so the
untested area stays small. What IS covered is everything around it — tree
filtering, dirty bookkeeping, git wiring, and status display.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# QApplication must exist before any widget is constructed.
from PyQt6.QtWidgets import QApplication

from assistant.manual_projects import ManualProjectRegistry
from gui.ide.file_tree import _IS_DIR_ROLE, _PATH_ROLE, FileTreePanel
from gui.ide.monaco import language_for, monaco_assets_available
from gui.ide.repo_bar import KnowledgeBankState, RepoBar
from gui.ide.workers import RepoStatus
from assistant import git_ops


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    for args in (["init"], ["config", "user.email", "t@e.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, capture_output=True)
    (path / "app.py").write_text("print('hi')\n")
    (path / "src").mkdir()
    (path / "src" / "util.py").write_text("x = 1\n")
    (path / "node_modules").mkdir()
    (path / "node_modules" / "junk.js").write_text("junk")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)
    return path


# -- language detection -----------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("app.py", "python"),
        ("main.ts", "typescript"),
        ("Component.tsx", "typescript"),
        ("style.scss", "scss"),
        ("README.md", "markdown"),
        ("config.yaml", "yaml"),
        ("Dockerfile", "dockerfile"),
        (".env.local", "ini"),
        ("data.bin", "plaintext"),
        ("noextension", "plaintext"),
    ],
)
def test_language_for(filename: str, expected: str) -> None:
    assert language_for(filename) == expected


def test_monaco_assets_available_false_for_missing_dir(tmp_path: Path) -> None:
    assert monaco_assets_available(tmp_path / "nope") is False


# -- file tree --------------------------------------------------------------


def _top_level_labels(panel: FileTreePanel) -> list:
    return [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]


def test_file_tree_hides_ignored_dirs(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))

    labels = _top_level_labels(panel)

    assert "node_modules" not in labels
    assert ".git" not in labels
    assert "src" in labels and "app.py" in labels


def test_file_tree_lists_directories_before_files(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    assert _top_level_labels(panel) == ["src", "app.py"]


def test_file_tree_populates_lazily_on_expand(qapp, repo: Path) -> None:
    """A collapsed directory holds only a placeholder — the filesystem isn't
    touched until the user expands it."""
    panel = FileTreePanel()
    panel.set_project(str(repo))
    src_item = panel.tree.topLevelItem(0)

    assert src_item.childCount() == 1
    assert src_item.child(0).text(0) == "Loading..."

    src_item.setExpanded(True)

    assert [src_item.child(i).text(0) for i in range(src_item.childCount())] == ["util.py"]


def test_file_tree_stores_relative_paths(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    src_item = panel.tree.topLevelItem(0)
    src_item.setExpanded(True)

    assert src_item.child(0).data(0, _PATH_ROLE) == "src/util.py"
    assert src_item.data(0, _IS_DIR_ROLE) is True


def test_file_tree_emits_file_activated_for_files_only(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    activated = []
    panel.file_activated.connect(activated.append)

    panel._on_item_activated(panel.tree.topLevelItem(1))  # app.py
    assert activated == ["app.py"]

    panel._on_item_activated(panel.tree.topLevelItem(0))  # src — expands instead
    assert activated == ["app.py"]


def test_file_tree_filter_hides_non_matching(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))

    panel.filter_input.setText("app")

    by_label = {panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i)
                for i in range(panel.tree.topLevelItemCount())}
    assert by_label["app.py"].isHidden() is False
    assert by_label["src"].isHidden() is True


def test_file_tree_filter_keeps_parent_of_a_match(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    panel.tree.topLevelItem(0).setExpanded(True)  # load src/

    panel.filter_input.setText("util")

    src_item = panel.tree.topLevelItem(0)
    assert src_item.isHidden() is False, "parent of a match must stay visible"
    assert src_item.child(0).isHidden() is False


def test_file_tree_clearing_the_project_empties_it(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    assert panel.tree.topLevelItemCount() > 0

    panel.set_project(None)

    assert panel.tree.topLevelItemCount() == 0
    assert panel.refresh_btn.isEnabled() is False


def test_file_tree_preserves_expansion_across_refresh(qapp, repo: Path) -> None:
    panel = FileTreePanel()
    panel.set_project(str(repo))
    panel.tree.topLevelItem(0).setExpanded(True)

    panel.refresh()

    src_item = panel.tree.topLevelItem(0)
    assert src_item.isExpanded() is True
    assert src_item.childCount() == 1  # repopulated, not left as a placeholder
    assert src_item.child(0).text(0) == "util.py"


# -- repo bar ---------------------------------------------------------------


def _repo_bar(tmp_path: Path) -> RepoBar:
    return RepoBar(ManualProjectRegistry(tmp_path / "manual.json"))


def test_repo_bar_shows_branch_and_clean_status(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)

    bar.set_repo_status(RepoStatus(is_repo=True, branch="main", branches=["main", "dev"], files=[]))

    assert bar.branch_combo.currentText() == "main"
    assert bar.git_label.text() == "clean"
    assert bar.branch_combo.isEnabled() is True


def test_repo_bar_summarizes_dirty_status(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)
    files = [
        git_ops.FileStatus(path="a.py", index_status="M", worktree_status=" "),
        git_ops.FileStatus(path="b.py", index_status=" ", worktree_status="M"),
        git_ops.FileStatus(path="c.py", index_status="?", worktree_status="?"),
    ]

    bar.set_repo_status(RepoStatus(is_repo=True, branch="main", branches=["main"], files=files))

    assert bar.git_label.text() == "1 staged, 1 modified, 1 untracked"


def test_repo_bar_disables_branch_controls_for_non_repo(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)

    bar.set_repo_status(RepoStatus(is_repo=False))

    assert bar.git_label.text() == "not a git repo"
    assert bar.branch_combo.isEnabled() is False
    assert bar.new_branch_btn.isEnabled() is False


def test_repo_bar_shows_detached_head(qapp, tmp_path: Path) -> None:
    """A detached HEAD isn't in `branches`; it still has to be displayed."""
    bar = _repo_bar(tmp_path)

    bar.set_repo_status(RepoStatus(is_repo=True, branch="abc1234", branches=["main"]))

    assert bar.branch_combo.currentText() == "abc1234"


def test_repo_bar_repopulating_branches_does_not_request_a_switch(qapp, tmp_path: Path) -> None:
    """Regression guard: the combo's currentTextChanged fires while being
    repopulated, which must not be mistaken for the user picking a branch."""
    bar = _repo_bar(tmp_path)
    requested = []
    bar.branch_switch_requested.connect(requested.append)

    bar.set_repo_status(RepoStatus(is_repo=True, branch="dev", branches=["main", "dev"]))

    assert requested == []


def test_repo_bar_user_branch_choice_does_emit(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)
    bar.set_repo_status(RepoStatus(is_repo=True, branch="main", branches=["main", "dev"]))
    requested = []
    bar.branch_switch_requested.connect(requested.append)

    bar.branch_combo.setCurrentText("dev")

    assert requested == ["dev"]


def test_repo_bar_shows_repo_bank_state(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)

    bar.set_knowledge_bank_state(KnowledgeBankState.INDEXING, "120/900")

    assert bar.kb_label.text() == "Repo KB: indexing (120/900)"


def test_repo_bar_shows_general_bank_state(qapp, tmp_path: Path) -> None:
    """Two banks, two indicators — the general one isn't tied to a repository."""
    bar = _repo_bar(tmp_path)

    bar.set_general_bank_state(KnowledgeBankState.READY, "482 events")

    assert bar.general_kb_label.text() == "Team KB: 482 events" or \
        bar.general_kb_label.text() == "Team KB: ready (482 events)"


def test_the_two_bank_indicators_are_independent(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)

    bar.set_knowledge_bank_state(KnowledgeBankState.READY, "120 files")
    bar.set_general_bank_state(KnowledgeBankState.MISSING)

    assert "ready" in bar.kb_label.text()
    assert "not indexed" in bar.general_kb_label.text()


def test_repo_bar_lists_recent_repos_from_the_registry(qapp, tmp_path: Path) -> None:
    registry = ManualProjectRegistry(tmp_path / "manual.json")
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    registry.add(str(project_dir))

    bar = RepoBar(registry)

    paths = [bar.repo_combo.itemData(i) for i in range(bar.repo_combo.count())]
    assert str(project_dir.resolve()) in [p for p in paths if p]


# -- RepoStatus -------------------------------------------------------------


def test_repo_status_clean_when_no_files() -> None:
    assert RepoStatus(is_repo=True).is_clean is True


def test_repo_status_summary_for_non_repo() -> None:
    assert RepoStatus(is_repo=False).summary == "not a git repo"


# -- Knowledge Bank actions live next to their status ------------------------


def test_index_repo_button_needs_a_repository(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)
    assert bar.build_kb_btn.isEnabled() is False


def test_index_repo_button_enables_once_a_repo_is_open(qapp, tmp_path: Path, repo: Path) -> None:
    bar = _repo_bar(tmp_path)

    bar.set_project(str(repo))

    assert bar.build_kb_btn.isEnabled() is True


def test_update_team_kb_needs_no_repository(qapp, tmp_path: Path) -> None:
    """The general bank describes work around the code, not a specific repo."""
    bar = _repo_bar(tmp_path)
    assert bar.build_general_kb_btn.isEnabled() is True


def test_index_repo_button_emits(qapp, tmp_path: Path, repo: Path) -> None:
    bar = _repo_bar(tmp_path)
    bar.set_project(str(repo))
    seen = []
    bar.build_repo_bank_requested.connect(lambda: seen.append(True))

    bar.build_kb_btn.click()

    assert seen == [True]


def test_update_team_kb_button_emits(qapp, tmp_path: Path) -> None:
    bar = _repo_bar(tmp_path)
    seen = []
    bar.build_general_bank_requested.connect(lambda: seen.append(True))

    bar.build_general_kb_btn.click()

    assert seen == [True]


def test_bank_buttons_are_disabled_while_busy(qapp, tmp_path: Path, repo: Path) -> None:
    bar = _repo_bar(tmp_path)
    bar.set_project(str(repo))

    bar.set_busy(True)

    assert bar.build_kb_btn.isEnabled() is False
    assert bar.build_general_kb_btn.isEnabled() is False


def test_index_repo_stays_disabled_after_busy_with_no_repo(qapp, tmp_path: Path) -> None:
    """Clearing the busy flag must not enable an action that has no target."""
    bar = _repo_bar(tmp_path)

    bar.set_busy(True)
    bar.set_busy(False)

    assert bar.build_kb_btn.isEnabled() is False
