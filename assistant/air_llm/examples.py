"""Integration examples for AiR LLM library in Shadow project."""

from .core import PhaseWiseLoader
from .models import Phase
from .device_profile import DeviceProfileManager
from .phase_registry import PhaseRegistry


def example_basic_usage():
    """Example 1: Basic usage with auto-detection."""
    print("=" * 60)
    print("Example 1: Basic Usage")
    print("=" * 60)

    # Initialize (use standard for demo - works on most devices)
    loader = PhaseWiseLoader(device_profile="standard")
    print(f"Device profile: {loader.device_profile}")
    print(f"Current phase: {loader.get_current_phase()}")

    # Get model for chat (Phase 1)
    chat_model = loader.get_model("chat")
    print(f"\nChat model: {chat_model}")
    print(f"Current phase: {loader.get_current_phase()}")
    print(f"Loaded models: {loader.get_loaded_models()}")

    # Get model for code planning (Phase 2, auto-advance)
    plan_model = loader.get_model("code_planning")
    print(f"\nPlan model: {plan_model}")
    print(f"Current phase: {loader.get_current_phase()}")
    print(f"Loaded models: {loader.get_loaded_models()}")

    # Unload all
    unloaded = loader.unload_all()
    print(f"\nUnloaded: {unloaded}")
    print(f"Loaded models: {loader.get_loaded_models()}")


def example_device_profiles():
    """Example 2: Device profile selection."""
    print("\n" + "=" * 60)
    print("Example 2: Device Profiles")
    print("=" * 60)

    for profile in DeviceProfileManager.list_profiles():
        config = DeviceProfileManager.get_profile_config(profile)
        print(f"\nProfile: {profile}")
        print(f"  Description: {config['description']}")
        print(f"  Max models: {config['max_loaded_models']}")
        print(f"  Available phases: {config['available_phases']}")

        # Show models per phase
        for phase in config["available_phases"]:
            models = DeviceProfileManager.get_models_for_phase(profile, phase)
            print(f"    Phase {phase}: {models}")


def example_phase_registry():
    """Example 3: Use case registry."""
    print("\n" + "=" * 60)
    print("Example 3: Phase Registry")
    print("=" * 60)

    print("\nUse cases by phase:")
    for phase in [Phase.READY, Phase.WORKING, Phase.ADVANCED]:
        use_cases = PhaseRegistry.get_use_cases_for_phase(phase)
        if use_cases:
            print(f"\nPhase {phase}:")
            for use_case in sorted(use_cases):
                print(f"  - {use_case}")


def example_memory_management():
    """Example 4: Memory-aware loading."""
    print("\n" + "=" * 60)
    print("Example 4: Memory Management")
    print("=" * 60)

    loader = PhaseWiseLoader(device_profile="standard")

    # Check memory
    mem_info = loader.get_memory_info()
    print(f"\nSystem Memory:")
    print(f"  Total: {mem_info['system_total_gb']:.1f} GB")
    print(f"  Available: {mem_info['system_available_gb']:.1f} GB")
    print(f"  Used: {mem_info['system_used_gb']:.1f} GB ({mem_info['system_used_percent']:.0f}%)")
    print(f"  Pressure: {mem_info['pressure']}")

    # Load models and check memory
    loader.get_model("chat")
    loader.get_model("code_planning")

    mem_info = loader.get_memory_info()
    print(f"\nMemory after loading Phase 1 + Phase 2:")
    print(f"  Available: {mem_info['system_available_gb']:.1f} GB")
    print(f"  Pressure: {mem_info['pressure']}")


def example_integration_with_chat_engine():
    """Example 5: Integration with ChatEngine."""
    print("\n" + "=" * 60)
    print("Example 5: Integration with ChatEngine")
    print("=" * 60)

    from assistant.chat_engine import ChatEngine
    from database.json_store import EventStore
    from pathlib import Path

    # Initialize phase loader
    loader = PhaseWiseLoader()

    # Initialize event store (would be real in actual code)
    # store = EventStore(Path("./events"))

    # Create ChatEngine with phase loader
    # engine = ChatEngine(store, phase_loader=loader)

    # Now when engine.ask() is called, it uses phase-aware model:
    # for chunk in engine.ask("What did I work on?"):
    #     print(chunk, end="", flush=True)
    # The loader automatically selects Phase 1 model for chat

    print("\nChatEngine integration:")
    print("  from assistant.chat_engine import ChatEngine")
    print("  loader = PhaseWiseLoader()")
    print("  engine = ChatEngine(store, phase_loader=loader)")
    print("  for chunk in engine.ask('What did I work on?'):")
    print("    print(chunk, end='', flush=True)")


def example_streaming_integration():
    """Example 6: Integration with streaming.py."""
    print("\n" + "=" * 60)
    print("Example 6: Streaming Integration")
    print("=" * 60)

    print("\nUsage with stream_chat():")
    print("\n  from assistant.streaming import stream_chat")
    print("  from assistant.air_llm import PhaseWiseLoader")
    print("")
    print("  loader = PhaseWiseLoader()")
    print("  prompt = 'Explain this code...'")
    print("")
    print("  # Option 1: Phase-aware (loader determines model)")
    print("  for chunk in stream_chat(")
    print("      prompt,")
    print("      use_case='code_analysis',")
    print("      loader=loader")
    print("  ):")
    print("      print(chunk, end='', flush=True)")
    print("")
    print("  # Option 2: Explicit model (backward compatible)")
    print("  for chunk in stream_chat(prompt, model='qwen2.5:7b'):")
    print("      print(chunk, end='', flush=True)")


def example_error_handling():
    """Example 7: Error handling."""
    print("\n" + "=" * 60)
    print("Example 7: Error Handling")
    print("=" * 60)

    from .exceptions import DeviceConstraintError, PhaseLoadError

    print("\nDevice constraint handling:")
    print("  loader = PhaseWiseLoader(device_profile='limited')")
    print("  try:")
    print("      model = loader.get_model('multi_file_refactoring')")
    print("  except DeviceConstraintError:")
    print("      print('Phase 3 not available on limited device')")

    print("\nUse case error handling:")
    print("  try:")
    print("      model = loader.get_model('unknown_use_case')")
    print("  except KeyError:")
    print("      print('Use case not registered')")


def example_manual_phase_control():
    """Example 8: Manual phase control."""
    print("\n" + "=" * 60)
    print("Example 8: Manual Phase Control")
    print("=" * 60)

    loader = PhaseWiseLoader(device_profile="performance")

    print("\nManual phase advancement:")
    print(f"Initial phase: {loader.get_current_phase()}")

    loader.advance_phase(Phase.READY)
    print(f"After advance_phase(Phase.READY): {loader.get_current_phase()}")

    loader.advance_phase(Phase.WORKING)
    print(f"After advance_phase(Phase.WORKING): {loader.get_current_phase()}")

    loader.advance_phase(Phase.ADVANCED)
    print(f"After advance_phase(Phase.ADVANCED): {loader.get_current_phase()}")

    print("\nCustomizing models per phase:")
    available = DeviceProfileManager.get_models_for_phase("performance", Phase.READY)
    if available:
        loader.set_phase_model(Phase.READY, available[0])
        print(f"Set Phase {Phase.READY} model to: {available[0]}")


def example_transition_history():
    """Example 9: Transition history tracking."""
    print("\n" + "=" * 60)
    print("Example 9: Transition History")
    print("=" * 60)

    loader = PhaseWiseLoader(device_profile="standard")

    # Make some transitions
    loader.get_model("chat")
    loader.get_model("code_planning")
    loader.unload_all()

    print(f"\nTotal transitions: {len(loader.transitions)}")
    for i, transition in enumerate(loader.transitions, 1):
        print(f"\nTransition {i}:")
        print(f"  From: Phase {transition.from_phase} → To: Phase {transition.to_phase}")
        print(f"  Reason: {transition.reason}")
        print(f"  Models loaded: {transition.models_loaded}")
        print(f"  Models unloaded: {transition.models_unloaded}")


def example_monitoring():
    """Example 10: Phase monitoring."""
    print("\n" + "=" * 60)
    print("Example 10: Phase Monitoring")
    print("=" * 60)

    loader = PhaseWiseLoader(device_profile="standard")

    # Load some models
    loader.get_model("chat")

    # Get phase info
    info = loader.get_phase_info()
    print("\nPhase Information:")
    for key, value in info.items():
        print(f"  {key}: {value}")

    # List available models
    models = loader.list_available_models()
    print("\nAvailable Models per Phase:")
    for phase, model_list in sorted(models.items()):
        if model_list:
            print(f"  Phase {phase}: {model_list}")


if __name__ == "__main__":
    example_basic_usage()
    example_device_profiles()
    example_phase_registry()
    example_memory_management()
    example_integration_with_chat_engine()
    example_streaming_integration()
    example_error_handling()
    example_manual_phase_control()
    example_transition_history()
    example_monitoring()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)
