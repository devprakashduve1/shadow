# Local AI Code Editor for macOS: Architecture & Implementation Plan

**Date**: August 11, 2026  
**Target Platform**: macOS (Apple M-series)  
**Goal**: Production-quality, extensible local-first AI code editor

---

## Executive Summary

This document proposes a **production-grade desktop IDE** with these core characteristics:

- **100% Local Inference**: No cloud API dependencies (AI models run on your M3 Mac)
- **Multiple Provider Support**: AirLLM, MLX, Ollama (extensible)
- **VS Code-like IDE**: File explorer, Monaco editor, terminal, git integration
- **AI-first Workflow**: Chat panel, code actions, AI agent with filesystem/terminal tools
- **Apple Silicon Optimized**: Uses Metal/MLX for M-series acceleration
- **Incremental Implementation**: Build in phases, test often, don't try to build everything at once

---

## Part 1: ARCHITECTURE OVERVIEW

### 1.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    DESKTOP (Electron)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │   Monaco     │  │  File        │  │   AI Chat Panel    │ │
│  │   Editor     │  │  Explorer    │  │  (streaming)       │ │
│  │              │  │  Git panel   │  │                    │ │
│  └──────────────┘  └──────────────┘  └────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Terminal    │  │  Problems    │  │  Settings/         │ │
│  │  (bash)      │  │  Output      │  │  Model Selector    │ │
│  └──────────────┘  └──────────────┘  └────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
                      [IPC Bridge / WebSocket]
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  LOCAL AI SERVER (FastAPI)                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Provider Abstraction Layer                  │ │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐           │ │
│  │  │ AirLLM    │  │   MLX     │  │  Ollama   │           │ │
│  │  │ Provider  │  │ Provider  │  │ Provider  │           │ │
│  │  └───────────┘  └───────────┘  └───────────┘           │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Agent System (Planning + Tools)             │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │ │
│  │  │ Intent   │  │ Planning │  │ Code     │             │ │
│  │  │ Analyzer │  │ Agent    │  │ Editor   │             │ │
│  │  └──────────┘  └──────────┘  └──────────┘             │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │ │
│  │  │ File     │  │ Terminal │  │ Git      │             │ │
│  │  │ Tools    │  │ Tools    │  │ Tools    │             │ │
│  │  └──────────┘  └──────────┘  └──────────┘             │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │          Project Context & Symbol Indexing              │ │
│  │  • AST-aware symbol extraction                          │ │
│  │  • File tree with metadata                              │ │
│  │  • Embedding-based search (optional fallback)           │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
                   [Filesystem, Terminal, Models]
```

### 1.2 Technology Stack

**Desktop (Electron):**
- Electron 32+
- React 18+ (TSX)
- TypeScript 5+
- Vite (build tool)
- Monaco Editor (code editor)
- Socket.io or WebSocket (server communication)

**Backend (Python):**
- FastAPI 0.100+
- Python 3.10+
- Uvicorn (ASGI server)
- Pydantic (type validation)
- Pathlib (filesystem operations)
- AST (Python syntax parsing)

**AI/ML:**
- AirLLM (local quantized models)
- MLX (Apple Silicon inference)
- Ollama (for optional remote or local models)
- Sentence-transformers (embeddings, optional)

**Development:**
- pnpm (package manager, faster than npm)
- ESLint + Prettier (linting/formatting)
- pytest (Python testing)

---

## Part 2: PROPOSED DIRECTORY STRUCTURE

```
local-ai-editor/
├── apps/
│   ├── desktop/
│   │   ├── src/
│   │   │   ├── main/              # Electron main process
│   │   │   │   ├── index.ts
│   │   │   │   ├── preload.ts     # IPC bridge
│   │   │   │   └── window.ts
│   │   │   ├── renderer/          # React UI
│   │   │   │   ├── index.tsx
│   │   │   │   ├── App.tsx
│   │   │   │   ├── components/
│   │   │   │   │   ├── Editor.tsx
│   │   │   │   │   ├── FileExplorer.tsx
│   │   │   │   │   ├── AIChatPanel.tsx
│   │   │   │   │   ├── Terminal.tsx
│   │   │   │   │   ├── ModelSelector.tsx
│   │   │   │   │   └── SettingsPanel.tsx
│   │   │   │   ├── hooks/
│   │   │   │   │   ├── useServer.ts
│   │   │   │   │   ├── useModels.ts
│   │   │   │   │   └── useProject.ts
│   │   │   │   └── types/
│   │   │   │       └── index.ts
│   │   │   ├── api/
│   │   │   │   └── index.ts       # IPC/WebSocket client
│   │   │   └── styles/
│   │   │       └── index.css
│   │   ├── public/
│   │   └── vite.config.ts
│   │
│   └── ai-server/
│       ├── src/
│       │   ├── main.py            # FastAPI app entry
│       │   ├── config.py
│       │   ├── models/
│       │   │   ├── __init__.py
│       │   │   ├── schemas.py      # Pydantic models
│       │   │   └── enums.py
│       │   ├── providers/
│       │   │   ├── __init__.py
│       │   │   ├── base.py         # Abstract provider
│       │   │   ├── airlm.py
│       │   │   ├── mlx.py
│       │   │   └── ollama.py
│       │   ├── agents/
│       │   │   ├── __init__.py
│       │   │   ├── intent.py
│       │   │   ├── planner.py
│       │   │   ├── editor.py
│       │   │   ├── tools/
│       │   │   │   ├── filesystem.py
│       │   │   │   ├── terminal.py
│       │   │   │   └── git.py
│       │   │   └── orchestrator.py
│       │   ├── context/
│       │   │   ├── __init__.py
│       │   │   ├── retriever.py    # File finding
│       │   │   ├── indexer.py      # Symbol indexing
│       │   │   └── validator.py    # Patch validation
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── models.py       # /models endpoints
│       │   │   ├── chat.py         # /chat endpoints
│       │   │   ├── files.py        # /files endpoints
│       │   │   └── agent.py        # /agent endpoints
│       │   └── utils/
│       │       ├── __init__.py
│       │       ├── logger.py
│       │       └── validation.py
│       ├── tests/
│       │   ├── test_providers.py
│       │   ├── test_agents.py
│       │   └── conftest.py
│       ├── requirements.txt
│       ├── pyproject.toml
│       └── Makefile
│
├── packages/
│   ├── shared/                     # Shared TypeScript types
│   │   ├── src/
│   │   │   ├── models.ts
│   │   │   ├── messages.ts
│   │   │   └── index.ts
│   │   └── package.json
│   │
│   └── editor-config/              # Shared editor configs
│       ├── .eslintrc.json
│       ├── .prettierrc.json
│       └── tsconfig.json
│
├── scripts/
│   ├── dev.sh                      # Start both servers in dev mode
│   ├── build.sh                    # Build for production
│   ├── install-models.sh           # Download initial models
│   └── test.sh                     # Run all tests
│
├── models/                         # AI models (gitignored)
│   ├── airlm/
│   ├── mlx/
│   └── ollama/
│
├── docs/
│   ├── ARCHITECTURE.md             # This file
│   ├── SETUP.md                    # Getting started
│   ├── API.md                      # FastAPI endpoints
│   ├── CONTRIBUTING.md
│   └── PROVIDERS.md                # Provider-specific docs
│
├── .claude/
│   └── settings.json               # Claude Code settings
├── .gitignore
├── .prettierrc.json
├── .eslintrc.json
├── pnpm-workspace.yaml
├── package.json                    # Root workspace
├── tsconfig.json
└── README.md
```

---

## Part 3: KEY TYPE DEFINITIONS

### 3.1 TypeScript Interfaces (Frontend)

```typescript
// apps/desktop/src/types/index.ts

// ===== MODEL MANAGEMENT =====
interface LocalModel {
  id: string;
  name: string;
  provider: "airlm" | "mlx" | "ollama";
  path?: string;                          // Local filesystem path
  parameters?: string;                    // "7B", "13B", etc.
  quantization?: string;                  // "q4", "q5", "q8"
  contextLength?: number;
  capabilities: {
    chat: boolean;
    codeCompletion: boolean;
    codeEditing: boolean;
    reasoning: boolean;
    toolCalling: boolean;
    vision: boolean;
  };
  memoryEstimate?: number;                // MB
  status: "available" | "loading" | "loaded" | "unavailable" | "error";
  lastUsed?: Date;
  errorMessage?: string;
}

interface ModelStatus {
  modelId: string;
  status: "available" | "loading" | "loaded" | "unloading" | "error";
  loadedAt?: Date;
  memoryUsed?: number;                    // MB
  temperature: number;
  maxTokens: number;
  contextLength: number;
}

interface AIProvider {
  id: string;
  name: string;
  installed: boolean;
  version?: string;
  configPath?: string;
}

// ===== EDITOR =====
interface EditorFile {
  id: string;
  path: string;
  name: string;
  language: string;
  content: string;
  isDirty: boolean;
  isModified: boolean;
  lastSaved?: Date;
}

interface EditorProject {
  rootPath: string;
  name: string;
  files: EditorFile[];
  currentFile?: string;
}

// ===== AI CHAT =====
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  tokens?: number;
  modelId?: string;
}

interface ChatSession {
  id: string;
  messages: ChatMessage[];
  selectedModel: string;
  createdAt: Date;
}

// ===== AI AGENT =====
interface AgentRequest {
  userMessage: string;
  context: {
    selectedFile?: string;
    selectedCode?: string;
    activeTab?: string;
    projectPath?: string;
  };
  options?: {
    temperature?: number;
    maxTokens?: number;
  };
}

interface AgentAction {
  type: "think" | "read_file" | "write_file" | "search" | "execute" | "review";
  target?: string;
  content?: string;
  status: "pending" | "in_progress" | "completed" | "failed";
}

// ===== SERVER RESPONSE =====
interface APIResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
  };
}

interface StreamedResponse {
  id: string;
  type: "token" | "action" | "complete" | "error";
  payload: unknown;
}
```

### 3.2 Python Data Models (Backend)

```python
# apps/ai-server/src/models/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
from datetime import datetime

# ===== MODEL MANAGEMENT =====
class ModelCapabilities(BaseModel):
    chat: bool = True
    code_completion: bool = False
    code_editing: bool = False
    reasoning: bool = False
    tool_calling: bool = False
    vision: bool = False

class LocalModel(BaseModel):
    id: str
    name: str
    provider: Literal["airlm", "mlx", "ollama"]
    path: Optional[str] = None
    parameters: Optional[str] = None  # "7B", "13B"
    quantization: Optional[str] = None  # "q4", "q5"
    context_length: Optional[int] = None
    capabilities: ModelCapabilities
    memory_estimate: Optional[int] = None  # MB
    status: Literal["available", "loading", "loaded", "unavailable", "error"]
    error_message: Optional[str] = None
    last_used: Optional[datetime] = None

class ModelStatus(BaseModel):
    model_id: str
    status: Literal["available", "loading", "loaded", "unloading", "error"]
    loaded_at: Optional[datetime] = None
    memory_used: Optional[int] = None  # MB
    temperature: float = 0.2
    max_tokens: int = 2000
    context_length: int = 4096

# ===== AI PROVIDERS =====
class ProviderInfo(BaseModel):
    id: str
    name: str
    installed: bool
    version: Optional[str] = None
    config_path: Optional[str] = None

# ===== FILES =====
class FileInfo(BaseModel):
    path: str
    name: str
    language: str
    size_bytes: int
    last_modified: datetime

class FileContent(BaseModel):
    path: str
    content: str
    language: str

# ===== AI CHAT =====
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model_id: str
    temperature: float = 0.2
    max_tokens: int = 2000
    context_length: int = 4096

class ChatResponse(BaseModel):
    id: str
    message: str
    tokens_used: int
    model_id: str

# ===== AGENT =====
class IntentAnalysis(BaseModel):
    intent_type: Literal["fix", "feature", "refactor", "test", "docs", "debug", "explain"]
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    summary: str
    keywords: List[str]
    likely_symbols: List[str]
    complexity_score: int = Field(1, ge=1, le=5)
    estimated_files: int
    breaking_changes_risk: Literal["low", "medium", "high"]

class PlanStep(BaseModel):
    step_number: int
    action: Literal["understand", "modify", "create", "delete", "refactor"]
    file: str
    target_function: Optional[str] = None
    change_type: Optional[str] = None
    details: str

class Plan(BaseModel):
    plan_id: str
    steps: List[PlanStep]
    estimated_impact: Dict
    requires_user_approval: bool
    estimated_tokens: int

class AgentRequest(BaseModel):
    user_message: str
    context: Optional[Dict] = None
    options: Optional[Dict] = None

class PatchOperation(BaseModel):
    type: Literal["replace", "add_import", "insert", "delete"]
    search: Optional[str] = None
    replacement: Optional[str] = None
    line: Optional[int] = None

class Patch(BaseModel):
    file: str
    operations: List[PatchOperation]
    validation: Optional[Dict] = None
```

---

## Part 4: COMMUNICATION PROTOCOL

### 4.1 Electron ↔ FastAPI Communication

**Method**: WebSocket + REST (hybrid approach)

```typescript
// REST for one-shot requests
GET    /api/models                 → List available models
POST   /api/models/load            → Load a model
POST   /api/models/unload          → Unload current model
GET    /api/models/status          → Get model status
POST   /api/files/read             → Read file
POST   /api/files/write            → Write file
GET    /api/files/list             → List files in directory

// WebSocket for streaming
WS     /api/chat                   → Streaming chat messages
WS     /api/agent                  → Streaming agent actions
WS     /api/completion             → Code completion (streaming)
```

### 4.2 Example: Chat Flow

```
Client (Electron)
   │
   ├─→ [User types "Explain this function"]
   │
   ├─→ [Extract selected code as context]
   │
   └─→ POST /api/context/analyze  {selectedCode, selectedFile}
        │
        └────────────────────────────────────→ FastAPI Server
                                                │
                                              (1) IntentAnalyzer
                                                  intent = analyze(message)
                                                │
                                              (2) ContextRetriever
                                                  relevant_files = retrieve(intent)
                                                │
                                              (3) Planner
                                                  plan = create_plan(intent, context)
                                                │
                                              (4) Check if needs approval
                                                  if needs_approval:
                                                    return plan for review
                                                  else:
                                                    proceed to execution
                                                │
                                              (5) CodeEditor
                                                  patches = generate_patches(plan)
                                                │
                                              (6) Validator
                                                  validate_patches(patches)
                                                │
                                              (7) Apply & Test
                                                  apply_patches(patches)
                                                  test_results = run_tests()
                                                │
        ┌────────────────────────────────────← Stream result back
        │
   ┌────┴─────────────────────────────────┐
   │ WS: /api/chat (streaming)            │
   │ {type: "token", content: "..."}      │
   │ {type: "token", content: "..."}      │
   │ {type: "complete", ...}              │
   │
   └─→ [Render response in chat panel]
```

---

## Part 5: MODEL DISCOVERY STRATEGY

### 5.1 Discovery Workflow

When the app starts, it runs this sequence:

```
1. Load saved configuration (~/.config/local-ai-editor/config.json)
   └─ Selected model ID
   └─ Provider settings

2. Scan for installed models (parallel):
   ├─ AirLLM: Check ~/.airlm/models
   ├─ MLX: Check ~/.mlx_models
   ├─ Ollama: Call /api/tags (if Ollama running)
   └─ Hugging Face: Check ~/.cache/huggingface/hub

3. Build model registry:
   ├─ id, name, provider, path, quantization, capabilities
   └─ estimated memory, context length

4. Check if previously selected model exists:
   ├─ If yes: show status (available, loading, not installed)
   ├─ If no: show suggestion to select different model

5. Show ModelSelector UI with:
   ├─ List of discovered models
   ├─ Current selection
   ├─ + Add Model button (manual directory)
   ├─ Model details (size, quantization, memory)
   └─ Load/Unload buttons
```

### 5.2 Model Metadata Schema

```json
// ~/.airlm/models/qwen-coder-7b-instruct/model.json
{
  "id": "qwen-coder-7b-instruct",
  "name": "Qwen Coder 7B Instruct",
  "provider": "airlm",
  "quantization": "q4_k_m",
  "parameters": "7B",
  "context_length": 4096,
  "capabilities": {
    "chat": true,
    "code_completion": true,
    "code_editing": true,
    "reasoning": false,
    "tool_calling": false,
    "vision": false
  },
  "memory_estimate_mb": 5000,
  "source": "huggingface",
  "source_id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
  "installed_at": "2026-08-10T10:30:00Z"
}
```

---

## Part 6: PROVIDER ISOLATION

### 6.1 Provider Interface (Abstract Base Class)

```python
# apps/ai-server/src/providers/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterable, List, Dict, Optional

class LocalAIProvider(ABC):
    """Abstract base for all AI providers."""
    
    id: str
    name: str
    
    @abstractmethod
    async def discover_models(self) -> List[LocalModel]:
        """Find models installed for this provider."""
        pass
    
    @abstractmethod
    async def load_model(self, model_id: str) -> None:
        """Load a model into memory."""
        pass
    
    @abstractmethod
    async def unload_model(self) -> None:
        """Unload current model from memory."""
        pass
    
    @abstractmethod
    async def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> AsyncIterable[str]:
        """Streaming chat completion."""
        pass
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> AsyncIterable[str]:
        """Streaming code completion."""
        pass
    
    @abstractmethod
    async def get_status(self) -> ModelStatus:
        """Get current model status."""
        pass
    
    @abstractmethod
    def validate_model_path(self, model_path: str) -> bool:
        """Check if path contains valid model for this provider."""
        pass
```

### 6.2 MLX Provider (Example Implementation)

```python
# apps/ai-server/src/providers/mlx.py

import asyncio
import json
from pathlib import Path
from typing import List, AsyncIterable

from .base import LocalAIProvider
from ..models.schemas import LocalModel, ModelStatus, ChatMessage

class MLXProvider(LocalAIProvider):
    """MLX-based inference on Apple Silicon."""
    
    id = "mlx"
    name = "MLX"
    
    def __init__(self, config: Dict):
        self.config = config
        self.model_path = None
        self.loaded_model = None
        self.tokenizer = None
        self.memory_used = 0
    
    async def discover_models(self) -> List[LocalModel]:
        """Scan ~/mlx_models for MLX-compatible models."""
        mlx_dir = Path.home() / ".mlx_models"
        if not mlx_dir.exists():
            return []
        
        models = []
        
        for model_dir in mlx_dir.iterdir():
            if not model_dir.is_dir():
                continue
            
            metadata_file = model_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                    
                    model = LocalModel(
                        id=f"mlx_{model_dir.name}",
                        name=metadata.get("name", model_dir.name),
                        provider="mlx",
                        path=str(model_dir),
                        parameters=metadata.get("parameters", "7B"),
                        context_length=metadata.get("context_length", 4096),
                        capabilities=metadata.get("capabilities", {}),
                        memory_estimate=metadata.get("memory_estimate_mb"),
                        status="available"
                    )
                    models.append(model)
                except Exception as e:
                    logger.error(f"Failed to load MLX model {model_dir}: {e}")
        
        return models
    
    async def load_model(self, model_id: str) -> None:
        """Load MLX model."""
        try:
            # Import MLX library
            import mlx.core as mx
            from mlx_lm import generate, load
            
            # Find model directory
            mlx_dir = Path.home() / ".mlx_models"
            model_dir = mlx_dir / model_id.replace("mlx_", "")
            
            if not model_dir.exists():
                raise FileNotFoundError(f"Model not found: {model_dir}")
            
            # Load model and tokenizer
            self.loaded_model, self.tokenizer = load(str(model_dir))
            self.model_path = model_dir
            
            logger.info(f"Loaded MLX model: {model_id}")
        
        except ImportError:
            raise RuntimeError("MLX library not installed")
        except Exception as e:
            logger.error(f"Failed to load MLX model: {e}")
            raise
    
    async def unload_model(self) -> None:
        """Unload MLX model."""
        self.loaded_model = None
        self.tokenizer = None
        self.model_path = None
    
    async def chat(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> AsyncIterable[str]:
        """Stream chat completion via MLX."""
        if not self.loaded_model:
            raise RuntimeError("No model loaded")
        
        # Format messages into prompt
        prompt = self._format_prompt(messages)
        
        # Generate tokens
        try:
            import mlx_lm
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            for token_id in self.loaded_model.generate_ids(
                [self.tokenizer.encode(prompt)],
                top_p=0.9,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                token_str = self.tokenizer.decode([token_id])
                yield token_str
        
        except Exception as e:
            logger.error(f"MLX generation failed: {e}")
            raise
    
    async def get_status(self) -> ModelStatus:
        """Get current status."""
        return ModelStatus(
            model_id=self.model_path.name if self.model_path else "none",
            status="loaded" if self.loaded_model else "available",
            memory_used=self.memory_used,
        )
    
    def validate_model_path(self, model_path: str) -> bool:
        """Check if path contains MLX model."""
        model_dir = Path(model_path)
        return (model_dir / "weights.npz").exists() or \
               (model_dir / "metadata.json").exists()
    
    def _format_prompt(self, messages: List[ChatMessage]) -> str:
        """Format messages into prompt."""
        prompt = ""
        for msg in messages:
            prompt += f"{msg.role.upper()}: {msg.content}\n"
        prompt += "ASSISTANT:"
        return prompt
```

### 6.3 Provider Manager (Orchestrator)

```python
# apps/ai-server/src/providers/__init__.py

from typing import Dict, List, Optional
from .base import LocalAIProvider
from .mlx import MLXProvider
from .airlm import AirLLMProvider
from .ollama import OllamaProvider

class ProviderManager:
    """Manages all AI providers and model loading."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.providers: Dict[str, LocalAIProvider] = {
            "mlx": MLXProvider(config.get("mlx", {})),
            "airlm": AirLLMProvider(config.get("airlm", {})),
            "ollama": OllamaProvider(config.get("ollama", {})),
        }
        self.current_provider: Optional[LocalAIProvider] = None
        self.current_model_id: Optional[str] = None
    
    async def discover_all_models(self) -> List[LocalModel]:
        """Discover models from all providers."""
        all_models = []
        
        for provider in self.providers.values():
            try:
                models = await provider.discover_models()
                all_models.extend(models)
            except Exception as e:
                logger.error(f"Provider discovery failed: {e}")
        
        return all_models
    
    async def load_model(self, model_id: str, provider_id: str) -> None:
        """Load a specific model from a provider."""
        if provider_id not in self.providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        
        provider = self.providers[provider_id]
        await provider.load_model(model_id)
        
        self.current_provider = provider
        self.current_model_id = model_id
    
    async def unload_model(self) -> None:
        """Unload current model."""
        if self.current_provider:
            await self.current_provider.unload_model()
            self.current_provider = None
            self.current_model_id = None
    
    def get_active_provider(self) -> Optional[LocalAIProvider]:
        """Get currently loaded provider."""
        return self.current_provider
```

---

## Part 7: TECHNICAL RISKS & MITIGATIONS

### Risk 1: Limited Memory (16 GB M3)
**Problem**: Large models may not fit in memory  
**Mitigation**:
- Use quantized models (Q4, Q5 instead of full precision)
- Implement auto-unload when switching models
- Show memory warnings in UI
- Start with 7B-13B parameter models
- Monitor memory usage during inference

### Risk 2: Local Model Quality
**Problem**: Smaller models may not be as capable as cloud APIs  
**Mitigation**:
- Use instruction-tuned models (Instruct variants)
- Start with specialized models (CodeLlama, Qwen-Coder)
- Implement staged prompting (plan → code, not both at once)
- Show confidence scores to user
- Allow fallback to cloud APIs (optional) for critical tasks

### Risk 3: Long Inference Time
**Problem**: Model generation may take 5-10 seconds per token on M3  
**Mitigation**:
- Use streaming responses (show tokens as they generate)
- Don't block UI during inference (background worker)
- Show progress indicator
- Allow cancellation mid-generation
- Cache common completions

### Risk 4: Model Download Size
**Problem**: Models are 3-7 GB, slow download  
**Mitigation**:
- Don't auto-download (explicit user action)
- Support resumable downloads
- Show download progress
- Allow pre-loading models before first use

### Risk 5: Provider Compatibility
**Problem**: Each provider has different APIs, requirements  
**Mitigation**:
- Abstract behind common interface
- Isolate provider-specific code
- Test each provider independently
- Document provider setup requirements

### Risk 6: File System Safety
**Problem**: Agent could accidentally delete files  
**Mitigation**:
- Never execute file operations without user approval
- Show diffs before applying
- Keep backups/git history
- Don't allow rm -rf style operations
- Log all file modifications

---

## Part 8: IMPLEMENTATION ROADMAP

### Phase 0: Setup & Project Structure (Week 1)
- [ ] Initialize Electron + React TypeScript project
- [ ] Set up FastAPI backend structure
- [ ] Create monorepo structure with pnpm
- [ ] Set up CI/CD (GitHub Actions or similar)
- [ ] Create base type definitions
- **Deliverable**: Repo compiles, can start both servers

### Phase 1: Model Selector & Discovery (Week 1-2)
- [ ] Implement model discovery for each provider
- [ ] Create ModelSelector React component
- [ ] Build /api/models endpoints
- [ ] Implement ProviderManager
- [ ] Create configuration persistence (~/.config/local-ai-editor)
- **Deliverable**: User can see available models, select one

### Phase 2: Editor Foundation (Week 2-3)
- [ ] Build Monaco editor integration
- [ ] File explorer component
- [ ] File read/write operations
- [ ] Open folder dialog
- [ ] Basic git integration (show branch, diff)
- **Deliverable**: Can open files, edit, save

### Phase 3: AI Chat (Week 3-4)
- [ ] Streaming chat endpoint
- [ ] ChatPanel React component
- [ ] Load/unload model
- [ ] Token streaming display
- [ ] Chat history persistence
- **Deliverable**: Can chat with AI model, see streaming response

### Phase 4: Context & Code Understanding (Week 4-5)
- [ ] File indexing & symbol extraction
- [ ] Implement ContextRetriever
- [ ] AST-based symbol finding
- [ ] Project context awareness
- [ ] Code selection context
- **Deliverable**: AI can understand current file context

### Phase 5: AI Agent (Week 5-7)
- [ ] Intent Analyzer
- [ ] Planner Agent
- [ ] Code Editor Agent
- [ ] File system tools (read, write, create)
- [ ] Patch validation
- [ ] /api/agent endpoint
- **Deliverable**: Can explain code, suggest fixes (no auto-apply yet)

### Phase 6: Code Modification (Week 7-8)
- [ ] Diff viewer component
- [ ] Patch application logic
- [ ] Git integration for branches
- [ ] Syntax validation
- [ ] Lint/format integration
- **Deliverable**: Can apply AI-suggested changes with approval

### Phase 7: Terminal & Advanced Tools (Week 8-9)
- [ ] Integrated terminal component
- [ ] Terminal tool for agent
- [ ] Git commands (commit, push, etc.)
- [ ] Run tests/build commands
- [ ] Output monitoring
- **Deliverable**: Full terminal access, AI can execute commands

### Phase 8: Polish & Optimization (Week 9-10)
- [ ] Settings panel for all configuration
- [ ] Keyboard shortcuts
- [ ] Dark mode (system default)
- [ ] Performance optimization
- [ ] Error handling & recovery
- [ ] Logging & debugging
- **Deliverable**: Production-ready UI/UX

### Phase 9: Testing & Documentation (Week 10-11)
- [ ] Unit tests (pytest for backend)
- [ ] Integration tests
- [ ] User documentation
- [ ] Developer documentation
- [ ] Example workflows
- **Deliverable**: Full test coverage, docs complete

### Phase 10: Packaging & Distribution (Week 11-12)
- [ ] macOS code signing
- [ ] App bundle creation
- [ ] Installer/DMG
- [ ] Auto-updates
- [ ] Release notes
- **Deliverable**: Distributable .dmg file

---

## Part 9: API ENDPOINTS (PRELIMINARY)

### Model Management
```
GET    /api/v1/models
       → List all discovered models

POST   /api/v1/models/scan
       → Rescan for new models

POST   /api/v1/models/{model_id}/load
       → Load specific model

POST   /api/v1/models/unload
       → Unload current model

GET    /api/v1/models/status
       → Get current model status

GET    /api/v1/providers
       → List installed providers
```

### File Operations
```
POST   /api/v1/files/read
       body: { path: string }
       → Read file content

POST   /api/v1/files/write
       body: { path: string, content: string }
       → Write file content

POST   /api/v1/files/list
       body: { dirPath: string }
       → List directory contents

POST   /api/v1/files/search
       body: { query: string, dirPath: string }
       → Search files
```

### Chat
```
WS     /api/v1/chat
       Connect with: { modelId: string, temperature?: number }
       Send: { messages: ChatMessage[] }
       Receive: { type: "token"|"complete", content: string }
       → Streaming chat
```

### Agent
```
WS     /api/v1/agent/execute
       Connect with: { context?: any }
       Send: { action: string, payload: any }
       Receive: { type: string, status: string, result: any }
       → Agentic loop with tools
```

### Context
```
POST   /api/v1/context/analyze
       body: { selectedFile?: string, selectedCode?: string, message: string }
       → Analyze intent + retrieve relevant files

POST   /api/v1/context/symbols
       body: { dirPath: string }
       → Index symbols in directory
```

---

## Part 10: SECURITY CONSIDERATIONS

### Local-First Security
- ✅ No cloud API calls (all processing local)
- ✅ No telemetry by default
- ✅ Configuration stored in user home directory
- ✅ Models stored locally
- ✅ No authentication needed (single-user)

### File System Safety
- ✅ Require user approval before modifying files
- ✅ Show diffs before applying patches
- ✅ Keep git history (can always revert)
- ✅ Don't allow destructive shell commands without review
- ✅ Log all operations

### Memory Safety
- ✅ Use type-safe languages (TypeScript, Python with Pydantic)
- ✅ Validate all user inputs
- ✅ Proper error handling (no panics/unhandled exceptions)
- ✅ Resource limits (max tokens, timeouts)

### Model Privacy
- ✅ Models stay on user's computer
- ✅ Project files never sent to cloud
- ✅ No automatic error reporting (user can opt-in)

---

## Part 11: DECISION JUSTIFICATIONS

### Why Electron + React?
- **Pro**: Mature ecosystem, large community, easy cross-platform
- **Con**: ~150 MB app, uses ~200 MB RAM
- **Alternative**: Qt (Python), but less polished UI ecosystem
- **Decision**: Electron is worth the trade-off for UX

### Why FastAPI?
- **Pro**: Modern, async-first, fast validation, auto API docs
- **Con**: Python only (but we need it for ML anyway)
- **Alternative**: Node.js backend (TypeScript), but adds complexity
- **Decision**: FastAPI is simpler than duplicating logic

### Why WebSocket for Streaming?
- **Pro**: Bidirectional, low-overhead, perfect for streaming
- **Con**: Need to manage connection state
- **Alternative**: Server-Sent Events (SSE), polling
- **Decision**: WebSocket is cleaner for real-time interaction

### Why Monorepo?
- **Pro**: Shared types between frontend/backend, single version management
- **Con**: More complex tooling
- **Alternative**: Separate repos
- **Decision**: Monorepo for easier refactoring

### Why Provider Abstraction?
- **Pro**: Easy to add providers (AirLLM, MLX, Ollama, future ones)
- **Con**: Extra layer of indirection
- **Alternative**: Ollama-only, but limits flexibility
- **Decision**: Abstraction enables extensibility goal

---

## Part 12: SUCCESS CRITERIA

After Phase 5 (core AI agent working):
- [ ] Can discover and load local models
- [ ] Chat works with streaming output
- [ ] Agent can read/analyze files
- [ ] Can explain code
- [ ] Can suggest fixes

After Phase 8 (full implementation):
- [ ] All features from prompt working
- [ ] 90%+ test coverage
- [ ] < 50ms UI response time
- [ ] < 10s for typical AI request
- [ ] < 100 MB app size
- [ ] Full documentation
- [ ] Example workflows

---

## Summary

This architecture provides:

1. **Solid Foundation**: Typed, modular, testable code
2. **Flexibility**: Easy to add providers, tools, features
3. **Reliability**: Validation gates, retry logic, error handling
4. **Performance**: Streaming, async, memory-conscious
5. **Usability**: VS Code-like IDE with AI superpowers
6. **Safety**: Local-first, file review, approval workflows

**Next Steps**:
1. Review and approve this architecture
2. Create initial project structure (Phase 0)
3. Build ModelSelector + discovery (Phase 1)
4. Iterate with working features visible every week
