"""Detects an active call/meeting on macOS: Slack huddle, Google Meet, Zoom,
Teams, Webex, GoToMeeting, Whereby, Around, FaceTime, and Skype.

This is a best-effort heuristic, not a real integration with any of these
products:
- Browser-based meetings, tier 1 (reliable): Chrome, Microsoft Edge, Brave,
  and Safari all expose a "tabs of window" / "URL of tab" AppleScript
  dictionary, so every open tab's URL is read directly and matched against
  known meeting-room URL patterns.
- Browser-based meetings, tier 2 (fallback): Firefox and Arc don't reliably
  expose tab URLs to AppleScript, so instead their *window title* (which
  mirrors the active tab's page title) is matched against the same
  meeting-provider keywords used for native apps below. Less precise —
  a marketing page titled "Zoom Meetings — Video Conferencing" would also
  match — but better than no coverage.
- Native apps (Zoom, Teams, Webex, Skype, FaceTime): asks System Events (via
  AppleScript) for that app's window titles and matches them against a
  known "in-call" title pattern per app.
- Slack huddle: same System Events approach — Slack labels an active huddle
  window/bar with "Huddle" in its title.

Known gaps that this module cannot close with window-title/URL matching:
- Discord: its main window is titled "Discord" regardless of call state, so
  there's no title signal to key off of.
- Plain cellular/carrier phone calls have no scriptable window at all —
  except on macOS Monterey+, where Continuity phone calls are answered
  inside FaceTime.app and so happen to be caught by the FaceTime rule below.

Beyond that, a renamed window, an app version with different title
conventions, or a meeting joined in an unlisted browser can still cause a
live call to go undetected. It errs toward under-detecting rather than
false-positiving on unrelated windows.

Requires the calling process to have Accessibility + Automation ("control
Google Chrome/Safari/<other browsers>/System Events") permissions under
System Settings > Privacy & Security, otherwise osascript calls fail
silently and no call is ever detected.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# (source, URL pattern) — matched against every open browser tab URL.
_BROWSER_MEETING_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("google_meet", re.compile(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", re.IGNORECASE)),
    ("zoom", re.compile(r"https://[\w.-]*zoom\.us/(j|wc/join)/\d+", re.IGNORECASE)),
    ("teams", re.compile(r"https://teams\.(microsoft|live)\.com/(l/meetup-join|.*meet)", re.IGNORECASE)),
    ("webex", re.compile(r"https://[\w.-]*webex\.com/(meet|join|webappng)/", re.IGNORECASE)),
    ("gotomeeting", re.compile(r"https://[\w.-]*gotomeeting\.com/join/", re.IGNORECASE)),
    ("whereby", re.compile(r"https://[\w.-]*whereby\.com/[\w-]+", re.IGNORECASE)),
    ("around", re.compile(r"https://[\w.-]*around\.co/", re.IGNORECASE)),
]

# (System Events process name, source, title predicate) — matched against
# that app's window titles. Slack's huddle bar and a live FaceTime call are
# both just "another window" on the process, same as a Zoom/Teams/Webex
# meeting window.
_NATIVE_APP_RULES: List[Tuple[str, str, Callable[[str], bool]]] = []


def _title_contains(*needles: str) -> Callable[[str], bool]:
    def _match(title: str) -> bool:
        lowered = title.lower()
        return any(needle.lower() in lowered for needle in needles)

    return _match


def _facetime_call_window(title: str) -> bool:
    # FaceTime's idle window (no call) is titled exactly "FaceTime"; any
    # other non-empty title is a live call window (named after the callee).
    # This incidentally also catches Continuity phone calls, which route
    # through FaceTime.app on macOS Monterey+.
    stripped = title.strip()
    return bool(stripped) and stripped.lower() != "facetime"


def _skype_call_window(title: str) -> bool:
    stripped = title.strip()
    if not stripped:
        return False
    if "call" in stripped.lower():
        return True
    # Skype's idle windows are just the app/product name; anything else
    # (a contact name, a call duration) implies an active call.
    return stripped.lower() not in {"skype", "skype for desktop"}


_NATIVE_APP_RULES.extend(
    [
        ("zoom.us", "zoom", _title_contains("Zoom Meeting", "Zoom Webinar")),
        ("Microsoft Teams", "teams", _title_contains("Meeting")),
        ("MSTeams", "teams", _title_contains("Meeting")),
        ("Cisco Webex Meetings", "webex", _title_contains("Webex Meeting")),
        ("Slack", "slack", _title_contains("Huddle")),
        ("FaceTime", "facetime", _facetime_call_window),
        ("Skype", "skype", _skype_call_window),
        ("Skype for Desktop", "skype", _skype_call_window),
        # Firefox/Arc don't reliably expose tab URLs to AppleScript (see
        # module docstring), so fall back to matching their window title —
        # which mirrors the active tab's page title — against the same
        # provider keywords used for browser tab URLs below.
        ("firefox", "google_meet", _title_contains("Google Meet")),
        ("firefox", "zoom", _title_contains("Zoom Meeting")),
        ("firefox", "teams", _title_contains("Microsoft Teams")),
        ("firefox", "webex", _title_contains("Webex Meeting")),
        ("Arc", "google_meet", _title_contains("Google Meet")),
        ("Arc", "zoom", _title_contains("Zoom Meeting")),
        ("Arc", "teams", _title_contains("Microsoft Teams")),
        ("Arc", "webex", _title_contains("Webex Meeting")),
    ]
)

# Browsers whose AppleScript dictionary reliably exposes "tabs of window" /
# "URL of tab" (all Chromium-based, plus Safari).
_BROWSER_APPS = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Safari"]

# Existence is checked via System Events' running-process list ("exists
# process"), never via `application appName is running` — the latter makes
# AppleScript resolve appName through Launch Services, and for an app that
# isn't installed that can pop a "select an application" locate dialog
# instead of failing quietly. Any browser not installed/not running is just
# skipped, silently, like every other not-found app in this module.
#
# IMPORTANT: this MUST use a literal app name in "tell application", never a
# loop variable (e.g. `repeat with appName in {...}` then `tell application
# appName`). AppleScript resolves which app's terminology (like "tabs of
# window") applies to a `tell application` block at compile time from a
# literal string; with a variable it can't determine the target app's
# dictionary and silently falls back to a generic one that has no "tabs"
# property, so `tabs of w` throws -1700 every time. That's why this used to
# be one script loop over all browsers — and why no browser-based meeting
# was ever actually detected.
#
# Each browser also gets its OWN separate osascript call (rather than one
# combined script for all of them) so that one browser's pending "<App>
# would like to control this computer" Automation permission dialog — which
# blocks the whole script until answered or timed out — can't also starve
# out the others. A single combined script means e.g. an unanswered Safari
# permission prompt silently zeroes out Chrome's results too, since the
# whole script hangs until _run_osascript's timeout and then returns "".
def _browser_tab_urls_script(app: str) -> str:
    return f"""
set urls to {{}}
tell application "System Events"
    set appRunning to exists process "{app}"
end tell
if appRunning then
    try
        tell application "{app}"
            repeat with w in windows
                repeat with t in tabs of w
                    set end of urls to URL of t
                end repeat
            end repeat
        end tell
    end try
end if
set AppleScript's text item delimiters to linefeed
return urls as text
"""


_BROWSER_TAB_URL_SCRIPTS = {app: _browser_tab_urls_script(app) for app in _BROWSER_APPS}

# Every native-app process worth polling, gathered in one osascript call
# (rather than one call per app) to keep per-poll overhead low.
_NATIVE_APP_PROCESSES = sorted({process for process, _source, _match in _NATIVE_APP_RULES})

_RULES_BY_PROCESS: dict = {}
for _process, _source, _match in _NATIVE_APP_RULES:
    _RULES_BY_PROCESS.setdefault(_process, []).append((_source, _match))

_ALL_APP_WINDOW_TITLES_SCRIPT = """
set output to {{}}
tell application "System Events"
    repeat with procName in {process_list}
        if exists process procName then
            tell process procName
                repeat with w in windows
                    set end of output to (procName & "::" & (name of w))
                end repeat
            end tell
        end if
    end repeat
end tell
set AppleScript's text item delimiters to linefeed
return output as text
""".format(process_list="{" + ", ".join(f'"{p}"' for p in _NATIVE_APP_PROCESSES) + "}")


@dataclass
class CallState:
    active: bool
    source: str = ""  # "slack" | "google_meet" | "zoom" | "teams" | "webex" | "gotomeeting" | "whereby" | "around" | "facetime" | "skype"
    label: str = ""  # meeting URL / window title, for logging


def _run_osascript(script: str, timeout: float = 5.0) -> str:
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


def _active_browser_meeting() -> Optional[CallState]:
    for app in _BROWSER_APPS:
        output = _run_osascript(_BROWSER_TAB_URL_SCRIPTS[app], timeout=3.0)
        for url in output.splitlines():
            url = url.strip()
            if not url:
                continue
            for source, pattern in _BROWSER_MEETING_PATTERNS:
                if pattern.search(url):
                    return CallState(active=True, source=source, label=url)
    return None


def _active_native_app_call() -> Optional[CallState]:
    output = _run_osascript(_ALL_APP_WINDOW_TITLES_SCRIPT, timeout=6.0)
    for line in output.splitlines():
        process, sep, title = line.partition("::")
        if not sep:
            continue
        for source, matches in _RULES_BY_PROCESS.get(process, []):
            if matches(title):
                return CallState(active=True, source=source, label=title)
    return None


class CallDetector:
    """Polls for an active call/meeting across browser tabs and native apps (macOS only)."""

    def check(self) -> CallState:
        state = _active_browser_meeting()
        if state is not None:
            return state

        state = _active_native_app_call()
        if state is not None:
            return state

        return CallState(active=False)
