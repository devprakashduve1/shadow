"""Tests for assistant/knowledge/general.py.

Uses a real `EventStore` over `tmp_path`, matching tests/test_event_store.py —
the interesting behaviour is how captured events fold into a digest, which a mock
store wouldn't exercise.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant.knowledge.general import (
    MAX_GLOSSARY_TERMS,
    MAX_PER_SECTION,
    GeneralKnowledgeBank,
    assemble_general_context,
    general_dir,
    render_digest,
)
from database.json_store import EventStore
from events.schema import Event, EventType, Severity


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(base_dir=tmp_path / "events")


def _event(
    content: str,
    event_type: EventType = EventType.NOTE,
    *,
    when: str = "",
    application: str = "Chrome",
    source: str = "ocr",
    tags=None,
) -> Event:
    return Event(
        timestamp=when or datetime.now().isoformat(timespec="seconds"),
        type=event_type,
        title=content[:40],
        application=application,
        severity=Severity.LOW,
        source=source,
        content=content,
        tags=list(tags or []),
    )


def _bank(store: EventStore, shadow_root: Path) -> GeneralKnowledgeBank:
    return GeneralKnowledgeBank(store, shadow_root)


# -- location ----------------------------------------------------------------


def test_general_bank_lives_beside_repo_banks(shadow_root: Path) -> None:
    assert general_dir(shadow_root).parent == shadow_root


def test_general_dir_name_cannot_collide_with_a_repo_id(shadow_root: Path) -> None:
    """Repo directories are always `<name>-<8 hex>`; a leading underscore and no
    hash keeps this one clear of them."""
    name = general_dir(shadow_root).name
    assert name.startswith("_")
    assert "-" not in name


def test_paths_are_not_created_as_a_side_effect(store: EventStore, shadow_root: Path) -> None:
    general_dir(shadow_root)
    assert not shadow_root.exists()


# -- building ----------------------------------------------------------------


def test_empty_store_yields_an_empty_digest(store: EventStore, shadow_root: Path) -> None:
    digest = _bank(store, shadow_root).build()
    assert digest.is_empty


def test_decisions_are_collected(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event(
            "We decided to move the payment retry logic into the billing service.",
            EventType.DECISION,
        )
    )

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == 1
    assert "payment retry logic" in digest.decisions[0].text


def test_action_items_are_collected(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event("Action item: Priya to update the deployment runbook this week.", EventType.TASK)
    )

    digest = _bank(store, shadow_root).build()

    assert len(digest.action_items) == 1


def test_problems_are_collected(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event("ConnectionTimeout talking to the inventory service again in staging.", EventType.ERROR)
    )

    digest = _bank(store, shadow_root).build()

    assert len(digest.problems) == 1


def test_meeting_transcripts_are_collected(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event(
            "So the plan for the quarter is to finish onboarding then start on reporting.",
            EventType.MEETING,
            source="speech",
        )
    )

    digest = _bank(store, shadow_root).build()

    assert len(digest.meetings) == 1
    assert digest.meetings[0].source == "speech"


def test_tagged_events_land_in_the_right_section(store: EventStore, shadow_root: Path) -> None:
    """A NOTE carrying a "decision" tag still belongs with the decisions."""
    store.insert_event(
        _event(
            "Agreed that we will not support Internet Explorer going forward.",
            EventType.NOTE,
            tags=["decision"],
        )
    )

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == 1


def test_glossary_captures_domain_vocabulary(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event("The InventoryService calls PaymentGateway through the order-fulfilment queue.")
    )

    digest = _bank(store, shadow_root).build()

    assert "InventoryService" in digest.glossary
    assert "PaymentGateway" in digest.glossary


def test_glossary_excludes_ui_chrome_words(store: EventStore, shadow_root: Path) -> None:
    """Screen OCR is full of toolbar labels; those aren't domain vocabulary."""
    store.insert_event(_event("file edit view window help settings profile loading untitled"))

    digest = _bank(store, shadow_root).build()

    for noise in ("settings", "profile", "loading", "untitled"):
        assert noise not in digest.glossary


def test_ticket_keys_are_counted(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("Picked up PROJ-1139 and linked it to PLAT-204 for the release."))

    digest = _bank(store, shadow_root).build()

    assert digest.tickets["PROJ-1139"] == 1
    assert digest.tickets["PLAT-204"] == 1


def test_hosts_and_applications_are_counted(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(
        _event("Reviewing the spec at https://confluence.example.com/pages/42", application="Chrome")
    )

    digest = _bank(store, shadow_root).build()

    assert digest.applications["Chrome"] == 1
    assert digest.hosts["confluence.example.com"] == 1


def test_type_counts_and_days_are_recorded(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("A decision was made about caching.", EventType.DECISION,
                              when="2026-07-01T10:00:00"))
    store.insert_event(_event("Another note entirely about something else.", EventType.NOTE,
                              when="2026-07-02T10:00:00"))

    digest = _bank(store, shadow_root).build()

    assert digest.type_counts["decision"] == 1
    assert digest.type_counts["note"] == 1
    assert digest.days_covered == ["2026-07-01", "2026-07-02"]
    assert digest.event_count == 2


# -- noise filtering ---------------------------------------------------------


def test_short_snippets_are_ignored(store: EventStore, shadow_root: Path) -> None:
    """OCR fragments like a single button label aren't statements worth keeping."""
    store.insert_event(_event("Submit", EventType.DECISION))

    digest = _bank(store, shadow_root).build()

    assert digest.decisions == []


def test_snippets_with_too_few_words_are_ignored(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("x1 y2 z3 >>> ||| ~~~ 12345 6789", EventType.DECISION))

    digest = _bank(store, shadow_root).build()

    assert digest.decisions == []


def test_long_snippets_are_truncated(store: EventStore, shadow_root: Path) -> None:
    """A whole wall of transcript shouldn't monopolise the digest."""
    long_text = "We decided that " + "the reporting service should own aggregation. " * 60
    store.insert_event(_event(long_text, EventType.DECISION))

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == 1
    assert len(digest.decisions[0].text) <= 400
    assert digest.decisions[0].text.startswith("We decided that")


def test_repeated_ocr_of_the_same_text_is_deduplicated(store: EventStore, shadow_root: Path) -> None:
    """Screen OCR re-captures the same visible text on every change, so the same
    sentence can arrive dozens of times."""
    for index in range(8):
        store.insert_event(
            _event(
                "We decided to cache the catalogue responses for five minutes.",
                EventType.DECISION,
                when=f"2026-07-0{index + 1}T10:00:00",
            )
        )

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == 1


# -- incremental updates -----------------------------------------------------


def test_second_build_processes_only_new_events(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("First decision about the schema design.", EventType.DECISION,
                              when="2026-07-01T10:00:00"))
    bank = _bank(store, shadow_root)
    first = bank.build()
    assert first.event_count == 1

    store.insert_event(_event("Second decision about the queue topology.", EventType.DECISION,
                              when="2026-07-02T10:00:00"))
    second = bank.build()

    assert second.event_count == 2, "counts accumulate rather than being recomputed"
    assert len(second.decisions) == 2


def test_rebuild_with_no_new_events_is_a_noop(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("A decision worth remembering about retries.", EventType.DECISION))
    bank = _bank(store, shadow_root)
    first = bank.build()

    second = bank.build()

    assert second.event_count == first.event_count
    assert len(second.decisions) == len(first.decisions)


def test_watermark_advances_to_the_newest_event(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("Decision one about the caching layer.", EventType.DECISION,
                              when="2026-07-01T10:00:00"))
    store.insert_event(_event("Decision two about the retry policy.", EventType.DECISION,
                              when="2026-07-05T10:00:00"))

    digest = _bank(store, shadow_root).build()

    assert digest.last_event_timestamp == "2026-07-05T10:00:00"


def test_force_full_reprocesses_everything(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("A decision about the deployment pipeline.", EventType.DECISION))
    bank = _bank(store, shadow_root)
    bank.build()

    rebuilt = bank.build(force_full=True)

    assert rebuilt.event_count == 1, "a full rebuild counts from scratch, not additively"


def test_sections_are_capped(store: EventStore, shadow_root: Path) -> None:
    """The digest is prompt material, so it stays bounded however long capture runs."""
    for index in range(MAX_PER_SECTION + 25):
        store.insert_event(
            _event(
                f"We decided item number {index} about the reporting pipeline design.",
                EventType.DECISION,
                when=f"2026-07-01T10:{index % 60:02d}:00",
            )
        )

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == MAX_PER_SECTION


def test_glossary_is_capped(store: EventStore, shadow_root: Path) -> None:
    words = " ".join(f"ServiceName{index}Thing" for index in range(MAX_GLOSSARY_TERMS + 40))
    store.insert_event(_event(words))

    digest = _bank(store, shadow_root).build()

    assert len(digest.glossary) <= MAX_GLOSSARY_TERMS


# -- status ------------------------------------------------------------------


def test_status_progresses_missing_ready_stale(store: EventStore, shadow_root: Path) -> None:
    bank = _bank(store, shadow_root)
    assert bank.status() == "missing"

    store.insert_event(_event("A decision about the migration order.", EventType.DECISION,
                              when="2026-07-01T10:00:00"))
    bank.build()
    assert bank.status() == "ready"

    store.insert_event(_event("A later decision about rollback.", EventType.DECISION,
                              when="2026-07-09T10:00:00"))
    assert bank.status() == "stale"


def test_persisted_digest_round_trips(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("We decided to split the monolith by bounded context.",
                              EventType.DECISION))
    bank = _bank(store, shadow_root)
    bank.build()

    reloaded = GeneralKnowledgeBank(store, shadow_root).load()

    assert reloaded.event_count == 1
    assert "bounded context" in reloaded.decisions[0].text


# -- rendering / context -----------------------------------------------------


def test_render_includes_sections_with_labels(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("We decided to adopt trunk-based development.", EventType.DECISION))
    store.insert_event(_event("Action item: document the release process properly.", EventType.TASK))
    digest = _bank(store, shadow_root).build()

    text = render_digest(digest)

    assert "[decisions]" in text and "trunk-based" in text
    assert "[action items]" in text


def test_render_respects_a_budget(store: EventStore, shadow_root: Path) -> None:
    for index in range(30):
        store.insert_event(
            _event(f"We decided thing {index} about the ingestion pipeline design.",
                   EventType.DECISION, when=f"2026-07-01T10:{index:02d}:00")
        )
    digest = _bank(store, shadow_root).build()

    assert len(render_digest(digest, max_chars=300)) <= 300


def test_render_is_empty_for_an_empty_digest(store: EventStore, shadow_root: Path) -> None:
    from assistant.knowledge.general import GeneralDigest

    assert render_digest(GeneralDigest()) == ""


def test_context_floats_question_relevant_items_first(store: EventStore, shadow_root: Path) -> None:
    """A question about payments should surface the payment decision, not just
    whichever decision happened to be most recent."""
    store.insert_event(_event("We decided to rewrite the payment retry handler.",
                              EventType.DECISION, when="2026-07-01T10:00:00"))
    store.insert_event(_event("We decided to change the sidebar navigation colours.",
                              EventType.DECISION, when="2026-07-09T10:00:00"))
    _bank(store, shadow_root).build()

    text = assemble_general_context(store, "payment retry", shadow_root=shadow_root)

    payment_at = text.index("payment retry handler")
    sidebar_at = text.index("sidebar navigation")
    assert payment_at < sidebar_at


def test_context_defaults_to_recency_without_a_question(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("We decided the older thing about logging levels.",
                              EventType.DECISION, when="2026-07-01T10:00:00"))
    store.insert_event(_event("We decided the newer thing about tracing spans.",
                              EventType.DECISION, when="2026-07-09T10:00:00"))
    _bank(store, shadow_root).build()

    text = assemble_general_context(store, shadow_root=shadow_root)

    assert text.index("newer thing") < text.index("older thing")


def test_context_is_empty_before_the_bank_is_built(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("Something was decided about the API gateway.", EventType.DECISION))

    assert assemble_general_context(store, "api", shadow_root=shadow_root) == ""


def test_reordering_does_not_mutate_the_stored_digest(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("We decided the older thing about logging levels.",
                              EventType.DECISION, when="2026-07-01T10:00:00"))
    store.insert_event(_event("We decided the newer thing about tracing spans.",
                              EventType.DECISION, when="2026-07-09T10:00:00"))
    bank = _bank(store, shadow_root)
    bank.build()

    assemble_general_context(store, "logging levels", shadow_root=shadow_root)

    assert "newer thing" in bank.load().decisions[0].text, "stored order stays newest-first"


def test_near_duplicate_ocr_captures_are_deduplicated(store: EventStore, shadow_root: Path) -> None:
    """Real screen OCR of the same window differs only in its tail — a clock, a
    badge count — so exact-match de-duplication lets copies through."""
    base = "Innovation Hour PROJ team presenting the quarterly roadmap discussion notes"
    for index, tail in enumerate(("10:24 PM", "10:25 PM", "10:26 PM extra")):
        store.insert_event(
            _event(f"{base} {tail}", EventType.TASK, when=f"2026-07-24T10:2{index}:00")
        )

    digest = _bank(store, shadow_root).build()

    assert len(digest.action_items) == 1


def test_genuinely_different_items_are_kept(store: EventStore, shadow_root: Path) -> None:
    store.insert_event(_event("Action item: rewrite the billing reconciliation job.",
                              EventType.TASK, when="2026-07-01T10:00:00"))
    store.insert_event(_event("Action item: document the deployment rollback steps.",
                              EventType.TASK, when="2026-07-02T10:00:00"))

    digest = _bank(store, shadow_root).build()

    assert len(digest.action_items) == 2


def test_dedupe_keeps_items_differing_only_by_a_number(store: EventStore, shadow_root: Path) -> None:
    """Digits are significant: PROJ-1139 and PROJ-1140 are different tickets, and
    "raise the timeout to 30s" is a different decision from "to 60s"."""
    store.insert_event(_event("We decided to raise the request timeout to 30 seconds for now.",
                              EventType.DECISION, when="2026-07-01T10:00:00"))
    store.insert_event(_event("We decided to raise the request timeout to 60 seconds for now.",
                              EventType.DECISION, when="2026-07-02T10:00:00"))

    digest = _bank(store, shadow_root).build()

    assert len(digest.decisions) == 2
