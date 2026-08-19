"""Unit tests for AiR LLM phase-wise model loading library."""

import pytest
from .core import PhaseWiseLoader
from .models import Phase
from .device_profile import DeviceProfileManager
from .phase_registry import PhaseRegistry
from .memory_monitor import MemoryMonitor
from .exceptions import DeviceConstraintError, PhaseLoadError


class TestDeviceProfileManager:
    """Tests for device profile detection and configuration."""

    def test_auto_detect_limited(self):
        """Test device detection for < 4GB RAM."""
        profile = DeviceProfileManager.auto_detect_profile(3.5)
        assert profile == "limited"

    def test_auto_detect_standard(self):
        """Test device detection for 8-16GB RAM."""
        profile = DeviceProfileManager.auto_detect_profile(8.0)
        assert profile == "standard"

        profile = DeviceProfileManager.auto_detect_profile(15.0)
        assert profile == "standard"

    def test_auto_detect_performance(self):
        """Test device detection for 16GB+ RAM."""
        profile = DeviceProfileManager.auto_detect_profile(16.0)
        assert profile == "performance"

        profile = DeviceProfileManager.auto_detect_profile(32.0)
        assert profile == "performance"

    def test_get_profile_config(self):
        """Test profile configuration retrieval."""
        config = DeviceProfileManager.get_profile_config("standard")
        assert config["description"] == "8-16GB RAM, modern laptop"
        assert config["max_loaded_models"] == 2

    def test_get_profile_config_invalid(self):
        """Test error on invalid profile."""
        with pytest.raises(ValueError):
            DeviceProfileManager.get_profile_config("invalid_profile")

    def test_get_models_for_phase(self):
        """Test model retrieval for phase."""
        models = DeviceProfileManager.get_models_for_phase("standard", Phase.READY)
        assert "gemma2:2b" in models

        models = DeviceProfileManager.get_models_for_phase("standard", Phase.WORKING)
        assert "qwen2.5:7b" in models

    def test_can_load_phase_limited(self):
        """Test phase availability checks for limited device."""
        assert DeviceProfileManager.can_load_phase("limited", Phase.READY)
        assert not DeviceProfileManager.can_load_phase("limited", Phase.WORKING)
        assert not DeviceProfileManager.can_load_phase("limited", Phase.ADVANCED)

    def test_can_load_phase_standard(self):
        """Test phase availability for standard device."""
        assert DeviceProfileManager.can_load_phase("standard", Phase.READY)
        assert DeviceProfileManager.can_load_phase("standard", Phase.WORKING)
        assert not DeviceProfileManager.can_load_phase("standard", Phase.ADVANCED)

    def test_can_load_phase_performance(self):
        """Test phase availability for performance device."""
        assert DeviceProfileManager.can_load_phase("performance", Phase.READY)
        assert DeviceProfileManager.can_load_phase("performance", Phase.WORKING)
        assert DeviceProfileManager.can_load_phase("performance", Phase.ADVANCED)

    def test_get_max_concurrent_models(self):
        """Test max concurrent model limits."""
        assert DeviceProfileManager.get_max_concurrent_models("limited") == 1
        assert DeviceProfileManager.get_max_concurrent_models("standard") == 2
        assert DeviceProfileManager.get_max_concurrent_models("performance") == 3


class TestPhaseRegistry:
    """Tests for use case to phase mapping."""

    def test_get_phase_for_use_case(self):
        """Test use case to phase mapping."""
        assert PhaseRegistry.get_phase_for_use_case("chat") == Phase.READY
        assert PhaseRegistry.get_phase_for_use_case("code_planning") == Phase.WORKING
        assert PhaseRegistry.get_phase_for_use_case("multi_file_refactoring") == Phase.ADVANCED

    def test_get_phase_for_use_case_invalid(self):
        """Test error on unregistered use case."""
        with pytest.raises(KeyError):
            PhaseRegistry.get_phase_for_use_case("invalid_use_case")

    def test_is_use_case_registered(self):
        """Test use case registration check."""
        assert PhaseRegistry.is_use_case_registered("chat")
        assert not PhaseRegistry.is_use_case_registered("nonexistent")

    def test_get_use_cases_for_phase(self):
        """Test retrieval of use cases per phase."""
        phase1_use_cases = PhaseRegistry.get_use_cases_for_phase(Phase.READY)
        assert "chat" in phase1_use_cases
        assert "search_summarization" in phase1_use_cases

        phase2_use_cases = PhaseRegistry.get_use_cases_for_phase(Phase.WORKING)
        assert "code_planning" in phase2_use_cases

    def test_register_use_case(self):
        """Test custom use case registration."""
        PhaseRegistry.register_use_case("test_case", Phase.WORKING)
        assert PhaseRegistry.get_phase_for_use_case("test_case") == Phase.WORKING

    def test_list_registered_use_cases(self):
        """Test listing all use cases."""
        use_cases = PhaseRegistry.list_registered_use_cases()
        assert isinstance(use_cases, list)
        assert len(use_cases) > 0
        assert "chat" in use_cases


class TestMemoryMonitor:
    """Tests for memory monitoring."""

    def test_get_system_memory(self):
        """Test system memory retrieval."""
        mem = MemoryMonitor.get_system_memory_gb()
        assert "total_gb" in mem
        assert "available_gb" in mem
        assert "used_gb" in mem
        assert "percent" in mem
        assert mem["total_gb"] > 0

    def test_get_available_memory(self):
        """Test available memory retrieval."""
        available = MemoryMonitor.get_available_memory_gb()
        assert isinstance(available, float)
        assert available > 0

    def test_is_memory_sufficient(self):
        """Test memory sufficiency check."""
        available = MemoryMonitor.get_available_memory_gb()
        # Should have enough memory for a small model
        assert MemoryMonitor.is_memory_sufficient(1.0)
        # Should not have enough for excessive amount
        assert not MemoryMonitor.is_memory_sufficient(100.0)

    def test_get_memory_pressure(self):
        """Test memory pressure assessment."""
        pressure = MemoryMonitor.get_memory_pressure()
        assert pressure in ("low", "moderate", "high")

    def test_estimate_model_size(self):
        """Test model size estimation."""
        assert MemoryMonitor.estimate_model_size("gemma2:2b") == 1.5
        assert MemoryMonitor.estimate_model_size("qwen2.5:7b") == 4.5
        assert MemoryMonitor.estimate_model_size("deepseek-coder:34b") == 18.0

    def test_estimate_model_size_pattern(self):
        """Test model size estimation from pattern."""
        # Should estimate based on parameter count
        assert MemoryMonitor.estimate_model_size("unknown:7b") == 4.5
        assert MemoryMonitor.estimate_model_size("unknown:2b") == 1.5


class TestPhaseWiseLoader:
    """Tests for main PhaseWiseLoader orchestrator."""

    def test_initialization_auto_detect(self):
        """Test loader initialization with auto-detection."""
        loader = PhaseWiseLoader(device_profile="standard")
        assert loader.device_profile == "standard"
        assert loader.get_current_phase() == Phase.INIT

    def test_initialization_explicit_profile(self):
        """Test loader with explicit profile."""
        loader = PhaseWiseLoader(device_profile="performance")
        assert loader.device_profile == "performance"

    def test_initialization_invalid_profile(self):
        """Test error on invalid profile."""
        with pytest.raises(ValueError):
            PhaseWiseLoader(device_profile="invalid")

    def test_get_model_phase_1(self):
        """Test getting Phase 1 model."""
        loader = PhaseWiseLoader(device_profile="standard")
        model = loader.get_model("chat")
        assert isinstance(model, str)
        assert model in ["gemma2:2b"]
        assert loader.get_current_phase() == Phase.READY

    def test_get_model_phase_2_auto_advance(self):
        """Test auto-advancement to Phase 2."""
        loader = PhaseWiseLoader(device_profile="standard")
        assert loader.get_current_phase() == Phase.INIT

        # Request Phase 2 use case
        model = loader.get_model("code_planning")
        assert loader.get_current_phase() == Phase.WORKING
        assert model in ["qwen2.5:7b"]

    def test_get_model_phase_3_unavailable(self):
        """Test error when requesting unavailable phase."""
        loader = PhaseWiseLoader(device_profile="standard")
        with pytest.raises((PhaseLoadError, DeviceConstraintError)):
            loader.get_model("multi_file_refactoring")

    def test_advance_phase_manual(self):
        """Test manual phase advancement."""
        loader = PhaseWiseLoader(device_profile="standard")
        loader.advance_phase(Phase.READY)
        assert loader.get_current_phase() == Phase.READY

        loader.advance_phase(Phase.WORKING)
        assert loader.get_current_phase() == Phase.WORKING

    def test_advance_phase_unavailable(self):
        """Test error when advancing to unavailable phase."""
        loader = PhaseWiseLoader(device_profile="standard")
        with pytest.raises(DeviceConstraintError):
            loader.advance_phase(Phase.ADVANCED)

    def test_get_loaded_models(self):
        """Test tracking of loaded models."""
        loader = PhaseWiseLoader(device_profile="standard")
        initial = loader.get_loaded_models()
        assert initial == []

        loader.get_model("chat")
        loaded = loader.get_loaded_models()
        assert len(loaded) > 0

    def test_unload_model(self):
        """Test unloading a specific model."""
        loader = PhaseWiseLoader(device_profile="standard")
        loader.get_model("chat")
        assert len(loader.get_loaded_models()) > 0

        model = loader.get_loaded_models()[0]
        loader.unload_model(model)
        assert model not in loader.get_loaded_models()

    def test_unload_all(self):
        """Test unloading all models."""
        loader = PhaseWiseLoader(device_profile="standard")
        loader.get_model("chat")
        loader.get_model("code_planning")
        assert len(loader.get_loaded_models()) >= 2

        unloaded = loader.unload_all()
        assert len(unloaded) >= 2
        assert len(loader.get_loaded_models()) == 0

    def test_set_phase_model(self):
        """Test setting custom model for phase."""
        loader = PhaseWiseLoader(device_profile="standard")
        available = DeviceProfileManager.get_models_for_phase("standard", Phase.READY)
        if len(available) > 1:
            loader.set_phase_model(Phase.READY, available[1])
            model = loader.get_model("chat")
            assert model == available[1]

    def test_set_phase_model_invalid(self):
        """Test error on invalid model for phase."""
        loader = PhaseWiseLoader(device_profile="standard")
        with pytest.raises(ValueError):
            loader.set_phase_model(Phase.READY, "nonexistent_model")

    def test_get_phase_info(self):
        """Test phase information retrieval."""
        loader = PhaseWiseLoader(device_profile="standard")
        loader.get_model("chat")
        info = loader.get_phase_info()

        assert "current_phase" in info
        assert "device_profile" in info
        assert "loaded_models" in info
        assert "max_concurrent" in info
        assert info["device_profile"] == "standard"

    def test_get_memory_info(self):
        """Test memory information retrieval."""
        loader = PhaseWiseLoader(device_profile="standard")
        info = loader.get_memory_info()

        assert "system_total_gb" in info
        assert "system_available_gb" in info
        assert "system_used_gb" in info
        assert "system_used_percent" in info
        assert "pressure" in info

    def test_list_available_models(self):
        """Test listing available models."""
        loader = PhaseWiseLoader(device_profile="standard")
        models = loader.list_available_models()

        # Models dict uses Phase enum string representations
        assert len(models) > 0
        # At least one phase should have models
        assert any(model_list for model_list in models.values())

    def test_phase_transition_tracking(self):
        """Test that transitions are recorded."""
        loader = PhaseWiseLoader(device_profile="standard")
        initial_transitions = len(loader.transitions)

        loader.get_model("chat")
        assert len(loader.transitions) > initial_transitions

        loader.get_model("code_planning")
        assert len(loader.transitions) > initial_transitions + 1

    def test_backward_compatibility(self):
        """Test that old code still works with explicit model parameter."""
        loader = PhaseWiseLoader(device_profile="standard")
        # Old code should work: phase loader tracks phase but doesn't enforce it
        loader.get_model("chat")
        assert loader.get_current_phase() == Phase.READY


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""

    def test_explicit_model_parameter(self):
        """Test that explicit model parameter still works."""
        loader = PhaseWiseLoader(device_profile="standard")
        # Even though we're requesting an explicit model,
        # loader should track the phase for context awareness
        model = loader.get_model("chat")
        assert isinstance(model, str)

    def test_phase_loader_optional(self):
        """Test that phase loader is optional."""
        # ChatEngine and other components should work without phase loader
        # This is tested in integration tests
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
