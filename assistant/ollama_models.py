"""Discovers which models the local Ollama install actually has.

Replaces a hardcoded list in config: the models someone has pulled are a property
of their machine, not of this repo, so asking Ollama is both more accurate and
one less thing to keep in sync.

## Local vs cloud

Ollama can expose *cloud* models — entries with a `remote_host`, which run on
ollama.com rather than on this machine. Those are excluded by default and it is a
deliberate choice, not an oversight: Shadow captures the user's screen and edits
their source, and its whole premise is that this stays local. Quietly offering a
model that uploads file contents to a third party would break that promise
without the user ever being told. Set `assistant.allow_remote_models: true` to
opt in; they're then clearly labelled `(cloud)`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_BASE_URL = "http://localhost:11434"

# What to select when it's present. Chosen because it's the smallest/fastest of
# the usual pulls, so it's the least frustrating default on a local machine.
PREFERRED_DEFAULT = "gemma4"

# Fallback when Ollama can't be reached — at least the UI has something to show,
# and these are the names the app has always defaulted to.
FALLBACK_MODELS = ("gemma4", "qwen3.6")


@dataclass
class ModelInfo:
    """One model Ollama knows about."""

    name: str  # as Ollama accepts it, e.g. "gemma4" or "qwen3.6:8b"
    size_bytes: int = 0
    parameter_size: str = ""
    family: str = ""
    quantization: str = ""
    modified_at: str = ""
    is_remote: bool = False
    remote_host: str = ""
    capabilities: List[str] = field(default_factory=list)

    @property
    def size_label(self) -> str:
        """Human-readable size, or "cloud" for a remote model.

        A remote model's reported `size` is a placeholder (a few hundred bytes),
        so showing it would be actively misleading.
        """
        if self.is_remote:
            return "cloud"
        if self.size_bytes <= 0:
            return ""
        gigabytes = self.size_bytes / 1_000_000_000
        if gigabytes >= 1:
            return f"{gigabytes:.1f}GB"
        return f"{self.size_bytes / 1_000_000:.0f}MB"

    @property
    def label(self) -> str:
        """Display string for a dropdown: name plus the facts worth comparing."""
        parts = [part for part in (self.parameter_size, self.size_label) if part]
        return f"{self.name}  ({', '.join(parts)})" if parts else self.name

    @property
    def supports_thinking(self) -> bool:
        """True for reasoning models, which stream a chain of thought.

        Worth knowing: those emit their reasoning in a separate `thinking` field
        and leave `response` empty until it finishes, which is why
        `streaming.stream_chat` sends `think: false`.
        """
        return "thinking" in self.capabilities

    @property
    def supports_vision(self) -> bool:
        return "vision" in self.capabilities


def normalize_name(name: str) -> str:
    """Drops a redundant `:latest` tag.

    Ollama treats `gemma4` and `gemma4:latest` as the same model, and the bare
    form is what this app's config has always used — so normalising keeps a
    configured default matching a discovered model.
    """
    return name[: -len(":latest")] if name.endswith(":latest") else name


def _parse_model(entry: dict) -> Optional[ModelInfo]:
    raw_name = entry.get("name") or entry.get("model") or ""
    if not raw_name:
        return None
    details = entry.get("details") or {}
    remote_host = entry.get("remote_host") or ""
    return ModelInfo(
        name=normalize_name(raw_name),
        size_bytes=int(entry.get("size") or 0),
        parameter_size=str(details.get("parameter_size") or ""),
        family=str(details.get("family") or ""),
        quantization=str(details.get("quantization_level") or ""),
        modified_at=str(entry.get("modified_at") or ""),
        is_remote=bool(remote_host),
        remote_host=remote_host,
        capabilities=list(entry.get("capabilities") or []),
    )


def list_models(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 5.0,
    include_remote: bool = False,
) -> List[ModelInfo]:
    """Returns the models Ollama has, newest first.

    Returns an empty list rather than raising when Ollama isn't running — a
    missing model list is a UI inconvenience, not an error worth interrupting
    anything for. The timeout is deliberately short: this runs while the user is
    waiting to see a dropdown.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return []

    models: List[ModelInfo] = []
    for entry in payload.get("models") or []:
        if not isinstance(entry, dict):
            continue
        info = _parse_model(entry)
        if info is None:
            continue
        if info.is_remote and not include_remote:
            continue
        models.append(info)

    # Most recently pulled first — that's usually what someone is experimenting
    # with. Ties break by name so the order is stable.
    models.sort(key=lambda m: (m.modified_at, m.name), reverse=True)
    return models


def model_names(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 5.0,
    include_remote: bool = False,
) -> List[str]:
    """Just the names, for callers that don't need the metadata."""
    return [model.name for model in list_models(base_url, timeout_seconds, include_remote)]


def choose_default(
    models: List[str], preferred: str = PREFERRED_DEFAULT
) -> Optional[str]:
    """Picks which model to preselect.

    `preferred` wins if present (exactly, or ignoring a `:tag` suffix so a
    configured `gemma4` still matches a pulled `gemma4:8b`). Otherwise falls back
    to the first entry rather than leaving nothing selected.
    """
    if not models:
        return None
    normalized_preferred = normalize_name(preferred)
    if normalized_preferred in models:
        return normalized_preferred
    for name in models:
        if name.split(":", 1)[0] == normalized_preferred.split(":", 1)[0]:
            return name
    return models[0]


def resolve_choices(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 5.0,
    include_remote: bool = False,
    fallback: Optional[List[str]] = None,
) -> List[ModelInfo]:
    """Returns models to offer, synthesising a fallback list if Ollama is down.

    Fallback entries carry no metadata — they're names the app can still *try*,
    since Ollama may simply have not been running when we asked.
    """
    models = list_models(base_url, timeout_seconds, include_remote)
    if models:
        return models
    names = fallback if fallback is not None else list(FALLBACK_MODELS)
    return [ModelInfo(name=normalize_name(name)) for name in names]
