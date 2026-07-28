"""PyQt6 dashboard: live camera/screen preview, module toggles, and log search."""
from __future__ import annotations

import cv2
import numpy as np
from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assistant import ChatEngine
from config import settings
from database.json_store import EventStore
from gesture import GestureResult
from logger import DataLogger
from search import SearchEngine

from .chat_widgets import ChatInput, _DictationMixin
from .progress import AIProgressIndicator
from .ide import IDETab
from .workers import (
    CallVoiceCaptureWorker,
    ChatWorker,
    GestureWorker,
    ScreenOcrWorker,
    SpellCheckWorker,
    SuggestedQuestionsWorker,
    SummarizeWorker,
)


class SpellSuggestionPopup(QWidget):
    """Small, non-modal, auto-dismissing toast shown near the screen corner.

    Parented to the calling widget (rather than left top-level with no
    owner) so Qt keeps the underlying object alive until its own close()
    fires, instead of relying on a manually-tracked Python list.
    """

    DISPLAY_MS = 7000

    def __init__(
        self,
        word: str,
        suggestions: list[str],
        parent: QWidget,
        title: str = "Possible misspelling",
        stack_offset: int = 0,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        suggestion_text = f"Suggestions: {', '.join(suggestions)}" if suggestions else "No suggestions"
        label = QLabel(f'{title}: "{word}"\n{suggestion_text}')
        label.setStyleSheet(
            "background-color: #2b2b2b; color: white; padding: 10px; border-radius: 6px;"
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        self.setLayout(layout)

        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            # Stack upward from the corner (stack_offset accounts for other
            # currently-visible popups) so multiple in quick succession don't
            # render on top of each other and appear to vanish instantly.
            self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 20 - stack_offset)

        QTimer.singleShot(self.DISPLAY_MS, self.close)


class CallAlertPopup(QWidget):
    """Small, non-modal, auto-dismissing toast announcing a newly detected call/huddle/meeting.

    Shown top-right (vs. SpellSuggestionPopup's bottom-right) so the two
    never overlap even if both fire around the same time.
    """

    DISPLAY_MS = 6000

    _SOURCE_LABELS = {
        "slack": "Slack huddle",
        "google_meet": "Google Meet",
        "zoom": "Zoom meeting",
        "teams": "Microsoft Teams meeting",
        "webex": "Webex meeting",
        "gotomeeting": "GoToMeeting",
        "whereby": "Whereby meeting",
        "around": "Around meeting",
        "facetime": "FaceTime call",
        "skype": "Skype call",
    }

    def __init__(self, source: str, label: str, parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        kind = self._SOURCE_LABELS.get(source, source or "Call")
        text = f"\U0001F4DE {kind} detected"
        if label:
            text += f"\n{label}"
        message = QLabel(text)
        message.setStyleSheet(
            "background-color: #1b4d2e; color: white; padding: 10px; border-radius: 6px;"
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(message)
        self.setLayout(layout)

        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 20, geo.top() + 20)

        QTimer.singleShot(self.DISPLAY_MS, self.close)


def _to_pixmap(frame_rgb: np.ndarray) -> QPixmap:
    h, w, ch = frame_rgb.shape
    image = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image)


class LiveMonitorTab(QWidget):
    def __init__(self, logger: DataLogger, parent=None):
        super().__init__(parent)
        self._logger = logger

        self.camera_label = QLabel("Camera preview will appear here")
        self.camera_label.setMinimumSize(360, 270)
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setStyleSheet("background-color: #202020; color: #aaa;")

        self.screen_label = QLabel("Screen preview will appear here")
        self.screen_label.setMinimumSize(360, 270)
        self.screen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_label.setStyleSheet("background-color: #202020; color: #aaa;")

        self.gesture_status = QLabel("Gesture: --")
        self.window_status = QLabel("Active window: --")
        self.ocr_output = QTextEdit()
        self.ocr_output.setReadOnly(True)

        self.start_gesture_btn = QPushButton("Start Camera/Gesture")
        self.stop_gesture_btn = QPushButton("Stop Camera/Gesture")
        self.stop_gesture_btn.setEnabled(False)
        self.mouse_control_checkbox = QCheckBox("Enable mouse control")
        self.disable_video_checkbox = QCheckBox("Disable video preview")

        self.screen_capture_checkbox = QCheckBox("Enable screen capture")
        self.ocr_checkbox = QCheckBox("Enable OCR on change")
        self.mouse_capture_checkbox = QCheckBox("Capture screen on every mouse click (system-wide)")

        self.call_detect_checkbox = QCheckBox("Enable call detection (watch for Slack/Google Meet calls)")
        self.call_transcribe_checkbox = QCheckBox("Enable voice transcription")
        self.call_status_label = QLabel("Voice capture disabled")
        self.call_transcript_output = QTextEdit()
        self.call_transcript_output.setReadOnly(True)

        self.spellcheck_checkbox = QCheckBox("Enable spell-check popups (types anywhere on this Mac, no exclusions)")
        self.spellcheck_status_label = QLabel("Spell-check disabled")

        self._gesture_worker: GestureWorker | None = None
        self._screen_worker: ScreenOcrWorker | None = None
        self._call_worker: CallVoiceCaptureWorker | None = None
        self._spellcheck_worker: SpellCheckWorker | None = None
        self._active_popups: list[SpellSuggestionPopup] = []

        self.start_gesture_btn.clicked.connect(self._start_gesture)
        self.stop_gesture_btn.clicked.connect(self._stop_gesture)
        self.mouse_control_checkbox.toggled.connect(self._toggle_mouse_control)
        self.screen_capture_checkbox.toggled.connect(self._toggle_screen_capture)
        self.ocr_checkbox.toggled.connect(self._toggle_ocr)
        self.mouse_capture_checkbox.toggled.connect(self._toggle_mouse_capture)
        self.disable_video_checkbox.toggled.connect(self._toggle_video_preview)
        self.call_detect_checkbox.toggled.connect(self._toggle_call_detect)
        self.call_transcribe_checkbox.toggled.connect(self._toggle_call_transcribe)
        self.spellcheck_checkbox.toggled.connect(self._toggle_spellcheck)

        self.disable_video_checkbox.setChecked(True)
        self.ocr_checkbox.setChecked(True)
        self.call_transcribe_checkbox.setChecked(True)

        self._build_layout()
        # Screen capture starts OFF by default and is only auto-enabled while
        # a Slack/Meet call is detected (see _on_call_active_changed) — call
        # detection must be started first so that signal can actually fire.
        self.call_detect_checkbox.setChecked(True)
        self.spellcheck_checkbox.setChecked(True)

    def _build_layout(self) -> None:
        camera_box = QGroupBox("Camera + Gesture")
        camera_layout = QVBoxLayout()
        camera_layout.addWidget(self.camera_label)
        camera_layout.addWidget(self.gesture_status)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_gesture_btn)
        btn_row.addWidget(self.stop_gesture_btn)
        camera_layout.addLayout(btn_row)
        camera_layout.addWidget(self.mouse_control_checkbox)
        camera_layout.addWidget(self.disable_video_checkbox)
        camera_box.setLayout(camera_layout)

        screen_box = QGroupBox("Screen + OCR")
        screen_layout = QVBoxLayout()
        screen_layout.addWidget(self.screen_label)
        screen_layout.addWidget(self.screen_capture_checkbox)
        screen_layout.addWidget(self.ocr_checkbox)
        screen_layout.addWidget(self.mouse_capture_checkbox)
        screen_layout.addWidget(self.window_status)
        screen_layout.addWidget(QLabel("Latest extracted text:"))
        screen_layout.addWidget(self.ocr_output)
        screen_box.setLayout(screen_layout)

        call_box = QGroupBox("Call Voice Capture (Slack / Google Meet)")
        call_layout = QVBoxLayout()
        call_layout.addWidget(self.call_detect_checkbox)
        call_layout.addWidget(self.call_transcribe_checkbox)
        call_layout.addWidget(self.call_status_label)
        call_layout.addWidget(QLabel("Transcript:"))
        call_layout.addWidget(self.call_transcript_output)
        call_box.setLayout(call_layout)

        spellcheck_box = QGroupBox("Spell Check (system-wide)")
        spellcheck_layout = QVBoxLayout()
        spellcheck_layout.addWidget(self.spellcheck_checkbox)
        spellcheck_layout.addWidget(self.spellcheck_status_label)
        spellcheck_box.setLayout(spellcheck_layout)

        top_row = QHBoxLayout()
        top_row.addWidget(camera_box)
        top_row.addWidget(screen_box)

        root = QVBoxLayout()
        root.addLayout(top_row)
        root.addWidget(call_box)
        root.addWidget(spellcheck_box)
        self.setLayout(root)

    def _start_gesture(self) -> None:
        if self._gesture_worker is not None:
            return
        camera_cfg = dict(
            device_index=settings.get("camera.device_index", 0),
            width=settings.get("camera.width", 640),
            height=settings.get("camera.height", 480),
            fps=settings.get("camera.fps", 30),
        )
        gesture_cfg = dict(
            max_hands=settings.get("gesture.max_hands", 1),
            detection_confidence=settings.get("gesture.detection_confidence", 0.7),
            tracking_confidence=settings.get("gesture.tracking_confidence", 0.7),
            pinch_click_threshold=settings.get("gesture.pinch_click_threshold", 0.04),
        )
        mouse_cfg = dict(smoothing=settings.get("gesture.smoothing", 0.5))

        self._gesture_worker = GestureWorker(camera_cfg, gesture_cfg, mouse_cfg)
        self._gesture_worker.frame_ready.connect(self._on_camera_frame)
        self._gesture_worker.gesture_ready.connect(self._on_gesture)
        self._gesture_worker.error.connect(self._on_worker_error)
        self._gesture_worker.mouse_control_enabled = self.mouse_control_checkbox.isChecked()
        self._gesture_worker.start()

        self.start_gesture_btn.setEnabled(False)
        self.stop_gesture_btn.setEnabled(True)

    def _stop_gesture(self) -> None:
        if self._gesture_worker is None:
            return
        self._gesture_worker.stop()
        self._gesture_worker = None
        self.start_gesture_btn.setEnabled(True)
        self.stop_gesture_btn.setEnabled(False)
        if not self.disable_video_checkbox.isChecked():
            self.camera_label.setText("Camera preview will appear here")
        self.gesture_status.setText("Gesture: --")

    def _toggle_screen_capture(self, checked: bool) -> None:
        if checked:
            self._start_screen()
        else:
            self._stop_screen()

    def _start_screen(self) -> None:
        if self._screen_worker is not None:
            return
        screen_cfg = dict(
            monitor_index=settings.get("screen.monitor_index", 0),
            change_threshold=settings.get("screen.change_threshold", 0.02),
            capture_interval_seconds=settings.get("screen.capture_interval_seconds", 1.0),
            excluded_apps=settings.get("screen.excluded_apps", []),
            excluded_domains=settings.get("screen.excluded_domains", []),
            capture_on_mouse_event=settings.get("screen.capture_on_mouse_event", False),
        )
        ocr_cfg = dict(
            engine=settings.get("ocr.engine", "easyocr"),
            languages=settings.get("ocr.languages", ["en"]),
            tesseract_cmd=settings.get("ocr.tesseract_cmd"),
        )
        self._screen_worker = ScreenOcrWorker(screen_cfg, ocr_cfg, self._logger)
        self._screen_worker.frame_ready.connect(self._on_screen_frame)
        self._screen_worker.text_extracted.connect(self._on_text_extracted)
        self._screen_worker.window_changed.connect(self._on_window_changed)
        self._screen_worker.error.connect(self._on_worker_error)
        self._screen_worker.ocr_enabled = self.ocr_checkbox.isChecked()
        self._screen_worker.capture_on_mouse_event = self.mouse_capture_checkbox.isChecked()
        self._screen_worker.start()

    def _stop_screen(self) -> None:
        if self._screen_worker is None:
            return
        self._screen_worker.stop()
        self._screen_worker = None
        self.screen_label.setText("Screen preview will appear here")
        self.window_status.setText("Active window: --")

    def _toggle_call_detect(self, checked: bool) -> None:
        if checked:
            self._start_call_capture()
        else:
            self._stop_call_capture()

    def _toggle_call_transcribe(self, checked: bool) -> None:
        if self._call_worker is not None:
            self._call_worker.transcription_enabled = checked

    def _start_call_capture(self) -> None:
        if self._call_worker is not None:
            return
        audio_cfg = dict(
            device_index=settings.get("audio.device_index"),
            sample_rate=settings.get("audio.sample_rate", 16000),
            channels=settings.get("audio.channels", 1),
            chunk_seconds=settings.get("audio.chunk_seconds", 5),
        )
        speech_cfg = dict(
            model_size=settings.get("speech.model_size", "base"),
            language=settings.get("speech.language", "en"),
        )
        poll_interval = settings.get("callwatch.poll_interval_seconds", 3.0)

        self._call_worker = CallVoiceCaptureWorker(audio_cfg, speech_cfg, self._logger, poll_interval)
        self._call_worker.status_changed.connect(self.call_status_label.setText)
        self._call_worker.transcript_ready.connect(self._on_call_transcript)
        self._call_worker.call_active_changed.connect(self._on_call_active_changed)
        self._call_worker.call_detected.connect(self._on_call_detected)
        self._call_worker.error.connect(self._on_call_worker_error)
        self._call_worker.transcription_enabled = self.call_transcribe_checkbox.isChecked()
        self._call_worker.start()

    def _stop_call_capture(self) -> None:
        if self._call_worker is None:
            return
        self._call_worker.stop()
        self._call_worker = None
        self.call_status_label.setText("Voice capture disabled")

    def _on_call_transcript(self, source: str, text: str) -> None:
        self.call_transcript_output.append(f"[{source}] {text}")

    def _on_call_detected(self, source: str, label: str) -> None:
        popup = CallAlertPopup(source, label, parent=self)
        popup.show()

    def _on_call_active_changed(self, active: bool) -> None:
        # Screen capture is off by default and only auto-enabled while a
        # call is detected, so screen context lines up with meeting audio.
        self.screen_capture_checkbox.setChecked(active)

    def _on_call_worker_error(self, message: str) -> None:
        self.call_status_label.setText(f"Error: {message}")

    def _toggle_spellcheck(self, checked: bool) -> None:
        if checked:
            self._start_spellcheck()
        else:
            self._stop_spellcheck()

    def _start_spellcheck(self) -> None:
        if self._spellcheck_worker is not None:
            return
        spellcheck_cfg = dict(
            language=settings.get("spellcheck.language", "en"),
            grammar_enabled=settings.get("spellcheck.grammar_enabled", True),
            grammar_language=settings.get("spellcheck.grammar_language", "en-US"),
        )
        self._spellcheck_worker = SpellCheckWorker(spellcheck_cfg)
        self._spellcheck_worker.misspelling_found.connect(self._on_misspelling_found)
        self._spellcheck_worker.grammar_issue_found.connect(self._on_grammar_issue_found)
        self._spellcheck_worker.error.connect(self._on_spellcheck_worker_error)
        self._spellcheck_worker.grammar_warning.connect(self._on_grammar_warning)
        self._spellcheck_worker.start()
        self.spellcheck_status_label.setText("Spell-check active — watching keystrokes system-wide, no exclusions")

    def _stop_spellcheck(self) -> None:
        if self._spellcheck_worker is None:
            return
        self._spellcheck_worker.stop()
        self._spellcheck_worker = None
        self.spellcheck_status_label.setText("Spell-check disabled")

    def _show_popup(self, word: str, suggestions: list, title: str) -> None:
        stack_offset = sum(p.height() + 10 for p in self._active_popups)
        popup = SpellSuggestionPopup(word, suggestions, parent=self, title=title, stack_offset=stack_offset)
        self._active_popups.append(popup)
        popup.destroyed.connect(lambda: self._active_popups.remove(popup) if popup in self._active_popups else None)
        popup.show()

    def _on_misspelling_found(self, word: str, suggestions: list) -> None:
        self._show_popup(word, suggestions, title="Possible misspelling")

    def _on_grammar_issue_found(self, sentence: str, message: str, replacements: list) -> None:
        self._show_popup(message, replacements, title="Possible grammar issue")

    def _on_spellcheck_worker_error(self, message: str) -> None:
        self.spellcheck_status_label.setText(f"Error: {message}")
        self.spellcheck_checkbox.setChecked(False)

    def _on_grammar_warning(self, message: str) -> None:
        # Non-fatal: spelling keeps running even if grammar checking degrades.
        self.spellcheck_status_label.setText(f"Spell-check active — {message}")

    def _toggle_mouse_control(self, checked: bool) -> None:
        if self._gesture_worker is not None:
            self._gesture_worker.mouse_control_enabled = checked

    def _toggle_ocr(self, checked: bool) -> None:
        if self._screen_worker is not None:
            self._screen_worker.ocr_enabled = checked

    def _toggle_mouse_capture(self, checked: bool) -> None:
        if self._screen_worker is not None:
            self._screen_worker.capture_on_mouse_event = checked

    def _toggle_video_preview(self, checked: bool) -> None:
        if checked:
            self.camera_label.clear()
            self.camera_label.setText("Video preview disabled")
        elif self._gesture_worker is None:
            self.camera_label.setText("Camera preview will appear here")

    def _on_camera_frame(self, frame_bgr: np.ndarray) -> None:
        if self.disable_video_checkbox.isChecked():
            return
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pixmap = _to_pixmap(np.ascontiguousarray(rgb))
        self.camera_label.setPixmap(pixmap.scaled(self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio))

    def _on_screen_frame(self, frame_rgb: np.ndarray) -> None:
        pixmap = _to_pixmap(np.ascontiguousarray(frame_rgb))
        self.screen_label.setPixmap(pixmap.scaled(self.screen_label.size(), Qt.AspectRatioMode.KeepAspectRatio))

    def _on_gesture(self, result: GestureResult) -> None:
        if not result.hand_present:
            self.gesture_status.setText("Gesture: no hand detected")
            return
        self.gesture_status.setText(f"Gesture: {result.gesture} ({result.handedness})")

    def _on_text_extracted(self, title: str, text: str) -> None:
        self.ocr_output.setPlainText(f"[{title}]\n{text}" if title else text)

    def _on_window_changed(self, app_name: str) -> None:
        self.window_status.setText(f"Active window: {app_name}")

    def _on_worker_error(self, message: str) -> None:
        self.gesture_status.setText(f"Error: {message}")

    def shutdown(self) -> None:
        self._stop_gesture()
        self._stop_screen()
        self._stop_call_capture()
        self._stop_spellcheck()

    def is_capturing(self) -> tuple[bool, bool]:
        """Returns (screen/OCR active, mic/voice active) — MainWindow's consent badge polls this.

        `mic_active` reflects `CallVoiceCaptureWorker.is_recording` — true only
        while a microphone AudioCapture is actually open, i.e. only during a
        live-detected huddle/meeting with transcription enabled — never just
        because call detection is running or the checkbox is on. The mic is
        never opened outside of a detected call (see
        `CallVoiceCaptureWorker.run` in `gui/workers.py`); this only makes the
        badge tell the truth about that, since a worker existing with
        transcription enabled does not by itself mean audio is being captured.
        """
        screen_active = self._screen_worker is not None
        mic_active = self._call_worker is not None and self._call_worker.is_recording
        return screen_active, mic_active


class SearchTab(QWidget):
    def __init__(self, logger: DataLogger, parent=None):
        super().__init__(parent)
        self._search_engine = SearchEngine(logger=logger)
        self._results: list = []
        self._summarize_worker: SummarizeWorker | None = None

        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("Keyword...")
        self.source_combo = QComboBox()
        self.source_combo.addItems(["all", "screen_ocr", "speech", "manual"])
        # QDateEdit() defaults to 2000-01-01, not today — anchor explicitly to
        # QDate.currentDate() or the default search range silently predates
        # every real log entry and always returns zero results.
        self.start_date = QDateEdit(calendarPopup=True)
        self.start_date.setDate(QDate.currentDate().addMonths(-1))
        self.end_date = QDateEdit(calendarPopup=True)
        self.end_date.setDate(QDate.currentDate())

        self.search_btn = QPushButton("Search")
        self.export_btn = QPushButton("Export CSV")
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Timestamp", "Source", "Title", "Text"])
        self.results_table.horizontalHeader().setStretchLastSection(True)

        self.summarize_instructions_input = QLineEdit()
        self.summarize_instructions_input.setPlaceholderText(
            "Optional: focus the summary on something specific (e.g. \"action items only\")"
        )
        self.summarize_btn = QPushButton("Summarize results")
        self.summary_status_label = QLabel("")
        self.summary_output = QTextEdit()
        self.summary_output.setReadOnly(True)
        self.summary_output.setPlaceholderText(
            "Run a search above, then click \"Summarize results\" to send the matching entries "
            "to a local Ollama model (config: summarize.model, default gemma4)."
        )

        self.search_btn.clicked.connect(self._run_search)
        self.export_btn.clicked.connect(self._export_results)
        self.summarize_btn.clicked.connect(self._run_summarize)

        self._build_layout()

    def _build_layout(self) -> None:
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Keyword:"))
        filters.addWidget(self.keyword_input)
        filters.addWidget(QLabel("Source:"))
        filters.addWidget(self.source_combo)
        filters.addWidget(QLabel("From:"))
        filters.addWidget(self.start_date)
        filters.addWidget(QLabel("To:"))
        filters.addWidget(self.end_date)
        filters.addWidget(self.search_btn)
        filters.addWidget(self.export_btn)

        summarize_box = QGroupBox("Summarize (local LLM via Ollama)")
        summarize_layout = QVBoxLayout()
        summarize_layout.addWidget(self.summarize_instructions_input)
        summarize_row = QHBoxLayout()
        summarize_row.addWidget(self.summarize_btn)
        summarize_row.addWidget(self.summary_status_label)
        summarize_layout.addLayout(summarize_row)
        summarize_layout.addWidget(self.summary_output)
        summarize_box.setLayout(summarize_layout)

        root = QVBoxLayout()
        root.addLayout(filters)
        root.addWidget(self.results_table)
        root.addWidget(summarize_box)
        self.setLayout(root)

    def _run_search(self) -> None:
        keyword = self.keyword_input.text().strip() or None
        source = self.source_combo.currentText()
        source = None if source == "all" else source
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()

        self._results = self._search_engine.search(keyword=keyword, source=source, start_date=start, end_date=end)
        self.results_table.setRowCount(len(self._results))
        for row, entry in enumerate(self._results):
            self.results_table.setItem(row, 0, QTableWidgetItem(entry.timestamp))
            self.results_table.setItem(row, 1, QTableWidgetItem(entry.source))
            self.results_table.setItem(row, 2, QTableWidgetItem(entry.extra.get("title", "")))
            self.results_table.setItem(row, 3, QTableWidgetItem(entry.text[:200]))

    def _export_results(self) -> None:
        if not self._results:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "shadow_export.csv", "CSV files (*.csv)")
        if path:
            self._search_engine.export_csv(self._results, __import__("pathlib").Path(path))

    def _run_summarize(self) -> None:
        if self._summarize_worker is not None:
            return  # a summarize call is already in flight
        if not self._results:
            message = "Run a search above first — there are no results to summarize yet."
            self.summary_status_label.setText(message)
            self.summary_output.setPlainText(message)
            return

        summarize_cfg = dict(
            base_url=settings.get("summarize.base_url", "http://localhost:11434"),
            model=settings.get("summarize.model", "gemma4"),
            timeout_seconds=settings.get("summarize.timeout_seconds", 180.0),
        )
        instructions = self.summarize_instructions_input.text().strip()

        # Change both the button label and the (large, hard-to-miss) output
        # box, not just the small status label next to the button — a
        # multi-second wait with only a subtle label change reads as "nothing
        # happened" rather than "in progress".
        self.summarize_btn.setEnabled(False)
        self.summarize_btn.setText("Summarizing...")
        progress_message = (
            f"Summarizing {len(self._results)} entries...\n\n"
            "This can take up to a minute or more, especially the first call after "
            "Ollama starts (loading the model into memory alone can take 10+ seconds)."
        )
        self.summary_status_label.setText("Working...")
        self.summary_output.setPlainText(progress_message)
        self._summarize_worker = SummarizeWorker(summarize_cfg, self._results, instructions)
        self._summarize_worker.finished_ok.connect(self._on_summary_ready)
        self._summarize_worker.error.connect(self._on_summary_error)
        self._summarize_worker.start()

    def _on_summary_ready(self, summary: str) -> None:
        self.summary_output.setPlainText(summary)
        self.summary_status_label.setText("Summary ready.")
        self._summarize_worker.wait()  # see _StreamingChatMixin's docstring
        self._summarize_worker = None
        self.summarize_btn.setEnabled(True)
        self.summarize_btn.setText("Summarize results")

    def _on_summary_error(self, message: str) -> None:
        self.summary_status_label.setText("Error — see details below.")
        self.summary_output.setPlainText(f"Error: {message}")
        self._summarize_worker.wait()
        self._summarize_worker = None
        self.summarize_btn.setEnabled(True)
        self.summarize_btn.setText("Summarize results")

    def shutdown(self) -> None:
        # One-shot worker with no stop()/running-loop of its own — just wait
        # for it to finish so Qt doesn't tear down a thread mid-flight.
        if self._summarize_worker is not None:
            self._summarize_worker.wait(2000)


class _StreamingChatMixin:
    """Shared chunk/finished/error handling for a QTextEdit-based chat transcript.

    Used by `AssistantTab`, which owns its own `_ask`/`_reset_worker`. Kept as
    a mixin rather than folded in because the Code tab's AI panel renders
    streamed chunks the same way (see `gui/ide/ai_panel.py`).

    Assumes the including widget defines `self.transcript` (QTextEdit),
    `self.status_label` (QLabel), and a `self._reset_worker()` method.

    IMPORTANT pattern followed everywhere a one-shot worker's own
    `finished_ok`/`error` signal clears its Python reference (here and in
    every other `_on_..._ready`/`_on_..._error` handler in this file): always
    call `worker.wait()` immediately before setting the attribute to `None`.
    A worker's `run()` emits its signal right before returning, but the
    underlying OS thread may not have fully unwound yet by the time the
    (queued, cross-thread) signal is delivered here — dropping the last
    Python reference at that instant can destroy the QThread object while
    Qt still considers it running, printing "QThread: Destroyed while thread
    is still running". `wait()` with no args blocks until the thread has
    truly finished, which by this point is either already true or a matter
    of microseconds — never a perceptible delay — and closes the race.
    """

    def _on_chunk(self, chunk: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.transcript.setTextCursor(cursor)
        self.transcript.insertPlainText(chunk)
        # First chunk moves the indicator from waiting to generating; optional so
        # a host without a progress bar still works.
        if getattr(self, "progress", None) is not None:
            self.progress.add_output(chunk)

    def _on_finished(self, citations: list) -> None:
        if citations:
            lines = "\n".join(
                f"  [{c['timestamp']}] ({c['type']}: {c.get('application') or c['source']}) {c['snippet']}"
                for c in citations
            )
            self.transcript.append(f"\nSources:\n{lines}\n")
        self.status_label.setText("")
        self._reset_worker()

    def _on_error(self, message: str) -> None:
        self.transcript.append(f"\n[Error: {message}]\n")
        self.status_label.setText("Error — see transcript.")
        self._reset_worker()


class AssistantTab(QWidget, _StreamingChatMixin, _DictationMixin):
    """Chat over the structured events database — see assistant/chat_engine.py.

    Requires the same local Ollama prerequisite as SearchTab's "Summarize
    results" (`ollama serve` + the configured model pulled); a connection
    failure surfaces as an inline transcript message rather than a crash.
    """

    def __init__(self, chat_engine: ChatEngine, parent=None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._chat_worker: ChatWorker | None = None
        self._suggestions_worker: SuggestedQuestionsWorker | None = None

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(
            'Ask about your captured activity, e.g. "What did I work on today?" '
            "(config: assistant.model, default gemma4 via Ollama)"
        )

        self.question_input = ChatInput()
        self.question_input.setPlaceholderText(
            "Ask a question about your day... (Enter to send, Shift+Enter for a new line)"
        )
        self.question_input.setFixedHeight(70)
        self.send_btn = QPushButton("Send")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.new_session_btn = QPushButton("New Session")
        self.status_label = QLabel("")
        self.progress = AIProgressIndicator()
        self._build_dictate_button()  # see _DictationMixin

        self.suggestions_row = QHBoxLayout()

        self.question_input.submitted.connect(self._send)
        self.send_btn.clicked.connect(self._send)
        self.stop_btn.clicked.connect(self._stop)
        self.new_session_btn.clicked.connect(self._new_session)

        self._build_layout()
        self._load_suggested_questions()

    def _build_layout(self) -> None:
        suggestions_box = QWidget()
        suggestions_box.setLayout(self.suggestions_row)

        top_row = QHBoxLayout()
        top_row.addStretch()
        top_row.addWidget(self.new_session_btn)

        input_row = QHBoxLayout()
        input_row.addWidget(self.question_input)
        input_row.addWidget(self.dictate_btn)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.stop_btn)

        root = QVBoxLayout()
        root.addLayout(top_row)
        root.addWidget(self.transcript)
        root.addWidget(suggestions_box)
        root.addLayout(input_row)
        root.addWidget(self.progress)
        root.addWidget(self.status_label)
        self.setLayout(root)

    def _load_suggested_questions(self) -> None:
        if self._suggestions_worker is not None:
            return  # already loading
        # Generation now calls the local LLM (grounded in today's actual
        # captured content) rather than picking from fixed templates, so —
        # same reasoning as SummarizeWorker/ChatWorker — this must run off
        # the GUI thread; it can take a real amount of time, especially the
        # first Ollama call after (re)start.
        self.status_label.setText("Loading suggested questions...")
        self._suggestions_worker = SuggestedQuestionsWorker(self._chat_engine)
        self._suggestions_worker.finished_ok.connect(self._on_suggestions_ready)
        self._suggestions_worker.error.connect(self._on_suggestions_error)
        self._suggestions_worker.start()

    def _on_suggestions_ready(self, questions: list) -> None:
        for question in questions:
            btn = QPushButton(question)
            btn.clicked.connect(lambda _checked=False, q=question: self._ask(q))
            self.suggestions_row.addWidget(btn)
        self.status_label.setText("")
        self._suggestions_worker.wait()  # see _StreamingChatMixin's docstring
        self._suggestions_worker = None

    def _on_suggestions_error(self, message: str) -> None:
        self.status_label.setText(f"Could not load suggested questions: {message}")
        self._suggestions_worker.wait()
        self._suggestions_worker = None

    def _send(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            return
        self.question_input.clear()
        self._ask(question)

    def _new_session(self) -> None:
        """Clears this tab's visible transcript and its persisted conversation
        history (`ChatEngine.new_session()`) so the next question starts fresh
        with no prior turns carried into context."""
        if self._chat_worker is not None:
            return  # don't reset mid-answer
        self.transcript.clear()
        self._chat_engine.new_session()
        self.status_label.setText("Started a new session — previous chat history cleared.")

    def _ask(self, question: str) -> None:
        if self._chat_worker is not None:
            return  # a question is already in flight
        self.transcript.append(f"\nYou: {question}\n")
        self.transcript.insertPlainText("Shadow: ")
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.new_session_btn.setEnabled(False)
        self.status_label.setText("Thinking...")
        self.progress.begin()

        self._chat_worker = ChatWorker(self._chat_engine, question)
        self._chat_worker.chunk_ready.connect(self._on_chunk)
        self._chat_worker.finished_ok.connect(self._on_finished)
        self._chat_worker.error.connect(self._on_error)
        self._chat_worker.start()

    def _stop(self) -> None:
        if self._chat_worker is not None:
            self._chat_worker.stop()
            self.status_label.setText("Stopping...")

    def _reset_worker(self) -> None:
        self._chat_worker.wait()  # see _StreamingChatMixin's docstring
        self._chat_worker = None
        # Both the success and error paths land here, so this is the one place
        # that has to clear the indicator — it can't be left spinning.
        self.progress.end()
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.new_session_btn.setEnabled(True)

    def shutdown(self) -> None:
        if self._chat_worker is not None:
            self._chat_worker.stop()
            self._chat_worker.wait(2000)
        if self._suggestions_worker is not None:
            self._suggestions_worker.wait(2000)
        self._shutdown_dictation()  # releases the mic if a recording is in flight


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shadow")
        self.resize(900, 650)

        self._event_store = EventStore(base_dir=settings.get("database.dir", "output/events"))
        self._logger = DataLogger(
            base_dir=settings.get("logging.base_dir", "output/logs"),
            event_store=self._event_store,
        )
        self._chat_engine = ChatEngine.from_settings(self._event_store, settings)

        self.live_tab = LiveMonitorTab(self._logger)
        self.search_tab = SearchTab(self._logger)
        self.assistant_tab = AssistantTab(self._chat_engine)
        self.ide_tab = IDETab(self._chat_engine, self._event_store)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.live_tab, "Live Monitor")
        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.assistant_tab, "Assistant")
        # Replaced the old "Coding Agent" tab: same plan/apply, dev-server,
        # model picker and dictation, plus an editor, file tree, git status, and
        # per-file AI edits with diff review.
        self.tabs.addTab(self.ide_tab, "Code")
        self.setCentralWidget(self.tabs)

        # Consent badge: an always-visible "what's currently being captured"
        # indicator, polling LiveMonitorTab's existing worker state rather than
        # adding new capture behavior — the checkboxes on that tab remain the
        # actual consent mechanism.
        self._consent_label = QLabel()
        self.statusBar().addPermanentWidget(self._consent_label)
        self._consent_timer = QTimer(self)
        self._consent_timer.timeout.connect(self._update_consent_badge)
        self._consent_timer.start(2000)
        self._update_consent_badge()

    def _update_consent_badge(self) -> None:
        screen_active, mic_active = self.live_tab.is_capturing()
        # Dictation opens the mic from the Assistant tab and the Code tab's AI
        # panel, outside LiveMonitorTab's workers entirely. Folded in here so the
        # badge can't read "Idle" while a dictation recording is running.
        mic_active = mic_active or any(
            tab.is_dictating for tab in (self.assistant_tab, self.ide_tab.ai_panel)
        )
        if screen_active and mic_active:
            text = "● Recording: screen+OCR, mic"
        elif screen_active:
            text = "● Recording: screen+OCR"
        elif mic_active:
            text = "● Recording: mic"
        else:
            text = "○ Idle — no active capture"
        self._consent_label.setText(text)

    def closeEvent(self, event) -> None:
        self.live_tab.shutdown()
        self.search_tab.shutdown()
        self.assistant_tab.shutdown()
        self.ide_tab.shutdown()
        super().closeEvent(event)
