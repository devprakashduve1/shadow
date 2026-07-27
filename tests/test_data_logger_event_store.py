from database.json_store import EventStore
from events.schema import EventType
from logger.data_logger import DataLogger


def test_data_logger_without_event_store_is_unaffected(tmp_path):
    logger = DataLogger(base_dir=str(tmp_path / "logs"))
    entry = logger.log_ocr("hello world", extra={"title": "Notes"})
    assert entry is not None
    assert entry.text == "hello world"


def test_data_logger_with_event_store_inserts_classified_event(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    logger = DataLogger(base_dir=str(tmp_path / "logs"), event_store=store)

    logger.log_ocr(
        "Traceback (most recent call last):\nValueError: boom",
        extra={"title": "VSCode"},
    )

    events = store.query_events(limit=10)
    assert len(events) == 1
    assert events[0].type == EventType.ERROR
    assert events[0].source == "screen_ocr"


def test_data_logger_redacts_secrets_before_storing_event(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    logger = DataLogger(base_dir=str(tmp_path / "logs"), event_store=store)

    secret_text = "api_key=sk-abcdefghijklmnopqrstuvwx12345"
    logger.log_ocr(secret_text, extra={"title": "Terminal"})

    events = store.query_events(limit=10)
    assert len(events) == 1
    assert "sk-abcdefghijklmnopqrstuvwx12345" not in events[0].content

    # The raw JSONL log is untouched by redaction — only the structured
    # events.jsonl file is (see events/redaction.py's docstring / the plan's
    # design decision to leave DataLogger's own log files as-is).
    raw_entries = list(logger.iter_entries())
    assert any(secret_text == e.text for e in raw_entries)


def test_data_logger_dedup_still_skips_before_event_store(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    logger = DataLogger(base_dir=str(tmp_path / "logs"), event_store=store)

    logger.log_ocr("same text", extra={"title": "Notes"})
    result = logger.log_ocr("same text", extra={"title": "Notes"})  # duplicate, skipped

    assert result is None
    events = store.query_events(limit=10)
    assert len(events) == 1  # duplicate never reached the event store either
