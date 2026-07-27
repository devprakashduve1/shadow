"""Dataclasses and on-disk shapes for a repository's Knowledge Bank.

Everything here is JSON-serializable and carries a `version`, so a future change
to the layout can detect and discard an old bank rather than misreading it.

The bank lives outside the repository (see `assistant/shadow_home.py`) and is
purely derived data — deleting it costs a re-index and nothing else. Nothing in
here is authoritative about the project; the files on disk always are.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Bump when a change makes previously-written banks unreadable, which forces a
# rebuild instead of a misparse. Additive changes don't need a bump — readers
# use .get() with defaults.
SCHEMA_VERSION = 1

# Filenames inside <shadow_home>/<repo-id>/.
META_FILE = "meta.json"
FILES_FILE = "files.json"
MANIFESTS_FILE = "manifests.json"
DOCS_FILE = "docs.json"
OUTLINE_FILE = "outline.json"
SUMMARIES_FILE = "summaries.json"
LOCK_FILE = "advisory.lock"

# Summary keys in summaries.json.
SUMMARY_ARCHITECTURE = "architecture"
SUMMARY_PATTERNS = "patterns"
SUMMARY_ONBOARDING = "onboarding"

# Summary lifecycle states.
STATUS_MISSING = "missing"
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


@dataclass
class Symbol:
    """One named thing defined in a file.

    `parse` records how it was found: "ast" means a real parser (accurate),
    "regex" means a best-effort pattern match. Context assembly down-weights
    regex symbols, since they include false positives.
    """

    kind: str  # class | function | method | const | interface | type | enum
    name: str
    line: int
    signature: str = ""
    doc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        # Omit empty strings — a 10k-file index carries a lot of these.
        data = {"kind": self.kind, "name": self.name, "line": self.line}
        if self.signature:
            data["signature"] = self.signature
        if self.doc:
            data["doc"] = self.doc
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Symbol":
        return cls(
            kind=data.get("kind", ""),
            name=data.get("name", ""),
            line=data.get("line", 0),
            signature=data.get("signature", ""),
            doc=data.get("doc", ""),
        )


@dataclass
class FileEntry:
    """The indexed view of one file.

    `sha1` is the authority on whether a file changed; `size`/`mtime_ns` are only
    a cheap gate to decide whether re-hashing is worth it (see the indexer).
    """

    path: str
    size: int
    mtime_ns: int
    sha1: str
    language: str = "unknown"
    loc: int = 0
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    parse: str = "none"  # ast | regex | none
    skipped: str = ""  # why it has no symbols, e.g. "too_large"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha1": self.sha1,
            "language": self.language,
            "loc": self.loc,
            "parse": self.parse,
        }
        if self.symbols:
            data["symbols"] = [s.to_dict() for s in self.symbols]
        if self.imports:
            data["imports"] = self.imports
        if self.skipped:
            data["skipped"] = self.skipped
        return data

    @classmethod
    def from_dict(cls, path: str, data: Dict[str, Any]) -> "FileEntry":
        return cls(
            path=path,
            size=data.get("size", 0),
            mtime_ns=data.get("mtime_ns", 0),
            sha1=data.get("sha1", ""),
            language=data.get("language", "unknown"),
            loc=data.get("loc", 0),
            symbols=[Symbol.from_dict(s) for s in data.get("symbols", [])],
            imports=list(data.get("imports", [])),
            parse=data.get("parse", "none"),
            skipped=data.get("skipped", ""),
        )


@dataclass
class Manifest:
    """A parsed dependency manifest (package.json, pyproject.toml, ...)."""

    path: str
    kind: str  # npm | pip | poetry | go | cargo | maven
    name: str = ""
    version: str = ""
    dependencies: Dict[str, str] = field(default_factory=dict)
    dev_dependencies: Dict[str, str] = field(default_factory=dict)
    scripts: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        return cls(
            path=data.get("path", ""),
            kind=data.get("kind", ""),
            name=data.get("name", ""),
            version=data.get("version", ""),
            dependencies=dict(data.get("dependencies", {})),
            dev_dependencies=dict(data.get("dev_dependencies", {})),
            scripts=dict(data.get("scripts", {})),
        )


@dataclass
class DocExcerpt:
    """A README or docs file, trimmed to something prompt-sized."""

    path: str
    title: str = ""
    excerpt: str = ""
    headings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocExcerpt":
        return cls(
            path=data.get("path", ""),
            title=data.get("title", ""),
            excerpt=data.get("excerpt", ""),
            headings=list(data.get("headings", [])),
        )


@dataclass
class GitState:
    """The repository's git position when the index was last written.

    `dirty_paths` is the load-bearing field for incremental correctness: a file
    that was uncommitted at index time and has since been reverted looks
    unchanged to `git diff`, so the next update has to re-read the paths that
    were dirty *last* time as well as the ones dirty now.
    """

    is_repo: bool = False
    head_sha: str = ""
    branch: str = ""
    dirty: bool = False
    dirty_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitState":
        return cls(
            is_repo=data.get("is_repo", False),
            head_sha=data.get("head_sha", ""),
            branch=data.get("branch", ""),
            dirty=data.get("dirty", False),
            dirty_paths=list(data.get("dirty_paths", [])),
        )


@dataclass
class BankMeta:
    """meta.json — identity, git position, and index state."""

    repo_id: str
    name: str
    root_path: str
    created_at: str = ""
    updated_at: str = ""
    git: GitState = field(default_factory=GitState)
    file_count: int = 0
    skipped_count: int = 0
    truncated: bool = False  # hit the max_files cap
    index_mode: str = "full"  # full | incremental
    version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["git"] = self.git.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BankMeta":
        return cls(
            repo_id=data.get("repo_id", ""),
            name=data.get("name", ""),
            root_path=data.get("root_path", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            git=GitState.from_dict(data.get("git", {})),
            file_count=data.get("file_count", 0),
            skipped_count=data.get("skipped_count", 0),
            truncated=data.get("truncated", False),
            index_mode=data.get("index_mode", "full"),
            version=data.get("version", 0),
        )


@dataclass
class SummaryEntry:
    """One LLM-written prose summary, plus what it was generated from.

    `source_fingerprint` is deliberately coarse (see `summaries.fingerprint`) so
    editing a single function doesn't invalidate the architecture description.
    """

    text: str = ""
    status: str = STATUS_MISSING
    model: str = ""
    generated_at: str = ""
    source_fingerprint: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SummaryEntry":
        return cls(
            text=data.get("text", ""),
            status=data.get("status", STATUS_MISSING),
            model=data.get("model", ""),
            generated_at=data.get("generated_at", ""),
            source_fingerprint=data.get("source_fingerprint", ""),
            error=data.get("error", ""),
        )

    def is_stale_for(self, fingerprint: str) -> bool:
        """True if this summary was written against a different project shape.

        Stale summaries are still served (labelled) rather than hidden — an
        out-of-date architecture description is more useful than none while a
        regeneration is pending.
        """
        return self.status == STATUS_READY and self.source_fingerprint != fingerprint


@dataclass
class IndexResult:
    """What one index run did, for the UI's status line."""

    mode: str  # full | incremental | unchanged
    files_indexed: int = 0
    files_reused: int = 0
    files_removed: int = 0
    truncated: bool = False
    duration_seconds: float = 0.0

    @property
    def summary(self) -> str:
        if self.mode == "unchanged":
            return "up to date"
        parts = [f"{self.files_indexed} indexed"]
        if self.files_reused:
            parts.append(f"{self.files_reused} unchanged")
        if self.files_removed:
            parts.append(f"{self.files_removed} removed")
        text = ", ".join(parts)
        if self.truncated:
            text += " (hit the file limit)"
        return text


# Extension -> language name, used for the index and for grouping the outline.
LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".swift": "swift",
    ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".html": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".xml": "xml",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".vue": "vue", ".svelte": "svelte", ".lua": "lua", ".r": "r", ".dart": "dart",
}


def language_for_path(path: str) -> str:
    """Maps a path to a language name, defaulting to "unknown"."""
    from pathlib import PurePosixPath

    name = PurePosixPath(path).name.lower()
    if name in ("dockerfile", "containerfile"):
        return "dockerfile"
    if name in ("makefile", "gnumakefile"):
        return "make"
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(name).suffix, "unknown")


def files_to_dict(entries: Dict[str, FileEntry]) -> Dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "files": {path: entry.to_dict() for path, entry in entries.items()},
    }


def files_from_dict(data: Optional[Dict[str, Any]]) -> Dict[str, FileEntry]:
    if not data or data.get("version") != SCHEMA_VERSION:
        return {}
    return {
        path: FileEntry.from_dict(path, entry)
        for path, entry in (data.get("files") or {}).items()
    }
