from database.json_store import EventStore
from events.schema import Event, EventType, Severity


def _make_event(timestamp, **overrides):
    defaults = dict(
        timestamp=timestamp,
        type=EventType.ERROR,
        title="Payment API Timeout",
        application="VSCode",
        severity=Severity.HIGH,
        source="ocr",
        content="TimeoutException in checkout",
        entities=["Checkout"],
        tags=[],
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_insert_and_query_round_trip(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.insert_event(_make_event("2026-07-20T10:00:00"))

    results = store.query_events(limit=10)
    assert len(results) == 1
    assert results[0].content == "TimeoutException in checkout"
    assert results[0].type == EventType.ERROR


def test_events_are_partitioned_into_a_daily_jsonl_file(tmp_path):
    base_dir = tmp_path / "events"
    store = EventStore(base_dir=base_dir)
    store.insert_event(_make_event("2026-07-20T10:00:00"))

    events_file = base_dir / "2026-07-20" / "events.jsonl"
    assert events_file.exists()
    assert events_file.read_text().strip().count("\n") == 0  # exactly one line


def test_query_events_filters_by_keyword(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.insert_event(_make_event("2026-07-20T10:00:00", content="checkout timeout"))
    store.insert_event(_make_event("2026-07-20T11:00:00", content="unrelated meeting notes", type=EventType.MEETING))

    results = store.query_events(keyword="checkout")
    assert len(results) == 1
    assert "checkout" in results[0].content


def test_query_events_filters_by_type_and_orders_newest_first(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.insert_event(_make_event("2026-07-20T09:00:00"))
    store.insert_event(_make_event("2026-07-20T12:00:00"))

    results = store.query_events(event_type=EventType.ERROR)
    assert len(results) == 2
    assert results[0].timestamp == "2026-07-20T12:00:00"  # newest first


def test_recent_events_respects_window(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.insert_event(_make_event("2000-01-01T00:00:00"))  # far in the past
    recent = store.recent_events(within_hours=24)
    assert recent == []


def test_assistant_history_round_trip(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "what did I work on today?")
    store.append_history("assistant", "You fixed a timeout bug.", citations=[{"source": "ocr"}])

    history = store.get_history()
    assert [h["role"] for h in history] == ["user", "assistant"]
    assert history[1]["citations"] == [{"source": "ocr"}]


def test_history_threads_stay_separate(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "what did I work on today?")  # default thread
    store.append_history("user", "what's up with PROJ?", thread="project:PROJ")
    store.append_history("user", "what's up with PLAT?", thread="project:PLAT")

    assert [h["content"] for h in store.get_history()] == ["what did I work on today?"]
    assert [h["content"] for h in store.get_history(thread="project:PROJ")] == ["what's up with PROJ?"]
    assert [h["content"] for h in store.get_history(thread="project:PLAT")] == ["what's up with PLAT?"]


def test_clear_history_removes_only_the_given_thread(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "default question")  # default thread
    store.append_history("user", "about PROJ", thread="project:PROJ")
    store.append_history("assistant", "PROJ answer", thread="project:PROJ")
    store.append_history("user", "about PLAT", thread="project:PLAT")

    store.clear_history(thread="project:PROJ")

    assert store.get_history(thread="project:PROJ") == []
    assert [h["content"] for h in store.get_history()] == ["default question"]
    assert [h["content"] for h in store.get_history(thread="project:PLAT")] == ["about PLAT"]


def test_clear_history_on_empty_file_is_a_no_op(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.clear_history()  # no assistant_history.jsonl exists yet — must not raise
    assert store.get_history() == []


def test_suggested_questions_cached_per_day(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    calls = []

    def generator():
        calls.append(1)
        return ["What did I work on today?"]

    first = store.get_or_generate_suggested_questions("2026-07-20", generator)
    second = store.get_or_generate_suggested_questions("2026-07-20", generator)

    assert first == second == ["What did I work on today?"]
    assert len(calls) == 1  # generator only invoked once, second call hit the cache
