"""Multi-algorithm file and symbol retrieval for context gathering."""

import ast
import logging
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schemas import (
    BundledFile,
    IntentAnalysis,
    RetrievalResult,
    SymbolLocation,
)

logger = logging.getLogger(__name__)


class ContextRetriever:
    """Retrieve relevant files and symbols from project."""

    def __init__(self, project_root: str, max_file_size: int = 50000):
        self.project_root = Path(project_root)
        self.max_file_size = max_file_size
        self._symbol_index: Optional[Dict[str, SymbolLocation]] = None
        self._file_tree: Optional[List[Path]] = None

    def _build_symbol_index(self) -> Dict[str, SymbolLocation]:
        """Index all symbols in Python files."""
        symbols = {}

        for py_file in self.project_root.rglob("*.py"):
            if any(part.startswith(".") for part in py_file.parts):
                continue  # Skip hidden dirs

            try:
                content = py_file.read_text(errors="ignore")
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols[node.name] = SymbolLocation(
                            file=str(py_file.relative_to(self.project_root)),
                            line=node.lineno,
                            type="function",
                            name=node.name,
                        )
                    elif isinstance(node, ast.ClassDef):
                        symbols[node.name] = SymbolLocation(
                            file=str(py_file.relative_to(self.project_root)),
                            line=node.lineno,
                            type="class",
                            name=node.name,
                        )
            except (SyntaxError, UnicodeDecodeError):
                pass

        return symbols

    def _get_file_tree(self) -> List[Path]:
        """Get all relevant project files."""
        if self._file_tree is None:
            self._file_tree = list(
                self.project_root.rglob("*")
            )
        return self._file_tree

    def retrieve(self, intent: IntentAnalysis, max_files: int = 8) -> RetrievalResult:
        """Retrieve context using multi-algorithm approach."""
        candidates: Dict[str, float] = {}

        # Algorithm 1: Filename search
        for keyword in intent.keywords:
            matches = self._filename_search(keyword)
            for file_path, score in matches:
                file_str = str(file_path)
                candidates[file_str] = candidates.get(file_str, 0) + score * 1.0

        # Algorithm 2: Symbol search
        if self._symbol_index is None:
            self._symbol_index = self._build_symbol_index()

        for symbol in intent.likely_symbols:
            if symbol in self._symbol_index:
                loc = self._symbol_index[symbol]
                candidates[loc.file] = candidates.get(loc.file, 0) + 50

        # Algorithm 3: Ripgrep search (if available)
        for keyword in intent.keywords:
            matches = self._ripgrep_search(keyword)
            for file_path, score in matches:
                file_str = str(file_path)
                candidates[file_str] = candidates.get(file_str, 0) + score * 1.0

        # Algorithm 4: Embedding search (if confidence low)
        if intent.confidence < 0.8 and len(candidates) < 3:
            matches = self._semantic_search(intent.summary)
            for file_str, score in matches:
                candidates[file_str] = candidates.get(file_str, 0) + score * 20

        # Rank and select
        ranked = sorted(
            candidates.items(), key=lambda x: x[1], reverse=True
        )

        selected_files = [file_str for file_str, _ in ranked[:max_files]]
        bundled = self._bundle_files(selected_files)
        symbols = self._extract_symbols(bundled)

        return RetrievalResult(
            files=bundled,
            symbols=symbols,
            dependencies=self._build_dependencies(bundled),
        )

    def _filename_search(self, keyword: str) -> List[Tuple[Path, float]]:
        """Search for keyword in file names."""
        results = []
        keyword_lower = keyword.lower()

        for file_path in self._get_file_tree():
            if file_path.is_dir() or any(
                part.startswith(".") for part in file_path.parts
            ):
                continue

            name = file_path.name.lower()
            score = 0.0

            if name == keyword_lower:
                score = 100.0
            elif keyword_lower in name:
                score = 50.0
            elif (
                ratio := SequenceMatcher(None, keyword_lower, name).ratio()
            ) > 0.7:
                score = 30.0 * ratio
            elif name.startswith(keyword_lower):
                score = 20.0

            if score > 0:
                results.append((file_path, score))

        return sorted(results, key=lambda x: x[1], reverse=True)[:5]

    def _ripgrep_search(self, keyword: str) -> List[Tuple[str, float]]:
        """Use ripgrep for fast pattern matching."""
        results = []

        try:
            # Escape special regex characters
            pattern = re.escape(keyword)
            output = subprocess.run(
                [
                    "rg",
                    "--files-with-matches",
                    "--no-messages",
                    pattern,
                    str(self.project_root),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if output.returncode == 0:
                for line in output.stdout.strip().split("\n"):
                    if line:
                        rel_path = str(
                            Path(line).relative_to(self.project_root)
                        )
                        results.append((rel_path, 30.0))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return results[:5]

    def _semantic_search(self, query: str) -> List[Tuple[str, float]]:
        """Fallback semantic search using simple heuristics."""
        # TODO: Implement with embeddings model when available
        # For now, return empty to avoid blocking
        return []

    def _bundle_files(self, file_paths: List[str]) -> List[BundledFile]:
        """Read files and bundle with metadata."""
        bundled = []

        for rel_path in file_paths:
            file_path = self.project_root / rel_path
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(errors="ignore")

                # Truncate if too large
                if len(content) > self.max_file_size:
                    content = self._extract_essential(content, file_path)

                language = file_path.suffix.lstrip(".")

                bundled.append(
                    BundledFile(
                        file_path=rel_path,
                        content=content,
                        language=language,
                        size_bytes=len(content),
                        symbols=self._extract_file_symbols(file_path),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to bundle {rel_path}: {e}")

        return bundled

    def _extract_essential(self, content: str, file_path: Path) -> str:
        """Extract essential parts: imports, function/class defs."""
        if file_path.suffix != ".py":
            return content[:self.max_file_size]

        try:
            tree = ast.parse(content)
            essential = []

            # Keep imports
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    essential.append(ast.unparse(node))

            # Keep function and class definitions
            for node in tree.body:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    essential.append(ast.unparse(node))

            result = "\n".join(essential)
            return result[: self.max_file_size]
        except:
            return content[: self.max_file_size]

    def _extract_file_symbols(self, file_path: Path) -> Dict[str, SymbolLocation]:
        """Extract symbols from a single file."""
        symbols = {}

        if file_path.suffix != ".py":
            return symbols

        try:
            content = file_path.read_text(errors="ignore")
            tree = ast.parse(content)
            rel_path = str(file_path.relative_to(self.project_root))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols[node.name] = SymbolLocation(
                        file=rel_path,
                        line=node.lineno,
                        type="function",
                        name=node.name,
                    )
                elif isinstance(node, ast.ClassDef):
                    symbols[node.name] = SymbolLocation(
                        file=rel_path,
                        line=node.lineno,
                        type="class",
                        name=node.name,
                    )
        except:
            pass

        return symbols

    def _extract_symbols(self, bundled_files: List[BundledFile]) -> Dict[str, SymbolLocation]:
        """Merge symbols from all bundled files."""
        all_symbols = {}
        for bf in bundled_files:
            all_symbols.update(bf.symbols)
        return all_symbols

    def _build_dependencies(
        self, bundled_files: List[BundledFile]
    ) -> Dict[str, List[str]]:
        """Build dependency graph from imports."""
        deps = {}

        for bf in bundled_files:
            imports = self._extract_imports(bf.content, bf.language)
            deps[bf.file_path] = imports

        return deps

    def _extract_imports(self, content: str, language: str) -> List[str]:
        """Extract import statements."""
        imports = []

        if language == "py":
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.append(node.module)
            except:
                pass
        elif language in ("js", "ts", "jsx", "tsx"):
            # Simple regex for JavaScript imports
            patterns = [
                r'import\s+(?:{[^}]*}|[\w*]+)\s+from\s+["\']([^"\']+)["\']',
                r'require\(["\']([^"\']+)["\']\)',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    imports.append(match.group(1))

        return list(set(imports))
