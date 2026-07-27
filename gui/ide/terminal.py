"""Terminal panel for the Code tab: a real shell on a PTY, rendered by xterm.js.

Two halves:

- `assistant/pty_session.py` owns the PTY and the child process (Qt-free, so it's
  directly testable).
- this module wires that fd to Qt with a `QSocketNotifier`, and renders the bytes
  with xterm.js in a `QWebEngineView` — reusing the same WebChannel pattern as the
  Monaco editor (see `monaco.py` for the sequencing rules).

xterm.js rather than a `QPlainTextEdit` because PTY output is full of ANSI escape
sequences. A plain text widget renders those as literal garbage; xterm.js is an
actual terminal emulator, which is why vim, htop, and coloured test output work.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSocketNotifier, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from assistant.pty_session import PtyError, PtySession

from .monaco import REPO_ROOT, _MonacoWebWidget

DEFAULT_XTERM_DIR = REPO_ROOT / "vendor" / "xterm"
TERMINAL_HOST_HTML = "terminal_host.html"
_REQUIRED_ASSETS = ("lib/xterm.js", "css/xterm.css")


def xterm_assets_available(xterm_dir: Path = DEFAULT_XTERM_DIR) -> bool:
    """True if the vendored xterm.js build and host page are present."""
    if not (xterm_dir / TERMINAL_HOST_HTML).is_file():
        return False
    return all((xterm_dir / rel).is_file() for rel in _REQUIRED_ASSETS)


class TerminalBridge(QObject):
    """JS->Python entry points for the terminal.

    Slot names match what the host page calls (`ready`, `input`, `resized`);
    the signals they emit are named differently on purpose — a slot and a signal
    sharing one name would make the slot unreachable, since the class attribute
    resolves to the signal.
    """

    terminal_ready = pyqtSignal()
    input_received = pyqtSignal(str)
    size_changed = pyqtSignal(int, int)

    @pyqtSlot()
    def ready(self) -> None:
        self.terminal_ready.emit()

    @pyqtSlot(str)
    def input(self, data: str) -> None:
        self.input_received.emit(data)

    @pyqtSlot(int, int)
    def resized(self, cols: int, rows: int) -> None:
        self.size_changed.emit(cols, rows)


class TerminalPanel(_MonacoWebWidget):
    """A shell running in the project directory.

    The session starts lazily on first `start()` — spawning a login shell for
    every repo the user merely glances at would be wasteful, and `-l` shells can
    take a moment to read the user's profile.
    """

    exited = pyqtSignal(int)

    def __init__(self, xterm_dir: Optional[Path] = None, parent=None):
        bridge = TerminalBridge()
        super().__init__(
            TERMINAL_HOST_HTML, bridge, Path(xterm_dir or DEFAULT_XTERM_DIR), parent
        )
        self._terminal_bridge = bridge
        self._session: Optional[PtySession] = None
        self._notifier: Optional[QSocketNotifier] = None
        self._cwd: Optional[Path] = None
        self._pending_output: list = []

        bridge.terminal_ready.connect(self._on_page_ready)
        bridge.input_received.connect(self._on_input)
        bridge.size_changed.connect(self._on_size_changed)

        # Poll for child exit. There's no signal for "the shell exited" —
        # the fd reporting EOF is the only clue, and that arrives via the
        # notifier, so this is the backstop for the case where it doesn't.
        self._exit_timer = QTimer(self)
        self._exit_timer.setInterval(1000)
        self._exit_timer.timeout.connect(self._check_exit)

    @staticmethod
    def _assets_available(directory: Path) -> bool:
        return xterm_assets_available(directory)

    def _build_missing_assets_notice(self) -> QLabel:
        label = QLabel(
            "Terminal assets aren't installed.\n\n"
            "Run this once, then reopen Shadow:\n\n"
            "    python scripts/fetch_vendor.py\n\n"
            f"(expected xterm.js under {self._monaco_dir})"
        )
        label.setWordWrap(True)
        label.setStyleSheet("padding: 24px; color: #cccccc;")
        return label

    # -- session lifecycle -------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._session is not None and self._session.is_running

    def set_cwd(self, cwd: Optional[str]) -> None:
        """Points the terminal at a directory.

        A running shell isn't relocated — its own `cd` history is the user's, not
        ours to overwrite. The new directory applies to the next session.
        """
        self._cwd = Path(cwd) if cwd else None

    def start(self) -> None:
        """Starts a shell, replacing any previous session."""
        if not self.is_available:
            return
        if self._cwd is None or not self._cwd.is_dir():
            self._write_to_terminal("\r\n\x1b[33mOpen a repository first.\x1b[0m\r\n")
            return
        if self.is_running:
            self.focus()
            return

        self.stop()
        try:
            session = PtySession(self._cwd, cols=self._current_cols(), rows=self._current_rows())
            fd = session.start()
        except PtyError as exc:
            self._write_to_terminal(f"\r\n\x1b[31m{exc}\x1b[0m\r\n")
            return

        self._session = session
        # Read type: fires whenever the PTY master has bytes for us. On Unix a
        # plain fd is accepted directly.
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_readable)
        self._notifier.setEnabled(True)
        self._exit_timer.start()
        self.fit()
        self.focus()

    def stop(self) -> None:
        """Ends the session and everything it started."""
        self._exit_timer.stop()
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._session is not None:
            self._session.terminate()
            self._session = None

    def restart(self) -> None:
        self.stop()
        self.clear()
        self.start()

    # -- PTY <-> xterm.js --------------------------------------------------

    def _on_readable(self) -> None:
        if self._session is None:
            return
        data = self._session.read()
        if not data:
            # Empty read on a readable fd means EOF: the child closed the slave.
            if not self._session.is_running:
                self._handle_exit()
            return
        # `replace` rather than `strict`: a chunk boundary can split a multi-byte
        # UTF-8 sequence, and dropping the whole chunk over one broken character
        # would lose real output.
        self._write_to_terminal(data.decode("utf-8", errors="replace"))

    def _on_input(self, data: str) -> None:
        if self._session is not None:
            self._session.write(data)

    def _on_size_changed(self, cols: int, rows: int) -> None:
        if self._session is not None:
            self._session.resize(cols, rows)

    def _write_to_terminal(self, text: str) -> None:
        self._run_js(f"shadowWrite({json.dumps(text)});")

    def _check_exit(self) -> None:
        if self._session is not None and not self._session.is_running:
            self._handle_exit()

    def _handle_exit(self) -> None:
        code = self._session.exit_code if self._session is not None else 0
        self.stop()
        colour = "32" if code in (0, None) else "31"
        self._write_to_terminal(
            f"\r\n\x1b[{colour}m[shell exited with code {code}] — click Restart to start a new one\x1b[0m\r\n"
        )
        self.exited.emit(code if code is not None else 0)

    # -- view helpers ------------------------------------------------------

    def notify(self, text: str) -> None:
        """Writes a message into the terminal view (not to the shell)."""
        self._write_to_terminal(text)

    def clear(self) -> None:
        self._run_js("shadowClear();")

    def focus(self) -> None:
        self._run_js("shadowFocus();")

    def fit(self) -> None:
        """Recomputes the grid size and pushes it to the PTY."""
        self._fetch_js("shadowFit();", self._apply_fit)

    def _apply_fit(self, payload: str) -> None:
        if not payload or self._session is None:
            return
        try:
            size = json.loads(payload)
            self._session.resize(int(size["cols"]), int(size["rows"]))
        except (ValueError, KeyError, TypeError):
            pass  # a fit failure is cosmetic, not worth surfacing

    def _current_cols(self) -> int:
        return self._session.cols if self._session else 80

    def _current_rows(self) -> int:
        return self._session.rows if self._session else 24

    def shutdown(self) -> None:
        """Stops the shell, then tears down the web view.

        Order matters: leaving the child running past teardown would orphan a dev
        server or test run started in the terminal.
        """
        self.stop()
        super().shutdown()


class TerminalDock(QWidget):
    """The terminal plus its small toolbar."""

    def __init__(self, xterm_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.terminal = TerminalPanel(xterm_dir=xterm_dir)

        self.start_btn = QPushButton("Start Shell")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip(
            "End the shell and everything it started — a dev server running here is "
            "stopped too, not left orphaned"
        )
        self.stop_btn.clicked.connect(self._stop)
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self._restart)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.terminal.clear)
        self.status_label = QLabel("Not running")
        self.status_label.setStyleSheet("color: #888;")

        self.terminal.exited.connect(self._on_exited)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        toolbar.addWidget(QLabel("Terminal"))
        toolbar.addWidget(self.start_btn)
        toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.restart_btn)
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(self.status_label)
        toolbar.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addLayout(toolbar)
        root.addWidget(self.terminal, 1)
        self._sync_enabled()

    def _start(self) -> None:
        self.terminal.start()
        self._sync_enabled()

    def _stop(self) -> None:
        """Ends the session, telling the user rather than just going blank."""
        if not self.terminal.is_running:
            return
        self.terminal.stop()
        self.terminal.notify("\r\n\x1b[33m[shell stopped]\x1b[0m\r\n")
        self._sync_enabled()

    def _restart(self) -> None:
        self.terminal.restart()
        self._sync_enabled()

    def set_cwd(self, cwd: Optional[str]) -> None:
        self.terminal.set_cwd(cwd)
        self._sync_enabled()

    def _on_exited(self, _code: int) -> None:
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        running = self.terminal.is_running
        available = self.terminal.is_available
        self.start_btn.setEnabled(available and not running)
        self.stop_btn.setEnabled(available and running)
        self.restart_btn.setEnabled(available)
        self.clear_btn.setEnabled(available)
        self.status_label.setText("Running" if running else "Not running")
        self.status_label.setStyleSheet(
            "color: #4a9d4a;" if running else "color: #888;"
        )

    def shutdown(self) -> None:
        self.terminal.shutdown()
