"""Webcam capture wrapper around OpenCV's VideoCapture."""
from __future__ import annotations

from typing import Iterator, Optional

import cv2
import numpy as np


class CameraModule:
    def __init__(self, device_index: int = 0, width: int = 640, height: int = 480, fps: int = 30):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        if self._cap is not None:
            return
        cap = cv2.VideoCapture(self.device_index)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera at index {self.device_index}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        self._cap = cap

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> Optional[np.ndarray]:
        if not self.is_open():
            self.open()
        ok, frame = self._cap.read()
        if not ok:
            return None
        return cv2.flip(frame, 1)

    def frames(self) -> Iterator[np.ndarray]:
        self.open()
        while self.is_open():
            frame = self.read()
            if frame is None:
                break
            yield frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "CameraModule":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
