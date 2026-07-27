"""Shared chat widgets: the multi-line input box and voice dictation.

Extracted from `gui/dashboard.py` so both the Assistant/Coding Agent tabs and
the Code tab's AI panel (`gui/ide/ai_panel.py`) can use them. Keeping them in
dashboard.py would make `gui.ide` import `gui.dashboard`, which imports
`gui.ide` — a cycle that fails at class-definition time for anything using
`_DictationMixin` as a base class.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QPlainTextEdit, QPushButton

from config import settings

from .workers import DictationWorker


class ChatInput(QPlainTextEdit):
    """Multi-line chat input — Enter sends, Shift+Enter inserts a newline.

    A plain QLineEdit can't hold more than one line, which makes it awkward
    to paste in a multi-line issue description or a short stack trace. Used
    by the Assistant tab and the Code tab's AI panel. QPlainTextEdit has no
    `returnPressed` signal (unlike QLineEdit) and would otherwise just insert
    a newline on Enter, so this reproduces the common chat-app convention
    (Slack/Discord/etc.) on top of it.
    """

    submitted = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class _DictationMixin:
    """Adds a "Dictate" toggle that speaks a prompt into `self.question_input`.

    Used by `AssistantTab` and the Code tab's `AIPanel`. Reuses the same
    AudioCapture + SpeechToText pipeline as the call-transcript feature (see
    `gui/workers.py`'s `DictationWorker`), so it needs the same `audio.*` /
    `speech.*` config and mic permission — but unlike that feature it's fully
    on demand, only recording between the two clicks, and never writes the
    audio or its transcript to disk.

    Assumes the including widget defines `self.question_input` (ChatInput) and
    `self.status_label` (QLabel), and calls `_build_dictate_button()` in its
    `__init__` to create `self.dictate_btn`. `_update_action_buttons()` is
    called after a dictation finishes if the widget defines one (`AIPanel`
    does, AssistantTab manages its buttons inline instead).
    """

    _DICTATE_LABEL = "🎤 Dictate"
    _DICTATE_STOP_LABEL = "■ Stop recording"

    def _build_dictate_button(self) -> QPushButton:
        """Creates `self.dictate_btn` wired to `_toggle_dictation`."""
        self._dictation_worker: DictationWorker | None = None
        self.dictate_btn = QPushButton(self._DICTATE_LABEL)
        self.dictate_btn.setToolTip(
            "Speak your prompt instead of typing it. Transcribed locally with the same "
            "faster-whisper model as call transcripts (config: speech.model_size); the "
            "recording is never saved to disk."
        )
        self.dictate_btn.clicked.connect(self._toggle_dictation)
        return self.dictate_btn

    def _toggle_dictation(self) -> None:
        if self._dictation_worker is not None:
            # Second click: stop recording. The worker then transcribes what it
            # captured and comes back via _on_dictation_ready.
            self._dictation_worker.stop_recording()
            self.dictate_btn.setEnabled(False)
            self.status_label.setText("Transcribing...")
            return

        audio_cfg = dict(
            device_index=settings.get("audio.device_index", None),
            sample_rate=settings.get("audio.sample_rate", 16000),
            channels=settings.get("audio.channels", 1),
        )
        speech_cfg = dict(
            model_size=settings.get("speech.model_size", "base"),
            language=settings.get("speech.language", "en"),
        )
        self._dictation_worker = DictationWorker(audio_cfg, speech_cfg)
        self._dictation_worker.finished_ok.connect(self._on_dictation_ready)
        self._dictation_worker.status.connect(self.status_label.setText)
        self._dictation_worker.error.connect(self._on_dictation_error)
        self._dictation_worker.start()
        self.dictate_btn.setText(self._DICTATE_STOP_LABEL)
        self.status_label.setText("Recording — click again when you're done speaking.")

    def _reset_dictation(self) -> None:
        self._dictation_worker.wait()  # see _StreamingChatMixin's docstring
        self._dictation_worker = None
        self.dictate_btn.setText(self._DICTATE_LABEL)
        self.dictate_btn.setEnabled(True)
        if hasattr(self, "_update_action_buttons"):
            self._update_action_buttons()

    def _on_dictation_ready(self, text: str) -> None:
        if text:
            # Appended, not replaced: dictation is meant to compose with typing
            # (and with a second dictation) rather than clobber the box.
            existing = self.question_input.toPlainText()
            self.question_input.setPlainText(f"{existing} {text}".strip() if existing else text)
            self.question_input.setFocus()
            self.status_label.setText("Dictated — review it, then send.")
        else:
            self.status_label.setText("Didn't catch anything — try again, closer to the mic.")
        self._reset_dictation()

    def _on_dictation_error(self, message: str) -> None:
        self.status_label.setText(f"Dictation failed: {message}")
        self._reset_dictation()

    def _shutdown_dictation(self) -> None:
        """Stops any in-flight dictation — call from the tab's `shutdown()`."""
        if getattr(self, "_dictation_worker", None) is not None:
            self._dictation_worker.stop_recording()
            self._dictation_worker.wait(2000)


