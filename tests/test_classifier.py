from events.classifier import classify
from events.schema import EventType, Severity


def test_python_traceback_is_error():
    text = "Traceback (most recent call last):\nValueError: boom"
    result = classify(text, channel="screen", application="VSCode")
    assert result.type == EventType.ERROR


def test_rust_panic_is_high_severity_error():
    text = "thread 'main' panicked at src/main.rs:10:5:"
    result = classify(text, channel="screen", application="Terminal")
    assert result.type == EventType.ERROR
    assert result.severity == Severity.HIGH


def test_node_build_failure_is_error():
    result = classify("npm ERR! code ELIFECYCLE", channel="screen", application="Terminal")
    assert result.type == EventType.ERROR


def test_speech_channel_defaults_to_meeting():
    result = classify("let's sync again tomorrow", channel="speech", application="")
    assert result.type == EventType.MEETING


def test_decision_keyword_tagged_and_typed_outside_speech():
    result = classify("We decided to ship on Friday", channel="screen", application="Notes")
    assert result.type == EventType.DECISION
    assert "decision" in result.tags


def test_decision_keyword_layered_as_tag_within_meeting():
    result = classify("We decided to ship on Friday", channel="speech", application="")
    assert result.type == EventType.MEETING
    assert "decision" in result.tags


def test_task_keyword_is_task_type():
    result = classify("TODO: fix the retry logic", channel="screen", application="VSCode")
    assert result.type == EventType.TASK
    assert "task" in result.tags


def test_url_is_website():
    result = classify("Check https://example.com/docs", channel="screen", application="Google Chrome")
    assert result.type == EventType.WEBSITE
    assert "example.com" in result.entities


def test_code_editor_with_code_symbols():
    text = "def handle_request():\n    return {}\nclass Foo:\n    pass"
    result = classify(text, channel="screen", application="VSCode")
    assert result.type == EventType.CODE


def test_fallback_is_note():
    result = classify("just some ordinary screen text", channel="screen", application="Preview")
    assert result.type == EventType.NOTE
