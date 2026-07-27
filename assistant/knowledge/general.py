"""The General Knowledge Bank: organizational context from captured activity.

Where the per-repo bank (`indexer.py`) describes *code*, this one describes the
*work around* the code — what was decided in meetings, what was agreed, what
keeps breaking, which tickets and systems come up, the vocabulary a team actually
uses. It's built from the events Shadow already captures (screen OCR and meeting
transcripts, already redacted and classified by `events/`), so it accumulates on
its own rather than needing to be written.

Two halves, same split as the repo bank and for the same reason:

- a **static digest** — counts, decisions, action items, recurring errors, a
  glossary of terms, ticket keys, applications — cheap and deterministic
- **LLM prose** — business context and a decision log — slow, so generated lazily
  and cached

Stored at `<shadow_home>/_general/`. The leading underscore keeps it clear of
per-repo directories, which are always `<name>-<8 hex>`.

## A note on what's in here

This digest is derived from screen captures and meeting audio, so it can contain
anything that was on screen or said aloud. It goes through `events/redaction.py`
on the way in, but redaction is a filter, not a guarantee. It lives outside any
repository specifically so it can't be committed by accident, and its contents are
only ever sent to the *local* model.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from ..edits.atomic_io import read_json, write_json_atomic
from ..shadow_home import ensure_dir, shadow_home
from .schema import SCHEMA_VERSION

GENERAL_DIR_NAME = "_general"
DIGEST_FILE = "digest.json"
GENERAL_SUMMARIES_FILE = "summaries.json"

# Event types worth calling out separately in the digest, mapped to the section
# they feed. Everything else still counts toward totals and the glossary.
DECISION_TYPES = ("decision",)
TASK_TYPES = ("task", "reminder")
PROBLEM_TYPES = ("error", "bug")
MEETING_TYPES = ("meeting", "conversation")

# How many items to keep per section. The digest is prompt material, so it's
# bounded — an unbounded decision list would eventually crowd out everything else.
MAX_PER_SECTION = 60
MAX_GLOSSARY_TERMS = 80
MAX_TICKETS = 40

# A snippet shorter than this is usually OCR noise (a toolbar label, a stray
# word) rather than a statement worth remembering.
MIN_SNIPPET_CHARS = 25
MAX_SNIPPET_CHARS = 400

_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")
# CamelCase identifiers, ALL_CAPS constants, and dotted/service-ish names — the
# shape of domain vocabulary in a technical org.
_TERM_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z]{3,}(?:_[A-Z]+)*|[a-z]+(?:[-_][a-z]+){1,3})\b"
)
_URL_HOST_RE = re.compile(r"https?://([^/\s:]+)")

# Terms that are technically the right *shape* but carry no domain meaning.
_TERM_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "will", "your",
    "you", "not", "are", "was", "can", "all", "any", "but", "out", "get", "new",
    "one", "two", "see", "use", "now", "how", "why", "who", "what", "when",
    "click", "close", "open", "file", "edit", "view", "help", "window", "search",
    "select", "cancel", "submit", "back", "next", "done", "save", "menu", "home",
    "settings", "profile", "sign-in", "log-in", "sign-out", "loading",
    "untitled", "unknown", "default", "true", "false", "null", "none",
}


@dataclass
class ActivityItem:
    """One remembered snippet of captured activity."""

    timestamp: str
    text: str
    kind: str = ""
    application: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ActivityItem":
        return cls(
            timestamp=str(data.get("timestamp", "")),
            text=str(data.get("text", "")),
            kind=str(data.get("kind", "")),
            application=str(data.get("application", "")),
            source=str(data.get("source", "")),
        )


@dataclass
class GeneralDigest:
    """The static half of the general bank."""

    version: int = SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    # Watermark for incremental updates: the newest event timestamp already
    # folded in. Events at or before this are skipped on the next pass.
    last_event_timestamp: str = ""
    event_count: int = 0
    days_covered: List[str] = field(default_factory=list)
    type_counts: Dict[str, int] = field(default_factory=dict)
    decisions: List[ActivityItem] = field(default_factory=list)
    action_items: List[ActivityItem] = field(default_factory=list)
    problems: List[ActivityItem] = field(default_factory=list)
    meetings: List[ActivityItem] = field(default_factory=list)
    glossary: Dict[str, int] = field(default_factory=dict)
    tickets: Dict[str, int] = field(default_factory=dict)
    applications: Dict[str, int] = field(default_factory=dict)
    hosts: Dict[str, int] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.event_count == 0

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        for key in ("decisions", "action_items", "problems", "meetings"):
            data[key] = [item.to_dict() for item in getattr(self, key)]
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, object]]) -> "GeneralDigest":
        if not data or data.get("version") != SCHEMA_VERSION:
            return cls()
        digest = cls(
            version=int(data.get("version", SCHEMA_VERSION)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            last_event_timestamp=str(data.get("last_event_timestamp", "")),
            event_count=int(data.get("event_count", 0)),
            days_covered=list(data.get("days_covered", [])),
            type_counts=dict(data.get("type_counts", {})),
            glossary=dict(data.get("glossary", {})),
            tickets=dict(data.get("tickets", {})),
            applications=dict(data.get("applications", {})),
            hosts=dict(data.get("hosts", {})),
        )
        for key in ("decisions", "action_items", "problems", "meetings"):
            setattr(
                digest,
                key,
                [ActivityItem.from_dict(item) for item in (data.get(key) or [])],
            )
        return digest


def general_dir(root: Optional[Union[str, Path]] = None) -> Path:
    """Returns (without creating) the general bank's directory."""
    return shadow_home(root) / GENERAL_DIR_NAME


def _clean_snippet(text: str) -> str:
    """Collapses whitespace and trims to something prompt-sized."""
    collapsed = " ".join(text.split())
    return collapsed[:MAX_SNIPPET_CHARS]


def _is_useful_snippet(text: str) -> bool:
    """Filters OCR noise: too short, or barely any actual words.

    Screen OCR produces a lot of single labels and fragments. Requiring both a
    minimum length and a few multi-character words drops most of it without
    needing a language model.
    """
    cleaned = text.strip()
    if len(cleaned) < MIN_SNIPPET_CHARS:
        return False
    words = [w for w in re.findall(r"[A-Za-z]{3,}", cleaned)]
    return len(words) >= 4


def _extract_terms(text: str) -> List[str]:
    terms = []
    for match in _TERM_RE.findall(text):
        lowered = match.lower()
        if lowered in _TERM_STOPWORDS or len(match) < 4:
            continue
        terms.append(match)
    return terms


def _merge_counter(existing: Dict[str, int], additions: Counter, limit: int) -> Dict[str, int]:
    """Adds counts into a stored dict, keeping only the most frequent.

    Truncating on merge (rather than on read) keeps the file bounded no matter
    how long capture has been running.
    """
    merged = Counter(existing)
    merged.update(additions)
    return dict(merged.most_common(limit))


# Two snippets sharing this many leading characters are treated as the same
# capture. Screen OCR of one screen re-read a moment later usually differs only in
# its tail (a clock, a changed badge), so exact-match de-duplication lets near
# copies of the same thing through.
_DEDUPE_PREFIX_CHARS = 80


def _dedupe_key(text: str) -> str:
    """Normalises a snippet for de-duplication.

    Collapses whitespace and case, then compares only the opening characters —
    the OCR duplicates this exists for share a long identical prefix and differ
    in the tail.

    Digits are deliberately *kept*. Normalising them away would also merge
    genuinely distinct items that differ only by a number — "PROJ-1139" and
    "PROJ-1140", or "raise the timeout to 30s" and "to 60s" — and silently losing
    a real decision is worse than keeping a near-duplicate.
    """
    return " ".join(text.lower().split())[:_DEDUPE_PREFIX_CHARS]


def _merge_items(
    existing: List[ActivityItem], additions: List[ActivityItem], limit: int
) -> List[ActivityItem]:
    """Keeps the newest items, de-duplicated by their opening text.

    De-duplication matters a lot here: screen OCR re-captures the same visible
    text every time anything on screen changes, so the same content arrives
    dozens of times with small differences.
    """
    seen = set()
    combined: List[ActivityItem] = []
    for item in sorted(existing + additions, key=lambda i: i.timestamp, reverse=True):
        key = _dedupe_key(item.text)
        if not key.strip() or key in seen:
            continue
        seen.add(key)
        combined.append(item)
        if len(combined) >= limit:
            break
    return combined


class GeneralKnowledgeBank:
    """Read/write access to the general bank."""

    def __init__(self, event_store, shadow_root: Optional[Union[str, Path]] = None):
        self._store = event_store
        self.dir = general_dir(shadow_root)

    @property
    def exists(self) -> bool:
        return (self.dir / DIGEST_FILE).is_file()

    def load(self) -> GeneralDigest:
        return GeneralDigest.from_dict(read_json(self.dir / DIGEST_FILE))

    def save(self, digest: GeneralDigest) -> None:
        ensure_dir(self.dir)
        write_json_atomic(self.dir / DIGEST_FILE, digest.to_dict())

    def status(self) -> str:
        """One of "missing", "stale", "ready" — for the UI indicator."""
        digest = self.load()
        if digest.is_empty:
            return "missing"
        return "stale" if self._has_new_events(digest.last_event_timestamp) else "ready"

    def _has_new_events(self, watermark: str) -> bool:
        if not watermark:
            return True
        recent = self._store.query_events(limit=1)
        return bool(recent and recent[0].timestamp > watermark)

    # -- building ----------------------------------------------------------

    def build(self, limit: int = 100_000, force_full: bool = False) -> GeneralDigest:
        """Folds new captured events into the digest.

        Incremental by default: only events newer than the stored watermark are
        read, so a long-running capture history doesn't get re-processed on every
        update. `force_full` rebuilds from the whole history.
        """
        previous = GeneralDigest() if force_full else self.load()
        watermark = "" if force_full else previous.last_event_timestamp

        events = self._store.query_events(limit=limit)
        fresh = [e for e in events if not watermark or e.timestamp > watermark]

        now = datetime.now().isoformat(timespec="seconds")
        digest = GeneralDigest(
            created_at=previous.created_at or now,
            updated_at=now,
            last_event_timestamp=previous.last_event_timestamp,
            event_count=previous.event_count,
            days_covered=list(previous.days_covered),
            type_counts=dict(previous.type_counts),
            decisions=list(previous.decisions),
            action_items=list(previous.action_items),
            problems=list(previous.problems),
            meetings=list(previous.meetings),
            glossary=dict(previous.glossary),
            tickets=dict(previous.tickets),
            applications=dict(previous.applications),
            hosts=dict(previous.hosts),
        )

        if not fresh:
            self.save(digest)
            return digest

        buckets: Dict[str, List[ActivityItem]] = {
            "decisions": [], "action_items": [], "problems": [], "meetings": []
        }
        terms: Counter = Counter()
        tickets: Counter = Counter()
        applications: Counter = Counter()
        hosts: Counter = Counter()
        type_counts: Counter = Counter()
        days = set(digest.days_covered)

        for event in fresh:
            type_counts[event.type.value] += 1
            if event.timestamp:
                days.add(event.timestamp.split("T")[0])
            if event.application:
                applications[event.application] += 1

            content = event.content or ""
            for host in _URL_HOST_RE.findall(content):
                hosts[host] += 1
            for ticket in _TICKET_RE.findall(content):
                tickets[ticket] += 1
            terms.update(_extract_terms(content))

            if not _is_useful_snippet(content):
                continue
            item = ActivityItem(
                timestamp=event.timestamp,
                text=_clean_snippet(content),
                kind=event.type.value,
                application=event.application,
                source=event.source,
            )
            bucket = self._bucket_for(event)
            if bucket:
                buckets[bucket].append(item)

        digest.event_count += len(fresh)
        digest.last_event_timestamp = max(
            [digest.last_event_timestamp] + [e.timestamp for e in fresh if e.timestamp]
        )
        digest.days_covered = sorted(days)
        digest.type_counts = dict(Counter(digest.type_counts) + type_counts)
        digest.glossary = _merge_counter(digest.glossary, terms, MAX_GLOSSARY_TERMS)
        digest.tickets = _merge_counter(digest.tickets, tickets, MAX_TICKETS)
        digest.applications = _merge_counter(digest.applications, applications, 40)
        digest.hosts = _merge_counter(digest.hosts, hosts, 40)
        for key, additions in buckets.items():
            setattr(digest, key, _merge_items(getattr(digest, key), additions, MAX_PER_SECTION))

        self.save(digest)
        return digest

    @staticmethod
    def _bucket_for(event) -> str:
        value = event.type.value
        if value in DECISION_TYPES:
            return "decisions"
        if value in TASK_TYPES:
            return "action_items"
        if value in PROBLEM_TYPES:
            return "problems"
        if value in MEETING_TYPES:
            return "meetings"
        # Anything with a "decision"/"task" tag but a different classified type
        # still belongs in those sections.
        tags = set(getattr(event, "tags", []) or [])
        if "decision" in tags:
            return "decisions"
        if "task" in tags:
            return "action_items"
        return ""


def render_digest(digest: GeneralDigest, max_chars: int = 6000) -> str:
    """Renders the digest as prompt context, highest-value sections first."""
    if digest.is_empty:
        return ""

    sections: List[Tuple[str, str]] = [
        ("decisions", _render_items(digest.decisions, 12)),
        ("action items", _render_items(digest.action_items, 12)),
        ("recurring problems", _render_items(digest.problems, 8)),
        ("meeting notes", _render_items(digest.meetings, 8)),
        ("project vocabulary", ", ".join(list(digest.glossary)[:40])),
        ("tickets referenced", ", ".join(list(digest.tickets)[:20])),
        ("systems and tools", ", ".join(list(digest.applications)[:12] + list(digest.hosts)[:12])),
    ]

    parts: List[str] = []
    used = 0
    for label, body in sections:
        if not body.strip():
            continue
        block = f"\n[{label}]\n{body}"
        if used + len(block) > max_chars:
            continue
        parts.append(block)
        used += len(block)
    return "".join(parts).strip()


def _render_items(items: Sequence[ActivityItem], limit: int) -> str:
    lines = []
    for item in items[:limit]:
        when = item.timestamp.split("T")[0] if item.timestamp else "?"
        lines.append(f"- ({when}) {item.text}")
    return "\n".join(lines)


def assemble_general_context(
    event_store,
    question: str = "",
    *,
    shadow_root: Optional[Union[str, Path]] = None,
    max_chars: int = 4000,
) -> str:
    """Returns general organizational context for a prompt.

    When `question` is given, items mentioning any of its words are floated to
    the front — a question about "the payment retry decision" should surface that
    decision rather than whichever was most recent.
    """
    bank = GeneralKnowledgeBank(event_store, shadow_root)
    digest = bank.load()
    if digest.is_empty:
        return ""
    if question.strip():
        digest = _reorder_for(digest, question)
    return render_digest(digest, max_chars=max_chars)


def _reorder_for(digest: GeneralDigest, question: str) -> GeneralDigest:
    """Floats question-relevant items to the front of each section.

    Returns a shallow copy: the stored digest keeps its recency ordering, since
    that's the right default for a question that matches nothing.
    """
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9_]{3,}", question)}
    if not words:
        return digest

    def score(item: ActivityItem) -> int:
        text = item.text.lower()
        return sum(1 for word in words if word in text)

    reordered = GeneralDigest.from_dict(digest.to_dict())
    for key in ("decisions", "action_items", "problems", "meetings"):
        items = list(getattr(reordered, key))
        # Two stable passes: sort by recency first, then by score. Python's sort
        # is stable, so the second pass wins on score while equal scores keep the
        # newest-first order from the first.
        items.sort(key=lambda item: item.timestamp, reverse=True)
        items.sort(key=score, reverse=True)
        setattr(reordered, key, items)
    return reordered
