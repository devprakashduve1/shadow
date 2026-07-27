"""Tests for assistant/shadow_home.py, edits/atomic_io.py, and edits/diffs.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assistant.edits.atomic_io import append_jsonl, read_json, read_jsonl, write_json_atomic
from assistant.edits.diffs import diff_stats, unified_diff_text
from assistant.shadow_home import (
    backups_dir,
    bank_dir,
    flatten_rel_path,
    journal_path,
    repo_id,
    shadow_home,
)


# -- repo_id ----------------------------------------------------------------


def test_repo_id_includes_the_folder_name(tmp_path: Path) -> None:
    project = tmp_path / "my-webapp"
    project.mkdir()

    assert repo_id(project).startswith("my-webapp-")


def test_repo_id_differs_for_same_named_repos_at_different_paths(tmp_path: Path) -> None:
    """The collision this scheme exists to prevent — two repos both called `web`
    must not share one bank directory."""
    first = tmp_path / "a" / "web"
    second = tmp_path / "b" / "web"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert repo_id(first) != repo_id(second)
    assert repo_id(first).startswith("web-") and repo_id(second).startswith("web-")


def test_repo_id_is_stable_across_calls(tmp_path: Path) -> None:
    project = tmp_path / "stable"
    project.mkdir()

    assert repo_id(project) == repo_id(project)


def test_repo_id_ignores_trailing_slash_and_relative_segments(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()

    assert repo_id(str(project)) == repo_id(str(project) + "/")
    assert repo_id(project) == repo_id(project / "." )


def test_repo_id_sanitizes_unsafe_characters(tmp_path: Path) -> None:
    project = tmp_path / "we ird:name"
    project.mkdir()

    identifier = repo_id(project)

    assert " " not in identifier and ":" not in identifier


def test_repo_id_changes_when_the_repo_moves(tmp_path: Path) -> None:
    """A moved repo should get a fresh bank rather than reuse a stale one."""
    original = tmp_path / "here" / "proj"
    original.mkdir(parents=True)
    before = repo_id(original)

    moved = tmp_path / "there" / "proj"
    moved.mkdir(parents=True)

    assert repo_id(moved) != before


# -- paths ------------------------------------------------------------------


def test_bank_dir_is_under_the_shadow_home(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    root = tmp_path / "shadow"

    assert bank_dir(project, root).parent == root


def test_paths_are_not_created_as_a_side_effect(tmp_path: Path) -> None:
    """Opening a repo shouldn't litter the Desktop before there's data to store."""
    project = tmp_path / "proj"
    project.mkdir()
    root = tmp_path / "shadow"

    bank_dir(project, root)
    backups_dir(project, root)
    journal_path(project, root)

    assert not root.exists()


def test_journal_lives_under_backups(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    root = tmp_path / "shadow"

    assert journal_path(project, root).parent == backups_dir(project, root)


def test_shadow_home_defaults_to_desktop() -> None:
    assert shadow_home() == Path("~/Desktop/.shadow").expanduser()


def test_flatten_rel_path_removes_separators() -> None:
    assert flatten_rel_path("src/app/main.py") == "src__app__main.py"


# -- atomic_io --------------------------------------------------------------


def test_write_json_atomic_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "data.json"

    write_json_atomic(target, {"a": 1, "b": [2, 3]})

    assert json.loads(target.read_text()) == {"a": 1, "b": [2, 3]}


def test_write_json_atomic_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "data.json"

    write_json_atomic(target, {"ok": True})

    assert target.is_file()


def test_write_json_atomic_leaves_no_temp_files(tmp_path: Path) -> None:
    write_json_atomic(tmp_path / "data.json", {"x": 1})

    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_write_json_atomic_preserves_the_old_file_on_a_serialization_error(tmp_path: Path) -> None:
    """Serializing before opening anything means a bad payload can't truncate
    the existing file."""
    target = tmp_path / "data.json"
    write_json_atomic(target, {"good": True})

    with pytest.raises(TypeError):
        write_json_atomic(target, {"bad": object()})

    assert json.loads(target.read_text()) == {"good": True}
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_write_json_atomic_overwrites_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json_atomic(target, {"version": 1})
    write_json_atomic(target, {"version": 2})

    assert json.loads(target.read_text()) == {"version": 2}


def test_write_json_atomic_handles_unicode(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json_atomic(target, {"name": "wörld ünicode"})

    assert read_json(target)["name"] == "wörld ünicode"


def test_read_json_returns_default_for_missing_file(tmp_path: Path) -> None:
    assert read_json(tmp_path / "nope.json", default={"fallback": True}) == {"fallback": True}


def test_read_json_returns_default_for_corrupt_file(tmp_path: Path) -> None:
    """A corrupt cache should mean "rebuild", not a crash."""
    target = tmp_path / "bad.json"
    target.write_text("{not valid json")

    assert read_json(target, default=[]) == []


# -- jsonl ------------------------------------------------------------------


def test_append_jsonl_accumulates_records(tmp_path: Path) -> None:
    target = tmp_path / "journal.jsonl"

    append_jsonl(target, {"n": 1})
    append_jsonl(target, {"n": 2})

    assert read_jsonl(target) == [{"n": 1}, {"n": 2}]


def test_append_jsonl_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "journal.jsonl"
    append_jsonl(target, {"n": 1})
    assert target.is_file()


def test_read_jsonl_skips_a_torn_line(tmp_path: Path) -> None:
    """Only the incomplete record is lost, not the whole log."""
    target = tmp_path / "journal.jsonl"
    append_jsonl(target, {"n": 1})
    with open(target, "a", encoding="utf-8") as handle:
        handle.write('{"n": 2, "incomp')  # simulate a crash mid-append

    assert read_jsonl(target) == [{"n": 1}]


def test_read_jsonl_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


# -- diffs ------------------------------------------------------------------


def test_unified_diff_shows_added_and_removed_lines() -> None:
    diff = unified_diff_text("a\nb\nc\n", "a\nB\nc\n", "f.py")

    assert "-b" in diff and "+B" in diff
    assert "a/f.py" in diff and "b/f.py" in diff


def test_unified_diff_is_empty_for_identical_text() -> None:
    assert unified_diff_text("same\n", "same\n", "f.py") == ""


def test_unified_diff_ends_with_a_newline() -> None:
    diff = unified_diff_text("a", "b", "f.py")
    assert diff.endswith("\n")


def test_diff_stats_counts_changes() -> None:
    stats = diff_stats("one\ntwo\nthree\n", "one\nTWO\nthree\nfour\n")

    assert stats.added == 2  # TWO + four
    assert stats.removed == 1  # two
    assert stats.is_empty is False


def test_diff_stats_empty_for_identical_text() -> None:
    stats = diff_stats("x\n", "x\n")

    assert stats.is_empty is True
    assert stats.summary() == "no changes"


def test_diff_stats_summary_formats_counts() -> None:
    assert diff_stats("a\n", "a\nb\n").summary() == "+1"
    assert diff_stats("a\nb\n", "a\n").summary() == "-1"
