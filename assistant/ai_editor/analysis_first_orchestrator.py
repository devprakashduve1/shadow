"""
Analysis-First Orchestrator: Analyze entire app, get confirmation, then proceed.

Workflow:
1. User provides request
2. AI analyzes ENTIRE codebase first
3. Shows analysis to user
4. Gets explicit confirmation
5. THEN analyzes request
6. Shows plan
7. Gets confirmation again
8. THEN executes
"""

import logging
from pathlib import Path
from typing import Optional

from .orchestrator import AICodeEditor
from .codebase_analyzer import CodebaseAnalyzer, CodebaseAnalysis
from .conversation_manager import (
    ConversationManager,
    MessageSenderType,
    WorkflowPhase,
)
from .refinement_handler import PlanRefinementHandler

logger = logging.getLogger(__name__)


class AnalysisResult:
    """Result of comprehensive analysis."""

    def __init__(self):
        self.codebase_analysis: Optional[CodebaseAnalysis] = None
        self.plan_generated: bool = False
        self.user_approved_codebase: bool = False
        self.user_approved_plan: bool = False


class AnalysisFirstOrchestrator:
    """
    New architecture: Analyze app first, get confirmations, then proceed.

    This ensures:
    1. User understands entire codebase
    2. User approves before ANY changes
    3. Full context available to LLM
    4. Changes are deliberate and informed
    """

    def __init__(self, project_root: str, llm_client):
        """Initialize analysis-first orchestrator."""
        self.project_root = Path(project_root)
        self.llm = llm_client

        # Core components
        self.codebase_analyzer = CodebaseAnalyzer(str(project_root))
        self.editor = AICodeEditor(str(project_root), llm_client)
        self.conversation_mgr = None
        self.refinement_handler = PlanRefinementHandler(llm_client)

        # Track state
        self.analysis_result: Optional[AnalysisResult] = None

    def start_with_analysis(self, user_request: str) -> str:
        """
        Start workflow with codebase analysis.

        Phase 1: ANALYZE CODEBASE
        - Scan entire project
        - Identify frameworks, modules, dependencies
        - Show findings to user
        - Get confirmation
        """
        logger.info(f"Starting analysis-first workflow: {user_request[:60]}...")

        # Initialize session
        self.conversation_mgr = ConversationManager(self.llm)
        self.conversation_mgr.initialize_session(user_request)

        # Phase 1: Analyze entire codebase
        self.conversation_mgr.transition_to_phase(WorkflowPhase.INTENT_ANALYSIS)

        output = []
        output.append("\n" + "=" * 70)
        output.append("🔍 PHASE 1: ANALYZING YOUR ENTIRE APPLICATION")
        output.append("=" * 70 + "\n")

        output.append("Scanning codebase...")
        output.append("  • Counting files and lines")
        output.append("  • Detecting frameworks")
        output.append("  • Finding entry points")
        output.append("  • Identifying modules")
        output.append("  • Extracting dependencies")
        output.append("  • Finding tests")
        output.append("  • Identifying impact areas\n")

        # Run analysis
        codebase_analysis = self.codebase_analyzer.analyze_full_codebase()
        self.analysis_result = AnalysisResult()
        self.analysis_result.codebase_analysis = codebase_analysis

        # Log to conversation
        self.conversation_mgr.append_message(
            MessageSenderType.USER,
            f"Analyze and plan: {user_request}",
        )

        # Show analysis
        analysis_display = self.codebase_analyzer.format_for_display()
        output.append(analysis_display)

        return "\n".join(output)

    def confirm_codebase_analysis(self, user_confirmation: str) -> str:
        """
        Phase 2: User confirms they understand codebase analysis.

        User must say 'yes' to proceed, or 'no'/'cancel' to stop.
        """
        logger.info(f"Codebase analysis confirmation: {user_confirmation[:60]}...")

        confirmation_lower = user_confirmation.lower().strip()

        if confirmation_lower in ("no", "cancel", "stop"):
            self.analysis_result.user_approved_codebase = False
            return "❌ Analysis cancelled. No changes will be made."

        if confirmation_lower not in ("yes", "ok", "proceed", "continue"):
            return """⚠️  Please confirm you've reviewed the analysis:
- Type 'yes' to proceed to plan review
- Type 'no' to cancel
- Type 'review' to see the analysis again"""

        # Approved
        self.analysis_result.user_approved_codebase = True
        self.conversation_mgr.record_user_feedback(
            f"Confirmed understanding of codebase. Ready for plan."
        )

        # Move to Phase 2: Generate plan
        return self._phase_2_generate_plan()

    def _phase_2_generate_plan(self) -> str:
        """
        Phase 2: Generate plan for the user's request.

        Now that we understand the codebase, create a plan.
        """
        logger.info("Moving to Phase 2: Generate plan")

        self.conversation_mgr.transition_to_phase(WorkflowPhase.PLAN_GENERATION)

        output = []
        output.append("\n" + "=" * 70)
        output.append("📋 PHASE 2: GENERATING PLAN FOR YOUR REQUEST")
        output.append("=" * 70 + "\n")

        user_request = self.conversation_mgr.state.user_requirement

        # Get codebase context
        analysis_dict = self.analysis_result.codebase_analysis.to_dict()
        codebase_summary = f"""
Based on codebase analysis:
- Frameworks: {', '.join(analysis_dict['detected_frameworks']) or 'None detected'}
- Main modules: {', '.join(analysis_dict['main_modules'][:3]) or 'None found'}
- Dependencies: {', '.join(list(analysis_dict['dependencies'])[:5]) or 'None found'}
- Test coverage: {len(analysis_dict['existing_tests'])} test files
- Potential impact areas: {', '.join(analysis_dict['potential_impact_files'][:3]) or 'None'}
"""

        output.append("Analyzing your request in context of full codebase...")
        output.append(f"\nYour request: {user_request}\n")
        output.append(codebase_summary)

        # Get plan from editor
        plan_dict = self.editor._get_plan_for_request(user_request)

        if not plan_dict:
            output.append(
                "\n❌ Could not generate a plan. Please try rephrasing your request."
            )
            return "\n".join(output)

        self.conversation_mgr.set_generated_plan(plan_dict)
        self.analysis_result.plan_generated = True

        # Show plan
        output.append("\n✅ Plan generated:\n")
        output.append(f"**Summary**: {plan_dict.get('summary', 'N/A')}\n")

        if "steps" in plan_dict and plan_dict["steps"]:
            output.append("**Planned Changes**:")
            for step in plan_dict["steps"][:7]:
                output.append(
                    f"  {step.get('step_number', '?')}. "
                    f"**{step.get('action', 'action').upper()}** "
                    f"`{step.get('file', 'file')}`"
                )
                if step.get("details"):
                    output.append(f"     → {step['details']}")

            if len(plan_dict.get("steps", [])) > 7:
                output.append(
                    f"     ... and {len(plan_dict['steps']) - 7} more steps"
                )

        output.append("\n" + "=" * 70)
        output.append("\n**SECOND CONFIRMATION REQUIRED**:")
        output.append("Review the plan above carefully.\n")
        output.append("Does this plan address your request correctly?")
        output.append("- Type 'yes' to approve and proceed")
        output.append("- Describe changes if you'd like to refine the plan")
        output.append("- Type 'no' to cancel")
        output.append("=" * 70 + "\n")

        return "\n".join(output)

    def handle_plan_response(self, user_input: str) -> str:
        """
        Phase 3: Handle user response to plan.

        User can:
        - Approve ('yes')
        - Refine (describe changes)
        - Cancel ('no')
        """
        logger.info(f"Plan response: {user_input[:60]}...")

        self.conversation_mgr.record_user_feedback(user_input)

        user_input_lower = user_input.lower().strip()

        if user_input_lower in ("no", "cancel", "stop"):
            return "❌ Plan cancelled. No changes will be made. You can start over with a new request."

        if user_input_lower in ("yes", "ok", "approve", "proceed"):
            return self._phase_3_confirm_execution()

        # Otherwise treat as refinement request
        return self._handle_plan_refinement(user_input)

    def _handle_plan_refinement(self, feedback: str) -> str:
        """Handle request to refine plan."""
        logger.info("Refining plan based on user feedback...")

        self.conversation_mgr.transition_to_phase(WorkflowPhase.PLAN_REFINEMENT)

        output = []
        output.append("\n🔄 **Refining plan based on your feedback...**\n")

        # Parse feedback
        parsed_feedback = self.refinement_handler.parse_user_feedback_input(feedback)

        if not self.refinement_handler.should_refine(parsed_feedback.parsing_confidence_score):
            output.append(self.refinement_handler.ask_for_clarification(parsed_feedback))
            return "\n".join(output)

        # Show what we understood
        output.append(self.refinement_handler.generate_refinement_summary(parsed_feedback))

        # Refine plan with full context
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

            output.append("\n" + "=" * 70)
            output.append("\n**Ready to proceed with refined plan?**")
            output.append("- Type 'yes' to execute")
            output.append("- Provide more feedback to refine further")
            output.append("- Type 'no' to cancel")
            output.append("=" * 70 + "\n")

        return "\n".join(output)

    def _phase_3_confirm_execution(self) -> str:
        """
        Phase 3: Final execution confirmation.

        Before executing, get explicit final confirmation.
        """
        logger.info("Moving to Phase 3: Final execution confirmation")

        self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_READY)

        output = []
        output.append("\n" + "=" * 70)
        output.append("✅ PHASE 3: READY TO EXECUTE")
        output.append("=" * 70 + "\n")

        output.append("**FINAL SUMMARY**:\n")

        # Show codebase info
        analysis = self.analysis_result.codebase_analysis
        output.append(f"📊 Application: {analysis.total_files} files, {analysis.total_lines:,} lines")
        output.append(
            f"🛠️  Frameworks: {', '.join(analysis.detected_frameworks) or 'None'}"
        )
        output.append(f"📦 Modules: {', '.join(analysis.main_modules[:3]) or 'None'}")
        output.append(f"✅ Tests: {len(analysis.existing_tests)} test files\n")

        # Show planned changes
        plan = self.conversation_mgr.state.generated_plan
        output.append(f"📝 Plan: {plan.get('summary', 'N/A')}\n")
        output.append("Changes to be made:")
        for step in plan.get("steps", [])[:5]:
            output.append(f"  • {step.get('action').upper()}: {step.get('file')}")
        if len(plan.get("steps", [])) > 5:
            output.append(f"  ... and {len(plan['steps']) - 5} more\n")

        output.append("=" * 70)
        output.append("\n**⚠️  THIS WILL MAKE REAL CHANGES TO YOUR CODE**\n")
        output.append("Are you absolutely sure? Type 'execute' to proceed:")
        output.append("(or type anything else to cancel)")
        output.append("=" * 70 + "\n")

        return "\n".join(output)

    def execute_changes(self, final_confirmation: str) -> str:
        """
        Final execution: Make the actual changes.

        Only called after THREE confirmations:
        1. User understood codebase analysis
        2. User approved the plan
        3. User confirmed to execute
        """
        logger.info(f"Final execution confirmation: {final_confirmation[:60]}...")

        if final_confirmation.lower().strip() != "execute":
            return "❌ Execution cancelled. No changes made."

        self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_IN_PROGRESS)

        output = []
        output.append("\n" + "=" * 70)
        output.append("⚡ EXECUTING CHANGES")
        output.append("=" * 70 + "\n")

        try:
            # Execute
            user_requirement = self.conversation_mgr.state.user_requirement
            result = self.editor.handle_request(user_requirement, require_approval=False)

            if result.success:
                output.append("✅ **EXECUTION SUCCESSFUL**\n")
                output.append(f"📊 Results:")
                output.append(f"  • Files modified: {len(result.modified_files)}")
                output.append(f"  • Patches applied: {result.patches_applied}")
                output.append(f"  • Time taken: {result.total_time_seconds:.1f}s\n")

                if result.modified_files:
                    output.append("Modified files:")
                    for file in result.modified_files[:5]:
                        output.append(f"  • {file}")
                    if len(result.modified_files) > 5:
                        output.append(
                            f"  ... and {len(result.modified_files) - 5} more"
                        )

                if result.warnings:
                    output.append("\n⚠️  Warnings:")
                    for warning in result.warnings[:3]:
                        output.append(f"  • {warning}")

                self.conversation_mgr.transition_to_phase(WorkflowPhase.EXECUTION_COMPLETE)
            else:
                output.append("❌ **EXECUTION FAILED**\n")
                output.append("Errors:")
                for error in result.errors[:3]:
                    output.append(f"  • {error}")

                self.conversation_mgr.transition_to_phase(WorkflowPhase.AWAITING_USER_FEEDBACK)

        except Exception as e:
            logger.error(f"Execution error: {e}")
            output.append(f"❌ **ERROR**: {str(e)}")
            self.conversation_mgr.transition_to_phase(WorkflowPhase.AWAITING_USER_FEEDBACK)

        output.append("\n" + "=" * 70 + "\n")

        return "\n".join(output)

    def get_session_summary(self) -> str:
        """Get summary of entire session."""
        if not self.conversation_mgr:
            return "No active session"

        output = []
        output.append("\n" + "=" * 70)
        output.append("SESSION SUMMARY")
        output.append("=" * 70 + "\n")

        # Codebase
        if self.analysis_result and self.analysis_result.codebase_analysis:
            analysis = self.analysis_result.codebase_analysis
            output.append("📊 **Codebase Analyzed**:")
            output.append(f"  • {analysis.total_files} files, {analysis.total_lines:,} lines")
            output.append(f"  • Frameworks: {', '.join(analysis.detected_frameworks)}")
            output.append("")

        # Confirmations
        output.append("✅ **Confirmations**:")
        output.append(
            f"  • Codebase analysis: "
            f"{'✅ Approved' if self.analysis_result.user_approved_codebase else '❌ Not approved'}"
        )
        output.append(
            f"  • Plan: {'✅ Approved' if self.analysis_result.user_approved_plan else '❌ Not approved'}"
        )

        # Status
        state = self.conversation_mgr.state
        output.append(f"\n📍 **Status**: {state.phase.value}")
        output.append(f"📝 **Request**: {state.user_requirement}")
        output.append(f"🔄 **Refinements**: {state.refinement_iteration_count}")

        output.append("\n" + "=" * 70 + "\n")

        return "\n".join(output)
