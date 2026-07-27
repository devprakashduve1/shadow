# Shadow

A desktop productivity/accessibility app that combines hand-gesture mouse control,
desktop screen monitoring with OCR, and speech-to-text transcription into a single
PyQt6 dashboard with searchable logs.

## Contents

- [Features](#features)
- [Project layout](#project-layout)
- [Dependencies](#dependencies)
- [Setup](#setup)
  - [macOS permissions checklist](#macos-permissions-checklist)
  - [Other macOS notes](#other-macos-notes)
- [Running](#running)
  - [Live Monitor controls](#live-monitor-controls)
  - [Session files](#session-files)
  - [Summarize (local LLM)](#summarize-local-llm)
  - [AI Assistant (chat over your captured activity)](#ai-assistant-chat-over-your-captured-activity)
  - [Code (VS Code-style editor with AI, git, and a Knowledge Bank)](#code-vs-code-style-editor-with-ai-git-and-a-knowledge-bank)
  - [Plan a fix, implement it, verify in Chrome](#plan-a-fix-implement-it-verify-in-chrome)
  - [Screen capture exclusions](#screen-capture-exclusions)
  - [Spell check (system-wide)](#spell-check-system-wide)
- [Configuration](#configuration)
- [Structured events and redaction (JSON files, no database)](#structured-events-and-redaction-json-files-no-database)
- [Testing](#testing)
- [Gesture vocabulary](#gesture-vocabulary)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)

## Features

- Hand-gesture mouse control (webcam + MediaPipe + pynput)
- Desktop screen capture with change detection (mss)
- OCR text extraction from screen captures (EasyOCR or Tesseract)
- System/mic audio capture and local speech-to-text (faster-whisper)
- Auto voice capture + transcription when a Slack huddle or Google Meet call is detected (macOS)
- Date-partitioned JSON + plain-text event logging (`~/Desktop/Shadow/YYYY-MM-DD/`):
  one consolidated file for all screen OCR text, and a fresh file per detected meeting
  for voice transcripts (see [Session files](#session-files))
- Keyword/date/source search over logged OCR + transcript entries, with CSV export
- One-click summarization of search results via a local Ollama model (default: `gemma4`) — see [Summarize](#summarize-local-llm)
- Every logged entry is also redacted, classified (error/meeting/decision/task/code/website/note),
  and appended as a structured event to a local JSON/JSONL file (no database) — see
  [Structured events and redaction (JSON files, no database)](#structured-events-and-redaction-json-files-no-database)
- Streaming AI chat assistant over your own captured history, with source citations and daily
  suggested questions, powered by the same local Ollama model — see
  [AI Assistant](#ai-assistant-chat-over-your-captured-activity)
- Code tab: a VS Code-style workspace over one git repository — Monaco editor, file explorer,
  git panel, real terminal, and AI actions that edit files behind a diff you review. Auto-detects
  code projects from ticket keys (e.g. `PROJ-1139`) in your
  captured activity, or browse to any folder directly, and chat scoped to just one
  project's history — see [Code](#code-vs-code-style-editor-with-ai-git-and-a-knowledge-bank)
- For a manually-browsed project: describe an issue, review an AI-written plan, approve it to
  have the change actually implemented on a new git branch, then launch and verify it in Chrome
  — see [Plan a fix, implement it, verify in Chrome](#plan-a-fix-implement-it-verify-in-chrome)
- System-wide spelling + grammar suggestion popups as you type (pyspellchecker +
  local LanguageTool), enabled by default with no exclusions — see
  [Spell check](#spell-check-system-wide) for important safety notes
- Unified PyQt6 dashboard: live camera/screen preview (toggleable), module toggles, search tab

## Project layout

```
shadow/
  camera/     webcam capture (OpenCV)
  gesture/    MediaPipe hand tracking + gesture classification
  mouse/      pynput-based mouse control
  screen/     mss-based screen capture + change detection
  ocr/        EasyOCR / Tesseract wrapper
  audio/      sounddevice mic/loopback capture
  speech/     faster-whisper transcription
  callwatch/  detects an active Slack huddle / Google Meet call (macOS)
  spellcheck/ offline spelling (pyspellchecker) + grammar (language_tool_python) checks
  logger/     date-partitioned event logging
  search/     search over logged events
  summarize/  local-LLM (Ollama) summarization of search results
  events/     typed event schema, redaction, and rule-based classification (see below)
  database/   JSON/JSONL-file-backed EventStore (structured events, chat history, suggested questions — no database)
  assistant/  streaming chat engine: retrieval + prompts + Ollama client + citations + project
              scoping + the Code tab (editor, git, terminal, AI edits, Knowledge Bank)
  gui/        PyQt6 dashboard + background workers
  config/     YAML settings loader
  tests/      pytest suite for events/, database/, assistant/, logger/
  models/     local model weights (gitignored)
  assets/     icons/static assets
  output/     logs, exports, events/ (gitignored)
  main.py     app entry point
```

## Dependencies

Everything below is pinned/floored in `requirements.txt` and installed by
`pip install -r requirements.txt` (see [Setup](#setup)). "Used in" points at
the one or two modules that actually import each package, so you can trace
exactly what breaks if a package is missing/misbehaving.

| Package | Version | Used in | Purpose |
|---|---|---|---|
| `opencv-python` (`cv2`) | `>=4.9.0` | `camera/camera_module.py`, `gesture/gesture_recognizer.py`, `gui/dashboard.py` | Webcam capture (`VideoCapture`) and frame color conversion (BGR↔RGB, mirror flip) |
| `mediapipe` | `==0.10.14` (pinned) | `gesture/gesture_recognizer.py` | Hand landmark detection/tracking. Pinned because `>=0.10.30` dropped the legacy `mp.solutions` API this module uses |
| `pyautogui` | `>=0.9.54` | `mouse/mouse_controller.py` | Only used for `pyautogui.size()` — detecting the real screen resolution to map gesture coordinates onto |
| `pynput` | `==1.8.2` (pinned) | `mouse/mouse_controller.py`, `gui/workers.py`, `spellcheck/_pynput_darwin_patch.py` | Synthesizing real mouse move/click/scroll events, and system-wide mouse-click/keyboard listeners (screen-capture trigger, spell check). Pinned because `_pynput_darwin_patch.py` patches this exact version's internals — see [Known limitations](#known-limitations) |
| `mss` | `>=9.0.1` | `screen/screen_capture.py` | Cross-platform, fast screenshot capture |
| `pytesseract` | `>=0.3.10` | `ocr/ocr_engine.py` | Optional OCR engine (wraps the system Tesseract binary) — alternative to the default EasyOCR, set via `ocr.engine: tesseract` |
| `easyocr` | `>=1.7.1` | `ocr/ocr_engine.py` | Default OCR engine — deep-learning-based text recognition, no external binary required |
| `faster-whisper` | `>=1.0.1` | `speech/speech_to_text.py` | Local speech-to-text transcription for meeting audio |
| `sounddevice` | `>=0.4.6` | `audio/audio_capture.py` | Microphone/loopback audio capture |
| `PyQt6` | `>=6.6.1` | `main.py`, `gui/dashboard.py`, `gui/workers.py` | The GUI framework — main window, widgets, and the `QThread` workers that keep every pipeline off the GUI thread |
| `numpy` | `>=1.26.4` | `ocr/`, `camera/`, `speech/`, `gesture/`, `audio/`, `screen/`, `gui/` | Shared array representation for frames/audio passed between nearly every pipeline |
| `PyYAML` | `>=6.0.1` | `config/settings.py` | Parses `config/default_settings.yaml` and the optional local override |
| `pyspellchecker` | `>=0.8.1` | `spellcheck/spell_checker.py` | Offline, word-level spelling suggestions (system-wide spell check) |
| `language_tool_python` | `>=2.7.0` | `spellcheck/grammar_checker.py` | Sentence-level grammar checking against a local LanguageTool server — requires a JRE, see [Spell check](#spell-check-system-wide) |
| `pandas` | `>=2.2.1` | *(none currently)* | Not imported directly anywhere in this codebase today — present in `requirements.txt` but unused by app code, distinct from every other entry here |
| `Pillow` | `>=10.2.0` | *(none currently)* | Not imported directly either — pulled in transitively as a hard dependency of `easyocr`/`torchvision`, listed explicitly to pin a floor version |
| `pytest` | `>=8.0.0` | `tests/` | Test suite for `events/`, `database/`, `assistant/`, and the `logger/`↔`EventStore` wiring — see [Testing](#testing) |

`events/`, `database/`, and `assistant/` (the structured-event/chat-assistant layer) add **no new dependencies** — `json`, `pathlib`, and `urllib.request` are Python stdlib, matching the existing "no extra package for the Ollama client" approach `summarize/` already uses. There's no database at all: `database/json_store.py` reads/writes plain JSON/JSONL files, same as `logger/data_logger.py` already does for the raw OCR/speech logs.

Beyond `requirements.txt`, three things are **not pip packages** and must be
installed/running separately — each is optional (only its own feature
degrades without it) and covered in more detail in [Setup](#setup):

| Tool | Needed for | Install |
|---|---|---|
| Java (JRE) | Grammar checking (`language_tool_python`) | `brew install openjdk` |
| Tesseract | OCR, only if you set `ocr.engine: tesseract` instead of the default EasyOCR | `brew install tesseract` |
| [Ollama](https://ollama.com) | Search-tab "Summarize results" | `brew install ollama` + `ollama pull gemma4` |

## Setup

```bash
cd shadow
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

That installs everything needed for camera/gesture, screen/OCR, meeting audio
transcription, and offline spelling checks.

If you plan to use the **Code** tab, also fetch its editor and terminal
JavaScript once — Monaco and xterm.js are ~28MB combined and aren't committed to
this repo:

```bash
python scripts/fetch_vendor.py
```

Both downloads are pinned by version and sha256. Skipping this leaves every other
feature working; the Code tab's editor and terminal panels just show these
instructions instead. See
[Code](#code-vs-code-style-editor-with-ai-git-and-a-knowledge-bank).

A few more things install separately because they're system-level, not pip
packages — see below:

1. **Java** (only needed for grammar checking, part of spell check):
   ```bash
   brew install openjdk
   ```
   Without this, grammar checking degrades gracefully — spelling-only checks
   keep working, you just won't get grammar suggestions (see
   `spellcheck.grammar_enabled` in `config/default_settings.yaml` to disable
   grammar checking outright and skip this step). The first time grammar
   checking actually runs, `language_tool_python` downloads a ~250MB
   LanguageTool bundle (cached afterward).
2. **Tesseract**, only if you want it instead of the default EasyOCR engine:
   ```bash
   brew install tesseract
   ```
   Then set `ocr.tesseract_cmd` in `config/default_settings.yaml` to its path
   and `ocr.engine: tesseract`.
3. **Ollama**, only for the Search tab's "Summarize results" feature:
   ```bash
   brew install ollama
   ollama pull gemma4
   ```
   Without this running, summarization just fails with a one-line error in
   the Search tab — every other feature works fine without it. See
   [Summarize (local LLM)](#summarize-local-llm).

### macOS permissions checklist

Nearly every feature here needs its own macOS privacy permission grant —
**System Settings > Privacy & Security**, then:

| Permission | Needed for |
|---|---|
| Camera | Hand-gesture mouse control |
| Screen Recording | Screen capture + OCR |
| Microphone | Meeting voice capture/transcription |
| Automation (control Google Chrome / Safari / System Events) | Call detection, window-switch tracking, screen-capture exclusion rules |
| Input Monitoring | Spell check (system-wide keystroke watching) |

Grant these to whichever app actually launches `python main.py` (Terminal,
iTerm, your IDE, etc.) — if a permission is missing, the affected feature
degrades or silently does nothing rather than crashing, so if something isn't
working, check this list first.

### Other macOS notes

- macOS has no native system-audio loopback input. To capture system audio
  (not just the mic), install [BlackHole](https://github.com/ExistentialAudio/BlackHole)
  and select it as the audio input device in `config/default_settings.yaml`
  (`audio.device_index`). Pair it with a Multi-Output Device in Audio MIDI Setup
  if you also want to hear the audio while it's being captured.

## Running

```bash
python main.py
```

This opens the dashboard with three tabs:

- **Live Monitor** — start/stop the camera+gesture pipeline (optionally driving
  the real mouse), the screen+OCR pipeline (optionally logging extracted text,
  and running automatically from launch), and the Slack/Google Meet call
  auto-capture (optionally transcribing voice).
- **Search** — filter logged OCR/speech entries by keyword, source, and date
  range, export results to CSV, and summarize the current results with a
  local LLM (see [Summarize](#summarize-local-llm)).
- **Assistant** — chat with a local LLM over your own captured activity, with
  streaming answers, source citations, and daily suggested questions (see
  [AI Assistant](#ai-assistant-chat-over-your-captured-activity)).

A small **●/○ status indicator** in the window's bottom status bar (the
"consent badge") always shows whether screen+OCR and/or mic capture are
currently active, regardless of which tab is open.

### Live Monitor controls

| Control                                              | Effect                                                                 |
|-------------------------------------------------------|-------------------------------------------------------------------------|
| Start/Stop Camera/Gesture                              | starts/stops the webcam + hand-tracking pipeline                        |
| Enable mouse control                                   | lets recognized gestures drive the real system mouse (see below)        |
| Disable video preview *(checked by default)*           | keeps gesture tracking running but stops rendering the camera feed — check it off if you want to see the camera preview for debugging |
| Enable screen capture *(off by default, auto-toggled)* | starts/stops periodic screen capture + change detection. Off at launch — automatically checked the moment a Slack/Meet call is detected, and automatically unchecked again when the call ends, so screen context lines up with meeting audio. You can still toggle it manually any other time. |
| Enable OCR on change *(checked by default)*             | runs OCR (and logs the text) whenever the captured screen changes — independent of the screen-capture checkbox above, so you can capture frames without OCR'ing them |
| Capture screen on every mouse click *(off by default)*  | when on (and OCR is enabled), every system-wide mouse click forces an immediate screen capture + OCR pass instead of waiting for the next `screen.capture_interval_seconds` tick — still skipped while the frontmost window/tab is excluded (see `screen.excluded_apps` / `excluded_domains` below). Requires macOS Accessibility permission for the click listener, same as gesture mouse control. |
| Enable call detection *(checked by default)*            | starts/stops the background watcher for an active Slack huddle or Google Meet call — a toast popup fires in the top-right corner the moment any call/huddle/meeting is first detected |
| Enable voice transcription *(checked by default)*       | independent of call detection above — when off, calls are still detected (status label updates) but the mic is never recorded/transcribed; toggling this off mid-call stops an in-progress recording immediately (see [Known limitations](#known-limitations)) |
| Enable spell-check popups *(running by default, no exclusions)* | watches keystrokes **system-wide** (any app, always) and pops up spelling suggestions — read [Spell check](#spell-check-system-wide) for safety notes |

### Session files

Every file this app writes is named `Shadow_*.jsonl` (+ a matching `.txt`).
The **screen** and **speech** channels (`logger/data_logger.py`) are always
kept in completely separate files from each other, but each follows its own
policy for how far it splits:

- **Screen (OCR): `Shadow_screen.jsonl` / `.txt`** — one fixed pair for the
  whole day, regardless of which window/app was frontmost or how many times
  you switched between them. Screen text is never fragmented across files.
- **Speech (voice transcripts): `Shadow_meeting_<source>_<timestamp>.jsonl`
  / `.txt`** — a fresh file pair per detected meeting. Every time a new Slack
  huddle or Google Meet call is detected, `CallVoiceCaptureWorker` calls
  `logger.start_session("speech", f"meeting_{source}")`, so each call's
  transcript lives in its own file rather than accumulating into one
  ever-growing speech log.

**Duplicate suppression**: if a channel's next entry has the exact same text
as the immediately preceding one logged on that channel (e.g. OCR re-reading
an unchanged screen), it's silently skipped — `log_ocr()`/`log_transcript()`
return `None` in that case instead of writing anything.

**Title**: every screen-OCR entry also gets a `title` — the topmost line of
text detected on the screenshot (`OCREngine.extract_text_with_title` in
`ocr/ocr_engine.py`), typically a window title bar or page/section header
since headers sit above the content they label. It's stored in the JSON
entry's `extra.title` field, shown as its own column in the Search tab and in
CSV exports, prefixed onto the `.txt` log line, and included when feeding
entries to the summarizer.

The **Search** tab reads every `Shadow_*.jsonl` file under a day folder.

### Summarize (local LLM)

The Search tab's "Summarize results" button sends whatever entries the
current search matched to a local [Ollama](https://ollama.com) model
(`summarize/log_summarizer.py`), and shows the model's summary underneath.
An optional free-text field lets you steer it (e.g. "action items only",
"just the standup").

Prerequisites — this feature does nothing without them, and fails with a
one-line error in the status label rather than crashing:
- Ollama installed and running locally (`ollama serve`, or just have the
  Ollama.app running — it serves the same local API).
- The configured model pulled: `ollama pull gemma4` (or whatever you set
  `summarize.model` to in `config/default_settings.yaml`).

Notes:
- Runs on a background `QThread` (`gui/workers.py`'s `SummarizeWorker`), so
  the GUI stays responsive — but expect it to take a while, especially the
  *first* call after Ollama starts, since loading an 8B-parameter model into
  memory alone can take 10+ seconds before generation even begins.
- Only uses the text already logged locally — nothing is sent anywhere
  except your own machine's Ollama server (`summarize.base_url`, default
  `http://localhost:11434`).
- Long result sets are truncated to the most recent ~12,000 characters
  (`_MAX_ENTRY_CHARS` in `summarize/log_summarizer.py`) to fit a small
  model's context window — summarize a narrower search (tighter date range/
  keyword) if you need older entries included.

#### How gemma4 is wired into the app

There's no model-serving code in this repo at all — Ollama does that part.
The app is purely an HTTP *client* of Ollama's local REST API, matching the
"no heavy ML dependency for an optional feature" approach used elsewhere
(e.g. `faster-whisper`/`easyocr` are only imported when their feature is
actually used). The full connection path, click to response:

1. **You pull the model once, outside the app**: `ollama pull gemma4`. Ollama
   stores and serves it; this app never downloads or loads model weights
   itself.
2. **Config** (`config/default_settings.yaml`, `summarize:` block) declares
   which model/server/timeout to use — nothing here is hardcoded in Python:
   ```yaml
   summarize:
     base_url: http://localhost:11434   # Ollama's default local API port
     model: gemma4
     timeout_seconds: 180
   ```
3. **Button click → background thread**: `gui/dashboard.py`'s
   `_run_summarize()` reads those three config values plus the current
   search results and the optional instructions field, then hands them to
   `gui/workers.py`'s `SummarizeWorker` (a `QThread`) so a slow/first-load
   model call can't freeze the GUI. `SummarizeWorker.run()` does exactly one
   thing: construct a `LogSummarizer` and call `.summarize(entries,
   instructions)`.
4. **`LogSummarizer.summarize()`** (`summarize/log_summarizer.py`) is the
   actual client:
   - Formats every matched `LogEntry` into a plain-text line —
     `[HH:MM:SS] (source: title) text` — via `_format_entries()`, trimmed to
     the most recent ~12,000 characters so it fits a small model's context.
   - Builds one prompt: a fixed system instruction (`_SYSTEM_PROMPT` — stay
     factual, call out topics/decisions/action items/people, don't invent
     anything not in the entries) + your optional free-text instructions +
     the formatted log text.
   - POSTs it as JSON to Ollama's **generate** endpoint —
     `POST {base_url}/api/generate` with body
     `{"model": "gemma4", "prompt": <the full prompt>, "stream": false}` —
     using nothing but the Python stdlib's `urllib.request` (no `ollama`
     package, no `requests`; this is the whole reason it's a hard
     dependency-free HTTP call rather than an SDK integration).
   - `stream: false` means Ollama buffers the full generation server-side and
     replies with one JSON object once it's done, rather than the
     chunked/streamed response Ollama also supports — simpler client code,
     at the cost of no incremental output while the model is still thinking.
   - Reads `response["response"]` out of that JSON as the summary text.
5. **Errors surface, they don't crash**: connection refused (Ollama not
   running), a non-2xx HTTP status (e.g. model not pulled), or a malformed
   response are each caught and re-raised as a `SummarizerError` with a
   specific one-line message; `SummarizeWorker` catches that and emits it on
   its `error` signal, which the dashboard shows in the status label instead
   of the summary box.

Nothing here is gemma4-specific — `summarize.model` is just a string handed
straight to Ollama's `/api/generate`, so pointing it at any other model
you've pulled (`llama3.2`, `mistral`, ...) works identically with zero code
changes.

### AI Assistant (chat over your captured activity)

The **Assistant** tab (`gui/dashboard.py`'s `AssistantTab`) is a conversational
chat interface over your own structured events database (see
[Structured events and redaction (JSON files, no database)](#structured-events-and-redaction-json-files-no-database)) —
distinct from Search's one-shot "Summarize results": you ask free-form
questions, answers stream in incrementally, and every answer lists the
specific events it drew from.

Same prerequisites as Summarize — nothing here works without them, and a
connection failure shows as an inline transcript message rather than a crash:
- Ollama installed and running locally (`ollama serve`).
- The configured model pulled: `ollama pull gemma4` (or whatever
  `assistant.model` is set to).

The question box (`gui/dashboard.py`'s `ChatInput`, a `QPlainTextEdit`, not a
single-line field) is multi-line — **Enter sends, Shift+Enter adds a new
line** (the same convention as Slack/Discord/etc.) — so you can write out a
longer issue description or paste in a short stack trace before sending,
rather than being limited to one line. The Code tab below uses the
same input widget.

How it works, click to response:
1. **Suggested questions** (`ChatEngine.suggested_questions()`,
   `assistant/chat_engine.py`) are AI-generated once per day, grounded in
   whatever actually happened today — the local LLM is given today's captured
   events as context and asked to write 5–8 specific questions referencing
   real names/errors/tickets/times from them (e.g. "What did Priya ask about
   the migration?", "What was the payment-service error around 2pm?") rather
   than generic templates, and the result is cached in
   `suggested_questions.json` for the day (`gui/workers.py`'s
   `SuggestedQuestionsWorker` runs this off the GUI thread, since — like the
   first Summarize/Assistant call after Ollama starts — it can take a real
   amount of time). Click one to ask it immediately, or type your own
   question. Falls back to a small set of fixed template questions (e.g.
   "What bugs appeared today?" if any `error`/`bug` event occurred) if there's
   no captured activity yet today, Ollama can't be reached, or the model's
   output doesn't parse into any usable questions — this degrades instead of
   leaving the tab with nothing to click.
2. **Retrieval** (`assistant/retrieval.py`) is lexical + date-filtered, not
   vector/embedding search — it pulls events from the last `assistant.retrieval_days`
   (default 7) via `EventStore.recent_events`, narrows to whichever events'
   title/content overlap with keywords extracted from your question (falling
   back to the full recent set for vague questions like "what did I do
   today?"), and formats them into a context block trimmed to
   `assistant.max_context_chars` (default 12000) — same
   trim-from-the-oldest-end budget convention `summarize/log_summarizer.py`
   uses. Real semantic/vector search is a larger, later addition (it needs an
   embedding model) — see [Roadmap](#roadmap).
3. **Prompting** (`assistant/prompts.py`) builds one prompt from a fixed
   system instruction (stay grounded in the context, say so rather than
   guessing if the answer isn't there, refer to *when* something happened),
   the retrieved context, recent chat history (`assistant_history` table),
   and your question.
4. **Streaming** (`assistant/streaming.py`) POSTs to Ollama's `/api/generate`
   with `"stream": true` — unlike Summarize's `stream: false` — so Ollama
   replies with newline-delimited JSON chunks as they're generated instead of
   one buffered response; `gui/workers.py`'s `ChatWorker` (a `QThread`)
   forwards each chunk to the transcript as it arrives.
5. **Citations** (`assistant/citations.py`) — once the answer finishes, the
   events actually used to build the context are listed underneath it
   (type, timestamp, application, a short snippet), so you can trace any
   answer back to the exact captured entry.
6. Every question and answer is appended to `assistant_history.jsonl`
   (`database/json_store.py`), so context carries across turns in the same
   session.

Click **Stop** while an answer is streaming to cancel — the connection is
closed and no further chunks arrive, but whatever text streamed in before you
stopped is still saved to history.

Click **New Session** to start over: it clears the visible transcript and
wipes this tab's persisted conversation history
(`ChatEngine.new_session()` → `EventStore.clear_history()`, `default` thread
only — the Code tab keeps its own per-project history) so the next question doesn't carry any
prior turns into context. Disabled while a question is in flight.

### Code (VS Code-style editor with AI, git, and a Knowledge Bank)

The **Code** tab is a workspace over one local git repository: a Monaco editor,
file explorer, git panel, real terminal, and an AI assistant that edits files
with a diff you review before anything is written. It replaced the older
"Coding Agent" tab, absorbing its plan/apply and dev-server flows.

**One-time setup.** The editor (Monaco) and terminal (xterm.js) are JavaScript,
and are deliberately *not* committed to this repo (~28MB combined). Fetch them
once:

```bash
python scripts/fetch_vendor.py
```

Each download is pinned by version **and** sha256 — this JS runs inside the app
with access to the Python bridge, so an unverified download would be a real
supply-chain hole. Without the assets the editor and terminal panels show these
instructions instead of a blank page.

#### Opening a repository

**Open Repo...** browses for a folder; recently-opened ones are remembered in
the same `output/events/manual_projects.json` the Assistant tab uses, so a
folder added in either place shows up in both. The bar along the top always
shows four things: the active repository, the current branch, git status
(`clean` / `2 modified, 1 untracked`), and Knowledge Bank status.

**Branch switching** refuses when the working tree is dirty. git itself would
sometimes allow it, but in an editor that silently rewrites files under your
open buffers the stricter rule is the safer one — commit, stash, or discard
first. Switching branches or repositories closes open buffers rather than
leaving them stale.

#### Editing

The file explorer lists one directory level at a time, populating on expand, so
opening a large repository never walks the whole tree. `node_modules`, `.git`,
`dist` and the rest of `DEFAULT_IGNORED_DIRS` are hidden. Right-click for New
File/Folder, Rename, Delete, Reveal in Finder, or Copy Relative Path — every one
of those resolves through the same path-containment check used everywhere else,
so nothing can escape the project root.

Files open in Monaco with syntax highlighting. Editing marks the tab with a `●`;
**Cmd+S** saves. Saves are **atomic** (temp file + fsync + rename, so a crash
can't truncate your source) and **conflict-aware**: every buffer remembers the
mtime it was read at, and if the file changed on disk since then you get
Overwrite / Reload / Cancel rather than silently clobbering the other change.

Files are refused rather than truncated if they're over `ide.max_open_file_bytes`
(2MB) or aren't decodable text — opening a truncated file and saving it back
would delete the remainder.

#### AI actions on a file or selection

Select code (or don't, for the whole file), then pick an action: **Explain**,
**Refactor**, **Fix Bug**, **Optimise**, **Add Comments**, **Generate Tests** —
or type a request and press Send. 🎤 dictates a prompt instead of typing it, using
the same local whisper model as call transcripts.

**Choosing a model.** The dropdown lists whatever your Ollama actually has —
queried from `/api/tags` at startup, so anything you `ollama pull` appears without
touching config. Each entry shows its parameter count and size on disk
(`gemma4  (8.0B, 9.6GB)`), with a tooltip covering family and whether it supports
vision or reasoning. **gemma4 is preselected** when present; ↻ re-checks the list
after pulling something new. If Ollama isn't running, the dropdown falls back to
`coding_agent.available_models` so you can still pick a name to try.

Ollama can also expose **cloud** models — entries that run on ollama.com rather
than on your machine. Those are hidden by default, deliberately: Shadow reads your
screen and edits your source, and sending that to a third party should be an
explicit decision, not a side effect of picking a name from a list. Set
`assistant.allow_remote_models: true` to include them; they're labelled `(cloud)`
with a warning in the tooltip.

**Explain** streams prose and changes nothing. Everything else produces a
proposal you review as a side-by-side diff before it touches disk:

- **Accept** writes the file. The right-hand side of the diff is editable, so
  you can adjust the AI's version first — what you see is what gets written.
- **Reject** discards it; the file is untouched.

Unlike the multi-file plan flow below, this does **not** require a clean git tree
and does **not** commit — you're editing files, so demanding a clean tree would
make the feature unusable. Safety comes from four things instead:

1. Proposals are computed **entirely in memory**; nothing is written during
   generation.
2. Accepting re-hashes the file first and refuses if it changed since the
   proposal was made. With a local model taking tens of seconds, you editing the
   same file mid-generation is likely, not theoretical.
3. The previous content is copied to
   `~/Desktop/.shadow/<repo>/backups/` and recorded in `journal.jsonl` before the
   write — multi-step undo independent of git and of the editor.
4. The write itself is atomic.

**On edit reliability**: the model is asked for surgical search/replace blocks on
large files and a whole-file rewrite on small ones. If its blocks can't be
applied, Shadow retries once with the error fed back, then falls back to a
whole-file rewrite. Expect that path to be used regularly with a small local
model. Crucially, if a block's SEARCH text matches *more than one* place in the
file, the edit is **rejected rather than applied to a guess** — applying at the
wrong location silently corrupts a file, which is far worse than a visible
failure.

#### Knowledge Bank

Each repository gets a cached index at `~/Desktop/.shadow/<name>-<hash>/`, built
in the background when you open it. It's stored **outside** the repository, so
indexing never adds untracked files to your project. The directory name includes
a hash of the absolute path, so two repositories both called `web` never share
one bank.

The index holds the file list, languages, per-file symbols, dependencies parsed
from manifests (`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`,
`Cargo.toml`, `pom.xml`, ...), and README/docs excerpts. It's **incremental**:
re-indexing an unchanged repository re-reads nothing, and editing one file
re-reads exactly that file. Indexing this repository (114 files) takes ~0.16s
cold and ~0.11s warm.

This is what makes AI answers project-aware cheaply. Ranking happens entirely
over the index with **zero file reads**; only the handful of winning files are
then read from disk. The flow it replaces (`find_relevant_files`) read *every
file in the project* on every single call.

**Describe Project** writes an architecture summary using the local model. Slow
the first time, then cached until the project's *shape* changes — the cache key
is deliberately coarse (top-level directories, dependency names, entrypoints,
bucketed file count), so editing a function doesn't invalidate it but adding a
dependency does. A stale summary is still shown, labelled, rather than hidden.
**Re-index** rebuilds from scratch.

Symbol extraction is exact for Python (stdlib `ast`). For every other language
it's **regex and approximate** — it misses class methods, arrow functions
assigned to object properties, and decorated declarations. Those entries are
tagged and excluded from prompts in favour of real file excerpts. There are tests
asserting these gaps, so they stay deliberate rather than being mistaken for bugs
later.

#### Git panel

Staged, modified, and untracked files in one list, with the diff for whichever
you select. Stage/Unstage individual files or Stage All, write a commit message
and **Commit**, or **Stash All** (which includes untracked files, since the usual
reason to stash here is unblocking a branch switch). **History** shows recent
commits. Right-click a file to stage it, open it in the editor, or discard its
changes — discard asks for confirmation because it is genuinely unrecoverable:
no stash, no backup, nothing to undo.

Commits never use `git -a`: staging is an explicit action, and `-a` would sweep
in unrelated modified files you didn't choose.

#### Terminal

A **real** terminal: a login shell on a pseudo-terminal, rendered by xterm.js.
That distinction matters — a pipe is not a terminal, and on one `git`, `npm`, and
`pytest` all disable colour and progress output, while anything that prompts for
input (a password, `git rebase -i`) simply hangs. Here `isatty()` is true, so
tools behave the way they do in your own terminal, and `vim`/`htop` work.

Resizing the panel propagates the new size to the shell (via `TIOCSWINSZ` plus
`SIGWINCH`), so full-screen programs redraw correctly. The shell runs in its own
process group, which is why Ctrl-C reaches the command you're running instead of
killing Shadow. Closing the tab or the app terminates the whole group — a dev
server started in here won't be left orphaned holding its port.

#### Plan a multi-file change, implement it, verify in Chrome

Separate from the single-file actions above, and deliberately stricter, because
it rewrites several files at once. Type a description and click **Plan Multi-File
Change**:

1. `assistant/coding_agent.py`'s `generate_plan()` reads the project's file tree
   and the most relevant files, adds any captured-activity context, and asks the
   model for a plan — prose describing what to change, **not code yet** — ending
   with a machine-readable file list. Any path the model invents that doesn't
   exist is dropped rather than trusted, unless explicitly marked as new.
2. **Apply Plan** (`apply_plan()`) first checks the project **is a git repository
   with a clean working tree**, and refuses outright otherwise. It then creates a
   **brand-new branch** (`shadow-agent/<slug>-<timestamp>`), rewrites each planned
   file (one model call each, path-checked against the project root), and
   `git add -A && git commit`. Your original branch and any in-progress work are
   never touched — you were never on the new branch to begin with.
3. **Run Dev Server** (`assistant/dev_server.py`) detects a start command from
   `package.json` (`dev` → `start` → `serve`, via `npm`/`yarn`/`pnpm` depending
   on the lockfile) — **Node/npm-family projects only**; anything else reports
   "no known start command" rather than guessing. It watches the log for a
   `http://localhost:PORT` URL for up to
   `coding_agent.dev_server_timeout_seconds` (default 20s) and opens it in
   Chrome. **No browser automation** — it just gets the tab open. **Stop Dev
   Server** when done (also stopped automatically on close).

Relevant configuration:

```yaml
ide:
  monaco_dir: vendor/monaco       # where fetch_vendor.py puts the editor
  xterm_dir: vendor/xterm         # ... and the terminal
  theme: vs-dark
  max_open_file_bytes: 2000000    # larger files are refused, never truncated

knowledge_bank:
  root: ~/Desktop/.shadow         # per-repo banks live here, outside your project
  auto_index_on_open: true
  max_files: 20000                # ceiling for very large monorepos
  max_file_bytes: 524288          # bigger files are indexed but not parsed

coding_agent:
  max_relevant_files: 6           # source files fed to the model per plan
  max_file_bytes: 6000            # per-file budget when selecting relevant files
  dev_server_timeout_seconds: 20  # how long to wait for a localhost URL
  available_models: ["gemma4", "qwen3.6"]
  timeout_seconds: 600            # generous: a large model's cold load is slow
```

### Screen capture exclusions

`gui/workers.py`'s `ScreenOcrWorker` fully pauses screen capture, preview, and
OCR whenever the frontmost window/app matches an exclusion rule (see
`screen.excluded_apps` / `screen.excluded_domains` in
`config/default_settings.yaml`):

- **This app itself, and any window/Finder/folder/file whose name starts with
  "Shadow"** (case-insensitive, checked against both the frontmost app name
  and window title) — **hardcoded, always enforced**, regardless of
  `excluded_apps`. Removing `"Shadow"` from a local `excluded_apps` override
  does **not** re-enable capturing this app's own window — this rule can't be
  disabled via config. Covers this app's own window, this project's folder
  (e.g. a Finder/terminal window browsing `shadow/`), and its own output files
  (e.g. opening one of the `Shadow_*.txt` notes in a text editor).
- Any window/process whose name contains an entry in `excluded_apps`
  (case-insensitive) — defaults to `["Claude", "Shadow"]` (Claude Code, plus a
  redundant/overridable copy of the hardcoded Shadow rule above).
- Any Chrome/Safari tab whose URL contains an entry in `excluded_domains`
  (case-insensitive) — defaults to sites you likely don't want OCR'd, e.g.
  `mail.google.com`, `outlook.office.com`, `web.whatsapp.com`. These are generic
  examples — put the sites *you* never want captured (payroll, banking, health,
  internal admin) in the gitignored `config/settings.local.yaml` instead of here,
  so a public repo doesn't advertise which services you use.

The screen-capture exclusion rules above do **not** apply to spell check —
see below.

### Spell check (system-wide)

`gui/workers.py`'s `SpellCheckWorker` uses a `pynput.keyboard.Listener` to
watch every keystroke **system-wide** — not just inside Shadow — and shows a
small auto-dismissing popup whenever it finds an issue. **Enabled by default,
everywhere, with no exclusions.** Two independent checks run side by side:

- **Spelling** (`pyspellchecker`, fully offline, no extra setup) — checked
  word-by-word, right in the keyboard callback, since dictionary lookups are
  fast enough not to risk delaying real keystrokes.
- **Grammar** (`language_tool_python`, running a local LanguageTool server) —
  checked sentence-by-sentence (flushed on `.`/`!`/`?`, Enter, or a length
  cap) on a **separate background thread**, since grammar checks take real
  time (tens–hundreds of ms) and must never block the keyboard callback
  thread. Requires a **JRE on PATH/JAVA_HOME** and downloads a ~250MB
  LanguageTool bundle on first use (cached afterward, e.g.
  `brew install openjdk` if you don't have Java). Set
  `spellcheck.grammar_enabled: false` in `config/default_settings.yaml` to
  disable grammar checking and keep spelling-only if Java isn't available —
  a missing/broken grammar setup degrades gracefully (spelling keeps working,
  status label shows a one-line warning) rather than disabling the whole
  feature.

Safety notes (apply to both checks, since both come from the same keystroke
stream):

- **This is functionally a keylogger**, running continuously from app launch
  across every app and window on this Mac, with none of the app/domain
  exclusions that screen capture has. Neither check persists anything: the
  per-word and per-sentence buffers are discarded immediately after each
  check and **never written to disk or logged anywhere** — but the raw
  keystrokes are still observed live, including anything typed into password
  fields.
- **Uncheck "Enable spell-check popups" before typing passwords** or other
  sensitive input, since there is no automatic pause for any app or site.
- Requires macOS **Input Monitoring** permission (System Settings > Privacy &
  Security > Input Monitoring) for your terminal/app, separate from the
  Accessibility/Automation permissions the other features need.
- Best-effort, editor-unaware: it tracks a plain backspace-to-undo but has no
  concept of cursor position, so arrow-key navigation or pasted text mid-word/
  mid-sentence isn't handled precisely.

## Configuration

Defaults live in `config/default_settings.yaml`. Create an optional
`config/settings.local.yaml` (gitignored) with the same structure to override
any values locally, e.g. camera index, OCR engine, or audio device.

## Structured events and redaction (JSON files, no database)

Every entry `DataLogger.log_event()` writes (OCR text, meeting transcripts) is
still appended to the raw `Shadow_*.jsonl`/`.txt` files exactly as before (see
[Session files](#session-files)) — that behavior is unchanged. When a
`MainWindow` is constructed, it *also* wires an `EventStore` into the shared
`DataLogger` (`gui/dashboard.py`), so each entry additionally flows through:

1. **Redaction** (`events/redaction.py`) — a regex-based best-effort filter
   for common secret/PII shapes (OpenAI/AWS/GitHub/Slack-style API keys,
   `Bearer` tokens, generic `key=value`/`password=value` assignments, emails,
   card-number-like sequences), each replaced with a `[REDACTED_*]`
   placeholder.
2. **Classification** (`events/classifier.py`) — a rule-based (not ML)
   heuristic, in the same spirit as `callwatch/call_detector.py`'s call
   detection: recognizes Python/Java/Node/Rust tracebacks and build failures
   as `error` (severity bumped to `high` on `fatal`/`panic`/`crash` keywords),
   tags decision/action-item phrasing, detects URLs as `website`, and code
   editors + code-like symbol density as `code` — falling back to `note` when
   nothing more specific matches. `channel == "speech"` entries (meeting
   transcripts) default to `meeting`. Regardless of type, any Jira-style
   ticket key (`events/project_keys.py`, e.g. `PROJ-1139`) is also tagged as
   an entity — a convenience denormalization; the
   [Code tab](#code-vs-code-style-editor-with-ai-git-and-a-knowledge-bank) actually
   re-extracts ticket keys from `content` directly rather than relying on
   this, so it also works over events captured before this tagging existed.
3. **Storage** (`database/json_store.py`'s `EventStore`) — **no database** —
   the redacted, classified result is appended as one JSON line to a
   date-partitioned `events.jsonl` file, the same flat-file convention
   `logger/data_logger.py` already uses for the raw OCR/speech logs:
   ```
   output/events/
       2026-07-20/
           events.jsonl          # one JSON object per line for that day
       assistant_history.jsonl   # chat history, all days in one file
       suggested_questions.json  # {"2026-07-20": ["question", ...], ...}
   ```
   Queries (`EventStore.query_events`/`recent_events`) are a linear scan +
   filter in Python — the same approach `search/search_engine.py` already
   uses over `DataLogger.iter_entries()` — not an indexed lookup. Fine for a
   local single-user desktop app; would need revisiting if `events.jsonl`
   grows very large.

**Redaction boundary**: redaction only ever applies to what lands in
`events.jsonl` — the copy of your activity the AI Assistant can retrieve and
send to the local LLM. The original raw `Shadow_*.jsonl`/`.txt` files are
**not** redacted or otherwise changed; they're already local-only, already-
documented behavior this feature doesn't touch. If you want the assistant to
never see certain content, keep it out of what gets OCR'd/transcribed in the
first place (see [Screen capture exclusions](#screen-capture-exclusions))
rather than relying on redaction alone — it's a heuristic, not a guarantee.

This layer also powers the AI Assistant's conversation history
(`assistant_history.jsonl`) and daily suggested questions
(`suggested_questions.json`) — see
[AI Assistant](#ai-assistant-chat-over-your-captured-activity).

Relevant config (`config/default_settings.yaml`):
```yaml
database:
  dir: output/events

assistant:
  base_url: http://localhost:11434
  model: gemma4
  timeout_seconds: 180
  retrieval_days: 7       # how far back retrieval looks when answering a question
  max_context_chars: 12000 # prompt context budget, same convention as summarize/
```

## Testing

```bash
source .venv/bin/activate
pytest
```

Covers `events/` (redaction patterns, classifier heuristics, schema
round-trips), `database/json_store.py` (`EventStore` insert/query/history/
suggested-questions behavior against a `tmp_path` directory of JSON/JSONL
files), `assistant/retrieval.py` and `assistant/streaming.py` (the latter
mocks `urllib.request.urlopen` with a fake NDJSON response — no live Ollama
server needed to run the suite), and `logger/data_logger.py`'s optional
`EventStore` wiring (including that the redaction boundary above actually
holds: the raw JSONL log keeps the unredacted text while `events.jsonl`
doesn't). None of
the PyQt6 GUI code has automated tests — verify GUI changes by actually
running `python main.py`.

## Gesture vocabulary

All gesture recognition happens in `gesture/gesture_recognizer.py`; mapping
gestures to actual mouse input happens in `gui/workers.py`'s `GestureWorker`,
which runs once per camera frame while "Start Camera/Gesture" is active.

### Cursor movement

The pointer follows your **index fingertip** on every frame where a hand is
detected — this happens regardless of which gesture is classified below (i.e.
you don't need to be in the `point` gesture to move the cursor). Movement
only takes effect while **Enable mouse control** is checked.

- Normalized fingertip `(x, y)` is mapped to screen coordinates, with a 10%
  dead-zone margin at each edge (`mouse.screen_margin` / `MouseController.margin`)
  so you don't need to reach the literal frame edge to hit screen corners.
- Motion is smoothed (`gesture.smoothing`, default `0.5`) to reduce jitter —
  higher values mean more smoothing/lag, `0` disables smoothing entirely.

### Gestures and their mouse action

| Gesture      | Trigger                                            | Action (when mouse control enabled) |
|--------------|-----------------------------------------------------|--------------------------------------|
| `pinch`      | thumb tip within `pinch_click_threshold` (default `0.04`, normalized distance) of the index tip | **left click** — debounced by a 0.4s cooldown (`MouseController._click_cooldown`) so a single pinch can't fire repeated clicks |
| `point`      | exactly one finger extended, and it's the index finger | no separate action beyond the always-on cursor tracking above |
| `fist`       | no fingers extended                                  | reserved — no action wired up yet |
| `open_palm`  | four or more fingers extended                        | reserved — no action wired up yet |
| *(none of the above)* | 2–3 fingers extended in any other combination | reserved — no action wired up yet |

"Finger extended" is determined by comparing each fingertip's distance from
the wrist to its corresponding knuckle (MCP) distance from the wrist — a
finger counts as extended if the tip is farther from the wrist than the
knuckle is.

### Tuning

All thresholds live in `config/default_settings.yaml` under `gesture:` and
`mouse:` (see [Configuration](#configuration)):

- `gesture.pinch_click_threshold` — lower this if pinches aren't registering,
  raise it if clicks fire accidentally while your fingers are just close together.
- `gesture.detection_confidence` / `gesture.tracking_confidence` — MediaPipe's
  hand-detection/tracking confidence thresholds.
- `gesture.max_hands` — number of hands tracked at once (only the first
  detected hand drives the mouse).
- `gesture.smoothing`, `mouse.screen_margin` — cursor feel, as above.

## Troubleshooting

A symptom-first index of the issues most likely to come up, with a pointer to
the relevant section for the full explanation.

| Symptom | Likely cause | See |
|---|---|---|
| A feature "does nothing" — no crash, no output | Missing macOS privacy permission for whichever app launches `python main.py` | [macOS permissions checklist](#macos-permissions-checklist) |
| Call detection never fires for any browser, even one you know is in a meeting | A **different** browser (Edge/Brave/Safari) has an unanswered "would like to control this computer" prompt — check for it, it can be hidden behind other windows | [Known limitations](#known-limitations) |
| Call detection never fires for a specific app/browser only | That app's window/tab title just doesn't match the expected pattern (e.g. Slack huddle title changed, or an unlisted browser) — this is a heuristic, not an API integration | [Known limitations](#known-limitations) |
| "Summarize results" shows "Run a search above first" | Your last search matched zero entries, or you haven't run one yet — check your keyword/date/source filters | [Summarize (local LLM)](#summarize-local-llm) |
| "Summarize results" seems stuck on "Summarizing..." | Likely just the first call after Ollama (re)starts — loading an 8B model into memory alone can take 10+ seconds before generation even begins | [Summarize (local LLM)](#summarize-local-llm) |
| "Summarize results" shows an error | `ollama serve`/Ollama.app isn't running, or the configured model (`summarize.model`, default `gemma4`) hasn't been pulled — the error message names which | [Summarize (local LLM)](#summarize-local-llm) |
| Spell check / gesture mouse control does nothing | Input Monitoring / Accessibility permission not granted, or granted to the wrong app (e.g. iTerm instead of Terminal) | [macOS permissions checklist](#macos-permissions-checklist) |
| Grammar suggestions never appear (spelling still works) | Java (JRE) isn't installed/on PATH, or `spellcheck.grammar_enabled: false` | [Spell check (system-wide)](#spell-check-system-wide) |
| The whole app crashes on launch (`EXC_BREAKPOINT`) | Should already be handled — see the pynput/macOS patch note | [Known limitations](#known-limitations) |
| Screen/OCR pipeline seems paused for a window you didn't expect | It matches `screen.excluded_apps` / `excluded_domains`, or its title starts with "Shadow" | [Screen capture exclusions](#screen-capture-exclusions) |

If none of these match, check the relevant worker's `error` signal handler in
`gui/dashboard.py` — every background pipeline (`gui/workers.py`) surfaces
failures to a status label instead of failing silently or crashing the GUI.

## Roadmap

This scaffold covers the full module set. Suggested build order if extending
further:

1. Tune gesture thresholds/smoothing against your webcam and lighting
2. Add drag (pinch-hold) and scroll (two-finger) gestures
3. Add a manual "Start Transcription" control independent of call detection
4. Add a daily-report / merge-OCR-and-speech export action
5. Add multi-monitor and user-selectable OCR region support
6. Package with PyInstaller for distribution

Larger follow-ups to the AI Assistant / structured-events layer
(`events/`, `database/`, `assistant/`), roughly in the order they'd build on
each other:

7. Embedding-based retrieval (a local embedding model + a vector store, e.g.
   FAISS/Chroma) instead of `assistant/retrieval.py`'s current keyword
   overlap — a genuine "knowledge bank" needs semantic search
8. A nightly distillation worker that dedupes/links classified events into
   durable knowledge-bank entities (people, projects, decisions, glossary)
   rather than leaving every event as a standalone row
9. Voice mode for the Assistant tab (push-to-talk → faster-whisper →
   `ChatEngine.ask` → TTS), reusing the transcription pipeline `speech/`
   already has
10. Developer automation on top of classified events: one-click standup
    generation, bug-report/GitHub-issue drafting from an `error` event,
    meeting-transcript → task extraction
11. Manager-facing views: weekly digests and focus/meeting analytics rolled
    up from the `events` table
12. Outbound integrations (GitHub/Jira/Slack/Calendar) once there's a concrete
    action to trigger (e.g. filing the bug report from item 10) — needs
    credentials/config this repo doesn't currently manage

## Known limitations

- Call auto-capture (`callwatch/`) is a **heuristic, not a real Slack/Google
  API integration** — it detects calls by reading Chrome/Safari tab URLs and
  Slack window titles via AppleScript (`osascript`), so it's macOS-only and
  will miss calls whose window/tab doesn't match the expected pattern (e.g. a
  Slack huddle whose window title doesn't contain "Huddle").
- Call auto-capture records **your microphone**, not the other participants'
  audio. Capturing the full call audio requires a loopback device like
  [BlackHole](https://github.com/ExistentialAudio/BlackHole) selected as
  `audio.device_index`.
- Call auto-capture requires Automation permission for your terminal/app to
  control Google Chrome, Safari, and System Events, in addition to Microphone
  access — grant these under **System Settings > Privacy & Security >
  Automation / Microphone**. Each of Chrome/Edge/Brave/Safari is authorized
  **separately** and only prompts the first time it's actually polled — if a
  prompt appears (it can show up behind other windows) and is left
  unanswered, detection for every browser stalls until it's dismissed, since
  `callwatch/call_detector.py` polls each browser with its own short timeout
  and gives up silently rather than blocking forever. If call detection
  never seems to fire, check for a pending "`<App>` would like to control
  this computer" dialog first.
- `faster-whisper` and `easyocr` will download model weights on first use;
  ensure network access the first time each runs, or pre-populate `models/`.
- **Redaction and classification (`events/`) are heuristic, not guarantees.**
  `events/redaction.py` only catches secret/PII *shapes* it has a regex for —
  it will miss anything unusually formatted, and `events/classifier.py`'s
  event-type tagging (error/meeting/decision/task/code/website) is
  keyword/pattern matching, not real language understanding, so it will
  mislabel or miss unusual phrasing. Neither ever touches the raw
  `Shadow_*.jsonl` log — see
  [Structured events and redaction (JSON files, no database)](#structured-events-and-redaction-json-files-no-database).
- The AI Assistant tab's retrieval (`assistant/retrieval.py`) is keyword +
  recency based, not semantic/vector search — a question whose wording
  doesn't overlap with the relevant events' text may retrieve the wrong (or
  just the most recent) context instead. Proper embedding-based retrieval is
  a larger follow-up (see [Roadmap](#roadmap)).
- Summarization (`summarize/`) depends entirely on a local Ollama server
  being up with the configured model pulled — there's no bundled fallback
  model. It also does no request batching/retries: a slow/loaded Ollama
  instance just means a slow summarize call, not a queued one.
- **Spell check could crash the whole app on macOS without a patch we apply
  automatically.** `pynput.keyboard.Listener` calls Carbon/HIToolbox APIs on
  its own background thread to resolve the keyboard layout at startup; modern
  macOS asserts these calls must happen on the main dispatch queue, and
  violating this kills the entire process (`EXC_BREAKPOINT` /
  `dispatch_assert_queue_fail`) — not just the spell-check feature. This is a
  known upstream bug ([moses-palmer/pynput#511](https://github.com/moses-palmer/pynput/issues/511),
  reproduces with PyQt6/PySide6/tkinter alike). `spellcheck/_pynput_darwin_patch.py`
  removes the offending call at import time — it's genuinely unused for plain
  keystroke listening in pynput 1.8.2 (character decoding goes through a
  separate, thread-safe API), so this has no effect on detection accuracy.
  This patch is pinned to pynput 1.8.2's internals; if you upgrade pynput, re-verify
  this still applies cleanly.
