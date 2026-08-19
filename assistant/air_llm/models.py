"""Data models for phase-wise model loading."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class Phase(IntEnum):
    """Model loading phases."""
    INIT = 0          # No models loaded
    READY = 1         # Fast/lightweight models
    WORKING = 2       # Balanced models
    ADVANCED = 3      # Heavy/capable models


@dataclass
class ModelTier:
    """Definition of models available in a phase."""

    phase: Phase
    name: str                              # "fast", "balanced", "capable"
    models: List[str]                      # Available model names
    use_cases: List[str] = field(default_factory=list)  # e.g., ["chat", "quick_text"]
    size_bytes_estimate: int = 0           # Total memory estimate for tier
    priority: int = 1                      # 1=low, 2=medium, 3=high


@dataclass
class LoadingStrategy:
    """Configuration for phase-wise model loading."""

    phase_on_startup: Phase = Phase.INIT
    auto_advance_phases: bool = True
    max_concurrent_models: int = 2
    unload_unused_after_seconds: Optional[int] = None
    device_profile: str = "standard"
    keep_model_pinned: bool = True         # Use keep_alive=-1 in Ollama
    allow_phase_downgrade: bool = False    # Can go back to earlier phase


@dataclass
class LoadedModel:
    """Represents a currently loaded model."""

    name: str
    phase: Phase
    size_bytes: int = 0
    loaded_at: Optional[str] = None        # ISO 8601 timestamp
    last_used_at: Optional[str] = None


@dataclass
class PhaseTransition:
    """Records a phase advancement or change."""

    from_phase: Phase
    to_phase: Phase
    reason: str                            # "user_requested", "auto_advance", etc.
    timestamp: str = ""                    # ISO 8601
    models_loaded: List[str] = field(default_factory=list)
    models_unloaded: List[str] = field(default_factory=list)
