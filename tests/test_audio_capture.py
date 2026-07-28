"""Tests for audio/audio_capture.py's device validation.

Covers the fix for "no audio captured" reports: `start()` now checks the
resolved device actually has input channels before opening a stream, instead
of only surfacing a problem once callbacks silently never arrive.
"""
from __future__ import annotations

import pytest

from audio.audio_capture import AudioCapture, NoInputDeviceError


class _FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_sd(monkeypatch):
    devices = {
        0: {"name": "MacBook Pro Microphone", "max_input_channels": 1},
        1: {"name": "BlackHole 2ch", "max_input_channels": 2},
        2: {"name": "MacBook Pro Speakers", "max_input_channels": 0},
    }

    class _Default:
        device = (0, 0)

    fake = type("FakeSD", (), {})()
    fake.default = _Default()
    fake.query_devices = lambda index=None: devices[index if index is not None else fake.default.device[0]]
    fake.InputStream = lambda **kwargs: _FakeStream(**kwargs)

    monkeypatch.setattr("audio.audio_capture.sd", fake)
    return fake


def test_start_opens_a_valid_input_device(fake_sd) -> None:
    capture = AudioCapture(device_index=1)

    capture.start()

    assert capture.resolved_device_name == "BlackHole 2ch"
    assert capture._stream.started is True


def test_start_uses_the_system_default_when_no_index_given(fake_sd) -> None:
    capture = AudioCapture(device_index=None)

    capture.start()

    assert capture.resolved_device_name == "MacBook Pro Microphone"


def test_start_rejects_an_output_only_device(fake_sd) -> None:
    """The concrete "no audio ever" case this fix targets: device_index pointed
    at a playback device (0 input channels) rather than a microphone."""
    capture = AudioCapture(device_index=2)

    with pytest.raises(NoInputDeviceError):
        capture.start()

    assert capture._stream is None, "must not open a stream for an invalid device"
