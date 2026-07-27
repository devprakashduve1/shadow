"""Project discovery for the Coding Agent tab.

Two ways a project gets into the list, merged together by `list_projects()`:

1. **Auto-detected** — a project's known event history already lives in the
   `events` files, so most of the list is derived on demand by re-extracting
   ticket keys from each event's own content, the same linear-scan-and-
   aggregate approach `search/search_engine.py` and `database/json_store.py`
   already use. Deliberately re-extracts from `event.content` every time
   rather than trusting `event.entities` (which `events/classifier.py` also
   tags with ticket keys at capture time): entities are only as fresh as
   whatever classifier version wrote them, so anything captured before this
   feature existed — i.e. most of an existing install's history — would
   otherwise never show up here. Content never changes after capture, so
   re-scanning it is what makes this work retroactively.
2. **Manually added** — a folder the user browsed to directly (see
   `assistant/manual_projects.py`), for projects that don't happen to show up
   as a ticket-key pattern in captured text. Matched against captured content
   word-by-word (`manual_projects.name_matches_content`) rather than as an
   exact substring, since a folder's name is rarely how people actually refer
   to it in Slack/Jira/conversation — and still listed even with zero matches
   yet (you just added it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from database.json_store import EventStore
from events.project_keys import extract_project_keys

from .manual_projects import ManualProjectRegistry, name_matches_content


@dataclass
class ProjectInfo:
    key: str
    first_seen: str
    last_seen: str
    event_count: int
    path: Optional[str] = None  # set only for manually browsed folders


def list_projects(
    event_store: EventStore, manual_registry: Optional[ManualProjectRegistry] = None
) -> List[ProjectInfo]:
    """Returns known projects, most recently active first."""
    manual_projects = {p.name: p for p in manual_registry.list()} if manual_registry else {}

    stats: Dict[str, Dict[str, object]] = {}

    for event in event_store.query_events(limit=100_000):
        keys = set(extract_project_keys(event.content))
        keys.update(name for name in manual_projects if name_matches_content(name, event.content))

        for key in keys:
            info = stats.setdefault(
                key, {"first_seen": event.timestamp, "last_seen": event.timestamp, "event_count": 0}
            )
            info["event_count"] += 1
            info["first_seen"] = min(info["first_seen"], event.timestamp)
            info["last_seen"] = max(info["last_seen"], event.timestamp)

    # A just-browsed folder with no matching captured activity yet should
    # still show up — otherwise "Browse folder..." would silently do nothing
    # until something happened to mention it.
    for name, project in manual_projects.items():
        stats.setdefault(
            name, {"first_seen": project.added_at, "last_seen": project.added_at, "event_count": 0}
        )

    projects = [
        ProjectInfo(
            key=key,
            first_seen=data["first_seen"],
            last_seen=data["last_seen"],
            event_count=data["event_count"],
            path=manual_projects[key].path if key in manual_projects else None,
        )
        for key, data in stats.items()
    ]
    projects.sort(key=lambda p: p.last_seen, reverse=True)
    return projects
