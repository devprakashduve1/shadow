"""Comprehensive codebase analysis before any changes."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
import json

logger = logging.getLogger(__name__)


class CodebaseAnalysis:
    """Result of comprehensive codebase analysis."""

    def __init__(self):
        self.total_files: int = 0
        self.total_lines: int = 0
        self.file_types: Dict[str, int] = {}
        self.detected_frameworks: List[str] = []
        self.detected_patterns: List[str] = []
        self.entry_points: List[str] = []
        self.main_modules: List[str] = []
        self.dependencies: Set[str] = set()
        self.existing_tests: List[str] = []
        self.config_files: List[str] = []
        self.potential_impact_files: List[str] = []
        self.warnings: List[str] = []

    def to_dict(self) -> Dict:
        """Convert to dictionary for display/storage."""
        return {
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "file_types": self.file_types,
            "detected_frameworks": self.detected_frameworks,
            "detected_patterns": self.detected_patterns,
            "entry_points": self.entry_points,
            "main_modules": self.main_modules,
            "dependencies": list(self.dependencies),
            "existing_tests": self.existing_tests,
            "config_files": self.config_files,
            "potential_impact_files": self.potential_impact_files,
            "warnings": self.warnings,
        }


class CodebaseAnalyzer:
    """Comprehensive analysis of entire codebase before changes."""

    def __init__(self, project_root: str):
        """Initialize analyzer."""
        self.project_root = Path(project_root)
        self.analysis: Optional[CodebaseAnalysis] = None

    def analyze_full_codebase(self) -> CodebaseAnalysis:
        """Perform comprehensive analysis of entire codebase."""
        logger.info(f"Analyzing codebase: {self.project_root}")

        analysis = CodebaseAnalysis()

        # 1. Scan all files
        self._scan_files(analysis)

        # 2. Detect frameworks and patterns
        self._detect_frameworks(analysis)

        # 3. Find entry points
        self._find_entry_points(analysis)

        # 4. Identify main modules
        self._identify_main_modules(analysis)

        # 5. Extract dependencies
        self._extract_dependencies(analysis)

        # 6. Find test files
        self._find_tests(analysis)

        # 7. Find config files
        self._find_config_files(analysis)

        # 8. Identify potential impact areas
        self._identify_impact_areas(analysis)

        # 9. Generate warnings
        self._generate_warnings(analysis)

        self.analysis = analysis
        return analysis

    def _scan_files(self, analysis: CodebaseAnalysis) -> None:
        """Scan all files in project."""
        logger.info("Scanning files...")

        ignored_dirs = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            "dist",
            "build",
            ".egg-info",
        }

        for path in self.project_root.rglob("*"):
            # Skip ignored directories
            if any(ignored in path.parts for ignored in ignored_dirs):
                continue

            if path.is_file():
                analysis.total_files += 1

                # Count file types
                suffix = path.suffix or "no_extension"
                analysis.file_types[suffix] = analysis.file_types.get(suffix, 0) + 1

                # Count lines
                try:
                    if path.suffix in {".py", ".js", ".ts", ".java", ".go", ".rb"}:
                        lines = len(path.read_text(errors="ignore").splitlines())
                        analysis.total_lines += lines
                except Exception as e:
                    logger.warning(f"Could not read {path}: {e}")

    def _detect_frameworks(self, analysis: CodebaseAnalysis) -> None:
        """Detect frameworks used in project."""
        logger.info("Detecting frameworks...")

        # Check requirements.txt for Python
        requirements = self.project_root / "requirements.txt"
        if requirements.exists():
            content = requirements.read_text(errors="ignore").lower()

            if "django" in content:
                analysis.detected_frameworks.append("Django")
            if "flask" in content:
                analysis.detected_frameworks.append("Flask")
            if "fastapi" in content:
                analysis.detected_frameworks.append("FastAPI")
            if "pytest" in content:
                analysis.detected_frameworks.append("pytest")
            if "pyqt" in content or "pyside" in content:
                analysis.detected_frameworks.append("PyQt/PySide")
            if "requests" in content:
                analysis.detected_patterns.append("HTTP Client Library")

        # Check package.json for Node
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text())
                deps = pkg.get("dependencies", {})
                dev_deps = pkg.get("devDependencies", {})

                if "react" in deps:
                    analysis.detected_frameworks.append("React")
                if "vue" in deps:
                    analysis.detected_frameworks.append("Vue")
                if "angular" in deps:
                    analysis.detected_frameworks.append("Angular")
                if "express" in deps:
                    analysis.detected_frameworks.append("Express")
                if "next" in deps:
                    analysis.detected_frameworks.append("Next.js")
                if "jest" in dev_deps or "mocha" in dev_deps:
                    analysis.detected_frameworks.append("Test Framework")
            except Exception as e:
                logger.warning(f"Could not parse package.json: {e}")

    def _find_entry_points(self, analysis: CodebaseAnalysis) -> None:
        """Find application entry points."""
        logger.info("Finding entry points...")

        # Python entry points
        if (self.project_root / "main.py").exists():
            analysis.entry_points.append("main.py")
        if (self.project_root / "app.py").exists():
            analysis.entry_points.append("app.py")
        if (self.project_root / "run.py").exists():
            analysis.entry_points.append("run.py")

        # JavaScript entry points
        if (self.project_root / "index.js").exists():
            analysis.entry_points.append("index.js")
        if (self.project_root / "server.js").exists():
            analysis.entry_points.append("server.js")

        # Check for setup.py
        if (self.project_root / "setup.py").exists():
            analysis.entry_points.append("setup.py (package)")

    def _identify_main_modules(self, analysis: CodebaseAnalysis) -> None:
        """Identify main application modules/directories."""
        logger.info("Identifying main modules...")

        ignored = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

        for path in self.project_root.iterdir():
            if path.is_dir() and path.name not in ignored:
                file_count = len(list(path.glob("**/*.py"))) + len(
                    list(path.glob("**/*.js"))
                )
                if file_count > 0:
                    analysis.main_modules.append(f"{path.name}/ ({file_count} files)")

    def _extract_dependencies(self, analysis: CodebaseAnalysis) -> None:
        """Extract project dependencies."""
        logger.info("Extracting dependencies...")

        # Python dependencies
        requirements = self.project_root / "requirements.txt"
        if requirements.exists():
            for line in requirements.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg = line.split("==")[0].split(">=")[0].split("<")[0].strip()
                    if pkg:
                        analysis.dependencies.add(pkg)

        # JavaScript dependencies
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text())
                for dep in pkg.get("dependencies", {}).keys():
                    analysis.dependencies.add(dep)
            except Exception as e:
                logger.warning(f"Could not parse package.json: {e}")

    def _find_tests(self, analysis: CodebaseAnalysis) -> None:
        """Find existing test files."""
        logger.info("Finding tests...")

        for test_file in self.project_root.rglob("test_*.py"):
            rel_path = test_file.relative_to(self.project_root)
            analysis.existing_tests.append(str(rel_path))

        for test_file in self.project_root.rglob("*_test.py"):
            rel_path = test_file.relative_to(self.project_root)
            if str(rel_path) not in analysis.existing_tests:
                analysis.existing_tests.append(str(rel_path))

        for test_dir in self.project_root.glob("**/tests/"):
            if test_dir.is_dir():
                for test_file in test_dir.glob("*.py"):
                    rel_path = test_file.relative_to(self.project_root)
                    if str(rel_path) not in analysis.existing_tests:
                        analysis.existing_tests.append(str(rel_path))

    def _find_config_files(self, analysis: CodebaseAnalysis) -> None:
        """Find configuration files."""
        logger.info("Finding config files...")

        config_patterns = {
            "*.yaml",
            "*.yml",
            "*.json",
            ".env*",
            "*.toml",
            "*.ini",
            "*.cfg",
            "*.conf",
        }

        for pattern in config_patterns:
            for config_file in self.project_root.glob(pattern):
                if config_file.is_file():
                    rel_path = config_file.relative_to(self.project_root)
                    analysis.config_files.append(str(rel_path))

    def _identify_impact_areas(self, analysis: CodebaseAnalysis) -> None:
        """Identify files likely to be impacted by changes."""
        logger.info("Identifying potential impact areas...")

        impact_keywords = {
            "model": "Models",
            "controller": "Controllers",
            "service": "Services",
            "handler": "Event Handlers",
            "middleware": "Middleware",
            "validator": "Validators",
            "auth": "Authentication",
            "config": "Configuration",
        }

        found = set()

        for py_file in self.project_root.rglob("*.py"):
            # Skip certain directories
            if any(x in py_file.parts for x in ["__pycache__", ".venv", "venv"]):
                continue

            file_name = py_file.name.lower()
            for keyword, category in impact_keywords.items():
                if keyword in file_name:
                    rel_path = py_file.relative_to(self.project_root)
                    impact_str = f"{rel_path} ({category})"
                    if impact_str not in found:
                        analysis.potential_impact_files.append(impact_str)
                        found.add(impact_str)

    def _generate_warnings(self, analysis: CodebaseAnalysis) -> None:
        """Generate warnings about potential risks."""
        logger.info("Generating warnings...")

        # Check for missing tests
        if not analysis.existing_tests:
            analysis.warnings.append(
                "⚠️ No test files found - changes should be tested carefully"
            )

        # Check for multiple frameworks (potential complexity)
        if len(analysis.detected_frameworks) > 3:
            analysis.warnings.append(
                f"⚠️ Multiple frameworks detected ({len(analysis.detected_frameworks)}) - changes may have wide impact"
            )

        # Check for many files
        if analysis.total_files > 1000:
            analysis.warnings.append(
                f"⚠️ Large codebase ({analysis.total_files} files) - verify all changes thoroughly"
            )

        # Check for many lines of code
        if analysis.total_lines > 100000:
            analysis.warnings.append(
                f"⚠️ Large codebase ({analysis.total_lines} lines) - potential for widespread impact"
            )

    def format_for_display(self) -> str:
        """Format analysis for user display."""
        if not self.analysis:
            return "No analysis available"

        output = []

        output.append("\n" + "=" * 70)
        output.append("CODEBASE ANALYSIS REPORT")
        output.append("=" * 70 + "\n")

        # Summary
        output.append("📊 **SUMMARY**")
        output.append(f"  Total Files: {self.analysis.total_files}")
        output.append(f"  Total Lines of Code: {self.analysis.total_lines:,}")
        output.append("")

        # File types
        if self.analysis.file_types:
            output.append("📁 **FILE TYPES**")
            for ftype, count in sorted(
                self.analysis.file_types.items(), key=lambda x: x[1], reverse=True
            )[:5]:
                output.append(f"  {ftype}: {count} files")
            output.append("")

        # Frameworks
        if self.analysis.detected_frameworks:
            output.append("🛠️  **DETECTED FRAMEWORKS**")
            for framework in self.analysis.detected_frameworks:
                output.append(f"  • {framework}")
            output.append("")

        # Entry points
        if self.analysis.entry_points:
            output.append("🚀 **ENTRY POINTS**")
            for entry in self.analysis.entry_points:
                output.append(f"  • {entry}")
            output.append("")

        # Main modules
        if self.analysis.main_modules:
            output.append("📦 **MAIN MODULES**")
            for module in self.analysis.main_modules[:5]:
                output.append(f"  • {module}")
            if len(self.analysis.main_modules) > 5:
                output.append(f"  ... and {len(self.analysis.main_modules) - 5} more")
            output.append("")

        # Dependencies
        if self.analysis.dependencies:
            output.append(f"📚 **DEPENDENCIES** ({len(self.analysis.dependencies)})")
            for dep in sorted(list(self.analysis.dependencies))[:10]:
                output.append(f"  • {dep}")
            if len(self.analysis.dependencies) > 10:
                output.append(
                    f"  ... and {len(self.analysis.dependencies) - 10} more"
                )
            output.append("")

        # Tests
        if self.analysis.existing_tests:
            output.append(f"✅ **TEST FILES** ({len(self.analysis.existing_tests)})")
            for test in self.analysis.existing_tests[:5]:
                output.append(f"  • {test}")
            if len(self.analysis.existing_tests) > 5:
                output.append(
                    f"  ... and {len(self.analysis.existing_tests) - 5} more"
                )
            output.append("")

        # Config files
        if self.analysis.config_files:
            output.append(f"⚙️  **CONFIG FILES** ({len(self.analysis.config_files)})")
            for cfg in self.analysis.config_files[:5]:
                output.append(f"  • {cfg}")
            if len(self.analysis.config_files) > 5:
                output.append(f"  ... and {len(self.analysis.config_files) - 5} more")
            output.append("")

        # Impact areas
        if self.analysis.potential_impact_files:
            output.append("🎯 **POTENTIAL IMPACT AREAS**")
            for impact in self.analysis.potential_impact_files[:8]:
                output.append(f"  • {impact}")
            if len(self.analysis.potential_impact_files) > 8:
                output.append(
                    f"  ... and {len(self.analysis.potential_impact_files) - 8} more"
                )
            output.append("")

        # Warnings
        if self.analysis.warnings:
            output.append("⚠️  **WARNINGS**")
            for warning in self.analysis.warnings:
                output.append(f"  {warning}")
            output.append("")

        output.append("=" * 70)
        output.append("\n**BEFORE PROCEEDING WITH CHANGES:**")
        output.append("1. Review the analysis above")
        output.append("2. Verify frameworks and dependencies")
        output.append("3. Check potential impact areas")
        output.append("4. Address any warnings")
        output.append("\nDo you want to proceed? (yes/no/review)")
        output.append("=" * 70 + "\n")

        return "\n".join(output)
