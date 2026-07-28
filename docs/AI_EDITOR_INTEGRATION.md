# AI Editor Integration Guide

This guide shows how to integrate the new production-grade AI editing pipeline into your Shadow project.

## Quick Start

### 1. Basic Usage

```python
from assistant.ai_editor import AICodeEditor

# Initialize with your LLM client
editor = AICodeEditor(
    project_root="/path/to/project",
    llm_client=your_llm_client  # e.g., OllamaClient
)

# Handle a user request
result = editor.handle_request("Add email validation to the User model")

if result.success:
    print(f"✅ Applied {result.patches_applied} patches")
    print(f"Modified files: {result.modified_files}")
else:
    print(f"❌ Failed: {result.errors}")
    print(f"⚠️  Warnings: {result.warnings}")
```

### 2. Integrate with Existing Chat Engine

```python
# In your chat_engine.py or similar

from assistant.ai_editor import AICodeEditor

class ChatEngine:
    def __init__(self, project_root, llm_client):
        self.editor = AICodeEditor(project_root, llm_client)
    
    def handle_user_request(self, message: str) -> str:
        """Check if request is code-related, use editor if so."""
        
        # Determine if this is a coding request
        if self._is_coding_request(message):
            result = self.editor.handle_request(message)
            
            if result.success:
                return f"""
✅ Successfully applied changes:
- Modified {len(result.modified_files)} files
- Applied {result.patches_applied} patches
- Files: {', '.join(result.modified_files)}
"""
            else:
                return f"""
❌ Failed to apply changes:
- Errors: {', '.join(result.errors)}
- Warnings: {', '.join(result.warnings)}
"""
        else:
            # Use regular chat
            return self.chat(message)
    
    def _is_coding_request(self, message: str) -> bool:
        """Heuristic to detect coding requests."""
        coding_keywords = [
            "add", "change", "modify", "fix", "create", "delete",
            "refactor", "implement", "update", "function", "class",
            "test", "validate", "check"
        ]
        return any(kw in message.lower() for kw in coding_keywords)
```

### 3. Per-Stage Customization

If you want more control, use individual agents:

```python
from assistant.ai_editor import (
    ContextRetriever,
    Planner,
    CodeEditor,
    Validator,
)

# Retrieve context
retriever = ContextRetriever(project_root)
intent = analyze_intent(user_request)  # Your classifier
retrieval = retriever.retrieve(intent, max_files=8)

# Plan edits
planner = Planner(llm_client)
plan = planner.plan(intent, retrieval, user_request)

# Review plan (e.g., show to user)
print("Plan:")
for step in plan.steps:
    print(f"  {step.step_number}. {step.action}: {step.file}")

# Generate patches
editor = CodeEditor(llm_client)
patches = []
for step in plan.steps:
    if step.action != "understand":
        file_content = (project_root / step.file).read_text()
        context = CodeContext(...)
        patch = editor.generate_patch(step, file_content, context)
        patches.append(patch)

# Validate before applying
validator = Validator()
for patch in patches:
    validation = validator.validate(patch, file_content, patch.file)
    if not validation.is_valid:
        print(f"❌ Validation failed: {validation.errors}")
```

## Integration Points

### Current System → New System

Your current `assistant/coding_agent.py` does:
1. Build file tree
2. Find relevant files
3. Ask LLM for plan
4. Ask LLM to rewrite each file

New system does:
1. **Analyze intent** (intent classifier)
2. **Retrieve files** (4 algorithms: filename, symbol, ripgrep, embedding)
3. **Plan steps** (LLM, lightweight)
4. **Generate patches** (LLM, per-function, incremental)
5. **Validate patches** (syntax, imports, formatting)
6. **Apply patches** (safe, atomic per file)
7. **Test & retry** (auto-recovery)

### Minimal Migration Path

Replace this:
```python
from assistant.coding_agent import generate_plan, apply_plan

plan = generate_plan(project_path, issue)
result = apply_plan(project_path, plan, issue)
```

With this:
```python
from assistant.ai_editor import AICodeEditor

editor = AICodeEditor(project_path, llm_client)
result = editor.handle_request(issue)
```

### GUI Integration

In your `gui/ide/tab.py` (Code tab):

```python
# Current code
def on_plan_button_clicked(self):
    result = generate_plan(self.project_path, self.request)
    # ... show result to user

def on_apply_button_clicked(self):
    result = apply_plan(self.project_path, self.plan, self.request)
    # ... show result to user

# New code
from assistant.ai_editor import AICodeEditor

def on_plan_button_clicked(self):
    self.editor = AICodeEditor(self.project_path, self.llm_client)
    
    # Get plan only (stage 1-3)
    intent = self.editor._analyze_intent(self.request)
    retrieval = self.editor.retriever.retrieve(intent)
    plan = self.editor.planner.plan(intent, retrieval, self.request)
    
    # Show to user
    self.show_plan_review(plan)

def on_apply_button_clicked(self):
    # Apply with full pipeline (stages 4-8)
    result = self.editor.handle_request(self.request)
    self.show_apply_result(result)
```

## LLM Client Adapter

If your LLM client doesn't have `.complete()` method, create an adapter:

```python
class OllamaLLMAdapter:
    """Adapt Ollama streaming to standard LLM interface."""
    
    def __init__(self, base_url="http://localhost:11434", model="llama2"):
        self.base_url = base_url
        self.model = model
    
    def complete(self, prompt: str, max_tokens: int = 2000,
                 temperature: float = 0.1) -> str:
        """Call Ollama and collect streamed response."""
        from assistant.streaming import stream_chat
        
        response_parts = []
        for chunk in stream_chat(
            prompt,
            base_url=self.base_url,
            model=self.model,
        ):
            response_parts.append(chunk)
        
        return "".join(response_parts)
```

## Configuration

### Local LLM Recommendations

```python
# For quick iteration on your machine
editor = AICodeEditor(
    project_root=project_path,
    llm_client=LLMClient(
        model="qwen2.5:7b",  # Balanced size/speed
        temperature=0.1,     # Deterministic
        context_length=8192,
    )
)

# For better reasoning (if GPU allows)
editor = AICodeEditor(
    project_root=project_path,
    llm_client=LLMClient(
        model="llama2:13b",   # Larger context
        temperature=0.1,
        context_length=8192,
    )
)
```

### Environment Variables

```bash
# .env or settings.yaml
AI_EDITOR_PROJECT_ROOT=/path/to/project
AI_EDITOR_LLM_MODEL=qwen2.5:7b
AI_EDITOR_LLM_BASE_URL=http://localhost:11434
AI_EDITOR_MAX_FILES=8
AI_EDITOR_MAX_RETRIES=3
AI_EDITOR_TIMEOUT_SECONDS=180
```

## Testing the Integration

### Unit Test Example

```python
import pytest
from assistant.ai_editor import AICodeEditor
from pathlib import Path

@pytest.fixture
def editor(tmp_path):
    # Create test project
    project = tmp_path / "test_project"
    project.mkdir()
    
    # Create sample file
    py_file = project / "example.py"
    py_file.write_text("def hello(): return 'world'")
    
    # Create mock LLM
    class MockLLM:
        def complete(self, prompt, **kwargs):
            # Return simple JSON response
            return '{"steps": []}'
    
    return AICodeEditor(str(project), MockLLM())

def test_handle_request(editor):
    result = editor.handle_request("Add documentation")
    assert isinstance(result.success, bool)
    assert isinstance(result.errors, list)
```

### Integration Test Example

```python
def test_full_pipeline_add_validation():
    """Test adding email validation to User model."""
    
    project_path = Path("test_project")
    editor = AICodeEditor(str(project_path), OllamaLLMClient())
    
    # Create test file
    user_file = project_path / "models" / "user.py"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("""
class User:
    def __init__(self, email):
        self.email = email
""")
    
    # Request change
    result = editor.handle_request("Add email validation to User model")
    
    # Verify
    assert result.success, result.errors
    assert "user.py" in result.modified_files
    
    # Check that validation was added
    new_content = user_file.read_text()
    assert "validate" in new_content.lower() or "email" in new_content
```

## Debugging

### Enable Detailed Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("assistant.ai_editor")
logger.setLevel(logging.DEBUG)

# Now all debug messages appear
editor = AICodeEditor(project_root, llm_client)
result = editor.handle_request(request)
```

### Inspect Each Stage

```python
# Stage 1: Intent analysis
intent = editor._analyze_intent(request)
print(f"Intent: {intent.intent_type}, confidence: {intent.confidence}")
print(f"Keywords: {intent.keywords}")
print(f"Symbols: {intent.likely_symbols}")

# Stage 2: Retrieval
retrieval = editor.retriever.retrieve(intent)
print(f"Retrieved files: {[f.file_path for f in retrieval.files]}")
print(f"Found symbols: {list(retrieval.symbols.keys())}")

# Stage 3: Planning
plan = editor.planner.plan(intent, retrieval, request)
print(f"Plan steps:")
for step in plan.steps:
    print(f"  {step.step_number}. {step.action}: {step.file}")
```

### Trace Patch Generation

```python
from assistant.ai_editor import CodeEditor

editor = CodeEditor(llm_client)
patch = editor.generate_patch(step, file_content, context)

print(f"Generated patch with {len(patch.operations)} operations:")
for op in patch.operations:
    print(f"  - {op.type.value}")
    if op.search:
        print(f"    Search: {op.search[:50]}...")
    if op.replacement:
        print(f"    Replace: {op.replacement[:50]}...")
```

## Performance Tuning

### Reduce Retrieved Files

```python
# Default: 8 files
retrieval = editor.retriever.retrieve(intent, max_files=5)
```

### Reduce LLM Tokens

```python
class QuickPlanner(Planner):
    def plan(self, intent, retrieval, request):
        # Override: use fewer examples, shorter context
        prompt = self._build_short_prompt(intent, retrieval)
        response = self.llm.complete(prompt, max_tokens=1000)
        return self._parse_response(response)
```

### Parallel Processing

```python
from concurrent.futures import ThreadPoolExecutor

def apply_patches_parallel(patches):
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(apply_single_patch, patches))
    return results
```

## Common Issues & Solutions

### Issue: "Search text not found"
**Solution**: File content changed between retrieval and patch generation.
- **Fix**: Retry with fresh file content
- **Prevention**: Validate patch immediately before applying

### Issue: "Syntax error after patch"
**Solution**: LLM generated invalid Python.
- **Fix**: Validator catches this before applying
- **Prevention**: Use smaller context, add syntax examples to prompt

### Issue: "Imports not found"
**Solution**: Patch removed import that's still used.
- **Fix**: Validator checks for this
- **Prevention**: LLM told not to remove existing code

### Issue: Tests fail after changes
**Solution**: Patch breaks existing functionality.
- **Fix**: Auto-retry with error feedback
- **Prevention**: Better test coverage in project

## Next Steps

1. **Week 1**: Core integration (ContextRetriever + Planner)
2. **Week 2**: Full pipeline (CodeEditor + Validator + Orchestrator)
3. **Week 3**: GUI integration and testing
4. **Week 4**: Performance optimization
5. **Week 5**: Deploy and monitor

See `docs/AI_EDITOR_ARCHITECTURE.md` for full design documentation.
