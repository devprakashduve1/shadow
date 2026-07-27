"""A real pseudo-terminal session: a shell on a PTY, readable and writable.

Why a PTY rather than `subprocess.PIPE`: a pipe is not a terminal. Programs call
`isatty()` and change behaviour — `git`, `npm`, and `pytest` disable colour and
progress output, `less` and `vim` refuse to run properly, and anything prompting
for input (a password, `git rebase -i`) hangs waiting on a terminal that isn't
there. Allocating a PTY makes the child believe it has a real terminal, because
it does.

Deliberately Qt-free so it can be unit-tested directly (see
tests/test_pty_session.py); `gui/ide/terminal.py` wraps it with a
`QSocketNotifier` and an xterm.js view.
"""
from __future__ import annotations

import errno
import fcntl
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
from pathlib import Path
from typing import Dict, List, Optional, Union

# Read size per wakeup. Big enough that a fast-scrolling build doesn't need
# thousands of syscalls, small enough to stay responsive.
READ_CHUNK = 65536

DEFAULT_COLS = 80
DEFAULT_ROWS = 24


class PtyError(RuntimeError):
    """Raised when a PTY session can't be started."""


def default_shell() -> List[str]:
    """Returns the user's login shell as a command, falling back sensibly.

    `-l` so the shell reads the user's profile — otherwise PATH is missing
    everything installed via Homebrew, nvm, pyenv, and friends, and the terminal
    is useless for the tools people actually want to run.
    """
    shell = os.environ.get("SHELL") or shutil.which("zsh") or shutil.which("bash") or "/bin/sh"
    return [shell, "-l"]


class PtySession:
    """One shell process attached to a pseudo-terminal."""

    def __init__(
        self,
        cwd: Union[str, Path],
        command: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
    ):
        self.cwd = str(cwd)
        self.command = command or default_shell()
        self.cols = cols
        self.rows = rows
        self._master_fd: Optional[int] = None
        self._process: Optional[subprocess.Popen] = None
        self._env = self._build_env(env)

    def _build_env(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        env = dict(os.environ)
        # Tell programs what they're talking to. Without TERM, curses apps bail
        # out ("terminal is not fully functional") and colour is disabled.
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        # Stops tools from paging into a pager we don't control, which would look
        # like the terminal hanging.
        env.setdefault("PAGER", "cat")
        env.setdefault("GIT_PAGER", "cat")
        env["SHADOW_TERMINAL"] = "1"
        if extra:
            env.update(extra)
        return env

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> int:
        """Starts the shell and returns the master fd to read from."""
        if self._process is not None:
            raise PtyError("This session is already running.")
        if not Path(self.cwd).is_dir():
            raise PtyError(f"{self.cwd} is not a directory.")

        master_fd, slave_fd = pty.openpty()
        try:
            self._set_size(master_fd, self.cols, self.rows)
            self._process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self._env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                # A new session makes the child a process-group leader with the
                # PTY as its controlling terminal. Without it, Ctrl-C would be
                # delivered to Shadow's own process group — killing the app
                # instead of the command running in the terminal.
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            os.close(master_fd)
            os.close(slave_fd)
            self._process = None
            raise PtyError(f"Could not start {self.command[0]}: {exc}") from exc
        finally:
            # The child holds its own copy; keeping ours open would mean reads
            # never see EOF after the child exits.
            try:
                os.close(slave_fd)
            except OSError:
                pass

        # Non-blocking, so `read()` can honestly return b"" when nothing is
        # buffered. On a blocking fd it would sit in os.read until the child says
        # something — fine under a QSocketNotifier (which only fires when data is
        # ready) but a hang for any other caller, including tests.
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._master_fd = master_fd
        return master_fd

    @property
    def fd(self) -> Optional[int]:
        return self._master_fd

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def exit_code(self) -> Optional[int]:
        return None if self._process is None else self._process.poll()

    # -- I/O ---------------------------------------------------------------

    def read(self, size: int = READ_CHUNK) -> bytes:
        """Reads available output. Returns b"" at EOF or when nothing is ready.

        Never raises on the normal shutdown races: EIO is how a PTY master
        reports "the child closed the slave", which is an ordinary exit rather
        than an error, and EAGAIN just means nothing is buffered yet.
        """
        if self._master_fd is None:
            return b""
        try:
            return os.read(self._master_fd, size)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                return b""  # child exited and closed its end
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return b""
            raise

    def write(self, data: Union[str, bytes]) -> None:
        """Sends input to the shell."""
        if self._master_fd is None:
            return
        payload = data.encode("utf-8") if isinstance(data, str) else data
        try:
            os.write(self._master_fd, payload)
        except OSError as exc:
            if exc.errno not in (errno.EIO, errno.EBADF, errno.EPIPE):
                raise
            # Child is gone; dropping the input is the correct outcome.

    def resize(self, cols: int, rows: int) -> None:
        """Tells the PTY its new size.

        Required for full-screen programs: vim and less read the size from the
        terminal, so without this they keep drawing at the old dimensions after
        the panel is resized. Also sends SIGWINCH so the child notices.
        """
        cols = max(1, int(cols))
        rows = max(1, int(rows))
        self.cols, self.rows = cols, rows
        if self._master_fd is None:
            return
        self._set_size(self._master_fd, cols, rows)
        if self._process is not None and self.is_running:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGWINCH)
            except (OSError, ProcessLookupError):
                pass

    @staticmethod
    def _set_size(fd: int, cols: int, rows: int) -> None:
        # struct winsize is {rows, cols, xpixel, ypixel} — rows first, which is
        # the opposite of how everything else here orders them.
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
        except OSError:
            pass

    def interrupt(self) -> None:
        """Sends SIGINT to the foreground process group (what Ctrl-C does)."""
        if self._process is None or not self.is_running:
            return
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGINT)
        except (OSError, ProcessLookupError):
            pass

    # -- teardown ----------------------------------------------------------

    def terminate(self, timeout: float = 2.0) -> None:
        """Stops the shell and everything it started, then closes the PTY.

        Signals the whole process *group*, not just the shell: a shell that
        launched a dev server would otherwise leave it orphaned and still holding
        its port after the app closed.
        """
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            pgid = None
            try:
                pgid = os.getpgid(process.pid)
            except (OSError, ProcessLookupError):
                pass
            self._signal_group(pgid, process, signal.SIGHUP)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._signal_group(pgid, process, signal.SIGKILL)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass  # nothing further we can do without blocking forever

        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    @staticmethod
    def _signal_group(pgid: Optional[int], process: subprocess.Popen, sig: int) -> None:
        if pgid is not None:
            try:
                os.killpg(pgid, sig)
                return
            except (OSError, ProcessLookupError):
                pass
        try:
            process.send_signal(sig)
        except (OSError, ProcessLookupError, ValueError):
            pass

    def __enter__(self) -> "PtySession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.terminate()
