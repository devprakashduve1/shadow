"""Coding Agent orchestration: plan a fix, then apply it on a new git branch.

Two entry points the GUI (the Code tab's "Plan Multi-File Change" flow in
`gui/ide/tab.py`, via `gui/workers.py`'s `PlanWorker`/`ApplyWorker`) calls:

- `generate_plan()` — reads the project's files (`assistant/project_files.py`)
  and asks the local model for a plan, not code yet.
- `apply_plan()` — once the user approves, writes the actual file changes on
  a brand-new git branch and commits them. Never touches the user's current
  branch or working tree — see the precondition checks below.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Union

from .git_ops import is_git_repo, run_git
from .project_files import build_file_tree_text, find_relevant_files, list_files, read_file, write_file
from .prompts import build_file_rewrite_prompt, build_plan_prompt
from .streaming import stream_chat

_FILES_MARKER_RE = re.compile(r"(?im)^\s*FILES:\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class CodingAgentError(RuntimeError):
    """Raised when a plan can't safely be generated or applied."""


@dataclass
class PlanFile:
    path: str
    is_new: bool = False


@dataclass
class PlanResult:
    summary: str
    files: List[PlanFile] = field(default_factory=list)
    raw: str = ""


@dataclass
class ApplyResult:
    branch: str
    changed_files: List[str]


def _parse_plan(raw_text: str, known_files: Iterable[str]) -> PlanResult:
    """Splits a plan completion at its `FILES:` marker (see `prompts.build_plan_prompt`).

    Tolerant like `chat_engine._parse_questions` — small local models don't
    always follow formatting instructions exactly. Paths not marked `NEW:`
    that don't actually exist in the project are dropped rather than trusted,
    since a hallucinated path should never reach `apply_plan()`.
    """
    known = set(known_files)
    match = _FILES_MARKER_RE.search(raw_text)
    if not match:
        return PlanResult(summary=raw_text.strip(), files=[], raw=raw_text)

    summary = raw_text[: match.start()].strip()
    files: List[PlanFile] = []
    seen = set()
    for line in raw_text[match.end() :].splitlines():
        line = line.strip().lstrip("-*").strip().strip("`\"'")
        if not line:
            continue
        is_new = False
        if line.upper().startswith("NEW:"):
            is_new = True
            line = line[4:].strip()
        if not line or line in seen:
            continue
        if not is_new and line not in known:
            continue
        seen.add(line)
        files.append(PlanFile(path=line, is_new=is_new))

    return PlanResult(summary=summary, files=files, raw=raw_text)


def generate_plan(
    project_path: Union[str, Path],
    issue: str,
    captured_context: str = "",
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 180.0,
    max_relevant_files: int = 6,
    max_file_bytes: int = 6000,
    previous_plan: Optional[str] = None,
    feedback: Optional[str] = None,
) -> PlanResult:
    """Reads the project and asks the model for an implementation plan (no code yet)."""
    project_path = Path(project_path)
    file_tree = build_file_tree_text(project_path)
    search_text = f"{issue}\n{feedback}" if feedback else issue
    relevant_files = find_relevant_files(
        project_path, search_text, max_files=max_relevant_files, max_bytes_per_file=max_file_bytes
    )
    prompt = build_plan_prompt(
        issue, file_tree, relevant_files, captured_context, previous_plan=previous_plan, feedback=feedback
    )
    raw = "".join(stream_chat(prompt, base_url=base_url, model=model, timeout_seconds=timeout_seconds))
    known_files = {str(p) for p in list_files(project_path)}
    return _parse_plan(raw, known_files)


def _slugify(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "change"


def _branch_name(issue: str) -> str:
    return f"shadow-agent/{_slugify(issue)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _run_git(project_path: Path, args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Thin alias kept so this module's call sites read unchanged — the shared
    implementation now lives in `assistant/git_ops.py`, which the Code tab's
    git panel uses too."""
    return run_git(project_path, args, timeout=timeout)


def _is_git_repo(project_path: Path) -> bool:
    return is_git_repo(project_path)


def _is_working_tree_clean(project_path: Path) -> bool:
    result = _run_git(project_path, ["status", "--porcelain"])
    return result.returncode == 0 and result.stdout.strip() == ""


def _strip_code_fence(text: str) -> str:
    """Removes a wrapping ``` fence a small model added despite being told not to."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1])
    return text


def apply_plan(
    project_path: Union[str, Path],
    plan: PlanResult,
    issue: str,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "gemma4",
    timeout_seconds: float = 180.0,
) -> ApplyResult:
    """Writes `plan`'s file changes on a brand-new git branch and commits them.

    Refuses to run (raising `CodingAgentError`, nothing written) unless
    `project_path` is a git repo with a clean working tree — the user's
    current branch/uncommitted work is never touched either way.
    """
    project_path = Path(project_path)

    if not _is_git_repo(project_path):
        raise CodingAgentError(
            f"{project_path} isn't a git repository. Run `git init` (and make an initial commit) "
            "there first, so the Coding Agent's changes are always on a revertible branch."
        )
    if not _is_working_tree_clean(project_path):
        raise CodingAgentError(
            "This project has uncommitted changes. Commit or stash your own work first — the "
            "Coding Agent only ever applies changes on a fresh branch and won't mix them with "
            "work already in progress."
        )
    if not plan.files:
        raise CodingAgentError("This plan doesn't name any files to change — nothing to apply.")

    branch = _branch_name(issue)
    checkout = _run_git(project_path, ["checkout", "-b", branch])
    if checkout.returncode != 0:
        raise CodingAgentError(f"Could not create branch {branch!r}: {checkout.stderr.strip()}")

    changed_files: List[str] = []
    for plan_file in plan.files:
        current_content = "" if plan_file.is_new else (read_file(project_path, plan_file.path, max_bytes=20000) or "")
        prompt = build_file_rewrite_prompt(
            plan_file.path, current_content, plan.summary, issue, is_new=plan_file.is_new
        )
        new_content = "".join(
            stream_chat(prompt, base_url=base_url, model=model, timeout_seconds=timeout_seconds)
        )
        write_file(project_path, plan_file.path, _strip_code_fence(new_content))
        changed_files.append(plan_file.path)

    add_result = _run_git(project_path, ["add", "-A"])
    if add_result.returncode != 0:
        raise CodingAgentError(f"`git add` failed on branch {branch!r}: {add_result.stderr.strip()}")

    commit_message = f"Shadow AI: {issue.strip()[:72]}"
    commit_result = _run_git(project_path, ["commit", "-m", commit_message])
    if commit_result.returncode != 0:
        raise CodingAgentError(f"`git commit` failed on branch {branch!r}: {commit_result.stderr.strip()}")

    return ApplyResult(branch=branch, changed_files=changed_files)
