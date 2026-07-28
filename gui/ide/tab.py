"""The Code tab: a VS Code-style workspace over one git repository.

Assembles the pieces — repo bar, file explorer, Monaco editor tabs — and owns
the repository-level state they share. Later phases add the AI chat panel, diff
review, git panel, and terminal into the splitters already laid out here.

Git operations are serialized through a single in-flight worker: concurrent git
invocations on one repository contend for `index.lock` and fail confusingly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from assistant.edits.actions import EditAction
from assistant.git_ops import log as git_log
from assistant.knowledge.general import GeneralKnowledgeBank
from assistant.knowledge.indexer import KnowledgeBank
from assistant.knowledge.summaries import SUMMARY_ARCHITECTURE, get_summary, is_stale
from assistant.retrieval import retrieve_for_project
from assistant.manual_projects import ManualProjectRegistry
from config import settings
from database.json_store import EventStore

from assistant.project_files import MAX_EDITABLE_BYTES

from .ai_panel import AIPanel
from ..progress import Stage
from .editor_tabs import EditorTabs
from .git_panel import GitPanel
from .terminal import TerminalDock
from .file_tree import FileTreePanel
from .monaco import REPO_ROOT
from .repo_bar import KnowledgeBankState, RepoBar
from ..workers import ApplyWorker, ChatWorker, DevServerWorker, PlanWorker
from .workers import (
    ApplyEditWorker,
    DiscussionWorker,
    GeneralBankWorker,
    GitDiffWorker,
    ModelListWorker,
    ModelUnloadWorker,
    EditProposalWorker,
    ExplainWorker,
    GitCommandWorker,
    GitStatusWorker,
    KnowledgeIndexWorker,
    KnowledgeSummaryWorker,
)


# Question wording that signals "answer me, don't touch anything" — checked
# first since asking a question about a fix ("why does X break?") should never
# edit the file it's asking about.
_DISCUSSION_STARTERS = (
    "what", "why", "how", "when", "where", "who", "which", "explain", "describe",
    "does", "is", "are", "can", "could", "should", "would", "will",
)
# Wording that signals a change spanning more than one file — the safer default
# for these is a reviewable plan, not an in-place edit of whatever file happens
# to be open.
_PLAN_KEYWORDS = ("plan", "across the project", "across multiple files", "several files", "architecture")


def _classify_intent(prompt: str) -> str:
    """Guesses plan / discussion / code_fix from a free-form prompt.

    Replaces the old explicit mode picker: instead of asking the user to choose
    up front, infer intent from the prompt's own wording. Defaults to "code_fix"
    (edit the open file, or let the AI pick a target) since that's what most
    project-context prompts turn out to be ("fix the off-by-one", "add a
    --dry-run flag") — the diff-review step before anything is written is the
    real safety net, not this classification.
    """
    text = prompt.strip().lower()
    if any(keyword in text for keyword in _PLAN_KEYWORDS):
        return "plan"
    first_word = text.split(" ", 1)[0] if text else ""
    if text.endswith("?") or first_word in _DISCUSSION_STARTERS:
        return "discussion"
    return "code_fix"


def _resolve_vendor_dir(configured: str) -> Path:
    """Resolves `ide.monaco_dir` against the repo root, not the process CWD.

    Shadow can be launched from anywhere; a relative path in config should mean
    "relative to the Shadow checkout", which is what users will expect from the
    default value of `vendor/monaco`.
    """
    path = Path(configured).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


class IDETab(QWidget):
    """Code editing workspace for a selected repository."""

    def __init__(self, chat_engine, event_store: EventStore, shadow_root=None, parent=None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._event_store = event_store
        # Where the knowledge banks live. An explicit parameter rather than only a
        # settings lookup, because the constructor builds the general bank — doing
        # I/O to a path the caller can't influence makes this untestable and
        # surprising.
        self._shadow_root_override = str(shadow_root) if shadow_root else None
        self._project_path: Optional[Path] = None
        self._status_worker: Optional[GitStatusWorker] = None
        self._git_worker: Optional[GitCommandWorker] = None
        self._diff_worker: Optional[GitDiffWorker] = None

        # Same registry file the Coding Agent tab writes to, so browsing a folder
        # in either place makes it available in both.
        self._manual_projects = ManualProjectRegistry(event_store.base_dir / "manual_projects.json")

        self.repo_bar = RepoBar(self._manual_projects)
        self.file_tree = FileTreePanel()
        self.editor_tabs = EditorTabs(
            monaco_dir=_resolve_vendor_dir(settings.get("ide.monaco_dir", "vendor/monaco")),
            theme=settings.get("ide.theme", "vs-dark"),
            max_file_bytes=settings.get("ide.max_open_file_bytes", MAX_EDITABLE_BYTES),
        )
        self.status_label = QLabel("Open a repository to start editing.")
        self.status_label.setWordWrap(True)

        self.ai_panel = AIPanel(
            monaco_dir=_resolve_vendor_dir(settings.get("ide.monaco_dir", "vendor/monaco"))
        )

        self.git_panel = GitPanel()
        self.terminal = TerminalDock(
            xterm_dir=_resolve_vendor_dir(settings.get("ide.xterm_dir", "vendor/xterm"))
        )

        # AI worker state. Only one generation runs at a time — the local model
        # saturates the machine and concurrent edits to one file would race.
        self._explain_worker: Optional[ExplainWorker] = None
        self._proposal_worker: Optional[EditProposalWorker] = None
        self._apply_worker: Optional[ApplyEditWorker] = None
        self._current_proposal = None
        self._last_applied = None
        # Whole-project flow, carried over from the Coding Agent tab.
        self._plan_worker: Optional[PlanWorker] = None
        self._apply_plan_worker: Optional[ApplyWorker] = None
        self._dev_server_worker: Optional[DevServerWorker] = None
        self._dev_server_process = None
        self._current_plan = None
        self._current_issue = ""
        # Knowledge Bank. Indexing is static and fast; the prose summary is a
        # separate, slower, lazy step.
        self._index_worker: Optional[KnowledgeIndexWorker] = None
        self._summary_worker: Optional[KnowledgeSummaryWorker] = None
        self._model_worker: Optional[ModelListWorker] = None
        self._unload_worker: Optional[ModelUnloadWorker] = None
        self._chat_worker: Optional[ChatWorker] = None
        self._general_worker: Optional[GeneralBankWorker] = None
        self._discussion_worker: Optional[DiscussionWorker] = None

        self._wire_signals()
        self._build_layout()
        self._install_shortcuts()
        # The prompt box works with no repository open (general questions), so the
        # panel starts live rather than waiting for a project.
        self.ai_panel.set_project_open(True)
        # Asked for once at startup rather than per repository: which models are
        # installed is a property of the machine, not of the open project.
        self.refresh_models()
        # The general bank isn't tied to a repository, so it's kept current from
        # the moment the tab exists.
        self._refresh_general_bank_state()
        if settings.get("knowledge_bank.auto_index_on_open", True):
            self.build_general_bank()

    def _placeholder(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #777; padding: 12px;")
        return label

    def _wire_signals(self) -> None:
        self.repo_bar.repo_selected.connect(self.open_repository)
        self.repo_bar.branch_switch_requested.connect(self._switch_branch)
        self.repo_bar.branch_create_requested.connect(self._create_branch)
        self.repo_bar.refresh_requested.connect(self.refresh_git_status)
        self.repo_bar.build_repo_bank_requested.connect(lambda: self.build_knowledge_bank())
        self.repo_bar.build_general_bank_requested.connect(lambda: self.build_general_bank())

        self.file_tree.file_activated.connect(self.editor_tabs.open_file)
        self.file_tree.file_activated.connect(self.ai_panel.set_active_file)
        self.file_tree.file_deleted.connect(self._on_file_deleted)
        self.file_tree.file_renamed.connect(self._on_file_renamed)
        self.file_tree.error.connect(self._show_error)

        self.editor_tabs.status_message.connect(self.status_label.setText)
        self.editor_tabs.error.connect(self._show_error)
        # A save can change git status (and does, for a tracked file), so keep
        # the status read-out honest.
        self.editor_tabs.file_saved.connect(lambda _p: self.refresh_git_status())
        # Saved code means the index no longer matches disk.
        self.editor_tabs.file_saved.connect(lambda _p: self._refresh_knowledge_bank_state())
        self.editor_tabs.selection_changed.connect(self.ai_panel.set_selection)
        self.editor_tabs.tabs.currentChanged.connect(self._on_editor_tab_changed)

        self.ai_panel.action_requested.connect(self._run_action)
        self.ai_panel.accept_requested.connect(self._accept_proposal)
        self.ai_panel.reject_requested.connect(self._reject_proposal)
        self.ai_panel.stop_requested.connect(self._stop_ai)
        self.ai_panel.plan_requested.connect(self._plan_multi_file)
        self.ai_panel.apply_plan_requested.connect(self._apply_plan)
        self.ai_panel.dev_server_requested.connect(self._launch_dev_server)
        self.ai_panel.stop_dev_server_requested.connect(self._stop_dev_server)
        self.ai_panel.new_session_requested.connect(self._new_session)
        self.git_panel.stage_requested.connect(
            lambda paths: self._run_git_op("stage", {"paths": paths}, "Staging...")
        )
        self.git_panel.unstage_requested.connect(
            lambda paths: self._run_git_op("unstage", {"paths": paths}, "Unstaging...")
        )
        self.git_panel.discard_requested.connect(
            lambda paths: self._run_git_op("discard", {"paths": paths}, "Discarding...")
        )
        self.git_panel.commit_requested.connect(
            lambda message: self._run_git_op("commit", {"message": message}, "Committing...")
        )
        self.git_panel.stash_requested.connect(
            lambda: self._run_git_op("stash", {}, "Stashing...")
        )
        self.git_panel.diff_requested.connect(self._show_diff)
        self.git_panel.file_activated.connect(self.editor_tabs.open_file)
        self.git_panel.file_activated.connect(self.ai_panel.set_active_file)

        self.ai_panel.describe_project_requested.connect(self.describe_project)
        self.ai_panel.reindex_requested.connect(lambda: self.build_all_knowledge(force_full=True))
        self.ai_panel.refresh_models_requested.connect(self.refresh_models)
        self.ai_panel.unload_model_requested.connect(self.unload_models)
        self.ai_panel.build_kb_requested.connect(self.build_all_knowledge)
        self.ai_panel.build_general_kb_requested.connect(self.build_general_bank)
        self.ai_panel.general_chat_requested.connect(self._ask_general)
        self.ai_panel.prompt_submitted.connect(self._run_request)

    def _build_layout(self) -> None:
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.file_tree)
        left.addWidget(self.git_panel)
        left.setSizes([320, 420])

        center = QSplitter(Qt.Orientation.Vertical)
        center.addWidget(self.editor_tabs)
        center.addWidget(self.terminal)
        center.setSizes([560, 220])

        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(left)
        outer.addWidget(center)
        outer.addWidget(self.ai_panel)
        outer.setSizes([240, 720, 360])
        outer.setStretchFactor(1, 1)  # the editor takes the slack when resizing

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.repo_bar)
        # Stretch factor 1: the splitter absorbs all spare vertical space, so the
        # editor grows with the window instead of the bar and status label
        # sharing it out.
        root.addWidget(outer, 1)
        root.addWidget(self.status_label)

    def _install_shortcuts(self) -> None:
        # QKeySequence.Save maps to Cmd+S on macOS and Ctrl+S elsewhere.
        save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        save.activated.connect(self.editor_tabs.save_current)

    # -- repository lifecycle ----------------------------------------------

    def open_repository(self, project_path: str) -> None:
        """Switches the workspace to `project_path`.

        Refuses while unsaved buffers exist rather than silently discarding
        them — closing every tab is the first thing a switch does.
        """
        if self.editor_tabs.has_unsaved_changes():
            unsaved = ", ".join(self.editor_tabs.unsaved_paths())
            confirm = QMessageBox.question(
                self,
                "Unsaved changes",
                f"These files have unsaved changes:\n\n{unsaved}\n\n"
                "Switching repositories will close them and discard those edits. Continue?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if confirm != QMessageBox.StandardButton.Discard:
                self.repo_bar.set_project(str(self._project_path) if self._project_path else None)
                return

        # Resolved so it matches what ManualProjectRegistry stores — the repo
        # picker looks entries up by exact path string, and an unresolved path
        # (or one with a trailing slash) would silently fail to match.
        path = Path(project_path).expanduser().resolve()
        if not path.is_dir():
            self._show_error(f"{project_path} is not a folder.")
            return

        # Opening a repo makes it "recent" — otherwise a repo opened by any route
        # other than Browse wouldn't appear in the picker (and the picker would
        # still read "Select a repository..." while one was plainly open).
        self._manual_projects.add(str(path))

        self._project_path = path
        self.editor_tabs.set_project(str(path))
        self.file_tree.set_project(str(path))
        self.repo_bar.set_project(str(path))
        self.terminal.set_cwd(str(path))
        self.ai_panel.set_active_file(None)
        self.ai_panel.set_project_open(True)
        self.ai_panel.set_plan_available(False)
        self.ai_panel.return_to_chat()
        self.ai_panel.append_note(
            f"Opened {path.name}. Ask a question, describe a change, or use "
            "'Plan Multi-File Change' below for something spanning several files."
        )
        self._current_plan = None
        self._current_issue = ""
        self.status_label.setText(f"Opened {path}")
        self.refresh_git_status()
        self._refresh_knowledge_bank_state()
        if settings.get("knowledge_bank.auto_index_on_open", True):
            self.build_knowledge_bank()

    @property
    def project_path(self) -> Optional[Path]:
        return self._project_path

    # -- model discovery ---------------------------------------------------

    def refresh_models(self) -> None:
        """Asks Ollama which models are installed and repopulates the dropdown."""
        if self._model_worker is not None:
            return
        self._model_worker = ModelListWorker(
            settings.get("assistant.base_url", "http://localhost:11434"),
            include_remote=settings.get("assistant.allow_remote_models", False),
            fallback=settings.get("coding_agent.available_models", None),
            timeout_seconds=settings.get("assistant.model_list_timeout_seconds", 5.0),
        )
        self._model_worker.finished_ok.connect(self._on_models_listed)
        self._model_worker.start()

    def _on_models_listed(self, models) -> None:
        self._model_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._model_worker = None
        self.ai_panel.set_models(models)
        if not models:
            self.status_label.setText(
                "No models found — is `ollama serve` running? (`ollama pull gemma4`)"
            )

    def unload_models(self) -> None:
        """Releases Ollama's resident models, freeing their memory."""
        if self._unload_worker is not None:
            return
        self.ai_panel.set_status("Unloading the model...")
        self.ai_panel.set_progress_stage(Stage.WORKING, "Unloading the model...")
        self._unload_worker = ModelUnloadWorker(
            settings.get("assistant.base_url", "http://localhost:11434")
        )
        self._unload_worker.finished_ok.connect(self._on_models_unloaded)
        self._unload_worker.error.connect(self._on_unload_error)
        self._unload_worker.start()

    def _on_models_unloaded(self, unloaded) -> None:
        self._unload_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._unload_worker = None
        self.ai_panel.end_progress()
        if unloaded:
            self.ai_panel.set_status(
                f"Unloaded {', '.join(unloaded)} — the next request will reload it."
            )
        else:
            # Not an error: Ollama was reachable and simply had nothing resident,
            # which is the normal state before the first request of a session.
            self.ai_panel.set_status("No model was loaded — nothing to unload.")

    def _on_unload_error(self, message: str) -> None:
        self._unload_worker.wait()
        self._unload_worker = None
        self.ai_panel.end_progress()
        self.ai_panel.set_status(f"Could not unload: {message}")

    # -- Knowledge Bank ----------------------------------------------------

    def build_all_knowledge(self, force_full: bool = False) -> None:
        """Updates both banks — the repo's and the general one."""
        self.build_general_bank(force_full=force_full)
        if self._project_path is not None:
            self.build_knowledge_bank(force_full=force_full)

    def build_general_bank(self, force_full: bool = False) -> None:
        """Folds newly captured meetings and screen activity into the general bank.

        Independent of any repository: it describes the work around the code, so
        it's worth keeping current even with nothing open.
        """
        if self._general_worker is not None:
            return
        self.repo_bar.set_general_bank_state(KnowledgeBankState.INDEXING)
        self._general_worker = GeneralBankWorker(
            self._event_store,
            shadow_root=self._shadow_root(),
            force_full=force_full,
            text_export_dir=self._text_export_dir(),
        )
        self._general_worker.finished_ok.connect(self._on_general_bank_built)
        self._general_worker.error.connect(self._on_general_bank_error)
        self._general_worker.start()

    def _on_general_bank_built(self, digest) -> None:
        self._general_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._general_worker = None
        self._refresh_general_bank_state()
        if digest.is_empty:
            self.status_label.setText(
                "General Knowledge Bank is empty — it fills up from captured meetings and "
                "screen activity (see the Live Monitor tab)."
            )
        else:
            self.status_label.setText(
                f"General Knowledge Bank: {digest.event_count} events, "
                f"{len(digest.decisions)} decisions, {len(digest.action_items)} action items. "
                f"Readable copy: {self._text_export_dir() or '~/Desktop/Shadow/knowledgebank'}"
            )

    def _on_general_bank_error(self, message: str) -> None:
        self._general_worker.wait()
        self._general_worker = None
        self.repo_bar.set_general_bank_state(KnowledgeBankState.MISSING)
        self.status_label.setText(f"Could not update the General Knowledge Bank: {message}")

    def _refresh_general_bank_state(self) -> None:
        bank = GeneralKnowledgeBank(self._event_store, self._shadow_root())
        state = {
            "missing": KnowledgeBankState.MISSING,
            "stale": KnowledgeBankState.STALE,
            "ready": KnowledgeBankState.READY,
        }.get(bank.status(), KnowledgeBankState.UNKNOWN)
        digest = bank.load()
        detail = f"{digest.event_count} events" if not digest.is_empty else ""
        self.repo_bar.set_general_bank_state(state, detail)

    def _refresh_knowledge_bank_state(self) -> None:
        """Reads the bank's status from disk and shows it in the repo bar."""
        if self._project_path is None:
            self.repo_bar.set_knowledge_bank_state(KnowledgeBankState.UNKNOWN)
            return
        bank = KnowledgeBank(self._project_path, self._shadow_root())
        state = {
            "missing": KnowledgeBankState.MISSING,
            "stale": KnowledgeBankState.STALE,
            "ready": KnowledgeBankState.READY,
        }.get(bank.status(), KnowledgeBankState.UNKNOWN)
        detail = ""
        meta = bank.load_meta()
        if meta is not None and state != KnowledgeBankState.MISSING:
            detail = f"{meta.file_count} files"
        self.repo_bar.set_knowledge_bank_state(state, detail)

    def _text_export_dir(self) -> Optional[str]:
        """Where the readable .txt copies go — see assistant/knowledge/export.py."""
        configured = settings.get("knowledge_bank.text_export_dir", None)
        return str(Path(configured).expanduser()) if configured else None

    def _shadow_root(self) -> Optional[str]:
        if self._shadow_root_override:
            return self._shadow_root_override
        configured = settings.get("knowledge_bank.root", None)
        return str(Path(configured).expanduser()) if configured else None

    def build_knowledge_bank(self, force_full: bool = False) -> None:
        """Indexes the repository in the background.

        Reuses unchanged entries, so a repeat call on an unchanged repo is
        near-instant rather than a full rebuild.
        """
        if self._project_path is None or self._index_worker is not None:
            return
        self.repo_bar.set_knowledge_bank_state(KnowledgeBankState.INDEXING)
        self._index_worker = KnowledgeIndexWorker(
            str(self._project_path),
            shadow_root=self._shadow_root(),
            max_files=settings.get("knowledge_bank.max_files", 20_000),
            max_file_bytes=settings.get("knowledge_bank.max_file_bytes", 524_288),
            force_full=force_full,
            text_export_dir=self._text_export_dir(),
        )
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.finished_ok.connect(self._on_index_done)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()
        # Indexing doesn't set the panel busy (it doesn't block asking
        # questions), so the indicator is driven explicitly here. The file count
        # isn't known until the walk finishes, hence indeterminate to start.
        self.ai_panel.begin_progress("Indexing the repository...")

    def _on_index_progress(self, done: int, total: int) -> None:
        self.repo_bar.set_knowledge_bank_state(
            KnowledgeBankState.INDEXING, f"{done}/{total}"
        )
        # The one genuinely countable job in the app, so the only one that earns
        # a real percentage.
        self.ai_panel.set_counted_progress(done, total, "Indexing the repository...")

    def _on_index_done(self, result) -> None:
        self._index_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._index_worker = None
        self.ai_panel.end_progress()
        self._refresh_knowledge_bank_state()
        self.status_label.setText(
            f"Knowledge Bank: {result.summary} in {result.duration_seconds}s — readable copy in "
            f"{self._text_export_dir() or '~/Desktop/Shadow/knowledgebank'}"
        )

    def _on_index_error(self, message: str) -> None:
        self._index_worker.wait()
        self._index_worker = None
        self.ai_panel.end_progress()
        self.repo_bar.set_knowledge_bank_state(KnowledgeBankState.MISSING)
        self.status_label.setText(f"Could not index this repository: {message}")

    def describe_project(self) -> None:
        """Streams an LLM description of the project into the transcript.

        On demand rather than at index time: each summary costs tens of seconds
        on a local model, and most sessions never need one.
        """
        if self._project_path is None or self._summary_worker is not None:
            return
        bank = KnowledgeBank(self._project_path, self._shadow_root())
        if not bank.exists:
            self.ai_panel.set_status("Index the repository first (Knowledge Bank is empty).")
            return

        cached = get_summary(bank, SUMMARY_ARCHITECTURE)
        if cached.status == "ready" and cached.text and not is_stale(bank, SUMMARY_ARCHITECTURE):
            self.ai_panel.append_note(f"Shadow (cached): {cached.text}")
            self.ai_panel.set_status("Served from the Knowledge Bank cache.")
            return

        self.ai_panel.append_user("Describe this project")
        self.ai_panel.append_assistant_prefix()
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status("Writing a project description (this is slow the first time)...")
        self._summary_worker = KnowledgeSummaryWorker(
            str(self._project_path),
            SUMMARY_ARCHITECTURE,
            self._llm_cfg(),
            shadow_root=self._shadow_root(),
        )
        self._summary_worker.chunk_ready.connect(self.ai_panel.append_chunk)
        self._summary_worker.finished_ok.connect(self._on_summary_done)
        self._summary_worker.error.connect(self._on_summary_error)
        self._summary_worker.start()

    def _on_summary_done(self, entry) -> None:
        self._summary_worker.wait()
        self._summary_worker = None
        self.ai_panel.set_busy(False)
        self.ai_panel.append_note("")
        if entry.status == "failed":
            self.ai_panel.set_status(f"Could not write a description: {entry.error}")
        else:
            self.ai_panel.set_status("Description cached — future requests are instant.")

    def _on_summary_error(self, message: str) -> None:
        self._summary_worker.wait()
        self._summary_worker = None
        self.ai_panel.set_busy(False)
        self.ai_panel.set_status(f"Could not write a description: {message}")

    # -- git ---------------------------------------------------------------

    def refresh_git_status(self) -> None:
        if self._project_path is None or self._status_worker is not None:
            return
        self._status_worker = GitStatusWorker(str(self._project_path))
        self._status_worker.finished_ok.connect(self._on_git_status)
        self._status_worker.error.connect(self._on_git_status_error)
        self._status_worker.start()

    def _on_git_status(self, status) -> None:
        self._retire_status_worker()
        self.repo_bar.set_repo_status(status)
        self.git_panel.set_repo_status(status)
        if status.is_repo:
            self._refresh_log()

    def _on_git_status_error(self, message: str) -> None:
        self._retire_status_worker()
        self.status_label.setText(f"Could not read git status: {message}")

    def _retire_status_worker(self) -> None:
        if self._status_worker is not None:
            self._status_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
            self._status_worker = None

    def _refresh_log(self) -> None:
        """Reads recent history. Cheap enough to do inline — `git log -30` on a
        large repo is single-digit milliseconds, unlike a full status."""
        if self._project_path is None:
            return
        try:
            self.git_panel.set_log(git_log(self._project_path, limit=30))
        except Exception:
            pass  # history is informational; never let it break the status refresh

    def _show_diff(self, rel_path: str, staged: bool) -> None:
        if self._project_path is None or self._diff_worker is not None:
            return
        self._diff_worker = GitDiffWorker(str(self._project_path), rel_path, staged=staged)
        self._diff_worker.finished_ok.connect(self._on_diff_ready)
        self._diff_worker.error.connect(lambda msg: self._retire_diff_worker())
        self._diff_worker.start()

    def _on_diff_ready(self, rel_path: str, diff_text: str) -> None:
        self._retire_diff_worker()
        self.git_panel.set_diff(rel_path, diff_text)

    def _retire_diff_worker(self) -> None:
        if self._diff_worker is not None:
            self._diff_worker.wait()
            self._diff_worker = None

    def _switch_branch(self, branch: str) -> None:
        self._run_git_op("checkout", {"branch": branch}, f"Switching to {branch}...")

    def _create_branch(self, name: str) -> None:
        self._run_git_op("create_branch", {"name": name}, f"Creating {name}...")

    def _run_git_op(self, op: str, params: dict, message: str) -> None:
        if self._project_path is None:
            return
        if self._git_worker is not None:
            self.status_label.setText("A git operation is already running — try again shortly.")
            return
        self.status_label.setText(message)
        self.repo_bar.set_busy(True)
        self.git_panel.set_busy(True)
        self._git_worker = GitCommandWorker(str(self._project_path), op, params)
        self._git_worker.finished_ok.connect(self._on_git_op_done)
        self._git_worker.error.connect(self._on_git_op_error)
        self._git_worker.start()

    def _on_git_op_done(self, op: str, _result) -> None:
        self._retire_git_worker()
        self.status_label.setText(f"{op.replace('_', ' ').capitalize()} done.")
        if op == "commit":
            self.git_panel.clear_commit_message()
        if op in ("commit", "discard", "stash"):
            # These rewrite files on disk, so the index no longer matches.
            self._refresh_knowledge_bank_state()
        if op in ("discard", "stash"):
            # Both revert working-tree files under any open buffers.
            for rel_path in list(self.editor_tabs._states):
                self.editor_tabs.reload(rel_path)
        # checkout/create_branch rewrite files on disk, so open buffers and the
        # tree are both stale now.
        if op in ("checkout", "create_branch"):
            self.editor_tabs.close_all()
            self.file_tree.refresh()
        self.refresh_git_status()

    def _on_git_op_error(self, op: str, message: str) -> None:
        self._retire_git_worker()
        self.status_label.setText(f"{op.replace('_', ' ').capitalize()} failed: {message}")
        QMessageBox.warning(self, "Git", message)
        # Put the branch combo back to what's actually checked out.
        self.refresh_git_status()

    def _retire_git_worker(self) -> None:
        if self._git_worker is not None:
            self._git_worker.wait()
            self._git_worker = None
        self.repo_bar.set_busy(False)
        self.git_panel.set_busy(False)

    # -- file tree reactions -----------------------------------------------

    def _on_file_deleted(self, rel_path: str) -> None:
        self.editor_tabs.close_file(rel_path)
        self.refresh_git_status()

    def _on_file_renamed(self, old_rel: str, new_rel: str) -> None:
        # The buffer's path is now wrong; simplest correct move is to close it
        # and let the user reopen under the new name.
        self.editor_tabs.close_file(old_rel)
        self.status_label.setText(f"Renamed {old_rel} → {new_rel}")
        self.refresh_git_status()

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_editor_tab_changed(self, _index: int) -> None:
        self.ai_panel.set_active_file(self.editor_tabs.current_rel_path())
        self.ai_panel.set_selection(self.editor_tabs.current_selection())

    # -- AI actions --------------------------------------------------------

    def _llm_cfg(self) -> dict:
        return dict(
            base_url=settings.get("assistant.base_url", "http://localhost:11434"),
            model=self.ai_panel.model,
            timeout_seconds=settings.get("coding_agent.timeout_seconds", 600.0),
            # `keep_alive` deliberately absent: `streaming.stream_chat` resolves
            # it from `assistant.keep_model_loaded` itself. Threading it through
            # every wrapper would mean touching each of `propose_edit`'s internal
            # helpers too, and missing one would silently ignore the setting.
        )

    def _ai_busy(self) -> bool:
        return any(
            w is not None
            for w in (
                self._explain_worker,
                self._proposal_worker,
                self._apply_worker,
                self._plan_worker,
                self._apply_plan_worker,
                self._chat_worker,
                self._discussion_worker,
            )
        )

    def _reject_while_busy(self, what: str) -> bool:
        """Refuses `what` if a worker is still running, and says so.

        These guards used to `return` silently. The panel tracks its own busy
        flag, so the two could disagree — Send stayed enabled while this refused
        every click, with nothing on screen to explain why. Re-syncing the panel
        here makes the button reflect reality, and the message covers the gap
        until it does.
        """
        if not self._ai_busy():
            return False
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status(
            f"Still working on the previous request — press Stop to cancel it, then {what}."
        )
        return True

    def _no_project_for(self, what: str) -> bool:
        """Refuses `what` when it needs a repository and none is open."""
        if self._project_path is not None:
            return False
        self.ai_panel.set_status(f"Open a repository first — {what} needs one.")
        return True

    def _run_action(self, action: EditAction, instruction: str) -> None:
        if self._no_project_for(action.label.lower()) or self._reject_while_busy("try again"):
            return
        rel_path = self.editor_tabs.current_rel_path()
        # An empty rel_path is only workable for IMPLEMENT, where the model chooses
        # the target. "Refactor" with nothing selected has no subject.
        if not rel_path and action is not EditAction.IMPLEMENT:
            self.ai_panel.set_status(f"{action.label} needs a file open — pick one in the Explorer.")
            return

        request = self.ai_panel.build_request(str(self._project_path), action, instruction)
        # Lets _resolve_context blend in organizational knowledge alongside the
        # repository's own, from the configured bank location.
        request.event_store = self._event_store
        request.shadow_root = self._shadow_root()
        label = f"{action.label}: {instruction}" if instruction else action.label
        self.ai_panel.append_user(label)
        self.ai_panel.clear_prompt()
        self.ai_panel.set_busy(True)

        if action is EditAction.EXPLAIN:
            self._start_explain(request)
        else:
            self._start_proposal(request, action)

    def _start_explain(self, request) -> None:
        self.ai_panel.append_assistant_prefix()
        self.ai_panel.set_status("Thinking...")
        self._explain_worker = ExplainWorker(request, self._llm_cfg())
        self._explain_worker.chunk_ready.connect(self.ai_panel.append_chunk)
        self._explain_worker.finished_ok.connect(self._on_explain_done)
        self._explain_worker.error.connect(self._on_ai_error)
        self._explain_worker.start()

    def _on_explain_done(self) -> None:
        self._explain_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._explain_worker = None
        self.ai_panel.append_note("")
        self.ai_panel.set_status("")
        self.ai_panel.set_busy(False)

    def _start_proposal(self, request, action: EditAction) -> None:
        target = self.editor_tabs.current_rel_path()
        where = target if target else "a file the AI will choose"
        self.ai_panel.set_status(
            f"{action.label} on {where}: asking the model..."
        )
        self._proposal_worker = EditProposalWorker(request, self._llm_cfg())
        self._proposal_worker.finished_ok.connect(self._on_proposal_ready)
        self._proposal_worker.error.connect(self._on_ai_error)
        self._proposal_worker.start()

    def _on_proposal_ready(self, proposal) -> None:
        self._proposal_worker.wait()
        self._proposal_worker = None
        self.ai_panel.set_busy(False)

        if proposal.is_noop:
            self.ai_panel.append_note(
                f"Shadow: no changes proposed for {proposal.rel_path} — the model left it as is."
            )
            self.ai_panel.set_status("No changes proposed.")
            return

        self._current_proposal = proposal
        for warning in proposal.warnings:
            self.ai_panel.append_note(f"⚠ {warning}")
        # If the model picked the file itself, open it so the diff isn't reviewed
        # against a file the user can't see.
        if proposal.rel_path != self.editor_tabs.current_rel_path() and not proposal.is_new:
            self.editor_tabs.open_file(proposal.rel_path)
            self.ai_panel.set_active_file(proposal.rel_path)
        self.ai_panel.append_note(
            f"Shadow: proposed {proposal.stats.summary()} in {proposal.rel_path} — review it."
        )
        self.ai_panel.show_proposal(proposal)
        self.ai_panel.set_status("Review the diff, then Accept or Reject.")

    def _accept_proposal(self, final_content: str) -> None:
        """Writes the reviewed content.

        `final_content` comes from the diff editor's right-hand side, so it
        already includes any manual adjustment — never re-read from the proposal
        here or those edits would be silently dropped.
        """
        if self._current_proposal is None or self._project_path is None:
            return
        self.ai_panel.set_busy(True)
        # Writing a file, not calling a model — the default stage would
        # eventually blame a slow model load for a delay that can't be that.
        self.ai_panel.set_progress_stage(Stage.WORKING, "Applying the edit...")
        self.ai_panel.set_status("Applying...")
        self._apply_worker = ApplyEditWorker(
            self._current_proposal,
            str(self._project_path),
            override_content=final_content,
        )
        self._apply_worker.finished_ok.connect(self._on_edit_applied)
        self._apply_worker.stale.connect(self._on_edit_stale)
        self._apply_worker.error.connect(self._on_ai_error)
        self._apply_worker.start()

    def _on_edit_applied(self, applied) -> None:
        self._apply_worker.wait()
        self._apply_worker = None
        self._last_applied = applied
        self._current_proposal = None
        self.ai_panel.set_busy(False)
        self.ai_panel.return_to_chat()

        backup_note = (
            f" A backup is in {Path(applied.backup_path).parent}." if applied.backup_path else ""
        )
        self.ai_panel.append_note(f"Shadow: applied to {applied.rel_path}.{backup_note}")
        self.ai_panel.set_status(f"Applied to {applied.rel_path}.")

        # The file on disk no longer matches the open buffer, so pull it back in
        # rather than leaving a stale view that would overwrite the edit on save.
        self.editor_tabs.reload(applied.rel_path)
        self.file_tree.refresh()
        self.refresh_git_status()

    def _on_edit_stale(self, message: str) -> None:
        self._apply_worker.wait()
        self._apply_worker = None
        self._current_proposal = None
        self.ai_panel.set_busy(False)
        self.ai_panel.return_to_chat()
        self.ai_panel.append_note(f"Shadow: not applied — {message}")
        self.ai_panel.set_status("Not applied: the file changed. Re-run the action.")

    def _reject_proposal(self) -> None:
        self._current_proposal = None
        self.ai_panel.append_note("Shadow: proposal rejected — the file is unchanged.")
        self.ai_panel.set_status("Rejected.")

    def _stop_ai(self) -> None:
        stoppable = (self._explain_worker, self._proposal_worker, self._chat_worker,
                     self._discussion_worker)
        for worker in stoppable:
            if worker is not None:
                worker.stop()
        # A worker that has already finished leaves its reference behind if the
        # completion signal never landed, and `_ai_busy()` then refuses every
        # subsequent request. Clearing the finished ones here means Stop can
        # always get the panel back to a usable state.
        for name in ("_explain_worker", "_proposal_worker", "_apply_worker",
                     "_plan_worker", "_apply_plan_worker", "_chat_worker",
                     "_discussion_worker"):
            worker = getattr(self, name, None)
            if worker is not None and worker.isFinished():
                worker.wait()
                setattr(self, name, None)
        if self._ai_busy():
            self.ai_panel.set_status("Stopping...")
        else:
            self.ai_panel.set_busy(False)
            self.ai_panel.set_status("Stopped.")

    def _on_ai_error(self, message: str) -> None:
        for name in ("_explain_worker", "_proposal_worker", "_apply_worker",
                     "_plan_worker", "_apply_plan_worker", "_chat_worker",
                     "_discussion_worker"):
            worker = getattr(self, name, None)
            if worker is not None:
                worker.wait()
                setattr(self, name, None)
        self.ai_panel.set_busy(False)
        self.ai_panel.append_note(f"Shadow: {message}")
        self.ai_panel.set_status("Error — see the transcript.")

    def _run_request(self, prompt: str) -> None:
        """Routes a prompt to whichever of the three project-context paths fits.

        The three stay deliberately different code paths, not one prompt with a
        preamble: Plan produces a reviewable multi-file plan and can write to a new
        branch, Discussion only ever reads, and Code Fix edits the open file behind
        a diff a user must accept before anything is written. `_classify_intent`
        picks between them from the prompt's own wording, replacing the explicit
        mode picker that used to make this choice.
        """
        if self._reject_while_busy("send it again"):
            return
        intent = _classify_intent(prompt)
        if intent == "plan":
            self._plan_multi_file(prompt)
        elif intent == "discussion":
            self._discuss(prompt)
        else:
            # No open file is fine: propose_edit resolves a target from the
            # Knowledge Bank and reports which file it picked.
            self._run_action(EditAction.IMPLEMENT, prompt)

    def _discuss(self, question: str) -> None:
        """Answers a question about the project, grounded in both banks, editing nothing."""
        if self._no_project_for("discussing the code") or self._reject_while_busy("ask again"):
            return
        request = self.ai_panel.build_request(
            str(self._project_path), EditAction.EXPLAIN, question
        )
        request.event_store = self._event_store
        request.shadow_root = self._shadow_root()

        self.ai_panel.append_user(question)
        self.ai_panel.append_assistant_prefix()
        self.ai_panel.clear_prompt()
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status("Thinking (nothing will be edited)...")

        self._discussion_worker = DiscussionWorker(request, self._llm_cfg())
        self._discussion_worker.chunk_ready.connect(self.ai_panel.append_chunk)
        self._discussion_worker.finished_ok.connect(self._on_discussion_done)
        self._discussion_worker.error.connect(self._on_ai_error)
        self._discussion_worker.start()

    def _on_discussion_done(self) -> None:
        self._discussion_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._discussion_worker = None
        self.ai_panel.append_note("")
        self.ai_panel.set_status("")
        self.ai_panel.set_busy(False)

    def _ask_general(self, question: str) -> None:
        """Answers a question with no project context at all.

        Used when no file is open: rather than the panel being inert until a
        repository is picked, the model answers from its own knowledge. Reuses
        `ChatEngine.ask(free_chat=True)`, which skips retrieval entirely — see
        that method for why retrieved screen-OCR context is the wrong thing to
        ground a general coding question in.
        """
        if self._reject_while_busy("ask again"):
            return
        self.ai_panel.append_user(question)
        self.ai_panel.append_assistant_prefix()
        self.ai_panel.clear_prompt()
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status("Thinking...")

        self._chat_worker = ChatWorker(
            self._chat_engine,
            question,
            project=self._project_path.name if self._project_path else None,
            model=self.ai_panel.model,
            free_chat=True,
        )
        self._chat_worker.chunk_ready.connect(self.ai_panel.append_chunk)
        self._chat_worker.finished_ok.connect(self._on_general_answer_done)
        self._chat_worker.error.connect(self._on_ai_error)
        self._chat_worker.start()

    def _on_general_answer_done(self, _citations) -> None:
        self._chat_worker.wait()  # see gui/dashboard.py's _StreamingChatMixin note
        self._chat_worker = None
        self.ai_panel.append_note("")
        self.ai_panel.set_status("")
        self.ai_panel.set_busy(False)

    def _stop_general(self) -> None:
        if self._chat_worker is not None:
            self._chat_worker.stop()

    # -- whole-project actions (carried over from the Coding Agent tab) -----

    def _plan_multi_file(self, issue: str) -> None:
        """Plans a change spanning several files.

        Distinct from the single-file actions above: this one produces a plan for
        review, and applying it goes through `coding_agent.apply_plan`, which
        writes to a fresh git branch and does require a clean tree. Kept as a
        separate path rather than merged, because that stricter safety model is
        appropriate for a multi-file rewrite and wrong for an in-place edit.
        """
        if self._no_project_for("planning a change") or self._reject_while_busy("plan it again"):
            return
        self._current_issue = issue
        self.ai_panel.append_user(f"Plan: {issue}")
        self.ai_panel.clear_prompt()
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status("Planning (reading project files)...")

        captured_context, _ = retrieve_for_project(
            self._event_store, self._project_path.name, manual_registry=self._manual_projects
        )
        plan_cfg = dict(
            base_url=settings.get("assistant.base_url", "http://localhost:11434"),
            model=self.ai_panel.model,
            timeout_seconds=settings.get("coding_agent.timeout_seconds", 600.0),
            max_relevant_files=settings.get("coding_agent.max_relevant_files", 6),
            max_file_bytes=settings.get("coding_agent.max_file_bytes", 6000),
        )
        self._plan_worker = PlanWorker(
            str(self._project_path), issue, captured_context, plan_cfg
        )
        self._plan_worker.finished_ok.connect(self._on_plan_ready)
        self._plan_worker.error.connect(self._on_ai_error)
        self._plan_worker.start()

    def _on_plan_ready(self, plan) -> None:
        self._plan_worker.wait()
        self._plan_worker = None
        self._current_plan = plan
        self.ai_panel.set_busy(False)

        self.ai_panel.append_note(f"--- Proposed plan ---\n{plan.summary}")
        if plan.files:
            files = "\n".join(f"  - {'[NEW] ' if f.is_new else ''}{f.path}" for f in plan.files)
            self.ai_panel.append_note(f"Files:\n{files}")
            self.ai_panel.set_plan_available(True)
            self.ai_panel.set_status('Plan ready — "Apply Plan" writes it to a new git branch.')
        else:
            self.ai_panel.set_status("The plan didn't name any files — try describing it differently.")

    def _apply_plan(self) -> None:
        if self._project_path is None or self._current_plan is None or self._ai_busy():
            return
        self.ai_panel.set_busy(True)
        self.ai_panel.set_status("Applying plan on a new branch...")
        ollama_cfg = dict(
            base_url=settings.get("assistant.base_url", "http://localhost:11434"),
            model=self.ai_panel.model,
            timeout_seconds=settings.get("coding_agent.timeout_seconds", 600.0),
        )
        self._apply_plan_worker = ApplyWorker(
            str(self._project_path), self._current_plan, self._current_issue, ollama_cfg
        )
        self._apply_plan_worker.finished_ok.connect(self._on_plan_applied)
        self._apply_plan_worker.error.connect(self._on_ai_error)
        self._apply_plan_worker.start()

    def _on_plan_applied(self, result) -> None:
        self._apply_plan_worker.wait()
        self._apply_plan_worker = None
        self._current_plan = None
        self.ai_panel.set_busy(False)
        self.ai_panel.set_plan_available(False)

        files = "\n".join(f"  - {path}" for path in result.changed_files)
        self.ai_panel.append_note(f"--- Applied on branch {result.branch} ---\n{files}")
        self.ai_panel.set_status(f'Committed on "{result.branch}".')
        # apply_plan switched branches and rewrote files under any open buffers.
        self.editor_tabs.close_all()
        self.file_tree.refresh()
        self.refresh_git_status()

    def _launch_dev_server(self) -> None:
        if self._project_path is None or self._dev_server_worker is not None:
            return
        self.ai_panel.set_status("Detecting and starting the dev server...")
        self._dev_server_worker = DevServerWorker(
            str(self._project_path),
            timeout_seconds=settings.get("coding_agent.dev_server_timeout_seconds", 20),
        )
        self._dev_server_worker.finished_ok.connect(self._on_dev_server_started)
        self._dev_server_worker.no_start_command.connect(self._on_no_start_command)
        self._dev_server_worker.error.connect(self._on_ai_error)
        self._dev_server_worker.start()

    def _on_dev_server_started(self, result) -> None:
        self._dev_server_worker.wait()
        self._dev_server_worker = None
        self._dev_server_process = result.process
        self.ai_panel.set_dev_server_running(True)
        where = result.url or f"(no URL detected — see {result.log_path})"
        self.ai_panel.append_note(f"Shadow: dev server running at {where}")
        self.ai_panel.set_status(f"Dev server running — log: {result.log_path}")

    def _on_no_start_command(self) -> None:
        self._dev_server_worker.wait()
        self._dev_server_worker = None
        self.ai_panel.set_status(
            "No dev-server command found (looked for a package.json dev/start/serve script)."
        )

    def _stop_dev_server(self) -> None:
        if self._dev_server_process is not None and self._dev_server_process.poll() is None:
            self._dev_server_process.terminate()
        self._dev_server_process = None
        self.ai_panel.set_dev_server_running(False)
        self.ai_panel.set_status("Dev server stopped.")

    def _new_session(self) -> None:
        """Clears the transcript, saved chat history, and any in-progress plan."""
        if self._project_path is None or self._ai_busy():
            return
        self.ai_panel.clear_transcript()
        self._chat_engine.new_session(project=self._project_path.name)
        self._current_plan = None
        self._current_issue = ""
        self.ai_panel.set_plan_available(False)
        self.ai_panel.set_status("Started a new session — transcript and history cleared.")

    # -- teardown ----------------------------------------------------------

    def shutdown(self) -> None:
        """Called by MainWindow.closeEvent — see the other tabs' shutdown()."""
        if self._status_worker is not None:
            self._status_worker.wait(2000)
            self._status_worker = None
        if self._git_worker is not None:
            self._git_worker.wait(5000)
            self._git_worker = None
        self._retire_diff_worker()
        for name in ("_explain_worker", "_proposal_worker", "_apply_worker",
                     "_plan_worker", "_apply_plan_worker", "_dev_server_worker",
                     "_index_worker", "_summary_worker", "_model_worker",
                     "_chat_worker", "_general_worker", "_discussion_worker",
                     "_unload_worker"):
            worker = getattr(self, name, None)
            if worker is not None:
                if hasattr(worker, "stop"):
                    worker.stop()
                worker.wait(3000)
                setattr(self, name, None)
        if self._dev_server_process is not None and self._dev_server_process.poll() is None:
            self._dev_server_process.terminate()
        self.terminal.shutdown()
        self.ai_panel.shutdown()
        self.editor_tabs.shutdown()
