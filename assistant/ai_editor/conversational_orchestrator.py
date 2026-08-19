"""Conversational orchestrator - Interactive multi-turn code editing with real LLM integration."""

import logging
import json
from pathlib import Path
from typing import Optional, Callable

from .orchestrator import AICodeEditor
from .conversation_manager import (
    ConversationManager,
    ConversationOrchestrator,
    MessageSenderType,
    WorkflowPhase
)
from .refinement_handler import PlanRefinementHandler, ParsedUserFeedback
from .diff_generator import UnifiedDiffGenerator

logger = logging.getLogger(__name__)


class ConversationalAICodeEditor:
    """
    Interactive conversational code editor with real LLM integration.

    Workflow:
    1. User: "Add email validation"
    2. AI: Analyzes → Shows plan → Asks confirmation
    3. User approves or refines
    4. If refine:
       - AI: Parses feedback with LLM
       - Shows refined plan
       - Asks confirmation again
    5. User approves
    6. AI: Applies actual changes with full validation
    """

    def __init__(self, project_root: str, llm_client):
        """Initialize conversational editor."""
        self.project_root = Path(project_root)
        self.llm = llm_client

        self.editor = AICodeEditor(str(project_root), llm_client)
        self.conversation_mgr = None
        self.refinement_handler = PlanRefinementHandler(llm_client)
        self.diff_generator = UnifiedDiffGenerator()
        self.approval_callback = None

    def start_session(self, user_request: str) -> str:
        """Start an interactive editing session with real workflow."""
        logger.info(f"Starting session: {user_request[:60]}...")

        self.conversation_mgr = ConversationManager(self.llm)
        self.conversation_mgr.initialize_session(user_request)

        return self._phase_1_analyze_and_plan(user_request)

    def set_approval_callback(self, callback: Callable[[str], bool]) -> None:
        """Set callback for user confirmations during interactive session."""
        self.approval_callback = callback

    def _phase_1_analyze_and_plan(self, user_request: str) -> str:
        """Phase 1: Analyze request and generate plan."""
        logger.info("Phase 1: Analyzing request and generating plan...")
        self.conversation_mgr.transition_to_phase(WorkflowPhase.INTENT_ANALYSIS)

        try:
            plan_result = self.editor._get_plan_for_request(user_request)

            if not plan_result:
                response = "❌ Could not generate a plan. Please try rephrasing your request."
                self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
                return response

            self.conversation_mgr.set_generated_plan(plan_result)
            self.conversation_mgr.transition_to_phase(WorkflowPhase.PLAN_GENERATION)

            response = self._build_initial_plan_response(plan_result, user_request)
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)

            return response

        except Exception as e:
            logger.error(f"Error in phase 1: {e}")
            response = f"❌ Error analyzing request: {str(e)}"
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
            return response

    def _build_initial_plan_response(self, plan_result, user_request: str) -> str:
        """Build formatted response showing the plan."""
        output = []

        output.append("✅ **I've analyzed your request**\n")

        plan_dict = plan_result if isinstance(plan_result, dict) else plan_result.to_dict()

        output.append(f"📋 **Plan**: {plan_dict.get('summary', 'N/A')}\n")

        if "steps" in plan_dict and plan_dict["steps"]:
            output.append("**Steps I'll take**:")
            for step in plan_dict["steps"][:5]:
                output.append(
                    f"  {step.get('step_number', '?')}. "
                    f"**{step.get('action', 'action').upper()}** "
                    f"`{step.get('file', 'file')}`"
                )
                if step.get('details'):
                    output.append(f"     → {step['details']}")

            if len(plan_dict.get("steps", [])) > 5:
                output.append(f"     ... and {len(plan_dict['steps']) - 5} more steps")

        output.append("\n---\n")
        output.append("**Before I proceed, please review this plan:**\n")
        output.append("- Type 'yes' or 'apply' if this looks good")
        output.append("- Describe changes if you'd like adjustments")
        output.append("- Type 'cancel' to abort")

        return "\n".join(output)

    def process_feedback(self, user_input: str) -> str:
        """Process user feedback and respond appropriately."""
        logger.info(f"Processing feedback: {user_input[:60]}...")

        self.conversation_mgr.record_user_feedback(user_input)

        if not self.conversation_mgr.is_session_active():
            return "❌ Session is no longer active. Please start a new one."

        user_input_lower = user_input.lower().strip()

        if user_input_lower in ("yes", "apply", "ok", "proceed", "go"):
            return self._handle_approval()

        elif user_input_lower in ("cancel", "abort", "stop", "no"):
            self.conversation_mgr.set_execution_rejected()
            return "❌ **Cancelled.** Changes were not applied. Feel free to start fresh!"

        else:
            return self._handle_refinement_feedback(user_input)

    def _handle_approval(self) -> str:
        """Handle user approval - execute the plan."""
        logger.info("User approved plan. Moving to execution...")

        self.conversation_mgr.set_execution_approved()
        self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_READY)

        output = []
        output.append("✅ **Great! Proceeding with changes...**\n")

        output.append("📋 Executing plan:")
        output.append("  1. Generating patches...")
        output.append("  2. Validating syntax...")
        output.append("  3. Checking for conflicts...")
        output.append("  4. Applying changes...")
        output.append("  5. Formatting code...")
        output.append("  6. Running validations...\n")

        self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_IN_PROGRESS)

        try:
            user_requirement = self.conversation_mgr.state.user_requirement
            result = self.editor.handle_request(user_requirement, require_approval=False)

            if result.success:
                output.append("✅ **Changes applied successfully!**\n")
                output.append(f"📊 Summary:")
                output.append(f"  • Files modified: {len(result.modified_files)}")
                output.append(f"  • Patches applied: {result.patches_applied}")

                if result.warnings:
                    output.append(f"\n⚠️  Warnings:")
                    for warning in result.warnings[:3]:
                        output.append(f"  • {warning}")

                self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_COMPLETE)
            else:
                output.append("❌ **Execution failed**\n")
                output.append("Errors:")
                for error in result.errors[:3]:
                    output.append(f"  • {error}")

                self.conversation_mgr.transition_to_phase(WorkflowPhase.AWAITING_USER_FEEDBACK)

            response = "\n".join(output)
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
            return response

        except Exception as e:
            logger.error(f"Error during execution: {e}")
            output.append(f"❌ **Error during execution**: {str(e)}")
            response = "\n".join(output)
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
            self.conversation_mgr.transition_to_phase(WorkflowPhase.AWAITING_USER_FEEDBACK)
            return response

    def _handle_refinement_feedback(self, user_feedback: str) -> str:
        """Handle user feedback for plan refinement."""
        logger.info("Parsing user feedback for refinement...")

        self.conversation_mgr.transition_to_phase(WorkflowPhase.PLAN_REFINEMENT)

        try:
            parsed_feedback = self.refinement_handler.parse_user_feedback_input(user_feedback)

            if not self.refinement_handler.should_refine(parsed_feedback.parsing_confidence_score):
                response = self.refinement_handler.ask_for_clarification(parsed_feedback)
                self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
                return response

            output = []
            output.append(self.refinement_handler.generate_refinement_summary(parsed_feedback))

            current_plan = self.conversation_mgr.state.generated_plan
            if current_plan:
                refined_plan = self.refinement_handler.refine_plan(
                    current_plan,
                    parsed_feedback,
                    self.conversation_mgr.state.user_requirement,
                )

                self.conversation_mgr.set_generated_plan(refined_plan)

                output.append("\n✅ **Plan updated**\n")
                output.append("Updated steps:")
                for step in refined_plan.get("steps", [])[:5]:
                    output.append(
                        f"  • **{step.get('action', 'action').upper()}** "
                        f"`{step.get('file', 'file')}`"
                    )

                if len(refined_plan.get("steps", [])) > 5:
                    output.append(f"  ... and {len(refined_plan['steps']) - 5} more")

                output.append("\n---\n")
                output.append("**Ready to proceed?**")
                output.append("- Type 'yes' or 'apply' to proceed")
                output.append("- Or provide more feedback for further changes")

            response = "\n".join(output)
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
            self.conversation_mgr.transition_to_phase(WorkflowPhase.AWAITING_USER_FEEDBACK)
            return response

        except Exception as e:
            logger.error(f"Error in refinement: {e}")
            response = f"❌ Error refining plan: {str(e)}"
            self.conversation_mgr.append_message(MessageSenderType.AGENT, response)
            return response

    def get_session_summary(self) -> str:
        """Get analysis of the entire session."""
        if not self.conversation_mgr:
            return "No active session"

        context = self.conversation_mgr.build_llm_context_prompt()

        summary_prompt = f"""# SESSION ANALYSIS & SUMMARY

## SESSION CONTEXT
{context}

## YOUR TASK
Analyze the entire code editing session and provide a comprehensive summary.

## ANALYSIS POINTS

1. **Original Goal**: What did the user want to accomplish?
2. **Refinement Journey**: What changes/adjustments did the user request?
3. **Current Status**: Where are we in the workflow?
4. **Completeness**: Is the task done, in progress, or cancelled?
5. **Key Decisions**: What important decisions were made?
6. **Risks/Concerns**: Any potential issues or limitations?
7. **Outstanding Items**: What's left to do (if anything)?

## RESPONSE FORMAT

Provide a well-structured markdown summary that covers:

```
## Executive Summary
[One-line summary of what was accomplished]

## Original Request
[The user's original goal/requirement]

## Refinements Made
- [Refinement 1]
- [Refinement 2]
- [Refinement 3]

## Key Decisions
- [Decision 1]
- [Decision 2]

## Final Status
[Status: Complete/In Progress/Cancelled]

## Accomplishments
- [Achievement 1]
- [Achievement 2]

## Outstanding Items
- [Item 1 (if any)]
- [Item 2 (if any)]

## Concerns/Limitations
- [Concern 1 (if any)]
- [Concern 2 (if any)]

## Next Steps (if applicable)
- [Next step 1]
- [Next step 2]
```

## GUIDELINES
- Be clear and concise
- Use markdown formatting
- Highlight key information
- Be factual: reference actual messages/decisions from session
- Be helpful: provide actionable insights
- Be balanced: acknowledge both successes and concerns"""

        try:
            summary = self.llm.complete(summary_prompt, max_tokens=500, temperature=0.3)
            return summary
        except Exception as e:
            logger.warning(f"Could not generate summary: {e}")
            return self.conversation_mgr.format_state_for_display()

    def get_conversation_history(self) -> str:
        """Get formatted conversation history."""
        if not self.conversation_mgr:
            return "No conversation history"

        output = []
        output.append("\n" + "=" * 70)
        output.append("CONVERSATION HISTORY")
        output.append("=" * 70 + "\n")

        for idx, msg in enumerate(self.conversation_mgr.message_log, 1):
            sender = "🧑 User" if msg.sender_type == MessageSenderType.USER else "🤖 AI"
            output.append(f"{sender}:")
            output.append(f"  {msg.content}\n")

        output.append("=" * 70)
        return "\n".join(output)

    def get_current_state(self) -> str:
        """Get current session state."""
        if not self.conversation_mgr:
            return "No active session"

        return self.conversation_mgr.format_state_for_display()
