#!/usr/bin/env python3
"""
Example usage of the improved AI Code Editor with props analysis and user confirmation.

This script demonstrates:
1. Props analysis - extracting requirements from user requests
2. Plan review - showing proposed changes to users
3. User confirmation - asking for approval before making changes
4. Error handling - graceful handling of rejection and errors
"""

import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
)

from assistant.ai_editor import (
    AICodeEditor,
    PropsAnalyzer,
    ReviewManager,
    ConfirmationRequest,
)


class MockLLMClient:
    """Mock LLM client for demonstration (replace with real client)."""

    def complete(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.1) -> str:
        """Simulate LLM response."""
        # In production, use real LLM like Ollama or OpenAI

        if "extract detailed requirements" in prompt.lower():
            return """{
                "requirements": [
                    {
                        "type": "functional",
                        "description": "Add email validation logic",
                        "priority": "high",
                        "effort": "small",
                        "keywords": ["email", "validate"]
                    }
                ],
                "affected_components": ["user", "authentication"],
                "dependencies": [],
                "breaking_changes": false,
                "complexity": 2,
                "files_to_modify": 2,
                "scope": "Add email validation to User model and authentication flows",
                "assumptions": ["Email validation uses regex pattern"],
                "clarifications": [],
                "confidence": 0.85
            }"""

        elif "create a step-by-step plan" in prompt.lower():
            return """{
                "plan_id": "plan-20260806-001",
                "summary": "Add email validation to authentication system",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "understand",
                        "file": "assistant/models/user.py",
                        "goal": "Review User model structure",
                        "details": "Understand current validation implementation"
                    },
                    {
                        "step_number": 2,
                        "action": "modify",
                        "file": "assistant/models/user.py",
                        "target_function": "validate_email",
                        "change_type": "enhance",
                        "details": "Add comprehensive email validation"
                    },
                    {
                        "step_number": 3,
                        "action": "test",
                        "file": "tests/test_validation.py",
                        "goal": "Add tests",
                        "details": "Add unit tests for email validation"
                    }
                ],
                "estimated_impact": {
                    "files_to_modify": 2,
                    "files_to_create": 0,
                    "breaking_changes": 0
                },
                "estimated_tokens": 2000
            }"""

        return "{}"


def example_1_basic_usage():
    """Example 1: Basic usage with auto-confirmation."""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Basic Usage (Auto Mode - No User Confirmation)")
    print("=" * 70)

    editor = AICodeEditor(
        project_root="/Users/dev.duve/TelusProjscts/shadow",
        llm_client=MockLLMClient(),
    )

    result = editor.handle_request(
        "Add email validation to User model",
        require_approval=False,  # Skip confirmation in this example
    )

    print(f"\n✅ Result:")
    print(f"  Success: {result.success}")
    print(f"  Patches Applied: {result.patches_applied}")
    print(f"  Modified Files: {result.modified_files}")
    if result.errors:
        print(f"  Errors: {result.errors}")


def example_2_plan_preview():
    """Example 2: Preview plan without applying changes."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Plan Preview (No Changes Applied)")
    print("=" * 70)

    editor = AICodeEditor(
        project_root="/Users/dev.duve/TelusProjscts/shadow",
        llm_client=MockLLMClient(),
    )

    # Get plan review
    review = editor.get_plan_review("Add email validation to User model")

    if review:
        # Display the review
        print(review.format_for_display())

        # Access individual components
        print("\n📊 PROGRAMMATIC ACCESS:")
        print(f"  Plan ID: {review.plan.plan_id}")
        print(f"  Status: {review.status}")
        print(f"  Files affected: {len(review.files_affected)}")
        print(f"  Operations: {review.operations_count}")

        print("\n📋 REQUIREMENTS:")
        for req in review.props_analysis.requirements:
            print(f"  • [{req.priority}] {req.description}")

        if review.props_analysis.breaking_changes_possible:
            print("\n⚠️  WARNING: Breaking changes possible!")

    else:
        print("❌ Could not create review")


def example_3_props_analysis():
    """Example 3: Detailed props analysis."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Props Analysis (Requirement Extraction)")
    print("=" * 70)

    analyzer = PropsAnalyzer(MockLLMClient())

    requests = [
        "Add email validation to User model",
        "Fix authentication bug in login endpoint",
        "Refactor database connection handling for better performance",
    ]

    for request in requests:
        print(f"\n📝 Request: {request}")
        props = analyzer.analyze(request)

        print(f"  Complexity: {props.estimated_complexity}/5")
        print(f"  Confidence: {props.confidence_score:.0%}")
        print(f"  Files to modify: {props.estimated_files_to_modify}")

        print("  Requirements:")
        for req in props.requirements:
            print(f"    • [{req.priority}] {req.type.value}: {req.description}")

        if props.affected_components:
            print(f"  Affected: {', '.join(props.affected_components)}")

        if props.breaking_changes_possible:
            print("  ⚠️  May have breaking changes")


def example_4_custom_callback():
    """Example 4: Custom confirmation callback (for GUI integration)."""
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Custom Confirmation Callback (GUI Integration)")
    print("=" * 70)

    def custom_confirmation(confirmation: ConfirmationRequest) -> bool:
        """Custom callback that could integrate with GUI."""
        print("\n🔍 Review received by custom handler:")
        print(f"  Files affected: {len(confirmation.review.files_affected)}")
        print(f"  Confirmations needed: {len(confirmation.required_confirmations)}")

        # In a real GUI, this would show a dialog
        # For this example, we simulate user approval
        print("  (Simulating user approval...)")
        return True  # User approved

    editor = AICodeEditor(
        project_root="/Users/dev.duve/TelusProjscts/shadow",
        llm_client=MockLLMClient(),
    )

    # Set custom callback
    editor.set_confirmation_callback(custom_confirmation)

    # Now when we handle a request, our callback will be used
    print("\nProcessing request with custom callback...")
    result = editor.handle_request(
        "Add email validation to User model",
        require_approval=True,
    )

    print(f"\n✅ Result: {'Success' if result.success else 'Failed'}")


def example_5_review_manager():
    """Example 5: Using ReviewManager directly."""
    print("\n" + "=" * 70)
    print("EXAMPLE 5: ReviewManager (Direct API)")
    print("=" * 70)

    from assistant.ai_editor import PropsAnalysis, PlanResult, PlanStep
    from assistant.ai_editor.schemas import IntentType, RiskLevel

    # Create mock objects
    props = PropsAnalysis(
        raw_request="Add email validation",
        requirements=[],
        affected_components=["auth", "user"],
        dependencies=[],
        breaking_changes_possible=False,
        estimated_complexity=2,
        estimated_files_to_modify=2,
        scope_description="Add validation to authentication flow",
        assumptions=["Email pattern is standard"],
        clarifications_needed=[],
        confidence_score=0.85,
    )

    plan = PlanResult(
        plan_id="plan-001",
        steps=[
            PlanStep(
                step_number=1,
                action="modify",
                file="user.py",
                details="Add validation",
            )
        ],
        summary="Add email validation",
        estimated_impact={"files_to_modify": 2},
    )

    # Create review
    review = ReviewManager.create_review(plan, props)

    # Create confirmation
    confirmation = ReviewManager.create_confirmation_request(review)

    print("\n📋 Review Status: " + review.status.value)
    print("📋 Confirmation Prompt:")
    print(confirmation.get_confirmation_prompt())

    # Simulate user confirmation
    print("\n✅ Approving changes...")
    confirmation.confirm(user_response=True, notes="Looks good!")

    # Validate
    is_valid = ReviewManager.validate_confirmation(confirmation)
    print(f"Confirmation valid: {is_valid}")


def example_6_error_handling():
    """Example 6: Error handling and rejection."""
    print("\n" + "=" * 70)
    print("EXAMPLE 6: Error Handling (User Rejection)")
    print("=" * 70)

    def rejecting_callback(confirmation: ConfirmationRequest) -> bool:
        """Callback that rejects the confirmation."""
        print("\n❌ User rejected the changes in confirmation callback")
        return False  # User rejected

    editor = AICodeEditor(
        project_root="/Users/dev.duve/TelusProjscts/shadow",
        llm_client=MockLLMClient(),
    )

    editor.set_confirmation_callback(rejecting_callback)

    result = editor.handle_request(
        "Add email validation to User model",
        require_approval=True,
    )

    print(f"\n📊 Result after rejection:")
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.errors}")


def main():
    """Run all examples."""
    print("\n")
    print("█" * 70)
    print("█ AI CODE EDITOR - IMPROVED USAGE EXAMPLES")
    print("█" * 70)

    # Run examples
    try:
        example_1_basic_usage()
    except Exception as e:
        print(f"Example 1 error: {e}")

    try:
        example_2_plan_preview()
    except Exception as e:
        print(f"Example 2 error: {e}")

    try:
        example_3_props_analysis()
    except Exception as e:
        print(f"Example 3 error: {e}")

    try:
        example_4_custom_callback()
    except Exception as e:
        print(f"Example 4 error: {e}")

    try:
        example_5_review_manager()
    except Exception as e:
        print(f"Example 5 error: {e}")

    try:
        example_6_error_handling()
    except Exception as e:
        print(f"Example 6 error: {e}")

    print("\n" + "█" * 70)
    print("█ EXAMPLES COMPLETE")
    print("█" * 70 + "\n")


if __name__ == "__main__":
    main()
