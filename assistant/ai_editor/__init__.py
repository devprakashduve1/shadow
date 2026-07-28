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
]
