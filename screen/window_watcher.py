"""Detects the frontmost application window on macOS via AppleScript (System Events).

Best-effort heuristic, same caveats as callwatch/call_detector.py: requires
Automation permission for the calling process to control System Events under
System Settings > Privacy & Security > Automation, otherwise osascript calls
fail silently and no window changes are ever detected.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional

_FRONT_WINDOW_SCRIPT = """
tell application "System Events"
    set frontProc to first application process whose frontmost is true
    set appName to name of frontProc
    try
        set winTitle to name of front window of frontProc
    on error
        set winTitle to ""
    end try
end tell
return appName & "||" & winTitle
"""


@dataclass
class WindowInfo:
    app_name: str
    window_title: str = ""
    url: str = ""  # active tab URL, only populated when app_name is a known browser


def _run_osascript(script: str, timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _active_browser_url(app_name: str) -> str:
    if app_name == "Google Chrome":
        script = 'tell application "Google Chrome" to get URL of active tab of front window'
    elif app_name == "Safari":
        script = 'tell application "Safari" to get URL of current tab of front window'
    else:
        return ""
    return _run_osascript(script)


def get_frontmost_window() -> Optional[WindowInfo]:
    output = _run_osascript(_FRONT_WINDOW_SCRIPT)
    if not output:
        return None
    app_name, _, window_title = output.partition("||")
    app_name = app_name.strip()
    if not app_name:
        return None
    url = _active_browser_url(app_name)
    return WindowInfo(app_name=app_name, window_title=window_title.strip(), url=url.strip())


def is_window_excluded(
    window: Optional[WindowInfo],
    excluded_apps: List[str],
    excluded_domains: List[str],
) -> bool:
    """Exclusion rule used by the screen-capture/OCR pipeline (`gui/workers.py`'s
    `ScreenOcrWorker`). Not used by spell check, which has no exclusions — see
    README's "Spell check (system-wide)" section.

    Always excludes this app itself and anything named after it — the
    frontmost app name OR window title starting with "shadow" (case
    insensitive) — this app's own window, and any Finder/editor/terminal
    window showing a folder or file whose name starts with "Shadow" (e.g.
    this project folder, or one of its own `Shadow_*` output files). This
    check is hardcoded and NOT affected by `excluded_apps`/`config/settings.local.yaml`
    — removing "Shadow" from your local `excluded_apps` override does not
    re-enable capturing this app's own window.

    Beyond that, matches (case-insensitively) the frontmost process name/
    window title against the configurable `excluded_apps`, and the active
    browser tab URL against `excluded_domains`.
    """
    if window is None:
        return False
    haystacks = [window.app_name.lower(), window.window_title.lower()]
    if any(text.startswith("shadow") for text in haystacks if text):
        return True
    if any(pattern.lower() in text for pattern in excluded_apps for text in haystacks):
        return True
    if window.url:
        url = window.url.lower()
        if any(domain.lower() in url for domain in excluded_domains):
            return True
    return False
