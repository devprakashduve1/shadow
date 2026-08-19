"""
Example: Interactive code editing session with full workflow.

This demonstrates the proper way to use the conversational AI code editor
with real user interaction, LLM context passing, and confirmations.
"""

import logging
from pathlib import Path
from typing import Optional

from .conversational_orchestrator import ConversationalAICodeEditor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockLLMClient:
    """Mock LLM client for testing. Replace with real client (Ollama, etc)."""

    def complete(self, prompt: str, max_tokens: int = 500, temperature: float = 0.3) -> str:
        """Mock LLM completion."""
        # In production, call actual LLM
        # response = requests.post("http://localhost:11434/api/generate", json={...})

        # For demo, return sensible defaults based on prompt keywords
        if "requirements_to_add" in prompt:
            return """{
  "requirements_to_add": ["feature requested by user"],
  "requirements_to_remove": [],
  "requirements_to_modify": [],
  "documented_concerns": [],
  "clarification_questions": [],
  "parsing_confidence": 0.85
}"""

        elif "Refine" in prompt or "refined plan" in prompt:
            return """{
  "plan_id": "plan-refined-001",
  "summary": "Updated plan based on feedback",
  "changes_made": ["incorporated user feedback"],
  "steps": [
    {
      "step_number": 1,
      "action": "modify",
      "file": "src/models.py",
      "target_function": "User",
      "details": "Add requested validation",
      "reason": "User requested this change"
    }
  ],
  "estimated_impact": {
    "files_to_modify": 1,
    "breaking_changes": 0
  }
}"""

        else:
            return "Mock LLM response"


def interactive_session_demo():
    """
    Demonstrate a full interactive session.

    This shows:
    1. Initializing conversational editor
    2. User provides requirement
    3. AI shows plan
    4. User refines
    5. AI refines with LLM
    6. User approves
    7. Changes applied
    8. Session summarized
    """

    print("=" * 70)
    print("INTERACTIVE CODE EDITING DEMO")
    print("=" * 70)
    print()

    # Initialize
    project_root = str(Path(__file__).parent.parent.parent)
    llm = MockLLMClient()

    editor = ConversationalAICodeEditor(project_root, llm)

    # ===== PHASE 1: Start Session =====
    print("\n>>> USER: Add email validation to the User model")
    print()

    response = editor.start_session("Add email validation to the User model")
    print(f"<<< AI:\n{response}\n")

    # ===== PHASE 2: User provides feedback for refinement =====
    print("\n>>> USER: Also add password strength validation")
    print()

    response = editor.process_feedback("Also add password strength validation")
    print(f"<<< AI:\n{response}\n")

    # ===== PHASE 3: User provides another refinement =====
    print("\n>>> USER: Make sure to handle internationalization for error messages")
    print()

    response = editor.process_feedback("Make sure to handle internationalization for error messages")
    print(f"<<< AI:\n{response}\n")

    # ===== PHASE 4: User approves =====
    print("\n>>> USER: Looks good, proceed with the changes")
    print()

    response = editor.process_feedback("yes")
    print(f"<<< AI:\n{response}\n")

    # ===== PHASE 5: Session Analysis =====
    print("\n" + "=" * 70)
    print("SESSION ANALYSIS")
    print("=" * 70)

    print("\n### Current State ###")
    state = editor.get_current_state()
    print(state)

    print("\n### Conversation History ###")
    history = editor.get_conversation_history()
    print(history)

    print("\n### Session Summary ###")
    summary = editor.get_session_summary()
    print(summary)


def multi_turn_refinement_demo():
    """
    Demonstrate multiple rounds of refinement.

    Shows how LLM context accumulates and refines across iterations.
    """

    print("\n" + "=" * 70)
    print("MULTI-TURN REFINEMENT DEMO")
    print("=" * 70)
    print()

    project_root = str(Path(__file__).parent.parent.parent)
    llm = MockLLMClient()

    editor = ConversationalAICodeEditor(project_root, llm)

    # Initial request
    print(">>> USER: Refactor the authentication module for better performance")
    response = editor.start_session("Refactor the authentication module for better performance")
    print(f"<<< AI:\n{response}\n")

    # First refinement
    print(">>> USER: Use async/await for I/O operations")
    response = editor.process_feedback("Use async/await for I/O operations")
    print(f"<<< AI:\n{response}\n")

    # Second refinement
    print(">>> USER: Add caching for token validation")
    response = editor.process_feedback("Add caching for token validation")
    print(f"<<< AI:\n{response}\n")

    # Third refinement
    print(">>> USER: But don't modify the login flow, keep it simple")
    response = editor.process_feedback("But don't modify the login flow, keep it simple")
    print(f"<<< AI:\n{response}\n")

    # Approval
    print(">>> USER: Apply these changes")
    response = editor.process_feedback("apply")
    print(f"<<< AI:\n{response}\n")

    # Analysis
    print("\n### LLM Context at this point includes all 4 user messages ###")
    context = editor.conversation_mgr.build_llm_context_prompt()
    print(context)


def cancellation_demo():
    """
    Demonstrate cancellation workflow.
    """

    print("\n" + "=" * 70)
    print("CANCELLATION DEMO")
    print("=" * 70)
    print()

    project_root = str(Path(__file__).parent.parent.parent)
    llm = MockLLMClient()

    editor = ConversationalAICodeEditor(project_root, llm)

    print(">>> USER: Add logging to all API endpoints")
    response = editor.start_session("Add logging to all API endpoints")
    print(f"<<< AI:\n{response}\n")

    print(">>> USER: Actually, let me think about this more. Cancel.")
    response = editor.process_feedback("cancel")
    print(f"<<< AI:\n{response}\n")

    print("Session cancelled.")


def approval_workflow_demo():
    """
    Demonstrate the approval workflow with questions and confirmations.
    """

    print("\n" + "=" * 70)
    print("APPROVAL WORKFLOW DEMO")
    print("=" * 70)
    print()

    project_root = str(Path(__file__).parent.parent.parent)
    llm = MockLLMClient()

    editor = ConversationalAICodeEditor(project_root, llm)

    print(">>> USER: Add database migration for new user fields")
    response = editor.start_session("Add database migration for new user fields")
    print(f"<<< AI:\n{response}\n")

    print(">>> USER: Make sure the migration is reversible")
    response = editor.process_feedback("Make sure the migration is reversible")
    print(f"<<< AI:\n{response}\n")

    print(">>> USER: Yes, I'm satisfied with the plan")
    response = editor.process_feedback("yes")
    print(f"<<< AI:\n{response}\n")

    # Show full session details
    print("\n### FULL SESSION DETAILS ###\n")
    print(editor.get_conversation_history())


# ============================================================================
# Key Concepts Demonstrated
# ============================================================================

def explain_workflow():
    """
    Explain the complete workflow architecture.
    """

    explanation = """
# Interactive Code Editing Workflow

## Architecture

The system uses TWO key components:

1. **ConversationManager** (conversation_manager.py)
   - Tracks session state
   - Maintains message history
   - Manages workflow phases
   - Builds LLM context from history

2. **ConversationalAICodeEditor** (conversational_orchestrator.py)
   - Orchestrates the workflow
   - Handles user input/feedback
   - Calls LLM for planning and refinement
   - Manages confirmations
   - Executes approved changes

## Workflow Phases

User Request
    ↓
1. INTENT_ANALYSIS - Parse what user wants
    ↓
2. PLAN_GENERATION - Create step-by-step plan
    ↓
3. AWAITING_USER_FEEDBACK - Show plan, ask for approval
    ↓
[User provides feedback or approval]
    ↓
IF approval: Go to 5
IF refinement: Go to 4
    ↓
4. PLAN_REFINEMENT - Refine with LLM using full context
    ↓
Back to 3
    ↓
5. EXECUTION_READY - User confirmed
    ↓
6. EXECUTION_IN_PROGRESS - Applying changes
    ↓
7. EXECUTION_COMPLETE - Done

## LLM Context Building

At each LLM call, the system:
1. Gets full conversation history from session
2. Includes current workflow phase
3. Includes all user feedback so far
4. Includes refinement iteration count
5. Passes this as context to LLM

Result: LLM understands full context and can make better decisions

## Actual LLM Prompts

1. Props Analysis:
   "Extract requirements from: {user_request}"

2. Planning:
   "Create step-by-step plan for: {intent}
    Context files: {retrieved_files}
    Request: {original_request}"

3. Feedback Parsing:
   "Parse this feedback into: add/remove/modify requirements
    Feedback: {user_feedback}
    Return JSON with confidence score"

4. Plan Refinement:
   "Refine this plan based on feedback:
    Original Request: {user_requirement}
    Current Plan: {plan_steps}
    Feedback: {parsed_feedback}
    Full Context: {session_context}"

## Before Execution

ALL changes require explicit user approval:
1. Show plan to user
2. Show proposed changes as diffs
3. Get user confirmation (yes/no)
4. Only then execute

This prevents accidental changes and gives users control.

## Session Analysis

After session:
1. Get session summary (LLM analyzes what happened)
2. Get conversation history (all messages)
3. Get current state (phase, iterations, etc)

This helps understand what was discussed and decided.

## Key Differences from Old System

OLD:
- ConversationalAICodeEditor was all mocks
- No real LLM integration
- Methods didn't exist
- No session tracking
- Random text generation

NEW:
- Real implementation
- Full LLM integration
- All methods properly named and functional
- Complete session state management
- User-friendly interaction flow
- Before-execution confirmations
- Full conversation context passed to LLM
"""

    return explanation


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    print(__doc__)

    # Run demos
    interactive_session_demo()
    multi_turn_refinement_demo()
    cancellation_demo()
    approval_workflow_demo()

    # Print explanation
    print(explain_workflow())

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print("""
For production use:
1. Replace MockLLMClient with real LLM (Ollama, OpenAI, etc)
2. Integrate with your UI framework (PyQt, web, etc)
3. Add proper error handling and logging
4. Add database persistence for sessions
5. Test with real code projects
""")
