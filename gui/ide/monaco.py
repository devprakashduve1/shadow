"""Monaco Editor embedded in a QWebEngineView, bridged to Python via QWebChannel.

The JS half lives in `vendor/monaco/monaco_host.html`; this module owns the
Python half. The division is deliberate: only a handful of functions cross the
boundary (see `MonacoBridge` for JS->Python and the `_js_*` calls for
Python->JS), which keeps the part that can't be unit-tested small.

Sequencing is the fiddly part. Three things must happen in order or the bridge
silently doesn't work:

1. `qwebchannel.js` is injected at DocumentCreation into the MainWorld — an
   isolated world can't see `qt.webChannelTransport`.
2. `setWebChannel()` happens before `load()`.
3. No Python->JS call that touches the editor may run before the page reports
   `ready()`; until then calls are queued in `_pending_ops`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QFile, QIODevice, QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MONACO_DIR = REPO_ROOT / "vendor" / "monaco"
HOST_HTML_NAME = "monaco_host.html"
DIFF_HOST_HTML_NAME = "monaco_diff_host.html"

# Same list scripts/fetch_monaco.py verifies; duplicated rather than imported
# because scripts/ isn't a package on sys.path at runtime.
_REQUIRED_ASSETS = ("vs/loader.js", "vs/editor/editor.main.js")

# Extension -> Monaco language id. Monaco can guess from a filename, but only
# via its own path-based API; doing it here keeps the JS surface smaller.
_LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".json": "json", ".jsonc": "json",
    ".html": "html", ".htm": "html", ".vue": "html",
    ".css": "css", ".scss": "scss", ".less": "less",
    ".md": "markdown", ".markdown": "markdown",
    ".yaml": "yaml", ".yml": "yaml",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".go": "go", ".rs": "rust", ".java": "java",
    ".kt": "kotlin", ".swift": "swift", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".xml": "xml", ".toml": "ini", ".ini": "ini", ".cfg": "ini",
    ".dockerfile": "dockerfile", ".graphql": "graphql", ".lua": "lua", ".r": "r",
}


def language_for(rel_path: str) -> str:
    """Maps a filename to a Monaco language id, defaulting to plaintext."""
    name = Path(rel_path).name.lower()
    # Extensionless files that are nonetheless well-known.
    if name in ("dockerfile", "containerfile"):
        return "dockerfile"
    if name in ("makefile", "gnumakefile"):
        return "plaintext"
    if name.startswith(".env"):
        return "ini"
    return _LANGUAGE_BY_SUFFIX.get(Path(name).suffix, "plaintext")


def monaco_assets_available(monaco_dir: Path = DEFAULT_MONACO_DIR) -> bool:
    """True if the vendored Monaco build and host page are both present."""
    if not (monaco_dir / HOST_HTML_NAME).is_file():
        return False
    return all((monaco_dir / rel).is_file() for rel in _REQUIRED_ASSETS)


def _read_qwebchannel_js() -> str:
    """Reads qwebchannel.js out of Qt's resource system.

    It is not shipped as a file on disk by PyQt6-WebEngine — it's compiled into
    the QtWebChannel library's resources. Importing QtWebChannel (done at module
    import above) is what registers the ":/qtwebchannel/..." prefix.
    """
    handle = QFile(":/qtwebchannel/qwebchannel.js")
    if not handle.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError(
            "Could not read ':/qtwebchannel/qwebchannel.js' from Qt's resources. "
            "Is PyQt6-WebEngine installed correctly?"
        )
    try:
        return bytes(handle.readAll()).decode("utf-8")
    finally:
        handle.close()


class MonacoBridge(QObject):
    """The object JS calls into. Every JS->Python entry point is a slot here.

    Must be kept alive by whoever registers it — `QWebChannel.registerObject`
    does not take ownership, so a bridge held only in a local variable gets
    garbage collected and JS silently sees `undefined`.
    """

    editor_ready = pyqtSignal()
    content_changed = pyqtSignal()
    cursor_moved = pyqtSignal(int, int)
    selection_changed = pyqtSignal(str, int, int)

    @pyqtSlot()
    def ready(self) -> None:
        self.editor_ready.emit()

    @pyqtSlot()
    def contentChanged(self) -> None:  # noqa: N802 - JS-facing name
        self.content_changed.emit()

    @pyqtSlot(int, int)
    def cursorMoved(self, line: int, column: int) -> None:  # noqa: N802
        self.cursor_moved.emit(line, column)

    @pyqtSlot(str, int, int)
    def selectionChanged(self, text: str, start_line: int, end_line: int) -> None:  # noqa: N802
        self.selection_changed.emit(text, start_line, end_line)



class _MonacoWebWidget(QWidget):
    """Shared QWebEngineView + QWebChannel plumbing for a Monaco-hosting page.

    Both the editor and the diff view need the same non-obvious setup sequence
    (see the module docstring), so it lives here once. Subclasses supply the host
    page's filename and a bridge object, and use `_run_js` without worrying about
    whether the page has finished loading.
    """

    ready = pyqtSignal()

    def __init__(self, host_html_name: str, bridge: QObject, monaco_dir: Path, parent=None):
        super().__init__(parent)
        self._monaco_dir = Path(monaco_dir)
        self._is_ready = False
        # Calls that arrived before the page reported ready; drained in
        # _on_page_ready.
        self._pending_ops: List[Callable[[], None]] = []
        self._view: Optional[QWebEngineView] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        host_html = self._monaco_dir / host_html_name
        if not self._assets_available(self._monaco_dir) or not host_html.is_file():
            layout.addWidget(self._build_missing_assets_notice())
            return

        self._view = QWebEngineView(self)
        settings = self._view.settings()
        # The host page is loaded from file:// and pulls vs/ from the same
        # directory. Remote access stays off — nothing here should reach the
        # network.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)

        # Order matters — see the module docstring.
        self._bridge = bridge  # attribute, not a local: registerObject won't own it
        self._bridge.setParent(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._inject_qwebchannel()

        layout.addWidget(self._view)
        self._view.load(QUrl.fromLocalFile(str(host_html.resolve())))

    @staticmethod
    def _assets_available(directory: Path) -> bool:
        """Whether the vendored JS this widget needs is present.

        Overridden by the terminal, which vendors xterm.js rather than Monaco.
        """
        return monaco_assets_available(directory)

    def _build_missing_assets_notice(self) -> QLabel:
        label = QLabel(
            "Monaco Editor assets aren't installed.\n\n"
            "Run this once, then reopen Shadow:\n\n"
            "    python scripts/fetch_vendor.py\n\n"
            f"(expected them under {self._monaco_dir})"
        )
        label.setWordWrap(True)
        label.setStyleSheet("padding: 24px; color: #cccccc;")
        return label

    def _inject_qwebchannel(self) -> None:
        script = QWebEngineScript()
        script.setName("qwebchannel")
        script.setSourceCode(_read_qwebchannel_js())
        # DocumentCreation so `QWebChannel` exists before the host page's inline
        # handshake script runs.
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        # MainWorld is mandatory: qt.webChannelTransport is not visible from an
        # isolated script world.
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        self._view.page().scripts().insert(script)

    def _on_page_ready(self) -> None:
        self._is_ready = True
        pending, self._pending_ops = self._pending_ops, []
        for op in pending:
            op()
        self.ready.emit()

    def _run_js(self, script: str) -> None:
        """Runs JS now, or queues it until the page reports ready."""
        if self._view is None:
            return
        if self._is_ready:
            self._view.page().runJavaScript(script)
        else:
            self._pending_ops.append(lambda: self._view.page().runJavaScript(script))

    def _fetch_js(self, script: str, callback: Callable[[str], None]) -> None:
        """Asynchronously evaluates `script`, passing its result to `callback`."""
        if self._view is None or not self._is_ready:
            callback("")
            return
        self._view.page().runJavaScript(script, lambda result: callback(result or ""))

    @property
    def is_available(self) -> bool:
        """False when Monaco assets are missing — the widget is then a notice."""
        return self._view is not None

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    def set_theme(self, theme: str) -> None:
        self._run_js(f"shadowSetTheme({json.dumps(theme)});")

    def shutdown(self) -> None:
        """Detaches the web channel before teardown.

        Without this, Qt can tear the page down while the channel still holds a
        reference to the bridge, which crashes at interpreter exit rather than
        raising anything catchable.
        """
        if self._view is not None:
            self._view.page().setWebChannel(None)
            self._view.page().deleteLater()
            self._view = None


class MonacoEditor(_MonacoWebWidget):
    """A single Monaco editor instance.

    Emits `content_changed` (debounced in JS) so a container can track dirty
    state, and `selection_changed` so AI actions know what the user highlighted.
    `ready` fires once the editor can accept content.
    """

    content_changed = pyqtSignal()
    cursor_moved = pyqtSignal(int, int)
    selection_changed = pyqtSignal(str, int, int)

    def __init__(self, monaco_dir: Path = DEFAULT_MONACO_DIR, parent=None):
        bridge = MonacoBridge()
        super().__init__(HOST_HTML_NAME, bridge, monaco_dir, parent)
        self._current_selection = ""
        bridge.editor_ready.connect(self._on_page_ready)
        bridge.content_changed.connect(self.content_changed)
        bridge.cursor_moved.connect(self.cursor_moved)
        bridge.selection_changed.connect(self._on_selection_changed)

    # -- state -------------------------------------------------------------

    @property
    def selected_text(self) -> str:
        """The user's current selection, tracked from JS selection events.

        Cached rather than fetched on demand because reading it would require a
        round trip through the async `runJavaScript`, which callers (AI actions)
        want synchronously at the moment they're invoked.
        """
        return self._current_selection

    def _on_selection_changed(self, text: str, start_line: int, end_line: int) -> None:
        self._current_selection = text
        self.selection_changed.emit(text, start_line, end_line)

    # -- Python -> JS ------------------------------------------------------

    def set_content(self, text: str, rel_path: str = "") -> None:
        """Replaces the buffer's content and sets syntax highlighting.

        `json.dumps` is what makes this safe — the text is interpolated into a
        JS expression, so newlines, quotes, backticks and unicode all have to be
        escaped. String concatenation here would break on the first apostrophe.
        """
        language = language_for(rel_path) if rel_path else "plaintext"
        self._run_js(f"shadowSetContent({json.dumps(text)}, {json.dumps(language)});")

    def get_content(self, callback: Callable[[str], None]) -> None:
        """Asynchronously fetches the buffer's content.

        Callback-based because `runJavaScript` is async — there is no way to read
        the editor's text synchronously from Python.
        """
        self._fetch_js("shadowGetContent();", callback)

    def set_read_only(self, read_only: bool) -> None:
        self._run_js(f"shadowSetReadOnly({json.dumps(bool(read_only))});")

    def reveal_line(self, line: int) -> None:
        self._run_js(f"shadowRevealLine({int(line)});")


class MonacoDiffBridge(QObject):
    """JS->Python entry points for the diff view."""

    editor_ready = pyqtSignal()
    proposed_edited = pyqtSignal()

    @pyqtSlot()
    def ready(self) -> None:
        self.editor_ready.emit()

    @pyqtSlot()
    def proposedEdited(self) -> None:  # noqa: N802 - JS-facing name
        self.proposed_edited.emit()


class MonacoDiffView(_MonacoWebWidget):
    """Side-by-side diff using Monaco's built-in diff editor.

    The right-hand (proposed) side stays editable, which is how "edit manually"
    works — the user adjusts the AI's version in place and `get_proposed()`
    returns what they actually want applied, not what the model produced.
    """

    proposed_edited = pyqtSignal()

    def __init__(self, monaco_dir: Path = DEFAULT_MONACO_DIR, parent=None):
        bridge = MonacoDiffBridge()
        super().__init__(DIFF_HOST_HTML_NAME, bridge, monaco_dir, parent)
        bridge.editor_ready.connect(self._on_page_ready)
        bridge.proposed_edited.connect(self.proposed_edited)

    def set_diff(self, original: str, proposed: str, rel_path: str = "") -> None:
        language = language_for(rel_path) if rel_path else "plaintext"
        self._run_js(
            "shadowSetDiff("
            f"{json.dumps(original)}, {json.dumps(proposed)}, {json.dumps(language)});"
        )

    def get_proposed(self, callback: Callable[[str], None]) -> None:
        """Fetches the proposed side, including any manual edits the user made."""
        self._fetch_js("shadowGetProposed();", callback)

    def set_proposed_editable(self, editable: bool) -> None:
        self._run_js(f"shadowSetProposedEditable({json.dumps(bool(editable))});")

