"""Local speech-to-text transcription using faster-whisper."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

import numpy as np

# What whisper itself was trained on; anything else has to be resampled before
# it reaches the model, which reads raw samples and cannot infer the rate.
WHISPER_SAMPLE_RATE = 16000


@dataclass
class TranscriptSegment:
    text: str
    start: float
    end: float
    timestamp: float  # wall-clock time.time() when transcribed


def resample_to_whisper_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resamples mono float32 `audio` to 16kHz, whisper's expected rate.

    Split out from `transcribe_chunk` so the live-transcription path can reuse it
    and so it's testable without loading a model.
    """
    if sample_rate == WHISPER_SAMPLE_RATE or audio.size == 0:
        return audio
    from math import gcd

    divisor = gcd(int(sample_rate), WHISPER_SAMPLE_RATE)
    try:
        from scipy.signal import resample_poly

        return resample_poly(
            audio, WHISPER_SAMPLE_RATE // divisor, int(sample_rate) // divisor
        ).astype(np.float32)
    except ImportError:
        # Linear interpolation is a downgrade in quality but keeps a non-16kHz
        # device usable rather than silently feeding whisper the wrong rate.
        duration = audio.shape[0] / float(sample_rate)
        target_len = int(round(duration * WHISPER_SAMPLE_RATE))
        if target_len <= 0:
            return np.zeros(0, dtype=np.float32)
        source_x = np.arange(audio.shape[0], dtype=np.float64)
        target_x = np.linspace(0, audio.shape[0] - 1, target_len, dtype=np.float64)
        return np.interp(target_x, source_x, audio).astype(np.float32)


class SpeechToText:
    def __init__(self, model_size: str = "base", language: str = "en", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel

        self.language = language
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe_chunk(self, audio: np.ndarray, sample_rate: int = WHISPER_SAMPLE_RATE) -> List[TranscriptSegment]:
        """audio: float32 mono (or multi-channel, which is averaged) samples in [-1, 1]."""
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        # Previously this argument was accepted and then ignored, so any
        # `audio.sample_rate` other than 16000 was handed to whisper as if it
        # were 16kHz — transcribing at the wrong speed and garbling the text.
        audio = resample_to_whisper_rate(audio, sample_rate)

        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            # Without voice-activity filtering whisper invents text for silence:
            # a few seconds of a quiet room reliably decodes as "You" or
            # "Thank you." Dictation ends with the user pausing before they click
            # stop, so this was firing on almost every take.
            vad_filter=True,
        )
        now = time.time()
        return [
            TranscriptSegment(text=seg.text.strip(), start=seg.start, end=seg.end, timestamp=now)
            for seg in segments
            if seg.text.strip()
        ]
