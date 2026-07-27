"""Prompt construction for the chat assistant.

Same "stay factual, don't invent" spirit as `summarize/log_summarizer.py`'s
`_SYSTEM_PROMPT`, extended with an instruction to cite timestamps/sources
since answers here are conversational Q&A rather than one-shot summaries.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

SYSTEM_PROMPT = (
    "You are Shadow, a local, privacy-first assistant answering questions about the "
    "user's own captured screen-OCR and meeting-transcript activity. Only use "
    "information present in the 'Context' section below — if the answer isn't there, "
    "say you don't have that in the user's history rather than guessing. When you use "
    "a piece of context, refer to when it happened (e.g. 'at 10:05' or 'yesterday') so "
    "the user can trace it back to a source."
)

# Used instead of SYSTEM_PROMPT when the caller wants a normal, free-form
# conversation rather than Q&A grounded in retrieved activity — see
# `build_prompt`'s `free_chat`, used for chatting freely about a selected
# project instead of restricting answers to (often noisy OCR) retrieved
# context.
FREE_CHAT_SYSTEM_PROMPT = (
    "You are Shadow's coding agent assistant, helping the user with their software "
    "project. Answer naturally and helpfully, drawing on your own general knowledge "
    "as well as anything relevant mentioned in the conversation so far — you are not "
    "restricted to a retrieved context block."
)


def build_prompt(
    question: str,
    context: str,
    history: Sequence[dict],
    *,
    scope_label: Optional[str] = None,
    free_chat: bool = False,
) -> str:
    """Builds the full text prompt sent to Ollama's /api/generate.

    `history` is a sequence of {"role": "user"|"assistant", "content": str} dicts,
    oldest first (see `database.json_store.EventStore.get_history`).

    `scope_label`, when set (e.g. by the Coding Agent tab), adds one line
    telling the model to stay within that scope even if unrelated context
    somehow ends up in the retrieved block. Ignored when `free_chat` is True.

    `free_chat`, when True, skips the retrieval-grounded system prompt/context
    block entirely in favor of `FREE_CHAT_SYSTEM_PROMPT` — for callers (the
    Coding Agent tab) that want a normal conversation instead of Q&A
    restricted to retrieved activity.
    """
    if free_chat:
        parts: List[str] = [FREE_CHAT_SYSTEM_PROMPT]
        if history:
            turns = "\n".join(f"{turn['role'].capitalize()}: {turn['content']}" for turn in history)
            parts.append(f"\nConversation so far:\n{turns}")
        parts.append(f"\nUser question: {question}\nAnswer:")
        return "\n".join(parts)

    parts = [SYSTEM_PROMPT]

    if scope_label:
        parts.append(f"\nOnly answer using activity related to {scope_label} — ignore anything else below.")

    if context.strip():
        parts.append(f"\nContext (the user's own captured activity):\n{context}")
    else:
        parts.append("\nContext: (no matching activity found in the user's history)")

    if history:
        turns = "\n".join(f"{turn['role'].capitalize()}: {turn['content']}" for turn in history)
        parts.append(f"\nConversation so far:\n{turns}")

    parts.append(f"\nUser question: {question}\nAnswer:")
    return "\n".join(parts)


SUGGESTED_QUESTIONS_PROMPT = (
    "You generate suggested questions a user could ask about their own captured "
    "activity today (screen-OCR text and meeting transcripts, shown below as Context). "
    "Write 5 to 8 short, specific questions grounded in real facts from the context — "
    "actual names, error messages, ticket numbers, decisions, or times mentioned below — "
    "not generic templates like 'what did I do today'. Every question must be answerable "
    "using only the context below.\n"
    "Output ONLY the questions, one per line, no numbering, no bullets, no other text."
)


def build_suggested_questions_prompt(context: str) -> str:
    """Builds the prompt asking the model to write today's suggested questions.

    Same plain-text-lines output convention as the rest of this app's Ollama
    usage (no JSON parsing of model output) — `chat_engine._parse_questions`
    tolerates numbered/bulleted lines anyway in case a small model doesn't
    follow the "no numbering" instruction exactly.
    """
    return f"{SUGGESTED_QUESTIONS_PROMPT}\n\nContext (today's captured activity):\n{context}\n\nQuestions:"


PLAN_SYSTEM_PROMPT = (
    "You are Shadow's Coding Agent, helping fix an issue in the user's own local project. You are "
    "given the project's file tree, the content of files most likely relevant to the issue, and "
    "(if available) context from the user's own captured screen/meeting activity about it. Write a "
    "short, concrete implementation plan describing what's wrong and what to change, file by file — "
    "do NOT write code yet, this plan is for the user to review before anything is changed. Reference "
    "actual file paths from the tree below; if a new file needs to be created, say so explicitly.\n\n"
    'End your response with a line that says exactly "FILES:" followed by one relative file path per '
    'line for every file your plan touches — prefix a new file\'s line with "NEW: ". Nothing after the '
    "file list."
)


def build_plan_prompt(
    issue: str,
    file_tree: str,
    relevant_files: Sequence[Tuple[str, str]],
    captured_context: str,
    *,
    previous_plan: Optional[str] = None,
    feedback: Optional[str] = None,
) -> str:
    """Builds the prompt for `coding_agent.generate_plan()`.

    When `previous_plan`/`feedback` are set (the user clicked "Revise Plan"),
    both are appended so the model regenerates rather than starting fresh.
    """
    parts: List[str] = [PLAN_SYSTEM_PROMPT, f"\nProject file tree:\n{file_tree}"]

    if relevant_files:
        files_text = "\n\n".join(f"--- {path} ---\n{content}" for path, content in relevant_files)
        parts.append(f"\nLikely relevant files:\n{files_text}")
    else:
        parts.append("\nLikely relevant files: (none matched keywords from the issue)")

    if captured_context.strip():
        parts.append(
            f"\nContext from the user's own captured activity about this project:\n{captured_context}"
        )

    if previous_plan and feedback:
        parts.append(f"\nYou previously proposed this plan:\n{previous_plan}")
        parts.append(f"\nThe user gave this feedback — revise the plan accordingly:\n{feedback}")

    parts.append(f"\nIssue: {issue}\nPlan:")
    return "\n".join(parts)


FILE_REWRITE_SYSTEM_PROMPT = (
    "You are implementing one step of an approved plan to fix an issue in the user's own local "
    "project. You are given one file's current content. Output the COMPLETE new content for this "
    "file only — nothing else: no explanation, no markdown code fence, no commentary before or "
    "after. If this file doesn't actually need to change for the plan, output its current content "
    "unchanged."
)


def build_file_rewrite_prompt(
    rel_path: str, current_content: str, plan_summary: str, issue: str, *, is_new: bool = False
) -> str:
    """Builds the per-file prompt `coding_agent.apply_plan()` sends once per changed file."""
    content_block = "(this file does not exist yet — create it)" if is_new else current_content
    return (
        f"{FILE_REWRITE_SYSTEM_PROMPT}\n\n"
        f"Issue: {issue}\n\n"
        f"Approved plan:\n{plan_summary}\n\n"
        f"File: {rel_path}\n"
        f"Current content:\n{content_block}\n\n"
        f"New content for {rel_path}:"
    )


# -- Code tab: selection-scoped edit actions -------------------------------
#
# These back the "explain / refactor / fix / add tests..." actions in the Code
# tab (see assistant/edits/actions.py). Two output formats are used depending on
# the file's size, chosen by `actions._choose_strategy`:
#
#   - search/replace blocks for large files, so the model only emits what changes
#   - a whole-file rewrite for small ones, which weak models get right more often
#
# Sentinels mark the user's selection rather than sending it alone, so the model
# can see surrounding code but still knows exactly what to act on.
SELECTION_START = ">>> SELECTION START"
SELECTION_END = ">>> SELECTION END"

_ACTION_INSTRUCTIONS = {
    "explain": (
        "Explain what this code does, in plain language. Cover its purpose, how it works, and "
        "anything surprising, risky, or subtly wrong about it. Do not rewrite the code."
    ),
    "refactor": (
        "Refactor this code to be clearer and easier to maintain. Preserve its exact behaviour — "
        "same inputs must produce the same outputs. Do not add features."
    ),
    "optimise": (
        "Make this code faster or less memory-hungry without changing its observable behaviour. "
        "Prefer changes that matter (algorithmic complexity, redundant work, repeated I/O) over "
        "micro-optimisations. If it's already efficient, say so and change nothing."
    ),
    "fix": (
        "Find and fix the bug in this code. Change only what's needed for the fix. If you cannot "
        "identify an actual bug, say so and change nothing rather than inventing one."
    ),
    "tests": (
        "Write tests for this code. Cover the normal path, edge cases, and error handling. Match "
        "the testing style and framework already used in this project."
    ),
    "comments": (
        "Add comments and docstrings explaining anything non-obvious — why the code does what it "
        "does, not a restatement of what each line says. Do not change any executable code."
    ),
    "implement": (
        "Implement what the user asks for. Follow the conventions visible in the surrounding code."
    ),
}

_SEARCH_REPLACE_FORMAT = (
    "Output ONLY edit blocks in exactly this format, and nothing else — no explanation, no "
    "markdown fence:\n\n"
    "<<<<<<< SEARCH\n"
    "(the exact existing lines to replace, copied character for character)\n"
    "=======\n"
    "(the new lines to put in their place)\n"
    ">>>>>>> REPLACE\n\n"
    "Rules that matter:\n"
    "- The SEARCH section must match the current file EXACTLY, including indentation.\n"
    "- Include enough surrounding lines to make each SEARCH section unique in the file. If the "
    "same code appears twice, the edit will be rejected.\n"
    "- Emit one block per separate change. Blocks must not overlap.\n"
    "- Do not output the whole file."
)

_WHOLE_FILE_FORMAT = (
    "Output the COMPLETE new content of the file and nothing else — no explanation, no markdown "
    "fence, no commentary. Preserve every part of the file you aren't changing."
)


def build_edit_prompt(
    action: str,
    rel_path: str,
    file_content: str,
    *,
    instruction: str = "",
    has_selection: bool = False,
    context: str = "",
    strategy: str = "search_replace",
) -> str:
    """Builds the prompt for an edit action.

    `file_content` should already have the selection wrapped in the SELECTION
    sentinels (see `actions._mark_selection`) when `has_selection` is true.

    `strategy` picks the output format: "search_replace" or "whole_file". The
    caller decides, because it also has to know which parser to run on the reply.
    """
    task = _ACTION_INSTRUCTIONS.get(action, _ACTION_INSTRUCTIONS["implement"])
    output_format = _WHOLE_FILE_FORMAT if strategy == "whole_file" else _SEARCH_REPLACE_FORMAT

    parts = [
        "You are Shadow's coding assistant, editing a file in the user's own local project.",
        f"\nTask: {task}",
    ]
    if instruction.strip():
        parts.append(f"\nThe user's specific request: {instruction.strip()}")
    if has_selection:
        parts.append(
            f"\nApply this ONLY to the code between {SELECTION_START} and {SELECTION_END}. "
            "The rest of the file is shown for context — leave it unchanged, and do not include "
            "the selection markers in your output."
        )
    if context.strip():
        parts.append(f"\nRelevant context from elsewhere in the project:\n{context}")

    parts.append(f"\nFile: {rel_path}\nCurrent content:\n{file_content}")
    parts.append(f"\n{output_format}")
    return "\n".join(parts)


def build_explain_prompt(
    rel_path: str, code: str, *, instruction: str = "", context: str = "", is_selection: bool = False
) -> str:
    """Builds the prompt for the explain action, which never edits anything."""
    scope = "selected code from" if is_selection else "contents of"
    parts = [
        "You are Shadow's coding assistant. Explain code in the user's own local project clearly "
        "and concisely, in plain language. Point out bugs, risks, or surprising behaviour if you "
        "see any. Do not output a rewritten version of the code.",
    ]
    if instruction.strip():
        parts.append(f"\nThe user specifically asks: {instruction.strip()}")
    if context.strip():
        parts.append(f"\nRelevant context from elsewhere in the project:\n{context}")
    parts.append(f"\nThe {scope} {rel_path}:\n{code}")
    parts.append("\nExplanation:")
    return "\n".join(parts)


def build_tests_prompt(
    rel_path: str, file_content: str, test_path: str, *, instruction: str = "", context: str = ""
) -> str:
    """Builds the prompt for generating a new test file.

    Separate from `build_edit_prompt` because the output is a whole new file
    rather than an edit to an existing one — there's nothing to search against.
    """
    parts = [
        "You are Shadow's coding assistant, writing tests for a file in the user's own local "
        "project. Cover the normal path, edge cases, and error handling. Match the testing "
        "framework and style already used in this project.",
    ]
    if instruction.strip():
        parts.append(f"\nThe user specifically asks: {instruction.strip()}")
    if context.strip():
        parts.append(f"\nExisting tests and project context, to match style:\n{context}")
    parts.append(f"\nFile under test ({rel_path}):\n{file_content}")
    parts.append(
        f"\nOutput the COMPLETE content of {test_path} and nothing else — no explanation, no "
        "markdown fence."
    )
    return "\n".join(parts)


def build_patch_retry_prompt(original_prompt: str, previous_reply: str, error: str) -> str:
    """Re-asks after an edit couldn't be applied, telling the model what broke.

    One retry only (see `actions.propose_edit`); if the model can't produce
    applicable blocks the second time, the caller falls back to a whole-file
    rewrite rather than looping.
    """
    return (
        f"{original_prompt}\n\n"
        f"--- Your previous attempt could not be applied ---\n"
        f"You replied with:\n{previous_reply}\n\n"
        f"That failed with: {error}\n\n"
        "Try again. Copy the SEARCH sections from the file contents above character for "
        "character, and include enough surrounding lines that each one appears exactly once "
        "in the file."
    )
