"""Code editor agent that generates patches."""

import json
import logging
from typing import List, Optional

from .schemas import CodeContext, Patch, PatchOperation, PlanStep, PatchOpType

logger = logging.getLogger(__name__)


class CodeEditor:
    """Generate patches for code modifications."""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM client with complete() method
        """
        self.llm = llm_client

    def generate_patch(
        self,
        step: PlanStep,
        file_content: str,
        context: CodeContext,
        current_attempt: int = 1,
        previous_error: Optional[str] = None,
    ) -> Patch:
        """Generate patch for a plan step."""

        prompt = self._build_prompt(
            step, file_content, context, previous_error
        )

        # Call LLM
        response = self.llm.complete(
            prompt,
            max_tokens=3000 if current_attempt == 1 else 2000,
            temperature=0.1,
        )

        # Parse patch
        patch_data = self._parse_response(response)
        operations = self._build_operations(patch_data.get("operations", []))

        patch = Patch(
            file=step.file,
            operations=operations,
        )

        logger.info(f"Generated patch with {len(operations)} operations")
        return patch

    def _build_prompt(
        self,
        step: PlanStep,
        file_content: str,
        context: CodeContext,
        previous_error: Optional[str],
    ) -> str:
        """Build focused prompt for code generation."""

        # Show relevant code section
        code_preview = self._extract_relevant_section(
            file_content, step.target_function
        )

        # Build related functions context
        related_context = self._build_related_context(context)

        # Prefix if retry
        error_prefix = ""
        if previous_error:
            error_prefix = f"""
PREVIOUS ATTEMPT FAILED:
{previous_error}

Fix this specific issue. Try a different approach if needed.
"""

        prompt = f"""
{error_prefix}

FILE: {step.file}
LANGUAGE: {context.language}

CURRENT CODE:
```{context.language}
{code_preview}
```

RELATED FUNCTIONS/CONTEXT:
{related_context}

CHANGE NEEDED:
- Target: {step.target_function or "file"}
- Type: {step.change_type or "modify"}
- Details: {step.details}

RULES:
1. Keep function signature unchanged (if modifying)
2. Don't touch other functions
3. Only modify what's specified
4. Add imports if needed via "add_import" operation
5. Keep existing logic that's not being changed

OUTPUT ONLY VALID JSON (no explanation):
{{
  "operations": [
    {{
      "type": "replace",
      "search": "exact_text_to_find",
      "replacement": "new_text"
    }},
    {{
      "type": "add_import",
      "import_statement": "import something",
      "after_line": 5
    }}
  ]
}}

Valid operation types: replace, insert, delete, add_import, remove_import

Start with JSON opening brace immediately.
"""

        return prompt

    def _extract_relevant_section(
        self, file_content: str, target_function: Optional[str]
    ) -> str:
        """Extract relevant code section for context."""
        if not target_function:
            # Show first 50 lines
            lines = file_content.split("\n")
            return "\n".join(lines[:50])

        # Try to find the function
        lines = file_content.split("\n")
        for i, line in enumerate(lines):
            if f"def {target_function}" in line or f"async def {target_function}" in line:
                # Found it, extract with context
                start = max(0, i - 2)
                end = min(len(lines), i + 30)
                return "\n".join(lines[start:end])

        # Fallback
        return "\n".join(lines[:50])

    def _build_related_context(self, context: CodeContext) -> str:
        """Build context about related code."""
        parts = []

        # Related files
        if context.related_files:
            parts.append("Related files:")
            for f in context.related_files[:3]:
                parts.append(f"  - {f.file_path}")

        # Related symbols
        if context.symbols:
            parts.append("Available symbols:")
            for symbol, loc in list(context.symbols.items())[:5]:
                parts.append(f"  - {symbol}: {loc.type} at {loc.file}:{loc.line}")

        return "\n".join(parts) if parts else "(none)"

    def _parse_response(self, response: str) -> dict:
        """Parse LLM response as JSON."""
        response = response.strip()

        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass

        # Fallback
        logger.warning("Could not parse patch response as JSON")
        return {"operations": []}

    def _build_operations(self, ops_data: list) -> List[PatchOperation]:
        """Convert operation data to PatchOperation objects."""
        operations = []

        for op_data in ops_data:
            op_type = op_data.get("type", "replace")
            try:
                op_type_enum = PatchOpType(op_type)
            except ValueError:
                logger.warning(f"Unknown operation type: {op_type}")
                continue

            op = PatchOperation(
                type=op_type_enum,
                search=op_data.get("search"),
                replacement=op_data.get("replacement"),
                line_start=op_data.get("line_start"),
                line_end=op_data.get("line_end"),
                import_statement=op_data.get("import_statement"),
                after_line=op_data.get("after_line"),
            )
            operations.append(op)

        return operations
