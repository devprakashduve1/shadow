"""Data structures for the AI editing pipeline."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class IntentType(str, Enum):
    """Classification of user request intent."""
    FIX = "fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TEST = "test"
    DOCS = "docs"
    DEBUG = "debug"


class RiskLevel(str, Enum):
    """Assessment of breaking change risk."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PatchOpType(str, Enum):
    """Type of patch operation."""
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"
    ADD_IMPORT = "add_import"
    REMOVE_IMPORT = "remove_import"


@dataclass(frozen=True)
class SymbolLocation:
    """Location of a symbol (function, class, variable) in code."""
    file: str
    line: int
    type: str  # "function", "class", "variable", etc.
    name: Optional[str] = None


@dataclass
class IntentAnalysis:
    """Result of analyzing user's request."""
    intent_type: IntentType
    confidence: float  # 0.0-1.0
    summary: str
    keywords: List[str] = field(default_factory=list)
    likely_symbols: List[str] = field(default_factory=list)
    likely_files: List[str] = field(default_factory=list)
    requires_new_file: bool = False
    requires_delete: bool = False
    complexity_score: int = 1  # 1-5
    estimated_files: int = 1
    breaking_changes_risk: RiskLevel = RiskLevel.LOW
    test_needed: bool = True


@dataclass
class BundledFile:
    """A retrieved file with metadata and context."""
    file_path: str
    content: str
    language: str
    size_bytes: int
    symbols: Dict[str, SymbolLocation] = field(default_factory=dict)
    related_files: List[str] = field(default_factory=list)
    test_coverage: Optional[float] = None
    last_modified: Optional[str] = None


@dataclass
class RetrievalResult:
    """Result of context retrieval phase."""
    files: List[BundledFile]
    symbols: Dict[str, SymbolLocation]
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    call_graph: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class PlanStep:
    """One step in an editing plan."""
    step_number: int
    action: str  # "understand", "modify", "create", "delete", "test"
    file: str
    target_function: Optional[str] = None
    change_type: Optional[str] = None
    details: str = ""
    goal: str = ""
    depends_on: List[int] = field(default_factory=list)


@dataclass
class PlanResult:
    """Result of planning phase."""
    plan_id: str
    steps: List[PlanStep]
    summary: str = ""
    estimated_impact: Dict = field(default_factory=dict)
    requires_user_approval: bool = False
    estimated_tokens: int = 0
    raw: str = ""  # Original LLM response


@dataclass
class PatchOperation:
    """Single edit operation within a patch."""
    type: PatchOpType
    search: Optional[str] = None
    replacement: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    import_statement: Optional[str] = None
    after_line: Optional[int] = None


@dataclass
class Patch:
    """Structured patch for a single file."""
    file: str
    operations: List[PatchOperation]
    validation: Dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of patch validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    syntax_valid: bool = True
    imports_valid: bool = True
    formatting_valid: bool = True


@dataclass
class TestResult:
    """Result of running tests."""
    passed: bool
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    failed_tests: List[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


@dataclass
class EditResult:
    """Final result of apply_with_retry."""
    success: bool
    patches_applied: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    branch: Optional[str] = None
    commit_hash: Optional[str] = None
    test_results: Optional[TestResult] = None
    total_time_seconds: float = 0.0


@dataclass
class CodeContext:
    """Context for code editing."""
    file_content: str
    file_path: str
    language: str
    related_files: List[BundledFile] = field(default_factory=list)
    symbols: Dict[str, SymbolLocation] = field(default_factory=dict)
    call_graph: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class EditMetrics:
    """Metrics tracking for an edit request."""
    request_id: str
    intent_confidence: float
    files_retrieved: int
    plan_steps: int
    patches_generated: int
    patches_valid: int
    patches_applied: int
    apply_attempts: int
    tests_run: int
    tests_passed: bool
    total_time_seconds: float
    success: bool
    error_message: Optional[str] = None

    @property
    def validation_rate(self) -> float:
        """Percentage of patches that passed validation."""
        if self.patches_generated == 0:
            return 1.0
        return self.patches_valid / self.patches_generated

    @property
    def apply_success_rate(self) -> float:
        """Percentage of valid patches applied successfully."""
        if self.patches_valid == 0:
            return 1.0
        return self.patches_applied / self.patches_valid

    @property
    def test_pass_rate(self) -> float:
        """Percentage of test runs that passed."""
        if self.tests_run == 0:
            return 1.0
        return 1.0 if self.tests_passed else 0.0
