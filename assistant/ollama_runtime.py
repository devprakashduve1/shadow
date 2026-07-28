"""Controls which models Ollama keeps resident in memory.

The app pins models by default (see `streaming.stream_chat`'s `keep_alive`), so
a session loads a model once instead of paying the cold-load cost every few
minutes. The flip side is that a pinned model holds its memory until something
releases it — which is what this module is for:

- `loaded_models` — what Ollama currently has in memory, via `/api/ps`.
- `unload_model` — release one model now.
- `unload_all` — release everything, the "give me my RAM back" action.

Same stdlib-urllib, no-extra-dependency approach as `streaming.py`, and it
raises that module's `AssistantError` so callers have one error type to handle.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

from .streaming import KEEP_ALIVE_UNLOAD, AssistantError

DEFAULT_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class LoadedModel:
    """A model Ollama reports as currently resident."""

    name: str
    size_bytes: int = 0
    # Ollama's own eviction deadline. A pinned model reports a date far in the
    # future rather than a null, so this is informational only — never parsed to
    # decide whether the model is loaded.
    expires_at: str = ""

    @property
    def size_label(self) -> str:
        if self.size_bytes <= 0:
            return ""
        gb = self.size_bytes / 1_000_000_000
        return f"{gb:.1f}GB" if gb >= 0.1 else f"{self.size_bytes / 1_000_000:.0f}MB"


def _post_json(url: str, payload: dict, timeout_seconds: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssistantError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AssistantError(
            f"Could not reach Ollama at {url} — is `ollama serve` running? ({exc})"
        ) from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Unloading only needs the request to have been accepted; an
        # unparseable body isn't worth failing over.
        return {}


def loaded_models(
    base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 10.0
) -> List[LoadedModel]:
    """Returns the models Ollama currently holds in memory.

    An empty list means nothing is loaded — which is also what a reachable
    server with an idle GPU reports, so it isn't treated as an error.
    """
    url = f"{base_url.rstrip('/')}/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise AssistantError(f"Ollama returned HTTP {exc.code} for /api/ps") from exc
    except urllib.error.URLError as exc:
        raise AssistantError(
            f"Could not reach Ollama at {base_url} — is `ollama serve` running? ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise AssistantError(f"Unexpected response from Ollama's /api/ps: {exc}") from exc

    models = []
    for entry in data.get("models") or []:
        # Ollama reports both `name` and `model`; either identifies it, and
        # which one is populated has varied between versions.
        name = entry.get("name") or entry.get("model") or ""
        if not name:
            continue
        models.append(
            LoadedModel(
                name=name,
                size_bytes=int(entry.get("size") or 0),
                expires_at=str(entry.get("expires_at") or ""),
            )
        )
    return models


def unload_model(
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 30.0,
) -> None:
    """Releases `model` from memory immediately.

    Implemented as a generate call with an empty prompt and `keep_alive: 0`,
    which is Ollama's documented way to evict: there's no dedicated unload
    endpoint. The empty prompt means nothing is generated, so this returns as
    soon as the model has been dropped.
    """
    if not model:
        return
    _post_json(
        f"{base_url.rstrip('/')}/api/generate",
        {"model": model, "prompt": "", "stream": False, "keep_alive": KEEP_ALIVE_UNLOAD},
        timeout_seconds,
    )


def _wait_until_released(
    names: List[str], base_url: str, deadline_seconds: float, timeout_seconds: float
) -> None:
    """Blocks briefly until `names` are gone from Ollama's resident set.

    Ollama accepts an eviction and returns before the model has actually been
    dropped — measured at roughly 200ms between the two. Without this wait,
    anything that queries residency straight after unloading still sees the old
    model. Bounded so a server that never releases can't hang the caller.
    """
    end = time.monotonic() + deadline_seconds
    wanted = set(names)
    while time.monotonic() < end:
        try:
            still_there = {m.name for m in loaded_models(base_url, timeout_seconds)}
        except AssistantError:
            return  # the unload itself succeeded; confirmation is best-effort
        if not (wanted & still_there):
            return
        time.sleep(0.1)


def unload_all(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 30.0,
    only: Optional[str] = None,
    confirm_seconds: float = 3.0,
) -> List[str]:
    """Unloads resident models, returning the ones asked to release.

    Defaults to everything rather than just the selected model on purpose:
    switching models mid-session leaves the previous one pinned and invisible,
    so "unload" meaning "free all of it" is both what a user wants from that
    button and the thing that prevents a slow memory creep. Pass `only` to
    target a single model.

    Waits briefly for the eviction to take effect (see `_wait_until_released`)
    so that the memory really is free by the time this returns. Set
    `confirm_seconds` to 0 to skip that.
    """
    resident = loaded_models(base_url, timeout_seconds)
    targets = [m.name for m in resident if only is None or m.name == only]
    for name in targets:
        unload_model(name, base_url, timeout_seconds)
    if targets and confirm_seconds > 0:
        _wait_until_released(targets, base_url, confirm_seconds, timeout_seconds)
    return targets
