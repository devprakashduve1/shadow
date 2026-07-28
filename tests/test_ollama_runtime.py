"""Tests for model residency: pinning via keep_alive, and unloading.

Ollama isn't contacted — `urlopen` is stubbed — so these assert on the exact
request payloads, which is where the keep_alive semantics live (negative keeps a
model loaded, 0 evicts it, and getting the sign wrong silently reverts to
Ollama's own idle eviction).
"""
from __future__ import annotations

import json
import time
from io import BytesIO

import pytest

from assistant import ollama_runtime
from assistant.ollama_runtime import LoadedModel, loaded_models, unload_all, unload_model
from assistant.streaming import (
    KEEP_ALIVE_OLLAMA_DEFAULT,
    KEEP_ALIVE_PINNED,
    KEEP_ALIVE_UNLOAD,
    AssistantError,
    resolve_keep_alive,
    stream_chat,
)


class _FakeResponse(BytesIO):
    """Enough of an HTTP response for urlopen's context-manager usage."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Captured:
    """Records outgoing requests and serves a settable canned body."""

    def __init__(self):
        self.calls = []
        self._body = b"{}"

    def set_body(self, body) -> None:
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def urlopen(self, request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        payload = None
        if not isinstance(request, str) and request.data:
            payload = json.loads(request.data.decode("utf-8"))
        self.calls.append({"url": url, "payload": payload, "timeout": timeout})
        return _FakeResponse(self._body)

    @property
    def payloads(self):
        return [c["payload"] for c in self.calls]


@pytest.fixture
def captured(monkeypatch) -> _Captured:
    cap = _Captured()
    monkeypatch.setattr("assistant.ollama_runtime.urllib.request.urlopen", cap.urlopen)
    monkeypatch.setattr("assistant.streaming.urllib.request.urlopen", cap.urlopen)
    return cap


# -- pinning -----------------------------------------------------------------


def test_keep_alive_constants_carry_ollamas_semantics() -> None:
    """Negative means never evict; zero means evict now. A positive number here
    would quietly reintroduce the reload-every-few-minutes behaviour."""
    assert KEEP_ALIVE_PINNED < 0
    assert KEEP_ALIVE_UNLOAD == 0


def test_stream_chat_pins_the_model_by_default(captured) -> None:
    captured.set_body(b'{"response": "hi", "done": true}\n')

    list(stream_chat("hello", model="gemma4"))

    payload = captured.payloads[0]
    assert payload["keep_alive"] == KEEP_ALIVE_PINNED


def test_stream_chat_honours_an_explicit_keep_alive(captured) -> None:
    captured.set_body(b'{"response": "hi", "done": true}\n')

    list(stream_chat("hello", keep_alive="10m"))

    assert captured.payloads[0]["keep_alive"] == "10m"


def test_stream_chat_still_sends_the_other_fields(captured) -> None:
    """Guards against the keep_alive addition displacing existing behaviour."""
    captured.set_body(b'{"response": "hi", "done": true}\n')

    list(stream_chat("a prompt", model="qwen3.6"))

    payload = captured.payloads[0]
    assert payload["model"] == "qwen3.6"
    assert payload["prompt"] == "a prompt"
    assert payload["stream"] is True
    assert payload["think"] is False


def test_config_can_restore_ollamas_idle_eviction(monkeypatch) -> None:
    monkeypatch.setattr("config.settings.get", lambda key, default=None: False)

    assert resolve_keep_alive() == KEEP_ALIVE_OLLAMA_DEFAULT


def test_config_defaults_to_pinned(monkeypatch) -> None:
    monkeypatch.setattr("config.settings.get", lambda key, default=None: default)

    assert resolve_keep_alive() == KEEP_ALIVE_PINNED


# -- unloading ---------------------------------------------------------------


def test_unload_sends_keep_alive_zero(captured) -> None:
    unload_model("gemma4")

    payload = captured.payloads[0]
    assert payload["keep_alive"] == KEEP_ALIVE_UNLOAD
    assert payload["model"] == "gemma4"


def test_unload_generates_nothing(captured) -> None:
    """An empty prompt is what makes this an eviction rather than a request."""
    unload_model("gemma4")

    payload = captured.payloads[0]
    assert payload["prompt"] == ""
    assert payload["stream"] is False


def test_unload_hits_the_generate_endpoint(captured) -> None:
    unload_model("gemma4", base_url="http://localhost:11434/")

    # Trailing slash in the base URL must not double up.
    assert captured.calls[0]["url"] == "http://localhost:11434/api/generate"


def test_unloading_nothing_makes_no_request(captured) -> None:
    unload_model("")

    assert captured.calls == []


# -- residency query ---------------------------------------------------------


def test_loaded_models_parses_the_ps_response(captured) -> None:
    captured.set_body(
        {"models": [{"name": "gemma4", "size": 9_600_000_000, "expires_at": "2030-01-01"}]}
    )

    models = loaded_models()

    assert models == [
        LoadedModel(name="gemma4", size_bytes=9_600_000_000, expires_at="2030-01-01")
    ]


def test_nothing_loaded_is_not_an_error(captured) -> None:
    """An idle-but-reachable Ollama reports an empty list."""
    captured.set_body({"models": []})

    assert loaded_models() == []


def test_loaded_models_accepts_either_name_field(captured) -> None:
    """Which of `name`/`model` is populated has varied between Ollama versions."""
    captured.set_body({"models": [{"model": "qwen3.6"}]})

    assert [m.name for m in loaded_models()] == ["qwen3.6"]


def test_entries_without_a_name_are_skipped(captured) -> None:
    captured.set_body({"models": [{"size": 1}, {"name": "ok"}]})

    assert [m.name for m in loaded_models()] == ["ok"]


def test_a_missing_models_key_is_tolerated(captured) -> None:
    captured.set_body({})

    assert loaded_models() == []


def test_size_label_is_human_readable() -> None:
    assert LoadedModel("m", size_bytes=9_600_000_000).size_label == "9.6GB"
    assert LoadedModel("m", size_bytes=0).size_label == ""


# -- unload_all --------------------------------------------------------------


def test_unload_all_releases_every_resident_model(captured, monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_runtime,
        "loaded_models",
        lambda *a, **k: [LoadedModel("gemma4"), LoadedModel("qwen3.6")],
    )

    released = unload_all(confirm_seconds=0)

    assert released == ["gemma4", "qwen3.6"]
    assert [p["model"] for p in captured.payloads] == ["gemma4", "qwen3.6"]


def test_unload_all_can_target_one_model(captured, monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_runtime,
        "loaded_models",
        lambda *a, **k: [LoadedModel("gemma4"), LoadedModel("qwen3.6")],
    )

    assert unload_all(only="qwen3.6", confirm_seconds=0) == ["qwen3.6"]


def test_unload_all_with_nothing_loaded_reports_nothing(captured, monkeypatch) -> None:
    """The caller distinguishes "freed nothing" from "failed", so this must not
    raise just because the model was already evicted."""
    monkeypatch.setattr(ollama_runtime, "loaded_models", lambda *a, **k: [])

    assert unload_all() == []


def test_unload_all_waits_for_the_eviction_to_take_effect(captured, monkeypatch) -> None:
    """Ollama accepts an eviction and returns ~200ms before the model is really
    gone, so without this wait the memory isn't free yet on return."""
    residency = [
        [LoadedModel("gemma4")],  # the initial survey
        [LoadedModel("gemma4")],  # still resident on the first confirm poll
        [],                       # evicted
    ]
    monkeypatch.setattr(
        ollama_runtime, "loaded_models", lambda *a, **k: residency.pop(0) if residency else []
    )

    assert unload_all(confirm_seconds=3.0) == ["gemma4"]
    assert residency == [], "should have polled until the model was gone"


def test_the_confirmation_wait_is_bounded(captured, monkeypatch) -> None:
    """A server that never releases must not hang the GUI thread's worker."""
    monkeypatch.setattr(
        ollama_runtime, "loaded_models", lambda *a, **k: [LoadedModel("stuck")]
    )

    started = time.monotonic()
    assert unload_all(confirm_seconds=0.3) == ["stuck"]
    assert time.monotonic() - started < 2.0


# -- errors ------------------------------------------------------------------


def test_an_unreachable_ollama_raises_a_clear_error(monkeypatch) -> None:
    import urllib.error

    def _boom(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("assistant.ollama_runtime.urllib.request.urlopen", _boom)

    with pytest.raises(AssistantError, match="ollama serve"):
        loaded_models()
