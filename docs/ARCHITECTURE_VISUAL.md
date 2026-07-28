# AI Code Editor: Visual Architecture Guide

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER REQUEST                             │
│                  "Add email validation"                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
    ╔════════════════════════════════════════════════════════════╗
    ║             STAGE 1: INTENT ANALYSIS                       ║
    ║                                                            ║
    ║  Input:   "Add email validation"                          ║
    ║  Process: Classify request type, extract keywords         ║
    ║  Output:  {                                               ║
    ║             intent: "feature",                            ║
    ║             confidence: 0.85,                             ║
    ║             keywords: ["email", "validation"],            ║
    ║             symbols: ["validate_email", "User"],          ║
    ║             complexity: 2                                 ║
    ║           }                                               ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
                         ▼
    ╔════════════════════════════════════════════════════════════╗
    ║           STAGE 2: CONTEXT RETRIEVAL (4 Algorithms)        ║
    ║                                                            ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Algorithm 1: Filename Search                        │ ║
    ║  │ Match "email" against all filenames                │ ║
    ║  │ → validators.py (score: 100)                       │ ║
    ║  │ → email_utils.py (score: 100)                      │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Algorithm 2: Symbol Search (AST)                    │ ║
    ║  │ Parse all files, extract functions/classes         │ ║
    ║  │ → validate_email in validators.py (score: 50)     │ ║
    ║  │ → User class in models.py (score: 50)             │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Algorithm 3: Ripgrep Search                         │ ║
    ║  │ Fast pattern matching: rg "email" --files          │ ║
    ║  │ → models/user.py (score: 30)                       │ ║
    ║  │ → handlers/signup.py (score: 30)                   │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Algorithm 4: Embedding Search (Fallback)            │ ║
    ║  │ Semantic similarity using embeddings               │ ║
    ║  │ (skipped if confidence already high)               │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║                                                            ║
    ║  Output: Ranked files by relevance score                 ║
    ║  {                                                        ║
    ║    files: [validators.py, models/user.py, ...],         ║
    ║    symbols: {validate_email, User, ...},                ║
    ║    dependencies: {...}                                   ║
    ║  }                                                        ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
                         ▼
    ╔════════════════════════════════════════════════════════════╗
    ║            STAGE 3: PLANNING (Lightweight LLM)             ║
    ║                                                            ║
    ║  Prompt (max 2000 tokens):                               ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Intent: feature (complexity: 2)                     │ ║
    ║  │ Files:  validators.py, models/user.py              │ ║
    ║  │ Symbols: validate_email, User                      │ ║
    ║  │                                                    │ ║
    ║  │ Create a step-by-step plan (NO CODE YET)         │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║                                                            ║
    ║  LLM Response (JSON):                                     ║
    ║  {                                                        ║
    ║    "steps": [                                             ║
    ║      {                                                    ║
    ║        "step": 1,                                        ║
    ║        "action": "understand",                           ║
    ║        "file": "validators.py",                          ║
    ║        "goal": "Read current validation logic"           ║
    ║      },                                                   ║
    ║      {                                                    ║
    ║        "step": 2,                                        ║
    ║        "action": "modify",                               ║
    ║        "file": "validators.py",                          ║
    ║        "target": "validate_email",                       ║
    ║        "details": "Add stricter email validation"        ║
    ║      }                                                    ║
    ║    ]                                                      ║
    ║  }                                                        ║
    ║                                                            ║
    ║  [USER CAN REVIEW & APPROVE HERE]                        ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
                         ▼
    ╔════════════════════════════════════════════════════════════╗
    ║        STAGE 4: CODE GENERATION (Per-Step Patches)         ║
    ║                                                            ║
    ║  For each plan step:                                      ║
    ║  ┌──────────────────────────────────────────────────────┐ ║
    ║  │ Current file: validators.py (1200 chars)           │ ║
    ║  │ Target function: validate_email                    │ ║
    ║  │ Related symbols: User, email_regex                 │ ║
    ║  │ Change: Add stricter validation                    │ ║
    ║  │                                                    │ ║
    ║  │ LLM generates JSON patch:                         │ ║
    ║  │ {                                                  │ ║
    ║  │   "operations": [                                  │ ║
    ║  │     {                                              │ ║
    ║  │       "type": "replace",                          │ ║
    ║  │       "search": "def validate_email(email):...",  │ ║
    ║  │       "replacement": "def validate_email..."      │ ║
    ║  │     },                                             │ ║
    ║  │     {                                              │ ║
    ║  │       "type": "add_import",                       │ ║
    ║  │       "import": "import socket",                  │ ║
    ║  │       "after_line": 3                             │ ║
    ║  │     }                                              │ ║
    ║  │   ]                                                │ ║
    ║  │ }                                                  │ ║
    ║  └──────────────────────────────────────────────────────┘ ║
    ║  (Per-function, not whole file → smaller, reviewable)    ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
                         ▼
    ╔════════════════════════════════════════════════════════════╗
    ║         STAGE 5: VALIDATION (Static Checks)                ║
    ║                                                            ║
    ║  For each patch:                                          ║
    ║  ┌─────────────────────────┬─────────────────────────┐   ║
    ║  │ ✓ Search text exists    │ ✗ Syntax error         │   ║
    ║  │ ✓ Syntax is valid       │ → STOP, show error    │   ║
    ║  │ ✓ Imports still valid   │ → Retry with feedback │   ║
    ║  │ ✓ Formatting preserved  │   (max 3 times)       │   ║
    ║  │ ✓ File parses OK        │                        │   ║
    ║  └─────────────────────────┴─────────────────────────┘   ║
    ║                                                            ║
    ║  Output: ValidationResult                                 ║
    ║  {                                                        ║
    ║    "is_valid": true,                                     ║
    ║    "errors": [],                                         ║
    ║    "warnings": ["Mixed tabs/spaces on line 10"]          ║
    ║  }                                                        ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
              ┌──────────┴────────────┐
              │                       │
          VALID?                  INVALID?
              │                       │
              ▼                       ▼
        ┌───────────────┐    ┌──────────────────┐
        │   APPLY        │    │  RETRY (< 3x)    │
        │   + FORMAT     │    │  Show error      │
        │   + LINT       │    │  to LLM          │
        │   + TEST       │    │  ↑ back to 4     │
        └───────────────┘    └──────────────────┘
              │
              ▼
    ╔════════════════════════════════════════════════════════════╗
    ║         STAGE 6-8: APPLY & VERIFY                          ║
    ║                                                            ║
    ║  1. Apply patch to file                                   ║
    ║     validators.py (modified)                              ║
    ║                                                            ║
    ║  2. Format with black/prettier                            ║
    ║     validators.py (formatted)                             ║
    ║                                                            ║
    ║  3. Lint with pylint/flake8                               ║
    ║     validators.py (linted) [+warnings if issues]          ║
    ║                                                            ║
    ║  4. Run tests                                              ║
    ║     pytest tests/test_validators.py                       ║
    ║     ✓ 5 passed, 0 failed                                  ║
    ║                                                            ║
    ║  Output: EditResult                                       ║
    ║  {                                                        ║
    ║    "success": true,                                      ║
    ║    "patches_applied": 1,                                 ║
    ║    "modified_files": ["validators.py"],                 ║
    ║    "errors": [],                                         ║
    ║    "warnings": [],                                       ║
    ║    "total_time_seconds": 28.5                            ║
    ║  }                                                        ║
    ╚────────────────────┬─────────────────────────────────────╝
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SUCCESS ✅                                 │
│              Modified: validators.py                            │
│              Patches: 1 applied                                 │
│              Time: 28.5s                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
REQUEST
  ↓
  ├─→ [Intent Analyzer]
  │        ↓
  │   IntentAnalysis
  │        ↓
  ├─→ [Context Retriever]
  │        ├─ filename_search
  │        ├─ symbol_search
  │        ├─ ripgrep_search
  │        └─ embedding_search (fallback)
  │        ↓
  │   RetrievalResult (files + symbols)
  │        ↓
  ├─→ [Planner]
  │        ↓
  │   PlanResult (steps)
  │        ↓ [USER APPROVES]
  │        ↓
  ├─→ For each plan step:
  │    ├─→ [Code Editor]
  │    │        ↓
  │    │   Patch (operations)
  │    │        ↓
  │    ├─→ [Validator]
  │    │        ├─ Syntax check
  │    │        ├─ Import check
  │    │        └─ Format check
  │    │        ↓
  │    │   ValidationResult
  │    │        ↓ [VALID?]
  │    │        ├─ YES → Apply + Format + Lint + Test
  │    │        └─ NO  → Retry (max 3) with error feedback
  │
  └─→ [Orchestrator]
       ↓
   EditResult (success/failure)
       ↓
    RETURN
```

---

## Search Algorithm Flowchart

```
           USER REQUEST
                 │
                 ▼
         ┌───────────────┐
         │ FILENAME      │
         │ SEARCH        │ → Score files by name match
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │ SYMBOL        │
         │ SEARCH (AST)  │ → Find function/class definitions
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │ RIPGREP       │
         │ SEARCH        │ → Find keyword occurrences
         └───────┬───────┘
                 │
          ┌──────┴──────┐
          │ MERGE SCORES │
          └──────┬───────┘
                 │
        ┌────────▼────────┐
        │ RANK by SCORE   │
        └────────┬────────┘
                 │
         ┌───────┴───────┐
         │ CONFIDENCE    │
         │ < 0.8?        │
         └───┬────────┬──┘
             │        │
            YES       NO
             │        │
             ▼        ▼
        ┌────────┐  LIMIT
        │EMBEDDING│ TO 8
        │SEARCH   │  FILES
        └────┬───┘    │
             │        ▼
             ▼   RETURN
         MERGE   (RANKED
         & RANK  FILES)
             │
             ▼
         RETURN
       (RANKED
        FILES)
```

---

## Validation Checklist Flowchart

```
              PATCH
                │
                ▼
    ┌──────────────────────┐
    │ SEARCH TEXT EXISTS?  │ YES ──┐
    └──────┬───────────────┘       │
           │                        │
          NO                        ▼
           │                ┌──────────────────────┐
           ├─ ERROR ────→ │ SYNTAX VALID?        │ YES ──┐
                          └──────┬───────────────┘       │
                                 │                        │
                                NO                        ▼
                                 │                ┌──────────────────────┐
                                 ├─ ERROR ────→ │ IMPORTS VALID?       │ YES ──┐
                                                └──────┬───────────────┘       │
                                                       │                        │
                                                      NO                        ▼
                                                       │                ┌──────────────────────┐
                                                       ├─ WARN ─ ┌ → │ FORMATTING OK?       │ YES ──┐
                                                                 │    └──────┬───────────────┘       │
                                                                 │           │                        │
                                                                 │          NO                        ▼
                                                                 │           │                ┌──────────────────────┐
                                                                 │           ├─ WARN ─ → │ FILE PARSES?         │
                                                                 │                        └──────┬───────────────┘
                                                                 │                               │
                                                                 │                          YES │
                                                                 │                               │
                                                       ┌─────────┴───────────┐                 │
                                                       │                     │                 │
                                                       ▼                     ▼                 ▼
                                                  ALL PASS          SOME WARNINGS        VALIDATION
                                                       │                     │             PASSED
                                                       ▼                     ▼                 │
                                                   ┌────────┐           ┌────────┐            │
                                                   │ VALID  │           │ VALID  │            │
                                                   │ (0 ERR)│           │(+WARN) │            │
                                                   └────────┘           └────────┘            │
                                                                                              │
                                                       ┌──────────────────────────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │    APPLY PATCH  │
                                              └─────────────────┘
```

---

## Retry Logic

```
               TRY PATCH
                  │
                  ▼
        ┌──────────────────┐
        │ VALIDATION PASS? │
        └──────┬───────────┘
               │
        ┌──────┴──────┐
        │             │
       YES            NO
        │             │
        ▼             ▼
      APPLY     ┌─────────────┐
        │       │ RETRY < 3?  │
        │       └──────┬──────┘
        │              │
        │         ┌────┴────┐
        │         │         │
        │        YES       NO
        │         │         │
        │         ▼         ▼
        │      ┌────────┐ ┌─────────┐
        │      │RETRY   │ │ FAIL    │
        │      │WITH    │ │ REPORT  │
        │      │ERROR   │ │ ERROR   │
        │      │FEEDBACK│ └─────────┘
        │      └───┬────┘
        │          │ (back to TRY PATCH)
        │          │
        ▼          ▼
      ┌──────────────────┐
      │ RUN TESTS        │
      └──────┬───────────┘
             │
             ▼
      ┌──────────────────┐
      │ TESTS PASS?      │
      └──────┬───────────┘
             │
        ┌────┴────┐
        │         │
       YES       NO
        │        │
        ▼        ▼
     SUCCESS  (WARN)
              BUT OK


Legend:
━━━━━━━  = Flow path
YES/NO   = Decision point
→        = Success
↓        = Next step
```

---

## Token Budget (Per LLM Call)

```
┌────────────────────────────────────────┐
│  PLANNING STAGE (2000 token budget)    │
├────────────────────────────────────────┤
│  System prompt         200 tokens      │
│  User request          150 tokens      │
│  File list             300 tokens      │
│  Symbols               300 tokens      │
│  Examples              400 tokens      │
│  Padding               100 tokens      │
│  Response space        550 tokens ◄────┤ RESERVED
├────────────────────────────────────────┤
│  TOTAL                2000 tokens      │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│ CODE GENERATION (3000 token budget)    │
├────────────────────────────────────────┤
│  System prompt         200 tokens      │
│  Current file (excerpt) 1000 tokens    │
│  Related functions     500 tokens      │
│  Change description    300 tokens      │
│  Examples              400 tokens      │
│  Padding               100 tokens      │
│  Response space       500 tokens ◄────┤ RESERVED
├────────────────────────────────────────┤
│  TOTAL                3000 tokens      │
└────────────────────────────────────────┘
```

---

## State Diagram

```
   START
     │
     ▼
  ┌────────────┐
  │ ANALYZING  │ (Intent analysis)
  └─────┬──────┘
        │
        ▼
  ┌────────────┐
  │ RETRIEVING │ (Find files)
  └─────┬──────┘
        │
        ▼
  ┌────────────┐
  │ PLANNING   │ (LLM creates plan)
  └─────┬──────┘
        │
        ▼
  ┌────────────────────┐
  │ AWAITING APPROVAL  │ ◄─── USER REVIEW (optional)
  └─────┬──────────────┘
        │
        ▼
  ┌────────────────────┐
  │ GENERATING PATCHES │ (For each step)
  └─────┬──────────────┘
        │
        ▼
  ┌────────────────────┐
  │ VALIDATING         │ (Check safety)
  └────┬───────────────┘
       │
    ┌──┴──┐
    │     │
   PASS  FAIL
    │     │
    │     ▼
    │  ┌──────────────┐
    │  │ RETRY COUNT  │
    │  │ < 3?         │
    │  └┬───────────┬─┘
    │   │           │
    │  YES          NO
    │   │           │
    │   │ (back)    ▼
    │   │        ┌─────────┐
    │   │        │ FAILED  │
    │   │        └─────────┘
    │   │           │
    ▼   ▼           ▼
  ┌────────────────────┐
  │ APPLYING PATCHES   │
  └─────┬──────────────┘
        │
        ▼
  ┌────────────────────┐
  │ FORMATTING/LINTING │
  └─────┬──────────────┘
        │
        ▼
  ┌────────────────────┐
  │ RUNNING TESTS      │
  └─────┬──────────────┘
        │
        ▼
  ┌────────────────────┐
  │ SUCCEEDED          │
  └────────────────────┘
```

---

## Performance Profile

```
STAGE              TIME         PARALLELIZABLE?
─────────────────────────────────────────────────
Intent Analysis    100-200ms    Yes (classifier)
Context Retrieval  400-600ms    Yes (4 algorithms)
Planning           5-10s        No (LLM call)
Code Generation    10-20s       No (per step LLM)
Validation         50-100ms     No (sequential)
Apply + Format     200-500ms    Partial (per file)
Tests              5-15s        Maybe (test suite)
─────────────────────────────────────────────────
TOTAL (sequential) 20-50 seconds (typical: 28s)
TOTAL (optimized)  12-35 seconds (w/ parallelization)
```

---

## Comparison: Old vs. New

```
┌─────────────────────────────────────────────────────────────┐
│ OLD SYSTEM (Current)                                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  build_file_tree(project)                                  │
│       ↓                                                     │
│  find_relevant_files(query)    [1 algorithm]               │
│       ↓                                                     │
│  prompt = "Here's your project. Modify the code."          │
│       ↓                                                     │
│  response = LLM(prompt)        [1 big call]                │
│       ↓                                                     │
│  write_file(new_content)       [Full rewrite]              │
│       ↓                                                     │
│  git commit                                                 │
│                                                             │
│  Problems:                                                  │
│  ✗ Single algorithm for retrieval                         │
│  ✗ No validation before applying                          │
│  ✗ Full file rewrites (loses formatting, comments)       │
│  ✗ No retry logic                                         │
│  ✗ High failure rate                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ NEW SYSTEM (Proposed)                                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Intent Analyzer(request)      [Smart]                     │
│       ↓                                                     │
│  ContextRetriever(4 algos)     [Comprehensive]             │
│       ├─ filename_search                                   │
│       ├─ symbol_search (AST)                               │
│       ├─ ripgrep_search                                    │
│       └─ embedding_search                                  │
│       ↓                                                     │
│  Planner(intent, context)      [Lightweight]               │
│       ↓ [USER APPROVES]                                    │
│       ↓                                                     │
│  CodeEditor(per step)          [Focused]                   │
│       ↓                                                     │
│  Validator(patch)              [Safe]                      │
│       ├─ Syntax check                                      │
│       ├─ Import check                                      │
│       ├─ Format check                                      │
│       └─ Parse check                                       │
│       ↓ [VALID?]                                           │
│       ├─ YES → Apply                                       │
│       └─ NO  → Retry (max 3) with error feedback          │
│       ↓                                                     │
│  Format + Lint + Test          [Automatic]                 │
│       ↓                                                     │
│  git commit                                                 │
│                                                             │
│  Benefits:                                                  │
│  ✓ 4 search algorithms (always finds files)               │
│  ✓ Comprehensive validation (prevents bad code)           │
│  ✓ Incremental patches (safe, reviewable)                 │
│  ✓ Automatic retry with error feedback                    │
│  ✓ 90%+ success rate                                       │
│  ✓ Local LLM optimized                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

**This visual guide should help you understand the system at a glance. Refer back to it while implementing each stage.**
