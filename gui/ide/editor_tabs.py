"""Tabbed Monaco editors with dirty tracking and conflict-aware saving.

One `MonacoEditor` per open file. Each is a full QWebEngineView, which is not
cheap, so `MAX_OPEN_TABS` caps how many can exist at once.

The save path is the part worth reading carefully: every buffer remembers the
mtime it was read at, and saving passes that back so a change made outside the
editor is detected instead of silently overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from assistant.project_files import MAX_EDITABLE_BYTES

from .monaco import DEFAULT_MONACO_DIR, MonacoEditor, monaco_assets_available
from .workers import FileReadWorker, FileSaveWorker

# Each tab is a separate Chromium view; more than this and memory use gets silly.
MAX_OPEN_TABS = 12


@dataclass
class EditorState:
    """Per-tab bookkeeping.

    `mtime` is the file's modification time as of the last successful read or
    write — the basis for conflict detection on save. `baseline_text` is what
    was loaded, used to tell a real edit from an edit-and-undo.
    """

    rel_path: str
    mtime: Optional[float] = None
    baseline_text: str = ""
    dirty: bool = False
    editor: Optional[MonacoEditor] = field(default=None, repr=False)


class EditorTabs(QWidget):
    """Manages open file buffers for one repository."""

    dirty_changed = pyqtSignal(bool)  # any tab dirty?
    status_message = pyqtSignal(str)
    error = pyqtSignal(str)
    file_saved = pyqtSignal(str)
    selection_changed = pyqtSignal(str)  # selected text in the active editor

    def __init__(
        self,
        monaco_dir: Optional[Path] = None,
        theme: str = "vs-dark",
        max_file_bytes: int = MAX_EDITABLE_BYTES,
        parent=None,
    ):
        super().__init__(parent)
        self._monaco_dir = Path(monaco_dir) if monaco_dir else DEFAULT_MONACO_DIR
        self._theme = theme
        self._max_file_bytes = max_file_bytes
        self._project_path: Optional[Path] = None
        self._states: Dict[str, EditorState] = {}
        self._read_workers: Dict[str, FileReadWorker] = {}
        self._save_workers: Dict[str, FileSaveWorker] = {}

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tabs.currentChanged.connect(self._on_current_changed)

        self.placeholder = QLabel(
            "No file open.\n\nPick a file in the Explorer on the left."
            if monaco_assets_available(self._monaco_dir)
            else "Monaco Editor assets aren't installed.\n\nRun: python scripts/fetch_vendor.py"
        )
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("padding: 24px; color: #999;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.tabs)
        self._sync_placeholder()

    # -- repo lifecycle ----------------------------------------------------

    def set_project(self, project_path: Optional[str]) -> None:
        """Points at a new repository, closing every open buffer first.

        Returns without switching if the user cancels over unsaved work — the
        caller checks `has_unsaved_changes()` before calling, so this is a
        backstop rather than the main gate.
        """
        self.close_all()
        self._project_path = Path(project_path) if project_path else None

    @property
    def project_path(self) -> Optional[Path]:
        return self._project_path

    # -- opening -----------------------------------------------------------

    def open_file(self, rel_path: str) -> None:
        if self._project_path is None:
            return
        if rel_path in self._states:
            self._focus(rel_path)
            return
        if len(self._states) >= MAX_OPEN_TABS:
            self.error.emit(
                f"{MAX_OPEN_TABS} files are already open — close one before opening another."
            )
            return
        if rel_path in self._read_workers:
            return  # already loading

        self.status_message.emit(f"Opening {rel_path}...")
        worker = FileReadWorker(str(self._project_path), rel_path, max_bytes=self._max_file_bytes)
        worker.finished_ok.connect(self._on_file_read)
        worker.error.connect(self._on_read_error)
        self._read_workers[rel_path] = worker
        worker.start()

    def _on_file_read(self, rel_path: str, text: str, mtime: float) -> None:
        self._retire_read_worker(rel_path)
        if self._project_path is None:
            return  # repo changed while we were reading

        editor = MonacoEditor(monaco_dir=self._monaco_dir, parent=self)
        editor.set_theme(self._theme)
        state = EditorState(rel_path=rel_path, mtime=mtime, baseline_text=text, editor=editor)
        self._states[rel_path] = state

        # set_content is safe before the editor reports ready — MonacoEditor
        # queues it (see its _pending_ops).
        editor.set_content(text, rel_path)
        editor.content_changed.connect(lambda p=rel_path: self._on_content_changed(p))
        editor.selection_changed.connect(
            lambda sel, _s, _e, p=rel_path: self._on_selection_changed(p, sel)
        )

        index = self.tabs.addTab(editor, Path(rel_path).name)
        self.tabs.setTabToolTip(index, rel_path)
        self.tabs.setCurrentIndex(index)
        self._sync_placeholder()
        self.status_message.emit(f"Opened {rel_path}")

    def _on_read_error(self, rel_path: str, message: str) -> None:
        self._retire_read_worker(rel_path)
        self.error.emit(f"Could not open {rel_path}: {message}")

    def _retire_read_worker(self, rel_path: str) -> None:
        worker = self._read_workers.pop(rel_path, None)
        if worker is not None:
            worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note

    # -- dirty tracking ----------------------------------------------------

    def _on_content_changed(self, rel_path: str) -> None:
        state = self._states.get(rel_path)
        if state is None or state.dirty:
            return
        state.dirty = True
        self._refresh_tab_title(rel_path)
        self.dirty_changed.emit(self.has_unsaved_changes())

    def _on_selection_changed(self, rel_path: str, selection: str) -> None:
        if self.current_rel_path() == rel_path:
            self.selection_changed.emit(selection)

    def _refresh_tab_title(self, rel_path: str) -> None:
        state = self._states.get(rel_path)
        if state is None or state.editor is None:
            return
        index = self.tabs.indexOf(state.editor)
        if index >= 0:
            name = Path(rel_path).name
            self.tabs.setTabText(index, f"● {name}" if state.dirty else name)

    def has_unsaved_changes(self) -> bool:
        return any(state.dirty for state in self._states.values())

    def unsaved_paths(self) -> list:
        return [path for path, state in self._states.items() if state.dirty]

    # -- current tab -------------------------------------------------------

    def current_rel_path(self) -> Optional[str]:
        widget = self.tabs.currentWidget()
        for rel_path, state in self._states.items():
            if state.editor is widget:
                return rel_path
        return None

    def current_editor(self) -> Optional[MonacoEditor]:
        rel_path = self.current_rel_path()
        state = self._states.get(rel_path) if rel_path else None
        return state.editor if state else None

    def current_selection(self) -> str:
        editor = self.current_editor()
        return editor.selected_text if editor else ""

    def _focus(self, rel_path: str) -> None:
        state = self._states.get(rel_path)
        if state and state.editor is not None:
            self.tabs.setCurrentWidget(state.editor)

    def _on_current_changed(self, _index: int) -> None:
        self.selection_changed.emit(self.current_selection())

    # -- saving ------------------------------------------------------------

    def save_current(self) -> None:
        rel_path = self.current_rel_path()
        if rel_path:
            self.save(rel_path)

    def save(self, rel_path: str, force: bool = False) -> None:
        """Saves one buffer.

        `force=True` skips the mtime check — used only after the user explicitly
        chooses "Overwrite" in the conflict prompt.
        """
        state = self._states.get(rel_path)
        if state is None or state.editor is None or self._project_path is None:
            return
        if rel_path in self._save_workers:
            return  # a save is already in flight

        # Content has to be fetched asynchronously from JS, so the actual write
        # is kicked off from the callback.
        state.editor.get_content(lambda text: self._write(rel_path, text, force=force))

    def _write(self, rel_path: str, text: str, force: bool) -> None:
        state = self._states.get(rel_path)
        if state is None or self._project_path is None:
            return
        self.status_message.emit(f"Saving {rel_path}...")
        worker = FileSaveWorker(
            str(self._project_path),
            rel_path,
            text,
            expected_mtime=None if force else state.mtime,
        )
        worker.finished_ok.connect(self._on_saved)
        worker.conflict.connect(self._on_save_conflict)
        worker.error.connect(self._on_save_error)
        self._save_workers[rel_path] = worker
        # Remember what we tried to write so a conflict prompt can re-offer it.
        state.baseline_text = text
        worker.start()

    def _on_saved(self, rel_path: str, new_mtime: float) -> None:
        self._retire_save_worker(rel_path)
        state = self._states.get(rel_path)
        if state is not None:
            state.mtime = new_mtime
            state.dirty = False
            self._refresh_tab_title(rel_path)
        self.dirty_changed.emit(self.has_unsaved_changes())
        self.status_message.emit(f"Saved {rel_path}")
        self.file_saved.emit(rel_path)

    def _on_save_conflict(self, rel_path: str, message: str) -> None:
        self._retire_save_worker(rel_path)
        choice = QMessageBox.question(
            self,
            "File changed on disk",
            f"{message}\n\nOverwrite the version on disk, or reload it and lose your edits?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            self.save(rel_path, force=True)
        elif choice == QMessageBox.StandardButton.Discard:
            self.reload(rel_path)
        else:
            self.status_message.emit(f"{rel_path} not saved.")

    def _on_save_error(self, rel_path: str, message: str) -> None:
        self._retire_save_worker(rel_path)
        self.error.emit(f"Could not save {rel_path}: {message}")

    def _retire_save_worker(self, rel_path: str) -> None:
        worker = self._save_workers.pop(rel_path, None)
        if worker is not None:
            worker.wait()

    def reload(self, rel_path: str) -> None:
        """Re-reads a file from disk, discarding buffer edits."""
        state = self._states.get(rel_path)
        if state is None or self._project_path is None:
            return
        worker = FileReadWorker(str(self._project_path), rel_path, max_bytes=self._max_file_bytes)
        worker.finished_ok.connect(self._on_reloaded)
        worker.error.connect(self._on_read_error)
        self._read_workers[rel_path] = worker
        worker.start()

    def _on_reloaded(self, rel_path: str, text: str, mtime: float) -> None:
        self._retire_read_worker(rel_path)
        state = self._states.get(rel_path)
        if state is None or state.editor is None:
            return
        state.editor.set_content(text, rel_path)
        state.mtime = mtime
        state.baseline_text = text
        state.dirty = False
        self._refresh_tab_title(rel_path)
        self.dirty_changed.emit(self.has_unsaved_changes())
        self.status_message.emit(f"Reloaded {rel_path}")

    def apply_text(self, rel_path: str, text: str) -> None:
        """Replaces a buffer's content in place (used when applying an AI edit).

        Marks the buffer dirty rather than saving — writing to disk is the
        caller's decision, not a side effect of updating the view.
        """
        state = self._states.get(rel_path)
        if state is None or state.editor is None:
            return
        state.editor.set_content(text, rel_path)
        state.dirty = True
        self._refresh_tab_title(rel_path)
        self.dirty_changed.emit(True)

    # -- closing -----------------------------------------------------------

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self.tabs.widget(index)
        rel_path = next((p for p, s in self._states.items() if s.editor is widget), None)
        if rel_path is None:
            return
        if self._states[rel_path].dirty and not self._confirm_discard(rel_path):
            return
        self.close_file(rel_path)

    def _confirm_discard(self, rel_path: str) -> bool:
        choice = QMessageBox.question(
            self,
            "Unsaved changes",
            f"{rel_path} has unsaved changes.\n\nSave before closing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            self.save(rel_path)
            return False  # closing happens after the save reports back
        return choice == QMessageBox.StandardButton.Discard

    def close_file(self, rel_path: str) -> None:
        state = self._states.pop(rel_path, None)
        if state is None:
            return
        if state.editor is not None:
            index = self.tabs.indexOf(state.editor)
            if index >= 0:
                self.tabs.removeTab(index)
            state.editor.shutdown()
            state.editor.deleteLater()
        self._sync_placeholder()
        self.dirty_changed.emit(self.has_unsaved_changes())

    def close_all(self) -> None:
        for rel_path in list(self._states):
            self.close_file(rel_path)

    def _sync_placeholder(self) -> None:
        has_tabs = self.tabs.count() > 0
        self.tabs.setVisible(has_tabs)
        self.placeholder.setVisible(not has_tabs)

    def shutdown(self) -> None:
        for worker in list(self._read_workers.values()) + list(self._save_workers.values()):
            worker.wait(2000)
        self._read_workers.clear()
        self._save_workers.clear()
        for state in self._states.values():
            if state.editor is not None:
                state.editor.shutdown()
        self._states.clear()
