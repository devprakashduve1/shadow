"""Tests for speech/speech_to_text.py's resampling.

Covers the fix for `transcribe_chunk`'s `sample_rate` argument, which used to be
accepted and then ignored — whisper reads raw samples and assumes 16kHz, so any
other configured rate was transcribed at the wrong speed.

No model is loaded here; `resample_to_whisper_rate` is a pure function.
"""
from __future__ import annotations

import builtins

import numpy as np
import pytest

from speech.speech_to_text import WHISPER_SAMPLE_RATE, resample_to_whisper_rate


def _tone(seconds: float, sample_rate: int, hz: float = 440.0) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / float(sample_rate)
    return (0.4 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


@pytest.fixture
def no_scipy(monkeypatch):
    """Forces the numpy-interpolation fallback, for installs without scipy."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("scipy"):
            raise ImportError("scipy unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


# -- passthrough -------------------------------------------------------------


def test_audio_already_at_16k_is_returned_untouched() -> None:
    audio = _tone(1.0, WHISPER_SAMPLE_RATE)

    result = resample_to_whisper_rate(audio, WHISPER_SAMPLE_RATE)

    assert result is audio, "no copy or conversion when the rate already matches"


def test_empty_audio_is_handled() -> None:
    empty = np.zeros(0, dtype=np.float32)

    assert resample_to_whisper_rate(empty, 48000).size == 0


# -- downsampling ------------------------------------------------------------


@pytest.mark.parametrize("source_rate", [22050, 44100, 48000])
def test_duration_is_preserved_when_resampling(source_rate: int) -> None:
    """A second of audio must still be a second afterwards — getting this wrong
    is exactly what made whisper transcribe at the wrong speed."""
    audio = _tone(1.0, source_rate)

    result = resample_to_whisper_rate(audio, source_rate)

    assert result.shape[0] == pytest.approx(WHISPER_SAMPLE_RATE, rel=0.01)


def test_result_is_float32_for_whisper() -> None:
    result = resample_to_whisper_rate(_tone(0.5, 48000), 48000)

    assert result.dtype == np.float32


def test_resampling_preserves_the_signal_amplitude() -> None:
    """A sanity check that the output is still the same sound, not noise."""
    result = resample_to_whisper_rate(_tone(1.0, 48000, hz=440.0), 48000)

    # 440Hz is well under 16kHz's Nyquist limit, so it survives intact.
    assert 0.2 < float(np.abs(result).max()) < 0.6


def test_upsampling_from_a_low_rate_also_works() -> None:
    audio = _tone(1.0, 8000)

    result = resample_to_whisper_rate(audio, 8000)

    assert result.shape[0] == pytest.approx(WHISPER_SAMPLE_RATE, rel=0.01)


# -- fallback ----------------------------------------------------------------


def test_falls_back_to_interpolation_without_scipy(no_scipy) -> None:
    """scipy is not a declared dependency, so the numpy path must still work."""
    audio = _tone(1.0, 48000)

    result = resample_to_whisper_rate(audio, 48000)

    assert result.shape[0] == pytest.approx(WHISPER_SAMPLE_RATE, rel=0.01)
    assert result.dtype == np.float32


def test_fallback_preserves_amplitude(no_scipy) -> None:
    result = resample_to_whisper_rate(_tone(1.0, 48000, hz=440.0), 48000)

    assert 0.2 < float(np.abs(result).max()) < 0.6


def test_fallback_handles_audio_shorter_than_one_output_sample(no_scipy) -> None:
    tiny = np.zeros(2, dtype=np.float32)

    assert resample_to_whisper_rate(tiny, 48000 * 1000).size == 0
