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
import threading
from typing import Iterator, Optional

import numpy as np
import sounddevice as sd

# Frames per callback, as a fraction of the sample rate (i.e. 100ms of audio).
# Set explicitly because letting PortAudio choose (blocksize=0) yields ~15-frame
# blocks on macOS when the requested rate differs from the device's native one —
# roughly a thousand queue pushes a second, all overhead and no benefit.
_BLOCK_SECONDS = 0.1


class NoInputDeviceError(RuntimeError):
    """Raised when `device_index` resolves to a device with no input channels.

    Distinguishes "wrong device selected" from a stream that opens fine but
    silently receives nothing because macOS denied microphone permission to
    the process (PortAudio doesn't raise for that — see `resolved_device_name`
    on `AudioCapture` for the diagnostic callers can surface instead).
    """


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
        self.resolved_device_name: Optional[str] = None
        # start()/stop() are called from different threads — a GUI thread asking a
        # worker to stop must be able to release the device (see
        # `CallVoiceCaptureWorker.stop`), so guard the stream handle rather than
        # relying on the callers happening not to overlap.
        self._lock = threading.RLock()

    @staticmethod
    def list_devices() -> list:
        return sd.query_devices()

    def _callback(self, indata, frames, time_info, status) -> None:
        self._queue.put(indata.copy())

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            device = self.device_index
            if device is None:
                device = sd.default.device[0]
            info = sd.query_devices(device)
            if info["max_input_channels"] < 1:
                raise NoInputDeviceError(
                    f"Device {device!r} ({info['name']}) has no input channels — "
                    "it looks like an output/playback device. Check audio.device_index."
                )
            self.resolved_device_name = info["name"]
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=int(self.sample_rate * _BLOCK_SECONDS),
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> None:
        """Closes the stream. Idempotent, and safe to call from another thread."""
        with self._lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._stream is not None

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
        """Yields concatenated float32 audio chunks of ~chunk_seconds each.

        Ends (raising StopIteration) once the stream is stopped, so callers should
        use `next(chunk_iter, None)` and treat None as "capture ended".

        Polls with a timeout rather than blocking on `get()` forever: an untimed
        get can never notice `stop()`, because after the stream closes no further
        blocks arrive to wake it. That left the generator — and whichever thread
        was pulling from it — wedged permanently, holding the microphone open.
        """
        self.start()
        samples_needed = int(self.sample_rate * self.chunk_seconds)
        buffer = np.empty((0, self.channels), dtype=np.float32)
        while self.is_running:
            block = self.read_available(timeout=_BLOCK_SECONDS)
            if block is None:
                continue  # loops back to re-check is_running, so stop() ends this
            buffer = np.concatenate([buffer, block], axis=0)
            if len(buffer) >= samples_needed:
                yield buffer[:samples_needed]
                buffer = buffer[samples_needed:]

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
