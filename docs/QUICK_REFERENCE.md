# AI Code Editor: Quick Reference

## Architecture Overview

```
User Request
    ↓
Intent Analyzer
    ↓ (IntentAnalysis: type, confidence, keywords, symbols)
Context Retriever (4 algorithms)
    ├─ Filename search
    ├─ Symbol search (AST)
    ├─ Ripgrep search
    └─ Embedding search
    ↓ (RetrievalResult: files, symbols, dependencies)
Planner
    ↓ (PlanResult: steps with actions)
Code Editor (per step)
    ↓ (Patch: JSON operations)
Validator
    ↓ (ValidationResult: valid?, errors, warnings)
Apply to Filesystem
    ↓ (format, lint, test)
Edit Result
```

## Core Classes

```python
# Main entry point
from assistant.ai_editor import AICodeEditor

editor = AICodeEditor(project_root, llm_client)
result = editor.handle_request("user request")

# Individual agents
from assistant.ai_editor import (
    ContextRetriever,
    Planner,
    CodeEditor,
    Validator,
)

# Data structures
from assistant.ai_editor import (
    IntentAnalysis,
    RetrievalResult,
    PlanResult,
    Patch,
    EditResult,
)
```

## Quick Usage

### Minimal
```python
editor = AICodeEditor("/path/to/project", llm_client)
result = editor.handle_request("Add email validation")

print(f"Success: {result.success}")
print(f"Modified: {result.modified_files}")
print(f"Errors: {result.errors}")
```

### With Plan Review
```python
# Stage 1-3: Analyze, Retrieve, Plan
intent = editor._analyze_intent(request)
retrieval = editor.retriever.retrieve(intent)
plan = editor.planner.plan(intent, retrieval, request)

# Show plan to user
print("Plan:")
for step in plan.steps:
    print(f"  {step.step_number}. {step.action}: {step.file}")

# Stage 4-8: Apply (if approved)
if user_approves:
    result = editor._apply_plan_with_retry(plan, retrieval, "req-123")
```

### Per-Agent
```python
# Stage 2: Retrieve files
retriever = ContextRetriever(project_root)
intent = IntentAnalysis(...)
retrieval = retriever.retrieve(intent, max_files=8)

# Stage 3: Plan
planner = Planner(llm_client)
plan = planner.plan(intent, retrieval, request)

# Stage 4: Generate patches
editor = CodeEditor(llm_client)
patch = editor.generate_patch(plan.steps[0], file_content, context)

# Stage 6: Validate
validator = Validator()
validation = validator.validate(patch, file_content, "path.py")

# Stage 7: Apply
new_content = validator._apply_patch(file_content, patch)
Path("path.py").write_text(new_content)
```

## Data Structures

### IntentAnalysis
```python
IntentAnalysis(
    intent_type: IntentType,          # fix|feature|refactor|test|docs|debug
    confidence: float,                 # 0.0-1.0
    summary: str,                      # User's request
    keywords: List[str],               # ["email", "validation", "user"]
    likely_symbols: List[str],         # ["validate_email", "User"]
    requires_new_file: bool,
    complexity_score: int,             # 1-5
)
```

### RetrievalResult
```python
RetrievalResult(
    files: List[BundledFile],          # Up to 8 relevant files
    symbols: Dict[str, SymbolLocation],
    dependencies: Dict[str, List[str]],
)

# Where BundledFile contains
BundledFile(
    file_path: str,
    content: str,
    language: str,
    symbols: Dict[str, SymbolLocation],
)
```

### PlanResult
```python
PlanResult(
    plan_id: str,
    steps: List[PlanStep],             # Ordered steps
    summary: str,
    estimated_impact: Dict,
)

# Where PlanStep is
PlanStep(
    step_number: int,
    action: str,                       # understand|modify|create|delete|test
    file: str,
    target_function: Optional[str],
    change_type: Optional[str],
    details: str,
)
```

### Patch
```python
Patch(
    file: str,
    operations: List[PatchOperation],
)

# Where PatchOperation is
PatchOperation(
    type: PatchOpType,                 # replace|insert|delete|add_import
    search: Optional[str],
    replacement: Optional[str],
    line_start: Optional[int],
    line_end: Optional[int],
)
```

### EditResult
```python
EditResult(
    success: bool,
    patches_applied: int,
    errors: List[str],
    warnings: List[str],
    modified_files: List[str],
    total_time_seconds: float,
)
```

## Search Algorithms

### 1. Filename Search
- Match keyword against file names
- Exact > Substring > Fuzzy > Prefix
- Fast, works well for obvious files

```python
retriever._filename_search("email")  # Finds: validators.py, email.py, etc.
```

### 2. Symbol Search
- Parse all files' AST
- Find function/class/variable definitions
- Very accurate for known symbols

```python
retriever._symbol_search(["validate_email", "User"])
```

### 3. Ripgrep Search
- Fast regex search via `rg` command
- Finds pattern occurrences
- Good for keywords in code

```python
retriever._ripgrep_search("email_regex")
```

### 4. Embedding Search
- Semantic search using sentence embeddings
- Slow but very flexible
- Fallback if others insufficient

```python
retriever._semantic_search("validation logic")
```

**Selection**: Run all, merge by score, deduplicate, limit to 8

## Validation Checklist

```python
validator.validate(patch, file_content, "path.py")
# Checks:
✓ Search text exists
✓ Syntax is valid (ast.parse, etc.)
✓ Imports remain valid
✓ No obvious formatting violations
✓ Line counts reasonable
```

## Patch Types

### JSON Operations
```json
{
  "file": "path/to/file.py",
  "operations": [
    {
      "type": "replace",
      "search": "old code block",
      "replacement": "new code block"
    },
    {
      "type": "add_import",
      "import_statement": "import socket",
      "after_line": 2
    }
  ]
}
```

### Unified Diff (Alternative)
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -10,6 +10,7 @@
 def validate_email(email):
     return True
+    # Add DNS check
```

## Common Patterns

### Add a function
```python
PatchOperation(
    type=PatchOpType.INSERT,
    line_start=20,
    replacement="""
def new_function(param):
    '''New function.'''
    return param * 2
"""
)
```

### Replace a function
```python
PatchOperation(
    type=PatchOpType.REPLACE,
    search="def old_func():\n    return 1",
    replacement="def old_func():\n    return 2"
)
```

### Add an import
```python
PatchOperation(
    type=PatchOpType.ADD_IMPORT,
    import_statement="import socket",
    after_line=5
)
```

### Delete lines
```python
PatchOperation(
    type=PatchOpType.DELETE,
    line_start=15,
    line_end=17
)
```

## Metrics to Track

```python
# Key metrics
success_rate = successful_edits / total_edits
validation_rate = valid_patches / generated_patches
test_pass_rate = tests_passed / tests_run
avg_retries = total_retry_attempts / total_edits
mean_time_seconds = total_time / total_edits

# Target thresholds
success_rate > 0.90
validation_rate > 0.95
test_pass_rate > 0.85
avg_retries < 1.5
mean_time_seconds < 30
```

## Environment Setup

```bash
# LLM
ollama pull qwen2.5:7b
ollama serve &

# Project
python -m pip install -e .

# Testing
pytest tests/

# Linting
black .
pylint assistant/ai_editor

# Type checking
mypy assistant/ai_editor
```

## LLM Prompting Tips

### For Local Models (7B-13B)

**DO**:
- Short prompts (< 2000 tokens)
- Explicit format (JSON, code blocks)
- Few-shot examples (2-3)
- Temperature = 0.1 (deterministic)
- Stage-based reasoning

**DON'T**:
- Zero-shot (add examples)
- Ambiguous format
- Temperature > 0.3 for code
- One giant prompt

### Temperature Settings
- Analysis/Classification: 0.0
- Planning: 0.1
- Code Generation: 0.3
- Creative: 0.5+

## Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Search text not found" | File changed | Retry with fresh content |
| "Syntax error after patch" | Invalid code | LLM error, validator should catch |
| "Imports not found" | Removed imports | Validator checks this |
| "Tests failed" | Patch broke code | Retry with error feedback |
| "Timeout" | LLM slow | Reduce context, use smaller model |

## Integration Checklist

- [ ] Initialize AICodeEditor with project path
- [ ] Create LLM client adapter (or use existing)
- [ ] Test handle_request() on simple changes
- [ ] Integrate with chat interface
- [ ] Add logging/metrics collection
- [ ] Test with real project
- [ ] Monitor success rate
- [ ] Deploy

## Performance Targets

| Stage | Time | Notes |
|-------|------|-------|
| Intent analysis | <100ms | Classifier |
| Context retrieval | <500ms | 4 searches in parallel |
| Planning | 5-10s | LLM call |
| Patch generation | 10-20s | Per step, may retry |
| Validation | <100ms | Static checks |
| Apply & format | <500ms | File I/O + black/prettier |
| **Total** | **<30s** | Target per request |

## Debugging Commands

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Trace each stage
intent = editor._analyze_intent(request)
print(f"Intent: {intent}")

retrieval = editor.retriever.retrieve(intent)
print(f"Files: {[f.file_path for f in retrieval.files]}")

plan = editor.planner.plan(intent, retrieval, request)
print(f"Steps: {[(s.step_number, s.action, s.file) for s in plan.steps]}")

# Inspect patch
patch = editor.editor.generate_patch(step, content, context)
print(f"Operations: {[(op.type.value, op.search[:20]) for op in patch.operations]}")

# Validate before apply
validation = editor.validator.validate(patch, content, file_path)
print(f"Valid: {validation.is_valid}, Errors: {validation.errors}")
```

## File Locations

```
assistant/ai_editor/
  ├── __init__.py              # Export main classes
  ├── schemas.py               # Data structures
  ├── retriever.py             # ContextRetriever (4 algorithms)
  ├── planner.py               # Planner (LLM-based)
  ├── editor.py                # CodeEditor (patch generation)
  ├── validator.py             # Validator (static checks)
  └── orchestrator.py          # AICodeEditor (main orchestrator)

docs/
  ├── AI_EDITOR_ARCHITECTURE.md # Full design
  ├── AI_EDITOR_INTEGRATION.md  # Integration guide
  ├── BEST_PRACTICES.md         # Best practices
  └── QUICK_REFERENCE.md        # This file
```

## Next Steps

1. Read `AI_EDITOR_ARCHITECTURE.md` for full design
2. Read `AI_EDITOR_INTEGRATION.md` for integration guide
3. Run simple test with AICodeEditor
4. Integrate with existing chat interface
5. Monitor metrics and iterate

---

**Version**: 1.0  
**Last Updated**: 2026-07-28  
**Status**: Ready for implementation
