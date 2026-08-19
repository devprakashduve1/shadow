# Local AI Editor: Visual Architecture

**This file shows HOW everything connects**

---

## System Overview

```
ENTIRE SYSTEM ARCHITECTURE
═══════════════════════════════════════════════════════════════════

                          USER
                           ↓
                    (Clicks, types, drags)
                           ↓
                    ┌──────────────┐
                    │   ELECTRON   │
                    │  DESKTOP APP │
                    │   (React)    │
                    └──────────────┘
                    (NEW WEEK 3-5)
                           ↕
                   (WebSocket + REST)
                           ↕
                    ┌──────────────┐
                    │   FASTAPI    │
                    │   SERVER     │
                    │ (Python)     │
                    └──────────────┘
                    (NEW WEEK 1-2)
                           ↕
                    (Python imports)
                           ↓
        ┌─────────────────────────────────┐
        │ EXISTING CODE EDITING ENGINE    │
        │ (NO CHANGES - 2000 LOC)         │
        │                                 │
        │ • Orchestrator                  │
        │ • Planner                       │
        │ • Editor                        │
        │ • Validator                     │
        │ • Props Analyzer                │
        │ • Context Retriever             │
        └─────────────────────────────────┘
                           ↓
        ┌─────────────────────────────────┐
        │ MODEL PROVIDERS (NEW)            │
        │                                 │
        │ • MLX (Apple Silicon)           │
        │ • AirLLM (quantized)            │
        │ • Ollama (existing)             │
        └─────────────────────────────────┘
                           ↓
        ┌─────────────────────────────────┐
        │ LOCAL AI MODELS                 │
        │ (Running on M3 Mac)             │
        └─────────────────────────────────┘
```

---

## Component Interaction Diagram

```
REQUEST FLOW: User asks "Explain this function"
═══════════════════════════════════════════════════════════════════

1. UI Layer (Electron/React)
   ┌─────────────────────────────────────┐
   │ ChatPanel Component                 │
   │ User types: "Explain this function" │
   └─────────────────────────────────────┘
                    ↓
2. Network Layer (WebSocket)
   ┌─────────────────────────────────────┐
   │ WS /api/v1/agent/execute            │
   │ {                                   │
   │   "message": "Explain...",          │
   │   "context": {                      │
   │     "selectedFile": "main.py",      │
   │     "selectedCode": "def foo()..."  │
   │   }                                 │
   │ }                                   │
   └─────────────────────────────────────┘
                    ↓
3. API Layer (FastAPI routes/agent.py)
   ┌─────────────────────────────────────┐
   │ @app.websocket("/api/v1/agent/...")│
   │ async def ws_execute(ws):           │
   │   editor = AICodeEditor(...)        │
   │   async for token in editor.xxx():  │
   │     await ws.send_json(token)       │
   └─────────────────────────────────────┘
                    ↓
4. Business Logic (Existing orchestrator.py)
   ┌─────────────────────────────────────┐
   │ AICodeEditor.handle_request()       │
   │ ├─ IntentAnalyzer.analyze()         │
   │ │  → intent = "explain"             │
   │ │                                   │
   │ ├─ ContextRetriever.retrieve()      │
   │ │  → finds main.py + related files  │
   │ │                                   │
   │ ├─ Planner.plan()                   │
   │ │  → creates plan                   │
   │ │                                   │
   │ └─ [Doesn't apply code, just      │
   │    generates explanation]           │
   └─────────────────────────────────────┘
                    ↓
5. Model Inference (Provider)
   ┌─────────────────────────────────────┐
   │ MLXProvider.chat()                  │
   │ ├─ Load model (if not loaded)       │
   │ ├─ Format prompt                    │
   │ ├─ Generate tokens via MLX          │
   │ └─ Stream each token back           │
   └─────────────────────────────────────┘
                    ↓
6. Response Stream (WebSocket)
   ┌─────────────────────────────────────┐
   │ Token 1: "This"                     │
   │ Token 2: "function"                 │
   │ Token 3: "validates"                │
   │ Token 4: "email"                    │
   │ Token 5: "addresses"                │
   │ Token 6: "..."                      │
   └─────────────────────────────────────┘
                    ↓
7. UI Update (React)
   ┌─────────────────────────────────────┐
   │ ChatPanel displays:                 │
   │ "This function validates email      │
   │  addresses..."                      │
   │ (shown as tokens arrive, not all    │
   │  at once)                           │
   └─────────────────────────────────────┘
```

---

## State Flow Diagram

```
APPLICATION STATE MACHINE
═══════════════════════════════════════════════════════════════════

                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │
                           ↓
                ┌──────────────────────┐
                │ Load Configuration   │
                │ ~/.config/app/...    │
                └──────────┬───────────┘
                           │
                           ↓
            ┌──────────────────────────────┐
            │ Initialize ProviderManager   │
            │ ├─ Discover Ollama models    │
            │ ├─ Discover MLX models       │
            │ └─ Discover AirLLM models    │
            └──────────┬───────────────────┘
                       │
                       ↓
         ┌────────────────────────────────┐
         │ Load UI with Model List        │
         │ ├─ File Explorer              │
         │ ├─ Model Selector             │
         │ ├─ Chat Panel (empty)         │
         │ └─ Editor (no file)           │
         └────────────┬───────────────────┘
                      │
                      ↓
        ┌──────────────────────────────┐
        │ READY STATE                  │
        │ Waiting for user action      │
        └──────────┬───────────────────┘
                   │
        ┌──────────┴──────────┬──────────────┐
        ↓                     ↓              ↓
    ┌────────┐        ┌──────────┐    ┌──────────┐
    │ OPEN   │        │ SELECT   │    │ CHAT     │
    │ FILE   │        │ MODEL    │    │ MESSAGE  │
    │ STATE  │        │ STATE    │    │ STATE    │
    └────────┘        └──────────┘    └──────────┘
```

---

## Provider Architecture

```
PROVIDER ABSTRACTION PATTERN
═══════════════════════════════════════════════════════════════════

┌────────────────────────────────────────────────────┐
│ LocalAIProvider (Abstract Base Class)              │
│                                                    │
│ Methods (ALL providers must implement):            │
│ ├─ async discover_models() → List[LocalModel]     │
│ ├─ async load_model(model_id: str)                │
│ ├─ async unload_model()                           │
│ ├─ async chat(messages) → AsyncIterable[str]      │
│ ├─ async get_status() → ModelStatus               │
│ └─ validate_model_path(path: str) → bool          │
└────────────────────────────────────────────────────┘
         ↑               ↑               ↑
         │               │               │
         │               │               │
    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
    │  OLLAMA  │    │   MLX    │    │  AIRLM  │
    │ PROVIDER │    │ PROVIDER │    │PROVIDER │
    │          │    │          │    │         │
    │ Uses:    │    │ Uses:    │    │ Uses:   │
    │ Ollama   │    │ mlx-lm   │    │ airlm   │
    │ HTTP API │    │ library  │    │ library │
    │          │    │ (native  │    │         │
    │ Models   │    │  M-chip) │    │ Models  │
    │ run on   │    │          │    │ can be  │
    │ Ollama   │    │ Models   │    │ from    │
    │ server   │    │ on local │    │ HF      │
    │          │    │ drive    │    │         │
    └──────────┘    └──────────┘    └─────────┘
```

---

## FastAPI Route Structure

```
FASTAPI ENDPOINT HIERARCHY
═══════════════════════════════════════════════════════════════════

/api/v1/
├── models/
│   ├── GET    /                    ← List all models
│   ├── POST   /scan                ← Rescan for new models
│   ├── POST   /{id}/load           ← Load specific model
│   ├── POST   /unload              ← Unload current
│   ├── GET    /status              ← Get status
│   └── GET    /providers           ← List providers
│
├── agent/
│   ├── POST   /analyze             ← Analyze intent
│   ├── POST   /plan                ← Generate plan
│   └── WS     /execute             ← Execute with streaming
│
├── files/
│   ├── POST   /read                ← Read file content
│   ├── POST   /write               ← Write file
│   ├── POST   /list                ← List directory
│   └── POST   /search              ← Search files
│
└── context/
    ├── POST   /analyze             ← Intent + context
    └── POST   /symbols             ← Index symbols
```

---

## UI Component Tree

```
ELECTRON + REACT COMPONENT HIERARCHY
═══════════════════════════════════════════════════════════════════

App.tsx
├── MainLayout
│   ├── Toolbar
│   │   ├── FileMenu
│   │   ├── EditMenu
│   │   ├── HelpMenu
│   │   └── [Model Selector]
│   │
│   ├── Sidebar
│   │   ├── FileExplorer
│   │   │   ├── FolderTree
│   │   │   │   └── FileItem (recursive)
│   │   │   ├── SearchBox
│   │   │   └── ContextMenu
│   │   │
│   │   ├── GitPanel
│   │   │   ├── BranchSelector
│   │   │   └── StatusView
│   │   │
│   │   └── SettingsPanel
│   │       ├── AISettings
│   │       ├── EditorSettings
│   │       └── AdvancedSettings
│   │
│   ├── MainContent
│   │   ├── TabBar
│   │   │   └── FileTab (multiple)
│   │   │
│   │   └── EditorArea
│   │       ├── Monaco Editor
│   │       ├── MiniMap
│   │       └── LineNumbers
│   │
│   ├── RightPanel
│   │   └── ChatPanel
│   │       ├── ChatHistory
│   │       │   └── ChatMessage (multiple)
│   │       │       ├── UserMessage
│   │       │       └── AssistantMessage
│   │       ├── InputBox
│   │       └── SendButton
│   │
│   └── BottomPanel
│       ├── Terminal
│       │   ├── TerminalOutput
│       │   └── TerminalInput
│       │
│       ├── Problems
│       │   └── ProblemList
│       │
│       └── Output
│           └── OutputLog
```

---

## Data Flow: Chat Message

```
TRACING ONE MESSAGE THROUGH THE ENTIRE SYSTEM
═══════════════════════════════════════════════════════════════════

Step 1: User Action (React)
───────────────────────────
React Component (ChatPanel):
  const [input, setInput] = useState("")
  onClick: sendMessage(input)
    → calls api.chat(input)


Step 2: Network (WebSocket)
──────────────────────────
client.ts:
  ws.send({
    "message": input,
    "context": { "selectedFile": "...", "selectedCode": "..." }
  })


Step 3: FastAPI Route
────────────────────
main.py / routes/agent.py:
  @app.websocket("/api/v1/agent/execute")
  async def ws_execute(websocket: WebSocket):
      editor = AICodeEditor(project_root, llm_client)
      request = await websocket.receive_json()
      result = editor.handle_request(request.message)
      for token in result:
        await websocket.send_json({"token": token})


Step 4: Orchestrator (Existing Code)
────────────────────────────────────
assistant/ai_editor/orchestrator.py:
  class AICodeEditor:
    def handle_request(self, message):
      1. intent = self._analyze_intent(message)
      2. retrieval = self.retriever.retrieve(intent)
      3. plan = self.planner.plan(intent, retrieval)
      4. For display: just return explanation
      5. Yield each token


Step 5: Model Provider
──────────────────────
providers/mlx.py or ollama.py:
  async def chat(messages):
    # Load model if needed
    # Generate tokens
    # Yield each token


Step 6: Response (WebSocket)
────────────────────────────
client.ts receives:
  { "token": "This" }
  { "token": " " }
  { "token": "function" }
  ...


Step 7: UI Update (React)
─────────────────────────
ChatPanel.tsx:
  async for token in api.chat(input):
    setResponse(prev => prev + token)
    
  User sees text appearing in real-time
```

---

## File Structure with Dependencies

```
DEPENDENCY GRAPH: Shows which files import what
═══════════════════════════════════════════════════════════════════

main.py
├── config.py
├── model_manager.py
│   ├── providers/base.py
│   ├── providers/ollama.py
│   │   └── assistant/ai_editor/ollama_models.py (EXISTING)
│   ├── providers/mlx.py
│   │   └── mlx-lm library
│   └── providers/airlm.py
│       └── airlm library
│
├── routes/agent.py
│   └── assistant/ai_editor/orchestrator.py (EXISTING)
│       ├── assistant/ai_editor/planner.py (EXISTING)
│       ├── assistant/ai_editor/editor.py (EXISTING)
│       ├── assistant/ai_editor/validator.py (EXISTING)
│       └── assistant/ai_editor/props_analyzer.py (EXISTING)
│
├── routes/files.py
│   └── tools/file_tools.py
│
├── routes/models.py
│   └── model_manager.py
│
└── routes/context.py
    └── assistant/ai_editor/retriever.py (EXISTING)

desktop/src/renderer/App.tsx
├── components/Editor.tsx
├── components/FileExplorer.tsx
├── components/ChatPanel.tsx
├── components/ModelSelector.tsx
├── components/Terminal.tsx
└── api/client.ts
    └── HTTP + WebSocket to main.py endpoints
```

---

## Request-Response Cycle

```
SIMPLE EXAMPLE: User loads a model
═══════════════════════════════════════════════════════════════════

USER ACTION
───────────
  User clicks: Model Selector → "Qwen 7B MLX" → [Load]


REACT COMPONENT
───────────────
  ModelSelector.tsx:
    onClick={() => api.loadModel("qwen-7b-mlx")}
      ↓
    client.ts:
      POST /api/v1/models/qwen-7b-mlx/load


FASTAPI ROUTE
─────────────
  routes/models.py:
    @app.post("/api/v1/models/{model_id}/load")
    async def load_model(model_id: str):
      manager.load_model(model_id, provider="mlx")
      return {"status": "loaded"}


MODEL MANAGER
─────────────
  model_manager.py:
    def load_model(model_id, provider):
      provider_instance = self.providers[provider]
      provider_instance.load_model(model_id)


PROVIDER
────────
  providers/mlx.py:
    async def load_model(model_id):
      model, tokenizer = load(model_path)  ← Uses MLX library
      self.loaded_model = model
      logger.info(f"Loaded: {model_id}")


RESPONSE FLOW
─────────────
  ← {"status": "loaded"}
  ← Response received by client.ts
  ← React state updated
  ← UI shows: "Model: Qwen 7B MLX (loaded)"
  ← User sees change immediately


UNDER THE HOOD
──────────────
  Behind the scenes now:
  - MLX model loaded in memory
  - Ready for inference
  - Can now receive /api/v1/chat requests
```

---

## Memory & Process Model

```
PROCESS LAYOUT: What runs where
═══════════════════════════════════════════════════════════════════

MACBOOK PRO 16GB UNIFIED MEMORY
═════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────┐
│ Electron Process (150 MB)                                   │
│ ├─ Main process (IPC)                                       │
│ └─ Renderer process (React + Monaco)                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Python/FastAPI Process (200 MB)                             │
│ ├─ Uvicorn ASGI server                                      │
│ ├─ Orchestrator instance                                    │
│ └─ Model Provider instances                                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Loaded AI Model (3-7 GB depending on size)                  │
│ ├─ MLX model (if loaded) - uses Metal/GPU                   │
│ └─ OR Ollama model (if loaded)                              │
└─────────────────────────────────────────────────────────────┘

Remaining: ~8-10 GB for OS, other processes


AUTO-UNLOAD STRATEGY
────────────────────
When switching models:
  1. User clicks different model
  2. Server unloads previous model (frees 3-7 GB)
  3. Server loads new model (uses 3-7 GB)
  4. Total always < 12 GB, leaves 4 GB buffer
```

---

## Error Handling Flow

```
ERROR SCENARIO: Model loading fails
═════════════════════════════════════════════════════════════════

User clicks [Load Model]
         ↓
    FastAPI route
         ↓
    try: provider.load_model()
    except Exception as e:
         ↓
    return {
      "status": "error",
      "error": {
        "code": "MODEL_LOAD_FAILED",
        "message": "MLX not installed. Install with: pip install mlx-lm",
        "recoverable": true
      }
    }
         ↓
    React receives error
         ↓
    Display in UI:
    ┌──────────────────────────────────┐
    │ ⚠ Failed to load model           │
    │                                  │
    │ MLX not installed. Install with: │
    │ pip install mlx-lm               │
    │                                  │
    │ [See Documentation] [Try Again] │
    └──────────────────────────────────┘
         ↓
    User can:
    - Click [Try Again] (after installing)
    - Select different provider/model
    - See detailed error logs


FALLBACK STRATEGY
─────────────────
If MLX provider fails:
  • Try Ollama provider (if available)
  • If Ollama fails, show user friendly error
  • Never crash the entire app
  • Always allow manual recovery
```

---

## This is a Complete System

These diagrams show:

1. ✅ **How components talk to each other**
2. ✅ **What happens on each request**
3. ✅ **Where data flows**
4. ✅ **How errors are handled**
5. ✅ **Memory constraints & solutions**
6. ✅ **UI component hierarchy**
7. ✅ **Provider architecture**

Everything is designed for **reliability**, **extensibility**, and **simplicity**.
