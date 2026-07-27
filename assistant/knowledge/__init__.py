"""Per-repository Knowledge Bank: a cached, incremental understanding of a project.

Stored outside the repository, under `~/Desktop/.shadow/<repo-id>/`, so indexing
never adds untracked files to the user's project.

Two halves, deliberately separated by cost:

- **static index** (`indexer.py`, `symbols.py`, `manifests.py`) — file list,
  languages, symbols, dependencies, docs. No LLM, fast enough to run on open.
- **prose summaries** (`summaries.py`) — architecture/patterns/onboarding
  descriptions written by the local model, generated lazily and cached, because
  each one costs tens of seconds on a local model.

`context.py` is what the rest of the app actually consumes: it turns a question
into a bounded, relevant context string while reading only a handful of files —
replacing `project_files.find_relevant_files`, which read the entire project on
every call.
"""
from .context import ContextResult, assemble_context, context_for_edit, rank_files
from .indexer import KnowledgeBank, build_index
from .schema import BankMeta, FileEntry, IndexResult, Manifest, Symbol
from .summaries import (
    SUMMARY_ARCHITECTURE,
    SUMMARY_ONBOARDING,
    SUMMARY_PATTERNS,
    ensure_summary,
    fingerprint,
    generate_summary,
    get_summary,
    summary_text_for_context,
)

__all__ = [
    "BankMeta",
    "ContextResult",
    "FileEntry",
    "IndexResult",
    "KnowledgeBank",
    "Manifest",
    "SUMMARY_ARCHITECTURE",
    "SUMMARY_ONBOARDING",
    "SUMMARY_PATTERNS",
    "Symbol",
    "assemble_context",
    "build_index",
    "context_for_edit",
    "ensure_summary",
    "fingerprint",
    "generate_summary",
    "get_summary",
    "rank_files",
    "summary_text_for_context",
]
