"""Tests for assistant/pty_session.py.

Real shells on real PTYs — the whole reason this module exists is that a pipe
behaves differently from a terminal, so mocking it would test nothing.

Uses `/bin/sh` rather than the user's login shell: no profile to load (so it
starts fast and deterministically) and no prompt customisation to confuse output
matching.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from assistant.pty_session import DEFAULT_COLS, DEFAULT_ROWS, PtyError, PtySession, default_shell

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith(("darwin", "linux")),
    reason="PTYs are Unix-only",
)

SH = ["/bin/sh"]


def _drain(session: PtySession, seconds: float = 2.0, quiet_after: float = 0.3) -> str:
    """Reads until output stops for `quiet_after`, or `seconds` elapses."""
    collected = b""
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = session.read()
        if chunk:
            collected += chunk
            deadline = min(deadline, time.time() + quiet_after)
        else:
            time.sleep(0.02)
    return collected.decode("utf-8", errors="replace")


def _run(session: PtySession, command: str, seconds: float = 2.0) -> str:
    session.write(command + "\n")
    return _drain(session, seconds)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "marker.txt").write_text("content\n")
    (tmp_path / "subdir").mkdir()
    return tmp_path


# -- the central claim: it's a real terminal ---------------------------------


def test_child_sees_a_tty(workdir: Path) -> None:
    """The entire point of a PTY. On a pipe this would print False, and every
    tool that checks isatty() would behave differently."""
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "python3 -c 'import sys; print(\"TTY\", sys.stdout.isatty())'")

    assert "TTY True" in output


def test_term_is_set_so_curses_apps_work(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "printf 'T=%s\\n' \"$TERM\"")

    assert "T=xterm-256color" in output


def test_size_is_reported_to_the_child(workdir: Path) -> None:
    with PtySession(workdir, command=SH, cols=120, rows=40) as session:
        output = _run(session, "stty size")

    assert "40 120" in output


def test_resize_is_visible_to_the_child(workdir: Path) -> None:
    """Without TIOCSWINSZ, vim and less keep drawing at the old size."""
    with PtySession(workdir, command=SH, cols=80, rows=24) as session:
        _run(session, "stty size")
        session.resize(100, 30)
        output = _run(session, "stty size")

    assert "30 100" in output
    assert session.cols == 100 and session.rows == 30


def test_resize_before_start_is_remembered(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    session.resize(90, 28)
    try:
        session.start()
        assert "28 90" in _run(session, "stty size")
    finally:
        session.terminate()


# -- basics ------------------------------------------------------------------


def test_starts_in_the_requested_directory(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "pwd")

    # macOS reports /private/var for /var, so compare the resolved tail.
    assert workdir.name in output


def test_commands_produce_output(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "echo HELLO_FROM_SHELL")

    assert "HELLO_FROM_SHELL" in output


def test_sees_files_in_the_working_directory(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "ls")

    assert "marker.txt" in output


def test_env_marker_is_set(workdir: Path) -> None:
    """Lets a shell profile detect it's running inside Shadow."""
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "printf 'M=%s\\n' \"$SHADOW_TERMINAL\"")

    assert "M=1" in output


def test_extra_env_is_applied(workdir: Path) -> None:
    with PtySession(workdir, command=SH, env={"MY_VAR": "custom"}) as session:
        output = _run(session, "printf 'V=%s\\n' \"$MY_VAR\"")

    assert "V=custom" in output


def test_pager_is_neutralised(workdir: Path) -> None:
    """A pager we don't control would look like the terminal hanging."""
    with PtySession(workdir, command=SH) as session:
        output = _run(session, "printf 'P=%s\\n' \"$GIT_PAGER\"")

    assert "P=cat" in output


def test_defaults_are_sane() -> None:
    assert DEFAULT_COLS == 80 and DEFAULT_ROWS == 24


def test_default_shell_is_a_login_shell() -> None:
    """`-l` so the profile runs; without it PATH misses Homebrew, nvm, pyenv."""
    command = default_shell()
    assert command[-1] == "-l"
    assert Path(command[0]).name in ("zsh", "bash", "sh", "fish")


# -- lifecycle ---------------------------------------------------------------


def test_is_running_reflects_state(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    assert session.is_running is False

    session.start()
    assert session.is_running is True

    session.terminate()
    assert session.is_running is False


def test_exit_code_is_captured(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    session.start()
    try:
        session.write("exit 7\n")
        for _ in range(50):
            session.read()
            if not session.is_running:
                break
            time.sleep(0.05)
        assert session.exit_code == 7
    finally:
        session.terminate()


def test_read_returns_empty_after_the_child_exits(workdir: Path) -> None:
    """EIO on a PTY master means "the child closed the slave" — an ordinary exit,
    not an error to propagate."""
    session = PtySession(workdir, command=SH)
    session.start()
    try:
        session.write("exit 0\n")
        time.sleep(0.6)
        for _ in range(20):
            session.read()
            time.sleep(0.03)
        assert session.read() == b""
    finally:
        session.terminate()


def test_read_does_not_block_when_idle(workdir: Path) -> None:
    """The fd is non-blocking, so a caller without a notifier can poll safely."""
    with PtySession(workdir, command=SH) as session:
        _drain(session, 1.0)
        started = time.time()
        session.read()
        assert time.time() - started < 0.5, "read() blocked on an idle terminal"


def test_starting_twice_raises(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        with pytest.raises(PtyError, match="already running"):
            session.start()


def test_missing_directory_raises(tmp_path: Path) -> None:
    session = PtySession(tmp_path / "does-not-exist", command=SH)
    with pytest.raises(PtyError, match="not a directory"):
        session.start()


def test_missing_command_raises(workdir: Path) -> None:
    session = PtySession(workdir, command=["/nonexistent/shell"])
    with pytest.raises(PtyError):
        session.start()


def test_write_after_terminate_is_ignored(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    session.start()
    session.terminate()

    session.write("echo nothing\n")  # must not raise


def test_terminate_is_idempotent(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    session.start()
    session.terminate()
    session.terminate()  # must not raise


def test_fd_is_closed_after_terminate(workdir: Path) -> None:
    session = PtySession(workdir, command=SH)
    fd = session.start()
    session.terminate()

    assert session.fd is None
    with pytest.raises(OSError):
        os.fstat(fd)  # the fd really is closed, not just forgotten


# -- process group handling --------------------------------------------------


def test_terminate_kills_background_children(workdir: Path) -> None:
    """The reason for start_new_session + killpg.

    A shell that launched a dev server would otherwise leave it running and
    holding its port after Shadow closed.
    """
    session = PtySession(workdir, command=SH)
    session.start()
    output = _run(session, "sleep 300 & echo PID=$!", seconds=2.0)

    child_pid = None
    for line in output.splitlines():
        if "PID=" in line and "echo" not in line:
            try:
                child_pid = int(line.split("PID=")[1].strip())
            except (ValueError, IndexError):
                pass
    assert child_pid, f"could not read the background pid from: {output!r}"

    session.terminate()
    time.sleep(0.5)

    with pytest.raises(OSError):
        os.kill(child_pid, 0)  # gone


def test_child_is_in_its_own_process_group(workdir: Path) -> None:
    """Otherwise Ctrl-C would signal Shadow's group and kill the whole app."""
    with PtySession(workdir, command=SH) as session:
        _drain(session, 1.0)
        child_pgid = os.getpgid(session._process.pid)

    assert child_pgid != os.getpgid(os.getpid())


def test_interrupt_stops_a_running_command(workdir: Path) -> None:
    """What Ctrl-C does — the command dies, the shell survives."""
    session = PtySession(workdir, command=SH)
    session.start()
    try:
        _drain(session, 1.0)
        session.write("sleep 60\n")
        time.sleep(0.5)

        session.interrupt()
        time.sleep(0.5)

        assert session.is_running is True, "the shell itself should survive"
        assert "INTERRUPT_WORKED" in _run(session, "echo INTERRUPT_WORKED")
    finally:
        session.terminate()


def test_context_manager_cleans_up(workdir: Path) -> None:
    with PtySession(workdir, command=SH) as session:
        assert session.is_running is True
        captured = session

    assert captured.is_running is False
    assert captured.fd is None
