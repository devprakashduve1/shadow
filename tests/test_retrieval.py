from datetime import datetime, timedelta

from assistant.manual_projects import ManualProjectRegistry
from assistant.retrieval import retrieve, retrieve_for_project
from database.json_store import EventStore
from events.schema import Event, EventType, Severity


def _insert(store, timestamp, content, event_type=EventType.NOTE, title="", entities=None):
    store.insert_event(
        Event(
            timestamp=timestamp,
            type=event_type,
            title=title,
            application="",
            severity=Severity.LOW,
            source="ocr",
            content=content,
            entities=entities or [],
        )
    )


def test_retrieve_filters_by_keyword(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    now = datetime.now()
    _insert(store, now.isoformat(), "fixed the payment timeout bug")
    _insert(store, now.isoformat(), "watched a random youtube video")

    context, matched = retrieve(store, "what happened with payment?")
    assert "payment" in context
    assert all("payment" in e.content for e in matched)


def test_retrieve_falls_back_to_recent_when_no_keyword_matches(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    now = datetime.now()
    _insert(store, now.isoformat(), "something entirely unrelated")

    context, matched = retrieve(store, "gibberish query xyzzyplugh")
    assert matched  # falls back rather than returning nothing


def test_retrieve_excludes_events_outside_window(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    old = datetime.now() - timedelta(days=30)
    _insert(store, old.isoformat(), "ancient history event")

    context, matched = retrieve(store, "ancient history", retrieval_days=7)
    assert matched == []
    assert context == ""


def test_retrieve_respects_char_budget(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    now = datetime.now()
    for i in range(20):
        _insert(store, (now - timedelta(minutes=i)).isoformat(), f"event number {i} " * 50)

    full_context, full_matched = retrieve(store, "event", max_chars=1_000_000)
    limited_context, limited_matched = retrieve(store, "event", max_chars=500)

    assert len(limited_context) < len(full_context)
    assert len(limited_matched) < len(full_matched)


def test_retrieve_for_project_only_returns_matching_events(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    now = datetime.now()
    _insert(store, now.isoformat(), "Bug PROJ-1139: generic error message")
    _insert(store, now.isoformat(), "unrelated note about lunch")

    context, matched = retrieve_for_project(store, "PROJ")
    assert len(matched) == 1
    assert "PROJ-1139" in context
    assert "lunch" not in context


def test_retrieve_for_project_works_without_precomputed_entities(tmp_path):
    # Regression test: detection re-extracts from `content` live rather than
    # trusting `event.entities` — this is what makes it work for events
    # captured before project-key tagging existed (entities=[] on old data).
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, datetime.now().isoformat(), "Bug PROJ-1139: generic error message", entities=[])

    context, matched = retrieve_for_project(store, "PROJ")
    assert len(matched) == 1
    assert "PROJ-1139" in context


def test_retrieve_for_project_ignores_recency_window(tmp_path):
    # Unlike retrieve(), there's no retrieval_days cutoff — old project
    # history is still in scope, budget permitting.
    store = EventStore(base_dir=tmp_path / "events")
    old = datetime.now() - timedelta(days=180)
    _insert(store, old.isoformat(), "very old PROJ-1 decision")

    context, matched = retrieve_for_project(store, "PROJ")
    assert len(matched) == 1
    assert "very old" in context


def test_retrieve_for_project_returns_empty_for_unknown_project(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, datetime.now().isoformat(), "Bug PROJ-1139")

    context, matched = retrieve_for_project(store, "NOPE")
    assert matched == []
    assert context == ""


def test_retrieve_for_project_includes_date_in_context_lines(tmp_path):
    # No recency window means "at 10:05" alone would be ambiguous across
    # days — the project-scoped context always includes the date.
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:05:00", "PROJ-1 filed")

    context, _ = retrieve_for_project(store, "PROJ")
    assert "2026-07-20" in context


def test_retrieve_for_project_matches_manually_browsed_folder(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, datetime.now().isoformat(), "fixed a bug in the myrepo codebase")
    _insert(store, datetime.now().isoformat(), "unrelated note about lunch")

    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")

    context, matched = retrieve_for_project(store, "myrepo", manual_registry=registry)
    assert len(matched) == 1
    assert "myrepo" in context
    assert "lunch" not in context


def test_retrieve_for_project_matches_kebab_case_folder_against_title_case_text(tmp_path):
    # Regression test for the reported bug: browsing "user-profile-mfe"
    # found zero activity because captured Jira/Slack text says
    # "User Profile MFE" — different casing and separators entirely.
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, datetime.now().isoformat(), "[User Profile MFE] display generic error instead of crash")
    _insert(store, datetime.now().isoformat(), "unrelated note about lunch")

    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "user-profile-mfe")

    context, matched = retrieve_for_project(store, "user-profile-mfe", manual_registry=registry)
    assert len(matched) == 1
    assert "User Profile MFE" in context


def test_retrieve_for_project_without_manual_registry_ignores_folder_names(tmp_path):
    # If no manual_registry is passed, a name that isn't ticket-key-shaped
    # can never match — this is what proves the two matching modes are
    # actually distinct rather than one silently subsuming the other.
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, datetime.now().isoformat(), "fixed a bug in the myrepo codebase")

    context, matched = retrieve_for_project(store, "myrepo")
    assert matched == []
    assert context == ""
