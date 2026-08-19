"""Review and confirmation workflow for code changes."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

from .schemas import PlanResult
from .props_analyzer import PropsAnalysis

logger = logging.getLogger(__name__)


class ReviewStatus(str, Enum):
    """Status of review."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass
class PlanReview:
    """Review and approval of a plan before execution."""
    plan: PlanResult
    props_analysis: PropsAnalysis

    # Review metadata
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer_notes: str = ""
    concerns: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    approved_by: Optional[str] = None

    # Change summary
    files_affected: List[str] = field(default_factory=list)
    operations_count: int = 0
    estimated_time_seconds: float = 0.0

    def __post_init__(self):
        """Calculate derived fields."""
        # Collect affected files
        self.files_affected = list(set(step.file for step in self.plan.steps))
        # Count operations
        self.operations_count = len(self.plan.steps)
        # Extract estimated time from plan
        self.estimated_time_seconds = self.plan.estimated_tokens / 50  # Rough estimate

    def format_for_display(self) -> str:
        """Format review for user display."""
        lines = []

        lines.append("=" * 70)
        lines.append("CODE CHANGE REVIEW")
        lines.append("=" * 70)

        # Request & Scope
        lines.append("\n📋 REQUEST & SCOPE:")
        lines.append(f"  Original: {self.props_analysis.raw_request[:80]}...")
        lines.append(f"  Scope: {self.props_analysis.scope_description}")
        lines.append(
            f"  Complexity: {self.props_analysis.estimated_complexity}/5 "
            f"(Confidence: {self.props_analysis.confidence_score:.0%})"
        )

        # Requirements
        lines.append("\n✅ REQUIREMENTS IDENTIFIED:")
        for req in self.props_analysis.requirements:
            lines.append(
                f"  • [{req.priority.upper()}] {req.type.value}: {req.description}"
            )
        if not self.props_analysis.requirements:
            lines.append("  (No specific requirements detected)")

        # Affected Components
        if self.props_analysis.affected_components:
            lines.append("\n🔧 AFFECTED COMPONENTS:")
            for component in self.props_analysis.affected_components:
                lines.append(f"  • {component}")

        # Plan Steps
        lines.append("\n📝 PLAN STEPS:")
        for step in self.plan.steps:
            lines.append(
                f"  {step.step_number}. [{step.action.upper()}] {step.file}"
            )
            if step.target_function:
                lines.append(f"     Function: {step.target_function}")
            if step.details:
                lines.append(f"     Details: {step.details}")

        # Files to Modify
        lines.append("\n📁 FILES AFFECTED:")
        for file in self.files_affected:
            lines.append(f"  • {file}")

        # Warnings
        if self.props_analysis.breaking_changes_possible:
            lines.append("\n⚠️  BREAKING CHANGES POSSIBLE")

        if self.props_analysis.clarifications_needed:
            lines.append("\n❓ CLARIFICATIONS NEEDED:")
            for clarification in self.props_analysis.clarifications_needed:
                lines.append(f"  • {clarification}")

        # Impact
        lines.append("\n📊 ESTIMATED IMPACT:")
        impact = self.plan.estimated_impact or {}
        lines.append(f"  Files to modify: {impact.get('files_to_modify', '?')}")
        lines.append(f"  Files to create: {impact.get('files_to_create', 0)}")
        lines.append(
            f"  Breaking changes risk: "
            f"{impact.get('breaking_changes', 0) > 0 and 'HIGH' or 'LOW'}"
        )
        lines.append(f"  Estimated time: ~{self.estimated_time_seconds:.0f}s")

        lines.append("\n" + "=" * 70)

        return "\n".join(lines)

    def add_concern(self, concern: str) -> None:
        """Add a reviewer concern."""
        if concern not in self.concerns:
            self.concerns.append(concern)

    def add_question(self, question: str) -> None:
        """Add a reviewer question."""
        if question not in self.questions:
            self.questions.append(question)

    def approve(self, reviewer: str = "user") -> None:
        """Approve the plan."""
        self.status = ReviewStatus.APPROVED
        self.approved_by = reviewer

    def reject(self, reason: str, reviewer: str = "user") -> None:
        """Reject the plan."""
        self.status = ReviewStatus.REJECTED
        self.reviewer_notes = reason
        self.approved_by = reviewer

    def request_clarification(self, questions: List[str]) -> None:
        """Request clarification before proceeding."""
        self.status = ReviewStatus.NEEDS_CLARIFICATION
        self.questions = questions


@dataclass
class ConfirmationRequest:
    """Request for user confirmation to proceed with changes."""
    review: PlanReview
    required_confirmations: List[str] = field(default_factory=list)
    confirmed: bool = False
    user_notes: str = ""

    def __post_init__(self):
        """Generate required confirmations based on review."""
        confirmations = []

        # Basic confirmation
        confirmations.append(
            f"Proceed with modifying {len(self.review.files_affected)} file(s)?"
        )

        # Breaking changes confirmation
        if self.review.props_analysis.breaking_changes_possible:
            confirmations.append(
                "This may introduce breaking changes. Continue?"
            )

        # High complexity confirmation
        if self.review.props_analysis.estimated_complexity >= 4:
            confirmations.append(
                "This is a complex change. Do you want to proceed?"
            )

        self.required_confirmations = confirmations

    def get_confirmation_prompt(self) -> str:
        """Get user-friendly confirmation prompt."""
        lines = []
        lines.append(self.review.format_for_display())
        lines.append("\n" + "=" * 70)
        lines.append("CONFIRMATIONS REQUIRED:")
        for i, confirm in enumerate(self.required_confirmations, 1):
            lines.append(f"  {i}. {confirm}")
        lines.append("=" * 70)
        lines.append("\nDo you approve these changes? (yes/no)")

        return "\n".join(lines)

    def confirm(self, user_response: bool, notes: str = "") -> None:
        """Record user confirmation."""
        self.confirmed = user_response
        self.user_notes = notes
        logger.info(
            f"Changes {'approved' if user_response else 'rejected'} by user"
        )


class ReviewManager:
    """Manage the review and confirmation workflow."""

    @staticmethod
    def create_review(
        plan: PlanResult, props_analysis: PropsAnalysis
    ) -> PlanReview:
        """Create a review from plan and analysis."""
        return PlanReview(
            plan=plan,
            props_analysis=props_analysis,
        )

    @staticmethod
    def create_confirmation_request(review: PlanReview) -> ConfirmationRequest:
        """Create a confirmation request from review."""
        return ConfirmationRequest(review=review)

    @staticmethod
    def validate_confirmation(confirmation: ConfirmationRequest) -> bool:
        """Check if confirmation is valid and approved."""
        return confirmation.confirmed and confirmation.review.status in (
            ReviewStatus.APPROVED,
            ReviewStatus.PENDING,  # If no explicit rejection
        )
