"""QThread workers that keep the camera / gesture / screen / OCR pipelines off the GUI thread."""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from audio import AudioCapture
from callwatch import CallDetector
from camera import CameraModule
from gesture import GestureRecognizer, GestureResult
from logger import DataLogger, LogEntry
from mouse import MouseController
from ocr import OCREngine
from screen import ScreenCapture, get_frontmost_window, is_window_excluded
from speech import SpeechToText
from spellcheck import GrammarChecker, SpellChecker
from summarize import LogSummarizer


class GestureWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    gesture_ready = pyqtSignal(object)  # GestureResult
    error = pyqtSignal(str)

    def __init__(self, camera_cfg: dict, gesture_cfg: dict, mouse_cfg: dict, parent=None):
        super().__init__(parent)
        self._camera_cfg = camera_cfg
        self._gesture_cfg = gesture_cfg
        self._mouse_cfg = mouse_cfg
        self._running = False
        self.mouse_control_enabled = False

    def run(self) -> None:
        self._running = True
        try:
            camera = CameraModule(**self._camera_cfg)
            recognizer = GestureRecognizer(
                max_hands=self._gesture_cfg.get("max_hands", 1),
                detection_confidence=self._gesture_cfg.get("detection_confidence", 0.7),
                tracking_confidence=self._gesture_cfg.get("tracking_confidence", 0.7),
                pinch_click_threshold=self._gesture_cfg.get("pinch_click_threshold", 0.04),
            )
            mouse = MouseController(smoothing=self._mouse_cfg.get("smoothing", 0.5))
            camera.open()

            while self._running:
                frame = camera.read()
                if frame is None:
                    continue
                result: GestureResult = recognizer.process(frame)

                if self.mouse_control_enabled and result.hand_present and result.pointer_xy:
                    mouse.move_to(*result.pointer_xy)
                    if result.gesture == "pinch":
                        mouse.click("left")

                self.frame_ready.emit(frame)
                self.gesture_ready.emit(result)
        except Exception as exc:  # surface to GUI instead of crashing the thread silently
            self.error.emit(str(exc))
        finally:
            try:
                camera.close()
                recognizer.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class CallVoiceCaptureWorker(QThread):
    """Watches for an active Slack huddle / Google Meet call and transcribes voice while one is live."""

    status_changed = pyqtSignal(str)
    transcript_ready = pyqtSignal(str, str)  # (source, text)
    call_active_changed = pyqtSignal(bool)  # fires on every active<->inactive transition
    error = pyqtSignal(str)

    def __init__(self, audio_cfg: dict, speech_cfg: dict, logger: DataLogger, poll_interval: float = 3.0, parent=None):
        super().__init__(parent)
        self._audio_cfg = audio_cfg
        self._speech_cfg = speech_cfg
        self._logger = logger
        self._poll_interval = poll_interval
        self._running = False
        # When False, call detection still runs (status label keeps updating)
        # but no microphone audio is captured/transcribed even if a call is live.
        self.transcription_enabled = True

    def run(self) -> None:
        self._running = True
        detector = CallDetector()
        stt: SpeechToText | None = None
        capture: AudioCapture | None = None
        chunk_iter = None
        current_source = ""
        was_active = False

        self.status_changed.emit("Watching for a Slack/Meet call...")
        try:
            while self._running:
                state = detector.check()
                if state.active != was_active:
                    was_active = state.active
                    self.call_active_changed.emit(state.active)
                should_capture = state.active and self.transcription_enabled

                if should_capture and capture is None:
                    current_source = state.source
                    self._logger.start_session("speech", f"meeting_{state.source}")
                    self.status_changed.emit(f"Recording ({state.source}): {state.label}")
                    capture = AudioCapture(**self._audio_cfg)
                    chunk_iter = capture.chunks()
                    if stt is None:
                        stt = SpeechToText(**self._speech_cfg)
                elif not should_capture and capture is not None:
                    # Stops recording whether triggered by the call ending or
                    # by transcription being toggled off mid-call.
                    capture.stop()
                    capture = None
                    chunk_iter = None
                    current_source = ""
                    if state.active:
                        self.status_changed.emit(f"Call detected ({state.source}) — transcription disabled")
                    else:
                        self.status_changed.emit("Watching for a Slack/Meet call...")
                elif state.active and capture is None and not self.transcription_enabled:
                    self.status_changed.emit(f"Call detected ({state.source}) — transcription disabled")

                if capture is not None and chunk_iter is not None and stt is not None:
                    chunk = next(chunk_iter)
                    for seg in stt.transcribe_chunk(chunk, sample_rate=self._audio_cfg.get("sample_rate", 16000)):
                        self._logger.log_transcript(seg.text, extra={"source_app": current_source})
                        self.transcript_ready.emit(current_source, seg.text)
                else:
                    time.sleep(self._poll_interval)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if capture is not None:
                capture.stop()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class ScreenOcrWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    text_extracted = pyqtSignal(str)
    window_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, screen_cfg: dict, ocr_cfg: dict, logger: DataLogger, parent=None):
        super().__init__(parent)
        self._screen_cfg = screen_cfg
        self._ocr_cfg = ocr_cfg
        self._logger = logger
        self._running = False
        self.ocr_enabled = False
        self._excluded_apps = screen_cfg.get("excluded_apps", [])
        self._excluded_domains = screen_cfg.get("excluded_domains", [])

    def _is_excluded(self, window) -> bool:
        return is_window_excluded(window, self._excluded_apps, self._excluded_domains)

    def run(self) -> None:
        self._running = True
        last_state_key = None  # (app_name, excluded) — tracks both, not just app_name
        try:
            capture = ScreenCapture(
                monitor_index=self._screen_cfg.get("monitor_index", 0),
                change_threshold=self._screen_cfg.get("change_threshold", 0.02),
            )
            ocr = None
            interval = self._screen_cfg.get("capture_interval_seconds", 1.0)

            while self._running:
                frame = capture.grab()
                changed = capture.has_changed(frame)

                window = get_frontmost_window()
                excluded = window is not None and self._is_excluded(window)
                state_key = (window.app_name, excluded) if window is not None else None

                if excluded:
                    if state_key != last_state_key:
                        last_state_key = state_key
                        self.window_changed.emit(f"{window.app_name} (excluded — not captured)")
                    time.sleep(interval)
                    continue

                self.frame_ready.emit(frame)

                if window is not None and state_key != last_state_key:
                    last_state_key = state_key
                    self.window_changed.emit(window.app_name)

                if changed and self.ocr_enabled:
                    if ocr is None:
                        ocr = OCREngine(**self._ocr_cfg)
                    text = ocr.extract_text(frame)
                    if text.strip():
                        self._logger.log_ocr(text)
                        self.text_extracted.emit(text)

                time.sleep(interval)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            try:
                capture.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class SpellCheckWorker(QThread):
    """Watches system-wide keystrokes and flags likely misspellings via a popup.

    Runs everywhere, unconditionally — no app/domain exclusions — per explicit
    request. Still never persists anything: the accumulated per-word buffer is
    discarded immediately after each check and is NEVER written to disk or
    logged anywhere.

    Requires macOS "Input Monitoring" permission (System Settings > Privacy &
    Security > Input Monitoring), separate from Accessibility/Automation.

    Best-effort, editor-unaware buffer: it tracks plain backspace-to-undo but
    not cursor movement, so arrow-key edits mid-word aren't reflected.

    Because this observes every keystroke system-wide with no exclusions, it
    will also see characters typed into password fields — see the warning in
    README.md's "Spell check (system-wide)" section.
    """

    misspelling_found = pyqtSignal(str, list)  # (word, suggestions)
    grammar_issue_found = pyqtSignal(str, str, list)  # (sentence, message, replacements)
    error = pyqtSignal(str)  # fatal: the listener itself failed, feature is fully stopped
    grammar_warning = pyqtSignal(str)  # non-fatal: grammar checking degraded, spelling still runs

    _MAX_SENTENCE_LEN = 500  # force-flush a runaway sentence with no terminator

    def __init__(self, spellcheck_cfg: dict, parent=None):
        super().__init__(parent)
        self._spellcheck_cfg = spellcheck_cfg
        self._running = False
        self._listener = None
        self._grammar_thread: Optional[threading.Thread] = None
        self._sentence_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def _grammar_loop(self) -> None:
        try:
            checker = GrammarChecker(language=self._spellcheck_cfg.get("grammar_language", "en-US"))
        except Exception as exc:
            self.grammar_warning.emit(f"Grammar check unavailable: {exc}")
            return
        try:
            while True:
                sentence = self._sentence_queue.get()
                if sentence is None:  # sentinel: stop() is shutting us down
                    break
                if len(sentence.strip()) < 5:
                    continue
                try:
                    for issue in checker.check(sentence):
                        self.grammar_issue_found.emit(sentence.strip(), issue.message, issue.replacements)
                except Exception as exc:
                    self.grammar_warning.emit(f"Grammar check failed: {exc}")
        finally:
            checker.close()

    def run(self) -> None:
        from pynput import keyboard

        self._running = True
        try:
            checker = SpellChecker(language=self._spellcheck_cfg.get("language", "en"))
        except Exception as exc:
            self.error.emit(str(exc))
            return

        if not self._running:
            return  # stop() already arrived while the dictionary was loading

        if self._spellcheck_cfg.get("grammar_enabled", True):
            self._grammar_thread = threading.Thread(target=self._grammar_loop, daemon=True)
            self._grammar_thread.start()

        word_holder = {"buffer": ""}
        sentence_holder = {"buffer": ""}

        def flush_word() -> None:
            word = word_holder["buffer"]
            word_holder["buffer"] = ""
            if len(word) < 3:
                return
            suggestions = checker.check_word(word)
            if suggestions:
                self.misspelling_found.emit(word, suggestions)

        def flush_sentence() -> None:
            sentence = sentence_holder["buffer"]
            sentence_holder["buffer"] = ""
            if sentence.strip() and self._grammar_thread is not None:
                self._sentence_queue.put(sentence)

        def on_press(key) -> Optional[bool]:
            if not self._running:
                return False
            if key == keyboard.Key.backspace:
                word_holder["buffer"] = word_holder["buffer"][:-1]
                sentence_holder["buffer"] = sentence_holder["buffer"][:-1]
                return None

            char = getattr(key, "char", None)

            if char and char.isalpha():
                word_holder["buffer"] += char
            elif word_holder["buffer"]:
                flush_word()

            if char is not None:
                sentence_holder["buffer"] += char
                if char in ".!?":
                    flush_sentence()
            elif key == keyboard.Key.space:
                sentence_holder["buffer"] += " "
            elif key == keyboard.Key.enter:
                flush_sentence()

            if len(sentence_holder["buffer"]) > self._MAX_SENTENCE_LEN:
                flush_sentence()
            return None

        listener = keyboard.Listener(on_press=on_press)
        # Assign before start()/join() (not after, and not via the `with`
        # block's __enter__) so stop() can never race ahead of this being set.
        self._listener = listener
        if not self._running:
            return  # stop() raced us between checker load and listener creation

        try:
            listener.start()
            listener.join()
        except Exception as exc:
            self.error.emit(str(exc))

    def stop(self) -> None:
        self._running = False
        if self._listener is not None:
            self._listener.stop()
        if self._grammar_thread is not None:
            self._sentence_queue.put(None)  # sentinel to unblock the grammar loop's queue.get()
        # Bounded, short wait: unlike the camera/audio workers, this one holds
        # no system resource that must be released synchronously before the
        # GUI can proceed, so we don't risk freezing the UI thread for long.
        self.wait(500)


class SummarizeWorker(QThread):
    """Runs a single local-LLM summarization call off the GUI thread.

    One-shot: start() runs exactly one summarize() call then the thread
    exits on its own — there's no run loop to stop(), unlike the other
    workers in this module. The Ollama call can legitimately take a long
    time (10+ seconds just to load an 8B model into memory on first use),
    so this must never run on the GUI thread.
    """

    finished_ok = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, summarize_cfg: dict, entries: list[LogEntry], instructions: str = "", parent=None):
        super().__init__(parent)
        self._summarize_cfg = summarize_cfg
        self._entries = entries
        self._instructions = instructions

    def run(self) -> None:
        try:
            summarizer = LogSummarizer(**self._summarize_cfg)
            summary = summarizer.summarize(self._entries, self._instructions)
            self.finished_ok.emit(summary)
        except Exception as exc:
            self.error.emit(str(exc))


