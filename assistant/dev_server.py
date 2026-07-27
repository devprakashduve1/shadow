"""Detects a Coding Agent project's dev-server start command, launches it, and
opens the result in Chrome — the "verify in Chrome" step after `apply_plan()`.

No browser automation (no clicking around, no screenshots) — this only gets
the page open so the user can look themselves, per the user's explicit
choice when this feature was scoped.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

# Preference order when a package.json defines more than one of these.
_SCRIPT_PREFERENCE = ("dev", "start", "serve")

_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1):\d+[^\s\"'<>]*")


def _package_manager(project_path: Path) -> str:
    if (project_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_path / "yarn.lock").exists():
        return "yarn"
    return "npm"


def detect_start_command(project_path: Union[str, Path]) -> Optional[List[str]]:
    """Returns a runnable start command for `project_path`, or None if unrecognized.

    v1 only understands Node/npm-family projects (a `package.json` with a
    `dev`/`start`/`serve` script) — anything else is reported honestly as "no
    known start command" by the caller rather than guessed at.
    """
    project_path = Path(project_path)
    package_json = project_path / "package.json"
    if not package_json.is_file():
        return None

    try:
        data = json.loads(package_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    scripts = data.get("scripts") or {}
    for script_name in _SCRIPT_PREFERENCE:
        if script_name in scripts:
            manager = _package_manager(project_path)
            return ["npm", "run", script_name] if manager == "npm" else [manager, script_name]
    return None


@dataclass
class LaunchResult:
    url: Optional[str]
    log_path: Path
    process: subprocess.Popen


def _wait_for_url(log_path: Path, *, timeout: float, process: subprocess.Popen) -> Optional[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break  # exited before ever printing a URL
        match = _URL_RE.search(log_path.read_text(errors="ignore"))
        if match:
            return match.group(0)
        time.sleep(0.5)
    return None


def _open_in_chrome(url: str) -> None:
    """Best-effort: cross-platform `webbrowser` "chrome" registration first,
    then macOS's `open -a "Google Chrome"` (this app is macOS-first — see
    screen/window_watcher.py, callwatch/call_detector.py), then whatever the
    system default browser is."""
    try:
        webbrowser.get("chrome").open(url)
        return
    except webbrowser.Error:
        pass
    try:
        subprocess.run(["open", "-a", "Google Chrome", url], check=True, timeout=5)
        return
    except (OSError, subprocess.SubprocessError):
        pass
    webbrowser.open(url)


def launch_and_open_chrome(
    project_path: Union[str, Path],
    command: List[str],
    *,
    timeout: float = 20.0,
    log_dir: Union[str, Path] = "output/dev_logs",
) -> LaunchResult:
    """Starts `command` in `project_path`, waits up to `timeout`s for it to
    print a localhost URL to its own log, then opens that URL in Chrome.

    The process is intentionally left running on return — the caller (the
    GUI) owns stopping it via `LaunchResult.process.terminate()`.
    """
    project_path = Path(project_path)
    log_dir = Path(log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{project_path.name}-{int(time.time())}.log"

    log_file = open(log_path, "w")
    process = subprocess.Popen(
        command, cwd=str(project_path), stdout=log_file, stderr=subprocess.STDOUT, text=True
    )

    url = _wait_for_url(log_path, timeout=timeout, process=process)
    if url:
        _open_in_chrome(url)

    return LaunchResult(url=url, log_path=log_path, process=process)
