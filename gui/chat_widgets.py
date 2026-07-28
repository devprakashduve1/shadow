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

from .workers import DictationWorker, LiveDictationWorker


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
    AudioCapture + SpeechToText pipeline as the call-transcript feature, so it
    needs the same `audio.*` / `speech.*` config and mic permission — but unlike
    that feature it's fully on demand, only recording between the two clicks, and
    never writes the audio or its transcript to disk.

    Two engines behind one button, chosen by `speech.live.enabled`:

    - **live** (default) — `LiveDictationWorker` transcribes as you speak, so
      text lands in the box while you're still talking.
    - **one-shot** — `DictationWorker` records, then transcribes once at the end.
      Kept as a fallback because live mode re-transcribes the sentence in
      progress every second or so, which is real work on a slow machine.

    Assumes the including widget defines `self.question_input` (ChatInput) and
    `self.status_label` (QLabel), and calls `_build_dictate_button()` in its
    `__init__` to create `self.dictate_btn`. `_update_action_buttons()` is
    called after a dictation finishes if the widget defines one (`AIPanel`
    does, AssistantTab manages its buttons inline instead).
    """

    _DICTATE_LABEL = "🎤 Dictate"
    _DICTATE_STOP_LABEL = "■ Stop recording"

    def _build_dictate_button(
        self, label: str | None = None, stop_label: str | None = None
    ) -> QPushButton:
        """Creates `self.dictate_btn` wired to `_toggle_dictation`.

        `label`/`stop_label` override the defaults for a host with no room for
        them — `AIPanel`'s button is icon-width. They're remembered rather than
        applied once, because the button's text is rewritten on every start and
        stop, which would otherwise put the long default back.
        """
        self._dictate_idle_label = label or self._DICTATE_LABEL
        self._dictate_stop_label = stop_label or self._DICTATE_STOP_LABEL
        self._dictation_worker = None
        # Text committed by this dictation, kept apart from what the user had
        # already typed so an interim result can be re-rendered without
        # disturbing either.
        self._dictation_base = ""
        self._dictation_finals: list[str] = []
        self._dictation_failed = False
        self.dictate_btn = QPushButton(self._dictate_idle_label)
        self.dictate_btn.setToolTip(
            "Speak your prompt instead of typing it. Transcribed locally with the same "
            "faster-whisper model as call transcripts (config: speech.model_size); the "
            "recording is never saved to disk."
        )
        self.dictate_btn.clicked.connect(self._toggle_dictation)
        return self.dictate_btn

    def _dictation_progress(self):
        """The host's progress indicator, if it has one.

        Optional so `_DictationMixin` stays usable by a host without one — both
        current consumers do have one, but the mixin shouldn't require it.
        """
        return getattr(self, "progress", None)

    def _on_dictation_stage(self, stage: str) -> None:
        """Reflects the worker's reported stage on the progress indicator.

        Driven by an explicit `stage` signal rather than by matching the status
        text, so the wording stays free to change without breaking this.
        """
        indicator = self._dictation_progress()
        if indicator is None:
            return
        if indicator.state.active:
            indicator.set_stage(stage)
        else:
            # The worker's first stage report is what starts the indicator, so
            # there's never a moment showing a stage it isn't in yet.
            indicator.begin(stage=stage)

    @property
    def is_dictating(self) -> bool:
        """True while the microphone is open for dictation.

        Read by the consent badge (see `MainWindow._update_consent_badge`), which
        must not claim the mic is idle while this is recording.
        """
        worker = getattr(self, "_dictation_worker", None)
        return worker is not None and bool(getattr(worker, "is_recording", True))

    def _toggle_dictation(self) -> None:
        if self._dictation_worker is not None:
            # Second click: stop recording. Any sentence still in progress is
            # flushed before the worker finishes.
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
        # Preserved so dictation composes with what's already typed rather than
        # clobbering it — the same intent as the old append-on-finish behaviour.
        self._dictation_base = self.question_input.toPlainText().strip()
        self._dictation_finals = []
        self._dictation_failed = False

        if settings.get("speech.live.enabled", True):
            self._dictation_worker = LiveDictationWorker(
                audio_cfg,
                speech_cfg,
                live_cfg=dict(
                    interim_interval_seconds=settings.get(
                        "speech.live.interim_interval_seconds", 1.5
                    ),
                    silence_seconds=settings.get("speech.live.silence_seconds", 0.8),
                    max_utterance_seconds=settings.get("speech.live.max_utterance_seconds", 20.0),
                ),
            )
            self._dictation_worker.partial_ready.connect(self._on_dictation_partial)
            self._dictation_worker.final_ready.connect(self._on_dictation_final)
            self._dictation_worker.finished.connect(self._on_live_dictation_finished)
        else:
            self._dictation_worker = DictationWorker(audio_cfg, speech_cfg)
            self._dictation_worker.finished_ok.connect(self._on_dictation_ready)

        self._dictation_worker.status.connect(self.status_label.setText)
        self._dictation_worker.stage.connect(self._on_dictation_stage)
        self._dictation_worker.error.connect(self._on_dictation_error)
        self._dictation_worker.start()
        self.dictate_btn.setText(self._dictate_stop_label)
        self.status_label.setText("Recording — click again when you're done speaking.")

    # -- rendering ---------------------------------------------------------

    def _dictation_text(self, interim: str = "") -> str:
        """Assembles the box's contents: typed text + finals + any interim."""
        parts = [self._dictation_base, *self._dictation_finals]
        if interim:
            parts.append(interim)
        return " ".join(part for part in parts if part).strip()

    def _show_dictation_text(self, interim: str = "") -> None:
        self.question_input.setPlainText(self._dictation_text(interim))
        # Keeps the caret after the newest words instead of at position zero,
        # so typing straight after dictating continues the sentence.
        cursor = self.question_input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.question_input.setTextCursor(cursor)

    def _on_dictation_partial(self, text: str) -> None:
        """An interim reading of the current sentence — replaces the last one."""
        self._show_dictation_text(interim=text)
        self.status_label.setText("Listening...")

    def _on_dictation_final(self, text: str) -> None:
        self._dictation_finals.append(text)
        self._show_dictation_text()

    def _on_live_dictation_finished(self) -> None:
        """Live mode commits text as it arrives, so there's nothing left to insert."""
        if self._dictation_finals:
            self._show_dictation_text()
            self.question_input.setFocus()
            self.status_label.setText("Dictated — review it, then send.")
        elif not self._dictation_failed:
            # Left alone when it failed, so the error message stays on screen
            # rather than being overwritten by the friendlier "try again".
            self.status_label.setText("Didn't catch anything — try again, closer to the mic.")
        self._reset_dictation()

    def _reset_dictation(self) -> None:
        if self._dictation_worker is not None:
            self._dictation_worker.wait()  # see _StreamingChatMixin's docstring
        self._dictation_worker = None
        # The single funnel every dictation outcome passes through, so the one
        # place that has to clear the indicator.
        indicator = self._dictation_progress()
        if indicator is not None:
            indicator.end()
        self.dictate_btn.setText(self._dictate_idle_label)
        self.dictate_btn.setEnabled(True)
        if hasattr(self, "_update_action_buttons"):
            self._update_action_buttons()

    def _on_dictation_ready(self, text: str) -> None:
        """One-shot mode's single result, delivered after recording stops."""
        if text:
            self._dictation_finals = [text]
            self._show_dictation_text()
            self.question_input.setFocus()
            self.status_label.setText("Dictated — review it, then send.")
        else:
            self.status_label.setText("Didn't catch anything — try again, closer to the mic.")
        self._reset_dictation()

    def _on_dictation_error(self, message: str) -> None:
        self._dictation_failed = True
        self.status_label.setText(f"Dictation failed: {message}")
        # Live mode reports errors from inside run(), so `finished` follows and
        # resets there; doing it here too would reset twice.
        if not isinstance(self._dictation_worker, LiveDictationWorker):
            self._reset_dictation()

    def _shutdown_dictation(self) -> None:
        """Stops any in-flight dictation — call from the tab's `shutdown()`."""
        if getattr(self, "_dictation_worker", None) is not None:
            self._dictation_worker.stop_recording()
            self._dictation_worker.wait(5000)
        indicator = self._dictation_progress()
        if indicator is not None:
            indicator.cancel()  # shutting down, so skip the completion linger


