"""Local speech-to-text transcription using faster-whisper."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class TranscriptSegment:
    text: str
    start: float
    end: float
    timestamp: float  # wall-clock time.time() when transcribed


class SpeechToText:
    def __init__(self, model_size: str = "base", language: str = "en", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel

        self.language = language
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe_chunk(self, audio: np.ndarray, sample_rate: int = 16000) -> List[TranscriptSegment]:
        """audio: float32 mono samples in [-1, 1] at `sample_rate` (resample to 16kHz upstream if needed)."""
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)

        segments, _info = self._model.transcribe(audio, language=self.language)
        now = time.time()
        return [
            TranscriptSegment(text=seg.text.strip(), start=seg.start, end=seg.end, timestamp=now)
            for seg in segments
            if seg.text.strip()
        ]
