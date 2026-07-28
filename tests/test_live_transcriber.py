"""Tests for speech/live_transcriber.py.

The speech-to-text engine is stubbed, so these cover the interim/final logic
without loading whisper — what gets transcribed, when, and how it's labelled.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from speech.live_transcriber import LiveResult, LiveTranscriber
from speech.segmenter import SegmenterConfig

SAMPLE_RATE = 16000
BLOCK = 1600


def speech_block(frames: int = BLOCK) -> np.ndarray:
    return (0.3 * np.sin(np.arange(frames) * 0.05)).astype(np.float32).reshape(-1, 1)


def silent_block(frames: int = BLOCK) -> np.ndarray:
    return np.zeros((frames, 1), dtype=np.float32)


@dataclass
class _Seg:
    text: str


class _StubSTT:
    """Records every call and returns a canned transcription."""

    def __init__(self, text="hello world"):
        self.text = text
        self.calls = []

    def transcribe_chunk(self, audio, sample_rate=SAMPLE_RATE):
        self.calls.append((audio.shape[0], sample_rate))
        return [_Seg(text=self.text)] if self.text else []


def _config(**kwargs) -> SegmenterConfig:
    base = dict(sample_rate=SAMPLE_RATE, silence_seconds=0.5, min_utterance_seconds=0.2)
    base.update(kwargs)
    return SegmenterConfig(**base)


# -- finals ------------------------------------------------------------------


def test_a_completed_utterance_yields_a_final_result() -> None:
    stt = _StubSTT("the quick brown fox")
    live = LiveTranscriber(stt, segmenter_config=_config(), interim_interval_seconds=0)

    results = []
    for _ in range(10):
        results.extend(live.push(speech_block()))
    for _ in range(6):
        results.extend(live.push(silent_block()))

    finals = [r for r in results if r.is_final]
    assert len(finals) == 1
    assert finals[0].text == "the quick brown fox"


def test_silence_alone_transcribes_nothing() -> None:
    """No audio should reach the model when nobody is speaking — this is what
    stops whisper inventing 'You' for a quiet room."""
    stt = _StubSTT()
    live = LiveTranscriber(stt, segmenter_config=_config())

    for _ in range(30):
        assert live.push(silent_block()) == []

    assert stt.calls == [], "the model must not be invoked on silence at all"


def test_flush_finalises_speech_still_in_progress() -> None:
    stt = _StubSTT("unfinished sentence")
    live = LiveTranscriber(stt, segmenter_config=_config(), interim_interval_seconds=0)
    for _ in range(5):
        live.push(speech_block())

    results = live.flush()

    assert [r.is_final for r in results] == [True]
    assert results[0].text == "unfinished sentence"


def test_empty_transcriptions_are_not_emitted() -> None:
    """A stub returning nothing stands in for audio whisper found no words in."""
    live = LiveTranscriber(_StubSTT(""), segmenter_config=_config(), interim_interval_seconds=0)

    for _ in range(10):
        live.push(speech_block())
    results = live.flush()

    assert results == []


def test_two_sentences_yield_two_finals() -> None:
    stt = _StubSTT("sentence")
    live = LiveTranscriber(stt, segmenter_config=_config(), interim_interval_seconds=0)

    results = []
    for _ in range(2):
        for _ in range(5):
            results.extend(live.push(speech_block()))
        for _ in range(6):
            results.extend(live.push(silent_block()))

    assert [r.is_final for r in results] == [True, True]


# -- interim -----------------------------------------------------------------


def test_interim_results_arrive_while_still_speaking() -> None:
    stt = _StubSTT("partial")
    live = LiveTranscriber(
        stt, segmenter_config=_config(max_utterance_seconds=60), interim_interval_seconds=0.5
    )

    results = []
    for _ in range(10):  # 1s of continuous speech, no pause yet
        results.extend(live.push(speech_block()))

    assert results, "expected feedback before the sentence ended"
    assert all(r.is_final is False for r in results)


def test_interim_can_be_disabled() -> None:
    stt = _StubSTT("partial")
    live = LiveTranscriber(
        stt, segmenter_config=_config(max_utterance_seconds=60), interim_interval_seconds=0
    )

    results = []
    for _ in range(20):
        results.extend(live.push(speech_block()))

    assert results == []
    assert stt.calls == [], "no interim means no transcription until an utterance closes"


def test_interim_respects_its_interval() -> None:
    """Cadence is driven by audio consumed, so it doesn't depend on machine speed."""
    stt = _StubSTT("partial")
    live = LiveTranscriber(
        stt, segmenter_config=_config(max_utterance_seconds=60), interim_interval_seconds=1.0
    )

    results = []
    for _ in range(30):  # 3s of speech -> roughly one interim per second
        results.extend(live.push(speech_block()))

    assert 2 <= len(results) <= 4, f"expected ~3 interims, got {len(results)}"


def test_a_final_is_not_accompanied_by_an_interim_for_the_same_utterance() -> None:
    """Emitting both would make the text flicker as the interim is superseded."""
    stt = _StubSTT("done")
    live = LiveTranscriber(
        stt, segmenter_config=_config(), interim_interval_seconds=0.1
    )

    for _ in range(6):
        live.push(speech_block())
    closing = []
    for _ in range(6):
        closing.extend(live.push(silent_block()))

    finals = [r for r in closing if r.is_final]
    assert len(finals) == 1
    assert all(r.is_final for r in closing), "no interim alongside the final"


# -- plumbing ----------------------------------------------------------------


def test_the_configured_sample_rate_reaches_the_engine() -> None:
    """Guards the bug where sample_rate was accepted and then ignored."""
    stt = _StubSTT("x")
    live = LiveTranscriber(
        stt,
        segmenter_config=_config(sample_rate=48000, silence_seconds=0.5),
        interim_interval_seconds=0,
        sample_rate=48000,
    )
    for _ in range(20):
        live.push(speech_block())
    live.flush()

    assert stt.calls, "expected at least one transcription"
    assert {rate for _frames, rate in stt.calls} == {48000}


def test_in_speech_reflects_the_segmenter_state() -> None:
    live = LiveTranscriber(_StubSTT(), segmenter_config=_config(), interim_interval_seconds=0)
    assert live.in_speech is False

    live.push(speech_block())

    assert live.in_speech is True
