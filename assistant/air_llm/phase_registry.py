"""Registry mapping use cases to model phases."""

from typing import Dict, List
from .models import Phase


class PhaseRegistry:
    """Maps use cases to model loading phases."""

    PHASE_MAPPINGS: Dict[str, Phase] = {
        # Phase 1: Ready (Fast/Lightweight)
        "chat": Phase.READY,
        "chat_completion": Phase.READY,
        "search_summarization": Phase.READY,
        "suggested_questions": Phase.READY,
        "text_processing": Phase.READY,
        "ui_analysis": Phase.READY,

        # Phase 2: Working (Balanced)
        "code_planning": Phase.WORKING,
        "code_analysis": Phase.WORKING,
        "plan_generation": Phase.WORKING,
        "single_file_edit": Phase.WORKING,
        "edit_proposal": Phase.WORKING,
        "props_analysis": Phase.WORKING,
        "feedback_parsing": Phase.WORKING,
        "plan_refinement": Phase.WORKING,

        # Phase 3: Advanced (Heavy/Capable)
        "code_application": Phase.ADVANCED,
        "code_generation_complex": Phase.ADVANCED,
        "multi_file_refactoring": Phase.ADVANCED,
        "advanced_reasoning": Phase.ADVANCED,
    }

    @staticmethod
    def get_phase_for_use_case(use_case: str) -> Phase:
        """Get the phase for a use case.

        Args:
            use_case: Use case identifier (e.g., "chat", "code_planning")

        Returns:
            Phase enumeration

        Raises:
            KeyError: If use case is not registered
        """
        if use_case not in PhaseRegistry.PHASE_MAPPINGS:
            raise KeyError(f"Unknown use case: {use_case}")
        return PhaseRegistry.PHASE_MAPPINGS[use_case]

    @staticmethod
    def is_use_case_registered(use_case: str) -> bool:
        """Check if a use case is registered.

        Args:
            use_case: Use case identifier

        Returns:
            True if registered
        """
        return use_case in PhaseRegistry.PHASE_MAPPINGS

    @staticmethod
    def get_use_cases_for_phase(phase: Phase) -> List[str]:
        """Get all use cases that belong to a phase.

        Args:
            phase: Target phase

        Returns:
            List of use case identifiers
        """
        return [use_case for use_case, p in PhaseRegistry.PHASE_MAPPINGS.items() if p == phase]

    @staticmethod
    def register_use_case(use_case: str, phase: Phase) -> None:
        """Register or override a use case to phase mapping.

        Args:
            use_case: Use case identifier
            phase: Target phase
        """
        PhaseRegistry.PHASE_MAPPINGS[use_case] = phase

    @staticmethod
    def list_registered_use_cases() -> List[str]:
        """List all registered use cases.

        Returns:
            Sorted list of use case identifiers
        """
        return sorted(PhaseRegistry.PHASE_MAPPINGS.keys())
