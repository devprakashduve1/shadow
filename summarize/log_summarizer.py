"""Summarizes DataLogger entries using a local Ollama model (default: gemma4).

Talks to Ollama's REST API directly over HTTP (stdlib `urllib`, no extra
dependency) rather than the `ollama` Python package, so this optional
feature doesn't add a hard dependency for anyone who doesn't use it.

Requires Ollama running locally (`ollama serve`, usually already running via
the Ollama.app) with the configured model already pulled, e.g.:
    ollama pull gemma4

The first call after Ollama (re)starts pays the model's load-into-memory
cost (can be 10+ seconds for an 8B model) on top of actual generation time —
callers should not assume a fast response, especially the first one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Sequence

from logger.data_logger import LogEntry

_SYSTEM_PROMPT = (
    "You summarize a user's captured screen-OCR and speech-transcript activity log "
    "into a short, factual summary. Call out key topics, decisions, action items, "
    "and people mentioned. Only use information present in the entries below — do "
    "not invent details."
)

# Keeps the prompt within a small local model's context window; trims from
# the front so the most recent entries (usually most relevant) survive.
_MAX_ENTRY_CHARS = 12000


class SummarizerError(RuntimeError):
    """Raised when the local Ollama server can't be reached or errors out."""


def _format_entries(entries: Sequence[LogEntry]) -> str:
    lines = []
    for entry in entries:
        time_part = entry.timestamp.split("T")[-1][:8] or entry.timestamp  # HH:MM:SS
        lines.append(f"[{time_part}] ({entry.source}) {entry.text}")
    text = "\n".join(lines)
    if len(text) > _MAX_ENTRY_CHARS:
        text = text[-_MAX_ENTRY_CHARS:]
    return text


class LogSummarizer:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma4",
        timeout_seconds: float = 180.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    def summarize(self, entries: List[LogEntry], instructions: str = "") -> str:
        if not entries:
            return "No log entries to summarize."

        prompt = _SYSTEM_PROMPT
        if instructions.strip():
            prompt += f"\n\nAdditional instructions from the user: {instructions.strip()}"
        prompt += f"\n\nLog entries:\n{_format_entries(entries)}\n\nSummary:"

        payload = json.dumps({"model": self._model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SummarizerError(f"Ollama returned HTTP {exc.code} for model '{self._model}': {detail}") from exc
        except urllib.error.URLError as exc:
            raise SummarizerError(
                f"Could not reach Ollama at {self._base_url} — is `ollama serve` running? ({exc})"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SummarizerError(f"Unexpected response from Ollama: {exc}") from exc

        text = str(data.get("response", "")).strip()
        if not text:
            raise SummarizerError(f"Ollama returned an empty summary: {data}")
        return text
