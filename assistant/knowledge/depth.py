"""Structural depth for the repo bank: module graph, APIs, frameworks, history.

The file index (`indexer.py`) says *what exists*. This module derives what the
pieces mean to each other, which is what the AI actually needs for anything
beyond a single-file edit:

- **module graph** — who imports whom, so "what breaks if I change this?" has an
  answer rather than a guess
- **API surface** — HTTP routes and CLI entry points, i.e. the ways the outside
  world reaches this code
- **integrations** — the external systems it talks to (databases, queues, HTTP
  clients, cloud SDKs) and the environment variables it reads
- **frameworks** — inferred from declared dependencies
- **history** — which files change most and most recently, from git

Everything here is derived from data already in the index or from git, so it's
deterministic and needs no model. That matters: an LLM guess about "what depends
on this module" is worse than useless for impact analysis.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .. import git_ops
from .schema import SCHEMA_VERSION, FileEntry, Manifest
from .symbols import strip_comment_lines

DEPTH_FILE = "depth.json"

# A module imported by this many files is a hub: changing it has wide reach, and
# that's worth stating explicitly in context.
HUB_THRESHOLD = 4

MAX_GRAPH_EDGES = 4000
MAX_ROUTES = 200
MAX_HOT_FILES = 30

# Framework/library detection from declared dependency names. Deliberately
# dependency-based rather than code-based: a package.json listing `next` is
# conclusive, whereas grepping for `import next` is not.
_FRAMEWORK_BY_DEPENDENCY = {
    # JS/TS
    "react": "React", "next": "Next.js", "vue": "Vue", "nuxt": "Nuxt",
    "@angular/core": "Angular", "svelte": "Svelte", "solid-js": "SolidJS",
    "express": "Express", "koa": "Koa", "fastify": "Fastify", "@nestjs/core": "NestJS",
    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha", "playwright": "Playwright",
    "@playwright/test": "Playwright", "cypress": "Cypress",
    "webpack": "Webpack", "vite": "Vite", "rollup": "Rollup", "esbuild": "esbuild",
    "typescript": "TypeScript", "tailwindcss": "Tailwind CSS",
    "redux": "Redux", "@reduxjs/toolkit": "Redux Toolkit", "zustand": "Zustand",
    "@tanstack/react-query": "React Query", "axios": "Axios",
    "prisma": "Prisma", "typeorm": "TypeORM", "sequelize": "Sequelize", "mongoose": "Mongoose",
    # Python
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "starlette": "Starlette",
    "tornado": "Tornado", "aiohttp": "aiohttp", "sanic": "Sanic",
    "sqlalchemy": "SQLAlchemy", "alembic": "Alembic", "pydantic": "Pydantic",
    "celery": "Celery", "pytest": "pytest", "unittest2": "unittest",
    "requests": "requests", "httpx": "httpx", "numpy": "NumPy", "pandas": "pandas",
    "torch": "PyTorch", "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn",
    "pyqt6": "PyQt6", "pyside6": "PySide6", "click": "Click", "typer": "Typer",
    # Other ecosystems
    "github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo",
    "github.com/gorilla/mux": "gorilla/mux",
    "actix-web": "Actix Web", "axum": "Axum", "rocket": "Rocket", "tokio": "Tokio",
    "serde": "Serde", "org.springframework.boot:spring-boot": "Spring Boot",
    "rails": "Rails", "sinatra": "Sinatra", "laravel/framework": "Laravel",
}

# Integration detection from imports. Grouped by the kind of system, so context
# can say "talks to Postgres and Redis" rather than listing package names.
_INTEGRATION_BY_IMPORT = {
    "psycopg2": "PostgreSQL", "psycopg": "PostgreSQL", "asyncpg": "PostgreSQL",
    "pg": "PostgreSQL", "mysql": "MySQL", "mysql2": "MySQL", "pymysql": "MySQL",
    "sqlite3": "SQLite", "better-sqlite3": "SQLite",
    "redis": "Redis", "ioredis": "Redis",
    "pymongo": "MongoDB", "mongodb": "MongoDB", "mongoose": "MongoDB",
    "elasticsearch": "Elasticsearch", "opensearchpy": "OpenSearch",
    "kafka": "Kafka", "confluent_kafka": "Kafka", "kafkajs": "Kafka",
    "pika": "RabbitMQ", "amqplib": "RabbitMQ", "celery": "Celery",
    "boto3": "AWS", "aws-sdk": "AWS", "@aws-sdk/client-s3": "AWS S3",
    "google.cloud": "Google Cloud", "azure": "Azure",
    "stripe": "Stripe", "twilio": "Twilio", "sendgrid": "SendGrid",
    "requests": "outbound HTTP", "httpx": "outbound HTTP", "urllib3": "outbound HTTP",
    "axios": "outbound HTTP", "node-fetch": "outbound HTTP", "got": "outbound HTTP",
    "graphql": "GraphQL", "apollo-server": "GraphQL", "strawberry": "GraphQL",
    "grpc": "gRPC", "@grpc/grpc-js": "gRPC",
    "openai": "OpenAI API", "anthropic": "Anthropic API", "ollama": "Ollama",
}

# HTTP route declarations, per ecosystem. Each pattern must capture (method?, path)
# or (path) — see `_extract_routes` for how each is read.
_ROUTE_PATTERNS: Tuple[Tuple[str, "re.Pattern"], ...] = (
    # FastAPI / Flask / Starlette route decorators.
    ("python-decorator", re.compile(
        r"""@\w+\.(get|post|put|patch|delete|head|options|route)\s*\(\s*['"]([^'"]+)['"]"""
    )),
    # Django urls.py path()/re_path()/url() entries.
    ("django", re.compile(r"""\b(?:path|re_path|url)\s*\(\s*r?['"]([^'"]*)['"]""")),
    # Express / Koa / Fastify handler registration on app/router/server/api.
    ("express", re.compile(
        r"""\b(?:app|router|server|api)\.(get|post|put|patch|delete|all|use)\s*\(\s*['"`]([^'"`]+)['"`]"""
    )),
    # Spring @GetMapping / @RequestMapping annotations.
    ("spring", re.compile(
        r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?['"]([^'"]+)['"]"""
    )),
    # Go net/http and gin-style handler registration.
    ("go", re.compile(r"""\.(?:HandleFunc|GET|POST|PUT|PATCH|DELETE)\s*\(\s*['"]([^'"]+)['"]""")),
)

_ENV_PATTERNS = (
    re.compile(r"""os\.environ(?:\.get)?\s*[\(\[]\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""os\.getenv\s*\(\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""process\.env\.([A-Z][A-Z0-9_]{2,})"""),
    re.compile(r"""process\.env\[\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""getenv\s*\(\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
)


@dataclass
class Route:
    """One externally reachable HTTP endpoint."""

    method: str
    path: str
    file: str
    line: int = 0
    flavour: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Route":
        return cls(
            method=str(data.get("method", "")),
            path=str(data.get("path", "")),
            file=str(data.get("file", "")),
            line=int(data.get("line", 0)),
            flavour=str(data.get("flavour", "")),
        )

    @property
    def label(self) -> str:
        return f"{self.method or 'ANY':6} {self.path}  ({self.file}:{self.line})"


@dataclass
class RepoDepth:
    """The derived structural picture of a repository."""

    version: int = SCHEMA_VERSION
    # path -> the in-repo modules it imports
    imports: Dict[str, List[str]] = field(default_factory=dict)
    # path -> the in-repo modules that import it (the reverse edge)
    imported_by: Dict[str, List[str]] = field(default_factory=dict)
    hub_modules: List[str] = field(default_factory=list)
    orphan_modules: List[str] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    integrations: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)
    # From git: recently and frequently changed files.
    hot_files: List[Dict[str, object]] = field(default_factory=list)
    recent_commits: List[Dict[str, str]] = field(default_factory=list)
    test_files: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["routes"] = [route.to_dict() for route in self.routes]
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, object]]) -> "RepoDepth":
        if not data or data.get("version") != SCHEMA_VERSION:
            return cls()
        depth = cls(
            version=int(data.get("version", SCHEMA_VERSION)),
            imports={k: list(v) for k, v in (data.get("imports") or {}).items()},
            imported_by={k: list(v) for k, v in (data.get("imported_by") or {}).items()},
            hub_modules=list(data.get("hub_modules", [])),
            orphan_modules=list(data.get("orphan_modules", [])),
            frameworks=list(data.get("frameworks", [])),
            integrations=list(data.get("integrations", [])),
            env_vars=list(data.get("env_vars", [])),
            hot_files=list(data.get("hot_files", [])),
            recent_commits=list(data.get("recent_commits", [])),
            test_files=list(data.get("test_files", [])),
            config_files=list(data.get("config_files", [])),
        )
        depth.routes = [Route.from_dict(r) for r in (data.get("routes") or [])]
        return depth

    def dependents_of(self, rel_path: str) -> List[str]:
        """Files that import `rel_path` — the blast radius of changing it."""
        return list(self.imported_by.get(rel_path, []))

    def dependencies_of(self, rel_path: str) -> List[str]:
        return list(self.imports.get(rel_path, []))


# -- module graph -----------------------------------------------------------


def _module_keys(rel_path: str) -> List[str]:
    """The names an import statement might plausibly use for this file.

    Import strings are wildly ecosystem-specific ("./helper", "..pkg.mod",
    "app.services.billing", "@/lib/api"), so rather than resolving them properly
    this generates the candidate keys a file could be referred to by and matches
    on those. Approximate — but wrong-in-both-directions approximate, not
    silently-missing approximate, and every edge is between two files that really
    exist.
    """
    posix = PurePosixPath(rel_path)
    parts = list(posix.parts)
    keys: List[str] = []

    if parts:
        if posix.suffix:
            parts[-1] = posix.stem
        # A package marker names the directory, not itself.
        if parts[-1] in ("__init__", "index", "mod"):
            parts = parts[:-1]
    if parts:
        # Fully-qualified forms first, so they win over a bare stem when both are
        # registered — see `_import_targets` for the same specificity ordering.
        keys.append(".".join(parts))
        keys.append("/".join(parts))
        # Package-relative: drop the top-level directory, which is often the
        # source root and absent from import strings.
        if len(parts) > 1:
            keys.append(".".join(parts[1:]))
            keys.append("/".join(parts[1:]))

    stem = posix.stem
    if stem and stem not in ("__init__", "index", "mod"):
        keys.append(stem)

    # Order-preserving dedupe keeps registration deterministic across runs.
    return [k for k in dict.fromkeys(keys) if k]


def _import_targets(raw_import: str) -> List[str]:
    """Normalises one import string into candidate module keys.

    Returns them **most specific first**, and the caller takes the first that
    matches a real file. The ordering is the whole point: `services.billing`
    generates both `services.billing` and the bare tail `billing`, and it also
    generates `services` — so trying them in an arbitrary order can resolve the
    import to the package's `__init__.py` instead of the module actually named.
    """
    cleaned = raw_import.strip().strip("'\"")
    cleaned = cleaned.lstrip(".")  # relative markers carry no name information
    cleaned = re.sub(r"^@[\w-]+/", "", cleaned)  # scoped npm package or alias
    if not cleaned:
        return []

    slashed = cleaned.replace("\\", "/")
    ordered: List[str] = [cleaned, slashed, slashed.replace("/", ".")]

    # Then the final segment on its own, for `from pkg.mod import thing` style
    # imports where `thing` isn't a module.
    if "/" in slashed:
        tail = slashed.rstrip("/").split("/")[-1]
        if tail:
            ordered.append(tail)
            # Only strip a suffix for real path segments — doing it for a dotted
            # module name would turn "services.billing" into "services".
            ordered.append(PurePosixPath(tail).stem)
    dotted_tail = cleaned.split(".")[-1]
    if dotted_tail:
        ordered.append(dotted_tail)

    # Order-preserving dedupe, so the specificity ranking above survives.
    return [c for c in dict.fromkeys(ordered) if c]


def build_module_graph(entries: Dict[str, FileEntry]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Builds (imports, imported_by) over in-repo files only.

    External packages are deliberately excluded: `requests` isn't a module in this
    repository, and including it would drown the graph in third-party noise. What
    's wanted is the internal shape.
    """
    key_to_path: Dict[str, str] = {}
    for path in entries:
        for key in _module_keys(path):
            # First writer wins; a later collision would otherwise silently
            # redirect edges to the wrong file.
            key_to_path.setdefault(key, path)

    imports: Dict[str, List[str]] = {}
    imported_by: Dict[str, List[str]] = {}
    edges = 0

    for path, entry in entries.items():
        resolved = []
        for raw in entry.imports:
            for candidate in _import_targets(raw):
                target = key_to_path.get(candidate)
                if target and target != path and target not in resolved:
                    resolved.append(target)
                    break  # one edge per import statement
        if resolved:
            imports[path] = resolved
            for target in resolved:
                imported_by.setdefault(target, []).append(path)
            edges += len(resolved)
            if edges >= MAX_GRAPH_EDGES:
                break

    for path in imported_by:
        imported_by[path] = sorted(set(imported_by[path]))
    return imports, imported_by


# -- routes, integrations, env ----------------------------------------------


def _extract_routes(rel_path: str, content: str, language: str = "") -> List[Route]:
    """Finds route declarations, ignoring commented-out ones.

    Comments are stripped first for the same reason symbol extraction does it: a
    codebase with an endpoint commented out would otherwise be reported as still
    serving it, which is worse than missing it.
    """
    routes: List[Route] = []
    # Keyed by (method, path, line) so the same declaration found by two patterns
    # is reported once. `@app.get(...)` legitimately matches both the Python
    # decorator pattern and the Express one, and listing it twice would both waste
    # prompt budget and imply two endpoints exist.
    seen = set()
    lines = strip_comment_lines(content, language)
    for flavour, pattern in _ROUTE_PATTERNS:
        for number, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                groups = [g for g in match.groups() if g is not None]
                if not groups:
                    continue
                if len(groups) >= 2:
                    method, route_path = groups[0], groups[1]
                else:
                    method, route_path = "", groups[0]
                # A "route" that's obviously not a path is a false positive.
                if not route_path or (not route_path.startswith("/") and flavour != "django"):
                    continue
                normalized = method.upper().replace("ROUTE", "ANY").replace("USE", "ANY")
                key = (normalized, route_path, number)
                if key in seen:
                    continue
                seen.add(key)
                routes.append(
                    Route(
                        method=normalized,
                        path=route_path,
                        file=rel_path,
                        line=number,
                        flavour=flavour,
                    )
                )
    return routes


def _extract_env_vars(content: str, language: str = "") -> List[str]:
    """Finds environment variables the code reads, ignoring commented-out ones."""
    text = "\n".join(strip_comment_lines(content, language))
    found = []
    for pattern in _ENV_PATTERNS:
        found.extend(pattern.findall(text))
    return found


def detect_frameworks(manifests: Sequence[Manifest]) -> List[str]:
    """Names the frameworks a project declares, from its manifests."""
    found = []
    for manifest in manifests:
        for name in list(manifest.dependencies) + list(manifest.dev_dependencies):
            label = _FRAMEWORK_BY_DEPENDENCY.get(name.lower())
            if label and label not in found:
                found.append(label)
    return sorted(found)


def detect_integrations(entries: Dict[str, FileEntry]) -> List[str]:
    """Names the external systems the code imports clients for."""
    found = []
    for entry in entries.values():
        for raw in entry.imports:
            base = raw.strip().lstrip(".").split(".")[0].split("/")[0].lower()
            label = _INTEGRATION_BY_IMPORT.get(base) or _INTEGRATION_BY_IMPORT.get(raw.lower())
            if label and label not in found:
                found.append(label)
    return sorted(found)


# -- git history ------------------------------------------------------------


def _churn(project_path: Path, limit: int = 400) -> List[Dict[str, object]]:
    """Counts how often each file changed across recent commits.

    A file that changes constantly is either the heart of the system or a problem
    area; either way it's worth the AI knowing before suggesting a rewrite.
    """
    result = git_ops.run_git(
        project_path, ["log", f"-{limit}", "--name-only", "--format=%x00%H"], timeout=30.0
    )
    if result.returncode != 0:
        return []
    counts: Counter = Counter()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("\x00"):
            continue
        counts[line] += 1
    return [
        {"path": path, "commits": count}
        for path, count in counts.most_common(MAX_HOT_FILES)
    ]


def _recent_commits(project_path: Path, limit: int = 15) -> List[Dict[str, str]]:
    try:
        return [
            {"sha": c.short_sha, "subject": c.subject, "author": c.author, "when": c.when}
            for c in git_ops.log(project_path, limit=limit)
        ]
    except Exception:
        return []


# -- assembly ---------------------------------------------------------------


def _looks_like_test(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", "_test.rs", ".test.ts", ".test.js",
                          ".test.tsx", ".test.jsx", ".spec.ts", ".spec.js"))
        or "/tests/" in f"/{lowered}"
        or "/__tests__/" in f"/{lowered}"
    )


_CONFIG_NAMES = {
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile",
    ".env.example", ".gitlab-ci.yml", "jenkinsfile", "procfile", "vercel.json",
    "tsconfig.json", "eslintrc", ".eslintrc.json", "pytest.ini", "tox.ini",
    "setup.cfg", "nginx.conf", "terraform.tf",
}


def _looks_like_config(path: str) -> bool:
    lowered = PurePosixPath(path.lower()).name
    if lowered in _CONFIG_NAMES:
        return True
    return lowered.endswith((".tf", ".tfvars")) or "/.github/workflows/" in f"/{path.lower()}"


def build_depth(
    project_path: Union[str, Path],
    entries: Dict[str, FileEntry],
    manifests: Sequence[Manifest],
    read_file=None,
) -> RepoDepth:
    """Derives the structural picture from an already-built file index.

    `read_file(rel_path) -> str | None` is injectable so callers control disk
    access; it's only used for files whose language could plausibly declare a
    route or read an environment variable, not for the whole repository.
    """
    project_path = Path(project_path)
    if read_file is None:
        from ..project_files import read_file as project_read

        def read_file(rel: str):  # noqa: F811 - deliberate local default
            return project_read(project_path, rel, max_bytes=200_000)

    imports, imported_by = build_module_graph(entries)

    routes: List[Route] = []
    env_vars: Counter = Counter()
    scannable = {
        "python", "javascript", "typescript", "go", "java", "ruby", "php",
        "kotlin", "rust", "csharp",
    }
    for path, entry in entries.items():
        if entry.skipped or entry.language not in scannable:
            continue
        content = read_file(path)
        if not content:
            continue
        if len(routes) < MAX_ROUTES:
            routes.extend(_extract_routes(path, content, entry.language))
        env_vars.update(_extract_env_vars(content, entry.language))

    hub_modules = sorted(
        (path for path, importers in imported_by.items() if len(importers) >= HUB_THRESHOLD),
        key=lambda p: (-len(imported_by[p]), p),
    )
    # Nothing imports it and it imports nothing in-repo: usually a script, an
    # entry point, or dead code — all worth flagging as such.
    orphans = sorted(
        path for path in entries
        if path not in imported_by and path not in imports and not entries[path].skipped
        and entries[path].language in scannable
    )

    return RepoDepth(
        imports=imports,
        imported_by=imported_by,
        hub_modules=hub_modules[:MAX_HOT_FILES],
        orphan_modules=orphans[:MAX_HOT_FILES],
        routes=routes[:MAX_ROUTES],
        frameworks=detect_frameworks(manifests),
        integrations=detect_integrations(entries),
        env_vars=[name for name, _count in env_vars.most_common(60)],
        hot_files=_churn(project_path),
        recent_commits=_recent_commits(project_path),
        test_files=sorted(p for p in entries if _looks_like_test(p))[:MAX_HOT_FILES],
        config_files=sorted(p for p in entries if _looks_like_config(p))[:MAX_HOT_FILES],
    )


def render_depth(depth: RepoDepth, max_chars: int = 4000, focus: str = "") -> str:
    """Renders the depth picture as prompt context.

    `focus` (a file path) pulls that file's dependents and dependencies to the
    front — for an edit, "what else touches this" is the single most useful fact
    here.
    """
    sections: List[Tuple[str, str]] = []

    if focus:
        dependents = depth.dependents_of(focus)
        dependencies = depth.dependencies_of(focus)
        lines = []
        if dependents:
            lines.append(f"imported by: {', '.join(dependents[:15])}")
        if dependencies:
            lines.append(f"imports: {', '.join(dependencies[:15])}")
        if not lines:
            lines.append("no in-repo modules import this file, and it imports none")
        sections.append((f"impact of changing {focus}", "\n".join(lines)))

    if depth.frameworks:
        sections.append(("frameworks", ", ".join(depth.frameworks)))
    if depth.integrations:
        sections.append(("external systems", ", ".join(depth.integrations)))
    if depth.routes:
        sections.append(
            ("http routes", "\n".join(route.label for route in depth.routes[:25]))
        )
    if depth.hub_modules:
        sections.append(
            (
                "widely-used modules (changes here have wide reach)",
                "\n".join(
                    f"{path} ({len(depth.imported_by.get(path, []))} importers)"
                    for path in depth.hub_modules[:10]
                ),
            )
        )
    if depth.hot_files:
        sections.append(
            (
                "most-changed files",
                ", ".join(f"{item['path']} ({item['commits']})" for item in depth.hot_files[:10]),
            )
        )
    if depth.recent_commits:
        sections.append(
            (
                "recent commits",
                "\n".join(f"{c['sha']} {c['subject']}" for c in depth.recent_commits[:8]),
            )
        )
    if depth.env_vars:
        sections.append(("environment variables read", ", ".join(depth.env_vars[:25])))
    if depth.test_files:
        sections.append(("test files", ", ".join(depth.test_files[:12])))

    parts: List[str] = []
    used = 0
    for label, body in sections:
        if not body.strip():
            continue
        block = f"\n[{label}]\n{body}"
        if used + len(block) > max_chars:
            continue
        parts.append(block)
        used += len(block)
    return "".join(parts).strip()
