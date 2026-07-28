# AI Code Editor: Robust Editing Pipeline Architecture

**Document Version**: 1.0  
**Date**: 2026-07-28  
**Target Systems**: Cursor, Cline, Roo Code, Windsurf-equivalent reliability

---

## Executive Summary

This document redesigns your AI editor's editing pipeline from a simple "generate plan → rewrite files" approach into a multi-stage, failure-resistant system. The key innovation is **splitting editing into discrete, validatable stages** instead of asking the LLM to both understand and modify code simultaneously.

### Current Problems
- LLM asked to do too much: analyze + plan + code all at once
- No intermediate validation—errors discovered only after writing
- Full file rewrites—introduces bugs in untouched areas
- No retry/recovery mechanism
- Context too large/unfocused for local LLMs
- No symbol-aware code navigation

### Solution
- **Stage-based pipeline**: Request → Analysis → Planning → Execution → Validation
- **Specialized agents**: Intent Analyzer, Context Retriever, Planner, Code Editor, Validator
- **Incremental patches**: JSON-structured edits, not full rewrites
- **Validation gates**: Check before apply, retry on failure
- **Local LLM optimized**: Token budgeting, context compression, staged reasoning

---

## Part 1: Pipeline Architecture

### Stage 1: Request Analysis

**Input**: User's natural language request  
**Output**: Structured intent analysis (JSON)

```json
{
  "intent_type": "fix|feature|refactor|test|docs|debug",
  "confidence": 0.85,
  "summary": "Add validation to user email field",
  "keywords": ["validation", "email", "user"],
  "requires_new_file": false,
  "requires_delete": false,
  "likely_files": ["auth/validators.py", "models/user.py"],
  "likely_symbols": ["validate_email", "User", "email_regex"],
  "complexity_score": 3,
  "estimated_files": 2,
  "breaking_changes_risk": "low|medium|high",
  "test_needed": true
}
```

**Algorithm**:
```
1. Tokenize request
2. Extract keywords (nouns, verbs, technical terms)
3. Classify into intent type (decision tree or classifier)
4. Assess scope (file count estimate)
5. Flag breaking changes
6. Score complexity (1-5)
```

**Local LLM Optimization**:
- Use a small classifier (3-layer NN or tree-based)
- Don't use LLM for this if possible—pre-defined patterns faster
- If using LLM: 1-shot prompt, max 256 tokens

---

### Stage 2: Project Indexing & File Retrieval

**Input**: Project path, request analysis  
**Output**: Minimal set of relevant files with context

#### 2.1 Multi-Algorithm File Search Strategy

Run these in parallel; merge results by relevance score:

##### Algorithm A: Filename Search
```python
def filename_search(project_root, keywords, max_results=10):
    """
    Match keywords against file/folder names.
    Exact > Substring > Fuzzy > Prefix
    """
    files = []
    for file_path in walk_project(project_root):
        name = file_path.name
        score = 0
        for keyword in keywords:
            if keyword == name.lower(): score += 100
            elif keyword in name.lower(): score += 50
            elif fuzzy_match(keyword, name): score += 25
            elif name.startswith(keyword): score += 15
        if score > 0:
            files.append((file_path, score))
    
    return sorted(files, key=lambda x: x[1], reverse=True)[:max_results]
```

##### Algorithm B: AST-Aware Symbol Search
```python
def symbol_search(project_root, symbols, language="python"):
    """
    Parse each file's AST, find definitions of symbols.
    Returns file + line number for each symbol.
    """
    results = {}
    for file_path in walk_files(project_root, extensions=[language_ext]):
        try:
            tree = parse_ast(file_path)
            for symbol in symbols:
                for node in walk_ast(tree):
                    if node.name == symbol:
                        results[symbol] = {
                            "file": file_path,
                            "line": node.lineno,
                            "type": node.__class__.__name__
                        }
        except:
            pass  # Skip files that don't parse
    
    return results
```

##### Algorithm C: Ripgrep (Regex Search)
```bash
# Fast pattern matching across whole project
rg --type python 'def validate_email|class User' \
   --line-number --with-filename
```

##### Algorithm D: Embedding-Based Semantic Search
```python
def embedding_search(project_root, request_text, k=5):
    """
    Use sentence transformer or similar.
    Requires pre-built embeddings index.
    
    Fallback if filename/symbol search insufficient.
    """
    if not index_exists():
        return []
    
    query_embedding = encode(request_text)
    results = index.search(query_embedding, k=k)
    return [(file, score) for file, score in results]
```

**Selection Strategy**:
```python
def find_relevant_files(project_root, intent_analysis, max_files=8):
    """
    1. Filename search on keywords
    2. Symbol search on likely_symbols
    3. Ripgrep for intent keywords
    4. Embedding search if confidence < 0.8
    5. Merge by score, deduplicate, limit to max_files
    """
    results = {}
    
    # Filename search
    for file, score in filename_search(project_root, intent_analysis["keywords"]):
        results[file] = results.get(file, 0) + score * 1.0
    
    # Symbol search
    for symbol, info in symbol_search(project_root, intent_analysis["likely_symbols"]).items():
        file = info["file"]
        results[file] = results.get(file, 0) + 50
    
    # Ripgrep
    for match in ripgrep_search(project_root, intent_analysis["keywords"]):
        results[match.file] = results.get(match.file, 0) + 30
    
    # Embedding search (if needed)
    if len(results) < 3:
        for file, score in embedding_search(project_root, intent_analysis["summary"]):
            results[file] = results.get(file, 0) + score * 20
    
    # Sort and limit
    ranked = sorted(results.items(), key=lambda x: x[1], reverse=True)
    return [file for file, _ in ranked[:max_files]]
```

#### 2.2 Context Bundling

For each retrieved file:
```json
{
  "file_path": "auth/validators.py",
  "language": "python",
  "size_bytes": 2048,
  "imports": ["re", "typing"],
  "symbols": {
    "validate_email": {"line": 15, "type": "function"},
    "email_regex": {"line": 5, "type": "variable"}
  },
  "content": "# file content (full or truncated)",
  "related_files": ["models/user.py", "tests/test_validators.py"],
  "last_modified": "2026-07-20",
  "test_coverage": 0.85
}
```

---

### Stage 3: Symbol & Dependency Analysis

**Input**: Retrieved files  
**Output**: Symbol table, call graph, dependency map

```json
{
  "symbols": {
    "validate_email": {
      "file": "auth/validators.py",
      "line": 15,
      "type": "function",
      "signature": "validate_email(email: str) -> bool",
      "called_by": ["User.validate", "signup_handler"],
      "calls": ["re.match", "email_regex"],
      "tests": ["test_validators.py::test_validate_email"]
    }
  },
  "dependencies": {
    "auth/validators.py": ["re", "typing", "models/user.py"],
    "models/user.py": ["auth/validators.py"]
  },
  "call_graph": {
    "signup_handler": ["validate_email", "create_user"],
    "validate_email": ["re.match"]
  },
  "breaking_risk": {
    "validate_email": "high"  # if heavily used
  }
}
```

---

### Stage 4: Planning (LLM Orchestrates, Doesn't Code)

**Input**: Intent, retrieved files, symbol analysis  
**Output**: Structured editing plan

```json
{
  "plan_id": "plan-20260728-001",
  "steps": [
    {
      "step_number": 1,
      "action": "understand",
      "file": "auth/validators.py",
      "goal": "Read current email validation logic",
      "instruction": "Do not modify. Just identify what needs changing."
    },
    {
      "step_number": 2,
      "action": "modify",
      "file": "auth/validators.py",
      "target_function": "validate_email",
      "change_type": "add_validation",
      "details": "Add stricter DNS check for domain"
    },
    {
      "step_number": 3,
      "action": "create",
      "file": "tests/test_validators_dns.py",
      "goal": "Test new DNS validation"
    }
  ],
  "estimated_impact": {
    "files_to_create": 1,
    "files_to_modify": 1,
    "files_to_test": 2,
    "breaking_changes": 0,
    "risk_level": "low"
  },
  "requires_user_approval": false,
  "estimated_tokens": 2500
}
```

**Prompt Strategy for Local LLMs**:
```
USER REQUEST: [request]

CONTEXT:
- Intent: [intent analysis JSON]
- Affected files: [list of files + line ranges]
- Current symbols: [relevant functions/classes]

TASK: Create a step-by-step plan (NOT code yet).

For each step, specify:
1. File to edit
2. What to change (be specific: line range, function, class)
3. Why this change
4. Risk assessment

Keep plan concise. Output JSON ONLY.

NO CODE IN THIS STAGE.
```

---

### Stage 5: Patch Generation (Focused, Not Full Rewrites)

**Input**: Plan step, current file content, related symbols  
**Output**: Structured patch

#### Option A: Unified Diff Format
```diff
--- a/auth/validators.py
+++ b/auth/validators.py
@@ -15,6 +15,12 @@
     def validate_email(email: str) -> bool:
         """Validate email format."""
-        return bool(re.match(email_regex, email))
+        if not re.match(email_regex, email):
+            return False
+        # Add DNS check
+        domain = email.split('@')[1]
+        try:
+            socket.gethostbyname(domain)
+        except socket.gaierror:
+            return False
+        return True
```

#### Option B: JSON Patch Operations
```json
{
  "file": "auth/validators.py",
  "operations": [
    {
      "type": "replace",
      "line_start": 15,
      "line_end": 17,
      "search": "def validate_email(email: str) -> bool:\n    \"\"\"Validate email format.\"\"\"\n    return bool(re.match(email_regex, email))",
      "replacement": "def validate_email(email: str) -> bool:\n    \"\"\"Validate email format and DNS.\"\"\"\n    if not re.match(email_regex, email):\n        return False\n    domain = email.split('@')[1]\n    try:\n        socket.gethostbyname(domain)\n    except socket.gaierror:\n        return False\n    return True"
    },
    {
      "type": "add_import",
      "import": "import socket",
      "after_line": 2
    }
  ],
  "validation": {
    "syntax_valid": true,
    "imports_valid": true,
    "line_count_before": 25,
    "line_count_after": 31
  }
}
```

**LLM Prompt for Patch Generation**:
```
FILE: auth/validators.py
CURRENT CONTENT:
[lines surrounding target function]

PLAN STEP:
- Target: validate_email function
- Change: Add DNS validation check
- Keep: Current regex validation

RULES:
1. Only modify the function body
2. Keep function signature unchanged
3. Don't remove existing validation
4. Add import if needed: socket

OUTPUT FORMAT (JSON PATCH):
{
  "operations": [
    {"type": "replace", "search": "...", "replacement": "..."},
    {"type": "add_import", "import": "...", "after_line": N}
  ]
}

NO explanations. JSON ONLY.
```

---

### Stage 6: Patch Validation

**Before applying any patch**, run these checks:

```python
def validate_patch(file_path, patch_operations, current_content):
    """
    Validate patch is safe to apply.
    Return: (is_valid, errors, warnings)
    """
    errors = []
    warnings = []
    
    # Check 1: Search text exists
    for op in patch_operations:
        if op["type"] == "replace":
            if op["search"] not in current_content:
                errors.append(f"Search text not found: {op['search'][:50]}...")
    
    # Check 2: Syntax validity
    if file_path.endswith(".py"):
        new_content = apply_patch_to_content(current_content, patch_operations)
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            errors.append(f"Syntax error after patch: {e}")
    
    # Check 3: Imports remain valid
    for op in patch_operations:
        if op["type"] == "replace":
            old_imports = extract_imports(op["search"])
            new_imports = extract_imports(op["replacement"])
            missing = set(old_imports) - set(new_imports)
            if missing and "import" in op.get("replacement", ""):
                warnings.append(f"Potentially removed imports: {missing}")
    
    # Check 4: Formatting preserved
    if has_format_violations(patch_operations):
        warnings.append("Formatting may not match project conventions")
    
    # Check 5: File can be parsed
    new_content = apply_patch_to_content(current_content, patch_operations)
    try:
        parser.parse(new_content, language=infer_language(file_path))
    except:
        errors.append("File doesn't parse after patch")
    
    return len(errors) == 0, errors, warnings
```

---

### Stage 7: Apply & Test

**Execute**:
```python
def apply_patch_sequence(project_path, patches):
    """
    Apply patches one by one, validate each.
    If any fails, stop and report.
    """
    for patch in patches:
        file_path = project_path / patch["file"]
        current = file_path.read_text()
        
        # Validate
        valid, errors, warnings = validate_patch(
            file_path, patch["operations"], current
        )
        if not valid:
            raise ValidationError(f"Patch failed validation: {errors}")
        
        # Apply
        new_content = apply_patch_to_content(current, patch["operations"])
        file_path.write_text(new_content)
        
        # Format & Lint (if applicable)
        if file_path.suffix == ".py":
            format_file(file_path)  # black, autopep8, etc.
            lint_results = lint_file(file_path)  # pylint, flake8
            if lint_results.errors:
                raise LintError(f"Lint errors after patch: {lint_results}")
```

**Run tooling**:
```bash
# Formatter
black --line-length 88 auth/validators.py

# Linter
pylint auth/validators.py

# Type checker (Python)
mypy auth/validators.py

# Tests
pytest tests/test_validators.py -v

# Compiler (JS/TS/Go/etc.)
tsc  # or equivalent
```

---

### Stage 8: Retry Logic

If any stage fails, retry with feedback:

```python
def apply_with_retry(project_path, plan, max_retries=3):
    """
    Apply patches with automatic retry on failure.
    """
    patches = generate_patches(plan)
    
    for retry_count in range(max_retries):
        try:
            # Validate all patches
            for patch in patches:
                valid, errors, warnings = validate_patch(...)
                if not valid:
                    raise ValidationError(errors)
            
            # Apply all patches
            apply_patch_sequence(project_path, patches)
            
            # Run tests
            test_results = run_tests(project_path)
            if not test_results.passed:
                raise TestError(test_results.failures)
            
            return ApplyResult(success=True, patches_applied=len(patches))
        
        except (ValidationError, LintError, TestError) as e:
            if retry_count < max_retries - 1:
                # Ask LLM to fix based on error
                patches = regenerate_patches_for_error(
                    plan, e.details, patches
                )
            else:
                raise
```

---

## Part 2: Specialized AI Agents

### Architecture Overview

```
User Request
    ↓
[Intent Analyzer] → Intent JSON
    ↓
[Context Retriever] → Relevant files + symbols
    ↓
[Planner] → Structured plan
    ↓
[Code Editor] → Generate patches
    ↓
[Validator] → Check safety
    ↓
[Test Runner] → Verify correctness
    ↓
Success or Retry
```

### Agent Specifications

#### Agent 1: Intent Analyzer
**Responsibility**: Understand what the user wants  
**Input**: Natural language request  
**Output**: Intent JSON (as per Stage 1)

```python
class IntentAnalyzer:
    def __init__(self, classifier_model=None):
        # Use small classifier or patterns
        self.classifier = classifier_model or DefaultIntentClassifier()
    
    def analyze(self, request: str) -> IntentAnalysis:
        keywords = extract_keywords(request)
        intent_type = self.classifier.predict(request)
        complexity = self._estimate_complexity(request)
        
        return IntentAnalysis(
            intent_type=intent_type,
            confidence=self.classifier.confidence,
            keywords=keywords,
            complexity_score=complexity,
            # ... other fields
        )
    
    def _estimate_complexity(self, request: str) -> int:
        # 1-5 score based on keywords
        pass
```

**LLM Usage**: Optional (prefer classifier)

---

#### Agent 2: Context Retriever
**Responsibility**: Find relevant files and symbols  
**Input**: Intent analysis, project root  
**Output**: Bundled files + symbol map

```python
class ContextRetriever:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.symbol_index = SymbolIndex.build(project_root)
    
    def retrieve(self, intent: IntentAnalysis) -> RetrievalResult:
        # Run all search algorithms in parallel
        candidates = {}
        
        candidates.update(self._filename_search(intent.keywords))
        candidates.update(self._symbol_search(intent.likely_symbols))
        candidates.update(self._ripgrep_search(intent.keywords))
        
        # If confidence low, add embedding search
        if intent.confidence < 0.8:
            candidates.update(self._embedding_search(intent.summary))
        
        # Score and limit
        ranked = self._rank_candidates(candidates)
        files = self._bundle_files(ranked[:8])
        symbols = self._build_symbol_table(files)
        
        return RetrievalResult(files=files, symbols=symbols)
    
    def _filename_search(self, keywords): pass
    def _symbol_search(self, symbols): pass
    def _ripgrep_search(self, keywords): pass
    def _embedding_search(self, text): pass
```

**LLM Usage**: None

---

#### Agent 3: Planner
**Responsibility**: Create step-by-step editing plan  
**Input**: Intent, retrieved files, symbols  
**Output**: Structured plan JSON

```python
class Planner:
    def __init__(self, llm_client):
        self.llm = llm_client
    
    def plan(self, intent: IntentAnalysis, 
             retrieval: RetrievalResult) -> PlanResult:
        
        # Build minimal prompt
        prompt = self._build_prompt(intent, retrieval)
        
        # Call LLM (small model, local)
        response = self.llm.complete(
            prompt,
            max_tokens=2000,
            temperature=0.1  # deterministic
        )
        
        # Parse plan JSON
        plan = parse_plan_json(response)
        
        # Validate plan
        plan = self._validate_plan(plan, retrieval)
        
        return plan
    
    def _build_prompt(self, intent, retrieval) -> str:
        """Minimal prompt: describe what to do, not how."""
        return f"""
        REQUEST: {intent.summary}
        
        FILES:
        {self._format_file_list(retrieval.files)}
        
        SYMBOLS:
        {self._format_symbols(retrieval.symbols)}
        
        Create a step-by-step PLAN (no code).
        Output JSON: {{"steps": [...]}}
        """
```

**LLM Usage**: Yes (lightweight)  
**Token Budget**: ~2000 tokens  
**Temperature**: 0.1 (deterministic)

---

#### Agent 4: Code Editor
**Responsibility**: Generate patches for each plan step  
**Input**: Plan step, file content, symbols, related files  
**Output**: JSON patch operations

```python
class CodeEditor:
    def __init__(self, llm_client):
        self.llm = llm_client
    
    def generate_patch(self, step: PlanStep, 
                       file_content: str,
                       context: CodeContext) -> Patch:
        
        # Build focused prompt
        prompt = self._build_edit_prompt(step, file_content, context)
        
        # Call LLM
        response = self.llm.complete(
            prompt,
            max_tokens=3000,
            temperature=0.1
        )
        
        # Parse patch
        patch = parse_json_patch(response)
        
        # Validate immediately
        valid, errors = validate_patch(file_content, patch)
        if not valid:
            # Retry with error feedback
            return self._retry_patch(step, file_content, context, errors)
        
        return patch
    
    def _build_edit_prompt(self, step, content, context) -> str:
        """Highly focused: edit only one function."""
        return f"""
        FILE: {step.file}
        TARGET: {step.target_function}
        
        CURRENT CODE:
        [relevant lines only, ~30 lines]
        
        RELATED FUNCTIONS:
        {self._format_related(context.related)}
        
        CHANGE: {step.details}
        
        Rules:
        1. Keep function signature
        2. Don't touch other functions
        3. Add imports if needed
        
        Output ONLY JSON patch:
        {{"operations": [...]}}
        """
```

**LLM Usage**: Yes (per patch)  
**Token Budget**: ~3000 tokens  
**Temperature**: 0.1

---

#### Agent 5: Validator
**Responsibility**: Check patches for correctness  
**Input**: Patch, current file, syntax checker  
**Output**: Validation result

```python
class Validator:
    def validate(self, patch: Patch, file_content: str,
                 file_path: str) -> ValidationResult:
        
        errors = []
        warnings = []
        
        # 1. Syntax check
        new_content = apply_patch(file_content, patch)
        if not is_valid_syntax(new_content, file_path):
            errors.append("Invalid syntax after patch")
        
        # 2. Search text exists
        for op in patch.operations:
            if op.type == "replace":
                if op.search not in file_content:
                    errors.append(f"Search text not found")
        
        # 3. Imports valid
        missing = check_missing_imports(new_content)
        if missing:
            warnings.append(f"Possible missing imports: {missing}")
        
        # 4. No breaking changes
        if is_breaking_change(patch):
            warnings.append("Potential breaking change")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
```

**LLM Usage**: None (pure validation)

---

#### Agent 6: Test Runner
**Responsibility**: Execute tests after applying changes  
**Input**: Project path, modified files  
**Output**: Test result

```python
class TestRunner:
    def run_tests(self, project_path: Path,
                  modified_files: List[str]) -> TestResult:
        
        # Find relevant tests
        test_files = self._find_related_tests(project_path, modified_files)
        
        # Run tests
        try:
            result = subprocess.run(
                ["pytest"] + test_files,
                cwd=project_path,
                capture_output=True,
                timeout=60
            )
            
            return TestResult(
                passed=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                failed_tests=parse_pytest_output(result.stdout)
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                error="Tests timed out after 60s"
            )
```

**LLM Usage**: None

---

## Part 3: Best Practices from Modern Editors

### 1. RAG (Retrieval-Augmented Generation)
- Index project files with embeddings
- Retrieve most relevant files before asking LLM
- Reduces token spend, improves accuracy

### 2. AST-Aware Editing
- Parse files into AST
- Navigate by symbol, not text
- Ensure edits respect language structure

### 3. Symbol Indexing
- Build once, reuse many times
- Track: definitions, usages, imports
- Enable "go to definition" + "find references"

### 4. Incremental Patching
- Generate patches (diff format), not full files
- Smaller LLM output
- Easier to review and validate

### 5. Token Optimization
- Context compression (remove comments, docstrings)
- Staged reasoning (plan before code)
- Batch related edits in one prompt

### 6. Conversation Memory
- Store plan, retrieval, previous attempts
- Reuse context across retries
- Reduce redundant LLM calls

### 7. Project Summaries
- File tree with descriptions
- Key symbols per file
- Entry points and patterns

### 8. Confidence Scoring
- Score each retrieval match
- Score patch validity
- Score test pass/fail likelihood

### 9. Edit Verification
- Syntax check before applying
- Lint/format check after applying
- Test pass/fail after applying

### 10. Automatic Recovery
- If patch fails: show errors to LLM
- Ask LLM to fix specifically
- Max 3 retries before manual intervention

---

## Part 4: Local LLM Optimizations

Local models (Qwen, DeepSeek, Llama, CodeLlama) have constraints:
- Limited context window (4K-16K typically)
- Slower inference (2-10 s/token)
- Lower reasoning ability than GPT-4/Claude

### Strategy 1: Staged Prompting

Instead of:
```
"Here's a project. Here's a request. Modify the code."
```

Do this:
```
Stage 1: "Understand this request. Output JSON analysis."
Stage 2: "Here's a plan. Find the relevant files."
Stage 3: "Here's a file. Change line X to Y."
```

Each stage is smaller, more focused, replayable.

### Strategy 2: Few-Shot Examples

```python
EXAMPLES = [
    {
        "request": "Add email validation",
        "analysis": {
            "intent_type": "feature",
            "keywords": ["email", "validation"],
            "complexity_score": 2
        }
    },
    # ... 3-5 more examples
]

prompt = f"""
Examples:
{format_examples(EXAMPLES)}

REQUEST: {user_request}
OUTPUT: {{...}}
"""
```

### Strategy 3: Context Compression

```python
def compress_context(file_content: str, language: str) -> str:
    """
    Remove:
    - Comments (unless critical)
    - Docstrings (first line only)
    - Test code
    - Import sections (summary only)
    """
    lines = file_content.split('\n')
    compressed = []
    
    for line in lines:
        if line.strip().startswith('#'):
            continue  # skip comments
        if '"""' in line or "'''" in line:
            # Keep only docstring summary
            compressed.append(extract_docstring_summary(line))
        else:
            compressed.append(line)
    
    return '\n'.join(compressed)
```

### Strategy 4: Temperature & Top-P Tuning

```python
# For analysis/classification: deterministic
llm.complete(prompt, temperature=0.0, top_p=0.95)

# For planning: slightly creative
llm.complete(prompt, temperature=0.1, top_p=0.9)

# For code generation: balanced
llm.complete(prompt, temperature=0.3, top_p=0.85)
```

### Strategy 5: Explicit Format Enforcement

```python
prompt = """
...
OUTPUT MUST BE VALID JSON. Only JSON, nothing else.
{
  "intent_type": "...",
  "confidence": 0.85,
  ...
}
"""

# Parse aggressively
try:
    result = json.loads(response)
except:
    # Extract JSON from response
    result = extract_json(response)
```

### Strategy 6: Retry with Smaller Context

If first attempt fails:
```python
def retry_with_reduced_context(original_prompt, error):
    # Remove least important context
    reduced_prompt = remove_examples(original_prompt)
    reduced_prompt += f"\n\nPrevious error: {error}\nFix it."
    
    return llm.complete(reduced_prompt, ...)
```

### Strategy 7: Use Quantized Models

```
Preferred for local setup:
- Qwen 2.5 7B (4K context, ~2s token)
- DeepSeek Coder 7B (4K context, ~2s token)
- CodeLlama 7B (8K context, ~3s token)
- Mistral 7B (8K context, ~2s token)

For better reasoning (if hardware allows):
- Llama 3 70B (8K context, ~5s token)
- DeepSeek Coder 34B (16K context, ~8s token)

Quantization:
- Use GGUF format (llama.cpp)
- 4-bit quantization (Q4_K_M)
- 5-10x faster with 1-2% accuracy loss
```

---

## Part 5: Production-Ready Pseudocode

### Core Pipeline

```python
class AICodeEditor:
    def __init__(self, project_root: str, llm_client):
        self.project_root = Path(project_root)
        self.llm = llm_client
        
        # Initialize agents
        self.intent_analyzer = IntentAnalyzer()
        self.context_retriever = ContextRetriever(project_root)
        self.planner = Planner(llm_client)
        self.code_editor = CodeEditor(llm_client)
        self.validator = Validator()
        self.test_runner = TestRunner()
    
    def handle_request(self, user_request: str) -> EditResult:
        """
        Main entry point: user request → applied edits
        """
        try:
            # Stage 1: Analyze
            intent = self.intent_analyzer.analyze(user_request)
            logger.info(f"Intent: {intent.intent_type}, confidence: {intent.confidence}")
            
            # Stage 2: Retrieve context
            retrieval = self.context_retriever.retrieve(intent)
            logger.info(f"Found {len(retrieval.files)} relevant files")
            
            # Stage 3: Plan
            plan = self.planner.plan(intent, retrieval)
            logger.info(f"Plan: {len(plan.steps)} steps")
            
            # Stage 4-8: Execute with retry
            result = self._apply_plan_with_retry(
                plan, retrieval, max_retries=3
            )
            
            return result
        
        except Exception as e:
            logger.error(f"Failed: {e}", exc_info=True)
            return EditResult(success=False, error=str(e))
    
    def _apply_plan_with_retry(self, plan, retrieval, max_retries):
        """
        Apply plan steps with automatic retry on failure.
        """
        patches_applied = []
        errors = []
        
        for step in plan.steps:
            for attempt in range(max_retries):
                try:
                    # Get file content
                    file_path = self.project_root / step.file
                    if not file_path.exists():
                        if step.action == "create":
                            content = ""
                        else:
                            raise FileNotFoundError(f"{step.file} not found")
                    else:
                        content = file_path.read_text()
                    
                    # Get related symbols
                    context = CodeContext(
                        file_content=content,
                        related_files=retrieval.files,
                        symbols=retrieval.symbols
                    )
                    
                    # Generate patch
                    patch = self.code_editor.generate_patch(
                        step, content, context
                    )
                    
                    # Validate patch
                    validation = self.validator.validate(
                        patch, content, step.file
                    )
                    if not validation.is_valid:
                        if attempt < max_retries - 1:
                            # Retry: ask LLM to fix
                            step = self._refine_step(
                                step, validation.errors
                            )
                            continue
                        else:
                            raise ValidationError(validation.errors)
                    
                    # Apply patch
                    new_content = apply_patch(content, patch)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(new_content)
                    
                    # Format & Lint
                    format_file(file_path)
                    lint_result = lint_file(file_path)
                    if lint_result.errors:
                        if attempt < max_retries - 1:
                            # Retry
                            step = self._refine_step(
                                step, lint_result.errors
                            )
                            # Revert and retry
                            file_path.write_text(content)
                            continue
                        else:
                            warnings.append(lint_result.errors)
                    
                    patches_applied.append((step.file, patch))
                    break  # Success, move to next step
                
                except Exception as e:
                    if attempt == max_retries - 1:
                        errors.append(f"Step {step.step_number}: {e}")
                        break
                    else:
                        logger.warning(f"Attempt {attempt+1} failed: {e}")
        
        # Run tests
        if patches_applied:
            modified_files = [f for f, _ in patches_applied]
            test_result = self.test_runner.run_tests(
                self.project_root, modified_files
            )
            
            if not test_result.passed and not errors:
                # Tests failed: show LLM the failures
                logger.error(f"Tests failed: {test_result.failed_tests}")
                errors.append(f"Tests failed: {test_result.failed_tests}")
        
        return EditResult(
            success=len(errors) == 0,
            patches_applied=len(patches_applied),
            errors=errors,
            modified_files=[f for f, _ in patches_applied]
        )
    
    def _refine_step(self, step: PlanStep, errors: List[str]) -> PlanStep:
        """
        Ask LLM to refine a failed step given error feedback.
        """
        prompt = f"""
        Step failed with errors:
        {errors}
        
        Original step:
        {step}
        
        Suggest a refined approach (JSON):
        {{"refined_step": {{...}}}}
        """
        
        response = self.llm.complete(prompt, max_tokens=1000)
        refined = parse_json(response)
        return refined.get("refined_step", step)


# Data classes
@dataclass
class IntentAnalysis:
    intent_type: str  # "fix", "feature", "refactor", etc.
    confidence: float
    keywords: List[str]
    likely_symbols: List[str]
    summary: str
    requires_new_file: bool
    complexity_score: int  # 1-5

@dataclass
class RetrievalResult:
    files: List[BundledFile]
    symbols: Dict[str, SymbolInfo]

@dataclass
class PlanResult:
    steps: List[PlanStep]
    estimated_impact: Dict

@dataclass
class Patch:
    file: str
    operations: List[PatchOperation]

@dataclass
class PatchOperation:
    type: str  # "replace", "add_import", "insert", "delete"
    search: Optional[str] = None
    replacement: Optional[str] = None
    line: Optional[int] = None

@dataclass
class EditResult:
    success: bool
    patches_applied: int
    errors: List[str]
    modified_files: List[str]
```

### File Retrieval Implementation

```python
class ContextRetriever:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.symbol_index = None
        self._build_indexes()
    
    def _build_indexes(self):
        """
        Build caches once at startup.
        """
        self.symbol_index = self._index_symbols()
        self.embedding_index = self._index_embeddings()
        self.file_tree = self._build_file_tree()
    
    def _index_symbols(self) -> Dict[str, SymbolLocation]:
        """
        Scan project, extract symbols from each file.
        """
        symbols = {}
        
        for py_file in self.project_root.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        symbols[node.name] = SymbolLocation(
                            file=py_file,
                            line=node.lineno,
                            type=node.__class__.__name__
                        )
            except:
                pass
        
        return symbols
    
    def _index_embeddings(self) -> VectorIndex:
        """
        Create embeddings for each file's content.
        Used as fallback retrieval if keyword search insufficient.
        """
        from sentence_transformers import SentenceTransformer
        
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = {}
        
        for file_path in self.project_root.rglob("*.py"):
            content = file_path.read_text()[:1000]  # First 1K chars
            embedding = model.encode(content)
            embeddings[str(file_path)] = embedding
        
        return VectorIndex(embeddings, model)
    
    def retrieve(self, intent: IntentAnalysis) -> RetrievalResult:
        """
        Multi-algorithm retrieval strategy.
        """
        candidates = {}
        
        # 1. Filename search
        for keyword in intent.keywords:
            matches = self._filename_search(keyword)
            for file, score in matches:
                candidates[str(file)] = candidates.get(str(file), 0) + score * 1.0
        
        # 2. Symbol search
        for symbol in intent.likely_symbols:
            if symbol in self.symbol_index:
                loc = self.symbol_index[symbol]
                candidates[str(loc.file)] = candidates.get(str(loc.file), 0) + 50
        
        # 3. Ripgrep search
        for keyword in intent.keywords:
            matches = self._ripgrep_search(keyword)
            for file, score in matches:
                candidates[str(file)] = candidates.get(str(file), 0) + 30
        
        # 4. Embedding search (if needed)
        if len(candidates) < 3 or intent.confidence < 0.8:
            matches = self.embedding_index.search(
                intent.summary, k=3
            )
            for file, score in matches:
                candidates[file] = candidates.get(file, 0) + score * 20
        
        # Rank and limit
        ranked = sorted(
            candidates.items(),
            key=lambda x: x[1],
            reverse=True
        )[:8]
        
        file_paths = [Path(f) for f, _ in ranked]
        bundled = self._bundle_files(file_paths)
        symbols = self._extract_symbols(bundled)
        
        return RetrievalResult(files=bundled, symbols=symbols)
    
    def _filename_search(self, keyword: str) -> List[Tuple[Path, int]]:
        """
        Match keyword against all file names.
        """
        results = []
        keyword_lower = keyword.lower()
        
        for file_path in self.project_root.rglob("*"):
            if file_path.is_dir():
                continue
            
            name = file_path.name.lower()
            score = 0
            
            if name == keyword_lower:
                score = 100
            elif keyword_lower in name:
                score = 50
            elif self._fuzzy_match(keyword_lower, name) > 0.8:
                score = 30
            
            if score > 0:
                results.append((file_path, score))
        
        return sorted(results, key=lambda x: x[1], reverse=True)
    
    def _ripgrep_search(self, keyword: str) -> List[Tuple[Path, int]]:
        """
        Use rg for fast pattern matching.
        """
        results = []
        try:
            output = subprocess.run(
                ["rg", "--files-with-matches", keyword, str(self.project_root)],
                capture_output=True,
                timeout=5
            ).stdout.decode()
            
            for line in output.split('\n'):
                if line:
                    results.append((Path(line), 30))
        except:
            pass
        
        return results
    
    def _bundle_files(self, file_paths: List[Path]) -> List[BundledFile]:
        """
        Read files, extract metadata, truncate if needed.
        """
        bundled = []
        
        for file_path in file_paths:
            content = file_path.read_text()
            
            # Truncate if too large
            if len(content) > 5000:
                # Keep: imports, class/function defs, first N lines
                content = self._extract_essential(content)
            
            symbols = self._extract_file_symbols(file_path)
            
            bundled.append(BundledFile(
                file_path=str(file_path.relative_to(self.project_root)),
                content=content,
                symbols=symbols,
                size_bytes=len(content),
                language=file_path.suffix[1:]  # "py", "js", etc.
            ))
        
        return bundled
    
    def _extract_essential(self, content: str) -> str:
        """
        For large files, extract: imports + function/class defs + docstrings.
        """
        try:
            tree = ast.parse(content)
            essential = []
            
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    essential.append(ast.unparse(node))
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    # Include def line + docstring
                    essential.append(ast.unparse(node))
            
            return '\n'.join(essential)
        except:
            # Fallback: return first 3K chars
            return content[:3000]
    
    def _fuzzy_match(self, query: str, target: str) -> float:
        """
        Simple fuzzy match score 0-1.
        """
        from difflib import SequenceMatcher
        return SequenceMatcher(None, query, target).ratio()


# Helper functions
def apply_patch(content: str, patch: Patch) -> str:
    """
    Apply JSON patch operations to content.
    """
    result = content
    
    for op in sorted(patch.operations, key=lambda x: -x.line):
        if op.type == "replace":
            result = result.replace(op.search, op.replacement, 1)
        elif op.type == "add_import":
            # Insert after existing imports
            lines = result.split('\n')
            insert_pos = 0
            for i, line in enumerate(lines):
                if line.startswith(('import ', 'from ')):
                    insert_pos = i + 1
            lines.insert(insert_pos, op.replacement)
            result = '\n'.join(lines)
        elif op.type == "insert":
            lines = result.split('\n')
            lines.insert(op.line, op.replacement)
            result = '\n'.join(lines)
        elif op.type == "delete":
            lines = result.split('\n')
            del lines[op.line]
            result = '\n'.join(lines)
    
    return result

def format_file(file_path: Path):
    """
    Format file using project's formatter.
    """
    if file_path.suffix == ".py":
        subprocess.run(["black", str(file_path)], capture_output=True)
    elif file_path.suffix in [".js", ".ts", ".jsx", ".tsx"]:
        subprocess.run(["prettier", "--write", str(file_path)], capture_output=True)
    elif file_path.suffix == ".go":
        subprocess.run(["gofmt", "-w", str(file_path)], capture_output=True)

def lint_file(file_path: Path) -> LintResult:
    """
    Lint file using project's linter.
    """
    if file_path.suffix == ".py":
        result = subprocess.run(
            ["pylint", str(file_path)],
            capture_output=True
        )
        return LintResult(
            errors=parse_pylint_output(result.stdout),
            passed=result.returncode == 0
        )
    # ... other languages
    return LintResult(errors=[], passed=True)

def is_valid_syntax(content: str, file_path: str) -> bool:
    """
    Check if content parses without syntax errors.
    """
    if file_path.endswith(".py"):
        try:
            ast.parse(content)
            return True
        except SyntaxError:
            return False
    elif file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
        # Use a JavaScript parser
        try:
            import esprima  # or similar
            esprima.parse(content)
            return True
        except:
            return False
    return True
```

---

## Part 6: Implementation Roadmap

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] Request analysis (intent classification)
- [ ] File retrieval (all 4 algorithms)
- [ ] Symbol indexing
- [ ] Data structures (Intent, Plan, Patch, etc.)

### Phase 2: Agent System (Week 2-3)
- [ ] Planner agent
- [ ] Code Editor agent
- [ ] Validator agent
- [ ] Orchestrator

### Phase 3: Validation & Testing (Week 3-4)
- [ ] Patch validation
- [ ] Syntax checking
- [ ] Test runner integration
- [ ] Retry logic

### Phase 4: Local LLM Optimization (Week 4-5)
- [ ] Context compression
- [ ] Few-shot examples
- [ ] Staged prompting
- [ ] Temperature tuning

### Phase 5: Integration & Polish (Week 5-6)
- [ ] GUI integration
- [ ] Error reporting
- [ ] Performance monitoring
- [ ] Documentation

---

## Part 7: Metrics & Monitoring

Track these to measure reliability:

```python
@dataclass
class EditMetrics:
    request_id: str
    intent_confidence: float
    files_retrieved: int
    plan_steps: int
    patches_generated: int
    patches_valid: int  # passed validation
    patches_applied: int
    apply_attempts: int  # retries needed
    tests_run: int
    tests_passed: bool
    total_time_seconds: float
    success: bool
    
    @property
    def validation_rate(self) -> float:
        """% of patches that pass validation."""
        return self.patches_valid / max(self.patches_generated, 1)
    
    @property
    def apply_success_rate(self) -> float:
        """% of patches applied successfully."""
        return self.patches_applied / max(self.patches_valid, 1)
    
    @property
    def test_pass_rate(self) -> float:
        """% of test runs that pass."""
        if self.tests_run == 0:
            return 1.0
        return 1.0 if self.tests_passed else 0.0
```

**Target Metrics**:
- Validation rate: > 95%
- Apply success rate: > 99%
- Test pass rate: > 90%
- Average retries per request: < 1.5
- Mean time to apply: < 30 seconds

---

## Conclusion

This architecture transforms your AI editor from a single-stage approach into a robust, multi-stage pipeline with:

1. **Focused context**: Retrieve only relevant files
2. **Staged reasoning**: LLM doesn't try to do everything at once
3. **Incremental edits**: Patches instead of full rewrites
4. **Validation gates**: Check before apply
5. **Automatic recovery**: Retry with feedback
6. **Local LLM friendly**: Optimized for 7B-13B parameter models
7. **Production ready**: Error handling, metrics, monitoring

Implement this and you'll have a system as reliable as modern cloud-based editors, but running 100% locally.

---

**Next Steps**:
1. Review architecture with your team
2. Start Phase 1 implementation
3. Benchmark against current approach
4. Iterate based on real-world usage

For questions or clarifications, refer to specific sections in this document.
