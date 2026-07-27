"""Lazy file explorer for the Code tab.

A hand-rolled `QTreeWidget` rather than `QFileSystemModel` because the tree has
to hide `node_modules`, `.git`, `dist` and friends (`DEFAULT_IGNORED_DIRS`), and
`QFileSystemModel` can only filter *files* by name — hiding directories needs a
recursive `QSortFilterProxyModel` that ends up longer than this, while giving up
control over when the filesystem is touched.

Directories populate on expand, so opening a repo never walks the whole tree.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from assistant.project_files import (
    ProjectFileError,
    atomic_write_file,
    list_dir,
    resolve_in_project,
)

# Item data roles. UserRole holds the repo-relative path; the others track lazy
# loading state so a directory is only listed once per expand cycle.
_PATH_ROLE = Qt.ItemDataRole.UserRole
_IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 1
_LOADED_ROLE = Qt.ItemDataRole.UserRole + 2


class FileTreePanel(QWidget):
    """File explorer with lazy expansion and a create/rename/delete context menu."""

    file_activated = pyqtSignal(str)  # repo-relative path
    file_renamed = pyqtSignal(str, str)  # (old_rel, new_rel)
    file_deleted = pyqtSignal(str)  # repo-relative path
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_path: Optional[Path] = None

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemActivated.connect(self._on_item_activated)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter visible files...")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._apply_filter)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.new_file_btn = QPushButton("New File")
        self.new_file_btn.clicked.connect(lambda: self._create_entry(is_dir=False))

        self.status_label = QLabel("No repository open.")
        self.status_label.setWordWrap(True)

        self._build_layout()
        self._set_controls_enabled(False)

    def _build_layout(self) -> None:
        button_row = QHBoxLayout()
        button_row.addWidget(self.new_file_btn)
        button_row.addWidget(self.refresh_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(QLabel("Explorer"))
        root.addWidget(self.filter_input)
        root.addWidget(self.tree)
        root.addLayout(button_row)
        root.addWidget(self.status_label)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.refresh_btn.setEnabled(enabled)
        self.new_file_btn.setEnabled(enabled)
        self.filter_input.setEnabled(enabled)

    # -- repo lifecycle ----------------------------------------------------

    def set_project(self, project_path: Optional[str]) -> None:
        self._project_path = Path(project_path) if project_path else None
        self._set_controls_enabled(self._project_path is not None)
        self.refresh()

    def refresh(self) -> None:
        """Rebuilds the tree, preserving which directories were expanded."""
        expanded = self._expanded_paths()
        self.tree.clear()

        if self._project_path is None:
            self.status_label.setText("No repository open.")
            return

        try:
            entries = list_dir(self._project_path, ".")
        except ProjectFileError as exc:
            self.status_label.setText(str(exc))
            return

        for name, is_dir in entries:
            self.tree.addTopLevelItem(self._make_item(name, name, is_dir))
        self.status_label.setText(f"{len(entries)} item(s) at top level.")
        self._restore_expanded(expanded)
        self._apply_filter(self.filter_input.text())

    def _make_item(self, label: str, rel_path: str, is_dir: bool) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _PATH_ROLE, rel_path)
        item.setData(0, _IS_DIR_ROLE, is_dir)
        item.setData(0, _LOADED_ROLE, False)
        if is_dir:
            # Placeholder child so Qt draws an expand arrow before we've listed
            # the directory; replaced on first expand.
            item.addChild(QTreeWidgetItem(["Loading..."]))
        return item

    # -- lazy expansion ----------------------------------------------------

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if not item.data(0, _IS_DIR_ROLE) or item.data(0, _LOADED_ROLE):
            return
        item.takeChildren()  # drop the placeholder
        item.setData(0, _LOADED_ROLE, True)

        rel_dir = item.data(0, _PATH_ROLE)
        try:
            entries = list_dir(self._project_path, rel_dir)
        except ProjectFileError as exc:
            self.error.emit(str(exc))
            return
        for name, is_dir in entries:
            item.addChild(self._make_item(name, f"{rel_dir}/{name}", is_dir))
        self._apply_filter(self.filter_input.text())

    def _expanded_paths(self) -> set:
        found = set()

        def walk(item: QTreeWidgetItem) -> None:
            if item.isExpanded() and item.data(0, _PATH_ROLE):
                found.add(item.data(0, _PATH_ROLE))
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return found

    def _restore_expanded(self, paths: set) -> None:
        if not paths:
            return

        def walk(item: QTreeWidgetItem) -> None:
            if item.data(0, _PATH_ROLE) in paths:
                item.setExpanded(True)  # triggers _on_item_expanded, which populates
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # -- filtering ---------------------------------------------------------

    def _apply_filter(self, text: str) -> None:
        """Hides non-matching items among those already loaded.

        Only filters what's been expanded — it deliberately does not walk the
        whole project, since that's the cost lazy loading exists to avoid. A
        directory stays visible if any loaded descendant matches.
        """
        needle = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            child_matches = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_matches = True
            label = item.text(0).lower()
            matches = (not needle) or (needle in label) or child_matches
            item.setHidden(not matches)
            return matches

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    # -- activation --------------------------------------------------------

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if item.data(0, _IS_DIR_ROLE):
            item.setExpanded(not item.isExpanded())
            return
        rel_path = item.data(0, _PATH_ROLE)
        if rel_path:
            self.file_activated.emit(rel_path)

    def _selected(self) -> Optional[QTreeWidgetItem]:
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _parent_dir_of_selection(self) -> str:
        """Where a "New File" should land: the selected dir, or the selection's parent."""
        item = self._selected()
        if item is None:
            return "."
        rel = item.data(0, _PATH_ROLE)
        if item.data(0, _IS_DIR_ROLE):
            return rel
        parent = str(Path(rel).parent)
        return "." if parent == "." else parent

    # -- context menu ------------------------------------------------------

    def _show_context_menu(self, position) -> None:
        if self._project_path is None:
            return
        item = self.tree.itemAt(position)
        menu = QMenu(self)

        menu.addAction("New File...", lambda: self._create_entry(is_dir=False))
        menu.addAction("New Folder...", lambda: self._create_entry(is_dir=True))
        if item is not None:
            menu.addSeparator()
            menu.addAction("Rename...", lambda: self._rename(item))
            menu.addAction("Delete", lambda: self._delete(item))
            menu.addSeparator()
            menu.addAction("Copy Relative Path", lambda: self._copy_path(item))
            menu.addAction("Reveal in Finder", lambda: self._reveal(item))
        menu.addSeparator()
        menu.addAction("Refresh", self.refresh)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _create_entry(self, is_dir: bool) -> None:
        if self._project_path is None:
            return
        kind = "folder" if is_dir else "file"
        parent_dir = self._parent_dir_of_selection()
        name, ok = QInputDialog.getText(
            self, f"New {kind}", f"Name of the new {kind} (in {parent_dir}):"
        )
        if not ok or not name.strip():
            return
        rel_path = name.strip() if parent_dir == "." else f"{parent_dir}/{name.strip()}"

        try:
            target = resolve_in_project(self._project_path, rel_path)
            if target.exists():
                raise ProjectFileError(f"{rel_path} already exists.")
            if is_dir:
                target.mkdir(parents=True)
            else:
                atomic_write_file(self._project_path, rel_path, "")
        except (ProjectFileError, OSError) as exc:
            self.error.emit(str(exc))
            return

        self.refresh()
        if not is_dir:
            self.file_activated.emit(rel_path)

    def _rename(self, item: QTreeWidgetItem) -> None:
        old_rel = item.data(0, _PATH_ROLE)
        new_name, ok = QInputDialog.getText(
            self, "Rename", f"New name for {Path(old_rel).name}:", text=Path(old_rel).name
        )
        if not ok or not new_name.strip() or new_name.strip() == Path(old_rel).name:
            return

        parent = str(Path(old_rel).parent)
        new_rel = new_name.strip() if parent == "." else f"{parent}/{new_name.strip()}"
        try:
            source = resolve_in_project(self._project_path, old_rel)
            target = resolve_in_project(self._project_path, new_rel)
            if target.exists():
                raise ProjectFileError(f"{new_rel} already exists.")
            source.rename(target)
        except (ProjectFileError, OSError) as exc:
            self.error.emit(str(exc))
            return

        self.refresh()
        self.file_renamed.emit(old_rel, new_rel)

    def _delete(self, item: QTreeWidgetItem) -> None:
        rel_path = item.data(0, _PATH_ROLE)
        is_dir = item.data(0, _IS_DIR_ROLE)
        confirm = QMessageBox.question(
            self,
            "Delete?",
            f"Permanently delete {rel_path}?"
            + ("\n\nThis deletes the folder and everything in it." if is_dir else "")
            + "\n\nThis does not go through the Trash.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            target = resolve_in_project(self._project_path, rel_path)
            if is_dir:
                shutil.rmtree(target)
            else:
                target.unlink()
        except (ProjectFileError, OSError) as exc:
            self.error.emit(str(exc))
            return

        self.refresh()
        self.file_deleted.emit(rel_path)

    def _copy_path(self, item: QTreeWidgetItem) -> None:
        QApplication.clipboard().setText(item.data(0, _PATH_ROLE))

    def _reveal(self, item: QTreeWidgetItem) -> None:
        try:
            target = resolve_in_project(self._project_path, item.data(0, _PATH_ROLE))
            subprocess.run(["open", "-R", str(target)], capture_output=True, timeout=5)
        except (ProjectFileError, OSError, subprocess.SubprocessError) as exc:
            self.error.emit(str(exc))
