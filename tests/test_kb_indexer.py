"""Tests for assistant/knowledge/indexer.py against real git repositories.

The important tests here are the incremental-correctness ones. An index that
silently describes code that no longer exists is worse than no index, so each of
the four documented traps (amended HEAD, previously-dirty files, renames/deletes,
gitignored files) has a test that would fail if the handling were removed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assistant.knowledge import indexer as indexer_module
from assistant.knowledge.indexer import KnowledgeBank, build_index


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "commit.gpgsign", "false")


def _commit_all(path: Path, message: str = "c") -> None:
    _git(path, "add", "-A")
    _git(path, "commit", "-m", message)


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "proj"
    _init_repo(path)
    (path / "app.py").write_text("def greet():\n    return 'hello'\n")
    (path / "util.py").write_text("VALUE = 1\n")
    (path / "README.md").write_text("# Demo\n\nA demo project.\n\n## Setup\n")
    (path / "package.json").write_text('{"name": "demo", "dependencies": {"react": "^18"}}')
    _commit_all(path, "initial")
    return path


@pytest.fixture
def counting_indexer(monkeypatch):
    """Wraps _index_one_file so tests can assert which files were re-read."""
    calls = []
    original = indexer_module._index_one_file

    def counted(root, rel_path, max_file_bytes):
        calls.append(rel_path)
        return original(root, rel_path, max_file_bytes)

    monkeypatch.setattr(indexer_module, "_index_one_file", counted)
    return calls


# -- full build --------------------------------------------------------------


def test_build_creates_the_bank(repo: Path, shadow_root: Path) -> None:
    result = build_index(repo, shadow_root)

    bank = KnowledgeBank(repo, shadow_root)
    assert bank.exists is True
    assert result.mode == "full"
    assert result.files_indexed >= 4


def test_bank_lives_outside_the_repository(repo: Path, shadow_root: Path) -> None:
    """Indexing must not add untracked files to the user's project."""
    build_index(repo, shadow_root)

    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    assert not (repo / ".shadow").exists()


def test_index_records_symbols_and_language(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)

    entry = KnowledgeBank(repo, shadow_root).load_files()["app.py"]

    assert entry.language == "python"
    assert entry.parse == "ast"
    assert {s.name for s in entry.symbols} == {"greet"}


def test_index_records_manifests_and_docs(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)
    bank = KnowledgeBank(repo, shadow_root)

    manifests = bank.load_manifests()
    readme, _docs = bank.load_docs()

    assert manifests[0].dependencies == {"react": "^18"}
    assert readme is not None and "demo project" in readme.excerpt
    assert readme.headings == ["Demo", "Setup"]


def test_outline_lists_entrypoints_and_languages(repo: Path, shadow_root: Path) -> None:
    (repo / "main.py").write_text("def main():\n    pass\n")
    _commit_all(repo)
    build_index(repo, shadow_root)

    outline = KnowledgeBank(repo, shadow_root).load_outline()

    assert "main.py" in outline["entrypoints"]
    assert outline["by_language"]["python"] >= 3


def test_outline_excludes_regex_derived_symbols(repo: Path, shadow_root: Path) -> None:
    """Regex symbols include false positives, so they stay out of prompts."""
    (repo / "app.ts").write_text("export function fromRegex() {}\n")
    _commit_all(repo)
    build_index(repo, shadow_root)

    outline = KnowledgeBank(repo, shadow_root).load_outline()

    assert "fromRegex" not in {s["name"] for s in outline["top_symbols"]}
    assert "greet" in {s["name"] for s in outline["top_symbols"]}, "AST symbols are included"


def test_build_honours_gitignore(repo: Path, shadow_root: Path) -> None:
    (repo / ".gitignore").write_text("build/\nsecret.txt\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.js").write_text("compiled")
    (repo / "secret.txt").write_text("shh")
    _commit_all(repo)

    build_index(repo, shadow_root)
    indexed = set(KnowledgeBank(repo, shadow_root).load_files())

    assert "build/out.js" not in indexed
    assert "secret.txt" not in indexed


def test_build_skips_ignored_dirs_even_when_committed(repo: Path, shadow_root: Path) -> None:
    """git would report these; DEFAULT_IGNORED_DIRS filters them anyway."""
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("x")
    _commit_all(repo)

    build_index(repo, shadow_root)

    assert "node_modules/dep.js" not in KnowledgeBank(repo, shadow_root).load_files()


def test_build_works_without_git(tmp_path: Path, shadow_root: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("x = 1\n")

    result = build_index(plain, shadow_root)

    assert result.files_indexed == 1
    assert KnowledgeBank(plain, shadow_root).load_meta().git.is_repo is False


def test_large_file_is_indexed_without_symbols(repo: Path, shadow_root: Path) -> None:
    (repo / "huge.py").write_text("x = 1\n" * 5000)
    _commit_all(repo)

    build_index(repo, shadow_root, max_file_bytes=100)
    entry = KnowledgeBank(repo, shadow_root).load_files()["huge.py"]

    assert entry.skipped == "too_large"
    assert entry.symbols == []
    assert entry.sha1, "still hashed, so change detection keeps working"


def test_binary_file_is_flagged_not_text(repo: Path, shadow_root: Path) -> None:
    (repo / "blob.dat").write_bytes(b"\x00\x01\x02binary")
    _commit_all(repo)

    build_index(repo, shadow_root)
    entry = KnowledgeBank(repo, shadow_root).load_files()["blob.dat"]

    assert entry.skipped == "not_text"


def test_truncated_flag_set_past_max_files(repo: Path, shadow_root: Path) -> None:
    for i in range(20):
        (repo / f"f{i}.py").write_text(f"x = {i}\n")
    _commit_all(repo)

    result = build_index(repo, shadow_root, max_files=5)

    assert result.truncated is True
    assert KnowledgeBank(repo, shadow_root).load_meta().truncated is True


def test_progress_callback_reports_completion(repo: Path, shadow_root: Path) -> None:
    seen = []
    build_index(repo, shadow_root, progress=lambda done, total: seen.append((done, total)))

    assert seen, "progress should be reported at least once"
    assert seen[-1][0] == seen[-1][1], "final callback reports done == total"


# -- incremental: the reuse path --------------------------------------------


def test_unchanged_files_are_reused(repo: Path, shadow_root: Path, counting_indexer) -> None:
    build_index(repo, shadow_root)
    counting_indexer.clear()

    result = build_index(repo, shadow_root)

    assert counting_indexer == [], "nothing changed, so nothing should be re-read"
    assert result.files_reused >= 4
    assert result.files_indexed == 0


def test_only_the_edited_file_is_reread(repo: Path, shadow_root: Path, counting_indexer) -> None:
    build_index(repo, shadow_root)
    counting_indexer.clear()

    (repo / "app.py").write_text("def greet():\n    return 'changed'\n")
    build_index(repo, shadow_root)

    assert counting_indexer == ["app.py"]


def test_reread_updates_the_symbol_list(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)
    (repo / "app.py").write_text("def renamed_function():\n    pass\n")

    build_index(repo, shadow_root)
    entry = KnowledgeBank(repo, shadow_root).load_files()["app.py"]

    assert {s.name for s in entry.symbols} == {"renamed_function"}


def test_new_file_is_picked_up(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)
    (repo / "added.py").write_text("def added():\n    pass\n")
    _commit_all(repo)

    build_index(repo, shadow_root)

    assert "added.py" in KnowledgeBank(repo, shadow_root).load_files()


def test_untracked_new_file_is_picked_up(repo: Path, shadow_root: Path) -> None:
    """Not committed, so only `git status` knows about it."""
    build_index(repo, shadow_root)
    (repo / "scratch.py").write_text("def scratch():\n    pass\n")

    build_index(repo, shadow_root)

    assert "scratch.py" in KnowledgeBank(repo, shadow_root).load_files()


def test_force_full_reindexes_everything(repo: Path, shadow_root: Path, counting_indexer) -> None:
    build_index(repo, shadow_root)
    counting_indexer.clear()

    build_index(repo, shadow_root, force_full=True)

    assert len(counting_indexer) >= 4


# -- incremental: trap 3, deletions and renames ------------------------------


def test_deleted_file_is_dropped_from_the_index(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)
    (repo / "util.py").unlink()
    _commit_all(repo)

    result = build_index(repo, shadow_root)

    assert "util.py" not in KnowledgeBank(repo, shadow_root).load_files()
    assert result.files_removed == 1


def test_renamed_file_updates_both_paths(repo: Path, shadow_root: Path) -> None:
    build_index(repo, shadow_root)
    _git(repo, "mv", "util.py", "helpers.py")
    _commit_all(repo)

    build_index(repo, shadow_root)
    files = KnowledgeBank(repo, shadow_root).load_files()

    assert "util.py" not in files
    assert "helpers.py" in files


# -- incremental: trap 1, rewritten history ---------------------------------


def _sha1_of(path: Path) -> str:
    import hashlib

    return hashlib.sha1(path.read_bytes()).hexdigest()


def test_amended_commit_keeps_the_index_correct(repo: Path, shadow_root: Path, counting_indexer) -> None:
    """An amend orphans the old commit but git keeps the object (via the reflog),
    so `git diff <old>..HEAD` still resolves and reports the change correctly."""
    build_index(repo, shadow_root)
    stored_head = KnowledgeBank(repo, shadow_root).load_meta().git.head_sha
    counting_indexer.clear()

    (repo / "app.py").write_text("def greet():\n    return 'amended'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--amend", "-m", "amended")

    assert _git(repo, "cat-file", "-e", f"{stored_head}^{{commit}}").returncode == 0, (
        "precondition: after an amend the old object survives, which is why the "
        "diff fast path is still usable here"
    )

    build_index(repo, shadow_root)

    assert "app.py" in counting_indexer
    entry = KnowledgeBank(repo, shadow_root).load_files()["app.py"]
    assert entry.sha1 == _sha1_of(repo / "app.py")


def test_pruned_old_head_falls_back_to_a_full_rescan(
    repo: Path, shadow_root: Path, counting_indexer
) -> None:
    """Once gc prunes the orphaned commit, `git diff <old>..HEAD` fails outright
    (exit 128). `_commit_exists` catches that and forces a rescan, which is the
    only reason the index doesn't silently stop updating."""
    build_index(repo, shadow_root)
    stored_head = KnowledgeBank(repo, shadow_root).load_meta().git.head_sha

    (repo / "app.py").write_text("def greet():\n    return 'rewritten'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--amend", "-m", "rewritten")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "--prune=now")

    assert _git(repo, "cat-file", "-e", f"{stored_head}^{{commit}}").returncode != 0, \
        "precondition: the old commit is genuinely gone"
    assert not indexer_module._commit_exists(repo, stored_head)

    counting_indexer.clear()
    build_index(repo, shadow_root)

    entry = KnowledgeBank(repo, shadow_root).load_files()["app.py"]
    assert entry.sha1 == _sha1_of(repo / "app.py")
    assert {s.name for s in entry.symbols} == {"greet"}


def test_hard_reset_does_not_leave_a_stale_index(repo: Path, shadow_root: Path) -> None:
    (repo / "app.py").write_text("def greet():\n    return 'v2'\n")
    _commit_all(repo, "v2")
    build_index(repo, shadow_root)

    _git(repo, "reset", "--hard", "HEAD~1")

    build_index(repo, shadow_root)
    entry = KnowledgeBank(repo, shadow_root).load_files()["app.py"]

    assert {s.name for s in entry.symbols} == {"greet"}
    assert entry.sha1 == _sha1_of(repo / "app.py"), "index hash must match disk"


# -- incremental: trap 2, previously-dirty files ----------------------------


def test_file_dirty_at_index_time_then_reverted_is_reread(
    repo: Path, shadow_root: Path, counting_indexer
) -> None:
    """The subtle one.

    Index while a file is uncommitted, then `git restore` it. HEAD never moved
    and the file now matches HEAD, so `git diff` reports nothing — but the stored
    entry describes the uncommitted version. Without persisting `dirty_paths`
    the index would keep describing code that no longer exists.
    """
    (repo / "app.py").write_text("def greet():\n    return 'uncommitted draft'\n")
    build_index(repo, shadow_root)
    indexed = KnowledgeBank(repo, shadow_root).load_files()["app.py"]
    assert indexed.sha1 == _sha1_of(repo / "app.py")

    counting_indexer.clear()
    _git(repo, "restore", "app.py")  # back to the committed version

    build_index(repo, shadow_root)

    assert "app.py" in counting_indexer, "previously-dirty path must be re-checked"
    reindexed = KnowledgeBank(repo, shadow_root).load_files()["app.py"]
    assert "hello" in (repo / "app.py").read_text()
    assert reindexed.sha1 != indexed.sha1


def test_dirty_paths_are_persisted_in_meta(repo: Path, shadow_root: Path) -> None:
    (repo / "app.py").write_text("modified\n")

    build_index(repo, shadow_root)

    assert KnowledgeBank(repo, shadow_root).load_meta().git.dirty_paths == ["app.py"]


# -- incremental: trap 4, gitignored files ----------------------------------


def test_gitignored_but_indexed_file_is_still_rechecked(
    tmp_path: Path, shadow_root: Path, counting_indexer
) -> None:
    """A non-git directory's files can never be reported by git, so the stat
    sweep is the only thing that notices they changed."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("def one():\n    pass\n")
    build_index(plain, shadow_root)
    counting_indexer.clear()

    (plain / "app.py").write_text("def two():\n    pass\n")
    build_index(plain, shadow_root)

    assert counting_indexer == ["app.py"]
    entry = KnowledgeBank(plain, shadow_root).load_files()["app.py"]
    assert {s.name for s in entry.symbols} == {"two"}


# -- bank identity and status ------------------------------------------------


def test_moved_repo_invalidates_the_bank(repo: Path, shadow_root: Path, tmp_path: Path) -> None:
    """A bank keyed to an old path shouldn't be read as describing a new one."""
    build_index(repo, shadow_root)
    bank = KnowledgeBank(repo, shadow_root)
    assert bank.load_meta() is not None

    # Simulate the recorded path no longer matching where we are now.
    import json

    meta_path = bank.dir / "meta.json"
    data = json.loads(meta_path.read_text())
    data["root_path"] = str(tmp_path / "somewhere-else")
    meta_path.write_text(json.dumps(data))

    assert bank.load_meta() is None


def test_schema_version_mismatch_invalidates_the_bank(repo: Path, shadow_root: Path) -> None:
    import json

    build_index(repo, shadow_root)
    bank = KnowledgeBank(repo, shadow_root)
    meta_path = bank.dir / "meta.json"
    data = json.loads(meta_path.read_text())
    data["version"] = 999
    meta_path.write_text(json.dumps(data))

    assert bank.load_meta() is None


def test_two_repos_named_the_same_get_separate_banks(tmp_path: Path, shadow_root: Path) -> None:
    first = tmp_path / "a" / "web"
    second = tmp_path / "b" / "web"
    for path, body in ((first, "def a(): pass\n"), (second, "def b(): pass\n")):
        path.mkdir(parents=True)
        (path / "app.py").write_text(body)
        build_index(path, shadow_root)

    first_symbols = {s.name for s in KnowledgeBank(first, shadow_root).load_files()["app.py"].symbols}
    second_symbols = {s.name for s in KnowledgeBank(second, shadow_root).load_files()["app.py"].symbols}

    assert first_symbols == {"a"}
    assert second_symbols == {"b"}


def test_status_reports_missing_then_ready_then_stale(repo: Path, shadow_root: Path) -> None:
    bank = KnowledgeBank(repo, shadow_root)
    assert bank.status() == "missing"

    build_index(repo, shadow_root)
    assert bank.status() == "ready"

    (repo / "app.py").write_text("changed\n")
    assert bank.status() == "stale"


def test_meta_written_last_so_a_partial_build_reads_as_missing(repo: Path, shadow_root: Path) -> None:
    """Guards the write ordering: meta.json is what `exists` gates on."""
    bank = KnowledgeBank(repo, shadow_root)
    build_index(repo, shadow_root)

    (bank.dir / "meta.json").unlink()

    assert bank.exists is False
    assert bank.load_files(), "payload files remain, so a rebuild can still reuse nothing harmful"
