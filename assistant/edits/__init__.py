"""AI-assisted code edits with in-memory preview and reversible application.

Unlike `assistant/coding_agent.py` — which plans a multi-file change and applies
it on a throwaway git branch — everything here operates on files the user is
actively editing. That rules out the branch-and-commit safety model, so safety
comes from elsewhere instead:

- proposals are computed entirely in memory; nothing is written during generation
- applying re-checks the file's hash and refuses if it changed since the proposal
- the previous content is copied to `~/Desktop/.shadow/<repo>/backups/` and
  recorded in a journal before the write, so any edit can be reverted
- the write itself is atomic

Read `patcher.py` first if you're touching the edit-application path; its
refuse-rather-than-guess rule is what keeps a bad model response from silently
corrupting a source file.
"""
from .actions import (
    AppliedEdit,
    EditAction,
    EditProposal,
    EditRequest,
    apply_proposal,
    propose_edit,
    revert,
    stream_explanation,
)
from .diffs import DiffStats, diff_stats, unified_diff_text
from .patcher import EditBlock, PatchError, apply_edit_blocks, parse_edit_blocks

__all__ = [
    "AppliedEdit",
    "DiffStats",
    "EditAction",
    "EditBlock",
    "EditProposal",
    "EditRequest",
    "PatchError",
    "apply_edit_blocks",
    "apply_proposal",
    "diff_stats",
    "parse_edit_blocks",
    "propose_edit",
    "revert",
    "stream_explanation",
    "unified_diff_text",
]
