from database.json_store import EventStore
from events.schema import Event, EventType, Severity

from assistant.manual_projects import ManualProjectRegistry
from assistant.projects import list_projects


def _insert(store, timestamp, content, entities=None, event_type=EventType.NOTE):
    store.insert_event(
        Event(
            timestamp=timestamp,
            type=event_type,
            title="",
            application="",
            severity=Severity.LOW,
            source="ocr",
            content=content,
            entities=entities or [],
        )
    )


def test_list_projects_empty_when_no_ticket_keys(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:00:00", "no ticket keys here")
    assert list_projects(store) == []


def test_list_projects_detected_from_content_even_with_no_entities(tmp_path):
    # Regression test: events captured before project-key tagging existed
    # have entities=[] (the classifier version that wrote them didn't tag
    # anything), but their `content` already contains the ticket key. Project
    # detection must not depend on `entities` being populated.
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:00:00", "Bug PROJ-1139 in Jira Cloud", entities=[])

    projects = list_projects(store)
    assert [p.key for p in projects] == ["PROJ"]


def test_list_projects_aggregates_counts_and_dates(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T09:00:00", "Bug PROJ-1139")
    _insert(store, "2026-07-20T12:00:00", "Also PROJ-1192")
    _insert(store, "2026-07-20T11:00:00", "PLAT-204 filed")

    projects = {p.key: p for p in list_projects(store)}
    assert projects["PROJ"].event_count == 2
    assert projects["PROJ"].first_seen == "2026-07-20T09:00:00"
    assert projects["PROJ"].last_seen == "2026-07-20T12:00:00"
    assert projects["PLAT"].event_count == 1


def test_list_projects_orders_most_recent_first(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T09:00:00", "old PLAT-1")
    _insert(store, "2026-07-20T15:00:00", "recent PROJ-1")

    keys = [p.key for p in list_projects(store)]
    assert keys == ["PROJ", "PLAT"]


def test_list_projects_ignores_lowercase_prefix(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:00:00", "visited vogs-1139, not a real ticket")
    assert list_projects(store) == []


def test_list_projects_includes_manually_browsed_folder_with_no_activity(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")

    projects = list_projects(store, registry)
    assert len(projects) == 1
    assert projects[0].key == "myrepo"
    assert projects[0].event_count == 0
    assert projects[0].path == str(tmp_path / "myrepo")


def test_list_projects_matches_manual_project_by_name_in_content(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:00:00", "fixed a bug in the myrepo codebase")
    _insert(store, "2026-07-20T11:00:00", "unrelated note")

    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")

    projects = {p.key: p for p in list_projects(store, registry)}
    assert projects["myrepo"].event_count == 1


def test_list_projects_matches_manual_project_across_naming_variants(tmp_path):
    # Regression test: a kebab-case repo folder name ("user-profile-mfe")
    # rarely appears verbatim in captured Jira/Slack text, which is far more
    # likely to write it as "User Profile MFE" — different casing and
    # separators. Matching must not require an exact substring.
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T10:00:00", "[User Profile MFE] display generic error instead of crash")
    _insert(store, "2026-07-20T11:00:00", "unrelated note about lunch")

    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "user-profile-mfe")

    projects = {p.key: p for p in list_projects(store, registry)}
    assert projects["user-profile-mfe"].event_count == 1


def test_list_projects_ticket_key_and_manual_project_coexist(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "2026-07-20T09:00:00", "Bug PROJ-1139")
    _insert(store, "2026-07-20T10:00:00", "working in myrepo today")

    registry = ManualProjectRegistry(tmp_path / "manual_projects.json")
    registry.add(tmp_path / "myrepo")

    keys = {p.key for p in list_projects(store, registry)}
    assert keys == {"PROJ", "myrepo"}
