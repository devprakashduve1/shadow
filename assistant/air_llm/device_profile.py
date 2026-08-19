"""Device profile detection and configuration."""

from typing import Dict, List, Optional
from .models import Phase


class DeviceProfileManager:
    """Manages device profiles and model configurations per profile."""

    PROFILES = {
        "limited": {
            "description": "< 4GB RAM or older device",
            "available_phases": [Phase.INIT, Phase.READY],
            "phase_models": {
                Phase.INIT: [],
                Phase.READY: ["gemma2:2b"],
                Phase.WORKING: [],
                Phase.ADVANCED: [],
            },
            "max_loaded_models": 1,
            "unload_timeout_seconds": 120,
            "estimated_free_ram_gb": 2.0,
        },
        "standard": {
            "description": "8-16GB RAM, modern laptop",
            "available_phases": [Phase.INIT, Phase.READY, Phase.WORKING],
            "phase_models": {
                Phase.INIT: [],
                Phase.READY: ["gemma2:2b"],
                Phase.WORKING: ["qwen2.5:7b"],
                Phase.ADVANCED: [],
            },
            "max_loaded_models": 2,
            "unload_timeout_seconds": 300,
            "estimated_free_ram_gb": 6.0,
        },
        "performance": {
            "description": "16GB+ RAM, high-end desktop/workstation",
            "available_phases": [Phase.INIT, Phase.READY, Phase.WORKING, Phase.ADVANCED],
            "phase_models": {
                Phase.INIT: [],
                Phase.READY: ["gemma2:2b"],
                Phase.WORKING: ["qwen2.5:7b"],
                Phase.ADVANCED: ["deepseek-coder:34b"],
            },
            "max_loaded_models": 3,
            "unload_timeout_seconds": 600,
            "estimated_free_ram_gb": 12.0,
        },
    }

    @staticmethod
    def auto_detect_profile(available_ram_gb: float) -> str:
        """Auto-detect device profile based on available RAM.

        Args:
            available_ram_gb: Available RAM in gigabytes

        Returns:
            Profile name: "limited", "standard", or "performance"
        """
        if available_ram_gb < 4:
            return "limited"
        elif available_ram_gb < 16:
            return "standard"
        else:
            return "performance"

    @staticmethod
    def get_profile_config(profile: str) -> Dict:
        """Get configuration for a device profile.

        Args:
            profile: Profile name ("limited", "standard", "performance")

        Returns:
            Profile configuration dictionary

        Raises:
            ValueError: If profile is not recognized
        """
        if profile not in DeviceProfileManager.PROFILES:
            raise ValueError(f"Unknown profile: {profile}")
        return DeviceProfileManager.PROFILES[profile]

    @staticmethod
    def get_models_for_phase(profile: str, phase: Phase) -> List[str]:
        """Get available models for a phase in a profile.

        Args:
            profile: Profile name
            phase: Target phase

        Returns:
            List of model names available in this phase for this profile
        """
        config = DeviceProfileManager.get_profile_config(profile)
        return config["phase_models"].get(phase, [])

    @staticmethod
    def can_load_phase(profile: str, phase: Phase) -> bool:
        """Check if a phase can be loaded in this profile.

        Args:
            profile: Profile name
            phase: Target phase

        Returns:
            True if phase is available in profile
        """
        config = DeviceProfileManager.get_profile_config(profile)
        return phase in config["available_phases"]

    @staticmethod
    def get_max_concurrent_models(profile: str) -> int:
        """Get max number of models that can be loaded concurrently.

        Args:
            profile: Profile name

        Returns:
            Maximum number of concurrent models
        """
        config = DeviceProfileManager.get_profile_config(profile)
        return config["max_loaded_models"]

    @staticmethod
    def get_estimated_free_ram(profile: str) -> float:
        """Get estimated safe free RAM for this profile.

        Args:
            profile: Profile name

        Returns:
            Estimated free RAM in GB after accounting for OS and app overhead
        """
        config = DeviceProfileManager.get_profile_config(profile)
        return config["estimated_free_ram_gb"]

    @staticmethod
    def list_profiles() -> List[str]:
        """List all available device profiles.

        Returns:
            List of profile names
        """
        return list(DeviceProfileManager.PROFILES.keys())
