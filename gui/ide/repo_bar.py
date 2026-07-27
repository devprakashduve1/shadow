"""Top bar of the Code tab: repository picker, branch control, and status.

Covers the "display the active repository, current branch, Git status, and
Knowledge Bank status" requirement in one strip, so the state that matters is
always visible rather than buried in a panel.

Recent repositories come from the same `ManualProjectRegistry` the Coding Agent
tab uses, so a folder browsed in either place shows up in both.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QWidget,
)

from assistant.manual_projects import ManualProjectRegistry


class KnowledgeBankState:
    """Display states for the Knowledge Bank indicator.

    Defined here (rather than in the not-yet-built knowledge package) so Phase 1
    can show an honest "not built yet" instead of pretending the feature exists.
    """

    UNKNOWN = "unknown"
    MISSING = "not indexed"
    INDEXING = "indexing"
    READY = "ready"
    STALE = "stale"


class RepoBar(QWidget):
    """Repository selection plus a live read-out of repo/branch/git/KB state."""

    repo_selected = pyqtSignal(str)  # absolute path
    branch_switch_requested = pyqtSignal(str)
    branch_create_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    build_repo_bank_requested = pyqtSignal()
    build_general_bank_requested = pyqtSignal()

    def __init__(self, manual_projects: ManualProjectRegistry, parent=None):
        super().__init__(parent)
        self._manual_projects = manual_projects
        self._project_path: Optional[Path] = None
        # Guards against the branch combo's currentTextChanged firing while we
        # repopulate it, which would look like the user requesting a switch.
        self._suppress_branch_signal = False

        self.repo_combo = QComboBox()
        self.repo_combo.setMinimumWidth(220)
        self.repo_combo.setToolTip("Recently opened repositories")
        self.repo_combo.activated.connect(self._on_repo_chosen)

        self.browse_btn = QPushButton("Open Repo...")
        self.browse_btn.clicked.connect(self._browse)

        self.branch_combo = QComboBox()
        self.branch_combo.setMinimumWidth(140)
        self.branch_combo.setToolTip("Current branch — switching requires a clean working tree")
        self.branch_combo.setEnabled(False)
        self.branch_combo.currentTextChanged.connect(self._on_branch_chosen)

        self.new_branch_btn = QPushButton("New Branch...")
        self.new_branch_btn.setEnabled(False)
        self.new_branch_btn.clicked.connect(self._create_branch)

        self.git_label = QLabel("—")
        self.git_label.setToolTip("Working tree status")

        # The knowledge banks get action buttons right next to their status, not
        # only at the bottom of the AI panel: "index this repo" is something you
        # reach for while looking at the repo controls, so that's where it belongs.
        self.kb_label = QLabel("Repo KB: —")
        self.kb_label.setToolTip(
            "Repository Knowledge Bank — architecture, symbols, dependencies, module "
            "graph, APIs, and git history for the open repo"
        )
        self.build_kb_btn = QPushButton("Index Repo")
        self.build_kb_btn.setToolTip(
            "Create or update this repository's Knowledge Bank: architecture, symbols, "
            "dependencies, module graph, APIs, and git history.\n"
            "Incremental — only files that changed are re-read."
        )
        self.build_kb_btn.setEnabled(False)
        self.build_kb_btn.clicked.connect(self.build_repo_bank_requested)

        self.general_kb_label = QLabel("Team KB: —")
        self.general_kb_label.setToolTip(
            "General Knowledge Bank — decisions, action items, and vocabulary gathered "
            "from your captured meetings and screen activity"
        )
        self.build_general_kb_btn = QPushButton("Update Team KB")
        self.build_general_kb_btn.setToolTip(
            "Fold newly captured meetings and screen activity into the General "
            "Knowledge Bank. Not tied to a repository."
        )
        self.build_general_kb_btn.clicked.connect(self.build_general_bank_requested)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(32)
        self.refresh_btn.setToolTip("Refresh git status")
        self.refresh_btn.clicked.connect(self.refresh_requested)

        self._build_layout()
        self.reload_recent_repos()

    def _build_layout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(QLabel("Repo:"))
        layout.addWidget(self.repo_combo)
        layout.addWidget(self.browse_btn)
        layout.addSpacing(12)
        layout.addWidget(QLabel("Branch:"))
        layout.addWidget(self.branch_combo)
        layout.addWidget(self.new_branch_btn)
        layout.addSpacing(12)
        layout.addWidget(self.git_label)
        layout.addSpacing(8)
        layout.addWidget(self.kb_label)
        layout.addWidget(self.build_kb_btn)
        layout.addSpacing(10)
        layout.addWidget(self.general_kb_label)
        layout.addWidget(self.build_general_kb_btn)
        layout.addStretch()
        layout.addWidget(self.refresh_btn)

    # -- repo selection ----------------------------------------------------

    def reload_recent_repos(self) -> None:
        """Repopulates the recent-repos combo from the shared registry."""
        current = str(self._project_path) if self._project_path else None
        self.repo_combo.blockSignals(True)
        self.repo_combo.clear()
        self.repo_combo.addItem("Select a repository...", None)
        for project in self._manual_projects.list():
            self.repo_combo.addItem(f"{project.name}  ·  {project.path}", project.path)
        if current:
            index = self.repo_combo.findData(current)
            if index >= 0:
                self.repo_combo.setCurrentIndex(index)
        self.repo_combo.blockSignals(False)

    def _on_repo_chosen(self, index: int) -> None:
        path = self.repo_combo.itemData(index)
        if path:
            self.repo_selected.emit(path)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open a repository folder")
        if not folder:
            return
        # Registering here means the folder is offered next time and is also
        # visible to the Assistant/Coding Agent tabs.
        self._manual_projects.add(folder)
        self.reload_recent_repos()
        self.repo_selected.emit(folder)

    def set_project(self, project_path: Optional[str]) -> None:
        self._project_path = Path(project_path) if project_path else None
        self.reload_recent_repos()
        self.build_kb_btn.setEnabled(self._project_path is not None)
        if self._project_path is None:
            self.git_label.setText("—")
            self.set_knowledge_bank_state(KnowledgeBankState.UNKNOWN)

    # -- branches ----------------------------------------------------------

    def _on_branch_chosen(self, branch: str) -> None:
        if self._suppress_branch_signal or not branch:
            return
        self.branch_switch_requested.emit(branch)

    def _create_branch(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New branch", "Branch name:", text="feature/"
        )
        if ok and name.strip():
            self.branch_create_requested.emit(name.strip())

    # -- status display ----------------------------------------------------

    def set_repo_status(self, status) -> None:
        """Updates the branch combo and git read-out from a `RepoStatus`."""
        self._suppress_branch_signal = True
        try:
            self.branch_combo.clear()
            if status.is_repo:
                self.branch_combo.addItems(status.branches or [])
                if status.branch:
                    index = self.branch_combo.findText(status.branch)
                    if index >= 0:
                        self.branch_combo.setCurrentIndex(index)
                    else:
                        # Detached HEAD, or a branch with no commits yet.
                        self.branch_combo.insertItem(0, status.branch)
                        self.branch_combo.setCurrentIndex(0)
        finally:
            self._suppress_branch_signal = False

        self.branch_combo.setEnabled(status.is_repo)
        self.new_branch_btn.setEnabled(status.is_repo)
        self.build_kb_btn.setEnabled(self._project_path is not None)

        if not status.is_repo:
            self.git_label.setText("not a git repo")
            self.git_label.setStyleSheet("color: #c07a00;")
            self.branch_combo.setToolTip(
                "This folder isn't a git repository. `git init` it to get branch "
                "switching and safe AI edits."
            )
            return

        self.git_label.setText(status.summary)
        self.git_label.setStyleSheet("color: #4a9d4a;" if status.is_clean else "color: #c07a00;")
        self.branch_combo.setToolTip(
            "Current branch"
            if status.is_clean
            else "Switching branches needs a clean working tree — commit or stash first."
        )

    def set_knowledge_bank_state(self, state: str, detail: str = "") -> None:
        self._apply_kb_state(self.kb_label, "Repo KB", state, detail)

    def set_general_bank_state(self, state: str, detail: str = "") -> None:
        self._apply_kb_state(self.general_kb_label, "Team KB", state, detail)

    def _apply_kb_state(self, label_widget, prefix: str, state: str, detail: str) -> None:
        label_widget.setText(f"{prefix}: {state}" + (f" ({detail})" if detail else ""))
        colors = {
            KnowledgeBankState.READY: "color: #4a9d4a;",
            KnowledgeBankState.INDEXING: "color: #3b78c3;",
            KnowledgeBankState.STALE: "color: #c07a00;",
            KnowledgeBankState.MISSING: "color: #888;",
            KnowledgeBankState.UNKNOWN: "color: #888;",
        }
        label_widget.setStyleSheet(colors.get(state, "color: #888;"))

    def set_busy(self, busy: bool) -> None:
        for widget in (self.repo_combo, self.browse_btn, self.branch_combo,
                       self.new_branch_btn, self.refresh_btn, self.build_kb_btn,
                       self.build_general_kb_btn):
            widget.setEnabled(not busy)
        if not busy and self._project_path is None:
            self.branch_combo.setEnabled(False)
            self.new_branch_btn.setEnabled(False)
            self.build_kb_btn.setEnabled(False)
