"""Patch validation before application."""

import ast
import logging
import re
from pathlib import Path
from typing import List

from .schemas import Patch, ValidationResult

logger = logging.getLogger(__name__)


class Validator:
    """Validate patches for safety and correctness."""

    def validate(
        self, patch: Patch, file_content: str, file_path: str
    ) -> ValidationResult:
        """Validate a patch against current file content."""
        errors: List[str] = []
        warnings: List[str] = []
        syntax_valid = True
        imports_valid = True
        formatting_valid = True

        # Check 1: Search text exists for replace operations
        for op in patch.operations:
            if op.type.value == "replace" and op.search:
                if op.search not in file_content:
                    errors.append(
                        f"Replace: Search text not found in file "
                        f"({len(op.search)} chars)"
                    )

        # Check 2: Apply patch and check syntax
        try:
            new_content = self._apply_patch(file_content, patch)
        except Exception as e:
            errors.append(f"Failed to apply patch: {e}")
            return ValidationResult(
                is_valid=False,
                errors=errors,
                syntax_valid=False,
            )

        # Check 3: Syntax validity
        if file_path.endswith(".py"):
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                errors.append(
                    f"Syntax error after patch (line {e.lineno}): {e.msg}"
                )
                syntax_valid = False
        elif file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
            # Basic validation: check for common syntax errors
            if not self._validate_js_syntax(new_content):
                errors.append("Possible JavaScript/TypeScript syntax error")
                syntax_valid = False

        # Check 4: Import validity
        import_issues = self._check_imports(file_content, new_content)
        if import_issues:
            warnings.extend(import_issues)
            imports_valid = len([i for i in import_issues if "missing" in i.lower()]) == 0

        # Check 5: No obvious formatting violations
        formatting_issues = self._check_formatting(file_path, new_content)
        if formatting_issues:
            warnings.extend(formatting_issues)
            formatting_valid = False

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            syntax_valid=syntax_valid,
            imports_valid=imports_valid,
            formatting_valid=formatting_valid,
        )

    def _apply_patch(self, content: str, patch: Patch) -> str:
        """Apply patch operations to content."""
        result = content
        lines = content.split("\n")

        # Sort operations to apply in reverse order (to avoid line number shifts)
        # Operations with line numbers first
        line_ops = [
            op for op in patch.operations
            if op.line_start is not None or op.line_end is not None
        ]
        search_ops = [op for op in patch.operations if op.search is not None]

        # Apply line-based operations in reverse
        for op in sorted(
            line_ops,
            key=lambda o: -(o.line_start or o.line_end or 0),
        ):
            if op.type.value == "replace" and op.line_start is not None:
                start = op.line_start - 1  # Convert to 0-indexed
                end = (op.line_end or op.line_start)
                if op.replacement:
                    lines[start:end] = op.replacement.split("\n")

            elif op.type.value == "insert" and op.line_start is not None:
                if op.replacement:
                    lines.insert(op.line_start, op.replacement)

            elif op.type.value == "delete" and op.line_start is not None:
                start = op.line_start - 1
                end = (op.line_end or op.line_start)
                del lines[start:end]

            elif op.type.value == "add_import" and op.after_line is not None:
                import_line = op.import_statement or ""
                lines.insert(op.after_line, import_line)

        result = "\n".join(lines)

        # Apply search-replace operations
        for op in search_ops:
            if op.type.value == "replace" and op.search and op.replacement:
                result = result.replace(op.search, op.replacement, 1)

        return result

    def _validate_js_syntax(self, content: str) -> bool:
        """Basic validation for JavaScript/TypeScript."""
        # Count braces
        open_braces = content.count("{") + content.count("[") + content.count("(")
        close_braces = content.count("}") + content.count("]") + content.count(")")

        if open_braces != close_braces:
            return False

        # Check for common issues
        if content.count('"""') % 2 != 0:
            return False

        return True

    def _check_imports(self, old_content: str, new_content: str) -> List[str]:
        """Check for import-related issues."""
        issues = []

        if old_content.endswith(".py"):
            try:
                old_tree = ast.parse(old_content)
                new_tree = ast.parse(new_content)

                old_imports = set()
                new_imports = set()

                for node in ast.walk(old_tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            old_imports.add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            old_imports.add(node.module)

                for node in ast.walk(new_tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            new_imports.add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            new_imports.add(node.module)

                removed = old_imports - new_imports
                if removed:
                    issues.append(
                        f"Imports removed that might be used: {removed}"
                    )

            except:
                pass

        return issues

    def _check_formatting(self, file_path: str, content: str) -> List[str]:
        """Check for formatting issues."""
        issues = []

        if file_path.endswith(".py"):
            lines = content.split("\n")
            for i, line in enumerate(lines):
                # Check for mixed tabs/spaces
                if "\t" in line and "    " in line:
                    issues.append(f"Line {i+1}: Mixed tabs and spaces")
                    break  # Only warn once

                # Check for trailing whitespace
                if line != line.rstrip() and line.strip():
                    if i == 0:  # Only report first occurrence
                        issues.append("Trailing whitespace found")

        return issues[:3]  # Limit to 3 warnings
