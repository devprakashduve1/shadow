"""Tests for assistant/knowledge/context.py.

The central claim being tested is that ranking touches **no** files — that's the
whole reason the Knowledge Bank exists, replacing a scoring pass that read every
file in the project. `test_ranking_reads_no_files_at_all` and
`test_only_top_ranked_files_are_read` are the load-bearing ones.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assistant.knowledge.context import (
    DEFAULT_MAX_FILES,
    assemble_context,
    context_for_edit,
    rank_files,
)
from assistant.knowledge.indexer import KnowledgeBank, build_index


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        '"""Authentication."""\n\n\ndef authenticate_user(token):\n'
        '    """Checks a token."""\n    return bool(token)\n'
    )
    (root / "src" / "billing.py").write_text(
        "def charge_card(amount):\n    return amount\n"
    )
    (root / "src" / "views.py").write_text(
        "from auth import authenticate_user\n\n\ndef index():\n    return 1\n"
    )
    (root / "unrelated.py").write_text("def totally_different():\n    pass\n")
    (root / "README.md").write_text("# Payments API\n\nHandles payments and auth.\n")
    (root / "requirements.txt").write_text("flask>=2.0\nstripe==7.0\n")
    return root


@pytest.fixture
def bank(project: Path, shadow_root: Path) -> KnowledgeBank:
    build_index(project, shadow_root)
    return KnowledgeBank(project, shadow_root)


# -- ranking -----------------------------------------------------------------


def test_ranking_reads_no_files_at_all(bank: KnowledgeBank, monkeypatch) -> None:
    """The point of the index: scoring must not touch the filesystem.

    The old `find_relevant_files` read every file on every call; if this
    regresses, large repos become unusable again.
    """
    import builtins

    opened = []
    real_open = builtins.open

    def tracking_open(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    entries = bank.load_files()  # loading the index itself is one read
    monkeypatch.setattr(builtins, "open", tracking_open)

    rank_files(entries, "fix the authenticate user token check")

    assert opened == [], f"ranking read files: {opened}"


def test_ranking_prefers_symbol_name_matches(bank: KnowledgeBank) -> None:
    ranked, symbols = rank_files(bank.load_files(), "authenticate_user is broken")

    assert ranked[0] == "src/auth.py"
    assert "authenticate_user" in symbols


def test_ranking_matches_camel_case_parts(bank: KnowledgeBank, project: Path, shadow_root: Path) -> None:
    """A question about "user auth" should reach `authenticateUser`."""
    (project / "src" / "session.ts").write_text("export function authenticateUser() {}\n")
    build_index(project, shadow_root)

    ranked, _symbols = rank_files(
        KnowledgeBank(project, shadow_root).load_files(), "user authentication problem"
    )

    assert any("auth" in path or "session" in path for path in ranked)


def test_ranking_excludes_irrelevant_files(bank: KnowledgeBank) -> None:
    ranked, _symbols = rank_files(bank.load_files(), "charge_card billing amount")

    assert "src/billing.py" in ranked
    assert "unrelated.py" not in ranked


def test_open_file_is_pinned_first(bank: KnowledgeBank) -> None:
    """Whatever the user is looking at is nearly always most relevant."""
    ranked, _symbols = rank_files(
        bank.load_files(), "charge_card billing", open_file="unrelated.py"
    )

    assert ranked[0] == "unrelated.py"


def test_importers_of_the_open_file_are_pinned(bank: KnowledgeBank) -> None:
    ranked, _symbols = rank_files(
        bank.load_files(), "something unrelated", open_file="src/auth.py"
    )

    assert ranked[0] == "src/auth.py"
    assert "src/views.py" in ranked, "views.py imports auth, so it's relevant context"


def test_ranking_respects_max_files(bank: KnowledgeBank) -> None:
    ranked, _symbols = rank_files(bank.load_files(), "def return", max_files=2)
    assert len(ranked) <= 2


def test_ranking_is_stable_for_equal_scores(bank: KnowledgeBank) -> None:
    entries = bank.load_files()
    first, _s = rank_files(entries, "def")
    second, _s = rank_files(entries, "def")
    assert first == second


def test_empty_instruction_yields_no_matches(bank: KnowledgeBank) -> None:
    ranked, symbols = rank_files(bank.load_files(), "")
    assert ranked == [] and symbols == []


def test_skipped_files_are_not_ranked(project: Path, shadow_root: Path) -> None:
    """Binary/oversized files have no useful content to offer a prompt."""
    (project / "blob.dat").write_bytes(b"\x00auth token binary")
    build_index(project, shadow_root)

    ranked, _s = rank_files(KnowledgeBank(project, shadow_root).load_files(), "auth token")

    assert "blob.dat" not in ranked


# -- assembly ----------------------------------------------------------------


def test_only_top_ranked_files_are_read(bank: KnowledgeBank) -> None:
    """Reads are bounded by max_files, not by project size."""
    read_paths = []

    def tracking_reader(rel_path):
        read_paths.append(rel_path)
        return "file body\n"

    assemble_context(
        bank, "authenticate_user token", max_files=2, read_file=tracking_reader
    )

    assert len(read_paths) <= 2


def test_assembled_context_includes_file_bodies(bank: KnowledgeBank) -> None:
    result = assemble_context(bank, "authenticate_user token")

    assert "src/auth.py" in result.files_used
    assert "def authenticate_user" in result.text
    assert "relevant files" in result.text


def test_selection_is_always_included_first(bank: KnowledgeBank) -> None:
    """Highest priority section — it's literally what the user pointed at."""
    result = assemble_context(
        bank, "explain this", selection="x = compute_total()", max_chars=200
    )

    assert "x = compute_total()" in result.text
    assert result.text.index("selected code") < 50


def test_context_respects_the_character_budget(bank: KnowledgeBank) -> None:
    result = assemble_context(bank, "authenticate_user token billing", max_chars=400)

    assert len(result.text) <= 400


def test_low_priority_sections_are_dropped_first(bank: KnowledgeBank) -> None:
    """Background context goes before the code the question is about.

    Asserts the ordering property rather than an exact list, so adding a new
    section doesn't break the test for the wrong reason.
    """
    result = assemble_context(bank, "authenticate_user", max_chars=250)

    assert result.truncated is True
    assert "relevant files" in result.text, "the code survives truncation"
    # Anything dropped must rank below the code sections that were kept.
    assert "relevant files" not in result.sections_dropped
    assert "selected code" not in result.sections_dropped
    assert "project shape" in result.sections_dropped, "cheapest context goes first"


def test_generous_budget_includes_everything(bank: KnowledgeBank) -> None:
    result = assemble_context(bank, "authenticate_user token", max_chars=50_000)

    assert result.truncated is False
    assert "dependencies" in result.text
    assert "flask" in result.text
    assert "Payments API" in result.text


def test_sections_are_dropped_whole_not_mid_file(bank: KnowledgeBank) -> None:
    """A half-truncated file would hand the model broken syntax."""
    result = assemble_context(bank, "authenticate_user", max_chars=300)

    for label in result.sections_dropped:
        assert f"--- {label} ---" not in result.text


def test_symbol_outline_flags_approximate_entries(project: Path, shadow_root: Path) -> None:
    """Regex-derived symbols are labelled so the model can discount them."""
    (project / "app.ts").write_text("export function handlePayment() {}\n")
    build_index(project, shadow_root)
    bank = KnowledgeBank(project, shadow_root)

    result = assemble_context(bank, "handlePayment", max_chars=50_000)

    assert "(approximate)" in result.text


def test_empty_bank_yields_empty_context(project: Path, shadow_root: Path) -> None:
    bank = KnowledgeBank(project, shadow_root)  # never built
    result = assemble_context(bank, "anything")

    assert result.is_empty


def test_unreadable_file_is_skipped_not_fatal(bank: KnowledgeBank) -> None:
    result = assemble_context(bank, "authenticate_user", read_file=lambda _p: None)

    assert result.files_used == []
    assert not result.text.startswith("--- relevant files")


# -- context_for_edit wrapper ------------------------------------------------


def test_context_for_edit_returns_text(project: Path, shadow_root: Path) -> None:
    build_index(project, shadow_root)

    text = context_for_edit(project, "authenticate_user token", shadow_root=shadow_root)

    assert "authenticate_user" in text


def test_context_for_edit_empty_without_a_bank(project: Path, shadow_root: Path) -> None:
    """Callers fall back to their old behaviour rather than special-casing this."""
    assert context_for_edit(project, "anything", shadow_root=shadow_root) == ""


def test_context_for_edit_passes_the_open_file_through(project: Path, shadow_root: Path) -> None:
    build_index(project, shadow_root)

    text = context_for_edit(
        project, "unrelated question", open_file="src/billing.py", shadow_root=shadow_root
    )

    assert "charge_card" in text


def test_default_max_files_is_modest() -> None:
    """A sanity bound: context should stay prompt-sized for a slow local model."""
    assert DEFAULT_MAX_FILES <= 10


# -- blending both banks -----------------------------------------------------


def test_structure_and_team_context_survive_a_realistic_budget(bank: KnowledgeBank) -> None:
    """Regression guard for a real design flaw.

    File bodies can be 4KB each; without a reserved share of the budget they
    consumed all of it, and the small-but-high-value sections (impact analysis,
    frameworks, team decisions) were never included at any realistic size.
    """
    result = assemble_context(
        bank,
        "authenticate_user token",
        open_file="src/auth.py",
        general_context="We decided tokens expire after 15 minutes.",
        max_chars=3000,
    )

    assert "relevant files" in result.text, "code still leads"
    assert "project structure" in result.text, "impact analysis must fit"
    assert "team context" in result.text
    assert "tokens expire after 15 minutes" in result.text


def test_file_bodies_do_not_exceed_their_share(bank: KnowledgeBank) -> None:
    from assistant.knowledge.context import FILE_BODY_BUDGET_SHARE

    result = assemble_context(
        bank, "authenticate_user", read_file=lambda _p: "x" * 50_000, max_chars=4000
    )

    body_section = result.text.split("--- relevant files ---")[-1]
    body_section = body_section.split("---")[0]
    assert len(body_section) <= 4000 * FILE_BODY_BUDGET_SHARE + 200


def test_impact_analysis_names_dependents(project: Path, shadow_root: Path) -> None:
    """The payoff of the module graph: "what else touches this" in the prompt."""
    build_index(project, shadow_root)
    bank = KnowledgeBank(project, shadow_root)

    result = assemble_context(bank, "change authenticate_user", open_file="src/auth.py",
                              max_chars=50_000)

    assert "impact of changing src/auth.py" in result.text
    assert "src/views.py" in result.text, "views.py imports auth, so it's in the blast radius"


def test_general_context_is_ranked_below_code(bank: KnowledgeBank) -> None:
    """Team notes explain intent; the code is authoritative about behaviour."""
    result = assemble_context(
        bank, "authenticate_user", general_context="A decision about auth.", max_chars=50_000
    )

    assert result.text.index("relevant files") < result.text.index("team context")


def test_context_for_edit_includes_the_general_bank(project: Path, shadow_root: Path) -> None:
    from datetime import datetime

    from assistant.knowledge.general import GeneralKnowledgeBank
    from database.json_store import EventStore
    from events.schema import Event, EventType, Severity

    store = EventStore(base_dir=shadow_root.parent / "events")
    store.insert_event(
        Event(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            type=EventType.DECISION,
            title="auth",
            application="Slack",
            severity=Severity.LOW,
            source="speech",
            content="We decided that authentication tokens must be rotated every hour.",
        )
    )
    GeneralKnowledgeBank(store, shadow_root).build()
    build_index(project, shadow_root)

    text = context_for_edit(
        project, "authenticate_user rotation", shadow_root=shadow_root, event_store=store
    )

    assert "rotated every hour" in text


def test_context_for_edit_returns_team_context_with_no_repo_index(
    project: Path, shadow_root: Path
) -> None:
    """Organizational knowledge is worth sending even before a repo is indexed."""
    from datetime import datetime

    from assistant.knowledge.general import GeneralKnowledgeBank
    from database.json_store import EventStore
    from events.schema import Event, EventType, Severity

    store = EventStore(base_dir=shadow_root.parent / "events2")
    store.insert_event(
        Event(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            type=EventType.DECISION,
            title="x",
            application="Slack",
            severity=Severity.LOW,
            source="speech",
            content="We decided to standardise on structured logging across all services.",
        )
    )
    GeneralKnowledgeBank(store, shadow_root).build()

    text = context_for_edit(project, "logging", shadow_root=shadow_root, event_store=store)

    assert "structured logging" in text


def test_a_broken_general_bank_never_blocks_an_edit(project: Path, shadow_root: Path) -> None:
    """Organizational context is a bonus; a failure there must not stop a code edit."""

    class _Exploding:
        def query_events(self, *_args, **_kwargs):
            raise RuntimeError("event store is broken")

    build_index(project, shadow_root)

    text = context_for_edit(
        project, "authenticate_user", shadow_root=shadow_root, event_store=_Exploding()
    )

    assert "authenticate_user" in text
