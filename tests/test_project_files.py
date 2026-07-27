from assistant.project_files import (
    ProjectFileError,
    build_file_tree_text,
    find_relevant_files,
    list_files,
    read_file,
    write_file,
)


def _make_project(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("should be ignored")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "checkout.py").write_text(
        'def checkout():\n    raise TimeoutError("payment timeout")\n'
    )
    (tmp_path / "src" / "unrelated.py").write_text("def unrelated():\n    return 1\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG fake binary content")
    (tmp_path / "README.md").write_text("a readme")
    return tmp_path


def test_list_files_skips_ignored_dirs_and_binary_extensions(tmp_path):
    project = _make_project(tmp_path)
    files = {str(p) for p in list_files(project)}
    assert files == {"README.md", "src/checkout.py", "src/unrelated.py"}


def test_build_file_tree_text_lists_relative_paths(tmp_path):
    project = _make_project(tmp_path)
    text = build_file_tree_text(project)
    assert "src/checkout.py" in text
    assert "node_modules" not in text


def test_find_relevant_files_ranks_by_keyword_overlap(tmp_path):
    project = _make_project(tmp_path)
    results = find_relevant_files(project, "fix the payment timeout error in checkout")
    assert results
    assert results[0][0] == "src/checkout.py"
    assert "unrelated.py" not in [path for path, _ in results]


def test_find_relevant_files_empty_for_no_keywords(tmp_path):
    project = _make_project(tmp_path)
    assert find_relevant_files(project, "a") == []  # too short to yield any keyword


def test_read_file_returns_none_for_missing_file(tmp_path):
    project = _make_project(tmp_path)
    assert read_file(project, "does/not/exist.py") is None


def test_read_file_truncates_to_max_bytes(tmp_path):
    project = tmp_path
    (project / "big.py").write_text("x" * 100)
    assert len(read_file(project, "big.py", max_bytes=10)) == 10


def test_write_file_creates_parent_directories(tmp_path):
    project = tmp_path
    write_file(project, "new/nested/file.py", "content")
    assert (project / "new" / "nested" / "file.py").read_text() == "content"


def test_write_file_rejects_path_escaping_project_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    try:
        write_file(project, "../../etc/passwd", "pwned")
        assert False, "should have raised ProjectFileError"
    except ProjectFileError:
        pass
    assert not (tmp_path / "etc" / "passwd").exists()


def test_read_file_rejects_path_escaping_project_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the project")
    assert read_file(project, "../secret.txt") is None
