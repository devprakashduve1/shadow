"""Tests for gui/progress.py's ProgressTracker.

The tracker is pure, so these cover the whole decision surface without a
display. The invariant under most scrutiny is that a percentage only ever
appears when something actually counted the work — an invented percentage is
worse than none, because it makes a working app look stuck.
"""
from __future__ import annotations

import pytest

from gui.progress import (
    WAIT_ESCALATION_SECONDS,
    ProgressState,
    ProgressTracker,
    Stage,
)


@pytest.fixture
def tracker() -> ProgressTracker:
    return ProgressTracker()


# -- lifecycle ---------------------------------------------------------------


def test_starts_idle_and_inactive(tracker) -> None:
    assert tracker.state.stage == Stage.IDLE
    assert tracker.state.active is False


def test_begin_activates_with_an_indeterminate_bar(tracker) -> None:
    state = tracker.begin()

    assert state.stage == Stage.PREPARING
    assert state.active is True
    assert state.percent is None, "nothing has been counted yet"
    assert state.label, "a stage always has something to say"


def test_begin_accepts_a_custom_label(tracker) -> None:
    assert tracker.begin("Thinking about your question...").label == (
        "Thinking about your question..."
    )


def test_end_deactivates(tracker) -> None:
    tracker.begin()

    state = tracker.end()

    assert state.stage == Stage.DONE
    assert state.active is False


def test_reset_returns_to_idle(tracker) -> None:
    tracker.begin()

    assert tracker.reset().stage == Stage.IDLE


def test_begin_clears_state_from_the_previous_run(tracker) -> None:
    tracker.begin()
    tracker.add_output("some earlier answer")

    state = tracker.begin()

    assert state.stage == Stage.PREPARING
    assert state.detail == "", "the old character count must not carry over"


# -- the no-invented-percentage rule ----------------------------------------


def test_preparing_is_indeterminate(tracker) -> None:
    assert tracker.begin().determinate is False


def test_generating_is_indeterminate(tracker) -> None:
    """A response's length isn't known until it ends, so there's no honest
    percentage to show while it streams."""
    tracker.begin()

    state = tracker.add_output("hello")

    assert state.determinate is False


def test_elapsed_time_never_produces_a_percentage(tracker) -> None:
    tracker.begin()

    for elapsed in (1.0, 5.0, 30.0, 600.0):
        assert tracker.tick(elapsed).percent is None


def test_counted_work_is_the_only_route_to_a_percentage(tracker) -> None:
    tracker.begin()

    state = tracker.set_counted_progress(25, 100)

    assert state.determinate is True
    assert state.percent == 25


# -- counted progress -------------------------------------------------------


@pytest.mark.parametrize(
    "done,total,expected",
    [(0, 10, 0), (5, 10, 50), (10, 10, 100), (1, 3, 33), (2, 3, 67)],
)
def test_percentage_is_computed_from_the_count(tracker, done, total, expected) -> None:
    assert tracker.set_counted_progress(done, total).percent == expected


def test_an_unknown_total_stays_indeterminate(tracker) -> None:
    """A job that hasn't been sized yet reports total=0; that's unknown, not 0%,
    and definitely not a division error."""
    state = tracker.set_counted_progress(0, 0)

    assert state.percent is None
    assert state.active is True


def test_a_negative_total_is_treated_as_unknown(tracker) -> None:
    assert tracker.set_counted_progress(5, -1).percent is None


def test_percentage_is_clamped_to_a_sane_range(tracker) -> None:
    """Defends against a worker that overshoots its own estimate."""
    assert tracker.set_counted_progress(150, 100).percent == 100
    assert tracker.set_counted_progress(-5, 100).percent == 0


def test_counted_progress_reports_the_raw_numbers_too(tracker) -> None:
    assert "3" in tracker.set_counted_progress(3, 40).detail
    assert "40" in tracker.set_counted_progress(3, 40).detail


# -- output / generation ----------------------------------------------------


def test_first_output_marks_generation_beginning(tracker) -> None:
    """This transition is the one genuinely informative moment in an otherwise
    opaque wait, so it must always move the stage."""
    tracker.begin()

    state = tracker.add_output("The")

    assert state.stage == Stage.GENERATING


def test_output_accumulates_across_chunks(tracker) -> None:
    tracker.begin()
    tracker.add_output("12345")
    state = tracker.add_output("67890")

    assert "10" in state.detail, f"expected a running total, got {state.detail!r}"


def test_a_single_character_is_not_pluralised(tracker) -> None:
    tracker.begin()

    assert "1 character" in tracker.add_output("x").detail


def test_output_after_a_wait_escalation_still_switches_to_generating(tracker) -> None:
    """The escalated wait message must not stick once tokens actually arrive."""
    tracker.begin()
    tracker.tick(WAIT_ESCALATION_SECONDS + 1)

    state = tracker.add_output("finally")

    assert state.stage == Stage.GENERATING


# -- wait escalation --------------------------------------------------------


def test_a_short_wait_is_not_escalated(tracker) -> None:
    tracker.begin()

    state = tracker.tick(WAIT_ESCALATION_SECONDS - 1)

    assert state.stage == Stage.PREPARING


def test_a_long_wait_explains_itself(tracker) -> None:
    """An unexplained pause reads as a hang; naming the model load doesn't make
    it faster but does make it legible."""
    tracker.begin()

    state = tracker.tick(WAIT_ESCALATION_SECONDS + 0.1)

    assert state.stage == Stage.WAITING
    assert state.detail, "the escalation should say why it's slow"


def test_escalation_happens_only_once(tracker) -> None:
    tracker.begin()
    first = tracker.tick(WAIT_ESCALATION_SECONDS + 1)
    second = tracker.tick(WAIT_ESCALATION_SECONDS + 20)

    assert first == second


def test_ticking_while_idle_does_nothing(tracker) -> None:
    state = tracker.tick(999.0)

    assert state.stage == Stage.IDLE


def test_generation_is_never_escalated_to_waiting(tracker) -> None:
    """Once output is flowing there's nothing to apologise for."""
    tracker.begin()
    tracker.add_output("streaming along")

    state = tracker.tick(WAIT_ESCALATION_SECONDS + 30)

    assert state.stage == Stage.GENERATING


def test_counted_work_is_not_escalated(tracker) -> None:
    """Indexing that takes a while is already showing a real percentage."""
    tracker.begin()
    tracker.set_counted_progress(10, 1000)

    state = tracker.tick(WAIT_ESCALATION_SECONDS + 30)

    assert state.stage == Stage.WORKING
    assert state.percent == 1


# -- explicit stages --------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [Stage.LOADING_MODEL, Stage.LISTENING, Stage.TRANSCRIBING, Stage.GENERATING],
)
def test_each_stage_has_default_wording(tracker, stage: str) -> None:
    assert tracker.set_stage(stage).label


def test_a_stage_change_drops_a_stale_percentage(tracker) -> None:
    """Moving on from counted work means the old percentage describes something
    that already finished."""
    tracker.set_counted_progress(50, 100)

    state = tracker.set_stage(Stage.GENERATING)

    assert state.percent is None


def test_set_stage_accepts_a_custom_label_and_detail(tracker) -> None:
    state = tracker.set_stage(Stage.LOADING_MODEL, "Loading whisper...", "base model")

    assert state.label == "Loading whisper..."
    assert state.detail == "base model"


# -- state value semantics --------------------------------------------------


def test_states_compare_by_value() -> None:
    """The widget only repaints when the state changed, so equality matters."""
    assert ProgressState(stage=Stage.PREPARING, label="x") == ProgressState(
        stage=Stage.PREPARING, label="x"
    )
    assert ProgressState(stage=Stage.PREPARING) != ProgressState(stage=Stage.GENERATING)


def test_done_and_idle_are_both_inactive() -> None:
    assert ProgressState(stage=Stage.DONE).active is False
    assert ProgressState(stage=Stage.IDLE).active is False


# -- the widget --------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def indicator(qapp):
    from gui.progress import AIProgressIndicator

    return AIProgressIndicator()


def test_the_indicator_is_hidden_until_there_is_work(indicator) -> None:
    """It must not occupy space in the panel while the app is idle."""
    assert indicator.isHidden() is True


def test_beginning_work_shows_it(indicator) -> None:
    indicator.begin("Processing...")

    assert indicator.isHidden() is False
    assert "Processing" in indicator.caption.text()


def test_an_indeterminate_stage_uses_qt_busy_mode(indicator) -> None:
    """range(0, 0) is Qt's self-animating busy bar."""
    indicator.begin()

    assert indicator.bar.maximum() == 0


def test_counted_progress_switches_the_bar_to_a_real_scale(indicator) -> None:
    indicator.begin()

    indicator.set_counted_progress(30, 60)

    assert indicator.bar.maximum() == 100
    assert indicator.bar.value() == 50


def test_returning_to_an_indeterminate_stage_restores_busy_mode(indicator) -> None:
    indicator.begin()
    indicator.set_counted_progress(30, 60)

    indicator.set_stage(Stage.GENERATING)

    assert indicator.bar.maximum() == 0


def test_the_caption_reports_streamed_output(indicator) -> None:
    indicator.begin()

    indicator.add_output("some tokens")

    assert "Generating" in indicator.caption.text()


def test_cancel_hides_immediately(indicator) -> None:
    indicator.begin()

    indicator.cancel()

    assert indicator.isHidden() is True
    assert indicator.state.stage == Stage.IDLE


def test_end_then_linger_expiry_hides_it(indicator) -> None:
    indicator.begin()
    indicator.end()

    indicator._finish_hiding()  # what the linger timer fires

    assert indicator.isHidden() is True
    assert indicator.state.stage == Stage.IDLE


def test_ending_work_that_never_started_leaves_nothing_behind(indicator) -> None:
    """An instant failure shouldn't flash a completed bar on screen."""
    indicator.end()

    assert indicator.isHidden() is True
    assert indicator.state.stage == Stage.IDLE


def test_ending_a_real_run_shows_completion_before_hiding(indicator) -> None:
    """Completion must not depend on Qt visibility: `isVisible()` is False for
    anything in a background tab, which would silently skip this for any request
    the user tabbed away from."""
    indicator.begin()

    indicator.end()

    assert indicator.state.stage == Stage.DONE
    assert indicator.isHidden() is False, "still on screen for the linger"


def test_the_caption_is_cleared_when_hidden(indicator) -> None:
    """Otherwise the next run flashes the previous run's text before updating."""
    indicator.begin()
    indicator.add_output("some earlier answer")

    indicator.cancel()

    assert indicator.caption.text() == ""
