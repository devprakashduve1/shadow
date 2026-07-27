"""Crash-safe JSON and JSONL writes.

Every other write in this codebase is a bare ``open(path, "w")`` — fine for the
append-only event logs, but not for state that is read back and relied on: a
crash or a full disk mid-write leaves a truncated file that fails to parse, and
the data is simply gone.

Deliberately dependency-free (stdlib only, no imports from elsewhere in
`assistant/`) so `database/json_store.py` can adopt it later without a circular
import.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Union


def write_json_atomic(path: Union[str, Path], payload: Any, indent: Optional[int] = 2) -> Path:
    """Serializes `payload` to `path` atomically.

    Serializes to a string *before* touching the filesystem, so a payload
    containing something unserializable raises without having created or
    truncated anything.

    The temp file is created in the destination directory so `os.replace` stays
    within one filesystem, where it is atomic; a temp file in /tmp would make the
    final step a cross-device copy, which is not.
    """
    target = Path(path).expanduser()
    text = json.dumps(payload, indent=indent, ensure_ascii=False)

    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(target.parent),
        prefix=f".{target.name}.", suffix=".tmp", delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            # fsync before the rename: without it the rename can be durable
            # while the contents are still only in the page cache, which after a
            # hard crash yields an empty-but-present file.
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(target))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return target


def read_json(path: Union[str, Path], default: Any = None) -> Any:
    """Reads JSON, returning `default` if the file is missing or unparseable.

    Tolerant on purpose: these files are a cache, so a corrupt one should mean
    "rebuild it", not a crash on startup. Atomic writes make corruption
    near-impossible anyway, but a file could predate this module or have been
    edited by hand.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        return default
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return default


def append_jsonl(path: Union[str, Path], record: Any) -> Path:
    """Appends one JSON record as a line.

    Not atomic in the rename sense, and doesn't need to be: a single `write()`
    of a short line under `O_APPEND` won't interleave with other appends, and a
    torn final line only costs the last record — which `read_jsonl` skips. That
    is the right trade for an append-only audit log, where rewriting the whole
    file per entry would be far worse.
    """
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def read_jsonl(path: Union[str, Path]) -> list:
    """Reads a JSONL file, skipping any line that doesn't parse."""
    target = Path(path).expanduser()
    if not target.is_file():
        return []
    records = []
    try:
        with open(target, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn last line, or hand-edited — skip it
    except (UnicodeDecodeError, OSError):
        return records
    return records
