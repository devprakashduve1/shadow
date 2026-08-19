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
        """Build optimized prompt for precise code generation."""

        code_preview = self._extract_relevant_section(
            file_content, step.target_function
        )
        related_context = self._build_related_context(context)

        error_section = ""
        if previous_error:
            error_section = f"""
## PREVIOUS ATTEMPT FAILED
**Error:** {previous_error}

Please analyze what went wrong and try a different approach:
- Check for exact text matching (whitespace, quotes, indentation)
- Verify the search pattern exists in the code
- Try shorter, more specific search strings
- Consider using insert instead of replace if needed

"""

        prompt = f"""# CODE GENERATION FOR PATCH

## CONTEXT
**File:** `{step.file}` ({context.language})
**Step:** {step.step_number} - {step.action.upper()}
**Target:** {step.target_function or "(whole file)"}

{error_section}

## CURRENT CODE
The relevant section you'll be modifying:

```{context.language}
{code_preview}
```

## RELATED CONTEXT
Available symbols and files you can reference:
{related_context}

## CHANGE SPECIFICATION

**What to do:** {step.details}
**Why:** {step.reason or step.goal or "As per plan"}
**Change Type:** {step.change_type or "general"}

## REQUIREMENTS & CONSTRAINTS

**Must follow:**
1. ✅ Preserve function signatures (don't change method/function names)
2. ✅ Only modify what's specified - don't touch other functions
3. ✅ Maintain code style and indentation
4. ✅ Keep all existing logic that's not being changed
5. ✅ Add required imports via add_import operations
6. ✅ Remove unused imports if applicable
7. ✅ Follow existing code patterns and conventions
8. ✅ Ensure changes are syntactically correct

**Avoid:**
- ❌ Breaking existing functionality
- ❌ Adding commented-out code
- ❌ Changing unrelated code
- ❌ Modifying imports unless necessary
- ❌ Creating new files (use create action if needed)

## OPERATION TYPES

Use the correct operation for each change:

1. **replace** - Replace specific text
   - Best for: Changing method bodies, variables, logic
   - Requires: Exact text to find (search) and replacement text

2. **insert** - Insert new code after a line
   - Best for: Adding new lines, methods, statements
   - Requires: Line number (line_start) and text to insert

3. **delete** - Remove code between lines
   - Best for: Removing lines or code blocks
   - Requires: Start and end line numbers

4. **add_import** - Add import statement
   - Best for: Adding new module imports
   - Requires: Import statement and position (after_line)

5. **remove_import** - Remove import statement
   - Best for: Removing unused imports
   - Requires: Import statement to remove

## EXAMPLES

### Example 1: Replace function body
```json
{{
  "type": "replace",
  "search": "def validate_email(self, email):\\n        return True",
  "replacement": "def validate_email(self, email):\\n        return '@' in email and '.' in email.split('@')[1]"
}}
```

### Example 2: Add import
```json
{{
  "type": "add_import",
  "import_statement": "from validators import EmailValidator",
  "after_line": 3
}}
```

### Example 3: Insert new method
```json
{{
  "type": "insert",
  "line_start": 25,
  "text": "\\n    def new_method(self):\\n        pass"
}}
```

## RESPONSE FORMAT

Return ONLY valid JSON (no markdown, no explanation, no notes):

```json
{{
  "operations": [
    {{
      "type": "replace",
      "search": "exact_text_to_search_for",
      "replacement": "new_replacement_text"
    }},
    {{
      "type": "add_import",
      "import_statement": "import module",
      "after_line": 5
    }},
    {{
      "type": "insert",
      "line_start": 45,
      "text": "new code to insert"
    }}
  ]
}}
```

**Critical:** Start response with opening brace `{{` immediately. No preamble.
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
