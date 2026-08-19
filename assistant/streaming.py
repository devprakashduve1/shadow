"""Streaming Ollama client for the chat assistant.

Same "stdlib urllib, no extra dependency" approach as
`summarize/log_summarizer.py`, but with `stream: true` — Ollama then responds
with newline-delimited JSON (one object per generated chunk, each with a
`response` fragment and a `done` flag) instead of buffering the whole
generation server-side. Kept separate from `log_summarizer.py` rather than
sharing a client class: the two response-handling loops (read-once-as-JSON vs
iterate-lines-as-NDJSON) don't actually share much beyond request setup and
error handling, and `log_summarizer.py` is working, documented behavior this
change shouldn't risk touching.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterator, Optional


class AssistantError(RuntimeError):
    """Raised when the local Ollama server can't be reached or errors out."""


# Ollama's `keep_alive` controls how long a model stays resident after a
# request. It takes seconds, or a duration string like "5m"; negative means
# "never unload" and 0 means "unload immediately".
#
# These live here, next to the only code that sends them, so that
# `ollama_runtime` can import from this module without an import cycle.
KEEP_ALIVE_PINNED = -1
KEEP_ALIVE_UNLOAD = 0
# What Ollama itself defaults to, and what the app used to inherit: the model is
# evicted five idle minutes after a request, so the next question pays the full
# cold-load cost again.
KEEP_ALIVE_OLLAMA_DEFAULT = "5m"


def resolve_keep_alive():
    """The configured residency policy, as an Ollama `keep_alive` value.

    Read here rather than passed down from the GUI because every AI path reaches
    Ollama through `stream_chat`, but several arrive via helpers that fan out
    internally (`propose_edit` alone calls three). Threading a parameter through
    all of them would mean any missed branch silently ignoring the setting.
    """
    from config import settings

    return (
        KEEP_ALIVE_PINNED
        if settings.get("assistant.keep_model_loaded", True)
        else KEEP_ALIVE_OLLAMA_DEFAULT
    )


def stream_chat(
    prompt: str,
    *,
    base_url: str = "http://localhost:11434",
    model: Optional[str] = None,
    use_case: Optional[str] = None,
    loader=None,
    timeout_seconds: float = 180.0,
    keep_alive=None,
) -> Iterator[str]:
    """Yields response text chunks as Ollama generates them.

    Phase-aware model selection: if `use_case` provided and `loader` available,
    automatically selects appropriate model and advances phases as needed.
    Backward compatible: explicit `model=` parameter still works.

    Args:
        prompt: Input prompt for the model
        base_url: Ollama server URL (default: http://localhost:11434)
        model: Model name (e.g., "gemma4"). If None and use_case provided, uses loader.
        use_case: Use case for phase-aware selection (e.g., "chat", "code_planning")
        loader: PhaseWiseLoader instance for phase-aware selection (optional)
        timeout_seconds: Request timeout (default: 180s)
        keep_alive: Ollama keep_alive value (see resolve_keep_alive)

    Yields:
        Response text chunks as they arrive from Ollama

    Raises:
        AssistantError: If Ollama unreachable or returns error

    Notes:
        - `think: False` skips reasoning on reasoning models (qwen3.6, deepseek-r1)
        - Phase-aware mode: `use_case` + `loader` override explicit `model`
        - Backward compatible: existing code with explicit `model=` unchanged
    """
    # Phase-aware model selection: use_case + loader takes precedence
    if use_case and loader:
        try:
            model = loader.get_model(use_case)
        except Exception:
            # Fall back to explicit model if loader fails
            pass

    # Fallback to default if no model specified
    if not model:
        model = "gemma4"

    if keep_alive is None:
        keep_alive = resolve_keep_alive()
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "keep_alive": keep_alive,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssistantError(f"Ollama returned HTTP {exc.code} for model '{model}': {detail}") from exc
    except urllib.error.URLError as exc:
        raise AssistantError(
            f"Could not reach Ollama at {base_url} — is `ollama serve` running? ({exc})"
        ) from exc

    got_any_chunk = False
    try:
        with response:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise AssistantError(f"Unexpected response from Ollama: {exc}") from exc

                if "error" in data:
                    raise AssistantError(f"Ollama error: {data['error']}")

                chunk = data.get("response", "")
                if chunk:
                    got_any_chunk = True
                    yield chunk
                if data.get("done"):
                    break
    except urllib.error.URLError as exc:
        raise AssistantError(f"Lost connection to Ollama mid-stream: {exc}") from exc

    if not got_any_chunk:
        raise AssistantError("Ollama returned an empty response.")
