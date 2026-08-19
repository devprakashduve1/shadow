"""Phase-wise model loading orchestrator."""

from typing import Dict, List, Optional, Set
from datetime import datetime

from .models import Phase, LoadingStrategy, LoadedModel, PhaseTransition
from .device_profile import DeviceProfileManager
from .phase_registry import PhaseRegistry
from .memory_monitor import MemoryMonitor
from .exceptions import (
    PhaseLoadError,
    DeviceConstraintError,
    ModelNotFoundError,
    OllamaConnectionError,
)


class PhaseWiseLoader:
    """Main orchestrator for phase-wise model loading.

    Manages progressive model loading across phases based on device profile and task requirements.
    Automatically advances phases when needed and manages model memory.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        device_profile: Optional[str] = None,
        auto_detect_device: bool = True,
    ):
        """Initialize phase-wise loader.

        Args:
            ollama_url: Ollama server URL
            device_profile: Device profile ("limited", "standard", "performance")
                          If None and auto_detect_device=True, auto-detects
            auto_detect_device: Auto-detect device profile from available RAM
        """
        self.ollama_url = ollama_url
        self.auto_detect_device = auto_detect_device

        # Auto-detect device profile if not provided
        if device_profile is None and auto_detect_device:
            available_ram = MemoryMonitor.get_available_memory_gb()
            device_profile = DeviceProfileManager.auto_detect_profile(available_ram)

        self.device_profile = device_profile or "standard"
        if self.device_profile not in DeviceProfileManager.list_profiles():
            raise ValueError(f"Unknown device profile: {self.device_profile}")

        # Initialize state
        self.current_phase = Phase.INIT
        self.loaded_models: Dict[str, LoadedModel] = {}
        self.phase_models: Dict[Phase, str] = {}  # Current model for each phase
        self.transitions: List[PhaseTransition] = []

        # Load device profile
        self.profile_config = DeviceProfileManager.get_profile_config(self.device_profile)

        # Set default models for each phase from profile
        for phase in [Phase.READY, Phase.WORKING, Phase.ADVANCED]:
            models = DeviceProfileManager.get_models_for_phase(self.device_profile, phase)
            if models:
                self.phase_models[phase] = models[0]  # Use first available

    def get_model(self, use_case: str) -> str:
        """Get a model for a use case, auto-loading if needed.

        This is the main entry point. It:
        1. Determines the phase for the use case
        2. Advances to that phase if needed
        3. Returns the appropriate model name

        Args:
            use_case: Use case identifier (e.g., "chat", "code_planning")

        Returns:
            Model name suitable for the use case

        Raises:
            KeyError: If use case not registered
            DeviceConstraintError: If phase can't run on this device
            PhaseLoadError: If model can't be loaded
        """
        # Determine target phase
        target_phase = PhaseRegistry.get_phase_for_use_case(use_case)

        # Advance to target phase if needed
        if target_phase > self.current_phase:
            self._advance_to_phase(target_phase, reason="auto_advance")

        # Return the model for this phase
        return self._get_phase_model(target_phase)

    def advance_phase(self, target_phase: Phase) -> None:
        """Manually advance to a phase.

        Args:
            target_phase: Target phase

        Raises:
            DeviceConstraintError: If phase unavailable on this device
        """
        if target_phase not in self.profile_config["available_phases"]:
            raise DeviceConstraintError(
                f"Phase {target_phase} not available on '{self.device_profile}' profile"
            )
        self._advance_to_phase(target_phase, reason="user_requested")

    def get_current_phase(self) -> Phase:
        """Get current phase.

        Returns:
            Current phase enumeration
        """
        return self.current_phase

    def get_loaded_models(self) -> List[str]:
        """Get currently loaded models.

        Returns:
            List of model names in memory
        """
        return list(self.loaded_models.keys())

    def set_phase_model(self, phase: Phase, model: str) -> None:
        """Set which model to use for a phase.

        Allows users to customize model selection per phase.

        Args:
            phase: Target phase
            model: Model name

        Raises:
            ValueError: If phase doesn't support this model
        """
        available = DeviceProfileManager.get_models_for_phase(self.device_profile, phase)
        if model not in available and model != "":
            raise ValueError(
                f"Model '{model}' not available for phase {phase} on '{self.device_profile}' profile. "
                f"Available: {available}"
            )
        self.phase_models[phase] = model

    def unload_model(self, model: str) -> None:
        """Unload a specific model from memory.

        Args:
            model: Model name to unload
        """
        if model in self.loaded_models:
            del self.loaded_models[model]

    def unload_all(self) -> List[str]:
        """Unload all models from memory.

        Returns:
            List of unloaded model names
        """
        unloaded = list(self.loaded_models.keys())
        self.loaded_models.clear()
        return unloaded

    def get_phase_info(self) -> Dict:
        """Get detailed information about current state.

        Returns:
            Dictionary with phase info:
                - current_phase: Current phase number and name
                - device_profile: Device profile in use
                - loaded_models: List of loaded models
                - max_concurrent: Max models this device can load
                - available_phases: Phases available on this device
        """
        return {
            "current_phase": self.current_phase,
            "device_profile": self.device_profile,
            "loaded_models": self.get_loaded_models(),
            "max_concurrent": self.profile_config["max_loaded_models"],
            "available_phases": self.profile_config["available_phases"],
            "total_transitions": len(self.transitions),
        }

    def get_memory_info(self) -> Dict:
        """Get memory usage information.

        Returns:
            Dictionary with memory stats:
                - system_total_gb: Total system RAM
                - system_available_gb: Available system RAM
                - system_used_percent: Percent of RAM used
                - pressure: "low", "moderate", or "high"
        """
        mem = MemoryMonitor.get_system_memory_gb()
        return {
            "system_total_gb": mem["total_gb"],
            "system_available_gb": mem["available_gb"],
            "system_used_gb": mem["used_gb"],
            "system_used_percent": mem["percent"],
            "pressure": MemoryMonitor.get_memory_pressure(),
        }

    def list_available_models(self) -> Dict[str, List[str]]:
        """List available models per phase for this device.

        Returns:
            Dictionary mapping phase -> list of model names
        """
        return {
            str(phase): DeviceProfileManager.get_models_for_phase(self.device_profile, phase)
            for phase in self.profile_config["available_phases"]
        }

    # Private methods

    def _advance_to_phase(self, target_phase: Phase, reason: str = "auto_advance") -> None:
        """Internal method to advance to a phase.

        Handles:
        - Checking device constraints
        - Unloading incompatible models
        - Recording transitions

        Args:
            target_phase: Target phase
            reason: Reason for transition
        """
        # Check device supports this phase
        if target_phase not in self.profile_config["available_phases"]:
            raise DeviceConstraintError(
                f"Phase {target_phase} not available on '{self.device_profile}' profile. "
                f"Available phases: {self.profile_config['available_phases']}"
            )

        # No-op if already at phase
        if target_phase == self.current_phase:
            return

        # Record transition
        models_unloaded = []
        if target_phase < self.current_phase:
            # Downgrading: unload higher phase models
            for phase in range(target_phase + 1, Phase.ADVANCED + 1):
                if self.phase_models.get(phase) in self.loaded_models:
                    model = self.phase_models[phase]
                    models_unloaded.append(model)
                    self.unload_model(model)
        else:
            # Upgrading: might unload lower phase if memory constrained
            max_models = self.profile_config["max_loaded_models"]
            if len(self.loaded_models) >= max_models:
                # Unload Phase 1 model to make room if advancing beyond Phase 1
                if Phase.READY in self.phase_models:
                    model = self.phase_models[Phase.READY]
                    if model in self.loaded_models:
                        models_unloaded.append(model)
                        self.unload_model(model)

        # Update current phase
        old_phase = self.current_phase
        self.current_phase = target_phase

        # Record transition
        self.transitions.append(
            PhaseTransition(
                from_phase=old_phase,
                to_phase=target_phase,
                reason=reason,
                timestamp=datetime.now().isoformat(),
                models_unloaded=models_unloaded,
                models_loaded=[self._get_phase_model(target_phase)],
            )
        )

    def _get_phase_model(self, phase: Phase) -> str:
        """Get the model name for a phase.

        Args:
            phase: Target phase

        Returns:
            Model name

        Raises:
            PhaseLoadError: If no model available for phase
        """
        if phase not in self.phase_models:
            # Try to get first available model for this phase
            models = DeviceProfileManager.get_models_for_phase(self.device_profile, phase)
            if not models:
                raise PhaseLoadError(f"No models available for phase {phase} on device '{self.device_profile}'")
            self.phase_models[phase] = models[0]

        model = self.phase_models[phase]

        # Mark as loaded (in production, would actually load via Ollama)
        if model and model not in self.loaded_models:
            self.loaded_models[model] = LoadedModel(
                name=model,
                phase=phase,
                loaded_at=datetime.now().isoformat(),
            )

        return model
