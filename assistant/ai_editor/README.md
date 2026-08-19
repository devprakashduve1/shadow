# AI Code Editor - Production-Grade Code Editing Engine

A professional, multi-stage code editing system with automated analysis, planning, validation, and execution. Delivers production-ready code modifications with minimal manual intervention.

**Status**: ✅ Production Ready  
**Type**: Code Editing & Automation Engine  
**Version**: 2.0

---

## What It Does

Transforms user requirements into safe, validated code changes through intelligent workflow stages:

```
User Requirement
    ↓
[Intent Analysis] → Understand what user wants
    ↓
[Requirement Extraction] → Parse requirements and dependencies
    ↓
[Context Retrieval] → Find relevant code files
    ↓
[Plan Generation] → Create step-by-step execution plan
    ↓
[Plan Review] → Format for user review
    ↓
[User Approval] → Get explicit confirmation
    ↓
[Code Generation] → Generate code modifications
    ↓
[Validation] → Check safety and correctness
    ↓
[Execution] → Apply changes, format, lint, test
    ↓
Result (success with report or detailed errors)
```

---

## Quick Start

### Installation

```python
from assistant.ai_editor.core import CodeEditingEngine

# Initialize
engine = CodeEditingEngine(
    project_root="/path/to/project",
    llm_client=your_llm_client  # LLM with .complete() method
)

# Execute
result = engine.handle_request(
    "Add email validation to User model",
    require_approval=True  # Show plan to user
)

if result.success:
    print(f"✅ Applied {result.patches_applied} patches")
    print(f"Modified: {result.modified_files}")
else:
    print(f"❌ Failed: {result.errors}")
```

### Preview Plan (Without Applying)

```python
from assistant.ai_editor.workflow import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator(project_root, llm_client)

# Get plan review without making changes
review = orchestrator.get_plan_review("Add validation")

if review:
    print(review.format_for_display())
```

---

## Features

### 1. Intelligent Analysis
- Extracts requirements from natural language
- Identifies affected components
- Detects potential breaking changes
- Scores complexity and confidence

### 2. Safe Planning
- Step-by-step execution plans
- Impact assessment
- Dependency tracking
- Risk identification

### 3. User-Friendly Workflow
- Shows plan before execution
- Displays code changes as diffs
- Allows plan refinement
- Requires explicit approval

### 4. Comprehensive Validation
- Syntax checking
- Import validation
- Format preservation
- Conflict detection
- Safe application

### 5. Professional Naming
- No layman's language
- Industry-standard terminology
- Clear intent in all names
- Professional API design

---

## Architecture

### Feature-Based Organization

```
ai_editor/
├── core/                      # Code Editing Engine
│   ├── engine.py             # Main editing orchestrator
│   ├── editor.py             # Patch generation
│   └── validator.py          # Safety validation
│
├── workflow/                  # Workflow Management
│   ├── orchestrator.py       # Workflow controller
│   ├── session_manager.py    # Session state
│   ├── approval_manager.py   # User confirmations
│   └── execution_controller.py
│
├── visualization/             # Change Display
│   ├── change_presenter.py   # Present code changes
│   └── diff_formatter.py     # Format diffs
│
├── adaptation/                # User Feedback
│   ├── feedback_processor.py # Process input
│   └── plan_refiner.py       # Refine plans
│
├── retrieval/                 # Context Retrieval
│   ├── requirement_extractor.py
│   ├── context_retriever.py
│   └── planner.py
│
├── schemas/                   # Data Models
│   └── models.py             # All dataclasses
│
└── interactive/               # CLI Interface
    ├── cli_interface.py      # Command-line interface
    └── examples.py           # Usage examples
```

---

## Core Modules

### CodeEditingEngine (`core/engine.py`)
Main orchestrator for the entire editing workflow.

```python
engine = CodeEditingEngine(project_root, llm_client)
result = engine.handle_request(requirement, require_approval=True)
```

### WorkflowOrchestrator (`workflow/orchestrator.py`)
Controls workflow phases and user interactions.

```python
orchestrator = WorkflowOrchestrator(project_root, llm_client)
review = orchestrator.get_plan_review(requirement)
```

### RequirementExtractor (`retrieval/requirement_extractor.py`)
Analyzes and extracts requirements from input.

```python
extractor = RequirementExtractor(llm_client)
requirements = extractor.analyze(user_input)
```

### CodeChangePresenter (`visualization/change_presenter.py`)
Generates and formats code diffs for display.

```python
presenter = CodeChangePresenter()
diff_text = presenter.generate_unified_format(before, after, "file.py")
```

### UserFeedbackProcessor (`adaptation/feedback_processor.py`)
Processes user feedback and refines plans.

```python
processor = UserFeedbackProcessor(llm_client)
feedback = processor.parse_user_feedback_input("Also add rate limiting")
```

---

## Usage Patterns

### Pattern 1: Auto Mode (No Approval)
```python
engine = CodeEditingEngine(project_root, llm_client)
result = engine.handle_request(requirement, require_approval=False)
```

### Pattern 2: Interactive Mode (With Approval)
```python
engine = CodeEditingEngine(project_root, llm_client)
result = engine.handle_request(requirement, require_approval=True)
# User sees plan and approves/rejects
```

### Pattern 3: Preview Only
```python
orchestrator = WorkflowOrchestrator(project_root, llm_client)
review = orchestrator.get_plan_review(requirement)
print(review.format_for_display())
```

### Pattern 4: Custom Approval Handler
```python
def approval_handler(confirmation):
    # Show approval dialog in GUI
    return user_decision

engine = CodeEditingEngine(project_root, llm_client)
engine.set_confirmation_callback(approval_handler)
result = engine.handle_request(requirement)
```

---

## Result Format

### Success
```python
EditResult(
    success=True,
    patches_applied=3,
    modified_files=['file1.py', 'file2.py', 'file3.py'],
    errors=[],
    warnings=['Minor linting issue in file1.py'],
    total_time_seconds=28.5
)
```

### Failure
```python
EditResult(
    success=False,
    patches_applied=0,
    modified_files=[],
    errors=['User rejected the proposed changes'],
    warnings=[],
    total_time_seconds=5.2
)
```

---

## Standards & Conventions

### Naming Standards
- **Classes**: PascalCase (e.g., `CodeEditingEngine`)
- **Methods**: snake_case with action verbs (e.g., `append_message()`)
- **Variables**: snake_case with explicit context (e.g., `user_requirement`)
- **Files**: snake_case (e.g., `session_manager.py`)
- **Directories**: lowercase category (e.g., `core/`, `workflow/`)

### No Implementation-Specific Language
- ✅ Generic terminology (not "Claude-style")
- ✅ Professional naming (not layman's language)
- ✅ Standard patterns (industry-recognized)
- ✅ Clear intent in every name

---

## LLM Setup

### Ollama Installation

```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Pull model
ollama pull qwen2.5:7b

# Start server
ollama serve

# Test
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"hello"}'
```

### Recommended Models

| Model | Size | Context | Quality |
|-------|------|---------|---------|
| Qwen2.5 7B | 7B | 32K | ⭐⭐⭐⭐ |
| CodeLlama 13B | 13B | 4K | ⭐⭐⭐⭐⭐ |
| DeepSeek Coder 34B | 34B | 16K | ⭐⭐⭐⭐⭐ |

### LLM Client Adapter

```python
class OllamaClient:
    def __init__(self, model="qwen2.5:7b"):
        self.model = model
    
    def complete(self, prompt, max_tokens=2000, temperature=0.1):
        # Call Ollama API
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": self.model, "prompt": prompt}
        )
        return response.json()["response"]

llm = OllamaClient()
engine = CodeEditingEngine(project_root, llm)
```

---

## Integration

### Replace Old System

Old:
```python
from assistant.coding_agent import generate_plan, apply_plan
result = apply_plan(project_path, generate_plan(project_path, issue))
```

New:
```python
from assistant.ai_editor.core import CodeEditingEngine
engine = CodeEditingEngine(project_path, llm_client)
result = engine.handle_request(issue)
```

### Web API

```python
@app.route("/api/code/review", methods=["POST"])
def review_changes():
    orchestrator = WorkflowOrchestrator(project_root, llm_client)
    review = orchestrator.get_plan_review(request.json["request"])
    
    return {
        "review": review.format_for_display(),
        "files_affected": review.files_affected,
        "requirements": [r.description for r in review.props_analysis.requirements]
    }

@app.route("/api/code/apply", methods=["POST"])
def apply_changes():
    if not request.json.get("approved"):
        return {"error": "Changes not approved"}
    
    engine = CodeEditingEngine(project_root, llm_client)
    result = engine.handle_request(
        request.json["request"],
        require_approval=False
    )
    return result.to_dict()
```

---

## Testing

### Unit Tests

```python
from assistant.ai_editor.core import CodeEditingEngine
from assistant.ai_editor.schemas import WorkflowPhase

def test_engine_initialization():
    engine = CodeEditingEngine(project_root, mock_llm)
    assert engine is not None
    assert engine.project_root == Path(project_root)

def test_requirement_analysis():
    engine = CodeEditingEngine(project_root, mock_llm)
    result = engine.handle_request("Add validation", require_approval=False)
    assert result.success or result.errors
    assert isinstance(result.modified_files, list)
```

---

## Troubleshooting

### Changes Not Applied
```python
result = engine.handle_request(requirement)
print(f"Success: {result.success}")
print(f"Errors: {result.errors}")
print(f"Warnings: {result.warnings}")
```

### Slow Performance
- Use faster LLM model (Qwen 7B)
- Reduce max_files parameter
- Use quantized model (4-bit)
- Compress context before sending

### Tests Failing
```python
if result.test_results:
    print(f"Tests passed: {result.test_results.passed}")
    print(f"Failed tests: {result.test_results.failed_tests}")
```

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Success Rate | >90% |
| Validation Rate | >95% |
| Test Pass Rate | >85% |
| Average Time | <30s |
| Avg Retries | <1.5 |

---

## Support

For issues or integration help:
- Check the interactive CLI: `python -m assistant.ai_editor.interactive.cli_interface`
- Review examples: `assistant.ai_editor.interactive.examples`
- Read code comments for implementation details

---

## Release Notes

### v2.0 (Current)
- ✅ Professional naming standards applied
- ✅ Feature-based organization
- ✅ Interactive CLI interface
- ✅ Comprehensive validation
- ✅ User approval workflow
- ✅ Plan refinement support

### v1.0
- Initial architecture
- Core editing pipeline
- Validation framework

---

**Status**: ✅ Production Ready  
**Last Updated**: 2026-08-06  
**License**: Part of Shadow Project
