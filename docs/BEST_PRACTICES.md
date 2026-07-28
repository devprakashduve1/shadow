# AI Code Editor: Best Practices & Implementation Checklist

## Part 1: Best Practices from Modern Editors

### 1. RAG (Retrieval-Augmented Generation)
**What**: Retrieve relevant files before asking LLM to code  
**Why**: Reduces context bloat, improves accuracy, faster inference  
**How**:
- Index project files at startup
- Use semantic search (embeddings) as fallback
- Limit to 5-8 most relevant files
- Bundle file metadata (symbols, imports)

**Your Implementation**:
```python
# ✅ Already in ContextRetriever
retrieval = retriever.retrieve(intent, max_files=8)
# Uses: filename search + symbol search + ripgrep + embeddings
```

---

### 2. AST-Aware Editing
**What**: Parse code into syntax trees, edit by structure not text  
**Why**: Preserves formatting, avoids partial matches, respects language rules  
**How**:
- Parse files into AST at retrieval time
- Extract function/class boundaries
- Navigate by symbol, not line numbers
- Generate patches that respect scope

**Your Implementation**:
```python
# ✅ In ContextRetriever._extract_file_symbols()
tree = ast.parse(content)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        # Track precisely where function is
```

---

### 3. Symbol Indexing
**What**: Pre-compute which symbols live where  
**Why**: Fast lookups, enables dependency analysis  
**How**:
- Build index once at startup
- Track: function/class names, line numbers, types
- Maintain as files change
- Use for "find all references"

**Your Implementation**:
```python
# ✅ In ContextRetriever._build_symbol_index()
# Run once, cache in _symbol_index
# Use in symbol_search algorithm
```

---

### 4. Incremental Patching
**What**: Generate diffs/structured edits, not full files  
**Why**: LLM output smaller, easier to validate, can retry just failed piece  
**How**:
- Use unified diff or JSON patch format
- Prefer replace over delete+insert
- Keep operation count low
- Include validation metadata

**Your Implementation**:
```python
# ✅ PatchOperation class with types:
# - replace (search→replacement)
# - insert (at line N)
# - delete (lines N-M)
# - add_import (after line N)
```

---

### 5. Token Optimization
**What**: Trim context to fit LLM's context window  
**Why**: Faster inference, cheaper, less hallucination  
**How**:
- Remove comments/docstrings from context
- Show only relevant function (not whole file)
- Use few-shot examples (not zero-shot)
- Batch related edits one request

**Your Implementation**:
```python
# ✅ In CodeEditor._extract_relevant_section()
# Show only target function + 2 lines context
# ✅ In CodeEditor._build_prompt()
# Include minimal but complete context
```

---

### 6. Conversation Memory
**What**: Remember plan, retrieval, previous attempts  
**Why**: Enables intelligent retries, context reuse, error recovery  
**How**:
- Store full retrieval result
- Save plan once, reference in each edit
- Track previous error + solution
- Include in retry prompts

**Your Implementation**:
```python
# ✅ Return full PlanResult (plan_id, steps, raw LLM response)
# ✅ Pass previous_error to CodeEditor.generate_patch()
# ✅ Retry with specific error feedback, not from scratch
```

---

### 7. Project Summaries
**What**: Quick overview of project structure and key symbols  
**Why**: Helps LLM understand project organization  
**How**:
- File tree with counts (N Python files, M tests)
- Key entry points
- Main patterns used
- Common imports

**Your Implementation**:
```python
# TODO: Add ProjectSummary class
# Build in ContextRetriever.__init__()
# Include in planner prompt as reference
```

---

### 8. Confidence Scoring
**What**: Assign confidence to each decision  
**Why**: Know when to ask for help, which results to trust  
**How**:
- Classifier confidence (0.0-1.0)
- Retrieval match scores
- Patch validation passes/fails
- Test pass rate

**Your Implementation**:
```python
# ✅ IntentAnalysis.confidence
# ✅ Retrieval scores in _rank_candidates()
# ✅ ValidationResult with detailed breakdown
# ✅ EditMetrics.validation_rate, apply_success_rate
```

---

### 9. Edit Verification
**What**: Run syntax check, linting, tests after applying changes  
**Why**: Catch errors immediately, automate quality gates  
**How**:
- Syntax check (ast.parse, eslint, etc.)
- Lint check (pylint, prettier, etc.)
- Type check (mypy, tsc, etc.)
- Unit tests (pytest, jest, etc.)

**Your Implementation**:
```python
# ✅ Validator.validate() - syntax check
# ✅ Orchestrator._format_file() - black, prettier
# ✅ Orchestrator._lint_file() - pylint, eslint
# ✅ Orchestrator._run_tests() - pytest, jest
```

---

### 10. Automatic Recovery
**What**: Retry with smarter feedback when edits fail  
**Why**: Self-healing system, reduces manual intervention  
**How**:
- Catch validation/test failures
- Extract specific error message
- Ask LLM to fix (not regenerate)
- Max 3 retries before giving up

**Your Implementation**:
```python
# ✅ Orchestrator._apply_plan_with_retry()
# For each step: max_retries=3
# Pass error back to CodeEditor.generate_patch(previous_error=...)
# Retry with same patch context
```

---

## Part 2: Cursor/Windsurf Specific Features

### Cursor's Approach
1. **Cmd+K for inline edits**: Cursor's killer feature
   - Highlight code → ask AI → get diff preview → accept/reject
   - Implementation: Use unified diff, show side-by-side before apply

2. **Codebase-wide understanding**: "Search through your codebase"
   - Implementation: ✅ Already have 4 search algorithms

3. **Automatic test discovery**: Find and run tests for changed code
   - Implementation: ✅ Already have _run_tests()

4. **Composer for multi-file edits**: Chat with generated code
   - Implementation: Plan step already supports multiple files

### Windsurf's Approach
1. **Flow state**: Chat persists across edits
   - Implementation: Pass plan_id, retrieval context between requests

2. **Context management**: Show what's being considered
   - Implementation: Log each stage (debug logging)

3. **Incremental development**: Build piece-by-piece
   - Implementation: ✅ Plan steps are atomic

4. **Breakpoint-style debugging**: Insert diagnostic code
   - Implementation: Could add as enhancement

---

## Part 3: Implementation Checklist

### Phase 1: Foundation (✅ DONE)
- [x] Data structures (schemas.py)
- [x] ContextRetriever (4 search algorithms)
- [x] Validator (syntax, imports, formatting)
- [x] Schemas for all stages

### Phase 2: Core Agents (✅ DONE)
- [x] Planner (plan generation)
- [x] CodeEditor (patch generation)
- [x] Orchestrator (pipeline coordination)
- [x] Error handling and retries

### Phase 3: Integration (⚠️ IN PROGRESS)
- [ ] Replace coding_agent.py usage with AICodeEditor
- [ ] GUI integration (show plan, apply, show results)
- [ ] Logging and metrics
- [ ] Error reporting to user

### Phase 4: Optimization (📋 TODO)
- [ ] Intent classifier (replace heuristic with ML)
- [ ] Project summary builder
- [ ] Embedding-based semantic search
- [ ] Conversation memory system

### Phase 5: Polish (📋 TODO)
- [ ] Performance monitoring
- [ ] Unit tests
- [ ] Integration tests
- [ ] Documentation and examples

---

## Part 4: Quality Metrics

### Target Metrics (Measure After Each Week)

| Metric | Current | Target | How to Measure |
|--------|---------|--------|-----------------|
| **Success Rate** | ? | >90% | Patches applied successfully |
| **Validation Rate** | ? | >95% | Patches pass validation |
| **Test Pass Rate** | ? | >85% | Tests pass after edits |
| **Avg Retries** | ? | <1.5 | Times auto-retry triggered |
| **Mean Time to Apply** | ? | <30s | End-to-end request time |
| **Context Size** | ? | <8000 | Tokens sent to LLM |
| **Hallucination Rate** | ? | <5% | Patches with syntax errors |

### Instrumentation

```python
# In EditMetrics
@dataclass
class EditMetrics:
    request_id: str
    intent_confidence: float
    files_retrieved: int
    plan_steps: int
    patches_generated: int
    patches_valid: int
    patches_applied: int
    apply_attempts: int  # retries
    tests_run: int
    tests_passed: bool
    total_time_seconds: float
    success: bool
    
    # Computed properties
    @property
    def validation_rate(self) -> float:
        return self.patches_valid / max(self.patches_generated, 1)
    
    @property
    def apply_success_rate(self) -> float:
        return self.patches_applied / max(self.patches_valid, 1)
    
    @property
    def retry_efficiency(self) -> float:
        """Lower is better (fewer retries needed)."""
        return self.apply_attempts / max(self.patches_applied, 1)
```

### Dashboard Example

```python
# Track metrics over time
metrics_log = []

for request in user_requests:
    result = editor.handle_request(request)
    
    # Log metrics
    metrics = EditMetrics(
        request_id=result.request_id,
        success=result.success,
        patches_applied=result.patches_applied,
        # ... more fields
    )
    metrics_log.append(metrics)

# Weekly report
successful = [m for m in metrics_log if m.success]
success_rate = len(successful) / len(metrics_log) if metrics_log else 0
avg_retries = sum(m.apply_attempts for m in metrics_log) / len(metrics_log)
avg_time = sum(m.total_time_seconds for m in metrics_log) / len(metrics_log)

print(f"""
Weekly Report:
- Success Rate: {success_rate:.0%}
- Avg Retries: {avg_retries:.1f}
- Avg Time: {avg_time:.1f}s
- Validation Rate: {avg([m.validation_rate for m in metrics_log]):.0%}
""")
```

---

## Part 5: Local LLM Configuration

### Quick-Start Setup

```bash
# Install Ollama (if not already)
curl https://ollama.ai/install.sh | sh

# Pull a good coding model
ollama pull qwen2.5:7b

# Or for better reasoning (if GPU allows)
ollama pull llama2:13b

# Start Ollama
ollama serve
```

### Model Selection Guide

| Use Case | Model | Size | Context | Speed | Notes |
|----------|-------|------|---------|-------|-------|
| **Testing/Demo** | Qwen2.5 7B | 7B | 32K | 2s/token | Good balance |
| **Production** | CodeLlama 13B | 13B | 4K | 3s/token | Code-specific |
| **High Quality** | Llama 3 70B | 70B | 8K | 5s/token | Best quality |
| **Fast** | Mistral 7B | 7B | 8K | 2s/token | Quick iteration |
| **Best Local** | DeepSeek Coder 34B | 34B | 16K | 4s/token | Great for coding |

### Prompt Engineering for Local LLMs

**DO**:
- [x] Use few-shot examples (2-3 examples)
- [x] Explicit output format (JSON, code block markers)
- [x] Break into stages (analyze → plan → code)
- [x] Low temperature (0.1) for correctness
- [x] Concrete examples with exact input/output

**DON'T**:
- [ ] Zero-shot (no examples)
- [ ] Implicit format ("write whatever code you think")
- [ ] One huge prompt with everything
- [ ] High temperature (>0.5)
- [ ] Vague instructions

### Context Window Management

```python
# For 4K context model
max_context = 4000
reserved_for_response = 1000
available = max_context - reserved_for_response

# Budget breakdown
budget = {
    "system_prompt": 300,
    "user_request": 200,
    "current_file": 1200,
    "related_context": 400,
    "examples": 400,
    "padding": 100,
}

assert sum(budget.values()) < available
```

---

## Part 6: Troubleshooting Guide

### Symptom: "Patches not applying"
**Diagnosis**:
```python
result = editor.handle_request("add email validation")
print(f"Patches generated: {metrics.patches_generated}")
print(f"Patches valid: {metrics.patches_valid}")
print(f"Patches applied: {metrics.patches_applied}")
print(f"Errors: {result.errors}")
```

**Common Causes**:
1. Search text not found → File changed between retrieval and apply
2. Syntax error → LLM generated invalid code
3. Imports not found → Removed import still in use

**Solutions**:
1. Retry immediately with fresh file content
2. Validator should catch syntax errors
3. Check imports validation results

---

### Symptom: "Tests fail after changes"
**Diagnosis**:
```python
print(f"Test passed: {result.test_results.passed}")
print(f"Failed tests: {result.test_results.failed_tests}")
print(f"Stderr: {result.test_results.stderr}")
```

**Common Causes**:
1. Patch broke existing functionality
2. Missing test setup
3. External dependencies

**Solutions**:
1. Retry with error feedback
2. Check test file exists and has setup
3. Mock external deps in test

---

### Symptom: "LLM is too slow / expensive"
**Diagnosis**:
```python
print(f"Plan tokens: {plan.estimated_tokens}")
print(f"Retrieval files: {len(retrieval.files)}")
print(f"Time elapsed: {result.total_time_seconds}s")
```

**Solutions**:
1. Reduce files to 5 instead of 8
2. Compress context (remove comments, docstrings)
3. Use smaller model (7B instead of 13B)
4. Use quantized version (4-bit instead of 8-bit)
5. Batch multiple edits into one request

---

## Part 7: Advanced Optimizations

### Optimization 1: Batch Related Edits

Instead of:
```
Request 1: Add function A
Request 2: Add function B
Request 3: Add imports
```

Do:
```
Request 1 (combined):
- Add function A
- Add function B
- Add imports
(in one plan with multiple steps)
```

### Optimization 2: Pre-Compute Common Contexts

```python
# Cache expensive computations
class CachedRetriever(ContextRetriever):
    def __init__(self, project_root):
        super().__init__(project_root)
        self._cache = {}
    
    def retrieve(self, intent, max_files=8):
        cache_key = tuple(sorted(intent.keywords))
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        result = super().retrieve(intent, max_files)
        self._cache[cache_key] = result
        return result
```

### Optimization 3: Parallel Patch Generation

```python
from concurrent.futures import ThreadPoolExecutor

def apply_steps_parallel(plan, context, editor):
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for step in plan.steps:
            future = executor.submit(
                editor.generate_patch,
                step, context
            )
            futures.append(future)
        
        patches = [f.result() for f in futures]
    
    return patches
```

### Optimization 4: Streaming LLM Responses

```python
# Collect response as it streams (faster time-to-first-token)
def complete_streaming(prompt, llm):
    response_parts = []
    for chunk in llm.stream(prompt):
        response_parts.append(chunk)
        # Show to user immediately
        yield chunk
    
    return "".join(response_parts)
```

---

## Checklist: Before Deploying to Production

- [ ] **Validation**: All tests pass, >95% patches valid
- [ ] **Robustness**: Error handling for all edge cases
- [ ] **Logging**: Debug logs for every stage
- [ ] **Metrics**: Collecting success/failure metrics
- [ ] **Documentation**: README, integration guide, examples
- [ ] **Testing**: Unit tests for each agent
- [ ] **Performance**: <30s for typical request
- [ ] **User Feedback**: Way to report issues
- [ ] **Monitoring**: Can see success rate over time
- [ ] **Recovery**: Max 3 retries, graceful failure message

---

## References

- **Cursor Editor**: https://cursor.com
- **Windsurf**: https://codeium.com/windsurf
- **Cline**: https://github.com/cline/cline
- **Roo Code**: https://github.com/RooVetGit/Roo-Code
- **Claude API**: https://claude.ai/api/documentation
- **LLM Optimization**: https://github.com/ggerganov/llama.cpp
