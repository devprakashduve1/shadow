"""Tests for assistant/ollama_models.py.

Network is faked by patching `urllib.request.urlopen`, matching the approach in
tests/test_coding_agent.py. The response shapes below are real output from
Ollama's `/api/tags`, including a cloud model entry.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from assistant.ollama_models import (
    FALLBACK_MODELS,
    PREFERRED_DEFAULT,
    ModelInfo,
    choose_default,
    list_models,
    model_names,
    normalize_name,
    resolve_choices,
)

# Trimmed from a real /api/tags response.
_TAGS_PAYLOAD = {
    "models": [
        {
            "name": "ornith:latest",
            "model": "ornith:latest",
            "modified_at": "2026-07-27T16:26:28Z",
            "size": 5629110568,
            "details": {
                "family": "qwen35",
                "parameter_size": "9.0B",
                "quantization_level": "Q4_K_M",
            },
            "capabilities": ["completion", "tools", "thinking"],
        },
        {
            "name": "qwen3.6:latest",
            "modified_at": "2026-07-23T18:58:33Z",
            "size": 23938333577,
            "details": {
                "family": "qwen35moe",
                "parameter_size": "36.0B",
                "quantization_level": "Q4_K_M",
            },
            "capabilities": ["vision", "completion", "tools", "thinking"],
        },
        {
            "name": "kimi-k2.6:cloud",
            "remote_model": "kimi-k2.6",
            "remote_host": "https://ollama.com:443",
            "modified_at": "2026-07-17T23:29:36Z",
            "size": 384,
            "details": {"family": "kimi-k2", "parameter_size": "1T"},
            "capabilities": ["completion", "thinking"],
        },
        {
            "name": "gemma4:latest",
            "modified_at": "2026-07-10T23:19:25Z",
            "size": 9608350718,
            "details": {
                "family": "gemma4",
                "parameter_size": "8.0B",
                "quantization_level": "Q4_K_M",
            },
            "capabilities": ["completion", "tools", "thinking"],
        },
    ]
}


class _FakeResponse:
    def __init__(self, payload, status: int = 200):
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        self._buffer = io.BytesIO(body.encode("utf-8") if isinstance(body, str) else body)

    def read(self):
        return self._buffer.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serving(payload=_TAGS_PAYLOAD):
    return lambda *_args, **_kwargs: _FakeResponse(payload)


def _unreachable(*_args, **_kwargs):
    import urllib.error

    raise urllib.error.URLError("connection refused")


# -- normalization -----------------------------------------------------------


def test_latest_tag_is_stripped() -> None:
    """Ollama treats `gemma4` and `gemma4:latest` as the same model, and the
    bare form is what config has always used."""
    assert normalize_name("gemma4:latest") == "gemma4"


def test_other_tags_are_preserved() -> None:
    assert normalize_name("qwen3.6:8b") == "qwen3.6:8b"


def test_untagged_name_is_unchanged() -> None:
    assert normalize_name("gemma4") == "gemma4"


# -- listing -----------------------------------------------------------------


def test_lists_installed_models() -> None:
    with patch("urllib.request.urlopen", _serving()):
        names = model_names()

    assert "gemma4" in names
    assert "qwen3.6" in names
    assert "ornith" in names


def test_cloud_models_are_excluded_by_default() -> None:
    """The privacy-relevant default: a model running on ollama.com would receive
    the user's source code, so it must be an explicit opt-in."""
    with patch("urllib.request.urlopen", _serving()):
        names = model_names()

    assert "kimi-k2.6:cloud" not in names


def test_cloud_models_appear_when_opted_in() -> None:
    with patch("urllib.request.urlopen", _serving()):
        models = list_models(include_remote=True)

    cloud = [m for m in models if m.is_remote]
    assert [m.name for m in cloud] == ["kimi-k2.6:cloud"]
    assert cloud[0].remote_host == "https://ollama.com:443"


def test_metadata_is_parsed() -> None:
    with patch("urllib.request.urlopen", _serving()):
        by_name = {m.name: m for m in list_models()}

    gemma = by_name["gemma4"]
    assert gemma.parameter_size == "8.0B"
    assert gemma.family == "gemma4"
    assert gemma.quantization == "Q4_K_M"
    assert gemma.size_bytes == 9608350718


def test_capabilities_are_exposed() -> None:
    with patch("urllib.request.urlopen", _serving()):
        by_name = {m.name: m for m in list_models()}

    assert by_name["qwen3.6"].supports_vision is True
    assert by_name["gemma4"].supports_vision is False
    # Every current model reports thinking; this is why stream_chat sends
    # think: false (see the empty-response failure it otherwise causes).
    assert by_name["qwen3.6"].supports_thinking is True


def test_models_are_sorted_newest_first() -> None:
    with patch("urllib.request.urlopen", _serving()):
        names = model_names()

    assert names[0] == "ornith", "most recently pulled should lead"
    assert names[-1] == "gemma4"


def test_entry_without_a_name_is_skipped() -> None:
    with patch("urllib.request.urlopen", _serving({"models": [{"size": 1}, {"name": "ok"}]})):
        assert model_names() == ["ok"]


def test_non_dict_entries_are_skipped() -> None:
    with patch("urllib.request.urlopen", _serving({"models": ["garbage", {"name": "ok"}]})):
        assert model_names() == ["ok"]


def test_empty_model_list_is_handled() -> None:
    with patch("urllib.request.urlopen", _serving({"models": []})):
        assert model_names() == []


def test_missing_models_key_is_handled() -> None:
    with patch("urllib.request.urlopen", _serving({})):
        assert model_names() == []


# -- failure modes -----------------------------------------------------------


def test_unreachable_ollama_returns_empty_rather_than_raising() -> None:
    """A missing model list is a UI inconvenience, not an error worth
    interrupting the user for."""
    with patch("urllib.request.urlopen", _unreachable):
        assert list_models() == []


def test_malformed_json_returns_empty() -> None:
    with patch("urllib.request.urlopen", _serving("{not json")):
        assert list_models() == []


# -- default selection -------------------------------------------------------


def test_default_is_gemma4_when_present() -> None:
    assert choose_default(["ornith", "qwen3.6", "gemma4"]) == "gemma4"


def test_default_matches_a_tagged_variant() -> None:
    """A configured `gemma4` should still match a pulled `gemma4:8b`."""
    assert choose_default(["qwen3.6", "gemma4:8b"]) == "gemma4:8b"


def test_default_falls_back_to_the_first_model() -> None:
    """Better than leaving nothing selected."""
    assert choose_default(["ornith", "qwen3.6"]) == "ornith"


def test_default_is_none_for_an_empty_list() -> None:
    assert choose_default([]) is None


def test_default_honours_an_explicit_preference() -> None:
    assert choose_default(["a", "b", "c"], preferred="b") == "b"


def test_preferred_default_is_gemma4() -> None:
    assert PREFERRED_DEFAULT == "gemma4"


# -- resolve_choices ---------------------------------------------------------


def test_resolve_prefers_real_models() -> None:
    with patch("urllib.request.urlopen", _serving()):
        models = resolve_choices()

    # Three of the fixture's four entries: the cloud one is excluded by default.
    assert [m.name for m in models] == ["ornith", "qwen3.6", "gemma4"]
    assert any(m.parameter_size for m in models), "real entries carry metadata"


def test_resolve_synthesises_a_fallback_when_ollama_is_down() -> None:
    with patch("urllib.request.urlopen", _unreachable):
        models = resolve_choices()

    assert [m.name for m in models] == list(FALLBACK_MODELS)
    assert all(m.parameter_size == "" for m in models), "fallbacks have no metadata"


def test_resolve_uses_a_caller_supplied_fallback() -> None:
    with patch("urllib.request.urlopen", _unreachable):
        models = resolve_choices(fallback=["custom-model:latest"])

    assert [m.name for m in models] == ["custom-model"], "still normalised"


def test_resolve_with_an_empty_fallback_yields_nothing() -> None:
    with patch("urllib.request.urlopen", _unreachable):
        assert resolve_choices(fallback=[]) == []


# -- labels ------------------------------------------------------------------


def test_label_includes_parameters_and_size() -> None:
    info = ModelInfo(name="gemma4", size_bytes=9_608_350_718, parameter_size="8.0B")
    assert info.label == "gemma4  (8.0B, 9.6GB)"


def test_label_is_just_the_name_without_metadata() -> None:
    assert ModelInfo(name="gemma4").label == "gemma4"


def test_cloud_model_size_is_labelled_not_reported() -> None:
    """A remote model's reported size is a placeholder, so showing it in bytes
    would be misleading."""
    info = ModelInfo(name="kimi:cloud", size_bytes=384, is_remote=True, parameter_size="1T")

    assert info.size_label == "cloud"
    assert "384" not in info.label


def test_small_models_are_labelled_in_megabytes() -> None:
    assert ModelInfo(name="tiny", size_bytes=250_000_000).size_label == "250MB"


@pytest.mark.parametrize("size", [0, -1])
def test_unknown_size_yields_no_label(size: int) -> None:
    assert ModelInfo(name="x", size_bytes=size).size_label == ""
