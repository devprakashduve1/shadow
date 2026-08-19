"""Generate and display visual diffs for code changes."""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CodeModificationDiff:
    """Single code modification with before/after content."""
    file_path: str
    previous_content: str
    modified_content: str
    operation_type: str  # "modify", "create", "delete"
    line_range: Tuple[int, int]  # start_line, end_line
    modification_description: str


class UnifiedDiffGenerator:
    """Generate standardized diff representations for code modifications."""

    @staticmethod
    def generate_unified_format(previous_content: str, modified_content: str,
                               file_path: str, context_line_count: int = 3) -> str:
        """Generate unified diff format compatible with git diff.

        Args:
            previous_content: Original file content
            modified_content: Modified file content
            file_path: Path to the file
            context_line_count: Number of context lines to display

        Returns:
            Formatted unified diff string
        """
        import difflib

        previous_lines = previous_content.splitlines(keepends=True)
        modified_lines = modified_content.splitlines(keepends=True)

        diff_generator = difflib.unified_diff(
            previous_lines,
            modified_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
            n=context_line_count,
        )

        return "\n".join(diff_generator)

    @staticmethod
    def generate_side_by_side_format(previous_content: str, modified_content: str,
                                     column_width: int = 40) -> str:
        """Generate side-by-side diff format for readability.

        Args:
            previous_content: Original file content
            modified_content: Modified file content
            column_width: Width of each column

        Returns:
            Formatted side-by-side diff string
        """
        import difflib

        previous_lines = previous_content.splitlines()
        modified_lines = modified_content.splitlines()

        # Use SequenceMatcher to find differences
        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)

        output = []
        output.append("╔" + "═" * (width - 2) + "╦" + "═" * (width - 2) + "╗")
        output.append("║ BEFORE" + " " * (width - 10) + "║ AFTER" + " " * (width - 9) + "║")
        output.append("╠" + "═" * (width - 2) + "╬" + "═" * (width - 2) + "╠")

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for line in before_lines[i1:i2]:
                    output.append(
                        f"║ {line:<{width-3}}║ {line:<{width-3}}║"
                    )
            elif tag == "replace":
                for before_line in before_lines[i1:i2]:
                    output.append(
                        f"║ {before_line:<{width-3}}║ " + " " * (width - 3) + "║"
                    )
                for after_line in after_lines[j1:j2]:
                    output.append(
                        f"║ " + " " * (width - 3) + f"║ {after_line:<{width-3}}║"
                    )
            elif tag == "delete":
                for before_line in before_lines[i1:i2]:
                    output.append(
                        f"║ {before_line:<{width-3}}║ " + " " * (width - 3) + "║"
                    )
            elif tag == "insert":
                for after_line in after_lines[j1:j2]:
                    output.append(
                        f"║ " + " " * (width - 3) + f"║ {after_line:<{width-3}}║"
                    )

        output.append("╚" + "═" * (width - 2) + "╩" + "═" * (width - 2) + "╝")
        return "\n".join(output)

    @staticmethod
    def generate_summary_diff(diffs: List[CodeDiff]) -> str:
        """Generate a summary of all diffs."""
        output = []

        output.append("=" * 70)
        output.append("CODE CHANGES SUMMARY")
        output.append("=" * 70)

        # Count changes
        modified = [d for d in diffs if d.operation == "modify"]
        created = [d for d in diffs if d.operation == "create"]
        deleted = [d for d in diffs if d.operation == "delete"]

        output.append(f"\n📊 STATISTICS:")
        output.append(f"  Files modified: {len(modified)}")
        output.append(f"  Files created: {len(created)}")
        output.append(f"  Files deleted: {len(deleted)}")

        # List files
        if modified:
            output.append(f"\n📝 MODIFIED ({len(modified)}):")
            for diff in modified:
                lines_changed = len(diff.before.splitlines()) - len(diff.after.splitlines())
                change_indicator = "+" if lines_changed < 0 else "-"
                output.append(f"  {change_indicator} {diff.file_path}")
                output.append(f"     {diff.description}")

        if created:
            output.append(f"\n✨ CREATED ({len(created)}):")
            for diff in created:
                output.append(f"  ➕ {diff.file_path}")
                output.append(f"     {diff.description}")

        if deleted:
            output.append(f"\n🗑️  DELETED ({len(deleted)}):")
            for diff in deleted:
                output.append(f"  ➖ {diff.file_path}")
                output.append(f"     {diff.description}")

        output.append("\n" + "=" * 70)
        return "\n".join(output)

    @staticmethod
    def format_diff_for_display(code_diff: CodeDiff, style: str = "unified") -> str:
        """Format a single diff for display."""
        output = []

        # Header
        output.append("\n" + "=" * 70)
        output.append(f"FILE: {code_diff.file_path} [{code_diff.operation.upper()}]")
        output.append("=" * 70)

        # Description
        output.append(f"\n📝 Change: {code_diff.description}")
        output.append(f"📍 Lines: {code_diff.line_numbers[0]}-{code_diff.line_numbers[1]}")

        # Diff
        output.append("\n" + "-" * 70)
        if style == "unified":
            diff = DiffGenerator.generate_unified_diff(
                code_diff.before,
                code_diff.after,
                code_diff.file_path
            )
        else:
            diff = DiffGenerator.generate_side_by_side_diff(
                code_diff.before,
                code_diff.after
            )

        output.append(diff)
        output.append("-" * 70)

        return "\n".join(output)

    @staticmethod
    def create_code_diff(
        file_path: str,
        before_content: str,
        after_content: str,
        operation: str,
        description: str,
        line_start: int = 1,
        line_end: Optional[int] = None,
    ) -> CodeDiff:
        """Create a CodeDiff object."""
        if line_end is None:
            line_end = len(after_content.splitlines())

        return CodeDiff(
            file_path=file_path,
            before=before_content,
            after=after_content,
            operation=operation,
            line_numbers=(line_start, line_end),
            description=description,
        )

    @staticmethod
    def highlight_changes(before: str, after: str) -> Tuple[str, str]:
        """Add highlighting to before/after for terminal display."""
        # ANSI color codes
        RED = "\033[91m"
        GREEN = "\033[92m"
        RESET = "\033[0m"

        before_lines = before.splitlines()
        after_lines = after.splitlines()

        highlighted_before = []
        highlighted_after = []

        # Simple highlighting - mark removed lines in red
        for line in before_lines:
            highlighted_before.append(f"{RED}─ {line}{RESET}")

        # Mark added lines in green
        for line in after_lines:
            highlighted_after.append(f"{GREEN}+ {line}{RESET}")

        return "\n".join(highlighted_before), "\n".join(highlighted_after)

    @staticmethod
    def generate_inline_diff(before: str, after: str) -> str:
        """Generate inline diff showing changes in context."""
        import difflib

        output = []
        before_lines = before.splitlines()
        after_lines = after.splitlines()

        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)

        for i, line in enumerate(before_lines):
            output.append(f"  {i+1:3} │ {line}")

        output.append("")
        output.append("        ↓ BECOMES ↓")
        output.append("")

        for i, line in enumerate(after_lines):
            output.append(f"  {i+1:3} │ {line}")

        return "\n".join(output)
