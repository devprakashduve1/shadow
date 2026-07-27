"""Tests for the editor-facing helpers in assistant/project_files.py.

These cover the data-loss-sensitive paths specifically: reading a file whole
(rather than truncating it and later saving the truncation back), refusing to
overwrite a file that changed underneath us, and never leaving a half-written
file behind.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from assistant.project_files import (
    BinaryFileError,
    FileConflictError,
    FileTooLargeError,
    ProjectFileError,
    atomic_write_file,
    iter_files,
    list_dir,
    read_text_file,
)


# -- list_dir ---------------------------------------------------------------


def test_list_dir_returns_dirs_first_then_files(tmp_path: Path) -> None:
    (tmp_path / "zeta_dir").mkdir()
    (tmp_path / "alpha.py").write_text("x")
    (tmp_path / "beta.py").write_text("x")

    assert list_dir(tmp_path) == [("zeta_dir", True), ("alpha.py", False), ("beta.py", False)]


def test_list_dir_hides_ignored_dirs_and_suffixes(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    (tmp_path / "app.py").write_text("x")

    assert list_dir(tmp_path) == [("src", True), ("app.py", False)]


def test_list_dir_is_shallow(tmp_path: Path) -> None:
    """Only one level — nested files belong to the child's own expansion."""
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    (nested / "buried.py").write_text("x")

    assert list_dir(tmp_path) == [("src", True)]
    assert list_dir(tmp_path, "src") == [("deep", True)]


def test_list_dir_refuses_to_escape_the_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "secrets").mkdir()

    with pytest.raises(ProjectFileError):
        list_dir(project, "../secrets")


def test_list_dir_on_a_file_raises(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x")
    with pytest.raises(ProjectFileError):
        list_dir(tmp_path, "app.py")


# -- read_text_file ---------------------------------------------------------


def test_read_text_file_returns_whole_content_not_a_truncation(tmp_path: Path) -> None:
    """The bug this guards: read_file() caps at 6000 bytes, so opening a larger
    file in an editor and saving it back would silently delete the remainder."""
    body = "line\n" * 5000  # 25,000 bytes — well past read_file's 6000 cap
    (tmp_path / "big.py").write_text(body)

    text, _mtime = read_text_file(tmp_path, "big.py")

    assert text == body


def test_read_text_file_returns_usable_mtime(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x")

    _text, mtime = read_text_file(tmp_path, "app.py")

    assert mtime == target.stat().st_mtime


def test_read_text_file_rejects_oversized_file(tmp_path: Path) -> None:
    (tmp_path / "huge.py").write_text("x" * 500)

    with pytest.raises(FileTooLargeError):
        read_text_file(tmp_path, "huge.py", max_bytes=100)


def test_read_text_file_rejects_binary_with_nul_byte(tmp_path: Path) -> None:
    (tmp_path / "app.bin").write_bytes(b"MZ\x00\x00binary")

    with pytest.raises(BinaryFileError):
        read_text_file(tmp_path, "app.bin")


def test_read_text_file_rejects_utf16_which_decodes_as_latin1(tmp_path: Path) -> None:
    """UTF-16 is the case a UnicodeDecodeError check alone would let through."""
    (tmp_path / "utf16.txt").write_bytes("hello".encode("utf-16"))

    with pytest.raises(BinaryFileError):
        read_text_file(tmp_path, "utf16.txt")


def test_read_text_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectFileError):
        read_text_file(tmp_path, "nope.py")


def test_read_text_file_refuses_to_escape_the_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "secret.txt").write_text("password")

    with pytest.raises(ProjectFileError):
        read_text_file(project, "../secret.txt")


# -- atomic_write_file ------------------------------------------------------


def test_atomic_write_file_round_trips(tmp_path: Path) -> None:
    new_mtime = atomic_write_file(tmp_path, "app.py", "print('hi')")

    assert (tmp_path / "app.py").read_text() == "print('hi')"
    assert new_mtime == (tmp_path / "app.py").stat().st_mtime


def test_atomic_write_file_creates_parent_directories(tmp_path: Path) -> None:
    atomic_write_file(tmp_path, "src/deep/new.py", "x")

    assert (tmp_path / "src" / "deep" / "new.py").read_text() == "x"


def test_atomic_write_file_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    atomic_write_file(tmp_path, "app.py", "x")

    assert [p.name for p in tmp_path.iterdir()] == ["app.py"]


def test_atomic_write_file_detects_a_concurrent_change(tmp_path: Path) -> None:
    """The lost-update guard: someone else wrote the file after we read it."""
    target = tmp_path / "app.py"
    target.write_text("original")
    _text, mtime = read_text_file(tmp_path, "app.py")

    os.utime(target, (mtime + 10, mtime + 10))  # simulate an external write

    with pytest.raises(FileConflictError):
        atomic_write_file(tmp_path, "app.py", "ours", expected_mtime=mtime)
    assert target.read_text() == "original"  # nothing written


def test_atomic_write_file_allows_save_when_mtime_matches(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("original")
    _text, mtime = read_text_file(tmp_path, "app.py")

    atomic_write_file(tmp_path, "app.py", "updated", expected_mtime=mtime)

    assert (tmp_path / "app.py").read_text() == "updated"


def test_atomic_write_file_flags_a_deleted_file(tmp_path: Path) -> None:
    with pytest.raises(FileConflictError):
        atomic_write_file(tmp_path, "gone.py", "x", expected_mtime=123.0)


def test_atomic_write_file_preserves_the_executable_bit(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\necho old")
    script.chmod(0o755)

    atomic_write_file(tmp_path, "run.sh", "#!/bin/sh\necho new")

    assert script.stat().st_mode & 0o777 == 0o755


def test_atomic_write_file_refuses_to_escape_the_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")

    with pytest.raises(ProjectFileError):
        atomic_write_file(project, "../outside.txt", "pwned")
    assert outside.read_text() == "safe"


# -- iter_files -------------------------------------------------------------


def test_iter_files_skips_ignored_dirs_without_descending(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x")

    found = {str(p) for p in iter_files(tmp_path)}

    assert found == {"src/app.py"}


def test_iter_files_respects_max_files(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x")

    assert len(list(iter_files(tmp_path, max_files=3))) == 3


def test_iter_files_is_unbounded_by_default(tmp_path: Path) -> None:
    """list_files caps at 500; the indexer needs more than that."""
    for i in range(600):
        (tmp_path / f"f{i:04d}.py").write_text("x")

    assert len(list(iter_files(tmp_path))) == 600
