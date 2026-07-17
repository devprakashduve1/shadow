"""Maps normalized hand-landmark coordinates to screen mouse actions via pynput."""
from __future__ import annotations

import time
from typing import Optional, Tuple

from pynput.mouse import Button, Controller


class MouseController:
    def __init__(self, screen_size: Optional[Tuple[int, int]] = None, smoothing: float = 0.5, margin: float = 0.1):
        self._controller = Controller()
        if screen_size is None:
            screen_size = self._detect_screen_size()
        self.screen_w, self.screen_h = screen_size
        self.smoothing = smoothing  # 0 = no smoothing, closer to 1 = more smoothing
        self.margin = margin  # fraction of the frame treated as dead zone at edges
        self._last_pos: Optional[Tuple[float, float]] = None
        self._enabled = True
        self._last_click_time = 0.0
        self._click_cooldown = 0.4

    @staticmethod
    def _detect_screen_size() -> Tuple[int, int]:
        try:
            import pyautogui

            return pyautogui.size()
        except Exception:
            return (1920, 1080)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def _map_to_screen(self, x_norm: float, y_norm: float) -> Tuple[int, int]:
        lo, hi = self.margin, 1.0 - self.margin
        x_clamped = min(max(x_norm, lo), hi)
        y_clamped = min(max(y_norm, lo), hi)
        x_scaled = (x_clamped - lo) / (hi - lo)
        y_scaled = (y_clamped - lo) / (hi - lo)
        return int(x_scaled * self.screen_w), int(y_scaled * self.screen_h)

    def move_to(self, x_norm: float, y_norm: float) -> None:
        if not self._enabled:
            return
        target = self._map_to_screen(x_norm, y_norm)
        if self._last_pos is not None and self.smoothing > 0:
            sx = self._last_pos[0] + (target[0] - self._last_pos[0]) * (1 - self.smoothing)
            sy = self._last_pos[1] + (target[1] - self._last_pos[1]) * (1 - self.smoothing)
            target = (sx, sy)
        self._controller.position = target
        self._last_pos = target

    def click(self, button: str = "left") -> None:
        if not self._enabled:
            return
        now = time.monotonic()
        if now - self._last_click_time < self._click_cooldown:
            return
        self._last_click_time = now
        btn = Button.left if button == "left" else Button.right
        self._controller.click(btn, 1)

    def scroll(self, dx: int, dy: int) -> None:
        if not self._enabled:
            return
        self._controller.scroll(dx, dy)

    def reset(self) -> None:
        self._last_pos = None
