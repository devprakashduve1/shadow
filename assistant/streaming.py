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
from typing import Iterator


class AssistantError(RuntimeError):
    """Raised when the local Ollama server can't be reached or errors out."""


def stream_chat(
    prompt: str,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 180.0,
) -> Iterator[str]:
    """Yields response text chunks as Ollama generates them.

    `think: False` tells Ollama to skip the reasoning/chain-of-thought pass on
    models that support it (e.g. qwen3.6, deepseek-r1) and go straight to the
    final answer under `response`. Without it, those models stream their
    entire reasoning under a separate `thinking` field — which this function
    doesn't read — while `response` stays empty, so a slow reasoning pass
    that doesn't finish before `timeout_seconds` looks identical to Ollama
    returning nothing at all. Models that don't support thinking ignore the
    field.
    """
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": True, "think": False}
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
