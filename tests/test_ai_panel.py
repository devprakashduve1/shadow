"""Qt-level tests for gui/ide/ai_panel.py.

Covers the state machine around a proposal — which controls are live when, and
that a pending review blocks new actions — without involving Monaco or a model.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from assistant.edits.actions import EditAction
from assistant.edits.diffs import DiffStats
from gui.ide.ai_panel import AIPanel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp, tmp_path):
    # A monaco_dir with no assets keeps MonacoDiffView as a cheap notice widget,
    # so these tests don't start Chromium.
    return AIPanel(monaco_dir=tmp_path / "no-monaco")


class _FakeProposal:
    def __init__(self, warnings=None, rel_path="app.py"):
        self.rel_path = rel_path
        self.original = "old\n"
        self.proposed = "new\n"
        self.action = EditAction.REFACTOR
        self.strategy = "whole_file"
        self.stats = DiffStats(added=1, removed=1)
        self.warnings = warnings or []
        self.is_noop = False


# -- context -----------------------------------------------------------------


def test_actions_disabled_with_no_file_open(panel) -> None:
    assert panel.send_btn.isEnabled() is False
    for button in panel._action_buttons.values():
        assert button.isEnabled() is False


def test_actions_enable_once_a_file_is_active(panel) -> None:
    """Opening a file unlocks the action buttons.

    Send is deliberately not included: it tracks whether anything is *typed*,
    not whether a file is open, since with no file it asks a general question.
    """
    panel.set_active_file("app.py")

    assert panel._action_buttons[EditAction.REFACTOR].isEnabled() is True
    assert panel.send_btn.isEnabled() is False, "nothing typed yet"


def test_context_label_reports_whole_file_by_default(panel) -> None:
    panel.set_active_file("src/app.py")
    assert "whole file" in panel.context_label.text()


def test_context_label_reports_selected_line_count(panel) -> None:
    panel.set_active_file("app.py")
    panel.set_selection("line one\nline two\nline three")

    assert "3 selected line(s)" in panel.context_label.text()


def test_switching_files_clears_the_selection(panel) -> None:
    """A selection belongs to the file it was made in."""
    panel.set_active_file("a.py")
    panel.set_selection("some code")

    panel.set_active_file("b.py")

    assert panel._selection == ""
    assert "whole file" in panel.context_label.text()


# -- requests ----------------------------------------------------------------


def test_action_button_emits_the_action(panel) -> None:
    panel.set_active_file("app.py")
    seen = []
    panel.action_requested.connect(lambda action, instruction: seen.append((action, instruction)))

    panel._action_buttons[EditAction.FIX].click()

    assert seen == [(EditAction.FIX, "")]


def test_action_button_forwards_the_typed_instruction(panel) -> None:
    panel.set_active_file("app.py")
    panel.prompt_input.setPlainText("only the retry logic")
    seen = []
    panel.action_requested.connect(lambda action, instruction: seen.append((action, instruction)))

    panel._action_buttons[EditAction.REFACTOR].click()

    assert seen == [(EditAction.REFACTOR, "only the retry logic")]


def test_send_does_nothing_without_an_instruction(panel) -> None:
    """The button is disabled rather than clickable-then-scolding, so a click
    can't emit an empty request at all."""
    panel.set_active_file("app.py")
    seen = []
    panel.action_requested.connect(lambda *a: seen.append(a))

    assert panel.send_btn.isEnabled() is False
    panel.send_btn.click()

    assert seen == []


def test_calling_send_directly_with_no_text_explains_itself(panel) -> None:
    """Belt and braces: the handler still guards, e.g. if Enter is pressed."""
    panel.set_active_file("app.py")

    panel._request_implement()

    assert "Type something first" in panel.status_label.text()


def test_send_with_project_context_emits_prompt_submitted(panel) -> None:
    """Send no longer needs a mode choice; the tab infers intent from the prompt."""
    panel.set_active_file("app.py")
    panel.prompt_input.setPlainText("add a --dry-run flag")
    seen = []
    panel.prompt_submitted.connect(seen.append)

    panel.send_btn.click()

    assert seen == ["add a --dry-run flag"]


def test_build_request_carries_the_panel_context(panel) -> None:
    panel.set_active_file("src/app.py")
    panel.set_selection("def f(): pass")

    request = panel.build_request("/tmp/proj", EditAction.OPTIMISE, "speed it up")

    assert request.rel_path == "src/app.py"
    assert request.selection == "def f(): pass"
    assert request.instruction == "speed it up"
    assert request.has_selection is True


# -- busy state --------------------------------------------------------------


def test_busy_disables_actions_and_enables_stop(panel) -> None:
    panel.set_active_file("app.py")

    panel.set_busy(True)

    assert panel._action_buttons[EditAction.FIX].isEnabled() is False
    assert panel.send_btn.isEnabled() is False
    assert panel.stop_btn.isEnabled() is True
    assert panel.model_combo.isEnabled() is False


def test_clearing_busy_restores_actions(panel) -> None:
    panel.set_active_file("app.py")
    panel.set_busy(True)
    panel.set_busy(False)

    assert panel._action_buttons[EditAction.FIX].isEnabled() is True
    assert panel.stop_btn.isEnabled() is False


# -- review mode -------------------------------------------------------------


def test_show_proposal_switches_to_review(panel) -> None:
    panel.set_active_file("app.py")

    panel.show_proposal(_FakeProposal())

    assert panel.stack.currentIndex() == 1
    assert panel.accept_btn.isEnabled() is True
    assert panel.reject_btn.isEnabled() is True


def test_pending_review_blocks_new_actions(panel) -> None:
    """A proposal must be decided before another can be generated, or the first
    would be silently discarded."""
    panel.set_active_file("app.py")

    panel.show_proposal(_FakeProposal())

    assert panel._action_buttons[EditAction.FIX].isEnabled() is False
    assert panel.send_btn.isEnabled() is False


def test_diff_header_shows_stats_and_action(panel) -> None:
    panel.show_proposal(_FakeProposal())

    header = panel.diff_header.text()

    assert "app.py" in header
    assert "+1 -1" in header
    assert "Refactor" in header


def test_diff_header_surfaces_warnings(panel) -> None:
    """Fallback/retry warnings matter — the user should know the model struggled."""
    panel.show_proposal(_FakeProposal(warnings=["Retry also failed; fell back."]))

    assert "⚠" in panel.diff_header.text()
    assert "fell back" in panel.diff_header.text()


def test_reject_returns_to_chat_and_reenables_actions(panel) -> None:
    panel.set_active_file("app.py")
    panel.show_proposal(_FakeProposal())
    rejected = []
    panel.reject_requested.connect(lambda: rejected.append(True))

    panel.reject_btn.click()

    assert rejected == [True]
    assert panel.stack.currentIndex() == 0
    assert panel._action_buttons[EditAction.FIX].isEnabled() is True


def test_return_to_chat_clears_the_pending_flag(panel) -> None:
    panel.set_active_file("app.py")
    panel.show_proposal(_FakeProposal())

    panel.return_to_chat()

    assert panel._has_proposal is False
    assert panel.accept_btn.isEnabled() is False


def test_accept_disables_the_button_to_prevent_double_apply(panel) -> None:
    panel.set_active_file("app.py")
    panel.show_proposal(_FakeProposal())

    panel.accept_btn.click()

    assert panel.accept_btn.isEnabled() is False


# -- transcript --------------------------------------------------------------


def test_transcript_accumulates_streamed_chunks(panel) -> None:
    panel.append_user("explain this")
    panel.append_assistant_prefix()
    panel.append_chunk("It ")
    panel.append_chunk("works.")

    text = panel.transcript.toPlainText()
    assert "You: explain this" in text
    assert "Shadow: It works." in text


def test_model_selection_is_readable(panel) -> None:
    assert panel.model == panel.model_combo.currentText()
    assert panel.model != ""


# -- Send follows the prompt box, not the open file --------------------------


def test_send_is_disabled_with_an_empty_prompt(panel) -> None:
    assert panel.send_btn.isEnabled() is False


def test_send_enables_as_soon_as_something_is_typed(panel) -> None:
    """Without a file or repo open — the box is for questions too."""
    panel.prompt_input.setPlainText("what is a decorator?")

    assert panel.send_btn.isEnabled() is True


def test_send_disables_again_when_the_prompt_is_cleared(panel) -> None:
    panel.prompt_input.setPlainText("something")
    panel.prompt_input.clear()

    assert panel.send_btn.isEnabled() is False


def test_whitespace_only_prompt_does_not_enable_send(panel) -> None:
    panel.prompt_input.setPlainText("   \n  ")
    assert panel.send_btn.isEnabled() is False


def test_prompt_box_is_typable_with_no_repository_open(panel) -> None:
    assert panel.prompt_input.isEnabled() is True


def test_send_is_disabled_while_busy_even_with_text(panel) -> None:
    panel.prompt_input.setPlainText("something")
    panel.set_busy(True)

    assert panel.send_btn.isEnabled() is False


# -- routing: general question vs file edit ---------------------------------


def test_send_with_no_file_asks_a_general_question(panel) -> None:
    """The panel is useful before a repository is opened rather than inert."""
    asked = []
    edits = []
    panel.general_chat_requested.connect(asked.append)
    panel.action_requested.connect(lambda a, i: edits.append((a, i)))
    panel.prompt_input.setPlainText("explain python generators")

    panel.send_btn.click()

    assert asked == ["explain python generators"]
    assert edits == [], "no file open, so this must not become an edit request"


def test_send_with_a_file_open_is_not_a_general_question(panel) -> None:
    """An open file means project context exists, so the prompt is routed for
    intent classification rather than answered as a context-free question."""
    panel.set_active_file("app.py")
    asked, routed = [], []
    panel.general_chat_requested.connect(asked.append)
    panel.prompt_submitted.connect(routed.append)
    panel.prompt_input.setPlainText("add a docstring")

    panel.send_btn.click()

    assert routed == ["add a docstring"]
    assert asked == []


def test_context_label_explains_the_no_file_case_from_the_start(panel) -> None:
    """Set at construction, not just after a file changes."""
    assert "general knowledge" in panel.context_label.text()


def test_action_buttons_still_require_a_file(panel) -> None:
    panel.prompt_input.setPlainText("some text")

    for button in panel._action_buttons.values():
        assert button.isEnabled() is False


# -- Knowledge Bank buttons --------------------------------------------------


def test_build_kb_button_emits(panel) -> None:
    panel.set_project_open(True)
    seen = []
    panel.build_kb_requested.connect(lambda: seen.append(True))

    panel.build_kb_btn.click()

    assert seen == [True]


def test_reindex_is_separate_from_build(panel) -> None:
    """Two distinct actions: incremental update vs full rebuild."""
    panel.set_project_open(True)
    built, reindexed = [], []
    panel.build_kb_requested.connect(lambda: built.append(True))
    panel.reindex_requested.connect(lambda: reindexed.append(True))

    panel.build_kb_btn.click()
    panel.reindex_btn.click()

    assert built == [True] and reindexed == [True]


def test_kb_buttons_need_a_project(panel) -> None:
    panel.set_project_open(False)
    assert panel.build_kb_btn.isEnabled() is False


def test_kb_build_is_blocked_while_busy(panel) -> None:
    panel.set_project_open(True)
    panel.set_busy(True)

    assert panel.build_kb_btn.isEnabled() is False


# -- model dropdown ---------------------------------------------------------


def test_model_dropdown_sends_the_bare_name_not_the_label(panel) -> None:
    """The visible label carries size annotations Ollama wouldn't recognise."""
    from assistant.ollama_models import ModelInfo

    panel.set_models([ModelInfo(name="gemma4", size_bytes=9_600_000_000, parameter_size="8.0B")])

    assert "8.0B" in panel.model_combo.currentText()
    assert panel.model == "gemma4"


def test_model_dropdown_prefers_gemma4(panel) -> None:
    from assistant.ollama_models import ModelInfo

    panel.set_models([ModelInfo(name="ornith"), ModelInfo(name="gemma4"), ModelInfo(name="qwen3.6")])

    assert panel.model == "gemma4"


def test_model_selection_survives_a_refresh(panel) -> None:
    """A refresh must not silently switch which model the user picked."""
    from assistant.ollama_models import ModelInfo

    models = [ModelInfo(name="gemma4"), ModelInfo(name="qwen3.6")]
    panel.set_models(models)
    panel.model_combo.setCurrentIndex(panel.model_combo.findData("qwen3.6"))

    panel.set_models(models)

    assert panel.model == "qwen3.6"


def test_refresh_models_button_emits(panel) -> None:
    seen = []
    panel.refresh_models_requested.connect(lambda: seen.append(True))

    panel.refresh_models_btn.click()

    assert seen == [True]


# -- prompt routing (mode picker removed — the tab classifies intent) --------
#
# The explicit Plan/Discussion/Code Fix radio picker is gone; AIPanel just
# forwards any prompt with project context via `prompt_submitted`, and
# `gui.ide.tab._classify_intent` (tested separately in
# tests/test_intent_classification.py) decides what to do with it. These tests
# cover only what AIPanel itself still owns: that project context is required
# for send to be meaningful, and that no mode gate blocks it anymore.


def test_send_no_longer_requires_a_mode_choice(panel) -> None:
    panel.set_project_open(True)
    panel.prompt_input.setPlainText("make it faster")

    assert panel.send_btn.isEnabled() is True


def test_send_with_project_context_and_no_file_still_routes_via_prompt_submitted(panel) -> None:
    """Code Fix used to require an open file; now nothing does — the AI resolves
    the target from the Knowledge Bank when none is open."""
    panel.set_project_open(True)
    panel.prompt_input.setPlainText("charges are off by a cent")
    routed = []
    panel.prompt_submitted.connect(routed.append)

    panel.send_btn.click()

    assert routed == ["charges are off by a cent"]


def test_with_no_repository_send_falls_back_to_a_plain_question(panel) -> None:
    """The panel stays useful before a project is chosen."""
    panel.set_project_open(False)
    asked, routed = [], []
    panel.general_chat_requested.connect(asked.append)
    panel.prompt_submitted.connect(routed.append)
    panel.prompt_input.setPlainText("what is a generator?")

    panel.send_btn.click()

    assert asked == ["what is a generator?"]
    assert routed == []


def test_build_request_leaves_the_path_empty_with_no_file(panel) -> None:
    """An empty rel_path is the signal for `propose_edit` to choose a target."""
    panel.set_project_open(True)

    request = panel.build_request("/tmp/proj", EditAction.IMPLEMENT, "fix charges")

    assert request.rel_path == ""


def test_context_label_says_the_ai_will_choose(panel) -> None:
    panel.set_project_open(True)
    panel.set_active_file(None)

    assert "choose which file" in panel.context_label.text()
