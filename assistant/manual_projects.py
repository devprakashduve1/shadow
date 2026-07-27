"""Manually-added Coding Agent projects — folders the user browsed to and
picked directly (the Code tab's "Open Repo..." button
button), as opposed to auto-detected ticket-key projects
(`events/project_keys.py`).

Unlike ticket-key projects, a browsed folder isn't derivable by re-scanning
`events` — nothing in captured activity necessarily proves you picked this
folder — so it needs actual storage. Still just a JSON file, no database,
same as everything else under `output/`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Union

_WORD_RE = re.compile(r"[a-z0-9]+")


def name_matches_content(name: str, content: str) -> bool:
    """True if every significant word in `name` shows up in `content`.

    A repo/folder's directory name is usually kebab-case or snake_case
    (e.g. "user-profile-mfe") and rarely appears verbatim like that in
    captured Slack/Jira/editor text, which is far more likely to say
    something like "User Profile MFE" — different casing, spaces instead
    of hyphens, maybe reordered. Requiring an exact contiguous substring match
    (the original approach) missed all of that. This instead splits the name
    into words on any non-alphanumeric character and requires each one to
    appear as its own token somewhere in `content`, tokenized the same way —
    case-insensitively, regardless of order or separator style. Content is
    tokenized rather than checked with a regex `\\bword\\b`: `\\b` treats
    underscores as word characters, so it would fail to split
    "user_profile_mfe" into separate words the way this needs to.
    """
    words = _WORD_RE.findall(name.lower())
    if not words:
        return False
    content_words = set(_WORD_RE.findall(content.lower()))
    return all(word in content_words for word in words)


@dataclass
class ManualProject:
    name: str  # the folder's basename — used as its project identity/key
    path: str
    added_at: str


class ManualProjectRegistry:
    def __init__(self, path: Union[str, Path] = "output/events/manual_projects.json"):
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> List[dict]:
        if not self._path.exists():
            return []
        with open(self._path) as f:
            return json.load(f)

    def _save(self, items: List[dict]) -> None:
        with open(self._path, "w") as f:
            json.dump(items, f, indent=2)

    def list(self) -> List[ManualProject]:
        return [ManualProject(**item) for item in self._load()]

    def add(self, folder_path: Union[str, Path]) -> ManualProject:
        """Adds `folder_path` as a project, keyed by its folder name. Idempotent."""
        resolved = str(Path(folder_path).expanduser())
        items = self._load()
        for item in items:
            if item["path"] == resolved:
                return ManualProject(**item)  # already added

        project = ManualProject(name=Path(resolved).name, path=resolved, added_at=datetime.now().isoformat())
        items.append(project.__dict__)
        self._save(items)
        return project

    def remove(self, name: str) -> None:
        items = [item for item in self._load() if item["name"] != name]
        self._save(items)
