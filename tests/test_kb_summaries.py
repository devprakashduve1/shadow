"""Tests for assistant/knowledge/summaries.py.

The behaviour worth pinning down is caching and invalidation: a summary costs
tens of seconds on a local model, so it must be served from cache aggressively,
and the fingerprint must be coarse enough that ordinary code edits don't
invalidate it.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from assistant.knowledge.indexer import KnowledgeBank, build_index
from assistant.knowledge.summaries import (
    SUMMARY_ARCHITECTURE,
    build_evidence,
    build_summary_prompt,
    ensure_summary,
    fingerprint,
    generate_summary,
    get_summary,
    is_stale,
    summary_text_for_context,
)


class _FakeResponse:
    def __init__(self, text: str):
        rows = [
            json.dumps({"response": text, "done": False}),
            json.dumps({"response": "", "done": True}),
        ]
        self._buffer = io.BytesIO(("\n".join(rows) + "\n").encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._buffer)


def _fake_model(text: str = "This project is a payments API."):
    state = {"calls": 0}

    def opener(*_args, **_kwargs):
        state["calls"] += 1
        return _FakeResponse(text)

    opener.state = state
    return opener


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text('"""App."""\n\n\ndef main():\n    return 1\n')
    (root / "README.md").write_text("# Payments API\n\nHandles payments.\n")
    (root / "requirements.txt").write_text("flask>=2.0\n")
    return root


@pytest.fixture
def bank(project: Path, shadow_root: Path) -> KnowledgeBank:
    build_index(project, shadow_root)
    return KnowledgeBank(project, shadow_root)


# -- evidence and prompt -----------------------------------------------------


def test_evidence_is_built_from_the_bank_not_the_project(bank: KnowledgeBank) -> None:
    """Cheap by construction — reads the bank's JSON, not the project's files."""
    evidence = build_evidence(bank)

    assert "Payments API" in evidence
    assert "flask" in evidence
    assert "src/" in evidence or "src" in evidence


def test_evidence_includes_symbol_signatures(bank: KnowledgeBank) -> None:
    assert "def main" in build_evidence(bank)


def test_evidence_respects_a_size_limit(bank: KnowledgeBank) -> None:
    assert len(build_evidence(bank, max_chars=200)) <= 200


def test_prompt_forbids_speculation(bank: KnowledgeBank) -> None:
    prompt = build_summary_prompt(SUMMARY_ARCHITECTURE, build_evidence(bank))

    assert "Do not invent details" in prompt
    assert "architecture" in prompt.lower()


# -- generation and caching --------------------------------------------------


def test_generate_stores_a_ready_summary(bank: KnowledgeBank) -> None:
    with patch("urllib.request.urlopen", _fake_model()):
        entry = generate_summary(bank, SUMMARY_ARCHITECTURE)

    assert entry.status == "ready"
    assert entry.text == "This project is a payments API."
    assert entry.source_fingerprint == fingerprint(bank)


def test_generated_summary_is_persisted(bank: KnowledgeBank) -> None:
    with patch("urllib.request.urlopen", _fake_model()):
        generate_summary(bank, SUMMARY_ARCHITECTURE)

    assert get_summary(bank, SUMMARY_ARCHITECTURE).text == "This project is a payments API."


def test_ensure_summary_serves_the_cache_without_calling_the_model(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    """The whole point of caching: the second request costs nothing."""
    opener = _fake_model()
    with patch("urllib.request.urlopen", opener):
        ensure_summary(project, SUMMARY_ARCHITECTURE, shadow_root=shadow_root)
        assert opener.state["calls"] == 1

        ensure_summary(project, SUMMARY_ARCHITECTURE, shadow_root=shadow_root)
        assert opener.state["calls"] == 1, "cache hit must not call the model again"


def test_ensure_summary_without_a_bank_reports_missing(project: Path, shadow_root: Path) -> None:
    entry = ensure_summary(project, SUMMARY_ARCHITECTURE, shadow_root=shadow_root)
    assert entry.status == "missing"


def test_model_failure_is_recorded_not_raised(bank: KnowledgeBank) -> None:
    """A repeatedly-unreachable Ollama shouldn't make callers retry forever."""

    def broken(*_args, **_kwargs):
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", broken):
        entry = generate_summary(bank, SUMMARY_ARCHITECTURE)

    assert entry.status == "failed"
    assert "connection refused" in entry.error


def test_empty_model_output_is_a_failure(bank: KnowledgeBank) -> None:
    with patch("urllib.request.urlopen", _fake_model("   ")):
        entry = generate_summary(bank, SUMMARY_ARCHITECTURE)

    assert entry.status == "failed"


def test_chunks_are_forwarded_while_streaming(bank: KnowledgeBank) -> None:
    seen = []
    with patch("urllib.request.urlopen", _fake_model("streamed text")):
        generate_summary(bank, SUMMARY_ARCHITECTURE, on_chunk=seen.append)

    assert "".join(seen) == "streamed text"


def test_cancellation_stops_generation(bank: KnowledgeBank) -> None:
    with patch("urllib.request.urlopen", _fake_model()):
        entry = generate_summary(bank, SUMMARY_ARCHITECTURE, should_cancel=lambda: True)

    assert entry.status == "missing"
    assert entry.error == "Cancelled."


# -- fingerprint coarseness (the important part) -----------------------------


def test_fingerprint_unchanged_by_an_ordinary_code_edit(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    """If editing one function invalidated the architecture summary, the cache
    would never be hit and every session would pay the generation cost."""
    before = fingerprint(bank)

    (project / "src" / "app.py").write_text(
        '"""App."""\n\n\ndef main():\n    # a new comment\n    return 2\n'
    )
    build_index(project, shadow_root)

    assert fingerprint(KnowledgeBank(project, shadow_root)) == before


def test_fingerprint_unchanged_by_adding_one_file(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    before = fingerprint(bank)

    (project / "src" / "helper.py").write_text("def helper():\n    pass\n")
    build_index(project, shadow_root)

    assert fingerprint(KnowledgeBank(project, shadow_root)) == before


def test_fingerprint_changes_when_a_dependency_is_added(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    """A new dependency genuinely can change what the project is."""
    before = fingerprint(bank)

    (project / "requirements.txt").write_text("flask>=2.0\nsqlalchemy>=2.0\n")
    build_index(project, shadow_root)

    assert fingerprint(KnowledgeBank(project, shadow_root)) != before


def test_fingerprint_changes_when_a_top_level_package_appears(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    before = fingerprint(bank)

    (project / "workers").mkdir()
    (project / "workers" / "queue.py").write_text("def consume():\n    pass\n")
    build_index(project, shadow_root)

    assert fingerprint(KnowledgeBank(project, shadow_root)) != before


def test_fingerprint_ignores_dependency_version_bumps(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    """A version bump doesn't change the architecture."""
    before = fingerprint(bank)

    (project / "requirements.txt").write_text("flask>=3.0\n")
    build_index(project, shadow_root)

    assert fingerprint(KnowledgeBank(project, shadow_root)) == before


# -- staleness ---------------------------------------------------------------


def test_summary_becomes_stale_when_the_shape_changes(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    with patch("urllib.request.urlopen", _fake_model()):
        generate_summary(bank, SUMMARY_ARCHITECTURE)
    assert is_stale(bank, SUMMARY_ARCHITECTURE) is False

    (project / "requirements.txt").write_text("flask>=2.0\ncelery>=5\n")
    build_index(project, shadow_root)

    assert is_stale(KnowledgeBank(project, shadow_root), SUMMARY_ARCHITECTURE) is True


def test_stale_summary_is_still_served_but_labelled(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    """An out-of-date description beats no description."""
    with patch("urllib.request.urlopen", _fake_model("Original description.")):
        generate_summary(bank, SUMMARY_ARCHITECTURE)

    (project / "requirements.txt").write_text("flask>=2.0\ncelery>=5\n")
    build_index(project, shadow_root)
    updated_bank = KnowledgeBank(project, shadow_root)

    text = summary_text_for_context(updated_bank, SUMMARY_ARCHITECTURE)

    assert "Original description." in text
    assert "may be out of date" in text


def test_ensure_summary_regenerates_when_stale(
    project: Path, shadow_root: Path, bank: KnowledgeBank
) -> None:
    opener = _fake_model("First.")
    with patch("urllib.request.urlopen", opener):
        ensure_summary(project, SUMMARY_ARCHITECTURE, shadow_root=shadow_root)
    assert opener.state["calls"] == 1

    (project / "requirements.txt").write_text("flask>=2.0\ncelery>=5\n")
    build_index(project, shadow_root)

    second = _fake_model("Second.")
    with patch("urllib.request.urlopen", second):
        entry = ensure_summary(project, SUMMARY_ARCHITECTURE, shadow_root=shadow_root)

    assert second.state["calls"] == 1
    assert entry.text == "Second."


def test_summary_text_for_context_empty_when_never_generated(bank: KnowledgeBank) -> None:
    assert summary_text_for_context(bank, SUMMARY_ARCHITECTURE) == ""
