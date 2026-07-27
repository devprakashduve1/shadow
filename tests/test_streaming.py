import io
import json
from unittest import mock

import pytest

from assistant.streaming import AssistantError, stream_chat


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for the object `urllib.request.urlopen` returns.

    `stream_chat` uses it both as a context manager and as a line iterator —
    `io.BytesIO` already supports iteration, this just adds `__enter__`/`__exit__`.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _ndjson(*objs) -> bytes:
    return b"".join((json.dumps(o) + "\n").encode("utf-8") for o in objs)


def test_stream_chat_yields_chunks_in_order():
    body = _ndjson({"response": "Hello ", "done": False}, {"response": "world!", "done": False}, {"response": "", "done": True})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        chunks = list(stream_chat("hi", base_url="http://fake", model="gemma4"))
    assert chunks == ["Hello ", "world!"]


def test_stream_chat_skips_blank_lines():
    body = b"\n" + _ndjson({"response": "ok", "done": True})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        chunks = list(stream_chat("hi", base_url="http://fake", model="gemma4"))
    assert chunks == ["ok"]


def test_stream_chat_raises_on_ollama_error_payload():
    body = _ndjson({"error": "model not found"})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        with pytest.raises(AssistantError, match="model not found"):
            list(stream_chat("hi", base_url="http://fake", model="gemma4"))


def test_stream_chat_raises_on_connection_error():
    import urllib.error

    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(AssistantError, match="ollama serve"):
            list(stream_chat("hi", base_url="http://fake", model="gemma4"))


def test_stream_chat_raises_on_empty_response():
    body = _ndjson({"response": "", "done": True})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        with pytest.raises(AssistantError, match="empty"):
            list(stream_chat("hi", base_url="http://fake", model="gemma4"))
