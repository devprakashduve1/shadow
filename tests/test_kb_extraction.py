"""Tests for knowledge/symbols.py and knowledge/manifests.py.

The regex-based extraction is approximate by design; the tests that assert
*known gaps* exist so the limitation stays documented and deliberate rather than
being mistaken for a bug later.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assistant.knowledge.manifests import (
    collect_manifests,
    find_manifests,
    parse_manifest,
    summarize_dependencies,
)
from assistant.knowledge.schema import language_for_path
from assistant.knowledge.symbols import MAX_SYMBOLS_PER_FILE, extract


def _names(symbols) -> set:
    return {s.name for s in symbols}


# -- language detection ------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("app.py", "python"),
        ("src/Component.tsx", "typescript"),
        ("main.go", "go"),
        ("Dockerfile", "dockerfile"),
        ("Makefile", "make"),
        ("data.bin", "unknown"),
    ],
)
def test_language_for_path(path, expected) -> None:
    assert language_for_path(path) == expected


# -- Python (exact, via ast) -------------------------------------------------


def test_python_extracts_classes_functions_and_imports() -> None:
    source = '''
import os
from pathlib import Path

CONSTANT = 42


def top_level(a, b=1, *args, **kwargs):
    """Does a thing."""
    return a


class Widget:
    """A widget."""

    def __init__(self, size):
        self.size = size

    def render(self, mode="fast"):
        """Renders it."""
        return self.size
'''
    symbols, imports, mode = extract("app.py", source)

    assert mode == "ast"
    assert _names(symbols) == {
        "CONSTANT", "top_level", "Widget", "Widget.__init__", "Widget.render"
    }
    assert set(imports) == {"os", "pathlib"}


def test_python_captures_signature_and_docstring() -> None:
    source = 'def fetch(url, timeout=30):\n    """Fetches a URL."""\n    return url\n'

    symbols, _imports, _mode = extract("app.py", source)

    fetch = symbols[0]
    assert fetch.signature == "def fetch(url, timeout=...)"
    assert fetch.doc == "Fetches a URL."


def test_python_marks_async_functions() -> None:
    symbols, _i, _m = extract("app.py", "async def run(x):\n    pass\n")
    assert symbols[0].signature.startswith("async def run")


def test_python_skips_private_methods_but_keeps_init() -> None:
    """An outline of a class shouldn't list its private helpers."""
    source = "class C:\n    def __init__(self): pass\n    def _helper(self): pass\n    def public(self): pass\n"

    symbols, _i, _m = extract("app.py", source)

    assert "C._helper" not in _names(symbols)
    assert {"C.__init__", "C.public"} <= _names(symbols)


def test_python_ignores_non_constant_globals() -> None:
    symbols, _i, _m = extract("app.py", "CONFIG = 1\nlowercase_global = 2\n")

    assert "CONFIG" in _names(symbols)
    assert "lowercase_global" not in _names(symbols)


def test_python_records_relative_imports() -> None:
    _s, imports, _m = extract("app.py", "from . import sibling\nfrom ..pkg import thing\n")
    assert "." in imports
    assert "..pkg" in imports


def test_python_syntax_error_falls_back_to_regex() -> None:
    """A file being mid-edit must not drop out of the index entirely."""
    broken = "def valid():\n    pass\n\ndef broken(:\n"

    symbols, _imports, mode = extract("app.py", broken)

    assert mode == "regex"
    assert "valid" in _names(symbols)


def test_symbols_are_capped_per_file() -> None:
    source = "\n".join(f"def f{i}(): pass" for i in range(MAX_SYMBOLS_PER_FILE + 50))

    symbols, _i, _m = extract("app.py", source)

    assert len(symbols) == MAX_SYMBOLS_PER_FILE


# -- JavaScript / TypeScript (approximate, via regex) ------------------------


def test_typescript_extracts_declarations() -> None:
    source = """
import { useState } from 'react';
import helper from './helper';

export interface Props { id: string }
export type Mode = 'a' | 'b';
export enum Colour { Red, Blue }

export function render(props: Props) { return null; }
export const handleClick = (e: Event) => { console.log(e); };
export class Widget { }
"""
    symbols, imports, mode = extract("Component.tsx", source)

    assert mode == "regex"
    assert {"Props", "Mode", "Colour", "render", "handleClick", "Widget"} <= _names(symbols)
    assert set(imports) == {"react", "./helper"}


def test_javascript_extracts_require_imports() -> None:
    _s, imports, _m = extract("app.js", "const fs = require('fs');\n")
    assert "fs" in imports


def test_regex_ignores_commented_out_code() -> None:
    """Without comment stripping, this would report a function that doesn't exist."""
    source = "// export function ghost() {}\n/* class Phantom {} */\nexport function real() {}\n"

    symbols, _i, _m = extract("app.ts", source)

    assert "real" in _names(symbols)
    assert "ghost" not in _names(symbols)
    assert "Phantom" not in _names(symbols)


def test_regex_symbols_are_in_file_order() -> None:
    source = "export class A {}\nexport function b() {}\nexport class C {}\n"

    symbols, _i, _m = extract("app.ts", source)

    assert [s.line for s in symbols] == sorted(s.line for s in symbols)


def test_known_gap_class_methods_are_not_extracted() -> None:
    """Documented limitation: only the class is found, not its methods.

    Asserted so the gap is explicit. If a real parser is added later, this test
    should be updated rather than silently starting to pass differently.
    """
    source = "export class Service {\n  fetchData() { return 1; }\n}\n"

    symbols, _i, _m = extract("app.ts", source)

    assert "Service" in _names(symbols)
    assert "fetchData" not in _names(symbols)


def test_known_gap_object_property_arrow_functions() -> None:
    """Another documented limitation."""
    source = "const api = {\n  getUser: () => fetch('/u'),\n};\n"

    symbols, _i, _m = extract("app.ts", source)

    assert "getUser" not in _names(symbols)


# -- other languages ---------------------------------------------------------


def test_go_extracts_functions_methods_and_types() -> None:
    source = """package main

import "fmt"

type Server struct {}

func NewServer() *Server { return &Server{} }

func (s *Server) Start(port int) error { return nil }
"""
    symbols, imports, _m = extract("main.go", source)

    assert {"Server", "NewServer", "Start"} <= _names(symbols)
    assert "fmt" in imports


def test_rust_extracts_items() -> None:
    source = "pub struct Config {}\npub enum Mode { A }\npub trait Run {}\npub async fn go() {}\n"

    symbols, _i, _m = extract("lib.rs", source)

    assert {"Config", "Mode", "Run", "go"} <= _names(symbols)


def test_ruby_extracts_classes_and_methods() -> None:
    symbols, _i, _m = extract("app.rb", "class Widget\n  def render\n  end\nend\n")
    assert {"Widget", "render"} <= _names(symbols)


def test_unknown_language_yields_nothing() -> None:
    symbols, imports, mode = extract("data.bin", "\x01\x02")
    assert symbols == [] and imports == [] and mode == "none"


# -- manifests ---------------------------------------------------------------


def test_parses_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "web", "version": "1.2.3", "dependencies": {"react": "^18.0.0"},'
        ' "devDependencies": {"vite": "^5"}, "scripts": {"dev": "vite"}}'
    )

    manifest = parse_manifest(tmp_path, tmp_path / "package.json")

    assert manifest.kind == "npm"
    assert manifest.name == "web" and manifest.version == "1.2.3"
    assert manifest.dependencies == {"react": "^18.0.0"}
    assert manifest.dev_dependencies == {"vite": "^5"}
    assert manifest.scripts == {"dev": "vite"}


def test_parses_requirements_with_markers_and_extras(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests>=2.0\n"
        "uvicorn[standard]==0.30 ; python_version >= '3.9'\n"
        "# a comment\n"
        "-r other.txt\n"
        "-e .\n"
        "\n"
        "plain-package\n"
    )

    manifest = parse_manifest(tmp_path, tmp_path / "requirements.txt")

    assert manifest.dependencies["requests"] == ">=2.0"
    assert manifest.dependencies["uvicorn"] == "==0.30"
    assert manifest.dependencies["plain-package"] == ""
    assert "-r" not in manifest.dependencies and "#" not in manifest.dependencies


def test_parses_pyproject_pep621(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "shadow"\nversion = "0.1.0"\n'
        'dependencies = [\n  "requests>=2",\n  "PyYAML",\n]\n'
    )

    manifest = parse_manifest(tmp_path, tmp_path / "pyproject.toml")

    assert manifest.name == "shadow" and manifest.version == "0.1.0"
    assert "requests" in manifest.dependencies
    assert "PyYAML" in manifest.dependencies


def test_parses_pyproject_poetry_style(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "svc"\nversion = "2.0"\n\n'
        '[tool.poetry.dependencies]\npython = "^3.9"\nfastapi = "^0.110"\n'
    )

    manifest = parse_manifest(tmp_path, tmp_path / "pyproject.toml")

    assert manifest.name == "svc"
    assert manifest.dependencies["fastapi"] == "^0.110"


def test_parses_go_mod_require_block(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text(
        "module example.com/app\n\ngo 1.21\n\n"
        "require (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgolang.org/x/sync v0.5.0\n)\n"
    )

    manifest = parse_manifest(tmp_path, tmp_path / "go.mod")

    assert manifest.name == "example.com/app"
    assert manifest.dependencies["github.com/gin-gonic/gin"] == "v1.9.1"
    assert manifest.dependencies["golang.org/x/sync"] == "v0.5.0"


def test_parses_go_mod_single_line_require(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module m\n\nrequire example.com/x v1.2.3\n")

    manifest = parse_manifest(tmp_path, tmp_path / "go.mod")

    assert manifest.dependencies["example.com/x"] == "v1.2.3"


def test_parses_cargo_toml(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "tool"\nversion = "0.3.0"\n\n[dependencies]\nserde = "1.0"\n'
    )

    manifest = parse_manifest(tmp_path, tmp_path / "Cargo.toml")

    assert manifest.name == "tool"
    assert manifest.dependencies["serde"] == "1.0"


def test_parses_pom_xml_with_namespace(tmp_path: Path) -> None:
    """Real POMs are namespaced, which makes tag names unmatchable directly."""
    (tmp_path / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<artifactId>svc</artifactId><version>1.0</version><dependencies>"
        "<dependency><groupId>org.junit</groupId><artifactId>junit</artifactId>"
        "<version>5.0</version><scope>test</scope></dependency>"
        "<dependency><groupId>com.google</groupId><artifactId>guava</artifactId>"
        "<version>33.0</version></dependency>"
        "</dependencies></project>"
    )

    manifest = parse_manifest(tmp_path, tmp_path / "pom.xml")

    assert manifest.name == "svc"
    assert manifest.dependencies["com.google:guava"] == "33.0"
    assert manifest.dev_dependencies["org.junit:junit"] == "5.0", "test scope is a dev dep"


def test_setup_py_is_not_executed(tmp_path: Path) -> None:
    """Running a repo's setup.py would execute arbitrary code from that repo."""
    (tmp_path / "setup.py").write_text(
        "raise SystemExit('should never run')\n"
        "setup(name='pkg', version='9.9', install_requires=['click>=8'])\n"
    )

    manifest = parse_manifest(tmp_path, tmp_path / "setup.py")

    assert manifest.name == "pkg" and manifest.version == "9.9"
    assert "click" in manifest.dependencies


def test_malformed_manifest_returns_none_rather_than_raising(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not json at all")

    assert parse_manifest(tmp_path, tmp_path / "package.json") is None


def test_find_manifests_skips_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "node_modules" / "dep").mkdir(parents=True)
    (tmp_path / "node_modules" / "dep" / "package.json").write_text("{}")

    found = {p.relative_to(tmp_path).as_posix() for p in find_manifests(tmp_path)}

    assert "package.json" in found
    assert "node_modules/dep/package.json" not in found


def test_collect_manifests_finds_nested_workspaces(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "root"}')
    (tmp_path / "packages" / "ui").mkdir(parents=True)
    (tmp_path / "packages" / "ui" / "package.json").write_text('{"name": "ui"}')

    names = {m.name for m in collect_manifests(tmp_path)}

    assert names == {"root", "ui"}


def test_summarize_dependencies_renders_a_block() -> None:
    from assistant.knowledge.schema import Manifest

    manifests = [
        Manifest(path="package.json", kind="npm", name="web", version="1.0",
                 dependencies={"react": "^18"}, scripts={"dev": "vite"})
    ]

    text = summarize_dependencies(manifests)

    assert "package.json (npm: web 1.0)" in text
    assert "react" in text and "dev" in text


def test_summarize_dependencies_empty_for_no_manifests() -> None:
    assert summarize_dependencies([]) == ""
