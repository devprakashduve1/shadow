"""Extracts the symbols a file defines, for the Knowledge Bank's outline.

Two very different levels of accuracy, and the index records which was used:

- **Python** uses the stdlib `ast`, so classes, functions, signatures, docstrings
  and imports are exact.
- **Everything else** uses per-language regex, because no parser for those
  languages is available here and adding one per ecosystem isn't proportionate.
  These results are genuinely approximate — see `_REGEX_LIMITATIONS` for what
  they miss. Entries are tagged `parse="regex"` so context assembly can prefer
  real file excerpts over a possibly-wrong symbol list.

The point is a *navigational* index ("auth logic is probably in these files"),
not a compiler-grade symbol table.
"""
from __future__ import annotations

import ast
import re
from typing import List, Tuple

from .schema import Symbol, language_for_path

# Guards against a generated or minified file producing thousands of matches and
# bloating the index for no benefit.
MAX_SYMBOLS_PER_FILE = 200

# Documented, deliberate gaps in the regex path. Not exhaustive, but these are
# the ones that come up constantly:
_REGEX_LIMITATIONS = """
- arrow functions assigned to object properties or passed inline
- methods inside classes (only the class itself is found)
- declarations split across lines, or wrapped in decorators/generics
- anything inside a template literal or a multi-line comment we didn't strip
- re-exports (`export * from`) contribute no symbol names
"""

# Line comment markers per language, stripped before matching so commented-out
# code doesn't register as a definition.
_LINE_COMMENT = {
    "javascript": "//", "typescript": "//", "go": "//", "rust": "//", "java": "//",
    "kotlin": "//", "swift": "//", "csharp": "//", "c": "//", "cpp": "//", "php": "//",
    "scss": "//", "dart": "//",
    "python": "#", "ruby": "#", "shell": "#", "r": "#", "make": "#", "dockerfile": "#",
    "yaml": "#", "toml": "#",
    "sql": "--", "lua": "--",
}

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# (kind, compiled pattern) per language. Each is anchored at line start and
# tolerant of the usual modifier prefixes.
_PATTERNS = {
    "javascript": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")),
        ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
        # Arrow functions and function expressions bound to a top-level name.
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("const", re.compile(r"^\s*(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*=")),
    ],
    "go": [
        ("function", re.compile(r"^func\s+([A-Za-z_]\w*)\s*\(")),
        ("method", re.compile(r"^func\s*\([^)]*\)\s*([A-Za-z_]\w*)\s*\(")),
        ("type", re.compile(r"^type\s+([A-Za-z_]\w*)\s+")),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")),
        ("struct", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)")),
        ("enum", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)")),
        ("trait", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)")),
    ],
    "java": [
        ("class", re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?class\s+([A-Za-z_]\w*)")),
        ("interface", re.compile(r"^\s*(?:public|private|protected)?\s*interface\s+([A-Za-z_]\w*)")),
        ("enum", re.compile(r"^\s*(?:public|private|protected)?\s*enum\s+([A-Za-z_]\w*)")),
    ],
    "ruby": [
        ("class", re.compile(r"^\s*class\s+([A-Z]\w*)")),
        ("module", re.compile(r"^\s*module\s+([A-Z]\w*)")),
        ("function", re.compile(r"^\s*def\s+([a-z_]\w*[?!]?)")),
    ],
    "php": [
        ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)")),
        ("interface", re.compile(r"^\s*interface\s+([A-Za-z_]\w*)")),
        ("function", re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?function\s+([A-Za-z_]\w*)")),
    ],
    "csharp": [
        ("class", re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+|sealed\s+|abstract\s+|partial\s+)*class\s+([A-Za-z_]\w*)")),
        ("interface", re.compile(r"^\s*(?:public|private|protected|internal)?\s*interface\s+([A-Za-z_]\w*)")),
    ],
    "swift": [
        ("function", re.compile(r"^\s*(?:public|private|internal|fileprivate|open)?\s*(?:static\s+)?func\s+([A-Za-z_]\w*)")),
        ("class", re.compile(r"^\s*(?:public|private|internal|final)?\s*class\s+([A-Za-z_]\w*)")),
        ("struct", re.compile(r"^\s*(?:public|private|internal)?\s*struct\s+([A-Za-z_]\w*)")),
        ("protocol", re.compile(r"^\s*(?:public|private|internal)?\s*protocol\s+([A-Za-z_]\w*)")),
    ],
    "kotlin": [
        ("function", re.compile(r"^\s*(?:public|private|internal|protected)?\s*(?:suspend\s+)?fun\s+([A-Za-z_]\w*)")),
        ("class", re.compile(r"^\s*(?:public|private|internal|open|data|sealed|abstract)?\s*class\s+([A-Za-z_]\w*)")),
    ],
    "shell": [
        ("function", re.compile(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\s*\)\s*\{")),
    ],
}
# TypeScript adds type-level declarations on top of JavaScript's.
_PATTERNS["typescript"] = _PATTERNS["javascript"] + [
    ("interface", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)")),
    ("enum", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)")),
]
_PATTERNS["cpp"] = _PATTERNS["c"] = [
    ("class", re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)")),
]

# Import/require extraction, for the "who depends on this file" ranking signal.
_IMPORT_PATTERNS = {
    "javascript": [
        re.compile(r"""^\s*import\s+(?:[\w*\s{},$]+\s+from\s+)?['"]([^'"]+)['"]"""),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""^\s*export\s+(?:\*|{[^}]*})\s+from\s+['"]([^'"]+)['"]"""),
    ],
    "go": [re.compile(r"""^\s*(?:[\w.]+\s+)?"([^"]+)"\s*$""")],
    "rust": [re.compile(r"^\s*(?:pub\s+)?use\s+([\w:]+)")],
    "java": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)")],
    "ruby": [re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""")],
}
_IMPORT_PATTERNS["typescript"] = _IMPORT_PATTERNS["javascript"]


def regex_limitations() -> str:
    """The documented gaps in non-Python extraction, for surfacing in the UI."""
    return _REGEX_LIMITATIONS.strip()


def extract(path: str, content: str) -> Tuple[List[Symbol], List[str], str]:
    """Returns (symbols, imports, parse_mode) for one file's content.

    `parse_mode` is "ast" (exact), "regex" (approximate), or "none".
    """
    language = language_for_path(path)
    if language == "python":
        try:
            return _extract_python(content)
        except SyntaxError:
            # Being mid-edit or targeting a newer Python than ours is normal;
            # fall back rather than losing the file from the index entirely.
            symbols, imports = _extract_with_regex(content, "python_fallback")
            return symbols, imports, "regex"
    if language in _PATTERNS or language in _IMPORT_PATTERNS:
        symbols, imports = _extract_with_regex(content, language)
        return symbols, imports, "regex"
    return [], [], "none"


def _extract_python(content: str) -> Tuple[List[Symbol], List[str], str]:
    """Exact extraction via the stdlib parser."""
    tree = ast.parse(content)
    symbols: List[Symbol] = []
    imports: List[str] = []

    # Only walk the top level plus one class level: nested helper functions are
    # noise in an outline, but methods are the useful part of a class.
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_python_import_names(node))
        elif isinstance(node, ast.ClassDef):
            symbols.append(
                Symbol(
                    kind="class",
                    name=node.name,
                    line=node.lineno,
                    signature=f"class {node.name}",
                    doc=_first_doc_line(node),
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("_") and child.name != "__init__":
                        continue  # private helpers aren't outline material
                    symbols.append(
                        Symbol(
                            kind="method",
                            name=f"{node.name}.{child.name}",
                            line=child.lineno,
                            signature=_python_signature(child),
                            doc=_first_doc_line(child),
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                Symbol(
                    kind="function",
                    name=node.name,
                    line=node.lineno,
                    signature=_python_signature(node),
                    doc=_first_doc_line(node),
                )
            )
        elif isinstance(node, ast.Assign):
            # Module-level CONSTANTS are worth indexing; ordinary globals aren't.
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.append(
                        Symbol(kind="const", name=target.id, line=target.lineno)
                    )

    return symbols[:MAX_SYMBOLS_PER_FILE], _dedupe(imports), "ast"


def _python_import_names(node) -> List[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    # `from . import x` has module=None; record the relative form so it still
    # carries a usable signal.
    base = node.module or ""
    if node.level:
        base = "." * node.level + base
    return [base] if base else []


def _python_signature(node) -> str:
    """Renders a def line without evaluating annotations or defaults."""
    args = node.args
    parts: List[str] = []
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults_offset = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        text = arg.arg
        if index >= defaults_offset:
            text += "=..."
        parts.append(text)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(f"{arg.arg}=..." if default is not None else arg.arg)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)})"


def _first_doc_line(node) -> str:
    """The docstring's first line — enough to say what something is for."""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    first = doc.strip().splitlines()[0].strip()
    return first[:200]


def strip_comment_lines(content: str, language: str) -> List[str]:
    """Returns lines with comments removed, so commented-out code isn't matched.

    Shared with `depth.py`'s route detection, which has the same problem: a
    commented-out endpoint must not be reported as a live one.
    """
    if language in ("javascript", "typescript", "java", "csharp", "c", "cpp", "rust",
                    "go", "swift", "kotlin", "php", "scss", "dart"):
        content = _BLOCK_COMMENT_RE.sub("", content)
    marker = _LINE_COMMENT.get(language)
    lines = content.splitlines()
    if not marker:
        return lines
    cleaned = []
    for line in lines:
        index = line.find(marker)
        # Crude but adequate: a marker inside a string literal is rare in the
        # leading part of a declaration line, which is all we match against.
        cleaned.append(line[:index] if index != -1 else line)
    return cleaned


def _extract_with_regex(content: str, language: str) -> Tuple[List[Symbol], List[str]]:
    if language == "python_fallback":
        return _python_regex_fallback(content)

    lines = strip_comment_lines(content, language)
    symbols: List[Symbol] = []
    seen = set()
    for kind, pattern in _PATTERNS.get(language, []):
        for number, line in enumerate(lines, start=1):
            match = pattern.match(line)
            if not match:
                continue
            key = (kind, match.group(1))
            if key in seen:
                continue
            seen.add(key)
            symbols.append(
                Symbol(kind=kind, name=match.group(1), line=number, signature=line.strip()[:160])
            )
            if len(symbols) >= MAX_SYMBOLS_PER_FILE:
                break
    # Patterns are applied one kind at a time, so results arrive grouped by kind
    # rather than in file order; sort so the outline reads top to bottom.
    symbols.sort(key=lambda s: s.line)

    imports: List[str] = []
    for pattern in _IMPORT_PATTERNS.get(language, []):
        for line in lines:
            match = pattern.match(line) if pattern.pattern.startswith("^") else pattern.search(line)
            if match:
                imports.append(match.group(1))

    return symbols[:MAX_SYMBOLS_PER_FILE], _dedupe(imports)


def _python_regex_fallback(content: str) -> Tuple[List[Symbol], List[str]]:
    """Used only when a .py file doesn't parse (mid-edit, or newer syntax)."""
    symbols: List[Symbol] = []
    imports: List[str] = []
    class_re = re.compile(r"^class\s+([A-Za-z_]\w*)")
    def_re = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)")
    import_re = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
    for number, line in enumerate(content.splitlines(), start=1):
        if (match := class_re.match(line)) is not None:
            symbols.append(Symbol(kind="class", name=match.group(1), line=number))
        elif (match := def_re.match(line)) is not None:
            symbols.append(Symbol(kind="function", name=match.group(1), line=number))
        elif (match := import_re.match(line)) is not None:
            imports.append(match.group(1) or match.group(2))
    return symbols[:MAX_SYMBOLS_PER_FILE], _dedupe(imports)


def _dedupe(items: List[str]) -> List[str]:
    """Order-preserving dedupe, capped — a file importing 500 modules is noise."""
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
        if len(result) >= 100:
            break
    return result
