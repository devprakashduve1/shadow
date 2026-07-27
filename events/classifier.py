"""Rule-based classification of captured text into a structured event type.

Heuristic, not ML-based — same tradeoff `callwatch/call_detector.py` makes for
call detection: fast, dependency-free, good enough for the common cases, will
miss unusual phrasing. `type` reflects the single primary classification;
`tags` layers in supplementary signals (e.g. a meeting transcript line that
also contains a decision) without overriding it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse

from .project_keys import extract_project_keys
from .schema import EventType, Severity

_TRACEBACK_PATTERNS = (
    re.compile(r"Traceback \(most recent call last\)"),  # Python
    re.compile(r"Exception in thread"),  # Java
    re.compile(r"\bat java\.\w"),  # Java stack frame
    re.compile(r"UnhandledPromiseRejection"),  # Node
    re.compile(r"\bat Object\.<anonymous>"),  # Node stack frame
    re.compile(r"thread '.*' panicked at"),  # Rust
    re.compile(r"BUILD FAILED"),
    re.compile(r"npm ERR!"),
    re.compile(r"error\[E\d+\]"),  # rustc
)

_HIGH_SEVERITY_KEYWORDS = re.compile(r"(?i)\b(fatal|panic(ked)?|crash(ed)?|segfault)\b")

_DECISION_KEYWORDS = re.compile(
    r"(?i)\b(we decided|let'?s go with|decision:|agreed to|final call)\b"
)
_TASK_KEYWORDS = re.compile(
    r"(?i)\b(todo|to-do|action item|follow[- ]?up|will (?:do|handle|own|take))\b"
)

_URL_PATTERN = re.compile(r"https?://[^\s\"'>]+")

_EDITOR_APPS = re.compile(
    r"(?i)\b(vs ?code|visual studio code|pycharm|intellij|xcode|sublime|vim|neovim|terminal|iterm)\b"
)
_CODE_SYMBOL_PATTERN = re.compile(r"(def |function |class |=>|;\s*$|\{|\}|import |const |let )")


@dataclass
class ClassificationResult:
    type: EventType
    severity: Severity
    entities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


def classify(text: str, *, channel: str = "default", application: str = "") -> ClassificationResult:
    """Classifies a single captured text snippet.

    `channel` mirrors `DataLogger`'s channel argument ("screen" for OCR,
    "speech" for meeting transcripts); `application` is the frontmost app/
    window name at capture time, when known.
    """
    tags: List[str] = []
    entities: List[str] = []

    if _DECISION_KEYWORDS.search(text):
        tags.append("decision")
    if _TASK_KEYWORDS.search(text):
        tags.append("task")

    urls = _URL_PATTERN.findall(text)
    if urls:
        entities.extend(sorted({urlparse(u).netloc for u in urls if urlparse(u).netloc}))

    # Ticket-key-shaped project identity (e.g. "PROJ-1139" -> "PROJ") — tagged
    # regardless of the event's eventual type, so a meeting/decision/task
    # event that mentions a project is tagged too, not just code/error
    # events. Denormalized convenience only: the Coding Agent tab
    # (assistant/projects.py, assistant/retrieval.py) re-extracts from
    # `content` directly rather than relying on this, so project detection
    # still works for events captured before this tagging existed.
    entities.extend(k for k in extract_project_keys(text) if k not in entities)

    for pattern in _TRACEBACK_PATTERNS:
        if pattern.search(text):
            severity = Severity.HIGH if _HIGH_SEVERITY_KEYWORDS.search(text) else Severity.MEDIUM
            return ClassificationResult(EventType.ERROR, severity, entities, tags)

    if channel == "speech":
        return ClassificationResult(EventType.MEETING, Severity.LOW, entities, tags)

    if urls:
        return ClassificationResult(EventType.WEBSITE, Severity.LOW, entities, tags)

    if _EDITOR_APPS.search(application) and len(_CODE_SYMBOL_PATTERN.findall(text)) >= 3:
        return ClassificationResult(EventType.CODE, Severity.LOW, entities, tags)

    if "decision" in tags:
        return ClassificationResult(EventType.DECISION, Severity.LOW, entities, tags)
    if "task" in tags:
        return ClassificationResult(EventType.TASK, Severity.LOW, entities, tags)

    return ClassificationResult(EventType.NOTE, Severity.LOW, entities, tags)
