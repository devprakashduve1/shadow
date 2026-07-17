"""Loads and exposes Shadow's YAML configuration."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "default_settings.yaml"
USER_SETTINGS_PATH = CONFIG_DIR / "settings.local.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings:
    """Dict-like accessor over the merged default + local settings."""

    def __init__(self, path: Path = DEFAULT_SETTINGS_PATH, local_path: Path = USER_SETTINGS_PATH):
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        if local_path.exists():
            with open(local_path, "r") as f:
                local_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, local_data)
        self._data = data

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def as_dict(self) -> dict:
        return copy.deepcopy(self._data)


settings = Settings()
