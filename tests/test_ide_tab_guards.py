"""Tests for IDETab's request guards.

These used to `return` silently, which produced a dead Send button: the panel
tracked its own busy flag and kept Send enabled while the tab refused every
click, with nothing on screen to explain it.

`IDETab` itself can't be constructed in a test (it builds a QWebEngineView), so
the guards are called unbound against a stub — they only touch `_ai_busy()`,
`_project_path` and `ai_panel`.
"""
from __future__ import annotations

from gui.ide.tab import IDETab


class _FakePanel:
    def __init__(self):
        self.busy = None
        self.status = ""

    def set_busy(self, value: bool) -> None:
        self.busy = value

    def set_status(self, text: str) -> None:
        self.status = text


class _FakeTab:
    """The slice of IDETab the guards actually read."""

    def __init__(self, busy: bool = False, project=None):
        self._busy = busy
        self._project_path = project
        self.ai_panel = _FakePanel()

    def _ai_busy(self) -> bool:
        return self._busy


# -- busy guard --------------------------------------------------------------


def test_an_idle_tab_does_not_refuse() -> None:
    tab = _FakeTab(busy=False)

    assert IDETab._reject_while_busy(tab, "send it again") is False
    assert tab.ai_panel.status == "", "nothing to report when it proceeds"


def test_a_busy_tab_refuses_and_explains() -> None:
    tab = _FakeTab(busy=True)

    assert IDETab._reject_while_busy(tab, "send it again") is True
    assert "Stop" in tab.ai_panel.status
    assert "send it again" in tab.ai_panel.status


def test_refusing_resyncs_the_panel_busy_flag() -> None:
    """The panel's flag is what enables Send. Left stale, Send stays clickable
    and every click is silently dropped — the reported bug."""
    tab = _FakeTab(busy=True)

    IDETab._reject_while_busy(tab, "send it again")

    assert tab.ai_panel.busy is True


def test_an_idle_tab_does_not_touch_the_busy_flag() -> None:
    tab = _FakeTab(busy=False)

    IDETab._reject_while_busy(tab, "send it again")

    assert tab.ai_panel.busy is None


# -- project guard -----------------------------------------------------------


def test_no_project_refuses_and_explains() -> None:
    tab = _FakeTab(project=None)

    assert IDETab._no_project_for(tab, "planning a change") is True
    assert "Open a repository" in tab.ai_panel.status
    assert "planning a change" in tab.ai_panel.status


def test_an_open_project_does_not_refuse() -> None:
    tab = _FakeTab(project="/tmp/some-repo")

    assert IDETab._no_project_for(tab, "planning a change") is False
    assert tab.ai_panel.status == ""
