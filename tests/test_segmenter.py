"""Tests for speech/segmenter.py — utterance boundary detection.

Uses synthetic audio (loud sine = speech, zeros = silence) so the state machine
is exercised deterministically without a microphone or a model.
"""
from __future__ import annotations

import numpy as np
import pytest

from speech.segmenter import SegmenterConfig, UtteranceSegmenter, block_rms

SAMPLE_RATE = 16000
BLOCK = 1600  # 100ms, matching AudioCapture's blocksize


def speech_block(frames: int = BLOCK, amplitude: float = 0.3) -> np.ndarray:
    """A block loud enough to read as speech."""
    return (amplitude * np.sin(np.arange(frames) * 0.05)).astype(np.float32).reshape(-1, 1)


def silent_block(frames: int = BLOCK) -> np.ndarray:
    return np.zeros((frames, 1), dtype=np.float32)


@pytest.fixture
def segmenter() -> UtteranceSegmenter:
    return UtteranceSegmenter(
        SegmenterConfig(sample_rate=SAMPLE_RATE, silence_seconds=0.5, min_utterance_seconds=0.2)
    )


# -- level detection ---------------------------------------------------------


def test_block_rms_separates_speech_from_silence() -> None:
    assert block_rms(silent_block()) == 0.0
    assert block_rms(speech_block()) > 0.01


def test_block_rms_handles_mono_and_multichannel() -> None:
    stereo = np.tile(speech_block(), (1, 2))
    assert block_rms(stereo) == pytest.approx(block_rms(speech_block().ravel()), rel=1e-6)


def test_block_rms_of_empty_audio_is_zero() -> None:
    assert block_rms(np.zeros((0, 1), dtype=np.float32)) == 0.0


# -- boundaries --------------------------------------------------------------


def test_silence_alone_never_starts_an_utterance(segmenter) -> None:
    for _ in range(20):
        assert segmenter.push(silent_block()) == []
    assert segmenter.in_speech is False


def test_speech_starts_but_does_not_immediately_close_an_utterance(segmenter) -> None:
    assert segmenter.push(speech_block()) == []
    assert segmenter.in_speech is True


def test_utterance_closes_after_enough_trailing_silence(segmenter) -> None:
    for _ in range(10):  # 1s of speech
        segmenter.push(speech_block())

    completed = []
    for _ in range(6):  # 0.6s of silence, past the 0.5s threshold
        completed.extend(segmenter.push(silent_block()))

    assert len(completed) == 1
    assert segmenter.in_speech is False, "state resets ready for the next utterance"


def test_a_short_pause_does_not_split_a_sentence(segmenter) -> None:
    """0.3s of silence is a mid-sentence breath, not the end of a thought."""
    for _ in range(5):
        segmenter.push(speech_block())
    for _ in range(3):  # 0.3s — under the 0.5s threshold
        assert segmenter.push(silent_block()) == []
    for _ in range(5):
        assert segmenter.push(speech_block()) == []

    assert segmenter.in_speech is True, "still one continuing utterance"


def test_blips_are_discarded_as_not_speech(segmenter) -> None:
    """A single click shorter than min_utterance_seconds yields nothing."""
    segmenter.push(speech_block())  # 100ms, under the 200ms minimum

    completed = []
    for _ in range(6):
        completed.extend(segmenter.push(silent_block()))

    assert completed == []


def test_long_unbroken_speech_is_force_cut(segmenter) -> None:
    """Someone who never pauses still gets text, rather than one block at the end."""
    small = UtteranceSegmenter(
        SegmenterConfig(sample_rate=SAMPLE_RATE, max_utterance_seconds=1.0, min_utterance_seconds=0.2)
    )
    completed = []
    for _ in range(12):  # 1.2s of unbroken speech, past the 1.0s cap
        completed.extend(small.push(speech_block()))

    assert len(completed) == 1
    # The speech after the cut carries on as a fresh utterance rather than being
    # dropped — the cap splits the stream, it doesn't end it.
    assert small.in_speech is True


def test_two_sentences_produce_two_utterances(segmenter) -> None:
    completed = []
    for _ in range(2):
        for _ in range(5):
            completed.extend(segmenter.push(speech_block()))
        for _ in range(6):
            completed.extend(segmenter.push(silent_block()))

    assert len(completed) == 2


# -- pre-roll ----------------------------------------------------------------


def test_preroll_is_included_so_the_onset_is_not_clipped() -> None:
    """The detector only notices speech once a block is loud, so the audio just
    before that has to be retained or the first phoneme is lost."""
    seg = UtteranceSegmenter(
        SegmenterConfig(sample_rate=SAMPLE_RATE, preroll_seconds=0.3, min_utterance_seconds=0.0)
    )
    for _ in range(10):
        seg.push(silent_block())  # builds up pre-roll
    seg.push(speech_block())

    pending = seg.pending_audio()
    assert pending is not None
    # One speech block plus retained pre-roll, not the speech block alone.
    assert pending.shape[0] > BLOCK


def test_preroll_does_not_grow_without_bound() -> None:
    seg = UtteranceSegmenter(SegmenterConfig(sample_rate=SAMPLE_RATE, preroll_seconds=0.3))
    for _ in range(100):  # 10s of silence
        seg.push(silent_block())
    seg.push(speech_block())

    # ~0.3s of pre-roll + 0.1s of speech, nowhere near the 10s pushed in.
    assert seg.pending_audio().shape[0] <= int(0.6 * SAMPLE_RATE)


# -- misc --------------------------------------------------------------------


def test_flush_finalises_speech_in_progress(segmenter) -> None:
    for _ in range(5):
        segmenter.push(speech_block())

    completed = segmenter.flush()

    assert len(completed) == 1
    assert segmenter.in_speech is False


def test_flush_with_nothing_pending_returns_nothing(segmenter) -> None:
    assert segmenter.flush() == []


def test_pending_seconds_tracks_the_utterance_length(segmenter) -> None:
    for _ in range(10):
        segmenter.push(speech_block())

    assert segmenter.pending_seconds == pytest.approx(1.0, abs=0.05)


def test_empty_blocks_are_ignored(segmenter) -> None:
    assert segmenter.push(np.zeros((0, 1), dtype=np.float32)) == []
    assert segmenter.push(None) == []
