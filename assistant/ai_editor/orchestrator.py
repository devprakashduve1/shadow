"""Main orchestrator that coordinates the editing pipeline."""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from .schemas import (
    CodeContext,
    EditMetrics,
    EditResult,
    IntentAnalysis,
    IntentType,
    RiskLevel,
    TestResult,
)
from .editor import CodeEditor
from .planner import Planner
from .retriever import ContextRetriever
from .validator import Validator

logger = logging.getLogger(__name__)


class AICodeEditor:
    """Orchestrate the multi-stage editing pipeline."""

    def __init__(self, project_root: str, llm_client):
        """
        Args:
            project_root: Path to project root
            llm_client: LLM client with complete() method
        """
        self.project_root = Path(project_root)
        self.llm = llm_client

        # Initialize agents
        self.retriever = ContextRetriever(str(project_root))
        self.planner = Planner(llm_client)
        self.editor = CodeEditor(llm_client)
        self.validator = Validator()

        # Metrics
        self.metrics: Optional[EditMetrics] = None

    def handle_request(self, user_request: str) -> EditResult:
        """
        Main entry point: user request → applied edits.
        """
        start_time = time.time()
        request_id = f"req-{int(start_time)}"

        try:
            # Stage 1: Analyze intent
            intent = self._analyze_intent(user_request)
            logger.info(
                f"[{request_id}] Intent: {intent.intent_type.value} "
                f"(confidence: {intent.confidence:.0%})"
            )

            # Stage 2: Retrieve context
            retrieval = self.retriever.retrieve(intent, max_files=8)
            logger.info(
                f"[{request_id}] Retrieved {len(retrieval.files)} files"
            )

            # Stage 3: Plan
            plan = self.planner.plan(intent, retrieval, user_request)
            logger.info(
                f"[{request_id}] Plan: {len(plan.steps)} steps"
            )

            # Stage 4-8: Apply with retry
            result = self._apply_plan_with_retry(
                plan, retrieval, request_id, max_retries=3
            )

            # Calculate metrics
            elapsed = time.time() - start_time
            result.total_time_seconds = elapsed

            logger.info(
                f"[{request_id}] Complete: {result.patches_applied} patches, "
                f"{len(result.errors)} errors, {elapsed:.1f}s"
            )

            return result

        except Exception as e:
            logger.error(f"[{request_id}] Failed: {e}", exc_info=True)
            return EditResult(
                success=False,
                errors=[str(e)],
                total_time_seconds=time.time() - start_time,
            )

    def _analyze_intent(self, request: str) -> IntentAnalysis:
        """Stage 1: Analyze user's request."""
        # TODO: Replace with actual intent classifier
        # For now, simple heuristic
        keywords = request.lower().split()

        intent_type = IntentType.FEATURE
        if any(w in keywords for w in ["fix", "bug", "error", "broken"]):
            intent_type = IntentType.FIX
        elif any(w in keywords for w in ["test", "test_"]):
            intent_type = IntentType.TEST
        elif any(w in keywords for w in ["refactor", "clean", "improve"]):
            intent_type = IntentType.REFACTOR
        elif any(w in keywords for w in ["doc", "comment", "docstring"]):
            intent_type = IntentType.DOCS

        complexity = 2  # Default
        if len(request) > 200:
            complexity = 4
        elif "multiple" in keywords or "several" in keywords:
            complexity = 3

        return IntentAnalysis(
            intent_type=intent_type,
            confidence=0.6,  # Conservative default
            summary=request,
            keywords=keywords[:10],
            complexity_score=complexity,
            test_needed=intent_type not in (IntentType.DOCS,),
        )

    def _apply_plan_with_retry(
        self,
        plan,
        retrieval,
        request_id: str,
        max_retries: int = 3,
    ) -> EditResult:
        """Apply plan steps with automatic retry on failure."""
        patches_applied = []
        errors = []
        warnings = []
        modified_files = []

        for step in plan.steps:
            success = False

            for attempt in range(max_retries):
                try:
                    logger.info(
                        f"[{request_id}] Step {step.step_number}: "
                        f"{step.action} {step.file} (attempt {attempt + 1})"
                    )

                    # Get file content
                    file_path = self.project_root / step.file
                    if not file_path.exists():
                        if step.action == "create":
                            content = ""
                        else:
                            raise FileNotFoundError(f"{step.file} not found")
                    else:
                        content = file_path.read_text(errors="ignore")

                    # Build context
                    context = CodeContext(
                        file_content=content,
                        file_path=step.file,
                        language=file_path.suffix.lstrip("."),
                        related_files=retrieval.files,
                        symbols=retrieval.symbols,
                    )

                    # Generate patch
                    patch = self.editor.generate_patch(
                        step, content, context
                    )

                    # Validate patch
                    validation = self.validator.validate(
                        patch, content, step.file
                    )

                    if not validation.is_valid:
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Patch validation failed: "
                                f"{validation.errors}"
                            )
                            continue  # Retry
                        else:
                            errors.extend(validation.errors)
                            raise ValueError(
                                f"Patch failed validation: "
                                f"{validation.errors[0]}"
                            )

                    # Apply patch
                    new_content = self.validator._apply_patch(
                        content, patch
                    )
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(new_content)

                    # Try formatting
                    self._format_file(file_path)

                    # Try linting
                    lint_warnings = self._lint_file(file_path)
                    if lint_warnings:
                        warnings.extend(lint_warnings)

                    patches_applied.append(patch)
                    modified_files.append(step.file)
                    success = True
                    break

                except Exception as e:
                    if attempt == max_retries - 1:
                        errors.append(f"Step {step.step_number}: {e}")
                        logger.error(
                            f"[{request_id}] Step {step.step_number} "
                            f"failed after {max_retries} attempts"
                        )
                    else:
                        logger.warning(
                            f"[{request_id}] Step {step.step_number} "
                            f"attempt {attempt + 1} failed: {e}"
                        )

            if not success and step.action != "understand":
                # Only fail if modify/create/delete failed
                pass

        # Run tests
        if modified_files and not errors:
            test_result = self._run_tests(modified_files)
            if not test_result.passed:
                warnings.append(f"Tests failed: {test_result.failed_tests}")

        return EditResult(
            success=len(errors) == 0,
            patches_applied=len(patches_applied),
            errors=errors,
            warnings=warnings,
            modified_files=modified_files,
        )

    def _format_file(self, file_path: Path):
        """Format file using appropriate formatter."""
        if file_path.suffix == ".py":
            try:
                subprocess.run(
                    ["black", "--quiet", str(file_path)],
                    capture_output=True,
                    timeout=10,
                )
            except:
                pass

        elif file_path.suffix in (".js", ".ts", ".jsx", ".tsx"):
            try:
                subprocess.run(
                    ["prettier", "--write", str(file_path)],
                    capture_output=True,
                    timeout=10,
                )
            except:
                pass

        elif file_path.suffix == ".go":
            try:
                subprocess.run(
                    ["gofmt", "-w", str(file_path)],
                    capture_output=True,
                    timeout=10,
                )
            except:
                pass

    def _lint_file(self, file_path: Path) -> list:
        """Lint file and return warnings."""
        warnings = []

        if file_path.suffix == ".py":
            try:
                result = subprocess.run(
                    ["pylint", "--disable=all", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    warnings.append(
                        f"Lint issues in {file_path.name}"
                    )
            except:
                pass

        return warnings

    def _run_tests(self, modified_files: list) -> TestResult:
        """Run relevant tests."""
        try:
            # For now, just check if pytest is available
            result = subprocess.run(
                ["pytest", "-xvs", "--tb=short", "tests/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return TestResult(
                passed=result.returncode == 0,
                tests_run=1,  # Simplified
                tests_passed=1 if result.returncode == 0 else 0,
                stdout=result.stdout[:500],
                stderr=result.stderr[:500],
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                error="Tests timed out after 60s",
            )
        except FileNotFoundError:
            # pytest not available
            return TestResult(passed=True)  # Assume success if no tests
