"""Git panel for the Code tab: stage, diff, commit, stash, and recent history.

Deliberately thin — it composes `assistant/git_ops.py` and emits requests rather
than running git itself. `IDETab` owns execution so every mutating command goes
through the single serialized worker; two concurrent git processes on one
repository contend for `index.lock` and fail confusingly.

The diff shown here is git's own text output, not the Monaco diff editor: this is
"what have I changed", which is exactly what a unified diff expresses, and it
avoids a second Chromium view in the sidebar.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from assistant.git_ops import Commit, FileStatus

_PATH_ROLE = Qt.ItemDataRole.UserRole
_STAGED_ROLE = Qt.ItemDataRole.UserRole + 1


class GitPanel(QWidget):
    """Working-tree status, staging, commit, and history."""

    stage_requested = pyqtSignal(list)
    unstage_requested = pyqtSignal(list)
    discard_requested = pyqtSignal(list)
    commit_requested = pyqtSignal(str)
    stash_requested = pyqtSignal()
    diff_requested = pyqtSignal(str, bool)  # (rel_path, staged)
    refresh_requested = pyqtSignal()
    file_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_repo = False
        self._busy = False

        self.changes_list = QListWidget()
        self.changes_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.changes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.changes_list.customContextMenuRequested.connect(self._show_context_menu)
        self.changes_list.currentItemChanged.connect(self._on_selection_changed)
        self.changes_list.itemDoubleClicked.connect(self._on_double_clicked)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        # A proportional font makes a diff's alignment meaningless.
        self.diff_view.setFont(QFont("Menlo", 11))
        self.diff_view.setPlaceholderText("Select a changed file to see its diff.")
        self.diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.commit_message = QPlainTextEdit()
        self.commit_message.setPlaceholderText("Commit message...")
        self.commit_message.setFixedHeight(56)

        self.stage_btn = QPushButton("Stage")
        self.stage_btn.clicked.connect(lambda: self._emit_for_selection(self.stage_requested))
        self.unstage_btn = QPushButton("Unstage")
        self.unstage_btn.clicked.connect(lambda: self._emit_for_selection(self.unstage_requested))
        self.stage_all_btn = QPushButton("Stage All")
        self.stage_all_btn.clicked.connect(self._stage_all)
        self.commit_btn = QPushButton("Commit")
        self.commit_btn.clicked.connect(self._commit)
        self.stash_btn = QPushButton("Stash All")
        self.stash_btn.setToolTip("Stash every change including untracked files")
        self.stash_btn.clicked.connect(self.stash_requested)

        self.log_list = QListWidget()
        self.log_list.setAlternatingRowColors(True)

        self.status_label = QLabel("No repository open.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #888;")

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_changes_page(), "Changes")
        self.tabs.addTab(self._build_history_page(), "History")

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(self.tabs)
        self._sync_enabled()

    def _build_changes_page(self) -> QWidget:
        stage_row = QHBoxLayout()
        stage_row.addWidget(self.stage_btn)
        stage_row.addWidget(self.unstage_btn)
        stage_row.addWidget(self.stage_all_btn)

        commit_row = QHBoxLayout()
        commit_row.addWidget(self.commit_btn)
        commit_row.addWidget(self.stash_btn)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.changes_list)
        top_layout.addLayout(stage_row)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.diff_view)
        bottom_layout.addWidget(self.commit_message)
        bottom_layout.addLayout(commit_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setSizes([160, 260])

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.status_label)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.log_list)
        return page

    # -- state -------------------------------------------------------------

    def set_repo_status(self, status) -> None:
        """Repopulates the file list from a `RepoStatus`.

        Preserves the selected path across refreshes — the list is rebuilt on
        every save and status poll, and losing the selection each time would make
        the diff view flicker unusably.
        """
        self._is_repo = status.is_repo
        previously_selected = self.selected_paths()
        self.changes_list.clear()

        if not status.is_repo:
            self.status_label.setText("This folder isn't a git repository.")
            self._sync_enabled()
            return

        staged = [f for f in status.files if f.is_staged]
        unstaged = [f for f in status.files if not f.is_staged]

        if staged:
            self._add_header(f"Staged ({len(staged)})")
            for entry in staged:
                self._add_file(entry, staged=True)
        if unstaged:
            self._add_header(f"Changes ({len(unstaged)})")
            for entry in unstaged:
                self._add_file(entry, staged=False)

        self.status_label.setText("Nothing to commit." if status.is_clean else status.summary)
        self._reselect(previously_selected)
        self._sync_enabled()

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.changes_list.addItem(item)

    def _add_file(self, entry: FileStatus, staged: bool) -> None:
        label = f"  {entry.label:>10}  {entry.path}"
        if entry.orig_path:
            label += f"  ← {entry.orig_path}"
        item = QListWidgetItem(label)
        item.setData(_PATH_ROLE, entry.path)
        item.setData(_STAGED_ROLE, staged)
        self.changes_list.addItem(item)

    def _reselect(self, paths: List[str]) -> None:
        if not paths:
            return
        for index in range(self.changes_list.count()):
            item = self.changes_list.item(index)
            if item.data(_PATH_ROLE) in paths:
                self.changes_list.setCurrentItem(item)
                return

    def set_log(self, commits: List[Commit]) -> None:
        self.log_list.clear()
        for commit in commits:
            self.log_list.addItem(f"{commit.short_sha}  {commit.subject}  ·  {commit.author}, {commit.when}")

    def set_diff(self, rel_path: str, diff_text: str) -> None:
        self.diff_view.setPlainText(
            diff_text or f"No textual diff for {rel_path} (it may be new, binary, or unchanged)."
        )

    def clear(self) -> None:
        self.changes_list.clear()
        self.log_list.clear()
        self.diff_view.clear()
        self.commit_message.clear()
        self._is_repo = False
        self.status_label.setText("No repository open.")
        self._sync_enabled()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        has_selection = bool(self.selected_paths())
        usable = self._is_repo and not self._busy
        self.stage_btn.setEnabled(usable and has_selection)
        self.unstage_btn.setEnabled(usable and has_selection)
        self.stage_all_btn.setEnabled(usable and self.changes_list.count() > 0)
        self.commit_btn.setEnabled(usable and self._has_staged())
        self.stash_btn.setEnabled(usable and self.changes_list.count() > 0)
        self.commit_message.setEnabled(usable)

    def _has_staged(self) -> bool:
        return any(
            self.changes_list.item(i).data(_STAGED_ROLE) is True
            for i in range(self.changes_list.count())
        )

    # -- selection ---------------------------------------------------------

    def selected_paths(self) -> List[str]:
        paths = []
        for item in self.changes_list.selectedItems():
            path = item.data(_PATH_ROLE)
            if path:
                paths.append(path)
        return paths

    def _on_selection_changed(self, current: Optional[QListWidgetItem], _previous) -> None:
        self._sync_enabled()
        if current is None:
            return
        path = current.data(_PATH_ROLE)
        if path:
            self.diff_requested.emit(path, bool(current.data(_STAGED_ROLE)))

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(_PATH_ROLE)
        if path:
            self.file_activated.emit(path)

    def _emit_for_selection(self, signal) -> None:
        paths = self.selected_paths()
        if paths:
            signal.emit(paths)

    def _stage_all(self) -> None:
        paths = [
            self.changes_list.item(i).data(_PATH_ROLE)
            for i in range(self.changes_list.count())
            if self.changes_list.item(i).data(_PATH_ROLE)
        ]
        if paths:
            self.stage_requested.emit(sorted(set(paths)))

    def _commit(self) -> None:
        message = self.commit_message.toPlainText().strip()
        if not message:
            self.status_label.setText("Write a commit message first.")
            return
        self.commit_requested.emit(message)

    def clear_commit_message(self) -> None:
        self.commit_message.clear()

    # -- context menu ------------------------------------------------------

    def _show_context_menu(self, position) -> None:
        item = self.changes_list.itemAt(position)
        if item is None or not item.data(_PATH_ROLE):
            return
        paths = self.selected_paths()
        staged = bool(item.data(_STAGED_ROLE))

        menu = QMenu(self)
        menu.addAction("Open in Editor", lambda: self.file_activated.emit(item.data(_PATH_ROLE)))
        menu.addSeparator()
        if staged:
            menu.addAction("Unstage", lambda: self.unstage_requested.emit(paths))
        else:
            menu.addAction("Stage", lambda: self.stage_requested.emit(paths))
            menu.addAction("Discard Changes...", lambda: self._confirm_discard(paths))
        menu.exec(self.changes_list.viewport().mapToGlobal(position))

    def _confirm_discard(self, paths: List[str]) -> None:
        """Discarding is unrecoverable — no backup, no reflog, nothing to undo."""
        listed = "\n".join(f"  {path}" for path in paths[:10])
        if len(paths) > 10:
            listed += f"\n  ... and {len(paths) - 10} more"
        confirm = QMessageBox.question(
            self,
            "Discard changes?",
            f"Throw away all uncommitted changes to:\n\n{listed}\n\n"
            "This cannot be undone — the changes are not stashed or backed up.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm == QMessageBox.StandardButton.Discard:
            self.discard_requested.emit(paths)
