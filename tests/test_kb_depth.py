"""Tests for assistant/knowledge/depth.py.

The module graph is the part that matters most: impact analysis ("what breaks if
I change this?") is only useful if the edges are real, so the tests assert both
that genuine edges exist and that spurious ones don't.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assistant.knowledge.depth import (
    HUB_THRESHOLD,
    RepoDepth,
    Route,
    build_depth,
    build_module_graph,
    detect_frameworks,
    detect_integrations,
    render_depth,
)
from assistant.knowledge.indexer import KnowledgeBank, build_index
from assistant.knowledge.schema import FileEntry, Manifest


def _git(path: Path, *args: str):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def _entry(path: str, imports=None, language: str = "python") -> FileEntry:
    return FileEntry(
        path=path, size=1, mtime_ns=1, sha1="x", language=language, imports=list(imports or [])
    )


@pytest.fixture
def shadow_root(tmp_path: Path) -> Path:
    return tmp_path / "shadow"


@pytest.fixture
def api_repo(tmp_path: Path) -> Path:
    """A small but realistic API project."""
    repo = tmp_path / "api"
    repo.mkdir()
    for args in (["init"], ["config", "user.email", "t@e.com"], ["config", "user.name", "T"],
                 ["config", "commit.gpgsign", "false"]):
        _git(repo, *args)

    (repo / "app.py").write_text(
        "import os\n"
        "from fastapi import FastAPI\n"
        "from services.billing import charge\n\n"
        "app = FastAPI()\n"
        'DB = os.environ["DATABASE_URL"]\n\n'
        '@app.get("/health")\n'
        "def health():\n    return {}\n\n"
        '@app.post("/orders")\n'
        "def create_order():\n    return charge({})\n\n"
        '# @app.delete("/orders/{id}")  <- commented out\n'
    )
    (repo / "services").mkdir()
    (repo / "services" / "__init__.py").write_text("")
    (repo / "services" / "billing.py").write_text("import stripe\n\n\ndef charge(p):\n    return p\n")
    (repo / "services" / "notify.py").write_text(
        "from services.billing import charge\n\n\ndef notify():\n    return charge({})\n"
    )
    (repo / "requirements.txt").write_text("fastapi\nsqlalchemy\nredis\nstripe\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_health():\n    pass\n")
    (repo / "Dockerfile").write_text("FROM python:3.11\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial api")
    return repo


@pytest.fixture
def depth(api_repo: Path, shadow_root: Path) -> RepoDepth:
    build_index(api_repo, shadow_root)
    return KnowledgeBank(api_repo, shadow_root).load_depth()


# -- module graph ------------------------------------------------------------


def test_graph_links_a_real_import() -> None:
    entries = {
        "app.py": _entry("app.py", ["services.billing"]),
        "services/billing.py": _entry("services/billing.py"),
    }

    imports, imported_by = build_module_graph(entries)

    assert imports["app.py"] == ["services/billing.py"]
    assert imported_by["services/billing.py"] == ["app.py"]


def test_graph_excludes_external_packages() -> None:
    """`requests` isn't a module in this repo; including it would drown the
    internal shape in third-party noise."""
    entries = {"app.py": _entry("app.py", ["requests", "os", "fastapi"])}

    imports, imported_by = build_module_graph(entries)

    assert imports == {} and imported_by == {}


def test_graph_resolves_relative_imports() -> None:
    entries = {
        "pkg/main.py": _entry("pkg/main.py", [".helper"]),
        "pkg/helper.py": _entry("pkg/helper.py"),
    }

    imports, _ = build_module_graph(entries)

    assert imports["pkg/main.py"] == ["pkg/helper.py"]


def test_graph_resolves_js_path_imports() -> None:
    entries = {
        "src/app.ts": _entry("src/app.ts", ["./lib/api"], language="typescript"),
        "src/lib/api.ts": _entry("src/lib/api.ts", language="typescript"),
    }

    imports, _ = build_module_graph(entries)

    assert imports["src/app.ts"] == ["src/lib/api.ts"]


def test_graph_ignores_self_imports() -> None:
    entries = {"app.py": _entry("app.py", ["app"])}

    imports, _ = build_module_graph(entries)

    assert imports == {}


def test_graph_identifies_hub_modules() -> None:
    """A module many files import has wide blast radius, worth stating."""
    entries = {"core.py": _entry("core.py")}
    for index in range(HUB_THRESHOLD + 2):
        entries[f"mod{index}.py"] = _entry(f"mod{index}.py", ["core"])

    _imports, imported_by = build_module_graph(entries)

    assert len(imported_by["core.py"]) >= HUB_THRESHOLD


def test_dependents_and_dependencies_round_trip(depth: RepoDepth) -> None:
    assert "app.py" in depth.dependents_of("services/billing.py")
    assert "services/notify.py" in depth.dependents_of("services/billing.py")
    assert "services/billing.py" in depth.dependencies_of("app.py")


def test_dependents_of_an_unknown_path_is_empty(depth: RepoDepth) -> None:
    assert depth.dependents_of("does/not/exist.py") == []


# -- routes ------------------------------------------------------------------


def test_routes_are_detected(depth: RepoDepth) -> None:
    found = {(route.method, route.path) for route in depth.routes}

    assert ("GET", "/health") in found
    assert ("POST", "/orders") in found


def test_commented_out_routes_are_not_reported(depth: RepoDepth) -> None:
    """Reporting a disabled endpoint as live is worse than missing it."""
    assert not any(route.method == "DELETE" for route in depth.routes)


def test_routes_are_not_duplicated(depth: RepoDepth) -> None:
    """`@app.get(...)` matches both the decorator and Express patterns, so the
    same declaration would otherwise appear twice."""
    keys = [(r.method, r.path, r.file, r.line) for r in depth.routes]

    assert len(keys) == len(set(keys))


def test_express_routes_are_detected(tmp_path: Path, shadow_root: Path) -> None:
    repo = tmp_path / "web"
    repo.mkdir()
    (repo / "server.js").write_text(
        'const app = require("express")();\n'
        'app.get("/users", h);\n'
        'router.post("/users", h);\n'
        '// app.delete("/users/:id", h);\n'
    )
    build_index(repo, shadow_root)

    routes = KnowledgeBank(repo, shadow_root).load_depth().routes
    found = {(r.method, r.path) for r in routes}

    assert ("GET", "/users") in found
    assert ("POST", "/users") in found
    assert not any(r.method == "DELETE" for r in routes)


def test_route_label_is_readable() -> None:
    route = Route(method="GET", path="/health", file="app.py", line=12)
    assert "GET" in route.label and "/health" in route.label and "app.py:12" in route.label


# -- frameworks and integrations --------------------------------------------


def test_frameworks_come_from_declared_dependencies() -> None:
    """Dependency-based on purpose: a manifest listing `next` is conclusive."""
    manifests = [
        Manifest(path="package.json", kind="npm", dependencies={"react": "^18", "next": "^14"}),
        Manifest(path="requirements.txt", kind="pip", dependencies={"fastapi": ""}),
    ]

    assert detect_frameworks(manifests) == ["FastAPI", "Next.js", "React"]


def test_unknown_dependencies_are_not_invented() -> None:
    manifests = [Manifest(path="p.json", kind="npm", dependencies={"some-obscure-lib": "1"})]
    assert detect_frameworks(manifests) == []


def test_dev_dependencies_count_as_frameworks() -> None:
    manifests = [Manifest(path="p.json", kind="npm", dev_dependencies={"jest": "^29"})]
    assert detect_frameworks(manifests) == ["Jest"]


def test_integrations_come_from_imports() -> None:
    entries = {
        "a.py": _entry("a.py", ["redis", "boto3"]),
        "b.py": _entry("b.py", ["stripe"]),
    }

    assert detect_integrations(entries) == ["AWS", "Redis", "Stripe"]


def test_integrations_detected_in_a_real_repo(depth: RepoDepth) -> None:
    assert "Stripe" in depth.integrations


def test_frameworks_detected_in_a_real_repo(depth: RepoDepth) -> None:
    assert "FastAPI" in depth.frameworks
    assert "SQLAlchemy" in depth.frameworks


# -- environment variables --------------------------------------------------


def test_env_vars_are_detected(depth: RepoDepth) -> None:
    assert "DATABASE_URL" in depth.env_vars


def test_commented_out_env_vars_are_ignored(tmp_path: Path, shadow_root: Path) -> None:
    repo = tmp_path / "envtest"
    repo.mkdir()
    (repo / "conf.py").write_text(
        'import os\n'
        'LIVE = os.getenv("LIVE_VALUE")\n'
        '# DEAD = os.getenv("DEAD_VALUE")\n'
    )
    build_index(repo, shadow_root)

    env_vars = KnowledgeBank(repo, shadow_root).load_depth().env_vars

    assert "LIVE_VALUE" in env_vars
    assert "DEAD_VALUE" not in env_vars


# -- classification ---------------------------------------------------------


def test_test_files_are_identified(depth: RepoDepth) -> None:
    assert "tests/test_app.py" in depth.test_files


def test_config_files_are_identified(depth: RepoDepth) -> None:
    assert "Dockerfile" in depth.config_files


# -- git history ------------------------------------------------------------


def test_recent_commits_are_recorded(depth: RepoDepth) -> None:
    assert depth.recent_commits
    assert depth.recent_commits[0]["subject"] == "initial api"


def test_hot_files_are_recorded(depth: RepoDepth) -> None:
    """Churn tells the AI which files are load-bearing or troublesome."""
    paths = {item["path"] for item in depth.hot_files}
    assert "app.py" in paths


def test_history_is_empty_for_a_non_git_project(tmp_path: Path, shadow_root: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("x = 1\n")
    build_index(plain, shadow_root)

    depth = KnowledgeBank(plain, shadow_root).load_depth()

    assert depth.recent_commits == []
    assert depth.hot_files == []


# -- persistence and rendering ----------------------------------------------


def test_depth_is_persisted_with_the_index(api_repo: Path, shadow_root: Path) -> None:
    build_index(api_repo, shadow_root)

    reloaded = KnowledgeBank(api_repo, shadow_root).load_depth()

    assert reloaded.frameworks and reloaded.imports


def test_depth_round_trips_through_json() -> None:
    original = RepoDepth(
        imports={"a.py": ["b.py"]},
        imported_by={"b.py": ["a.py"]},
        routes=[Route(method="GET", path="/x", file="a.py", line=1)],
        frameworks=["FastAPI"],
    )

    restored = RepoDepth.from_dict(original.to_dict())

    assert restored.imports == original.imports
    assert restored.routes[0].path == "/x"
    assert restored.frameworks == ["FastAPI"]


def test_render_leads_with_the_focused_file(depth: RepoDepth) -> None:
    """For an edit, "what else touches this" is the most useful fact available."""
    text = render_depth(depth, focus="services/billing.py")

    assert text.startswith("[impact of changing services/billing.py]")
    assert "app.py" in text


def test_render_states_when_a_file_is_isolated() -> None:
    depth = RepoDepth(frameworks=["FastAPI"])

    text = render_depth(depth, focus="lonely.py")

    assert "no in-repo modules import this file" in text


def test_render_respects_a_budget(depth: RepoDepth) -> None:
    assert len(render_depth(depth, max_chars=300)) <= 300


def test_render_is_empty_for_empty_depth() -> None:
    assert render_depth(RepoDepth()) == ""
