"""AiR LLM - Phase-Wise Model Loading Library

Progressive, intelligent model loading for local LLM inference with Ollama.
Automatically manages model lifecycle across four phases based on task complexity
and device capabilities.

Quick Start:
    from assistant.air_llm import PhaseWiseLoader

    loader = PhaseWiseLoader(device_profile="standard")
    model = loader.get_model("chat")           # Phase 1: lightweight
    model = loader.get_model("code_planning")  # Phase 2: auto-advance

Features:
    - Phase-based model loading (0=Init, 1=Ready, 2=Working, 3=Advanced)
    - Automatic device profile detection (limited/standard/performance)
    - Intelligent memory management and model unloading
    - Backward compatible with existing code
    - Per-phase model customization via UI
"""

from .core import PhaseWiseLoader
from .models import ModelTier, LoadingStrategy, Phase
from .device_profile import DeviceProfileManager
from .exceptions import AiRLLMError, PhaseLoadError, DeviceConstraintError

__all__ = [
    "PhaseWiseLoader",
    "ModelTier",
    "LoadingStrategy",
    "Phase",
    "DeviceProfileManager",
    "AiRLLMError",
    "PhaseLoadError",
    "DeviceConstraintError",
]

__version__ = "1.0.0"
