"""Parses dependency manifests so the AI knows what a project is built with.

Knowing a repo uses React 18 + Vite, or FastAPI + SQLAlchemy, changes what good
advice looks like — far more cheaply than inferring it from source.

Python 3.9 has no `tomllib`, and adding a `toml` dependency for two files isn't
proportionate, so TOML is read with targeted regex over the sections we actually
want. That's a real limitation: it handles the common flat `name = "version"`
form and ignores nested tables, inline arrays-of-tables, and multi-line values.
Mis-parsing a manifest degrades context quality; it can't corrupt anything.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Dict, List, Optional

from .schema import Manifest

# Filenames worth looking for, mapped to their ecosystem.
MANIFEST_KINDS = {
    "package.json": "npm",
    "requirements.txt": "pip",
    "requirements-dev.txt": "pip",
    "pyproject.toml": "python",
    "setup.py": "python",
    "go.mod": "go",
    "Cargo.toml": "cargo",
    "pom.xml": "maven",
    "Gemfile": "ruby",
    "composer.json": "php",
}

# Only look this deep — a monorepo has a package.json per workspace, but a
# node_modules-style deep scan would find thousands.
MAX_MANIFEST_DEPTH = 3

# requirements.txt: split "package[extra]>=1.0 ; python_version<'3.10'" into
# name and specifier.
_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*([<>=!~]=?[^;#\s]*)?")
_PIP_SKIP_PREFIXES = ("-r", "-e", "--", "#", "git+", "http")


def find_manifests(root: Path, max_depth: int = MAX_MANIFEST_DEPTH) -> List[Path]:
    """Finds manifest files up to `max_depth` levels below `root`."""
    from ..project_files import DEFAULT_IGNORED_DIRS

    found: List[Path] = []
    root = Path(root)
    for name in MANIFEST_KINDS:
        candidate = root / name
        if candidate.is_file():
            found.append(candidate)
    # Nested manifests (monorepo workspaces), skipping ignored trees.
    for depth in range(1, max_depth + 1):
        pattern = "/".join(["*"] * depth)
        for name in MANIFEST_KINDS:
            for candidate in root.glob(f"{pattern}/{name}"):
                if any(part in DEFAULT_IGNORED_DIRS for part in candidate.relative_to(root).parts):
                    continue
                if candidate.is_file():
                    found.append(candidate)
    return found


def parse_manifest(root: Path, path: Path) -> Optional[Manifest]:
    """Parses one manifest, returning None if it's unreadable or unrecognized."""
    root = Path(root)
    try:
        rel_path = str(path.relative_to(root))
    except ValueError:
        return None
    kind = MANIFEST_KINDS.get(path.name)
    if kind is None:
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    parsers = {
        "package.json": _parse_package_json,
        "composer.json": _parse_package_json,
        "requirements.txt": _parse_requirements,
        "requirements-dev.txt": _parse_requirements,
        "pyproject.toml": _parse_pyproject,
        "go.mod": _parse_go_mod,
        "Cargo.toml": _parse_cargo,
        "pom.xml": _parse_pom,
        "Gemfile": _parse_gemfile,
        "setup.py": _parse_setup_py,
    }
    parser = parsers.get(path.name)
    if parser is None:
        return None
    try:
        manifest = parser(text)
    except Exception:
        # A malformed manifest shouldn't fail the whole index.
        return None
    if manifest is None:
        return None
    manifest.path = rel_path
    manifest.kind = kind
    return manifest


def collect_manifests(root: Path) -> List[Manifest]:
    """Finds and parses every manifest under `root`."""
    results = []
    for path in find_manifests(root):
        manifest = parse_manifest(root, path)
        if manifest is not None:
            results.append(manifest)
    return results


# -- per-format parsers -----------------------------------------------------


def _parse_package_json(text: str) -> Optional[Manifest]:
    data = json.loads(text)
    if not isinstance(data, dict):
        return None
    return Manifest(
        path="",
        kind="npm",
        name=str(data.get("name", "")),
        version=str(data.get("version", "")),
        dependencies={k: str(v) for k, v in (data.get("dependencies") or {}).items()},
        dev_dependencies={k: str(v) for k, v in (data.get("devDependencies") or {}).items()},
        scripts={k: str(v) for k, v in (data.get("scripts") or {}).items()},
    )


def _parse_requirements(text: str) -> Manifest:
    dependencies: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_PIP_SKIP_PREFIXES):
            continue
        match = _REQUIREMENT_RE.match(stripped)
        if match:
            dependencies[match.group(1)] = (match.group(2) or "").strip()
    return Manifest(path="", kind="pip", dependencies=dependencies)


def _toml_section(text: str, header: str) -> List[str]:
    """Returns the lines of one `[header]` section.

    The regex-TOML compromise described in the module docstring: finds the
    header, then takes lines until the next `[`-prefixed header.
    """
    lines = text.splitlines()
    collected: List[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if inside:
                break
            inside = stripped.replace(" ", "") == f"[{header}]".replace(" ", "")
            continue
        if inside:
            collected.append(stripped)
    return collected


_TOML_PAIR_RE = re.compile(r"""^([A-Za-z0-9._-]+)\s*=\s*["']?([^"'#]*)["']?""")


def _toml_pairs(lines: List[str]) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        match = _TOML_PAIR_RE.match(line)
        if match:
            pairs[match.group(1)] = match.group(2).strip()
    return pairs


_TOML_ARRAY_ITEM_RE = re.compile(r"""["']([A-Za-z0-9._-]+)\s*([^"']*)["']""")


def _parse_pyproject(text: str) -> Manifest:
    project = _toml_pairs(_toml_section(text, "project"))
    manifest = Manifest(
        path="",
        kind="python",
        name=project.get("name", ""),
        version=project.get("version", ""),
    )

    # PEP 621 style: dependencies = ["requests>=2", ...] — an array that may span
    # lines, so scan the whole file for the block rather than one section.
    array_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if array_match:
        for item in _TOML_ARRAY_ITEM_RE.finditer(array_match.group(1)):
            manifest.dependencies[item.group(1)] = item.group(2).strip()

    # Poetry style: a [tool.poetry.dependencies] table of name = "version".
    for name, spec in _toml_pairs(_toml_section(text, "tool.poetry.dependencies")).items():
        manifest.dependencies[name] = spec
    for name, spec in _toml_pairs(_toml_section(text, "tool.poetry.dev-dependencies")).items():
        manifest.dev_dependencies[name] = spec
    poetry = _toml_pairs(_toml_section(text, "tool.poetry"))
    manifest.name = manifest.name or poetry.get("name", "")
    manifest.version = manifest.version or poetry.get("version", "")
    return manifest


def _parse_cargo(text: str) -> Manifest:
    package = _toml_pairs(_toml_section(text, "package"))
    return Manifest(
        path="",
        kind="cargo",
        name=package.get("name", ""),
        version=package.get("version", ""),
        dependencies=_toml_pairs(_toml_section(text, "dependencies")),
        dev_dependencies=_toml_pairs(_toml_section(text, "dev-dependencies")),
    )


_GO_MODULE_RE = re.compile(r"^module\s+(\S+)")
_GO_REQUIRE_LINE_RE = re.compile(r"^\s*(\S+)\s+(v\S+)")


def _parse_go_mod(text: str) -> Manifest:
    manifest = Manifest(path="", kind="go")
    inside_require = False
    for line in text.splitlines():
        stripped = line.strip()
        if (match := _GO_MODULE_RE.match(stripped)) is not None:
            manifest.name = match.group(1)
            continue
        if stripped.startswith("require ("):
            inside_require = True
            continue
        if inside_require:
            if stripped == ")":
                inside_require = False
                continue
            if (match := _GO_REQUIRE_LINE_RE.match(stripped)) is not None:
                manifest.dependencies[match.group(1)] = match.group(2)
        elif stripped.startswith("require "):
            # Single-line form: `require example.com/x v1.2.3`
            if (match := _GO_REQUIRE_LINE_RE.match(stripped[len("require "):])) is not None:
                manifest.dependencies[match.group(1)] = match.group(2)
    return manifest


def _parse_pom(text: str) -> Optional[Manifest]:
    """Parses Maven XML with the stdlib parser.

    Namespaces make tag names look like `{http://maven.apache.org/POM/4.0.0}artifactId`,
    so tags are compared on their local name.
    """
    root = ElementTree.fromstring(text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def child_text(element, name: str) -> str:
        for child in element:
            if local(child.tag) == name:
                return (child.text or "").strip()
        return ""

    manifest = Manifest(
        path="",
        kind="maven",
        name=child_text(root, "artifactId"),
        version=child_text(root, "version"),
    )
    for element in root.iter():
        if local(element.tag) != "dependency":
            continue
        group = child_text(element, "groupId")
        artifact = child_text(element, "artifactId")
        version = child_text(element, "version")
        scope = child_text(element, "scope")
        if not artifact:
            continue
        key = f"{group}:{artifact}" if group else artifact
        if scope == "test":
            manifest.dev_dependencies[key] = version
        else:
            manifest.dependencies[key] = version
    return manifest


_GEM_RE = re.compile(r"""^\s*gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""")


def _parse_gemfile(text: str) -> Manifest:
    manifest = Manifest(path="", kind="ruby")
    for line in text.splitlines():
        if (match := _GEM_RE.match(line)) is not None:
            manifest.dependencies[match.group(1)] = match.group(2) or ""
    return manifest


_SETUP_NAME_RE = re.compile(r"""name\s*=\s*['"]([^'"]+)['"]""")
_SETUP_VERSION_RE = re.compile(r"""version\s*=\s*['"]([^'"]+)['"]""")


def _parse_setup_py(text: str) -> Manifest:
    """Reads only name/version, by regex.

    A setup.py is executable code; running it to learn its metadata would mean
    executing arbitrary code from whatever repository the user opened. Not worth
    it for two strings.
    """
    manifest = Manifest(path="", kind="python")
    if (match := _SETUP_NAME_RE.search(text)) is not None:
        manifest.name = match.group(1)
    if (match := _SETUP_VERSION_RE.search(text)) is not None:
        manifest.version = match.group(1)
    install_requires = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if install_requires:
        for item in _TOML_ARRAY_ITEM_RE.finditer(install_requires.group(1)):
            manifest.dependencies[item.group(1)] = item.group(2).strip()
    return manifest


def summarize_dependencies(manifests: List[Manifest], limit: int = 40) -> str:
    """Renders manifests as a short block for prompt context."""
    if not manifests:
        return ""
    lines: List[str] = []
    for manifest in manifests:
        label = manifest.name or manifest.path
        header = f"{manifest.path} ({manifest.kind}"
        if manifest.name:
            header += f": {label}"
            if manifest.version:
                header += f" {manifest.version}"
        header += ")"
        lines.append(header)
        names = list(manifest.dependencies)[:limit]
        if names:
            lines.append("  deps: " + ", ".join(names))
        if manifest.scripts:
            lines.append("  scripts: " + ", ".join(list(manifest.scripts)[:12]))
    return "\n".join(lines)
