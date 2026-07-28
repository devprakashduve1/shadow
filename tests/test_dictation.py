"""Tests for the dictation mixin's live-transcription rendering.

`_DictationMixin` is exercised through a minimal host widget rather than a real
tab, and the worker signals are invoked directly — no microphone, no whisper
model, no threads. What's under test is how interim and final results are
composed into the input box.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from gui.chat_widgets import ChatInput, _DictationMixin
from gui.progress import AIProgressIndicator, Stage


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Host(_DictationMixin):
    """The minimum a `_DictationMixin` consumer has to provide."""

    def __init__(self):
        self.question_input = ChatInput()
        self.status_label = QLabel()
        self.progress = AIProgressIndicator()
        self._build_dictate_button()


class _HostWithoutProgress(_DictationMixin):
    """A consumer with no indicator — the mixin treats one as optional."""

    def __init__(self):
        self.question_input = ChatInput()
        self.status_label = QLabel()
        self._build_dictate_button()


@pytest.fixture
def host(qapp) -> _Host:
    return _Host()


def _begin(host: _Host) -> None:
    """Mimics `_toggle_dictation` starting a run, without a worker or a mic."""
    host._dictation_base = host.question_input.toPlainText().strip()
    host._dictation_finals = []
    host._dictation_failed = False


# -- composing the text ------------------------------------------------------


def test_a_final_result_lands_in_the_input_box(host) -> None:
    _begin(host)

    host._on_dictation_final("hello world")

    assert host.question_input.toPlainText() == "hello world"


def test_an_interim_result_is_shown_while_speaking(host) -> None:
    _begin(host)

    host._on_dictation_partial("hello wor")

    assert host.question_input.toPlainText() == "hello wor"


def test_each_interim_replaces_the_previous_one(host) -> None:
    """Interims are revisions of the same sentence, not additions to it."""
    _begin(host)

    host._on_dictation_partial("the qui")
    host._on_dictation_partial("the quick brown")

    assert host.question_input.toPlainText() == "the quick brown"


def test_a_final_supersedes_the_interim_it_replaces(host) -> None:
    _begin(host)

    host._on_dictation_partial("the quick brown")
    host._on_dictation_final("the quick brown fox")

    assert host.question_input.toPlainText() == "the quick brown fox"


def test_finals_accumulate_across_sentences(host) -> None:
    _begin(host)

    host._on_dictation_final("first sentence.")
    host._on_dictation_final("second sentence.")

    assert host.question_input.toPlainText() == "first sentence. second sentence."


def test_an_interim_follows_committed_finals(host) -> None:
    _begin(host)

    host._on_dictation_final("first sentence.")
    host._on_dictation_partial("second sen")

    assert host.question_input.toPlainText() == "first sentence. second sen"


# -- composing with typed text ----------------------------------------------


def test_dictation_appends_to_what_was_already_typed(host) -> None:
    """Dictation composes with typing rather than clobbering the box."""
    host.question_input.setPlainText("please review")
    _begin(host)

    host._on_dictation_final("the auth module")

    assert host.question_input.toPlainText() == "please review the auth module"


def test_interim_text_does_not_disturb_what_was_typed(host) -> None:
    host.question_input.setPlainText("please review")
    _begin(host)

    host._on_dictation_partial("the auth")
    host._on_dictation_partial("the auth mod")

    assert host.question_input.toPlainText() == "please review the auth mod"


# -- finishing ---------------------------------------------------------------


def test_finishing_with_text_prompts_the_user_to_review(host) -> None:
    _begin(host)
    host._on_dictation_final("some words")

    host._on_live_dictation_finished()

    assert "review it" in host.status_label.text()
    assert host.dictate_btn.text() == host._DICTATE_LABEL, "button returns to idle"


def test_finishing_with_nothing_heard_says_so(host) -> None:
    _begin(host)

    host._on_live_dictation_finished()

    assert "Didn't catch anything" in host.status_label.text()


def test_an_error_message_survives_the_finish_handler(host) -> None:
    """The real cause must stay on screen, not be replaced by 'try again'."""
    _begin(host)

    host._on_dictation_error("no microphone permission")
    host._on_live_dictation_finished()

    assert "no microphone permission" in host.status_label.text()
    assert "Didn't catch anything" not in host.status_label.text()


def test_a_partial_that_never_finalises_is_not_kept(host) -> None:
    """Only settled text counts as dictated — an interim alone means nothing was
    committed, so the run reports having heard nothing."""
    _begin(host)
    host._on_dictation_partial("half a thou")

    host._on_live_dictation_finished()

    assert "Didn't catch anything" in host.status_label.text()


# -- one-shot fallback (speech.live.enabled = false) -------------------------


def test_one_shot_result_lands_in_the_box(host) -> None:
    _begin(host)

    host._on_dictation_ready("a whole spoken sentence")

    assert host.question_input.toPlainText() == "a whole spoken sentence"
    assert "review it" in host.status_label.text()


def test_one_shot_appends_to_typed_text(host) -> None:
    host.question_input.setPlainText("please review")
    _begin(host)

    host._on_dictation_ready("the auth module")

    assert host.question_input.toPlainText() == "please review the auth module"


def test_one_shot_with_no_speech_says_so(host) -> None:
    _begin(host)

    host._on_dictation_ready("")

    assert "Didn't catch anything" in host.status_label.text()


# -- button labels -----------------------------------------------------------


def test_the_button_returns_to_its_idle_label(host) -> None:
    _begin(host)
    host.dictate_btn.setText(host._DICTATE_STOP_LABEL)

    host._reset_dictation()

    assert host.dictate_btn.text() == host._DICTATE_LABEL


def test_a_custom_label_survives_a_dictation_round_trip(qapp) -> None:
    """AIPanel's button is icon-width. A hardcoded reset used to overwrite its
    "🎤" with the long default, which then rendered as a clipped "Dic"."""

    class _CompactHost(_DictationMixin):
        def __init__(self):
            self.question_input = ChatInput()
            self.status_label = QLabel()
            self._build_dictate_button(label="🎤", stop_label="■")

    host = _CompactHost()
    assert host.dictate_btn.text() == "🎤"

    _begin(host)
    host._on_dictation_final("words")
    host._on_live_dictation_finished()

    assert host.dictate_btn.text() == "🎤"


# -- progress reporting ------------------------------------------------------


def test_the_first_stage_report_starts_the_indicator(host) -> None:
    assert host.progress.state.stage == Stage.IDLE

    host._on_dictation_stage(Stage.LOADING_MODEL)

    assert host.progress.state.stage == Stage.LOADING_MODEL
    assert host.progress.isHidden() is False


def test_later_stage_reports_advance_the_indicator(host) -> None:
    host._on_dictation_stage(Stage.LOADING_MODEL)

    host._on_dictation_stage(Stage.LISTENING)

    assert host.progress.state.stage == Stage.LISTENING


def test_finishing_a_dictation_completes_the_indicator(host) -> None:
    _begin(host)
    host._on_dictation_stage(Stage.LISTENING)
    host._on_dictation_final("words")

    host._on_live_dictation_finished()

    assert host.progress.state.stage == Stage.DONE


def test_a_failed_dictation_does_not_leave_a_bar_running(host) -> None:
    """Every outcome funnels through `_reset_dictation`, so the error path must
    clear the indicator too."""
    _begin(host)
    host._on_dictation_stage(Stage.LISTENING)

    host._on_dictation_error("no microphone permission")
    host._on_live_dictation_finished()
    host.progress._finish_hiding()

    assert host.progress.isHidden() is True
    assert host.progress.state.stage == Stage.IDLE


def test_shutdown_clears_the_indicator(host) -> None:
    host._on_dictation_stage(Stage.LISTENING)

    host._shutdown_dictation()

    assert host.progress.isHidden() is True


def test_a_host_without_an_indicator_still_works(qapp) -> None:
    """The indicator is optional, so the mixin must not require one."""
    host = _HostWithoutProgress()
    _begin(host)

    host._on_dictation_stage(Stage.LISTENING)  # must not raise
    host._on_dictation_final("words")
    host._on_live_dictation_finished()

    assert host.question_input.toPlainText() == "words"


# -- consent badge -----------------------------------------------------------


def test_is_dictating_is_false_when_idle(host) -> None:
    assert host.is_dictating is False


def test_is_dictating_is_true_while_a_worker_is_recording(host) -> None:
    """The consent badge reads this; it must not report idle with the mic open."""

    class _Recording:
        is_recording = True

    host._dictation_worker = _Recording()

    assert host.is_dictating is True


def test_is_dictating_is_false_once_the_worker_stops_recording(host) -> None:
    class _Stopped:
        is_recording = False

    host._dictation_worker = _Stopped()

    assert host.is_dictating is False
