"""AI Code Editor: Production-grade editing pipeline.

Multi-stage architecture for reliable, local-LLM-friendly code editing.
See docs/AI_EDITOR_ARCHITECTURE.md for full documentation.
"""

from .schemas import (
    IntentAnalysis,
    RetrievalResult,
    PlanResult,
    PlanStep,
    Patch,
    PatchOperation,
    EditResult,
    ValidationResult,
    TestResult,
)
from .retriever import ContextRetriever
from .planner import Planner
from .editor import CodeEditor
from .validator import Validator
from .orchestrator import AICodeEditor
from .props_analyzer import (
    PropsAnalyzer,
    PropsAnalysis,
    Requirement,
    RequirementType,
)
from .review import (
    ReviewManager,
    PlanReview,
    ConfirmationRequest,
    ReviewStatus,
)
from .conversation_manager import (
    ConversationManager,
    ConversationOrchestrator,
    WorkflowPhase,
    MessageSenderType,
    ConversationMessage,
    InteractionState,
)
from .diff_generator import (
    UnifiedDiffGenerator,
    CodeModificationDiff,
)
from .refinement_handler import (
    PlanRefinementHandler,
    ParsedUserFeedback,
)
from .conversational_orchestrator import (
    ConversationalAICodeEditor,
)

__all__ = [
    "IntentAnalysis",
    "RetrievalResult",
    "PlanResult",
    "PlanStep",
    "Patch",
    "PatchOperation",
    "EditResult",
    "ValidationResult",
    "TestResult",
    "ContextRetriever",
    "Planner",
    "CodeEditor",
    "Validator",
    "AICodeEditor",
    "PropsAnalyzer",
    "PropsAnalysis",
    "Requirement",
    "RequirementType",
    "ReviewManager",
    "PlanReview",
    "ConfirmationRequest",
    "ReviewStatus",
    "ConversationManager",
    "ConversationOrchestrator",
    "WorkflowPhase",
    "MessageSenderType",
    "ConversationMessage",
    "InteractionState",
    "UnifiedDiffGenerator",
    "CodeModificationDiff",
    "PlanRefinementHandler",
    "ParsedUserFeedback",
    "ConversationalAICodeEditor",
]
