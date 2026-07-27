"""The Code tab's AI panel: actions, chat, and diff review.

Two stacked modes in one panel:

- **chat** — action buttons plus a prompt box; explanations stream into the
  transcript.
- **review** — a proposed edit's diff with Accept / Reject / Edit Manually.

They share the panel so a proposal can't be silently forgotten: while a review is
pending, the actions are unavailable until the user decides.

Reuses `ChatInput` and `_DictationMixin` from `gui/chat_widgets.py` rather than
reinventing them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assistant.edits.actions import EditAction, EditRequest
from config import settings

from ..chat_widgets import ChatInput, _DictationMixin
from assistant.ollama_models import PREFERRED_DEFAULT, choose_default, normalize_name

from .monaco import DEFAULT_MONACO_DIR, MonacoDiffView


def _model_tooltip(info) -> str:
    """Per-item tooltip: the facts that actually help pick a model."""
    lines = [info.name]
    if info.parameter_size:
        lines.append(f"{info.parameter_size} parameters")
    if info.size_label:
        lines.append(f"{info.size_label} on disk" if not info.is_remote else "runs on ollama.com")
    if info.family:
        lines.append(f"family: {info.family}")
    extras = []
    if info.supports_vision:
        extras.append("vision")
    if info.supports_thinking:
        # Relevant because reasoning models stream a chain of thought; the app
        # sends `think: false` so they answer directly (see streaming.py).
        extras.append("reasoning")
    if extras:
        lines.append("supports: " + ", ".join(extras))
    if info.is_remote:
        lines.append("⚠ cloud model — file contents leave this machine")
    return "\n".join(lines)


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #888; font-size: 11px; margin-top: 4px;")
    return label

# Buttons, in the order they appear. Explain is first because it's the only
# non-mutating action and the safest thing to try on unfamiliar code.
_ACTION_ORDER = (
    EditAction.EXPLAIN,
    EditAction.REFACTOR,
    EditAction.FIX,
    EditAction.OPTIMISE,
    EditAction.ADD_COMMENTS,
    EditAction.GENERATE_TESTS,
)


class AIPanel(QWidget, _DictationMixin):
    """AI actions, streaming chat, and diff review for the active file.

    Also hosts the project-wide actions carried over from the retired Coding
    Agent tab (multi-file plan/apply, dev server), since they're AI/project
    concerns rather than editor ones.
    """

    # (action, instruction) — the tab turns these into worker runs.
    action_requested = pyqtSignal(object, str)
    accept_requested = pyqtSignal(str)  # final content to write
    reject_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    # Project-wide, carried over from the Coding Agent tab.
    plan_requested = pyqtSignal(str)  # issue description
    apply_plan_requested = pyqtSignal()
    dev_server_requested = pyqtSignal()
    stop_dev_server_requested = pyqtSignal()
    new_session_requested = pyqtSignal()
    describe_project_requested = pyqtSignal()
    reindex_requested = pyqtSignal()
    refresh_models_requested = pyqtSignal()
    build_kb_requested = pyqtSignal()
    build_general_kb_requested = pyqtSignal()
    # Emitted instead of action_requested when there's no file to act on — the
    # model answers from its own knowledge rather than from project context.
    general_chat_requested = pyqtSignal(str)

    def __init__(self, monaco_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._monaco_dir = Path(monaco_dir) if monaco_dir else DEFAULT_MONACO_DIR
        self._active_file: Optional[str] = None
        self._selection = ""
        self._busy = False
        self._has_proposal = False
        self._project_open = False

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(
            "Ask anything — with no repository open, answers come from the model's own "
            "knowledge.\n\n"
            "Open a file to unlock the actions above, and select code first to scope an "
            "action to just that part."
        )

        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        self.context_label.setStyleSheet("color: #888;")
        self._update_context_label()  # one source of truth for this text

        # Populated from Ollama itself (see set_models); the installed models are
        # a property of the user's machine, not something to hardcode. Starts with
        # the configured default so there's always a usable value even before the
        # list arrives — or if Ollama is down.
        self.model_combo = QComboBox()
        self._fallback_model = normalize_name(settings.get("assistant.model", PREFERRED_DEFAULT))
        self.model_combo.addItem(self._fallback_model, self._fallback_model)
        self.model_combo.setToolTip("Which local Ollama model runs these actions")
        self.refresh_models_btn = QPushButton("↻")
        self.refresh_models_btn.setFixedWidth(30)
        self.refresh_models_btn.setToolTip("Re-check which models Ollama has installed")
        self.refresh_models_btn.clicked.connect(self.refresh_models_requested)

        self._action_buttons = {}
        for action in _ACTION_ORDER:
            button = QPushButton(action.label)
            button.clicked.connect(lambda _checked=False, a=action: self._request(a))
            self._action_buttons[action] = button

        self.prompt_input = ChatInput()
        self.prompt_input.setPlaceholderText(
            "Ask a question, or describe a change... (Enter to send, Shift+Enter for a new line)"
        )
        self.prompt_input.setFixedHeight(64)
        self.prompt_input.submitted.connect(self._request_implement)
        # Send follows what's typed, so it enables as soon as there's a prompt.
        self.prompt_input.textChanged.connect(self._sync_enabled)
        # _DictationMixin writes transcribed text into `question_input`; the same
        # widget under the name that mixin expects.
        self.question_input = self.prompt_input

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._request_implement)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        # Speak a prompt instead of typing it — same worker and local whisper
        # model as the Assistant tab's dictation.
        self._build_dictate_button()
        self.dictate_btn.setText("🎤")
        self.dictate_btn.setFixedWidth(40)

        # -- project-wide actions (from the retired Coding Agent tab) ------
        self.plan_btn = QPushButton("Plan Multi-File Change")
        self.plan_btn.setToolTip(
            "Describe an issue above, then plan a change across several files. Applying a plan "
            "writes to a new git branch — unlike the single-file actions, which edit in place."
        )
        self.plan_btn.clicked.connect(self._request_plan)
        self.apply_plan_btn = QPushButton("Apply Plan")
        self.apply_plan_btn.setVisible(False)
        self.apply_plan_btn.clicked.connect(self.apply_plan_requested)
        self.dev_server_btn = QPushButton("Run Dev Server")
        self.dev_server_btn.setToolTip("Detect and start this project's dev server, then open Chrome")
        self.dev_server_btn.clicked.connect(self.dev_server_requested)
        self.stop_dev_server_btn = QPushButton("Stop Dev Server")
        self.stop_dev_server_btn.setVisible(False)
        self.stop_dev_server_btn.clicked.connect(self.stop_dev_server_requested)
        self.new_session_btn = QPushButton("New Session")
        self.new_session_btn.setToolTip("Clear the transcript and this project's saved chat history")
        self.new_session_btn.clicked.connect(self.new_session_requested)
        self.describe_btn = QPushButton("Describe Project")
        self.describe_btn.setToolTip(
            "Summarise this project's architecture from the Knowledge Bank. Slow the first "
            "time, then cached until the project's shape changes."
        )
        self.describe_btn.clicked.connect(self.describe_project_requested)
        self.build_kb_btn = QPushButton("Update Knowledge Banks")
        self.build_kb_btn.setToolTip(
            "Update both knowledge banks: this repository's (architecture, symbols, module "
            "graph, APIs, history) and the general one built from your captured meetings "
            "and screen activity. Incremental — only what changed is re-read."
        )
        self.build_kb_btn.clicked.connect(self.build_kb_requested)
        self.reindex_btn = QPushButton("Rebuild From Scratch")
        self.reindex_btn.setToolTip(
            "Discard the Knowledge Bank and rebuild it from scratch. Only needed if the "
            "index looks wrong — normally 'Build / Update KB' is enough."
        )
        self.reindex_btn.clicked.connect(self.reindex_requested)

        # -- review mode --------------------------------------------------
        self.diff_view = MonacoDiffView(monaco_dir=self._monaco_dir)
        self.diff_header = QLabel("")
        self.diff_header.setWordWrap(True)
        self.accept_btn = QPushButton("✓ Accept")
        self.accept_btn.setToolTip("Write this to the file (a backup is kept)")
        self.accept_btn.clicked.connect(self._accept)
        self.reject_btn = QPushButton("✗ Reject")
        self.reject_btn.setToolTip("Discard this proposal — the file is untouched")
        self.reject_btn.clicked.connect(self._reject)
        self.edit_hint = QLabel("The right-hand side is editable — adjust it before accepting.")
        self.edit_hint.setStyleSheet("color: #888;")
        self.edit_hint.setWordWrap(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_chat_page())
        self.stack.addWidget(self._build_review_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(self.stack)
        self._sync_enabled()

    def _build_chat_page(self) -> QWidget:
        actions = QGridLayout()
        for index, action in enumerate(_ACTION_ORDER):
            actions.addWidget(self._action_buttons[action], index // 2, index % 2)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_models_btn)
        model_row.addWidget(self.new_session_btn)

        input_row = QHBoxLayout()
        input_row.addWidget(self.dictate_btn)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.stop_btn)

        project_row = QGridLayout()
        project_row.addWidget(self.plan_btn, 0, 0)
        project_row.addWidget(self.apply_plan_btn, 0, 1)
        project_row.addWidget(self.dev_server_btn, 1, 0)
        project_row.addWidget(self.stop_dev_server_btn, 1, 1)
        project_row.addWidget(self.build_kb_btn, 2, 0)
        project_row.addWidget(self.reindex_btn, 2, 1)
        project_row.addWidget(self.describe_btn, 3, 0)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("AI Assistant"))
        layout.addWidget(self.context_label)
        layout.addLayout(model_row)
        layout.addLayout(actions)
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self.prompt_input)
        layout.addLayout(input_row)
        layout.addWidget(_section_label("Whole project"))
        layout.addLayout(project_row)
        layout.addWidget(self.status_label)
        return page

    def _build_review_page(self) -> QWidget:
        decision_row = QHBoxLayout()
        decision_row.addWidget(self.accept_btn)
        decision_row.addWidget(self.reject_btn)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Review changes"))
        layout.addWidget(self.diff_header)
        layout.addWidget(self.diff_view, 1)
        layout.addWidget(self.edit_hint)
        layout.addLayout(decision_row)
        return page

    # -- context from the editor -------------------------------------------

    def set_active_file(self, rel_path: Optional[str]) -> None:
        self._active_file = rel_path
        self._selection = ""
        self._update_context_label()
        self._sync_enabled()

    def set_selection(self, selection: str) -> None:
        self._selection = selection or ""
        self._update_context_label()

    def _update_context_label(self) -> None:
        if not self._active_file:
            self.context_label.setText(
                "No file open — questions are answered from the model's general knowledge."
            )
            return
        if self._selection.strip():
            lines = self._selection.count("\n") + 1
            self.context_label.setText(
                f"{self._active_file} — acting on {lines} selected line(s)"
            )
        else:
            self.context_label.setText(f"{self._active_file} — acting on the whole file")

    # -- requests ----------------------------------------------------------

    def _request(self, action: EditAction) -> None:
        self.action_requested.emit(action, self.prompt_input.toPlainText().strip())

    def _request_implement(self) -> None:
        """Sends the prompt box's text.

        Routes on whether there's a file to act on: with one open this is an
        IMPLEMENT edit request; without one it's a plain question, answered from
        the model's own knowledge. That means the panel is useful before a
        repository has even been opened, rather than being inert.
        """
        instruction = self.prompt_input.toPlainText().strip()
        if not instruction:
            self.status_label.setText("Type something first, or pick an action above.")
            return
        if self._active_file:
            self.action_requested.emit(EditAction.IMPLEMENT, instruction)
        else:
            self.general_chat_requested.emit(instruction)

    def _request_plan(self) -> None:
        issue = self.prompt_input.toPlainText().strip()
        if not issue:
            self.status_label.setText("Describe the change first, then plan it.")
            return
        self.plan_requested.emit(issue)

    def set_plan_available(self, available: bool) -> None:
        """Reveals "Apply Plan" once a plan exists to apply."""
        self.apply_plan_btn.setVisible(available)
        self._sync_enabled()

    def set_dev_server_running(self, running: bool) -> None:
        self.stop_dev_server_btn.setVisible(running)
        self.dev_server_btn.setVisible(not running)

    def clear_transcript(self) -> None:
        self.transcript.clear()

    def build_request(self, project_path: str, action: EditAction, instruction: str) -> EditRequest:
        """Assembles the request from the panel's current context."""
        return EditRequest(
            project_path=project_path,
            rel_path=self._active_file or "",
            action=action,
            instruction=instruction,
            selection=self._selection,
        )

    def clear_prompt(self) -> None:
        self.prompt_input.clear()

    @property
    def model(self) -> str:
        """The model name to send to Ollama.

        Read from the item's data rather than its text: the visible label carries
        size/parameter annotations ("gemma4  (8.0B, 9.6GB)") that Ollama wouldn't
        recognise.
        """
        data = self.model_combo.currentData()
        return data or self.model_combo.currentText()

    def set_models(self, models) -> None:
        """Replaces the dropdown's contents with what Ollama reported.

        Preserves the current selection if that model is still present, so a
        refresh doesn't silently switch which model the user picked.
        """
        previous = self.model
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for info in models:
            self.model_combo.addItem(info.label, info.name)
            index = self.model_combo.count() - 1
            self.model_combo.setItemData(index, _model_tooltip(info), Qt.ItemDataRole.ToolTipRole)
        self.model_combo.blockSignals(False)

        names = [info.name for info in models]
        target = previous if previous in names else choose_default(names, self._fallback_model)
        if target is not None:
            found = self.model_combo.findData(target)
            if found >= 0:
                self.model_combo.setCurrentIndex(found)
        self.model_combo.setToolTip(
            f"{len(models)} model(s) installed in Ollama — the AI actions use the selected one"
            if models
            else "Could not reach Ollama; showing the configured default"
        )

    # -- transcript --------------------------------------------------------

    def append_user(self, text: str) -> None:
        self.transcript.append(f"\nYou: {text}\n")

    def append_assistant_prefix(self) -> None:
        self.transcript.insertPlainText("Shadow: ")

    def append_chunk(self, chunk: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.transcript.setTextCursor(cursor)
        self.transcript.insertPlainText(chunk)

    def append_note(self, text: str) -> None:
        self.transcript.append(f"\n{text}\n")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # -- review mode -------------------------------------------------------

    def show_proposal(self, proposal) -> None:
        self._has_proposal = True
        self.diff_header.setText(
            f"{proposal.rel_path} — {proposal.stats.summary()} "
            f"({proposal.action.label}, {proposal.strategy.replace('_', ' ')})"
        )
        if proposal.warnings:
            self.diff_header.setText(
                self.diff_header.text() + "\n⚠ " + "\n⚠ ".join(proposal.warnings)
            )
        self.diff_view.set_diff(proposal.original, proposal.proposed, proposal.rel_path)
        self.diff_view.set_proposed_editable(True)
        self.stack.setCurrentIndex(1)
        self._sync_enabled()

    def _accept(self) -> None:
        # Read the proposed side rather than using the stored proposal, so any
        # manual adjustment the user made in the diff is what gets written.
        self.accept_btn.setEnabled(False)
        self.diff_view.get_proposed(self.accept_requested.emit)

    def _reject(self) -> None:
        self.reject_requested.emit()
        self.return_to_chat()

    def return_to_chat(self) -> None:
        self._has_proposal = False
        self.stack.setCurrentIndex(0)
        self._sync_enabled()

    # -- enable/disable ----------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._sync_enabled()

    def set_project_open(self, is_open: bool) -> None:
        """Project-wide actions need a repository but not an open file."""
        self._project_open = is_open
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        has_file = bool(self._active_file)
        idle = not self._busy and not self._has_proposal
        # Send is gated on there being something to send — not on a file or repo
        # being open, since with neither it still answers as a plain question.
        has_text = bool(self.prompt_input.toPlainText().strip())
        for button in self._action_buttons.values():
            button.setEnabled(has_file and idle)
        self.send_btn.setEnabled(has_text and idle)
        # Always typable: this is the box for questions, edit instructions, and a
        # multi-file plan's issue description alike.
        self.prompt_input.setEnabled(not self._busy)
        self.stop_btn.setEnabled(self._busy)
        self.model_combo.setEnabled(not self._busy)
        self.refresh_models_btn.setEnabled(not self._busy)
        self.accept_btn.setEnabled(self._has_proposal and not self._busy)
        self.reject_btn.setEnabled(self._has_proposal and not self._busy)

        project_idle = self._project_open and idle
        self.plan_btn.setEnabled(project_idle)
        self.apply_plan_btn.setEnabled(project_idle)
        self.build_kb_btn.setEnabled(project_idle)
        self.dev_server_btn.setEnabled(self._project_open and not self._busy)
        self.stop_dev_server_btn.setEnabled(self._project_open)
        self.new_session_btn.setEnabled(project_idle)
        self.describe_btn.setEnabled(project_idle)
        self.reindex_btn.setEnabled(self._project_open and not self._busy)

    def shutdown(self) -> None:
        self._shutdown_dictation()  # releases the mic if a recording is in flight
        self.diff_view.shutdown()
