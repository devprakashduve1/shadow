# Shadow

A desktop productivity/accessibility app that combines hand-gesture mouse control,
desktop screen monitoring with OCR, and speech-to-text transcription into a single
PyQt6 dashboard with searchable logs.

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
  gui/        PyQt6 dashboard + background workers
  config/     YAML settings loader
  models/     local model weights (gitignored)
  assets/     icons/static assets
  output/     logs, exports (gitignored)
  main.py     app entry point
```

## Setup

```bash
cd shadow
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

That installs everything needed for camera/gesture, screen/OCR, meeting audio
transcription, and offline spelling checks. Two things install separately
because they're system-level, not pip packages — see below:

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

This opens the dashboard with two tabs:

- **Live Monitor** — start/stop the camera+gesture pipeline (optionally driving
  the real mouse), the screen+OCR pipeline (optionally logging extracted text,
  and running automatically from launch), and the Slack/Google Meet call
  auto-capture (optionally transcribing voice).
- **Search** — filter logged OCR/speech entries by keyword, source, and date
  range, export results to CSV, and summarize the current results with a
  local LLM (see [Summarize](#summarize-local-llm)).

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

### Screen capture exclusions

`gui/workers.py`'s `ScreenOcrWorker` fully pauses screen capture, preview, and
OCR whenever the frontmost window/app matches an exclusion rule (see
`screen.excluded_apps` / `screen.excluded_domains` in
`config/default_settings.yaml`):

- Any window/process whose name contains an entry in `excluded_apps`
  (case-insensitive) — defaults to `["Claude", "Shadow"]`, covering this
  app's own window and Claude Code.
- **Any window/file whose title starts with "Shadow"** — always enforced,
  regardless of `excluded_apps`, so this app never re-captures its own output
  files (e.g. if you open one of the `Shadow_*.txt` notes in a text editor).
- Any Chrome/Safari tab whose URL contains an entry in `excluded_domains`
  (case-insensitive) — defaults to sites you likely don't want OCR'd, e.g.
  `vista.adp.com`, `mail.google.com`, `outlook.office.com`, `web.whatsapp.com`.

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

## Roadmap

This scaffold covers the full module set. Suggested build order if extending
further:

1. Tune gesture thresholds/smoothing against your webcam and lighting
2. Add drag (pinch-hold) and scroll (two-finger) gestures
3. Add a manual "Start Transcription" control independent of call detection
4. Add a daily-report / merge-OCR-and-speech export action
5. Add multi-monitor and user-selectable OCR region support
6. Package with PyInstaller for distribution

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
