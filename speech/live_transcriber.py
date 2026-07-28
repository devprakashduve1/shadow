"""Turns a stream of audio blocks into live transcription results.

Combines `UtteranceSegmenter` (when to transcribe) with a speech-to-text engine
(what was said), producing two kinds of result:

- **interim** — a best-effort reading of the sentence still being spoken. It is
  revisable: each interim replaces the previous one.
- **final** — an utterance that finished at a pause. Never revised afterwards.

The engine is injected rather than constructed here, so this logic can be tested
against a stub without loading a whisper model or opening a microphone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol

import numpy as np

from .segmenter import SegmenterConfig, UtteranceSegmenter
from .speech_to_text import WHISPER_SAMPLE_RATE


class SupportsTranscribe(Protocol):
    """The slice of `SpeechToText` this module depends on."""

    def transcribe_chunk(self, audio: np.ndarray, sample_rate: int = ...) -> list:
        ...


@dataclass
class LiveResult:
    text: str
    is_final: bool


class LiveTranscriber:
    """Stateful pipeline: push audio blocks in, get transcription results out."""

    def __init__(
        self,
        transcriber: SupportsTranscribe,
        segmenter_config: Optional[SegmenterConfig] = None,
        interim_interval_seconds: float = 1.5,
        sample_rate: int = WHISPER_SAMPLE_RATE,
    ):
        self._transcriber = transcriber
        self._segmenter = UtteranceSegmenter(segmenter_config or SegmenterConfig(sample_rate=sample_rate))
        self._sample_rate = sample_rate
        # 0 or less disables interim results, leaving only finals — worth doing on
        # a slow machine, where re-transcribing the pending buffer every second
        # and a half costs more than the feedback is worth.
        self._interim_interval = interim_interval_seconds
        self._last_interim_at = 0.0

    def push(self, block: np.ndarray) -> List[LiveResult]:
        """Feeds one captured block; returns whatever results it produced."""
        results: List[LiveResult] = []
        for utterance in self._segmenter.push(block):
            self._last_interim_at = 0.0
            results.extend(self._transcribe(utterance, is_final=True))
        # Only when nothing was finalised: a final already supersedes any interim
        # for that utterance, so emitting one straight after would flicker.
        if not results:
            interim = self._maybe_interim()
            if interim is not None:
                results.append(interim)
        return results

    def flush(self) -> List[LiveResult]:
        """Finalises the utterance in progress — call when recording stops."""
        results: List[LiveResult] = []
        for utterance in self._segmenter.flush():
            results.extend(self._transcribe(utterance, is_final=True))
        self._last_interim_at = 0.0
        return results

    @property
    def in_speech(self) -> bool:
        return self._segmenter.in_speech

    # -- internals --------------------------------------------------------

    def _maybe_interim(self) -> Optional[LiveResult]:
        if self._interim_interval <= 0 or not self._segmenter.in_speech:
            return None
        # Nothing new has been said during a pause, so re-transcribing the same
        # buffer would burn CPU to produce identical text — and the final is
        # about to supersede it anyway.
        if self._segmenter.in_trailing_silence:
            return None
        pending = self._segmenter.pending_seconds
        # Measured in audio consumed rather than wall-clock time, so the cadence
        # doesn't depend on how fast transcription happens to run.
        if pending - self._last_interim_at < self._interim_interval:
            return None
        self._last_interim_at = pending
        audio = self._segmenter.pending_audio()
        if audio is None:
            return None
        texts = self._transcribe(audio, is_final=False)
        return texts[0] if texts else None

    def _transcribe(self, audio: np.ndarray, is_final: bool) -> List[LiveResult]:
        segments = self._transcriber.transcribe_chunk(audio, sample_rate=self._sample_rate)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        if not text:
            return []
        return [LiveResult(text=text, is_final=is_final)]
