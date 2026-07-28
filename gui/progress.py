"""Progress reporting for long-running AI work.

Two pieces, deliberately separate:

- `ProgressTracker` — a pure state machine deciding *what* to say and whether a
  percentage is even knowable. No Qt, so it's unit-testable without a display
  (see tests/test_progress.py).
- `AIProgressIndicator` — the widget that renders a `ProgressState`, owns the
  animation, and hides itself when there's nothing to report.

The guiding rule is that a percentage is only ever shown when something actually
counted the work. Everything else gets an indeterminate bar plus a stage
message: a bar creeping to 90% and sitting there is worse than no bar at all,
because it makes the app look broken rather than busy.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PyQt6.QtWidgets import QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget


class Stage:
    """Coarse phases of an AI request, in the order they normally occur."""

    IDLE = "idle"
    PREPARING = "preparing"  # building the prompt, retrieving context
    LOADING_MODEL = "loading_model"  # a model is being loaded into memory
    WAITING = "waiting"  # request sent, nothing back yet
    GENERATING = "generating"  # tokens arriving
    WORKING = "working"  # countable work, e.g. indexing files
    LISTENING = "listening"  # capturing audio
    TRANSCRIBING = "transcribing"
    DONE = "done"


_DEFAULT_LABELS = {
    Stage.PREPARING: "Processing request...",
    Stage.LOADING_MODEL: "Loading model...",
    Stage.WAITING: "Waiting for the model...",
    Stage.GENERATING: "Generating response...",
    Stage.WORKING: "Working...",
    Stage.LISTENING: "Listening...",
    Stage.TRANSCRIBING: "Transcribing...",
    Stage.DONE: "Done",
    Stage.IDLE: "",
}

# How long a request may sit with no output before the message acknowledges the
# wait. Ollama loads the model on first use, which is invisible from here and can
# take far longer than the request itself — saying so beats an unexplained pause.
WAIT_ESCALATION_SECONDS = 4.0


@dataclass(frozen=True)
class ProgressState:
    """A snapshot for the widget to render.

    `percent is None` means indeterminate — the bar should animate without
    claiming a position.
    """

    stage: str = Stage.IDLE
    label: str = ""
    percent: Optional[int] = None
    detail: str = ""

    @property
    def active(self) -> bool:
        return self.stage not in (Stage.IDLE, Stage.DONE)

    @property
    def determinate(self) -> bool:
        return self.percent is not None


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


class ProgressTracker:
    """Turns coarse events from a worker into a `ProgressState`.

    Callers push events (`begin`, `set_stage`, `set_counted_progress`,
    `add_output`, `tick`, `end`); the tracker decides the wording and whether a
    percentage is justified.
    """

    def __init__(self, wait_escalation_seconds: float = WAIT_ESCALATION_SECONDS):
        self._state = ProgressState()
        self._wait_escalation = wait_escalation_seconds
        self._output_chars = 0
        self._escalated = False

    @property
    def state(self) -> ProgressState:
        return self._state

    def begin(self, label: Optional[str] = None, stage: str = Stage.PREPARING) -> ProgressState:
        """Starts a new run, discarding anything from the previous one."""
        self._output_chars = 0
        self._escalated = False
        self._state = ProgressState(
            stage=stage, label=label or _DEFAULT_LABELS.get(stage, ""), percent=None
        )
        return self._state

    def set_stage(
        self, stage: str, label: Optional[str] = None, detail: str = ""
    ) -> ProgressState:
        """Moves to `stage`, dropping any percentage that no longer applies."""
        # An explicit stage change means the counted work (if any) is over, so
        # the old percentage would be stale rather than merely imprecise.
        self._state = ProgressState(
            stage=stage,
            label=label or _DEFAULT_LABELS.get(stage, ""),
            percent=None,
            detail=detail,
        )
        return self._state

    def set_counted_progress(
        self, done: int, total: int, label: Optional[str] = None
    ) -> ProgressState:
        """Reports genuinely countable work — the only route to a percentage.

        A `total` of zero or less is treated as unknown rather than as 0% or a
        division error, which is what an empty or not-yet-sized job looks like.
        """
        percent = None if total <= 0 else max(0, min(100, round(done / total * 100)))
        self._state = ProgressState(
            stage=Stage.WORKING,
            label=label or _DEFAULT_LABELS[Stage.WORKING],
            percent=percent,
            detail=f"{done:,} of {total:,}" if total > 0 else "",
        )
        return self._state

    def add_output(self, text: str) -> ProgressState:
        """Records streamed model output.

        The first call is the moment generation actually began — the one useful
        transition in an otherwise opaque wait — so it always switches stage.
        """
        self._output_chars += len(text)
        self._state = ProgressState(
            stage=Stage.GENERATING,
            label=_DEFAULT_LABELS[Stage.GENERATING],
            percent=None,  # a response's length isn't known until it ends
            detail=_plural(self._output_chars, "character"),
        )
        return self._state

    def tick(self, elapsed_seconds: float) -> ProgressState:
        """Advances time-based messaging; call periodically while active.

        Only ever escalates the *wording* of a wait — it never moves a bar,
        because elapsed time says nothing about how much is left.
        """
        if not self._state.active or self._escalated:
            return self._state
        if self._state.stage != Stage.PREPARING or elapsed_seconds < self._wait_escalation:
            return self._state
        self._escalated = True
        self._state = replace(
            self._state,
            stage=Stage.WAITING,
            label=_DEFAULT_LABELS[Stage.WAITING],
            detail="first use loads the model, which can take a while",
        )
        return self._state

    def end(self) -> ProgressState:
        self._state = ProgressState(stage=Stage.DONE, label=_DEFAULT_LABELS[Stage.DONE])
        return self._state

    def reset(self) -> ProgressState:
        self._state = ProgressState()
        return self._state


class AIProgressIndicator(QWidget):
    """A thin progress bar with a stage caption, hidden unless work is running.

    Owns its own tracker and a timer driving `tick`, so a caller only has to
    report events it already knows about (`begin`, `add_output`, `end`) and never
    has to manage timing or decide between determinate and indeterminate.
    """

    # Cadence of the wait-escalation check. Comfortably finer than the ~4s
    # escalation, without waking the GUI thread more than necessary.
    _TICK_MS = 500
    # Kept on screen briefly at completion so a fast request still registers as
    # having done something, rather than flickering.
    _LINGER_MS = 700

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracker = ProgressTracker()
        self._elapsed = 0.0

        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        # Matches the muted hint styling used elsewhere in the app (see
        # `ai_panel._section_label`) so this reads as status, not content.
        self.caption.setStyleSheet("color: #888; font-size: 11px;")

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.bar)

        # Animates determinate jumps so a bar that advances in coarse steps (a
        # file at a time while indexing) still moves smoothly.
        self._animation = QPropertyAnimation(self.bar, b"value", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self._TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._finish_hiding)

        self.setVisible(False)

    # -- driving ----------------------------------------------------------

    def begin(self, label: Optional[str] = None, stage: str = Stage.PREPARING) -> None:
        self._elapsed = 0.0
        self._hide_timer.stop()
        self._apply(self._tracker.begin(label, stage))
        self._tick_timer.start()

    def set_stage(self, stage: str, label: Optional[str] = None, detail: str = "") -> None:
        self._apply(self._tracker.set_stage(stage, label, detail))

    def set_counted_progress(self, done: int, total: int, label: Optional[str] = None) -> None:
        self._apply(self._tracker.set_counted_progress(done, total, label))

    def add_output(self, text: str) -> None:
        self._apply(self._tracker.add_output(text))

    def end(self) -> None:
        """Completes the run and hides shortly afterwards."""
        self._tick_timer.stop()
        if not self._tracker.state.active:
            # Nothing was ever started (e.g. an instant failure), so there's
            # nothing to linger over. Deliberately not `isVisible()`, which is
            # also False whenever this sits in a background tab — that would
            # skip the completion state for any request the user tabbed away
            # from.
            self._apply(self._tracker.reset())
            return
        self._apply(self._tracker.end())
        self._hide_timer.start(self._LINGER_MS)

    def cancel(self) -> None:
        """Clears immediately, without the completion linger."""
        self._tick_timer.stop()
        self._hide_timer.stop()
        self._apply(self._tracker.reset())

    @property
    def state(self) -> ProgressState:
        return self._tracker.state

    # -- rendering --------------------------------------------------------

    def _apply(self, state: ProgressState) -> None:
        if state.stage == Stage.IDLE:
            self.setVisible(False)
            self.caption.clear()  # so a later run can't flash the old caption
            return

        text = state.label
        if state.detail:
            text = f"{text}  ({state.detail})" if text else state.detail
        self.caption.setText(text)

        if state.determinate:
            if self.bar.maximum() == 0:  # leaving indeterminate mode
                self.bar.setRange(0, 100)
                self.bar.setValue(state.percent or 0)
            else:
                self._animate_to(state.percent or 0)
        else:
            self._animation.stop()
            # 0..0 is Qt's indeterminate ("busy") bar, which animates itself.
            self.bar.setRange(0, 0)

        self.setVisible(True)

    def _animate_to(self, percent: int) -> None:
        self._animation.stop()
        self._animation.setStartValue(self.bar.value())
        self._animation.setEndValue(percent)
        self._animation.start()

    def _on_tick(self) -> None:
        self._elapsed += self._TICK_MS / 1000.0
        before = self._tracker.state
        after = self._tracker.tick(self._elapsed)
        if after != before:
            self._apply(after)

    def _finish_hiding(self) -> None:
        self._apply(self._tracker.reset())
