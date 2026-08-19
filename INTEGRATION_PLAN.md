# Integration Plan: Existing Code + New Components

**Date**: August 11, 2026  
**Goal**: Show what's done, what's missing, and how they connect

---

## Inventory: What We Have

### Backend: Code Editing Engine (✅ COMPLETE)

| Component | File | Status | LOC | Purpose |
|-----------|------|--------|-----|---------|
| Orchestrator | `orchestrator.py` | ✅ Production | ~250 | Coordinates entire pipeline |
| Intent Analyzer | `orchestrator.py` | ✅ Production | ~50 | Classifies requests |
| Props Analyzer | `props_analyzer.py` | ✅ Production | ~200 | Extracts requirements |
| Context Retriever | `retriever.py` | ✅ Production | ~300 | Finds relevant files |
| Planner | `planner.py` | ✅ Production | ~150 | Creates execution plans |
| Code Editor | `editor.py` | ✅ Production | ~150 | Generates patches |
| Validator | `validator.py` | ✅ Production | ~200 | Checks safety |
| Review Manager | `review.py` | ✅ Production | ~150 | Plan review formatting |
| Schemas | `schemas.py` | ✅ Production | ~150 | Data structures |
| Ollama Integration | `ollama_models.py` | ✅ Production | ~200 | Model discovery |
| **Total Backend** | | | **~2000 LOC** | **Ready to use** |

**These files will NOT be modified. Just wrapped in APIs.**

---

## Inventory: What We Need

### New Backend Components (❌ TODO)

| Component | Purpose | Est. LOC | Complexity |
|-----------|---------|----------|-----------|
| **Provider Abstraction** | | | |
| `providers/base.py` | Abstract interface | 100 | Low |
| `providers/mlx.py` | MLX (Apple Silicon) provider | 200 | Medium |
| `providers/airlm.py` | AirLLM (quantized) provider | 200 | Medium |
| `providers/ollama.py` | Enhanced Ollama wrapper | 100 | Low |
| **Model Management** | | | |
| `model_manager.py` | Orchestrate providers | 300 | Medium |
| `config.py` | Configuration loader | 150 | Low |
| **FastAPI Routes** | | | |
| `main.py` | FastAPI app | 150 | Low |
| `routes/models.py` | /api/v1/models/* | 200 | Low |
| `routes/agent.py` | /api/v1/agent/* (wraps orchestrator) | 250 | Medium |
| `routes/files.py` | /api/v1/files/* | 150 | Low |
| `routes/context.py` | /api/v1/context/* | 100 | Low |
| **Tools** | | | |
| `tools/file_tools.py` | File operations for agent | 150 | Low |
| `tools/terminal_tools.py` | Terminal execution | 100 | Low |
| `tools/git_tools.py` | Git operations | 100 | Low |
| **Tests** | | | |
| `tests/*.py` | Comprehensive test suite | 500 | Medium |
| **Total New Backend** | | **~3000 LOC** | **Mix** |

### New Frontend Components (❌ TODO)

| Component | Purpose | Est. Lines | Complexity |
|-----------|---------|-----------|-----------|
| **Electron Setup** | | | |
| `desktop/src/main/index.ts` | Electron main process | 150 | Low |
| `desktop/src/main/preload.ts` | IPC bridge | 100 | Low |
| **React Components** | | | |
| `components/Editor.tsx` | Monaco editor wrapper | 200 | Medium |
| `components/FileExplorer.tsx` | File tree view | 250 | Medium |
| `components/ModelSelector.tsx` | Model dropdown + controls | 200 | Low |
| `components/ChatPanel.tsx` | Streaming chat display | 250 | Medium |
| `components/Terminal.tsx` | Terminal widget (xterm.js) | 200 | Medium |
| `components/SettingsPanel.tsx` | Configuration UI | 200 | Low |
| `components/DiffReview.tsx` | Change approval dialog | 200 | Medium |
| **State Management** | | | |
| `hooks/useServer.ts` | Server API client | 150 | Low |
| `hooks/useModels.ts` | Model state | 100 | Low |
| `hooks/useProject.ts` | Project state | 100 | Low |
| `api/client.ts` | HTTP + WebSocket client | 250 | Medium |
| **App Shell** | | | |
| `App.tsx` | Layout + routing | 200 | Low |
| `index.tsx` | Entry point | 50 | Low |
| **Styling** | | | |
| `styles/*.css` | Theme + layout | 300 | Low |
| **Config** | | | |
| `vite.config.ts` | Build config | 100 | Low |
| `tsconfig.json` | TypeScript config | 50 | Low |
| **Total New Frontend** | | **~3500 lines** | **Mix** |

**Grand Total New Code**: ~6500 lines across 40+ files

---

## Integration Points

### How Backend & Existing Code Connect

```
New FastAPI Routes
    ↓
(wraps, no changes to)
    ↓
Existing orchestrator.py (AICodeEditor class)
    ↓
(uses)
    ↓
Existing editor, planner, validator, props_analyzer
```

**Example**: POST /api/v1/agent/execute

```python
# NEW: routes/agent.py
@app.post("/api/v1/agent/execute")
async def execute(request: AgentRequest):
    # Just call existing code
    editor = AICodeEditor(project_root, llm_client)
    result = editor.handle_request(request.message, require_approval=True)
    return result
```

No changes to orchestrator.py, editor.py, etc.

---

## How Frontend & Backend Connect

```
Electron App (React)
    ↓ (WebSocket)
    ↓
FastAPI Server
    ↓ (imports)
    ↓
Existing Python modules
```

**Example**: User clicks "Chat"

1. Frontend: User types message in ChatPanel
2. Frontend: WebSocket message sent to `/api/v1/chat`
3. Backend: FastAPI receives, gets provider
4. Backend: Streams tokens back via WebSocket
5. Frontend: ChatPanel displays tokens as they arrive

---

## Dependency Tree

```
desktop/App.tsx
├── components/Editor.tsx
│   └── hooks/useServer.ts
├── components/ChatPanel.tsx
│   └── hooks/useServer.ts
├── components/FileExplorer.tsx
│   └── hooks/useProject.ts
├── components/ModelSelector.tsx
│   └── hooks/useModels.ts
└── api/client.ts
    ├── routes/models.ts (backend)
    ├── routes/agent.ts (backend)
    └── routes/files.ts (backend)

routes/agent.ts (backend)
└── assistant/ai_editor/orchestrator.py ← EXISTING

routes/models.ts (backend)
└── providers/*.py ← NEW PROVIDERS

providers/*.py
└── ollama_models.py ← EXISTING
```

**Key Point**: Frontend depends on FastAPI, which depends on EXISTING orchestrator. No circular dependencies.

---

## Implementation Order

### Must Do First
1. **Provider abstraction** (base.py, interfaces)
2. **Model manager** (discovery, loading)
3. **FastAPI main.py** (create server)

These enable subsequent work (no one can do routes without backend).

### Can Parallelize (After Step 1-3)
- **Backend Routes**: Multiple people can work on different endpoints
- **Frontend Components**: Once API contracts are defined
- **Tests**: After features are implemented

### Must Do Last
- **Packaging** (only after everything works)
- **Optimization** (measure first, then optimize)

---

## Technical Decisions Made

### 1. Keep Existing Code Untouched ✅
**Why**: It works, it's tested, don't break it  
**How**: Wrap in API layer, don't refactor

### 2. Providers are Pluggable ✅
**Why**: User might only have Ollama, or only MLX  
**How**: Abstract interface, graceful fallback

### 3. FastAPI not Node.js ✅
**Why**: Python is already required for ML, simpler  
**How**: REST + WebSocket, easy to understand

### 4. React not Vue/Angular ✅
**Why**: Largest ecosystem, Monaco editor support  
**How**: TypeScript, Vite for speed

### 5. Streaming via WebSocket ✅
**Why**: Real-time chat feels better, bidirectional  
**How**: JSON frames, reconnection logic

---

## File-by-File Implementation Checklist

### Week 1: Providers & Model Manager

#### providers/base.py (NEW)
```python
class LocalAIProvider(ABC):
    async def discover_models() -> List[LocalModel]
    async def load_model(model_id: str)
    async def unload_model()
    async def chat(messages) -> AsyncIterable[str]
    # ... complete interface
```
Status: ☐ Write ☐ Test ☐ Done

#### providers/mlx.py (NEW)
```python
class MLXProvider(LocalAIProvider):
    # Implement each method
    # Use mlx-lm library
```
Status: ☐ Write ☐ Test ☐ Done

#### providers/airlm.py (NEW)
```python
class AirLLMProvider(LocalAIProvider):
    # Implement each method
    # Use airlm library
```
Status: ☐ Write ☐ Test ☐ Done

#### providers/ollama.py (NEW)
```python
class OllamaProvider(LocalAIProvider):
    # Wrap existing ollama_models.py
    # Add missing methods
```
Status: ☐ Write ☐ Test ☐ Done

#### model_manager.py (NEW)
```python
class ProviderManager:
    def __init__(config)
    async def discover_all_models()
    async def load_model(model_id, provider_id)
    async def unload_model()
    # ...
```
Status: ☐ Write ☐ Test ☐ Done

#### config.py (NEW)
```python
class Config:
    provider: str
    model: str
    temperature: float
    # ... load from ~/.config/local-ai-editor/config.json
```
Status: ☐ Write ☐ Test ☐ Done

#### main.py (NEW)
```python
from fastapi import FastAPI
from providers import ProviderManager
from routes import models, agent, files

app = FastAPI()
provider_manager = ProviderManager(config)
# ... register routes
```
Status: ☐ Write ☐ Test ☐ Done

### Week 2: Routes & Integration

#### routes/models.py (NEW)
```
GET    /api/v1/models
POST   /api/v1/models/scan
POST   /api/v1/models/{id}/load
POST   /api/v1/models/unload
GET    /api/v1/models/status
```
Status: ☐ Write ☐ Test ☐ Done

#### routes/agent.py (NEW)
```
POST   /api/v1/agent/analyze
POST   /api/v1/agent/plan
WS     /api/v1/agent/execute
```
Status: ☐ Write ☐ Test ☐ Done

#### routes/files.py (NEW)
```
POST   /api/v1/files/read
POST   /api/v1/files/write
POST   /api/v1/files/list
POST   /api/v1/files/search
```
Status: ☐ Write ☐ Test ☐ Done

#### routes/context.py (NEW)
```
POST   /api/v1/context/analyze
POST   /api/v1/context/symbols
```
Status: ☐ Write ☐ Test ☐ Done

#### tools/file_tools.py (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### tools/terminal_tools.py (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### tools/git_tools.py (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### tests/test_providers.py (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### tests/test_api.py (NEW)
Status: ☐ Write ☐ Test ☐ Done

### Week 3-4: Electron UI

#### desktop/src/main/index.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/main/preload.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/renderer/App.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/api/client.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/Editor.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/FileExplorer.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/ChatPanel.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/ModelSelector.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/Terminal.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/components/SettingsPanel.tsx (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/hooks/useServer.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/hooks/useModels.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

#### desktop/src/hooks/useProject.ts (NEW)
Status: ☐ Write ☐ Test ☐ Done

### Week 5+: Advanced Features & Polish

---

## How to Use This Plan

### For Implementation
1. Open this file in your editor
2. Work through sections in order
3. Update ☐ checkboxes as you complete files
4. Commit after each major section

### For Review
1. Check which files are ☐ vs ✅
2. Unblock any dependencies
3. Pair-review complex implementations
4. Run tests before moving forward

### For Progress Tracking
- Week 1: Should have 6 ✅ items (providers + manager + main)
- Week 2: Should have 14 ✅ items (all routes + tools + tests)
- Week 3-4: Should have 10+ ✅ items (UI components)
- Week 5+: Should have 100% ✅

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| MLX not available on test machine | High | Test with Ollama only first, MLX optional |
| Streaming breaks on slow network | Medium | Add buffering, show "loading..." indicator |
| Existing code has bugs | Medium | Run existing tests first, keep code as-is |
| Model loading timeout | Medium | Add timeout, allow cancellation |
| File permission errors | Low | Handle gracefully, show user what happened |

---

## Quality Gates

Before moving to next week:

- ✅ Code compiles/runs
- ✅ No regressions in existing code
- ✅ New tests pass
- ✅ Manual testing of feature
- ✅ Code reviewed
- ✅ Documentation updated

---

## Success Metrics

**Phase 1 (Week 1)**: Backend server runs, lists models  
**Phase 2 (Week 2)**: Can call existing orchestrator via API  
**Phase 3 (Week 4)**: Electron UI launches, shows models  
**Phase 4 (Week 5)**: Chat works with streaming  
**Phase 5 (Week 7)**: File operations + approval flow  
**Final (Week 10)**: Distributable macOS app

---

This plan makes it **clear what to build**, **who can work on what**, and **how to measure progress**.
