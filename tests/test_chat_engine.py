import io
import json
import urllib.error
from datetime import datetime
from unittest import mock

from assistant.chat_engine import ChatEngine, _parse_questions
from assistant.manual_projects import ManualProjectRegistry
from database.json_store import EventStore
from events.schema import Event, EventType, Severity


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _ndjson(*objs) -> bytes:
    return b"".join((json.dumps(o) + "\n").encode("utf-8") for o in objs)


def _insert(store, content, event_type=EventType.NOTE, title="", entities=None):
    store.insert_event(
        Event(
            timestamp=datetime.now().isoformat(),
            type=event_type,
            title=title,
            application="",
            severity=Severity.LOW,
            source="ocr",
            content=content,
            entities=entities or [],
        )
    )


def test_parse_questions_strips_markers_and_discards_non_questions():
    text = (
        "Sure! Here are some questions:\n"
        "1. What did Priya ask about the migration?\n"
        "2) What was the error in payment-service around 2pm?\n"
        "- What decisions were made in the huddle with Vinod?\n"
        "Hope that helps!"
    )
    assert _parse_questions(text) == [
        "What did Priya ask about the migration?",
        "What was the error in payment-service around 2pm?",
        "What decisions were made in the huddle with Vinod?",
    ]


def test_parse_questions_dedupes_and_respects_limit():
    text = "\n".join([f"What is fact {i}?" for i in range(3)] + ["What is fact 0?"])
    assert _parse_questions(text, limit=2) == ["What is fact 0?", "What is fact 1?"]


def test_parse_questions_returns_empty_for_no_questions():
    assert _parse_questions("Nothing here ends in a question mark.") == []


def test_suggested_questions_with_no_events_uses_fallback_without_calling_ollama(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    engine = ChatEngine(store)

    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("should not be called")):
        questions = engine.suggested_questions(today="2026-07-21")

    assert questions  # falls back to the default templates
    assert "What did I work on today?" in questions


def test_suggested_questions_grounded_in_todays_events(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Payment API timeout in checkout.py around 2pm", event_type=EventType.ERROR)
    _insert(store, "Priya asked about the migration ticket status", event_type=EventType.MEETING)

    body = _ndjson(
        {"response": "What was the payment timeout error around 2pm?\n", "done": False},
        {"response": "What did Priya ask about the migration?\n", "done": True},
    )
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)) as urlopen:
        questions = engine.suggested_questions(today="2026-07-21")
        urlopen.assert_called_once()

    assert questions == [
        "What was the payment timeout error around 2pm?",
        "What did Priya ask about the migration?",
    ]


def test_suggested_questions_cached_after_first_generation(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Payment API timeout in checkout.py around 2pm", event_type=EventType.ERROR)

    body = _ndjson({"response": "What was the payment timeout error?", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")

    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)) as urlopen:
        first = engine.suggested_questions(today="2026-07-21")
        second = engine.suggested_questions(today="2026-07-21")
        urlopen.assert_called_once()  # second call hit the per-day cache, no new Ollama request

    assert first == second


def test_suggested_questions_falls_back_when_ollama_unreachable(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Traceback (most recent call last):\nValueError: boom", event_type=EventType.ERROR)

    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        questions = engine.suggested_questions(today="2026-07-21")

    assert "What bugs appeared today?" in questions


def test_suggested_questions_falls_back_when_model_output_unparseable(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Some meeting notes", event_type=EventType.MEETING)

    body = _ndjson({"response": "I have nothing to suggest today.", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        questions = engine.suggested_questions(today="2026-07-21")

    assert "What meetings need follow-up?" in questions


def test_ask_without_project_uses_default_history_thread(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "fixed the payment timeout bug")

    body = _ndjson({"response": "You fixed a timeout bug.", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        answer = "".join(engine.ask("what did I work on?"))

    assert answer == "You fixed a timeout bug."
    assert store.get_history(thread="default")  # recorded in the default thread
    assert store.get_history(thread="project:PROJ") == []  # not leaked into a project thread


def test_ask_with_project_scopes_context_and_history(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Bug PROJ-1139: generic error message")
    _insert(store, "unrelated note about lunch")

    body = _ndjson({"response": "PROJ-1139 is about a generic error message.", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        answer = "".join(engine.ask("what is this about?", project="PROJ"))

    assert answer == "PROJ-1139 is about a generic error message."
    assert len(engine.last_citations) == 1
    assert "PROJ-1139" in engine.last_citations[0]["snippet"]

    # History for this project-scoped exchange is kept separate from the main
    # Assistant tab's default thread.
    assert store.get_history(thread="default") == []
    project_history = store.get_history(thread="project:PROJ")
    assert [h["role"] for h in project_history] == ["user", "assistant"]


def test_ask_different_projects_have_independent_history(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "Bug PROJ-1139")
    _insert(store, "Bug PLAT-204")

    body = _ndjson({"response": "ok", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    # A fresh _FakeResponse per call — reusing one BytesIO across both ask()
    # calls would exhaust it after the first, since urlopen is mocked to
    # return the same object every time otherwise.
    with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **kw: _FakeResponse(body)):
        list(engine.ask("about PROJ?", project="PROJ"))
        list(engine.ask("about PLAT?", project="PLAT"))

    vogs_history = store.get_history(thread="project:PROJ")
    wln_history = store.get_history(thread="project:PLAT")
    assert vogs_history[0]["content"] == "about PROJ?"
    assert wln_history[0]["content"] == "about PLAT?"


def test_ask_with_manually_browsed_project(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    _insert(store, "fixed a bug in the myrepo codebase")
    _insert(store, "unrelated note about lunch")

    registry = ManualProjectRegistry(store.base_dir / "manual_projects.json")
    registry.add(tmp_path / "myrepo")

    body = _ndjson({"response": "You fixed a bug.", "done": True})
    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        answer = "".join(engine.ask("what did I fix?", project="myrepo"))

    assert answer == "You fixed a bug."
    assert len(engine.last_citations) == 1
    assert "myrepo" in engine.last_citations[0]["snippet"]
    assert store.get_history(thread="project:myrepo")


def test_new_session_clears_default_thread_only(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "old default question")
    store.append_history("user", "old PROJ question", thread="project:PROJ")

    engine = ChatEngine(store)
    engine.last_citations = [{"source": "ocr"}]
    engine.new_session()

    assert store.get_history() == []
    assert store.get_history(thread="project:PROJ")  # untouched
    assert engine.last_citations == []


def test_new_session_with_project_clears_only_that_projects_thread(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "old default question")
    store.append_history("user", "old PROJ question", thread="project:PROJ")
    store.append_history("user", "old PLAT question", thread="project:PLAT")

    engine = ChatEngine(store)
    engine.new_session(project="PROJ")

    assert store.get_history(thread="project:PROJ") == []
    assert store.get_history()  # default thread untouched
    assert store.get_history(thread="project:PLAT")  # other project untouched


def test_new_session_lets_a_fresh_conversation_start_without_old_history(tmp_path):
    store = EventStore(base_dir=tmp_path / "events")
    store.append_history("user", "old question")
    store.append_history("assistant", "old answer")

    engine = ChatEngine(store, base_url="http://fake", model="gemma4")
    engine.new_session()

    body = _ndjson({"response": "brand new answer", "done": True})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)) as urlopen:
        "".join(engine.ask("a new question"))
        sent_request = urlopen.call_args.args[0]
        prompt_sent = json.loads(sent_request.data)["prompt"]

    assert "old question" not in prompt_sent
    assert "old answer" not in prompt_sent
