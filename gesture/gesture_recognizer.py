"""Hand landmark tracking (MediaPipe) and simple gesture classification."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import mediapipe as mp
import numpy as np

# Landmark indices, see:
# https://developers.google.com/mediapipe/solutions/vision/hand_landmarker
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_MCP = 13
RING_TIP = 16
PINKY_MCP = 17
PINKY_TIP = 20

FINGER_TIPS = [INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP]
FINGER_MCPS = [INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]


@dataclass
class GestureResult:
    hand_present: bool
    landmarks: Optional[np.ndarray] = None  # (21, 3) normalized [x, y, z]
    gesture: str = "none"  # "none" | "point" | "pinch" | "fist" | "open_palm"
    pointer_xy: Optional[tuple] = None  # normalized (x, y) used for mouse mapping
    pinch_strength: float = 0.0
    handedness: str = ""
    extra: dict = field(default_factory=dict)


class GestureRecognizer:
    """Wraps mediapipe.solutions.hands and classifies a small gesture vocabulary."""

    def __init__(
        self,
        max_hands: int = 1,
        detection_confidence: float = 0.7,
        tracking_confidence: float = 0.7,
        pinch_click_threshold: float = 0.04,
    ):
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            max_num_hands=max_hands,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self.pinch_click_threshold = pinch_click_threshold

    def process(self, frame_bgr: np.ndarray) -> GestureResult:
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)

        if not results.multi_hand_landmarks:
            return GestureResult(hand_present=False)

        hand_landmarks = results.multi_hand_landmarks[0]
        handedness = "unknown"
        if results.multi_handedness:
            handedness = results.multi_handedness[0].classification[0].label

        landmarks = np.array(
            [[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark], dtype=np.float32
        )

        pinch_strength = self._pinch_distance(landmarks)
        gesture = self._classify(landmarks, pinch_strength)
        pointer_xy = (float(landmarks[INDEX_TIP][0]), float(landmarks[INDEX_TIP][1]))

        return GestureResult(
            hand_present=True,
            landmarks=landmarks,
            gesture=gesture,
            pointer_xy=pointer_xy,
            pinch_strength=pinch_strength,
            handedness=handedness,
        )

    def _pinch_distance(self, landmarks: np.ndarray) -> float:
        thumb = landmarks[THUMB_TIP][:2]
        index = landmarks[INDEX_TIP][:2]
        return float(math.dist(thumb, index))

    def _finger_extended(self, landmarks: np.ndarray, tip_idx: int, mcp_idx: int) -> bool:
        wrist = landmarks[WRIST][:2]
        return math.dist(landmarks[tip_idx][:2], wrist) > math.dist(landmarks[mcp_idx][:2], wrist)

    def _classify(self, landmarks: np.ndarray, pinch_strength: float) -> str:
        if pinch_strength < self.pinch_click_threshold:
            return "pinch"

        extended = [
            self._finger_extended(landmarks, tip, mcp)
            for tip, mcp in zip(FINGER_TIPS, FINGER_MCPS)
        ]
        num_extended = sum(extended)

        if num_extended == 0:
            return "fist"
        if num_extended == 1 and extended[0]:
            return "point"
        if num_extended >= 4:
            return "open_palm"
        return "none"

    def close(self) -> None:
        self._hands.close()

    def __enter__(self) -> "GestureRecognizer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
