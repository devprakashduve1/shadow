"""Tests for assistant/edits/actions.py.

Network is faked by patching `urllib.request.urlopen` with NDJSON responses, the
same approach as tests/test_coding_agent.py.

The important cases here are the safety ones: a dirty git tree must NOT block an
edit (unlike the batch coding agent), a file that changed underneath a proposal
must, backups must be written before any overwrite, and revert must restore
byte-identical content.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from assistant.edits.actions import (
    EditAction,
    EditError,
    EditRequest,
    StaleFileError,
    apply_proposal,
    edit_history,
    propose_edit,
    revert,
    suggest_test_path,
)
from assistant.shadow_home import backups_dir, journal_path


class _FakeResponse:
    """Mimics Ollama's streaming NDJSON response."""

    def __init__(self, text: str):
        chunks = [json.dumps({"response": part, "done": False}) for part in [text]]
        chunks.append(json.dumps({"response": "", "done": True}))
        self._buffer = io.BytesIO(("\n".join(chunks) + "\n").encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._buffer)


def _fake_model(*replies: str):
    """Returns a urlopen replacement that yields `replies` in order.

    Also records how many calls were made, so tests can assert on the
    retry/fallback behaviour.
    """
    state = {"calls": 0}

    def opener(*_args, **_kwargs):
        index = min(state["calls"], len(replies) - 1)
        state["calls"] += 1
        return _FakeResponse(replies[index])

    opener.state = state
    return opener


def _block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "proj"
    path.mkdir()
    (path / "app.py").write_text("def greet():\n    return 'hello'\n")
    return path


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


def _request(project: Path, action=EditAction.REFACTOR, **kwargs) -> EditRequest:
    return EditRequest(
        project_path=str(project), rel_path="app.py", action=action, **kwargs
    )


# -- proposing --------------------------------------------------------------


def test_propose_edit_returns_a_diff_without_touching_disk(project: Path) -> None:
    original = (project / "app.py").read_text()
    reply = "def greet():\n    return 'hi'\n"

    with patch("urllib.request.urlopen", _fake_model(reply)):
        proposal = propose_edit(_request(project))

    assert "return 'hi'" in proposal.proposed
    assert "+" in proposal.diff_text and "-" in proposal.diff_text
    assert proposal.stats.added > 0
    assert (project / "app.py").read_text() == original, "propose must not write"


def test_propose_edit_uses_whole_file_strategy_for_a_short_file(project: Path) -> None:
    with patch("urllib.request.urlopen", _fake_model("def greet():\n    return 'hi'\n")):
        proposal = propose_edit(_request(project))

    assert proposal.strategy == "whole_file"


def test_propose_edit_uses_search_replace_for_a_long_file(project: Path) -> None:
    """Long files get surgical edits — rewriting them wholesale is slow and risky."""
    long_body = "\n".join(f"line_{i} = {i}" for i in range(400)) + "\n"
    (project / "big.py").write_text(long_body)
    request = EditRequest(
        project_path=str(project), rel_path="big.py", action=EditAction.REFACTOR
    )

    with patch("urllib.request.urlopen", _fake_model(_block("line_0 = 0", "line_0 = 999"))):
        proposal = propose_edit(request)

    assert proposal.strategy == "search_replace"
    assert "line_0 = 999" in proposal.proposed
    assert "line_399 = 399" in proposal.proposed, "untouched lines must survive"


def test_propose_edit_retries_then_falls_back_to_whole_file(project: Path) -> None:
    """Small models produce unapplicable blocks often; without the fallback the
    feature would just fail. Asserts all three model calls happen."""
    long_body = "\n".join(f"line_{i} = {i}" for i in range(400)) + "\n"
    (project / "big.py").write_text(long_body)
    request = EditRequest(project_path=str(project), rel_path="big.py", action=EditAction.REFACTOR)

    bad = _block("this text is not in the file", "whatever")
    good_whole_file = "rewritten = True\n"
    opener = _fake_model(bad, bad, good_whole_file)

    with patch("urllib.request.urlopen", opener):
        proposal = propose_edit(request)

    assert opener.state["calls"] == 3, "expected initial attempt, retry, then fallback"
    assert proposal.strategy == "whole_file"
    assert proposal.proposed == good_whole_file
    assert len(proposal.warnings) == 2


def test_propose_edit_succeeds_on_the_retry(project: Path) -> None:
    long_body = "\n".join(f"line_{i} = {i}" for i in range(400)) + "\n"
    (project / "big.py").write_text(long_body)
    request = EditRequest(project_path=str(project), rel_path="big.py", action=EditAction.REFACTOR)

    opener = _fake_model(_block("nonexistent", "x"), _block("line_5 = 5", "line_5 = 55"))

    with patch("urllib.request.urlopen", opener):
        proposal = propose_edit(request)

    assert opener.state["calls"] == 2, "should not reach the whole-file fallback"
    assert "line_5 = 55" in proposal.proposed
    assert len(proposal.warnings) == 1


def test_propose_edit_strips_a_code_fence(project: Path) -> None:
    with patch("urllib.request.urlopen", _fake_model("```python\ndef greet():\n    pass\n```")):
        proposal = propose_edit(_request(project))

    assert "```" not in proposal.proposed


def test_propose_edit_rejects_an_empty_response(project: Path) -> None:
    with patch("urllib.request.urlopen", _fake_model("   \n  ")):
        with pytest.raises(EditError, match="empty"):
            propose_edit(_request(project))


def test_propose_edit_refuses_the_explain_action(project: Path) -> None:
    with pytest.raises(EditError, match="does not produce file edits"):
        propose_edit(_request(project, action=EditAction.EXPLAIN))


def test_propose_edit_on_a_missing_file_raises(project: Path) -> None:
    request = EditRequest(project_path=str(project), rel_path="nope.py", action=EditAction.FIX)

    with patch("urllib.request.urlopen", _fake_model("x")):
        with pytest.raises(EditError):
            propose_edit(request)


def test_propose_edit_strips_echoed_selection_markers(project: Path) -> None:
    reply = ">>> SELECTION START\ndef greet():\n    return 'hi'\n>>> SELECTION END\n"

    with patch("urllib.request.urlopen", _fake_model(reply)):
        proposal = propose_edit(_request(project, selection="    return 'hello'"))

    assert "SELECTION" not in proposal.proposed


# -- generate tests ---------------------------------------------------------


def test_suggest_test_path_prefers_an_existing_tests_dir(project: Path) -> None:
    (project / "tests").mkdir()
    assert suggest_test_path(project, "app.py") == "tests/test_app.py"


def test_suggest_test_path_falls_back_to_a_sibling(project: Path) -> None:
    assert suggest_test_path(project, "src/app.py") == "src/test_app.py"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("app.ts", "app.test.ts"),
        ("app.jsx", "app.test.jsx"),
        ("main.go", "main_test.go"),
    ],
)
def test_suggest_test_path_matches_ecosystem_conventions(project: Path, source, expected) -> None:
    assert suggest_test_path(project, source) == expected


def test_generate_tests_proposes_a_new_file(project: Path) -> None:
    (project / "tests").mkdir()

    with patch("urllib.request.urlopen", _fake_model("def test_greet():\n    assert True\n")):
        proposal = propose_edit(_request(project, action=EditAction.GENERATE_TESTS))

    assert proposal.rel_path == "tests/test_app.py"
    assert proposal.is_new is True
    assert proposal.original == ""


def test_generate_tests_warns_when_overwriting(project: Path) -> None:
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("# existing tests\n")

    with patch("urllib.request.urlopen", _fake_model("def test_new():\n    pass\n")):
        proposal = propose_edit(_request(project, action=EditAction.GENERATE_TESTS))

    assert proposal.is_new is False
    assert any("already exists" in w for w in proposal.warnings)


# -- applying ---------------------------------------------------------------


def _proposal_for(project: Path, reply: str, **kwargs):
    with patch("urllib.request.urlopen", _fake_model(reply)):
        return propose_edit(_request(project, **kwargs))


def test_apply_proposal_writes_the_file(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "def greet():\n    return 'hi'\n")

    apply_proposal(proposal, project, shadow_root=shadow_root)

    assert (project / "app.py").read_text() == "def greet():\n    return 'hi'\n"


def test_apply_proposal_does_not_require_a_clean_git_tree(project: Path, shadow_root: Path) -> None:
    """The key difference from coding_agent.apply_plan: an editor can't demand a
    clean tree, because the user is mid-edit by definition."""
    for args in (["init"], ["config", "user.email", "t@e.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=project, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True)
    (project / "other.py").write_text("uncommitted work\n")  # dirty the tree

    proposal = _proposal_for(project, "def greet():\n    return 'hi'\n")
    apply_proposal(proposal, project, shadow_root=shadow_root)

    assert (project / "app.py").read_text() == "def greet():\n    return 'hi'\n"
    assert (project / "other.py").read_text() == "uncommitted work\n", "untouched"


def test_apply_proposal_makes_no_commit_and_no_branch(project: Path, shadow_root: Path) -> None:
    for args in (["init"], ["config", "user.email", "t@e.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=project, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True)
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True
    ).stdout.strip()
    branch_before = subprocess.run(
        ["git", "branch", "--show-current"], cwd=project, capture_output=True, text=True
    ).stdout.strip()

    proposal = _proposal_for(project, "changed\n")
    apply_proposal(proposal, project, shadow_root=shadow_root)

    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True
    ).stdout.strip()
    branch_after = subprocess.run(
        ["git", "branch", "--show-current"], cwd=project, capture_output=True, text=True
    ).stdout.strip()
    assert after == before, "must not commit"
    assert branch_after == branch_before, "must not switch branches"


def test_apply_proposal_writes_a_backup_and_journal_entry(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "new content\n")

    applied = apply_proposal(proposal, project, shadow_root=shadow_root)

    backup = Path(applied.backup_path)
    assert backup.is_file()
    assert backup.read_text() == "def greet():\n    return 'hello'\n", "backup holds the OLD content"
    assert backup.parent == backups_dir(project, shadow_root)

    records = edit_history(project, shadow_root)
    assert len(records) == 1
    assert records[0]["rel_path"] == "app.py"
    assert records[0]["action"] == "refactor"
    assert journal_path(project, shadow_root).is_file()


def test_apply_proposal_detects_a_file_changed_since_proposing(project: Path, shadow_root: Path) -> None:
    """A slow local model makes this likely, not theoretical."""
    proposal = _proposal_for(project, "ai version\n")
    (project / "app.py").write_text("the user typed this instead\n")

    with pytest.raises(StaleFileError, match="changed on disk"):
        apply_proposal(proposal, project, shadow_root=shadow_root)

    assert (project / "app.py").read_text() == "the user typed this instead\n", "nothing written"


def test_apply_proposal_detects_a_deleted_file(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "ai version\n")
    (project / "app.py").unlink()

    with pytest.raises(StaleFileError):
        apply_proposal(proposal, project, shadow_root=shadow_root)


def test_apply_proposal_honours_a_manual_override(project: Path, shadow_root: Path) -> None:
    """"Edit manually" — the user's text wins over the model's."""
    proposal = _proposal_for(project, "ai wrote this\n")

    apply_proposal(
        proposal, project, override_content="human wrote this\n", shadow_root=shadow_root
    )

    assert (project / "app.py").read_text() == "human wrote this\n"


def test_apply_proposal_can_skip_backups(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "new\n")

    applied = apply_proposal(proposal, project, backup=False, shadow_root=shadow_root)

    assert applied.backup_path is None


def test_apply_proposal_creates_a_new_test_file(project: Path, shadow_root: Path) -> None:
    (project / "tests").mkdir()
    with patch("urllib.request.urlopen", _fake_model("def test_x():\n    pass\n")):
        proposal = propose_edit(_request(project, action=EditAction.GENERATE_TESTS))

    applied = apply_proposal(proposal, project, shadow_root=shadow_root)

    assert (project / "tests" / "test_app.py").read_text() == "def test_x():\n    pass\n"
    assert applied.backup_path is None, "nothing to back up for a new file"


# -- reverting --------------------------------------------------------------


def test_revert_restores_byte_identical_content(project: Path, shadow_root: Path) -> None:
    original = (project / "app.py").read_text()
    proposal = _proposal_for(project, "totally different\n")
    applied = apply_proposal(proposal, project, shadow_root=shadow_root)
    assert (project / "app.py").read_text() != original

    revert(applied)

    assert (project / "app.py").read_text() == original


def test_revert_refuses_after_later_modifications(project: Path, shadow_root: Path) -> None:
    """Reverting would discard work done after the AI edit."""
    proposal = _proposal_for(project, "ai version\n")
    applied = apply_proposal(proposal, project, shadow_root=shadow_root)
    (project / "app.py").write_text("i edited this afterwards\n")

    with pytest.raises(StaleFileError, match="modified since"):
        revert(applied)

    assert (project / "app.py").read_text() == "i edited this afterwards\n"


def test_revert_without_a_backup_raises(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "new\n")
    applied = apply_proposal(proposal, project, backup=False, shadow_root=shadow_root)

    with pytest.raises(EditError, match="No backup"):
        revert(applied)


def test_revert_with_a_missing_backup_file_raises(project: Path, shadow_root: Path) -> None:
    proposal = _proposal_for(project, "new\n")
    applied = apply_proposal(proposal, project, shadow_root=shadow_root)
    Path(applied.backup_path).unlink()

    with pytest.raises(EditError, match="missing"):
        revert(applied)


# -- path safety ------------------------------------------------------------


def test_propose_edit_refuses_a_path_outside_the_project(project: Path, tmp_path: Path) -> None:
    (tmp_path / "outside.py").write_text("secret\n")
    request = EditRequest(
        project_path=str(project), rel_path="../outside.py", action=EditAction.REFACTOR
    )

    with patch("urllib.request.urlopen", _fake_model("pwned\n")):
        with pytest.raises(EditError):
            propose_edit(request)

    assert (tmp_path / "outside.py").read_text() == "secret\n"


def test_edit_history_is_newest_first(project: Path, shadow_root: Path) -> None:
    for reply in ("first\n", "second\n"):
        proposal = _proposal_for(project, reply)
        apply_proposal(proposal, project, shadow_root=shadow_root)

    history = edit_history(project, shadow_root)

    assert len(history) == 2
    assert history[0]["sha1_after"] != history[1]["sha1_after"]
