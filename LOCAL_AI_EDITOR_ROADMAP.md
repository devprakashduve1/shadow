# Local AI Editor: Integrated Implementation Roadmap

**Date**: August 11, 2026  
**Status**: Phase 1 (Planning) → Phase 2 (Backend API)  
**Existing Code**: 18 Python modules, 316 KB of sophisticated code editing engine  
**Goal**: Wrap existing engine in FastAPI + Electron UI with local model support

---

## What We Already Have ✅

### Code Editing Engine (100% Production-Ready)
- **Orchestrator** (`orchestrator.py`) - Main editing pipeline coordinator
- **Intent Analysis** - Classifies user requests (fix, feature, refactor, test, docs, debug)
- **Props Analyzer** - Extracts detailed requirements from natural language
- **Context Retriever** - Finds relevant files, symbols, dependencies
- **Planner** - Creates step-by-step execution plans
- **Code Editor** - Generates patches (replace, insert, delete, add_import)
- **Validator** - Checks syntax, imports, breaking changes
- **Review Manager** - Formats plans for user approval
- **Confirmation Handler** - User confirmation workflow

### Supporting Infrastructure
- **Schemas** - Complete data structures (IntentAnalysis, Plan, Patch, etc.)
- **Symbol Indexing** - AST-based code understanding
- **Ollama Integration** - Model discovery from running Ollama instance
- **File Operations** - Read, write, search files
- **Diff Generation** - Format code changes for review

**This is equivalent to ~8-10 weeks of work. We should not rewrite it.**

---

## What We Need to Add

### 1. FastAPI Backend (NEW)
Wrap the existing Python engine in REST/WebSocket endpoints:
- Model management (discover, load, unload)
- Provider abstraction (AirLLM, MLX, Ollama)
- Streaming chat
- Agent execution
- File operations
- Project context

### 2. Model Management (NEW)
Add support for local models beyond Ollama:
- MLX (Apple Silicon native)
- AirLLM (quantized models)
- Model discovery + selection
- Memory management

### 3. Electron + React UI (NEW)
Desktop application:
- File explorer + Monaco editor
- Model selector
- AI chat panel
- Terminal
- Plan review dialog
- Settings

### 4. Integration Glue (NEW)
Connect all pieces:
- IPC / WebSocket between Electron and FastAPI
- Streaming response handling
- File system operations
- Terminal execution
- Git integration

---

## Improved Architecture (Simplified)

```
┌─────────────────────────────────────────────────────┐
│           Electron Desktop App (React)              │
│  • Monaco Editor + File Explorer                    │
│  • Model Selector                                   │
│  • Chat Panel (streaming)                           │
│  • Terminal                                         │
│  • Settings                                         │
└─────────────────────────────────────────────────────┘
              ↕ (WebSocket + REST)
┌─────────────────────────────────────────────────────┐
│        FastAPI Server (New Integration Layer)       │
├─────────────────────────────────────────────────────┤
│ Routes: /api/models, /api/files, /api/chat, etc.   │
└─────────────────────────────────────────────────────┘
              ↕ (Uses)
┌─────────────────────────────────────────────────────┐
│    EXISTING Code Editing Engine (No Changes!)      │
│  • AICodeEditor (orchestrator.py)                   │
│  • Planner, Editor, Validator                       │
│  • Context Retriever                                │
│  • Props Analyzer                                   │
│  • Schemas & Data Models                            │
└─────────────────────────────────────────────────────┘
              ↕ (Uses)
┌─────────────────────────────────────────────────────┐
│    Model Providers (New)                            │
│  • MLXProvider (Apple Silicon)                      │
│  • AirLLMProvider (quantized)                       │
│  • OllamaProvider (existing, enhanced)              │
└─────────────────────────────────────────────────────┘
```

---

## Detailed Implementation Plan

### Phase 1: Backend Model Manager (Week 1)
**Goal**: Support multiple model providers, can load/unload models

#### 1.1 Create Provider Abstraction
```
providers/
├── __init__.py
├── base.py                    # Abstract LocalAIProvider
├── ollama.py                  # Enhanced (from existing code)
├── mlx.py                     # NEW: MLX provider
└── airlm.py                   # NEW: AirLLM provider
```

**Files to Create**: 3 new files (~500 lines total)

Key interface:
```python
class LocalAIProvider(ABC):
    async def discover_models() -> List[LocalModel]
    async def load_model(model_id: str)
    async def unload_model()
    async def chat(messages, temperature, max_tokens) -> AsyncIterable[str]
```

#### 1.2 Create Model Manager
```
model_manager.py              # NEW: Orchestrates providers
```

Features:
- Discover models from all providers
- Load/unload with memory tracking
- Save selected model to config
- Status reporting

#### 1.3 Create FastAPI Backend
```
main.py                       # NEW: FastAPI app entry point
config.py                     # NEW: Configuration loader
```

**Endpoints (REST)**:
```
GET    /api/v1/models
POST   /api/v1/models/scan
POST   /api/v1/models/{id}/load
POST   /api/v1/models/unload
GET    /api/v1/models/status
GET    /api/v1/providers
```

**Test**: Create simple FastAPI app that lists Ollama models

---

### Phase 2: Wrap Existing Code Editor in API (Week 2)
**Goal**: Expose orchestrator as FastAPI endpoints

#### 2.1 Create Agent Orchestrator
```
routes/
├── __init__.py
├── agent.py                  # NEW: /api/v1/agent/* endpoints
├── context.py                # NEW: /api/v1/context/* endpoints
└── files.py                  # NEW: /api/v1/files/* endpoints
```

**New Routes**:
```
POST   /api/v1/agent/analyze
       → Call existing IntentAnalyzer
       
POST   /api/v1/agent/plan
       → Call existing Planner
       
WS     /api/v1/agent/execute
       → Streaming execution with existing orchestrator
```

#### 2.2 Refactor Existing Engine for API Use
Minimal changes:
- Make `AICodeEditor` accept LLM provider
- Add async support where needed
- Create response models for API

**No rewrite of core logic** – just adapt interfaces.

#### 2.3 Add Streaming Support
Use existing orchestrator but stream responses:
```python
async def execute_agent_request(request):
    async for token in orchestrator.handle_request(request):
        yield {"type": "token", "content": token}
```

**Test**: Can call existing orchestrator via FastAPI endpoint

---

### Phase 3: Electron + React UI (Week 3-4)
**Goal**: VS Code-like desktop app with Monaco editor

#### 3.1 Project Setup
```
desktop/
├── src/
│   ├── main/
│   │   ├── index.ts
│   │   └── preload.ts
│   ├── renderer/
│   │   ├── index.tsx
│   │   ├── App.tsx
│   │   └── components/
│   │       ├── Editor.tsx
│   │       ├── FileExplorer.tsx
│   │       ├── ModelSelector.tsx
│   │       ├── ChatPanel.tsx
│   │       └── Terminal.tsx
│   └── types/
│       └── index.ts
├── package.json
└── vite.config.ts
```

**Dependencies**: Electron, React, TypeScript, Vite, Monaco, Socket.io

#### 3.2 Core Components
- **Editor**: Monaco + file tabs
- **FileExplorer**: Tree view with git status
- **ModelSelector**: Dropdown with model list + Load/Unload buttons
- **ChatPanel**: Streaming chat display
- **Terminal**: xterm.js integration

#### 3.3 State Management
- Use React Context or Zustand for:
  - Current model
  - Project path
  - Chat history
  - File contents
  - Terminal output

#### 3.4 API Client
```typescript
// src/api/client.ts
class APIClient {
    async listModels(): Promise<LocalModel[]>
    async loadModel(modelId: string)
    async chat(messages: Message[]): AsyncIterable<string>
    async executeAgent(request: AgentRequest)
    // ...
}
```

**Test**: UI connects to backend, displays list of models

---

### Phase 4: Chat & Streaming (Week 4-5)
**Goal**: Stream chat responses from local LLM in real-time

#### 4.1 Backend Streaming Endpoint
```python
@app.websocket("/api/v1/chat")
async def ws_chat(websocket: WebSocket):
    async for message in websocket.iter_json():
        async for token in provider.chat(message.messages):
            await websocket.send_json({
                "type": "token",
                "content": token
            })
```

#### 4.2 Frontend Chat Display
- Display tokens as they arrive
- Show thinking/processing indicator
- Allow cancellation mid-response

#### 4.3 Wire Up Model Manager
- Load/unload before chat
- Show memory usage
- Handle errors gracefully

**Test**: Chat with local model, see streaming response

---

### Phase 5: Agent with Tools (Week 5-7)
**Goal**: AI can read files, write files, execute terminal commands

#### 5.1 Add Agent Tools
```
agent_tools/
├── __init__.py
├── file_tools.py           # read, write, list, search
├── terminal_tools.py       # execute commands
└── git_tools.py            # git status, diff, commit
```

#### 5.2 Safe Execution
- Preview changes before applying
- Require user approval for destructive operations
- Log all operations
- Keep backups via git

#### 5.3 Review Dialog
Show diffs before applying:
```
[Code Change Review]
─────────────────
- old line
+ new line
─────────────────
[Approve] [Reject] [Edit]
```

**Test**: Agent can explain code, suggest fixes with diffs

---

### Phase 6: Advanced Features (Week 7-8)
**Goal**: Terminal, settings, git integration

#### 6.1 Integrated Terminal
- Spawn shell in project directory
- Capture output in UI
- Run tests/build commands
- Agent can use for commands

#### 6.2 Settings Panel
```
Settings
├── General
│   ├── Project Path
│   ├── Auto-load Model
│   └── Theme
├── AI
│   ├── Provider
│   ├── Chat Model
│   ├── Temperature
│   └── Max Tokens
├── Models
│   ├── Model Path
│   ├── Cache Path
│   └── Memory Limit
└── Advanced
    ├── Developer Tools
    └── Logs
```

#### 6.3 Git Integration
- Show branch in UI
- View diffs before applying changes
- Auto-commit option
- Show modified files

**Test**: Can load/unload models, run terminal commands, approve changes

---

### Phase 7: Polish & Testing (Week 8-9)
**Goal**: Production-ready, tested, documented

#### 7.1 Backend Tests
```
tests/
├── test_providers.py        # Provider interface
├── test_model_manager.py    # Model discovery
├── test_agent.py            # Agent integration
├── test_api.py              # FastAPI routes
└── test_e2e.py              # End-to-end workflows
```

Target: 80%+ code coverage for new code

#### 7.2 Frontend Tests
- Component tests (React Testing Library)
- API client mocks
- E2E tests (Cypress or Playwright)

#### 7.3 Performance
- Profile model loading time
- Optimize token streaming
- Cache model metadata
- Lazy-load UI components

#### 7.4 Error Handling
- Graceful degradation if model fails
- Meaningful error messages
- Recovery workflows
- Logging & debugging

---

### Phase 8: Distribution (Week 9-10)
**Goal**: macOS app bundle ready to distribute

#### 8.1 Code Signing & Notarization
```bash
codesign -s "Developer ID" MyApp.app
xcrun notarytool submit MyApp.dmg ...
```

#### 8.2 Installer
```
MyApp-1.0.0.dmg
├── MyApp.app
├── Applications (shortcut)
└── README
```

#### 8.3 Auto-Updates
Electron auto-updater configuration

#### 8.4 Release Notes
Document features, improvements, fixes

---

## Revised Directory Structure

```
shadow/
├── apps/
│   ├── ai-server/
│   │   ├── src/
│   │   │   ├── main.py                     (NEW)
│   │   │   ├── config.py                   (NEW)
│   │   │   ├── providers/
│   │   │   │   ├── base.py                 (NEW)
│   │   │   │   ├── ollama.py               (NEW wrapper)
│   │   │   │   ├── mlx.py                  (NEW)
│   │   │   │   └── airlm.py                (NEW)
│   │   │   ├── model_manager.py            (NEW)
│   │   │   ├── routes/
│   │   │   │   ├── agent.py                (NEW)
│   │   │   │   ├── context.py              (NEW)
│   │   │   │   └── files.py                (NEW)
│   │   │   └── tools/
│   │   │       ├── file_tools.py           (NEW)
│   │   │       ├── terminal_tools.py       (NEW)
│   │   │       └── git_tools.py            (NEW)
│   │   ├── requirements.txt                (UPDATE)
│   │   └── tests/                          (NEW, comprehensive)
│   │
│   └── desktop/
│       ├── src/
│       │   ├── main/index.ts               (NEW)
│       │   ├── renderer/
│       │   │   ├── App.tsx                 (NEW)
│       │   │   └── components/             (NEW)
│       │   ├── api/client.ts               (NEW)
│       │   └── types/index.ts              (NEW)
│       ├── package.json                    (NEW)
│       └── vite.config.ts                  (NEW)
│
├── assistant/
│   └── ai_editor/                          ← KEEP AS-IS (no changes needed)
│       ├── orchestrator.py
│       ├── editor.py
│       ├── planner.py
│       ├── validator.py
│       ├── schemas.py
│       └── ... (17 other files unchanged)
│
├── docs/
│   ├── ARCHITECTURE.md                     (KEEP - reference)
│   ├── IMPLEMENTATION_GUIDE.md             (NEW - this file)
│   └── API_REFERENCE.md                    (NEW)
│
├── Makefile                                 (UPDATE - add dev targets)
└── requirements.txt                         (UPDATE - add fastapi)
```

---

## Implementation Strategy

### Do NOT
- ❌ Rewrite the orchestrator/planner/editor
- ❌ Change existing data structures
- ❌ Add breaking changes to existing code
- ❌ Try to build everything at once

### Do
- ✅ Keep existing code as-is (it works!)
- ✅ Build API wrappers around it
- ✅ Add new features (providers, UI, tools) separately
- ✅ Test incrementally
- ✅ Deploy each phase as a working milestone

### Risk Mitigation
| Risk | Mitigation |
|------|-----------|
| Breaking existing code | Keep ai_editor/ untouched, only add wrappers |
| Model loading fails | Graceful fallback to Ollama-only mode |
| UI doesn't update | Use WebSocket for real-time updates |
| Performance issues | Stream responses, profile early, optimize late |
| File operation errors | Show diff, require approval, auto-commit |

---

## Week-by-Week Timeline

| Week | Focus | Deliverable |
|------|-------|------------|
| 1 | Providers + Model Manager | FastAPI server lists models |
| 2 | Agent API wrappers | Can call orchestrator via HTTP |
| 3-4 | Electron UI skeleton | Monaco editor, file explorer, model selector |
| 5 | Chat streaming | Real-time chat with local LLM |
| 6 | Agent tools | Read/write files, execute terminal, git |
| 7 | Review UI + git integration | Approve/reject changes |
| 8 | Settings, terminal, polish | Production-grade UX |
| 9 | Testing + documentation | Comprehensive tests, user docs |
| 10 | Packaging | Distributable .dmg |

---

## Success Criteria

### After Phase 2 (Week 2)
- [ ] FastAPI server runs
- [ ] Can list Ollama models
- [ ] Can call existing orchestrator via REST API
- [ ] Basic error handling

### After Phase 4 (Week 5)
- [ ] Electron app launches
- [ ] Shows list of available models
- [ ] Can chat with local LLM
- [ ] Streaming tokens display in real-time

### After Phase 6 (Week 7)
- [ ] File explorer works
- [ ] Can read/edit files
- [ ] Review diffs before applying
- [ ] Terminal integration

### Final (Week 10)
- [ ] All features working
- [ ] 80%+ test coverage
- [ ] User documentation
- [ ] Distributable macOS app

---

## Critical Dependencies

### For MLX Provider
- Requires MLX Python library: `pip install mlx-lm`
- Only works on Apple Silicon (M1/M2/M3/etc.)
- Models must be in MLX format or converted

### For AirLLM Provider
- Requires AirLLM library: `pip install airlm`
- Supports GGUF quantized models
- Compatible with HuggingFace model format

### For UI Development
- Node.js 18+
- pnpm (faster than npm)
- Electron requires macOS dev tools

### For FastAPI
- Python 3.10+
- FastAPI, Uvicorn
- Pydantic for validation

---

## Questions Before Starting

1. **Model Priority**: Start with Ollama + MLX, or add AirLLM support first?
2. **UI Framework**: React (chosen) or alternatives?
3. **IPC Method**: WebSocket (chosen) or Electron IPC?
4. **Test Coverage Target**: 80% or higher?
5. **Distribution**: Just .dmg or also homebrew/app store?

---

## Next Steps

1. **Week 1**: Start Phase 1 (providers + model manager)
2. **Daily progress**: Show working code every day
3. **Weekly sync**: Review progress, adjust plan as needed
4. **Measurement**: Track % complete per phase

This plan keeps existing code pristine, builds incrementally, and delivers working features every 1-2 weeks.
