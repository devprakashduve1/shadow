"""Manage conversational interactions with the code editor (Claude-style)."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageSenderType(str, Enum):
    """Type of sender for message in conversation."""
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class WorkflowPhase(str, Enum):
    """Phase of interaction workflow."""
    INTENT_ANALYSIS = "intent_analysis"
    PLAN_GENERATION = "plan_generation"
    DIFF_GENERATION = "diff_generation"
    AWAITING_USER_FEEDBACK = "awaiting_user_feedback"
    PLAN_REFINEMENT = "plan_refinement"
    EXECUTION_READY = "execution_ready"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    EXECUTION_COMPLETE = "execution_complete"


@dataclass
class ConversationMessage:
    """A single message in the conversation dialogue."""
    sender_type: MessageSenderType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionState:
    """Current state of the interaction session."""
    phase: WorkflowPhase
    user_requirement: str
    generated_plan: Optional[Dict] = None
    code_diffs: List[Dict] = field(default_factory=list)
    user_feedback_log: List[str] = field(default_factory=list)
    refinement_iteration_count: int = 0
    execution_approval_status: Optional[bool] = None
    session_notes: str = ""


class ConversationManager:
    """Manage multi-turn conversational interactions in code editing workflow."""

    def __init__(self, llm_client):
        """Initialize conversation manager.

        Args:
            llm_client: Language model client for LLM interactions
        """
        self.language_model_client = llm_client
        self.message_log: List[ConversationMessage] = []
        self.state = InteractionState(
            phase=WorkflowPhase.INTENT_ANALYSIS,
            user_requirement="",
        )

    def initialize_session(self, user_requirement: str) -> None:
        """Initialize a new interaction session.

        Args:
            user_requirement: User's code modification requirement
        """
        self.message_log = []
        self.state = InteractionState(
            phase=WorkflowPhase.INTENT_ANALYSIS,
            user_requirement=user_requirement,
        )

        # Log user requirement as initial message
        self.append_message(MessageSenderType.USER, user_requirement)

        logger.info(f"Session initialized with requirement: {user_requirement[:60]}...")

    def append_message(self, sender_type: MessageSenderType, content: str,
                       metadata: Optional[Dict] = None) -> None:
        """Append message to conversation log.

        Args:
            sender_type: Type of message sender (USER, AGENT, SYSTEM)
            content: Message content
            metadata: Optional metadata for the message
        """
        message = ConversationMessage(
            sender_type=sender_type,
            content=content,
            metadata=metadata or {}
        )
        self.message_log.append(message)

    def transition_to_phase(self, phase: WorkflowPhase) -> None:
        """Transition workflow to specified phase.

        Args:
            phase: Target workflow phase
        """
        self.state.phase = phase
        logger.info(f"Workflow phase: {phase.value}")

    def set_generated_plan(self, plan: Dict) -> None:
        """Set the generated execution plan.

        Args:
            plan: Generated plan dictionary
        """
        self.state.generated_plan = plan

    def set_code_diffs(self, diffs: List[Dict]) -> None:
        """Set generated code differences.

        Args:
            diffs: List of code diff dictionaries
        """
        self.state.code_diffs = diffs

    def record_user_feedback(self, feedback: str) -> None:
        """Record user feedback in session.

        Args:
            feedback: User's feedback or input
        """
        self.state.user_feedback_log.append(feedback)
        self.state.refinement_iteration_count += 1
        self.append_message(MessageSenderType.USER, feedback)

    def get_session_log_summary(self) -> str:
        """Generate summary of conversation session log.

        Returns:
            Formatted string containing message history
        """
        output = []
        output.append("\n" + "=" * 70)
        output.append("INTERACTION SESSION LOG")
        output.append("=" * 70)

        for index, message in enumerate(self.message_log, 1):
            sender_label = "USER" if message.sender_type == MessageSenderType.USER else "AGENT"
            output.append(f"\n[{index}] {sender_label}:")
            output.append(f"   {message.content[:100]}...")

        output.append("\n" + "=" * 70)
        return "\n".join(output)

    def build_llm_context_prompt(self) -> str:
        """Build contextual prompt for LLM based on session history.

        Returns:
            Formatted context string for LLM interaction
        """
        context_parts = []

        context_parts.append("# Session Context\n")
        context_parts.append(f"**User Requirement**: {self.state.user_requirement}\n")
        context_parts.append(f"**Current Workflow Phase**: {self.state.phase.value}\n")
        context_parts.append(f"**Refinement Iterations**: {self.state.refinement_iteration_count}\n")

        if self.state.user_feedback_log:
            context_parts.append("\n**User Feedback History**:")
            for feedback_item in self.state.user_feedback_log:
                context_parts.append(f"- {feedback_item}")

        context_parts.append("\n**Session Dialogue**:")
        for message in self.message_log[-5:]:  # Last 5 messages for context
            sender = "User" if message.sender_type == MessageSenderType.USER else "Agent"
            context_parts.append(f"\n{sender}: {message.content[:200]}")

        return "\n".join(context_parts)

    def format_state_for_display(self) -> str:
        """Format session state for user display.

        Returns:
            Formatted string containing session state
        """
        output = []

        output.append("\n" + "=" * 70)
        output.append("INTERACTION STATE")
        output.append("=" * 70)

        output.append(f"\nRequirement: {self.state.user_requirement}")
        output.append(f"Workflow Phase: {self.state.phase.value}")
        output.append(f"Refinement Iterations: {self.state.refinement_iteration_count}")

        if self.state.generated_plan:
            output.append(f"\nGenerated Plan:")
            output.append(f"   Steps: {len(self.state.generated_plan.get('steps', []))}")
            output.append(f"   Summary: {self.state.generated_plan.get('summary', 'N/A')}")

        if self.state.code_diffs:
            output.append(f"\nCode Modifications:")
            output.append(f"   Diff Items: {len(self.state.code_diffs)}")

        if self.state.user_feedback_log:
            output.append(f"\nUser Feedback Log:")
            for index, feedback in enumerate(self.state.user_feedback_log, 1):
                output.append(f"   [{index}] {feedback[:60]}...")

        if self.state.execution_approval_status is not None:
            status = "APPROVED" if self.state.execution_approval_status else "REJECTED"
            output.append(f"\nExecution Status: {status}")

        output.append("\n" + "=" * 70)
        return "\n".join(output)

    def get_messages_for_llm_api(self) -> List[Dict[str, str]]:
        """Convert message log to format suitable for LLM API.

        Returns:
            List of message dictionaries with role and content
        """
        return [
            {"role": message.sender_type.value, "content": message.content}
            for message in self.message_log
        ]

    def reset_feedback_log(self) -> None:
        """Clear user feedback log for fresh iteration."""
        self.state.user_feedback_log = []
        self.state.refinement_iteration_count = 0

    def is_session_active(self) -> bool:
        """Check if session should remain active.

        Returns:
            True if session should continue, False if complete
        """
        return self.state.phase != WorkflowPhase.EXECUTION_COMPLETE

    def set_execution_approved(self) -> None:
        """Mark execution as approved by user."""
        self.state.execution_approval_status = True
        self.transition_to_phase(WorkflowPhase.EXECUTION_READY)

    def set_execution_rejected(self) -> None:
        """Mark execution as rejected by user."""
        self.state.execution_approval_status = False
        self.transition_to_phase(WorkflowPhase.EXECUTION_COMPLETE)

    def get_refinement_prompt(self) -> str:
        """Get prompt to ask for feedback."""
        return """Looking at the proposed changes above:

1. Do they look correct?
2. Should I adjust anything?
3. Should I add/remove anything?
4. Or should I proceed with applying these changes?

Please let me know your feedback (or type 'apply' to proceed):"""

    def get_approval_prompt(self) -> str:
        """Get prompt to ask for final approval."""
        return """✅ I've prepared the code changes. Are you ready for me to apply them?

Type:
- 'apply' or 'yes' to proceed
- 'revise' to make changes
- 'cancel' to abort"""


class ConversationOrchestrator:
    """Orchestrate Claude-style conversational code editing."""

    def __init__(self, llm_client, project_root: str):
        """Initialize orchestrator."""
        self.llm = llm_client
        self.project_root = project_root
        self.conversation = ConversationManager(llm_client)

    def start_interactive_session(self, user_request: str) -> ConversationManager:
        """Start an interactive editing session."""
        self.conversation.initialize_session(user_request)
        return self.conversation

    def process_user_response(self, response: str) -> str:
        """Process user response and generate assistant response."""
        self.conversation.record_user_feedback(response)

        if response.lower() in ("apply", "yes", "ok", "proceed"):
            self.conversation.set_execution_approved()
            return self._generate_applying_message()
        elif response.lower() in ("cancel", "abort", "stop"):
            self.conversation.set_execution_rejected()
            return "❌ Changes cancelled. Goodbye!"
        elif response.lower() in ("revise", "adjust", "change"):
            self.conversation.transition_to_phase(WorkflowPhase.PLAN_REFINEMENT)
            return self._generate_refinement_prompt()
        else:
            return self._generate_response_to_feedback(response)

    def _generate_applying_message(self) -> str:
        """Generate message when applying changes."""
        msg = """✅ Great! I'm now applying the changes:

1. Generating patches...
2. Validating syntax...
3. Checking for conflicts...
4. Applying to files...
5. Formatting code...
6. Running tests...

This should take about 10-20 seconds..."""
        self.conversation.append_message(MessageSenderType.AGENT, msg)
        return msg

    def _generate_refinement_prompt(self) -> str:
        """Generate prompt for refinement."""
        msg = """I can adjust the plan. What would you like me to change?

For example:
- "Also add rate limiting"
- "Don't modify the tests"
- "Make the validation more strict"
- "Add caching for performance"

What adjustments would you like?"""
        self.conversation.append_message(MessageSenderType.AGENT, msg)
        return msg

    def _generate_response_to_feedback(self, feedback: str) -> str:
        """Generate response to general feedback."""
        msg = f"""Got it. You mentioned: "{feedback}"

Let me update the plan based on this feedback...

The updated plan would:
1. Incorporate your feedback
2. Show new diffs
3. Ask for approval again

Is this direction correct?"""
        self.conversation.append_message(MessageSenderType.AGENT, msg)
        return msg
