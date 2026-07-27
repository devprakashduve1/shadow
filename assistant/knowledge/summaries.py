"""LLM-written prose summaries of a repository, generated lazily and cached.

The expensive half of the Knowledge Bank. Deliberately separate from the static
index (`indexer.py`) because the local model on this machine takes ~11 seconds
for a trivial prompt — running these at repo-open time would make opening a
project feel broken. Instead the static index lands instantly, and prose is
generated on first request (or in the background) and cached.

## Invalidation

`fingerprint()` is intentionally **coarse**: it hashes the project's *shape*
(top-level directories, dependency names, entrypoints, rough file counts), not
its contents. Editing one function shouldn't invalidate a description of the
architecture — that would mean regenerating constantly and never serving a cache
hit. Adding a dependency or a new top-level package legitimately should.

When a summary is stale it's still returned, flagged, while a regeneration is
pending. An out-of-date architecture note beats no architecture note.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from ..edits.atomic_io import read_json, write_json_atomic
from ..shadow_home import ensure_dir
from ..streaming import stream_chat
from .indexer import KnowledgeBank
from .manifests import summarize_dependencies
from .schema import (
    SCHEMA_VERSION,
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_READY,
    SUMMARIES_FILE,
    SUMMARY_ARCHITECTURE,
    SUMMARY_ONBOARDING,
    SUMMARY_PATTERNS,
    SummaryEntry,
)

# Buckets rather than exact counts, so adding a couple of files doesn't change
# the fingerprint. Crossing an order of magnitude does.
_SIZE_BUCKETS = (10, 50, 100, 500, 1000, 5000, 20000)

SUMMARY_KINDS = (SUMMARY_ARCHITECTURE, SUMMARY_PATTERNS, SUMMARY_ONBOARDING)

_PROMPTS = {
    SUMMARY_ARCHITECTURE: (
        "Describe this project's architecture in 150-250 words: what it does, how it's "
        "organised, the main components and how they relate. Ground every claim in the "
        "structure shown below — if something isn't evident from it, don't assert it."
    ),
    SUMMARY_PATTERNS: (
        "Describe the coding conventions and patterns visible in this project in 100-200 "
        "words: naming, file organisation, error handling, testing approach, and anything "
        "notable a contributor should match. Only describe what the evidence below shows."
    ),
    SUMMARY_ONBOARDING: (
        "Write a 100-200 word orientation for a developer new to this project: where to "
        "start reading, which files matter most, and how to run or test it. Base it only "
        "on the structure and documentation below."
    ),
}


def _bucket(count: int) -> int:
    for threshold in _SIZE_BUCKETS:
        if count <= threshold:
            return threshold
    return _SIZE_BUCKETS[-1] * 10


def fingerprint(bank: KnowledgeBank) -> str:
    """A coarse hash of the project's shape. See the module docstring.

    Includes: top-level directories, dependency *names* (not versions — a version
    bump doesn't change the architecture), entrypoint paths, the language mix, and
    a bucketed file count.
    """
    entries = bank.load_files()
    manifests = bank.load_manifests()
    outline = bank.load_outline()

    top_level = sorted({Path(path).parts[0] for path in entries if Path(path).parts})
    dependencies = sorted(
        {name for manifest in manifests for name in manifest.dependencies}
    )
    languages = sorted(outline.get("by_language", {}))
    entrypoints = sorted(outline.get("entrypoints", []))

    payload = "|".join(
        [
            ",".join(top_level),
            ",".join(dependencies),
            ",".join(languages),
            ",".join(entrypoints),
            str(_bucket(len(entries))),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def load_summaries(bank: KnowledgeBank) -> Dict[str, SummaryEntry]:
    data = read_json(bank.dir / SUMMARIES_FILE) or {}
    if data.get("version") != SCHEMA_VERSION:
        return {}
    return {
        key: SummaryEntry.from_dict(value)
        for key, value in (data.get("entries") or {}).items()
    }


def save_summaries(bank: KnowledgeBank, entries: Dict[str, SummaryEntry]) -> None:
    ensure_dir(bank.dir)
    write_json_atomic(
        bank.dir / SUMMARIES_FILE,
        {
            "version": SCHEMA_VERSION,
            "entries": {key: entry.to_dict() for key, entry in entries.items()},
        },
    )


def get_summary(bank: KnowledgeBank, kind: str) -> SummaryEntry:
    """Returns a cached summary, marking it stale if the project shape moved."""
    entry = load_summaries(bank).get(kind, SummaryEntry())
    if entry.status == STATUS_READY and entry.is_stale_for(fingerprint(bank)):
        # Reported as stale but the text is preserved — callers decide whether to
        # use it while a regeneration runs.
        return SummaryEntry(
            text=entry.text,
            status=STATUS_READY,
            model=entry.model,
            generated_at=entry.generated_at,
            source_fingerprint=entry.source_fingerprint,
        )
    return entry


def is_stale(bank: KnowledgeBank, kind: str) -> bool:
    return load_summaries(bank).get(kind, SummaryEntry()).is_stale_for(fingerprint(bank))


def build_evidence(bank: KnowledgeBank, max_chars: int = 8000) -> str:
    """Renders the static index into the evidence block a summary is written from.

    Cheap by construction — reads the bank's own JSON, not the project's files.
    """
    entries = bank.load_files()
    outline = bank.load_outline()
    manifests = bank.load_manifests()
    readme, docs = bank.load_docs()
    meta = bank.load_meta()

    parts: List[str] = []
    if meta is not None:
        parts.append(f"Project: {meta.name} ({meta.file_count} indexed files)")

    languages = outline.get("by_language", {})
    if languages:
        mix = ", ".join(f"{name} ×{count}" for name, count in list(languages.items())[:8])
        parts.append(f"Languages: {mix}")

    top_level: Dict[str, int] = {}
    for path in entries:
        parts_of = Path(path).parts
        key = parts_of[0] if len(parts_of) > 1 else "(root)"
        top_level[key] = top_level.get(key, 0) + 1
    layout = ", ".join(
        f"{name}/ ({count})" for name, count in sorted(top_level.items(), key=lambda kv: -kv[1])[:15]
    )
    parts.append(f"Top-level layout: {layout}")

    if outline.get("entrypoints"):
        parts.append("Entrypoints: " + ", ".join(outline["entrypoints"][:10]))

    dependency_text = summarize_dependencies(manifests, limit=25)
    if dependency_text:
        parts.append("Dependencies:\n" + dependency_text)

    if readme is not None:
        parts.append(f"README ({readme.path}):\n{readme.excerpt[:2500]}")
    if docs:
        titles = ", ".join(doc.title for doc in docs[:8])
        parts.append(f"Docs present: {titles}")

    # A sample of real API signatures conveys style better than any description.
    signatures = [
        f"{item['path']}: {item.get('signature') or item['name']}"
        for item in outline.get("top_symbols", [])[:60]
    ]
    if signatures:
        parts.append("Sample of defined symbols:\n" + "\n".join(signatures))

    return "\n\n".join(parts)[:max_chars]


def build_summary_prompt(kind: str, evidence: str) -> str:
    instruction = _PROMPTS.get(kind, _PROMPTS[SUMMARY_ARCHITECTURE])
    return (
        "You are documenting a software project for a developer who has never seen it. "
        f"{instruction}\n\n"
        "Do not invent details, and do not speculate about anything not shown. Write plain "
        "prose with no markdown headings.\n\n"
        f"Evidence:\n{evidence}\n\nDescription:"
    )


def generate_summary(
    bank: KnowledgeBank,
    kind: str,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 600.0,
    on_chunk: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> SummaryEntry:
    """Generates and caches one summary.

    Failures are recorded (`status="failed"` plus the message) rather than
    raised, so a repeatedly-unreachable Ollama doesn't make the caller retry
    forever — and the UI can say what went wrong.
    """
    evidence = build_evidence(bank)
    if not evidence.strip():
        return SummaryEntry(status=STATUS_MISSING, error="Nothing indexed yet.")

    prompt = build_summary_prompt(kind, evidence)
    current_fingerprint = fingerprint(bank)

    try:
        chunks: List[str] = []
        for chunk in stream_chat(
            prompt, base_url=base_url, model=model, timeout_seconds=timeout_seconds
        ):
            chunks.append(chunk)
            if on_chunk is not None:
                on_chunk(chunk)
            if should_cancel is not None and should_cancel():
                return SummaryEntry(status=STATUS_MISSING, error="Cancelled.")
        text = "".join(chunks).strip()
    except Exception as exc:
        entry = SummaryEntry(status=STATUS_FAILED, error=str(exc), model=model)
        _store(bank, kind, entry)
        return entry

    if not text:
        entry = SummaryEntry(status=STATUS_FAILED, error="The model returned nothing.", model=model)
        _store(bank, kind, entry)
        return entry

    entry = SummaryEntry(
        text=text,
        status=STATUS_READY,
        model=model,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        source_fingerprint=current_fingerprint,
    )
    _store(bank, kind, entry)
    return entry


def _store(bank: KnowledgeBank, kind: str, entry: SummaryEntry) -> None:
    summaries = load_summaries(bank)
    summaries[kind] = entry
    save_summaries(bank, summaries)


def summary_text_for_context(bank: KnowledgeBank, kind: str = SUMMARY_ARCHITECTURE) -> str:
    """Returns a summary for prompt use, labelled if it may be out of date."""
    entry = get_summary(bank, kind)
    if entry.status != STATUS_READY or not entry.text:
        return ""
    if entry.is_stale_for(fingerprint(bank)):
        return f"{entry.text}\n\n(Note: this description may be out of date.)"
    return entry.text


def ensure_summary(
    project_path: Union[str, Path],
    kind: str = SUMMARY_ARCHITECTURE,
    *,
    shadow_root=None,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 600.0,
) -> SummaryEntry:
    """Returns a cached summary, generating it only if missing or stale."""
    bank = KnowledgeBank(project_path, shadow_root)
    if not bank.exists:
        return SummaryEntry(status=STATUS_MISSING, error="No Knowledge Bank yet.")
    existing = load_summaries(bank).get(kind, SummaryEntry())
    if existing.status == STATUS_READY and not existing.is_stale_for(fingerprint(bank)):
        return existing
    return generate_summary(
        bank, kind, base_url=base_url, model=model, timeout_seconds=timeout_seconds
    )
