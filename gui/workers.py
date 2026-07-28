"""QThread workers that keep the camera / gesture / screen / OCR pipelines off the GUI thread."""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from assistant.coding_agent import apply_plan, generate_plan
from assistant.dev_server import detect_start_command, launch_and_open_chrome
from audio import AudioCapture
from callwatch import CallDetector
from camera import CameraModule
from gesture import GestureRecognizer, GestureResult
from logger import DataLogger, LogEntry
from mouse import MouseController
from ocr import OCREngine
from screen import ScreenCapture, get_frontmost_window, is_window_excluded
from speech import LiveTranscriber, SegmenterConfig, SpeechToText
from speech.speech_to_text import WHISPER_SAMPLE_RATE

from .progress import Stage
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
    call_detected = pyqtSignal(str, str)  # (source, label) — fires only on inactive->active transitions
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
        # True only while a microphone AudioCapture is actually open (i.e. a
        # call/huddle is live AND transcription_enabled) — unlike
        # transcription_enabled above, this reflects real-time capture state,
        # not just configuration, so UI indicators (MainWindow's consent
        # badge) don't claim the mic is recording when it isn't.
        self.is_recording = False
        # Held so `stop()` can close the device from the GUI thread; without it a
        # stop lands while this thread is mid-chunk and the mic stays open.
        self._capture: AudioCapture | None = None

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
                    if state.active:
                        self.call_detected.emit(state.source, state.label)
                should_capture = state.active and self.transcription_enabled

                if should_capture and capture is None:
                    current_source = state.source
                    self._logger.start_session("speech", f"meeting_{state.source}")
                    self.status_changed.emit(f"Recording ({state.source}): {state.label}")
                    capture = AudioCapture(**self._audio_cfg)
                    self._capture = capture
                    chunk_iter = capture.chunks()
                    if stt is None:
                        stt = SpeechToText(**self._speech_cfg)
                    self.is_recording = True
                elif not should_capture and capture is not None:
                    # Stops recording whether triggered by the call ending or
                    # by transcription being toggled off mid-call.
                    capture.stop()
                    capture = None
                    self._capture = None
                    chunk_iter = None
                    current_source = ""
                    self.is_recording = False
                    if state.active:
                        self.status_changed.emit(f"Call detected ({state.source}) — transcription disabled")
                    else:
                        self.status_changed.emit("Watching for a Slack/Meet call...")
                elif state.active and capture is None and not self.transcription_enabled:
                    self.status_changed.emit(f"Call detected ({state.source}) — transcription disabled")

                if capture is not None and chunk_iter is not None and stt is not None:
                    # None means the capture ended underneath us (a stop from
                    # another thread); loop round so `_running` decides what next.
                    chunk = next(chunk_iter, None)
                    if chunk is None:
                        capture = None
                        self._capture = None
                        chunk_iter = None
                        self.is_recording = False
                        continue
                    for seg in stt.transcribe_chunk(chunk, sample_rate=self._audio_cfg.get("sample_rate", 16000)):
                        self._logger.log_transcript(seg.text, extra={"source_app": current_source})
                        self.transcript_ready.emit(current_source, seg.text)
                else:
                    time.sleep(self._poll_interval)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if capture is not None:
                capture.stop()
            self._capture = None
            self.is_recording = False

    def stop(self) -> None:
        self._running = False
        # Close the device first: this thread may be blocked part-way through
        # assembling a chunk, and `chunks()` only notices the stop once the
        # stream is gone. Without this the wait below times out and the thread
        # lingers with the microphone still open.
        capture = self._capture
        if capture is not None:
            capture.stop()
        self.wait(5000)


class ScreenOcrWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    text_extracted = pyqtSignal(str, str)  # (title, text) — title is the topmost/parent section heading on screen
    window_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, screen_cfg: dict, ocr_cfg: dict, logger: DataLogger, parent=None):
        super().__init__(parent)
        self._screen_cfg = screen_cfg
        self._ocr_cfg = ocr_cfg
        self._logger = logger
        self._running = False
        self.ocr_enabled = False
        # When True, every system-wide mouse click wakes the capture loop
        # immediately instead of waiting out the normal poll interval — set
        # at any time, checked live from the mouse listener callback below.
        self.capture_on_mouse_event = screen_cfg.get("capture_on_mouse_event", False)
        self._excluded_apps = screen_cfg.get("excluded_apps", [])
        self._excluded_domains = screen_cfg.get("excluded_domains", [])
        self._mouse_trigger = threading.Event()
        self._mouse_listener = None

    def _is_excluded(self, window) -> bool:
        return is_window_excluded(window, self._excluded_apps, self._excluded_domains)

    def _on_mouse_click(self, x, y, button, pressed) -> None:
        if pressed and self.capture_on_mouse_event:
            self._mouse_trigger.set()

    def _wait(self, interval: float) -> bool:
        """Sleeps for `interval` seconds, but wakes early on a mouse-click trigger.

        Returns whether the wake was caused by a mouse click (vs. the interval
        simply elapsing), so the caller can tell the two apart.
        """
        mouse_triggered = self._mouse_trigger.wait(timeout=interval)
        self._mouse_trigger.clear()
        return mouse_triggered

    def run(self) -> None:
        from pynput import mouse

        self._running = True
        last_state_key = None  # (app_name, excluded) — tracks both, not just app_name
        mouse_triggered = False  # whether the *previous* wait woke us due to a click
        self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self._mouse_listener.start()
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
                    mouse_triggered = self._wait(interval)
                    continue

                self.frame_ready.emit(frame)

                if window is not None and state_key != last_state_key:
                    last_state_key = state_key
                    self.window_changed.emit(window.app_name)

                if self.ocr_enabled and (changed or mouse_triggered):
                    if ocr is None:
                        ocr = OCREngine(**self._ocr_cfg)
                    text, title = ocr.extract_text_with_title(frame)
                    if text.strip():
                        self._logger.log_ocr(text, extra={"title": title})
                        self.text_extracted.emit(title, text)

                mouse_triggered = self._wait(interval)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            try:
                capture.close()
            except Exception:
                pass
            if self._mouse_listener is not None:
                self._mouse_listener.stop()

    def stop(self) -> None:
        self._running = False
        self._mouse_trigger.set()  # unblock a pending _wait() so stop() doesn't wait out a long interval
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


class DictationWorker(QThread):
    """Records the microphone until `stop_recording()`, then transcribes it once.

    Backs the chat boxes' "Dictate" button (see `gui/dashboard.py`'s
    `_DictationMixin`) so a prompt can be spoken instead of typed. Distinct
    from `CallVoiceCaptureWorker`, which streams continuously and logs every
    chunk: this records one arbitrary-length take, transcribes it in one pass,
    and emits the text for the UI to insert.

    Both phases must stay off the GUI thread — `SpeechToText.__init__` loads
    the whisper model (seconds on first use) and transcription itself is
    CPU-bound.
    """

    finished_ok = pyqtSignal(str)
    status = pyqtSignal(str)  # e.g. "Transcribing..." once recording stops
    stage = pyqtSignal(str)  # a `gui.progress.Stage`, for the progress indicator
    error = pyqtSignal(str)

    # How long each read_available() poll waits before re-checking
    # `_recording`, i.e. the worst-case lag between the user clicking "Stop"
    # and recording actually ending.
    _POLL_SECONDS = 0.1

    def __init__(self, audio_cfg: dict, speech_cfg: dict, parent=None):
        super().__init__(parent)
        self._audio_cfg = audio_cfg
        self._speech_cfg = speech_cfg
        self._recording = True

    def stop_recording(self) -> None:
        """Ends the recording; the thread then transcribes and emits."""
        self._recording = False

    def run(self) -> None:
        capture = None
        try:
            capture = AudioCapture(**self._audio_cfg)
            capture.start()
            self.stage.emit(Stage.LISTENING)
            blocks = []
            while self._recording:
                block = capture.read_available(timeout=self._POLL_SECONDS)
                if block is not None:
                    blocks.append(block)
            capture.stop()
            # Whatever the callback queued between the last poll and stop() —
            # dropping it would clip the end of the user's sentence.
            while True:
                block = capture.read_available(timeout=0.0)
                if block is None:
                    break
                blocks.append(block)

            if not blocks:
                # The stream opened without error (device.start() would have raised
                # otherwise) but delivered nothing — PortAudio doesn't raise when
                # macOS silently denies microphone access, so this is the most
                # common real-world cause, not a code bug.
                device = capture.resolved_device_name or "the selected input device"
                self.error.emit(
                    f"No audio captured from {device} — check that this app has microphone "
                    "permission (macOS: System Settings > Privacy & Security > Microphone) "
                    "and that audio.device_index points at a working input device."
                )
                return

            self.status.emit("Transcribing...")
            self.stage.emit(Stage.TRANSCRIBING)
            stt = SpeechToText(**self._speech_cfg)
            segments = stt.transcribe_chunk(
                np.concatenate(blocks, axis=0), sample_rate=self._audio_cfg.get("sample_rate", 16000)
            )
            self.finished_ok.emit(" ".join(s.text.strip() for s in segments if s.text.strip()))
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if capture is not None:
                capture.stop()  # idempotent — safe even if stop() already ran above


class LiveDictationWorker(QThread):
    """Transcribes the microphone continuously, emitting text as it's spoken.

    The streaming counterpart to `DictationWorker`: rather than one transcription
    after the user stops, `speech.LiveTranscriber` cuts the audio at pauses and
    transcribes each utterance as it completes, so text appears while they're
    still talking.

    Two signals because live results come in two flavours (see
    `speech.live_transcriber`): `partial_ready` is a revisable reading of the
    sentence in progress and each one replaces the last, while `final_ready` is
    settled text the UI can commit.
    """

    partial_ready = pyqtSignal(str)  # interim — supersedes the previous partial
    final_ready = pyqtSignal(str)  # settled text for the UI to keep
    status = pyqtSignal(str)
    stage = pyqtSignal(str)  # a `gui.progress.Stage`, for the progress indicator
    error = pyqtSignal(str)

    _POLL_SECONDS = 0.1

    def __init__(self, audio_cfg: dict, speech_cfg: dict, live_cfg: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self._audio_cfg = audio_cfg
        self._speech_cfg = speech_cfg
        self._live_cfg = live_cfg or {}
        self._recording = True
        self._capture: Optional[AudioCapture] = None
        self._heard_audio = False
        # Mirrors CallVoiceCaptureWorker's flag so MainWindow's consent badge can
        # tell the truth about the microphone being open (see
        # `LiveMonitorTab.is_capturing`).
        self.is_recording = False

    def stop_recording(self) -> None:
        """Ends the recording; any final utterance is flushed before finishing."""
        self._recording = False
        capture = self._capture
        if capture is not None:
            # Unblocks the poll immediately rather than waiting out its timeout.
            capture.stop()

    def run(self) -> None:
        capture = None
        try:
            # Loaded before the stream opens, not after: the model takes seconds
            # on first use, and audio captured during that wait would pile up in
            # the queue and be transcribed as one late backlog.
            self.status.emit("Preparing speech model...")
            self.stage.emit(Stage.LOADING_MODEL)
            stt = SpeechToText(**self._speech_cfg)

            sample_rate = self._audio_cfg.get("sample_rate", WHISPER_SAMPLE_RATE)
            live = LiveTranscriber(
                stt,
                segmenter_config=SegmenterConfig(
                    sample_rate=sample_rate,
                    silence_seconds=self._live_cfg.get("silence_seconds", 0.8),
                    max_utterance_seconds=self._live_cfg.get("max_utterance_seconds", 20.0),
                ),
                interim_interval_seconds=self._live_cfg.get("interim_interval_seconds", 1.5),
                sample_rate=sample_rate,
            )

            capture = AudioCapture(**self._audio_cfg)
            self._capture = capture
            capture.start()
            self.is_recording = True
            self.stage.emit(Stage.LISTENING)
            self.status.emit("Listening — speak now, then click again to finish.")

            while self._recording:
                block = capture.read_available(timeout=self._POLL_SECONDS)
                if block is None:
                    continue
                self._heard_audio = True
                self._emit(live.push(block))

            capture.stop()
            # Blocks queued between the last poll and the stop, which would
            # otherwise clip the end of the closing sentence.
            while True:
                block = capture.read_available(timeout=0.0)
                if block is None:
                    break
                self._heard_audio = True
                self._emit(live.push(block))
            self._emit(live.flush())

            if not self._heard_audio:
                device = capture.resolved_device_name or "the selected input device"
                self.error.emit(
                    f"No audio captured from {device} — check that this app has microphone "
                    "permission (macOS: System Settings > Privacy & Security > Microphone) "
                    "and that audio.device_index points at a working input device."
                )
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.is_recording = False
            self._capture = None
            if capture is not None:
                capture.stop()  # idempotent

    def _emit(self, results) -> None:
        for result in results:
            if result.is_final:
                self.final_ready.emit(result.text)
            else:
                self.partial_ready.emit(result.text)


class ChatWorker(QThread):
    """Runs one streaming ChatEngine.ask() call off the GUI thread.

    One-shot like SummarizeWorker, but forwards each chunk as it arrives via
    `chunk_ready` instead of waiting for the full answer. `stop()` doesn't
    (can't) kill a mid-flight HTTP read outright, but closes the underlying
    generator on the next chunk boundary so no further chunks are emitted and
    the partial answer still gets recorded to history (see
    `assistant.chat_engine.ChatEngine.ask`'s `finally` block).
    """

    chunk_ready = pyqtSignal(str)
    finished_ok = pyqtSignal(list)  # citations
    error = pyqtSignal(str)

    def __init__(
        self,
        chat_engine,
        question: str,
        project: str | None = None,
        model: str | None = None,
        free_chat: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._question = question
        self._project = project
        self._model = model
        self._free_chat = free_chat
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            stream = self._chat_engine.ask(
                self._question, project=self._project, model=self._model, free_chat=self._free_chat
            )
            for chunk in stream:
                if self._cancelled:
                    stream.close()
                    break
                self.chunk_ready.emit(chunk)
            self.finished_ok.emit(self._chat_engine.last_citations)
        except Exception as exc:
            self.error.emit(str(exc))


class SuggestedQuestionsWorker(QThread):
    """Runs one ChatEngine.suggested_questions() call off the GUI thread.

    One-shot, like SummarizeWorker. Unlike the old rule-based version, this
    can now call the local LLM (to ground questions in today's actual
    captured content), which — same as Summarize's first call after Ollama
    starts — can take a real amount of time, so it must not run on the GUI
    thread. Cached per-day by ChatEngine/EventStore, so this only actually
    hits Ollama once per day in practice.
    """

    finished_ok = pyqtSignal(list)  # questions
    error = pyqtSignal(str)

    def __init__(self, chat_engine, parent=None):
        super().__init__(parent)
        self._chat_engine = chat_engine

    def run(self) -> None:
        try:
            questions = self._chat_engine.suggested_questions()
            self.finished_ok.emit(questions)
        except Exception as exc:
            self.error.emit(str(exc))


class PlanWorker(QThread):
    """Runs one generate_plan() call off the GUI thread — see assistant/coding_agent.py.

    One-shot like SummarizeWorker: reads the project's files and makes one
    (larger, slower) Ollama call, so this must not block the GUI thread.
    """

    finished_ok = pyqtSignal(object)  # PlanResult
    error = pyqtSignal(str)

    def __init__(
        self,
        project_path: str,
        issue: str,
        captured_context: str,
        plan_cfg: dict,
        previous_plan: str | None = None,
        feedback: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._project_path = project_path
        self._issue = issue
        self._captured_context = captured_context
        self._plan_cfg = plan_cfg
        self._previous_plan = previous_plan
        self._feedback = feedback

    def run(self) -> None:
        try:
            plan = generate_plan(
                self._project_path,
                self._issue,
                self._captured_context,
                previous_plan=self._previous_plan,
                feedback=self._feedback,
                **self._plan_cfg,
            )
            self.finished_ok.emit(plan)
        except Exception as exc:
            self.error.emit(str(exc))


class ApplyWorker(QThread):
    """Runs one apply_plan() call off the GUI thread — see assistant/coding_agent.py.

    This is the step that actually writes files (on a new git branch) and
    can involve several sequential Ollama calls (one per changed file), so it
    can take a while — must run off the GUI thread same as PlanWorker.
    """

    finished_ok = pyqtSignal(object)  # ApplyResult
    error = pyqtSignal(str)

    def __init__(self, project_path: str, plan, issue: str, ollama_cfg: dict, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._plan = plan
        self._issue = issue
        self._ollama_cfg = ollama_cfg

    def run(self) -> None:
        try:
            result = apply_plan(self._project_path, self._plan, self._issue, **self._ollama_cfg)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class DevServerWorker(QThread):
    """Detects a project's dev-server start command, launches it, and opens
    the result in Chrome — see assistant/dev_server.py.

    The launched process is intentionally left running when this worker
    finishes; the Code tab keeps the `LaunchResult.process` handle and owns
    stopping it (via its "Stop Dev Server" button and `shutdown()`).
    """

    finished_ok = pyqtSignal(object)  # LaunchResult
    no_start_command = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, project_path: str, timeout_seconds: float = 20.0, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._timeout = timeout_seconds

    def run(self) -> None:
        try:
            command = detect_start_command(self._project_path)
            if command is None:
                self.no_start_command.emit()
                return
            result = launch_and_open_chrome(self._project_path, command, timeout=self._timeout)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


