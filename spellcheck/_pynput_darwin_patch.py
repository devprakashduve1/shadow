"""Workaround for a pynput/macOS crash: moses-palmer/pynput#511.

On macOS, pynput.keyboard.Listener._run() calls Carbon/HIToolbox APIs
(TISCopyCurrentKeyboardInputSource / TISGetInputSourceProperty, wrapped by
pynput's keycode_context()) on its own background listener thread to resolve
the current keyboard layout into self._context. Recent macOS versions assert
that these calls happen on the main dispatch queue; violating this raises
EXC_BREAKPOINT/dispatch_assert_queue_fail and kills the whole process — not
just the listener. This reproduces reliably with real keystrokes (though not
with pynput's own Controller-synthesized ones, which take a different path).

self._context, once set, is never actually read anywhere in pynput's Listener
or its canonical() implementation for this version — character decoding goes
through the separate, thread-safe CGEventKeyboardGetUnicodeString API in
_event_to_key() instead. So the keycode_context() call is both the crash
trigger and functionally dead weight for plain keystroke listening; this patch
just removes it. See the (open, unmerged as of writing) fix proposal at
https://github.com/moses-palmer/pynput/pull/512 for the same diagnosis.
"""
from __future__ import annotations

import sys

_applied = False


def apply() -> None:
    global _applied
    if _applied or sys.platform != "darwin":
        return
    try:
        from pynput.keyboard import _darwin
    except ImportError:
        return

    def _run(self) -> None:
        self._context = None
        try:
            super(_darwin.Listener, self)._run()
        finally:
            self._context = None

    _darwin.Listener._run = _run
    _applied = True
