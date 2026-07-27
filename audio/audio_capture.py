"""Audio capture via sounddevice.

Notes on system-audio (loopback) capture:
- macOS has no native loopback input device; install a virtual audio device
  such as BlackHole (https://github.com/ExistentialAudio/BlackHole) and select
  it as `device_index`, optionally paired with a Multi-Output Device in Audio
  MIDI Setup so you can still hear playback while capturing it.
- Windows can use the "Stereo Mix" input if the driver exposes it, or a
  WASAPI loopback device (see soundcard/pyaudiowpatch for a native option).
- Linux (PulseAudio/PipeWire) can monitor the default sink via a ".monitor"
  source selected as `device_index`.

Without a loopback device configured, this module falls back to whatever
default input (typically the microphone) sounddevice reports.
"""
from __future__ import annotations

import queue
from typing import Iterator, Optional

import numpy as np
import sounddevice as sd


class AudioCapture:
    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_seconds: float = 5.0,
    ):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_seconds = chunk_seconds
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None

    @staticmethod
    def list_devices() -> list:
        return sd.query_devices()

    def _callback(self, indata, frames, time_info, status) -> None:
        self._queue.put(indata.copy())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_available(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """Returns the next raw captured block, or None if none arrived in `timeout`.

        The building block `chunks()` is built on, exposed separately for
        callers that need to stop promptly or keep every last sample:
        `chunks()` blocks indefinitely waiting for a full chunk (so it can
        hang after `stop()`, when no more blocks arrive) and discards the
        trailing partial chunk. Polling this instead lets a caller check its
        own "still recording?" flag between blocks — see
        `gui/workers.py`'s `DictationWorker`.

        Block length is whatever the input stream hands the callback, not
        `chunk_seconds`; concatenate along axis 0 to assemble a recording.
        """
        try:
            return self._queue.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return None

    def chunks(self) -> Iterator[np.ndarray]:
        """Yields concatenated float32 audio chunks of ~chunk_seconds each."""
        self.start()
        samples_needed = int(self.sample_rate * self.chunk_seconds)
        buffer = np.empty((0, self.channels), dtype=np.float32)
        while self._stream is not None:
            block = self._queue.get()
            buffer = np.concatenate([buffer, block], axis=0)
            if len(buffer) >= samples_needed:
                yield buffer[:samples_needed]
                buffer = buffer[samples_needed:]

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
