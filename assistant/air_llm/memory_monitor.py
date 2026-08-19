"""Memory monitoring utilities."""

from typing import Optional
import psutil


class MemoryMonitor:
    """Monitors system and Ollama memory usage."""

    @staticmethod
    def get_system_memory_gb() -> dict:
        """Get system memory information.

        Returns:
            dict with keys:
                - total_gb: Total system RAM
                - available_gb: Available RAM
                - used_gb: Used RAM
                - percent: Percent of RAM used
        """
        vm = psutil.virtual_memory()
        return {
            "total_gb": vm.total / 1e9,
            "available_gb": vm.available / 1e9,
            "used_gb": vm.used / 1e9,
            "percent": vm.percent,
        }

    @staticmethod
    def get_available_memory_gb() -> float:
        """Get available system memory in GB.

        Returns:
            Available RAM in gigabytes
        """
        return psutil.virtual_memory().available / 1e9

    @staticmethod
    def get_total_memory_gb() -> float:
        """Get total system memory in GB.

        Returns:
            Total RAM in gigabytes
        """
        return psutil.virtual_memory().total / 1e9

    @staticmethod
    def is_memory_sufficient(required_gb: float, safety_margin_gb: float = 2.0) -> bool:
        """Check if sufficient memory is available.

        Args:
            required_gb: Required memory in GB
            safety_margin_gb: Safety margin to keep free (default 2GB)

        Returns:
            True if enough memory available with margin
        """
        available = MemoryMonitor.get_available_memory_gb()
        return available >= (required_gb + safety_margin_gb)

    @staticmethod
    def get_memory_pressure() -> str:
        """Assess current memory pressure.

        Returns:
            "low", "moderate", or "high"
        """
        percent = psutil.virtual_memory().percent
        if percent < 50:
            return "low"
        elif percent < 75:
            return "moderate"
        else:
            return "high"

    @staticmethod
    def estimate_model_size(model_name: str) -> Optional[float]:
        """Estimate model size in GB based on common models.

        Args:
            model_name: Model name (e.g., "qwen2.5:7b")

        Returns:
            Estimated size in GB, or None if unknown

        Note:
            This is a rough estimate; actual size varies by quantization.
        """
        # Common model size estimates (for q4_0 quantization)
        model_sizes = {
            "gemma2:2b": 1.5,
            "qwen2.5:1.5b": 1.2,
            "qwen2.5:7b": 4.5,
            "codellama:7b": 5.0,
            "deepseek-coder:34b": 18.0,
            "qwen:32b": 20.0,
        }

        # Try exact match
        if model_name in model_sizes:
            return model_sizes[model_name]

        # Try to parse from name (e.g., "gemma:7b" -> ~5GB)
        try:
            if ":2b" in model_name:
                return 1.5
            elif ":7b" in model_name:
                return 4.5
            elif ":13b" in model_name:
                return 8.0
            elif ":34b" in model_name:
                return 18.0
            elif ":70b" in model_name or ":32b" in model_name:
                return 20.0
        except Exception:
            pass

        return None
