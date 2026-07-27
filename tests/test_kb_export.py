"""Tests for assistant/knowledge/export.py.

The text files are a derived view for humans. What matters is that they contain
the real content (not placeholders), stay in step with the banks, and are clearly
marked as regenerated so nobody edits one expecting it to persist.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from assistant.knowledge.export import (
    DEFAULT_EXPORT_DIR,
    GENERAL_FILE,
    INDEX_FILE,
    export_dir,
    export_general,
    export_repo,
    render_general_text,
    render_repo_text,
    write_index,
)
from assistant.knowledge.general import GeneralDigest, GeneralKnowledgeBank
from assistant.knowledge.indexer import KnowledgeBank, build_index
from assistant.shadow_home import repo_id
from database.json_store import EventStore
from events.schema import Event, EventType, Severity


def _git(path: Path, *args: str):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "knowledgebank"


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(base_dir=tmp_path / "events")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "billing-api"
    path.mkdir()
    for args in (["init"], ["config", "user.email", "t@e.com"], ["config", "user.name", "T"],
                 ["config", "commit.gpgsign", "false"]):
        _git(path, *args)
    (path / "app.py").write_text(
        "import os\n"
        "from fastapi import FastAPI\n"
        "from billing import charge\n\n"
        "app = FastAPI()\n"
        'KEY = os.environ["STRIPE_KEY"]\n\n'
        '@app.post("/charge")\n'
        "def do_charge():\n"
        '    """Charges a card."""\n'
        "    return charge(1)\n"
    )
    (path / "billing.py").write_text("import stripe\n\n\ndef charge(amount):\n    return amount\n")
    (path / "requirements.txt").write_text("fastapi\nstripe\n")
    (path / "README.md").write_text("# Billing API\n\nHandles card charges.\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "initial billing api")
    return path


def _event(content: str, event_type: EventType = EventType.DECISION) -> Event:
    return Event(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        type=event_type,
        title=content[:30],
        application="Slack",
        severity=Severity.LOW,
        source="speech",
        content=content,
    )


# -- location ----------------------------------------------------------------


def test_default_export_dir_sits_beside_the_log_folders() -> None:
    """~/Desktop/Shadow already holds the dated capture logs."""
    assert export_dir() == Path("~/Desktop/Shadow/knowledgebank").expanduser()
    assert DEFAULT_EXPORT_DIR.parts[-2:] == ("Shadow", "knowledgebank")


def test_export_dir_is_not_created_as_a_side_effect(tmp_path: Path) -> None:
    export_dir(tmp_path / "nothing")
    assert not (tmp_path / "nothing").exists()


# -- general bank ------------------------------------------------------------


def test_general_export_writes_a_txt_file(store: EventStore, shadow_root: Path, dest: Path) -> None:
    store.insert_event(_event("We decided to charge in the customer's local currency."))
    GeneralKnowledgeBank(store, shadow_root).build()

    path = export_general(store, shadow_root, dest)

    assert path.name == GENERAL_FILE
    assert path.suffix == ".txt"
    assert path.parent == dest


def test_general_export_contains_the_actual_decisions(
    store: EventStore, shadow_root: Path, dest: Path
) -> None:
    store.insert_event(_event("We decided to charge in the customer's local currency."))
    GeneralKnowledgeBank(store, shadow_root).build()

    text = export_general(store, shadow_root, dest).read_text()

    assert "local currency" in text
    assert "Decisions" in text


def test_general_export_includes_vocabulary_and_tickets(
    store: EventStore, shadow_root: Path, dest: Path
) -> None:
    store.insert_event(
        _event("PaymentGateway retries are tracked under PROJ-1139 for this release.",
               EventType.NOTE)
    )
    GeneralKnowledgeBank(store, shadow_root).build()

    text = export_general(store, shadow_root, dest).read_text()

    assert "PaymentGateway" in text
    assert "PROJ-1139" in text


def test_general_export_explains_an_empty_bank(store: EventStore, shadow_root: Path, dest: Path) -> None:
    """Better than a file of empty headings."""
    text = export_general(store, shadow_root, dest).read_text()

    assert "Nothing captured yet" in text
    assert "Live Monitor" in text


def test_empty_decision_section_explains_why(store: EventStore, shadow_root: Path) -> None:
    """A real, current limitation: speech is classified as MEETING by default, so
    decisions inside a transcript aren't separated out."""
    digest = GeneralDigest(event_count=5, meetings=[], decisions=[])

    text = render_general_text(digest)

    assert "events/classifier.py" in text


def test_general_export_is_marked_as_generated(store: EventStore, shadow_root: Path, dest: Path) -> None:
    text = export_general(store, shadow_root, dest).read_text()

    assert "overwritten on every index run" in text
    assert "Editing it has no effect" in text


def test_general_export_is_overwritten_not_appended(
    store: EventStore, shadow_root: Path, dest: Path
) -> None:
    store.insert_event(_event("First decision about currency handling in checkout."))
    GeneralKnowledgeBank(store, shadow_root).build()
    first = export_general(store, shadow_root, dest).read_text()

    second = export_general(store, shadow_root, dest).read_text()

    assert second.count("GENERAL KNOWLEDGE BANK") == 1
    assert len(second) == pytest.approx(len(first), abs=200)


# -- repo bank ---------------------------------------------------------------


def test_repo_export_returns_none_when_unindexed(repo: Path, shadow_root: Path, dest: Path) -> None:
    assert export_repo(repo, shadow_root, dest) is None


def test_repo_export_filename_includes_the_path_hash(
    repo: Path, shadow_root: Path, dest: Path
) -> None:
    """Two repos with the same folder name must not overwrite each other."""
    build_index(repo, shadow_root)

    path = export_repo(repo, shadow_root, dest)

    assert path.stem == repo_id(repo)
    assert path.suffix == ".txt"


def test_same_named_repos_export_to_different_files(tmp_path: Path, dest: Path) -> None:
    shadow = tmp_path / "sh"
    paths = []
    for parent in ("a", "b"):
        repo = tmp_path / parent / "web"
        repo.mkdir(parents=True)
        (repo / "app.py").write_text(f"# {parent}\n")
        build_index(repo, shadow)
        paths.append(export_repo(repo, shadow, dest))

    assert paths[0] != paths[1]
    assert len(list(dest.glob("*.txt"))) == 2


def test_repo_export_contains_structure_and_dependencies(
    repo: Path, shadow_root: Path, dest: Path
) -> None:
    build_index(repo, shadow_root)

    text = export_repo(repo, shadow_root, dest).read_text()

    assert "REPOSITORY KNOWLEDGE BANK — billing-api" in text
    assert "FastAPI" in text, "frameworks"
    assert "Stripe" in text, "integrations"
    assert "/charge" in text, "http routes"
    assert "STRIPE_KEY" in text, "environment variables"
    assert "Module relationships" in text
    assert "billing.py" in text
    assert "Billing API" in text, "README excerpt"


def test_repo_export_includes_the_api_outline(repo: Path, shadow_root: Path, dest: Path) -> None:
    build_index(repo, shadow_root)

    text = export_repo(repo, shadow_root, dest).read_text()

    assert "API outline" in text
    assert "def charge(amount)" in text
    assert "Charges a card." in text, "docstrings carry over"


def test_repo_export_marks_approximate_symbols(tmp_path: Path, dest: Path) -> None:
    """Non-Python symbol extraction is regex-based; the file says so."""
    shadow = tmp_path / "sh"
    repo = tmp_path / "frontend"
    repo.mkdir()
    (repo / "api.ts").write_text("export function fetchUser() {}\n")
    build_index(repo, shadow)

    text = export_repo(repo, shadow, dest).read_text()

    assert "approximate" in text


def test_repo_export_includes_git_history(repo: Path, shadow_root: Path, dest: Path) -> None:
    build_index(repo, shadow_root)

    text = export_repo(repo, shadow_root, dest).read_text()

    assert "Recent commits" in text
    assert "initial billing api" in text


def test_unindexed_bank_renders_a_clear_message(repo: Path, shadow_root: Path) -> None:
    text = render_repo_text(KnowledgeBank(repo, shadow_root))
    assert "has not been indexed yet" in text


def test_repo_export_reflects_a_rebuild(repo: Path, shadow_root: Path, dest: Path) -> None:
    """The text stays in step with the bank rather than going stale."""
    build_index(repo, shadow_root)
    export_repo(repo, shadow_root, dest)

    (repo / "shipping.py").write_text("def quote():\n    return 5\n")
    build_index(repo, shadow_root)
    text = export_repo(repo, shadow_root, dest).read_text()

    assert "shipping.py" in text
    assert "def quote()" in text


# -- index file --------------------------------------------------------------


def test_index_lists_the_exported_files(
    repo: Path, store: EventStore, shadow_root: Path, dest: Path
) -> None:
    build_index(repo, shadow_root)
    export_repo(repo, shadow_root, dest)
    export_general(store, shadow_root, dest)

    text = write_index(dest).read_text()

    assert GENERAL_FILE in text
    assert repo_id(repo) in text


def test_index_does_not_list_itself(repo: Path, shadow_root: Path, dest: Path) -> None:
    build_index(repo, shadow_root)
    export_repo(repo, shadow_root, dest)

    text = write_index(dest).read_text()

    assert text.count(INDEX_FILE) == 0


def test_index_handles_an_empty_directory(dest: Path) -> None:
    text = write_index(dest).read_text()
    assert "Nothing exported yet" in text


# -- formatting --------------------------------------------------------------


def test_lines_are_wrapped_for_reading(repo: Path, shadow_root: Path, dest: Path) -> None:
    """A wall of 4000-character lines isn't readable in a text editor.

    Only prose is checked. Paths, symbol signatures and `a -> b` graph edges are
    legitimately long, and wrapping them would make them uncopyable.
    """
    build_index(repo, shadow_root)

    text = export_repo(repo, shadow_root, dest).read_text()

    prose_lines = [
        line
        for line in text.splitlines()
        if not line.startswith(("    ", "  - "))
        and "->" not in line
        and " " in line.strip()  # a token with no spaces is a path or identifier
    ]
    assert max((len(line) for line in prose_lines), default=0) <= 100


def test_export_creates_the_directory(store: EventStore, shadow_root: Path, tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "kb"

    export_general(store, shadow_root, nested)

    assert nested.is_dir()
