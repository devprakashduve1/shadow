"""Desktop/monitor screenshot capture with frame-diff change detection, via mss."""
from __future__ import annotations

import time
from typing import Optional

import mss
import numpy as np


class ScreenCapture:
    def __init__(self, monitor_index: int = 0, change_threshold: float = 0.02):
        """monitor_index 0 = all monitors combined; 1..N = individual monitor."""
        self.monitor_index = monitor_index
        self.change_threshold = change_threshold
        self._sct = mss.mss()
        self._last_gray: Optional[np.ndarray] = None
        self._paused = False

    def list_monitors(self) -> list:
        return self._sct.monitors

    def grab(self) -> np.ndarray:
        monitor = self._sct.monitors[self.monitor_index]
        shot = self._sct.grab(monitor)
        arr = np.array(shot)  # BGRA
        return arr[:, :, :3][:, :, ::-1]  # -> RGB

    def has_changed(self, frame_rgb: np.ndarray) -> bool:
        gray = frame_rgb.mean(axis=2)
        if self._last_gray is None:
            self._last_gray = gray
            return True
        if gray.shape != self._last_gray.shape:
            self._last_gray = gray
            return True
        diff = np.abs(gray - self._last_gray).mean() / 255.0
        self._last_gray = gray
        return diff > self.change_threshold

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def monitor_loop(self, interval_seconds: float = 1.0):
        """Generator yielding (frame_rgb, changed) at a fixed interval until stopped externally."""
        while True:
            if self._paused:
                time.sleep(interval_seconds)
                continue
            frame = self.grab()
            changed = self.has_changed(frame)
            yield frame, changed
            time.sleep(interval_seconds)

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
