# Prompt Engineering Guide - Optimized LLM Prompts

## Overview

All LLM prompts have been comprehensively optimized to:
- ✅ Be clear and structured
- ✅ Include proper context
- ✅ Provide explicit examples
- ✅ Set clear constraints
- ✅ Request proper output format
- ✅ Guide LLM thinking process

---

## LLM Integration Points

### 1. **Plan Generation** (`planner.py`)

**Purpose**: Create step-by-step implementation plan

**Input**: User request + intent analysis + code context

**Output**: Structured JSON plan with steps, dependencies, impact assessment

**Key Improvements**:
- ✅ Clear task description with guidelines
- ✅ Explicit action types (understand, modify, create, delete, test)
- ✅ Examples showing dependencies between steps
- ✅ Impact assessment fields (files_to_modify, breaking_changes, risk_level)
- ✅ Assumptions and open questions
- ✅ Proper JSON structure with all fields

**Temperature**: 0.1 (deterministic, focused)

**Max Tokens**: 2000

#### Example Plan Generated
```json
{
  "plan_id": "plan-add-email-validation",
  "summary": "Add email validation to user registration",
  "steps": [
    {
      "step_number": 1,
      "action": "understand",
      "file": "src/models/user.py",
      "details": "Review current user model implementation",
      "reason": "Establish baseline understanding",
      "dependencies": []
    },
    {
      "step_number": 2,
      "action": "modify",
      "file": "src/models/user.py",
      "target_function": "validate_email",
      "details": "Add email format validation",
      "reason": "Implement validation logic",
      "dependencies": [1]
    },
    {
      "step_number": 3,
      "action": "test",
      "file": "tests/test_email_validation.py",
      "details": "Add comprehensive email validation tests",
      "reason": "Ensure reliability",
      "dependencies": [2]
    }
  ],
  "estimated_impact": {
    "files_to_modify": 1,
    "files_to_create": 1,
    "breaking_changes": 0,
    "risk_level": "low"
  }
}
```

---

### 2. **Code Generation** (`editor.py`)

**Purpose**: Generate actual code patches/operations

**Input**: Plan step + file content + related functions

**Output**: JSON with operations (replace, insert, delete, add_import, remove_import)

**Key Improvements**:
- ✅ Shows exact code context that will be modified
- ✅ Provides examples for each operation type
- ✅ Explains when to use each operation type
- ✅ Includes retry logic with error messages
- ✅ Strict constraints to prevent breaking changes
- ✅ Clear requirement for exact text matching

**Temperature**: 0.1 (deterministic, precise)

**Max Tokens**: 3000 (first attempt) / 2000 (retry)

#### Example Operations Generated
```json
{
  "operations": [
    {
      "type": "replace",
      "search": "def validate_email(self, email):\n        return True",
      "replacement": "def validate_email(self, email):\n        return '@' in email and '.' in email.split('@')[1]"
    },
    {
      "type": "add_import",
      "import_statement": "from email_validator import validate_email as validate_email_format",
      "after_line": 3
    },
    {
      "type": "insert",
      "line_start": 45,
      "text": "\n    def is_valid_email_domain(self, email):\n        domain = email.split('@')[1]\n        return len(domain) > 3"
    }
  ]
}
```

---

### 3. **Requirements Analysis** (`props_analyzer.py`)

**Purpose**: Extract detailed requirements from user request

**Input**: User request (natural language)

**Output**: Structured requirements with types, priority, effort, complexity

**Key Improvements**:
- ✅ Clear requirement types (functional, performance, security, etc.)
- ✅ Complexity factors explained
- ✅ Assumptions and clarifications required
- ✅ Confidence scoring
- ✅ Comprehensive scope description
- ✅ Breaking changes detection

**Temperature**: 0.3 (balanced - some creativity for analysis)

**Max Tokens**: 1500

#### Example Analysis Generated
```json
{
  "requirements": [
    {
      "type": "functional",
      "description": "Add email validation to user registration",
      "priority": "high",
      "effort": "small",
      "keywords": ["validation", "email", "registration"]
    },
    {
      "type": "security",
      "description": "Prevent invalid emails from being stored",
      "priority": "high",
      "effort": "small",
      "keywords": ["security", "validation", "data integrity"]
    },
    {
      "type": "test",
      "description": "Add unit tests for validation logic",
      "priority": "high",
      "effort": "small",
      "keywords": ["tests", "coverage"]
    }
  ],
  "affected_components": ["user_model", "registration_service"],
  "complexity": 2,
  "breaking_changes": false,
  "assumptions": [
    "User model exists and is modifiable",
    "Email validator library is available"
  ],
  "confidence": 0.92
}
```

---

### 4. **Feedback Parsing** (`refinement_handler.py` - Part 1)

**Purpose**: Parse natural language feedback into structured requirements

**Input**: User feedback (natural language, e.g., "Also add rate limiting")

**Output**: Structured feedback with additions, removals, modifications, concerns

**Key Improvements**:
- ✅ Explicit parsing task description
- ✅ Clear categories (add, remove, modify, concerns, questions)
- ✅ Confidence scoring for parsing accuracy
- ✅ Handles ambiguous feedback
- ✅ Identifies concerns and risks

**Temperature**: 0.3 (balanced)

**Max Tokens**: 500

#### Example Parsed Feedback
```json
{
  "requirements_to_add": [
    "Add rate limiting for API endpoints",
    "Use async/await for I/O operations"
  ],
  "requirements_to_remove": [
    "Don't modify the authentication flow"
  ],
  "requirements_to_modify": [
    "Make validation more strict"
  ],
  "documented_concerns": [
    "Performance might be impacted",
    "Backward compatibility needs checking"
  ],
  "clarification_questions": [
    "Should caching be enabled?"
  ],
  "parsing_confidence": 0.88
}
```

---

### 5. **Plan Refinement** (`refinement_handler.py` - Part 2)

**Purpose**: Refine existing plan based on user feedback

**Input**: Original plan + parsed user feedback + original request

**Output**: Refined plan incorporating all feedback

**Key Improvements**:
- ✅ Shows what refinements were made
- ✅ Explains why changes were made
- ✅ Tracks which user requests were addressed
- ✅ Maintains step dependencies
- ✅ Updates risk assessment
- ✅ Identifies open questions

**Temperature**: 0.3 (balanced)

**Max Tokens**: 2000

#### Example Refined Plan
```json
{
  "plan_id": "plan-refined-add-email-validation",
  "summary": "Add email validation with async support and rate limiting",
  "refinements_made": [
    "Added async/await support for validation",
    "Added rate limiting middleware",
    "Kept authentication flow unchanged"
  ],
  "steps": [
    {
      "step_number": 1,
      "action": "understand",
      "file": "src/api/handlers.py",
      "details": "Understand current API implementation",
      "reason": "Establish baseline"
    },
    {
      "step_number": 2,
      "action": "create",
      "file": "src/middleware/rate_limiter.py",
      "details": "Create rate limiting middleware",
      "reason": "User requested rate limiting"
    },
    {
      "step_number": 3,
      "action": "modify",
      "file": "src/models/user.py",
      "details": "Add async email validation",
      "reason": "User requested async support"
    }
  ],
  "user_requests_addressed": [
    "Async/await for performance",
    "Rate limiting added",
    "Authentication flow unchanged"
  ],
  "estimated_impact": {
    "files_to_modify": 2,
    "files_to_create": 1,
    "breaking_changes": 0,
    "risk_level": "low"
  }
}
```

---

### 6. **Session Summarization** (`conversational_orchestrator.py`)

**Purpose**: Analyze and summarize entire code editing session

**Input**: Full conversation history + session state

**Output**: Markdown formatted summary of session

**Key Improvements**:
- ✅ Analyzes entire conversation context
- ✅ Extracts original goal and refinements
- ✅ Identifies key decisions and concerns
- ✅ Uses markdown formatting
- ✅ Provides actionable insights
- ✅ Comprehensive coverage of all aspects

**Temperature**: 0.3 (balanced)

**Max Tokens**: 500

#### Example Session Summary
```markdown
## Executive Summary
Successfully added email validation with async support and rate limiting to user registration.

## Original Request
Add email validation to the User model

## Refinements Made
- Added async/await for I/O operations
- Added rate limiting middleware
- Decided not to modify authentication flow

## Key Decisions
- Use built-in Python email validator
- Implement rate limiting as middleware
- Keep authentication separate

## Final Status
Complete - All changes applied successfully

## Accomplishments
- Email validation implemented (1 file modified)
- Rate limiting middleware added (1 file created)
- Tests added (1 file created)
- All tests passing

## Outstanding Items
- None

## Concerns/Limitations
- None identified

## Next Steps
- Deploy to staging
- Monitor rate limiting effectiveness
```

---

## Prompt Optimization Principles

### 1. **Clarity**
- Clear task description upfront
- Explicit constraints and guidelines
- No ambiguous instructions

### 2. **Structure**
- Use markdown headers for organization
- Use code blocks for examples
- Use JSON for structured data

### 3. **Context**
- Include relevant background information
- Show related files and functions
- Explain why changes are needed

### 4. **Examples**
- Provide concrete examples of expected output
- Show correct vs incorrect formats
- Demonstrate edge cases

### 5. **Constraints**
- List what to avoid (❌)
- List what to do (✅)
- Specify output format strictly

### 6. **Formatting**
- Use consistent, professional formatting
- Use markdown for readability
- Use JSON for structured output
- Start response with indicator (e.g., `{` for JSON)

---

## Common LLM Issues & Fixes

### Issue 1: LLM Adds Explanations Instead of JSON
**Problem**: LLM returns "Here's the JSON: { ... }" instead of just JSON

**Solution in Prompts**: 
- "Return ONLY valid JSON (no markdown, no explanation)"
- "Start response with opening brace immediately"
- "Critical: Start with `{` directly"

### Issue 2: LLM Returns Incomplete Steps
**Problem**: Plan missing some required fields

**Solution**: 
- Show complete example with all fields
- Explicitly list all required fields
- Use validation criteria

### Issue 3: LLM Makes Wrong Code Changes
**Problem**: Patches don't match actual code

**Solution**:
- Show exact code context
- Use simple, specific search strings
- Include examples for each operation type
- Reduce max_tokens on retry

### Issue 4: LLM Misunderstands Requirements
**Problem**: Generated plan doesn't match user intent

**Solution**:
- Provide detailed requirement analysis first
- Use confidence scoring
- Ask clarification questions
- Show assumptions explicitly

### Issue 5: LLM Modifies Unrelated Code
**Problem**: Changes code it shouldn't touch

**Solution**:
- Strict constraints: "Don't touch other functions"
- Function signature preservation requirement
- Operation type examples showing what NOT to do
- Dependency tracking

---

## Testing Prompts

To test if prompts work well:

```python
# Test with various request types
requests = [
    "Add email validation",  # Simple
    "Add async email validation, rate limiting, and caching",  # Complex
    "Fix bug in authentication",  # Bug fix
    "Refactor config system",  # Refactor
    "Add tests for validation",  # Test
]

for req in requests:
    response = llm.complete(prompt.format(request=req))
    
    # Check:
    # 1. Is it valid JSON?
    # 2. Does it have all required fields?
    # 3. Is the output reasonable?
    # 4. Does it match the request?
```

---

## Performance Notes

| Component | Tokens | Temp | Notes |
|-----------|--------|------|-------|
| Planning | 2000 | 0.1 | Deterministic planning |
| Code Gen | 3000/2000 | 0.1 | Precise code generation |
| Props Analysis | 1500 | 0.3 | Balanced analysis |
| Feedback Parse | 500 | 0.3 | Quick parsing |
| Plan Refinement | 2000 | 0.3 | Balanced refinement |
| Summarization | 500 | 0.3 | Comprehensive summary |

**Total per session**: ~8000-9000 tokens (excluding retries)

---

## Best Practices

1. **Always show examples** - Examples are worth 1000 words
2. **Be explicit about constraints** - State what NOT to do
3. **Use structured output** - JSON, markdown, clear formatting
4. **Include context** - Full code, related functions, decision rationale
5. **Provide fallbacks** - What to do if something is unclear
6. **Test extensively** - Try various request types and sizes
7. **Monitor quality** - Track success rates, user feedback
8. **Iterate based on failures** - When LLM makes mistakes, refine the prompt
9. **Use temperature appropriately** - 0.1 for precision, 0.3 for analysis
10. **Document decisions** - Explain why certain constraints are in place

---

## Future Improvements

- [ ] Add few-shot examples to prompts
- [ ] Implement prompt versioning
- [ ] Add prompt A/B testing
- [ ] Create prompt templates for common tasks
- [ ] Add prompt validation tests
- [ ] Implement feedback loop for prompt refinement
- [ ] Add multi-language support
- [ ] Create specialized prompts by codebase type

---

**Status**: ✅ All Prompts Optimized  
**Date**: 2026-08-06  
**Last Updated**: After comprehensive audit of all LLM integration points
