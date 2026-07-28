"""Splits a stream of audio blocks into utterances at natural pauses.

Live transcription needs to know *when* to transcribe: whisper works on whole
utterances, so feeding it a fixed 5-second window cuts words in half and produces
text that changes as the window slides. Cutting on silence instead means each
piece of text is final once emitted.

Deliberately free of Qt, whisper and sounddevice — this is pure sample-crunching,
which keeps it unit-testable with synthetic arrays (see
tests/test_segmenter.py) rather than needing a microphone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class SegmenterConfig:
    """Thresholds for deciding what counts as speech and what ends an utterance."""

    sample_rate: int = 16000
    # RMS below this is treated as silence. Room tone measures well under 0.01 on
    # a laptop mic; ordinary speech is an order of magnitude above it.
    silence_rms: float = 0.01
    # Trailing silence that closes an utterance. Long enough to sit through the
    # pause mid-sentence, short enough that text appears while you're still
    # talking.
    silence_seconds: float = 0.8
    # Utterances shorter than this are discarded as coughs, clicks and door
    # slams — transcribing them yields hallucinated filler.
    min_utterance_seconds: float = 0.4
    # A hard cut for someone who never pauses, so text keeps flowing instead of
    # arriving in one block at the end.
    max_utterance_seconds: float = 20.0
    # Audio kept from just before speech was detected, so the first phoneme
    # isn't clipped by the detector's own reaction time.
    preroll_seconds: float = 0.3


def block_rms(block: np.ndarray) -> float:
    """Root-mean-square level of one block, averaged down to mono."""
    if block.size == 0:
        return 0.0
    mono = block.mean(axis=1) if block.ndim > 1 else block
    return float(np.sqrt(np.mean(np.square(mono.astype(np.float64)))))


class UtteranceSegmenter:
    """Feeds on audio blocks and hands back complete utterances.

    Usage: `push()` every block as it arrives, then `flush()` once at the end to
    collect whatever speech was still in progress.
    """

    def __init__(self, config: Optional[SegmenterConfig] = None):
        self.config = config or SegmenterConfig()
        self._speech: List[np.ndarray] = []  # blocks of the utterance in progress
        self._preroll: List[np.ndarray] = []  # recent blocks, before speech starts
        self._speech_frames = 0
        self._preroll_frames = 0
        self._trailing_silent_frames = 0
        # Frames that actually read as speech, tracked separately from
        # `_speech_frames` (which includes pre-roll and interior pauses) so the
        # "too short to be speech" test measures voice and not padding.
        self._voiced_frames = 0

    # -- state ------------------------------------------------------------

    @property
    def in_speech(self) -> bool:
        return bool(self._speech)

    @property
    def pending_seconds(self) -> float:
        """Duration of the utterance currently being collected."""
        return self._speech_frames / float(self.config.sample_rate)

    @property
    def in_trailing_silence(self) -> bool:
        """True when the utterance is mid-pause, i.e. no new speech since the
        last block. Lets callers skip work that only matters while words are
        still arriving."""
        return self._trailing_silent_frames > 0

    def pending_audio(self) -> Optional[np.ndarray]:
        """The in-progress utterance, for an interim (revisable) transcription."""
        if not self._speech:
            return None
        return np.concatenate(self._speech, axis=0)

    # -- feeding ----------------------------------------------------------

    def push(self, block: np.ndarray) -> List[np.ndarray]:
        """Adds one block; returns any utterances it completed (usually none)."""
        if block is None or block.size == 0:
            return []
        cfg = self.config
        is_speech = block_rms(block) >= cfg.silence_rms

        if not self.in_speech:
            if is_speech:
                # Open the utterance with the retained pre-roll so the onset,
                # which is quiet enough to have read as silence, is included.
                self._speech = [*self._preroll, block]
                self._speech_frames = self._preroll_frames + block.shape[0]
                self._voiced_frames = block.shape[0]  # pre-roll is not voiced
                self._trailing_silent_frames = 0
                self._preroll, self._preroll_frames = [], 0
            else:
                self._remember_preroll(block)
            return []

        self._speech.append(block)
        self._speech_frames += block.shape[0]
        if is_speech:
            self._voiced_frames += block.shape[0]
        # Tracked as a run: any speech block resets it, so a pause only counts
        # when it is uninterrupted.
        self._trailing_silent_frames = (
            0 if is_speech else self._trailing_silent_frames + block.shape[0]
        )

        silence_limit = int(cfg.silence_seconds * cfg.sample_rate)
        max_frames = int(cfg.max_utterance_seconds * cfg.sample_rate)
        if self._trailing_silent_frames >= silence_limit:
            return self._close(trim_trailing_silence=True)
        if self._speech_frames >= max_frames:
            return self._close(trim_trailing_silence=False)
        return []

    def flush(self) -> List[np.ndarray]:
        """Closes any utterance in progress — call when the recording ends."""
        if not self.in_speech:
            return []
        return self._close(trim_trailing_silence=True)

    def reset(self) -> None:
        self._speech, self._preroll = [], []
        self._speech_frames = self._preroll_frames = self._voiced_frames = 0
        self._trailing_silent_frames = 0

    # -- internals --------------------------------------------------------

    def _remember_preroll(self, block: np.ndarray) -> None:
        """Keeps the most recent `preroll_seconds` of pre-speech audio."""
        limit = int(self.config.preroll_seconds * self.config.sample_rate)
        if limit <= 0:
            return
        self._preroll.append(block)
        self._preroll_frames += block.shape[0]
        while self._preroll_frames > limit and len(self._preroll) > 1:
            self._preroll_frames -= self._preroll.pop(0).shape[0]

    def _close(self, trim_trailing_silence: bool) -> List[np.ndarray]:
        cfg = self.config
        audio = np.concatenate(self._speech, axis=0)
        voiced_frames = self._voiced_frames
        if trim_trailing_silence and self._trailing_silent_frames:
            # Keep a little of the pause: whisper's own VAD uses the tail to
            # decide a sentence ended, and a hard cut can clip the last word.
            keep = int(0.2 * cfg.sample_rate)
            end = max(0, audio.shape[0] - self._trailing_silent_frames + keep)
            audio = audio[:end]
        self.reset()
        if voiced_frames < int(cfg.min_utterance_seconds * cfg.sample_rate):
            return []  # a click or a cough, not speech
        return [audio]
