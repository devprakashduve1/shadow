import json

from events.schema import Event, EventType, Severity


def _make_event(**overrides):
    defaults = dict(
        timestamp="2026-07-20T10:05:00",
        type=EventType.ERROR,
        title="Payment API Timeout",
        application="VSCode",
        severity=Severity.HIGH,
        source="ocr",
        content="TimeoutException...",
        entities=["PaymentService", "Checkout"],
        tags=["decision"],
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_round_trips_through_dict():
    event = _make_event()
    restored = Event.from_dict(event.to_dict())

    assert restored.type == event.type
    assert restored.severity == event.severity
    assert restored.entities == event.entities
    assert restored.tags == event.tags
    assert restored.content == event.content


def test_to_dict_is_json_serializable():
    event = _make_event()
    # This is what database/json_store.py actually does when appending to
    # events.jsonl — round-tripping through json.dumps/loads must work as-is.
    restored = Event.from_dict(json.loads(json.dumps(event.to_dict())))
    assert restored == event


def test_when_parses_timestamp():
    event = _make_event()
    assert event.when.hour == 10
    assert event.when.minute == 5


def test_empty_entities_and_tags_round_trip():
    event = _make_event(entities=[], tags=[])
    restored = Event.from_dict(event.to_dict())
    assert restored.entities == []
    assert restored.tags == []
