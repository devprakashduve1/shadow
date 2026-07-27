"""Typed structured-event schema.

An `Event` is the processed, classified counterpart to a raw `logger.LogEntry`:
every OCR/transcript entry that flows through `DataLogger` (see
`logger/data_logger.py`) is, once an `EventStore` is attached, redacted
(`events/redaction.py`) and classified (`events/classifier.py`) into one of
these before being appended as one JSON line to a date-partitioned
`events.jsonl` file (`database/json_store.py`) — no database involved, same
flat-file approach `logger/data_logger.py` already uses for OCR/speech logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    MEETING = "meeting"
    CODE = "code"
    ERROR = "error"
    BUG = "bug"
    DECISION = "decision"
    TASK = "task"
    WEBSITE = "website"
    APPLICATION = "application"
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    SEARCH = "search"
    QUESTION = "question"
    REMINDER = "reminder"
    NOTE = "note"  # fallback when nothing more specific matches


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Event:
    timestamp: str  # ISO 8601
    type: EventType
    title: str
    application: str
    severity: Severity
    source: str  # "ocr" | "speech" | "manual" | ... (mirrors LogEntry.source)
    content: str
    entities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Plain JSON-serializable dict — one of these is written per line in events.jsonl."""
        return {
            "timestamp": self.timestamp,
            "type": self.type.value,
            "title": self.title,
            "application": self.application,
            "severity": self.severity.value,
            "source": self.source,
            "content": self.content,
            "entities": list(self.entities),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(
            timestamp=data["timestamp"],
            type=EventType(data["type"]),
            title=data["title"],
            application=data["application"],
            severity=Severity(data["severity"]),
            source=data["source"],
            content=data["content"],
            entities=list(data.get("entities", [])),
            tags=list(data.get("tags", [])),
        )

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)
