import io
import json
import subprocess
from unittest import mock

import pytest

from assistant.coding_agent import (
    CodingAgentError,
    PlanFile,
    PlanResult,
    _parse_plan,
    apply_plan,
    generate_plan,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _ndjson(*objs) -> bytes:
    return b"".join((json.dumps(o) + "\n").encode("utf-8") for o in objs)


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, capture_output=True)


def _commit_all(path, message="init"):
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True)


def _current_branch(path) -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"], cwd=path, capture_output=True, text=True
    ).stdout.strip()


# -- _parse_plan ------------------------------------------------------------


def test_parse_plan_extracts_summary_and_existing_files():
    raw = (
        "Add a retry cap in checkout.py.\n\n"
        "FILES:\n"
        "src/checkout.py\n"
        "made/up/file.py\n"  # hallucinated — not in known_files, should be dropped
    )
    plan = _parse_plan(raw, known_files={"src/checkout.py", "README.md"})
    assert plan.summary == "Add a retry cap in checkout.py."
    assert plan.files == [PlanFile(path="src/checkout.py", is_new=False)]


def test_parse_plan_keeps_new_files_even_if_not_known():
    raw = "Create a config module.\n\nFILES:\nNEW: src/retry_config.py\n"
    plan = _parse_plan(raw, known_files=set())
    assert plan.files == [PlanFile(path="src/retry_config.py", is_new=True)]


def test_parse_plan_dedupes_repeated_paths():
    raw = "Plan.\n\nFILES:\na.py\na.py\n"
    plan = _parse_plan(raw, known_files={"a.py"})
    assert plan.files == [PlanFile(path="a.py", is_new=False)]


def test_parse_plan_with_no_files_marker_treats_everything_as_summary():
    plan = _parse_plan("Just some prose with no marker.", known_files=set())
    assert plan.summary == "Just some prose with no marker."
    assert plan.files == []


# -- generate_plan ------------------------------------------------------------


def test_generate_plan_reads_project_and_parses_response(tmp_path):
    (tmp_path / "checkout.py").write_text('def checkout():\n    raise TimeoutError("timeout")\n')
    body = _ndjson({"response": "Fix the timeout.\n\nFILES:\ncheckout.py\n", "done": True})

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        plan = generate_plan(tmp_path, "fix the checkout timeout", base_url="http://fake", model="gemma4")

    assert plan.summary == "Fix the timeout."
    assert plan.files == [PlanFile(path="checkout.py", is_new=False)]


# -- apply_plan ------------------------------------------------------------


def test_apply_plan_writes_on_new_branch_and_commits(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "checkout.py").write_text("def checkout():\n    pass\n")
    _commit_all(tmp_path)
    original_branch = _current_branch(tmp_path)

    plan = PlanResult(summary="fix it", files=[PlanFile(path="checkout.py")])
    body = _ndjson({"response": 'def checkout():\n    return "fixed"\n', "done": True})

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        result = apply_plan(tmp_path, plan, "fix the checkout bug", base_url="http://fake", model="gemma4")

    assert result.branch.startswith("shadow-agent/")
    assert result.changed_files == ["checkout.py"]
    assert (tmp_path / "checkout.py").read_text() == 'def checkout():\n    return "fixed"\n'
    assert _current_branch(tmp_path) == result.branch

    # Original branch untouched: still exactly one commit, unchanged content on disk there.
    log = subprocess.run(
        ["git", "log", "--oneline", original_branch], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip().splitlines()
    assert len(log) == 1


def test_apply_plan_creates_new_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)

    plan = PlanResult(summary="add config", files=[PlanFile(path="config.py", is_new=True)])
    body = _ndjson({"response": "TIMEOUT = 30\n", "done": True})

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        result = apply_plan(tmp_path, plan, "add a config module", base_url="http://fake", model="gemma4")

    assert (tmp_path / "config.py").read_text() == "TIMEOUT = 30\n"
    assert "config.py" in result.changed_files


def test_apply_plan_strips_code_fence(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("old\n")
    _commit_all(tmp_path)

    plan = PlanResult(summary="fix", files=[PlanFile(path="a.py")])
    fenced = "```python\nnew_content = True\n```"
    body = _ndjson({"response": fenced, "done": True})

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        apply_plan(tmp_path, plan, "fix a.py", base_url="http://fake", model="gemma4")

    assert (tmp_path / "a.py").read_text() == "new_content = True"


def test_apply_plan_refuses_when_not_a_git_repo(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    plan = PlanResult(summary="fix", files=[PlanFile(path="a.py")])
    with pytest.raises(CodingAgentError, match="git repository"):
        apply_plan(tmp_path, plan, "fix it")


def test_apply_plan_refuses_when_working_tree_is_dirty(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n")  # uncommitted change

    plan = PlanResult(summary="fix", files=[PlanFile(path="a.py")])
    with pytest.raises(CodingAgentError, match="uncommitted changes"):
        apply_plan(tmp_path, plan, "fix it")

    assert (tmp_path / "a.py").read_text() == "x = 2\n"  # left exactly as the user had it


def test_apply_plan_refuses_when_plan_has_no_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)

    plan = PlanResult(summary="fix", files=[])
    with pytest.raises(CodingAgentError, match="doesn't name any files"):
        apply_plan(tmp_path, plan, "fix it")
