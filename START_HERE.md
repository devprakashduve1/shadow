# START HERE: Your Implementation Roadmap

**Welcome!** This is your 10-week journey to build a local AI code editor.

---

## What You Need to Know (5 min read)

### The Big Picture
- **You already have**: Production-grade code editing engine (2000 LOC, done ✅)
- **You need to build**: FastAPI wrapper + Electron UI (~6500 LOC)
- **Timeline**: 10 weeks
- **Risk**: Low (keep existing code untouched)

### Four Documents to Read
| Doc | Purpose | Time |
|-----|---------|------|
| IMPLEMENTATION_SUMMARY.md | TL;DR + decisions | 5 min |
| LOCAL_AI_EDITOR_ROADMAP.md | Week-by-week plan | 10 min |
| INTEGRATION_PLAN.md | File-by-file checklist | 10 min |
| ARCHITECTURE_VISUAL.md | How it all connects | 10 min |

### Quick Start (Today)
1. ☐ Read IMPLEMENTATION_SUMMARY.md
2. ☐ Approve the plan (or request changes)
3. ☐ Answer 4 decision questions (below)
4. ☐ Come back here for Week 1 checklist

---

## Decision Points (Decide Now)

Before we start, confirm your preferences:

### Decision 1: Which Model Providers?
```
[ ] A - Ollama only (safest, well-tested)
[ ] B - Ollama + MLX (recommended, best for M3)
[ ] C - All three: Ollama + MLX + AirLLM (most flexibility)
```
**My recommendation**: B (Ollama as fallback, MLX for speed)

### Decision 2: Electron + React Confirmed?
```
[ ] Yes, Electron + React (chosen in architecture)
[ ] No, use different stack (what?)
```
**Recommendation**: Yes

### Decision 3: Packaging Strategy
```
[ ] DMG file only (fastest to launch)
[ ] DMG + Homebrew (adds ~1 day)
[ ] DMG + Homebrew + App Store (most work)
```
**Recommendation**: DMG only for v1.0

### Decision 4: Test Coverage Target
```
[ ] 50% (minimum)
[ ] 70% (good, balanced)
[ ] 80%+ (excellent, slower)
```
**Recommendation**: 70%

---

## After You Decide...

Once you've read the docs and made decisions above, **proceed to Week 1 below**.

Otherwise, your choices are:
- 🔴 **Request Changes**: Something doesn't match your vision
- 🟡 **Ask Questions**: Need clarification on specific points
- 🟢 **Proceed**: Ready to start implementation

---

## WEEK 1: Model Management Backend

**Goal**: FastAPI server that can discover and load local AI models  
**Duration**: ~40 hours of focused work  
**Starting**: Tomorrow (or whenever you're ready)

### Prerequisites
```bash
# Make sure you have:
python3 --version          # Should be 3.10+
pip --version              # Should be pip 24+

# Optional but helpful:
brew list | grep ollama    # Check if Ollama installed
```

### What You're Building

```
By end of week, you'll have:
✅ /apps/ai-server/src/providers/base.py      (abstract interface)
✅ /apps/ai-server/src/providers/mlx.py       (MLX provider)
✅ /apps/ai-server/src/providers/airlm.py     (AirLLM provider)
✅ /apps/ai-server/src/providers/ollama.py    (Ollama wrapper)
✅ /apps/ai-server/src/model_manager.py       (orchestrate providers)
✅ /apps/ai-server/src/config.py              (load configuration)
✅ /apps/ai-server/src/main.py                (FastAPI app)
✅ /apps/ai-server/requirements.txt            (update with new deps)
✅ /apps/ai-server/tests/test_providers.py    (test suite)
```

### Daily Checklist (Week 1)

#### Day 1-2: Setup & Providers/Base
```
[ ] Create apps/ai-server/ directory structure
    mkdir -p apps/ai-server/src/providers tests
    
[ ] Create providers/base.py
    • Define LocalAIProvider abstract base class
    • Methods: discover_models, load_model, unload_model, chat, get_status
    • Add docstrings + type hints
    
[ ] Create config.py
    • ConfigClass with provider, model, temperature, etc.
    • Load from ~/.config/local-ai-editor/config.json
    • Save configuration when changed
    
[ ] Create pyproject.toml or requirements.txt
    • fastapi>=0.100.0
    • uvicorn>=0.23.0
    • pydantic>=2.0.0
    • python-dotenv
    
[ ] Test: Can import base.py without errors
    python -c "from providers.base import LocalAIProvider"
```

#### Day 3: Ollama Provider
```
[ ] Create providers/ollama.py
    • Wrap existing ollama_models.py code
    • Implement all LocalAIProvider methods
    • discover_models(): call existing ollama_models code
    • load_model(): get model from Ollama
    • chat(): stream responses from Ollama API
    
[ ] Test with running Ollama instance
    # In another terminal: ollama serve
    python -c "
    from providers.ollama import OllamaProvider
    provider = OllamaProvider({'base_url': 'http://localhost:11434'})
    models = await provider.discover_models()
    print(models)
    "
```

#### Day 4: MLX Provider
```
[ ] Install MLX library (if on Apple Silicon)
    pip install mlx-lm
    
[ ] Create providers/mlx.py
    • discover_models(): scan ~/.mlx_models/
    • load_model(): load with mlx-lm library
    • unload_model(): free memory
    • chat(): generate tokens with MLX
    
[ ] Create test MLX model or use sample
    # MLX models available at: https://huggingface.co/mlx-community
    
[ ] Test: Can load MLX model
    python -c "
    from providers.mlx import MLXProvider
    p = MLXProvider()
    models = await p.discover_models()
    print(f'Found {len(models)} MLX models')
    "
```

#### Day 5: AirLLM Provider
```
[ ] Install AirLLM library
    pip install airlm
    
[ ] Create providers/airlm.py
    • Similar structure to MLX provider
    • discover_models(): find GGUF quantized models
    • load_model(): load with airlm
    • chat(): stream inference
    
[ ] Test: Basic functionality
    python -c "
    from providers.airlm import AirLLMProvider
    p = AirLLMProvider()
    models = await p.discover_models()
    print(f'Found {len(models)} AirLLM models')
    "
```

#### Day 6: Model Manager
```
[ ] Create model_manager.py
    • ProviderManager class
    • __init__: initialize all providers
    • discover_all_models(): merge models from all providers
    • load_model(model_id, provider_id): load specific model
    • unload_model(): unload current
    • get_status(): current model status
    
[ ] Test: Can discover + load models
    python -c "
    from model_manager import ProviderManager
    manager = ProviderManager(config)
    models = await manager.discover_all_models()
    print(f'Total models: {len(models)}')
    await manager.load_model('gemma4', 'ollama')
    status = await manager.get_status()
    print(status)
    "
```

#### Day 7: FastAPI App + Tests
```
[ ] Create main.py
    • FastAPI app
    • Initialize ProviderManager
    • Add CORS middleware
    • Basic health check endpoint
    
[ ] Test: Server starts
    uvicorn main:app --reload
    curl http://localhost:8000/health
    # Should return: {"status": "ok"}
    
[ ] Create tests/test_providers.py
    • Test each provider's discover_models()
    • Test load/unload (mock where needed)
    • Test error handling
    
[ ] Run tests
    pytest tests/ -v
    # Should pass (or have reasonable failures if MLX/AirLLM not installed)
    
[ ] Update requirements.txt
    pip freeze > requirements.txt
```

### Success Criteria for Week 1

You know you're done when:

```bash
# 1. Server starts
python main.py
# Output: "INFO:     Application startup complete"

# 2. Can list models
curl http://localhost:8000/api/v1/models
# Output: [{"id": "...", "name": "...", "provider": "...", "status": "available"}, ...]

# 3. Can load model (if Ollama running)
curl -X POST http://localhost:8000/api/v1/models/gemma4/load
# Output: {"status": "loaded"}

# 4. Tests pass
pytest tests/ -v
# Output: "passed" (with potentially some skipped if providers not installed)
```

### If You Get Stuck

1. **"ModuleNotFoundError: No module named 'mlx'"**
   - MLX only works on Apple Silicon
   - Install with: `pip install mlx-lm`
   - Or skip and use Ollama only for testing

2. **"Connection refused" to Ollama**
   - Make sure Ollama is running: `ollama serve` in another terminal
   - Or: `brew services start ollama`

3. **"GGUF model not found"**
   - AirLLM models need to be downloaded first
   - Place in: `~/.cache/airlm/models/`

4. **Tests failing**
   - Check if dependencies are installed: `pip install -r requirements.txt`
   - Run with verbose: `pytest -vv tests/`

### Next Steps (After Week 1)

Once you finish Week 1:
1. ✅ **Commit your work**: `git add -A && git commit -m "Week 1: Model providers + manager"`
2. 📋 **Review**: Check off items in INTEGRATION_PLAN.md
3. 🚀 **Move to Week 2**: FastAPI routes to wrap existing orchestrator

---

## Your First Command

Ready to start? Try this right now:

```bash
# Check your Python version
python3 -V              # Need 3.10+

# Check pip is updated
pip install --upgrade pip

# You're ready! Create the directories
mkdir -p apps/ai-server/src/providers tests
cd apps/ai-server

# Next: Follow Day 1-2 checklist above
```

---

## Daily Progress Tracking

Copy this to a file and check off as you go:

```markdown
# Week 1 Progress

## Day 1-2: Setup & Base.py
- [ ] Directory structure created
- [ ] base.py interface defined
- [ ] config.py loads configuration
- [ ] Can import without errors

## Day 3: Ollama Provider  
- [ ] providers/ollama.py implemented
- [ ] discover_models() works
- [ ] Manual test with Ollama: PASS/FAIL

## Day 4: MLX Provider
- [ ] providers/mlx.py implemented
- [ ] discover_models() works  
- [ ] Manual test with MLX: PASS/FAIL

## Day 5: AirLLM Provider
- [ ] providers/airlm.py implemented
- [ ] discover_models() works
- [ ] Manual test with AirLLM: PASS/FAIL

## Day 6: Model Manager
- [ ] model_manager.py implemented
- [ ] Can discover all models
- [ ] Can load/unload models
- [ ] Status endpoint works

## Day 7: FastAPI + Tests
- [ ] main.py creates FastAPI app
- [ ] Server starts without errors
- [ ] /api/v1/models endpoint works
- [ ] tests/test_providers.py passes
- [ ] requirements.txt updated

## Week 1 Complete?
- [ ] All items above checked
- [ ] Server runs: `python main.py`
- [ ] List models: `curl http://localhost:8000/api/v1/models`
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Commit to git: `git commit -m "Week 1 complete"`
```

---

## Communication

As you work:

- **Stuck?** Check docs first (they have solutions)
- **Questions?** Document them and ask
- **Progress?** Update your checklist daily
- **Finished?** Move to Week 2 checklist

---

## You've Got This 🚀

- ✅ You have existing code that works
- ✅ You have a detailed plan
- ✅ You know what to build each day
- ✅ You have success criteria

**Start Day 1 → Finish Week 1 → Move to Week 2**

The hardest part is starting. Everything else is just following the checklist.

Ready? Let's go! 💪

---

**Questions before Week 1?** Read:
1. IMPLEMENTATION_SUMMARY.md (decisions)
2. LOCAL_AI_EDITOR_ROADMAP.md (week 1 details)
3. ARCHITECTURE_VISUAL.md (how providers work)

**Then start Day 1** when you're ready.
