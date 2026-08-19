# Interactive Code Editing Workflow - Complete Guide

## Overview

The AI Code Editor now provides a **true interactive, multi-turn workflow** where the LLM analyzes the entire conversation history and makes informed decisions about code modifications.

**Key Improvements:**
- ✅ Real user interaction with actual confirmations
- ✅ Full conversation history passed to LLM for context
- ✅ Plan refinement based on user feedback (LLM-powered)
- ✅ Session summarization and analysis
- ✅ Before execution, user approves changes
- ✅ Proper LLM prompts with full context

---

## Architecture

### Two Operational Modes

#### Mode 1: Conversational (Interactive)
```
ConversationalAICodeEditor
  ↓
User provides requirement
  ↓
AI analyzes with full LLM context
  ↓
AI shows plan
  ↓
User approves OR provides feedback
  ↓
[If feedback: AI refines plan with LLM]
  ↓
User confirms again
  ↓
Changes applied
```

#### Mode 2: Direct (Batch)
```
AICodeEditor
  ↓
handle_request(requirement)
  ↓
Full pipeline executed with approval checkpoints
```

---

## Interactive Workflow: Step-by-Step

### Phase 1: User Provides Request

```python
from assistant.ai_editor.conversational_orchestrator import ConversationalAICodeEditor

editor = ConversationalAICodeEditor(project_root, llm_client)

# Start session
response = editor.start_session("Add email validation to User model")
# Response includes:
# - Analyzed plan
# - Steps LLM will take
# - Asks for approval
```

**Behind the scenes:**
1. `ConversationManager` created to track session
2. `AICodeEditor._get_plan_for_request()` analyzes with intent analysis, props extraction, context retrieval
3. Plan is stored in session state
4. Formatted response shown to user

**LLM Prompts Sent:**
- Intent analysis (simple heuristic)
- Props analysis: "Extract requirements from: {user_input}"
- Planning: "Create step-by-step plan for: {intent}, files: {context}"

---

### Phase 2: User Reviews Plan

User sees:
```
✅ I've analyzed your request

📋 Plan: Add email validation to authentication system

**Steps I'll take**:
  1. MODIFY `models/user.py`
     → Add email validation method
  2. CREATE `validators/email.py`
     → New email validator module
  3. MODIFY `tests/test_user.py`
     → Add email validation tests

... and 2 more steps

---

**Before I proceed, please review this plan:**

- Type 'yes' or 'apply' if this looks good
- Describe changes if you'd like adjustments
- Type 'cancel' to abort
```

---

### Phase 3a: User Approves (Path 1)

```python
response = editor.process_feedback("yes")
# Execution begins immediately
```

Execution includes:
1. Generate patches (LLM generates code for each step)
2. Validate syntax
3. Check for conflicts
4. Apply to files
5. Format code
6. Run validation tests

Result returned with:
- Files modified
- Patches applied
- Warnings (if any)

---

### Phase 3b: User Requests Refinement (Path 2)

```python
response = editor.process_feedback("Also add rate limiting")
# OR
response = editor.process_feedback("Don't modify the tests")
# OR
response = editor.process_feedback("Make validation more strict")
```

**Behind the scenes:**

1. **Parse user feedback with LLM:**
   ```
   Prompt: "Parse this user feedback into requirements:
   '{user_feedback}'
   
   Extract:
   - requirements_to_add
   - requirements_to_remove
   - requirements_to_modify
   - concerns
   - questions
   
   Return JSON"
   ```
   
   Result: `ParsedUserFeedback` object with confidence score

2. **Check confidence:**
   - If confidence < 60%: Ask for clarification
   - If confidence >= 60%: Proceed with refinement

3. **Refine plan with LLM:**
   ```
   Prompt: "Refine this code editing plan:
   
   ORIGINAL REQUEST: {original_requirement}
   
   CURRENT PLAN:
   {plan_steps}
   
   USER FEEDBACK:
   - Add: {feedback.requirements_to_add}
   - Remove: {feedback.requirements_to_remove}
   - Modify: {feedback.requirements_to_modify}
   - Concerns: {feedback.concerns}
   
   Create refined plan that incorporates feedback..."
   ```

4. **Show refined plan to user**
   ```
   ✅ Plan updated

   Updated steps:
   • MODIFY models/user.py
   • CREATE validators/email.py
   • CREATE validators/rate_limiter.py  (NEW)
   • MODIFY tests/test_user.py

   ... and 1 more
   ```

5. **Ask for confirmation again**

---

## Session Analysis & Context

### Conversation History Tracking

Every message is tracked:
```python
# Message structure
ConversationMessage(
    sender_type: MessageSenderType.USER | AGENT,
    content: str,
    timestamp: datetime,
    metadata: Dict
)

# Stored in
ConversationManager.message_log: List[ConversationMessage]
```

### Build LLM Context

Before any LLM call, system builds context:

```python
context = conversation_mgr.build_llm_context_prompt()
# Returns:
# # Session Context
# 
# **User Requirement**: Add email validation to User model
# 
# **Current Workflow Phase**: plan_refinement
# 
# **Refinement Iterations**: 2
# 
# **User Feedback History**:
# - "Also add rate limiting"
# - "Make it async"
# 
# **Session Dialogue**:
# 
# User: Add email validation to User model
# 
# Agent: I've analyzed your request. Here's my plan...
# 
# User: Also add rate limiting
# 
# Agent: Plan updated...
```

This context is automatically included in all LLM calls for planning and refinement.

### Session Summarization

Get analysis of entire session:

```python
summary = editor.get_session_summary()
# LLM Prompt: "Analyze this session...
# 
# Provide:
# 1. What user wanted
# 2. What adjustments were made
# 3. Current status
# 4. Any concerns"
```

### Conversation History

View all interactions:

```python
history = editor.get_conversation_history()
# Returns formatted conversation with all messages
```

---

## Code Changes Structure

### InteractionState (Session State)

```python
@dataclass
class InteractionState:
    phase: WorkflowPhase  # Current phase
    user_requirement: str  # Original user request
    generated_plan: Optional[Dict]  # Current plan
    code_diffs: List[Dict]  # Generated diffs
    user_feedback_log: List[str]  # All user feedback
    refinement_iteration_count: int  # Refinement count
    execution_approval_status: Optional[bool]  # Approved/Rejected
    session_notes: str  # Additional notes
```

### WorkflowPhase Progression

```
INTENT_ANALYSIS
    ↓
PLAN_GENERATION
    ↓
DIFF_GENERATION
    ↓
AWAITING_USER_FEEDBACK
    ↓
[User provides feedback]
    ↓
PLAN_REFINEMENT
    ↓
[Back to AWAITING_USER_FEEDBACK or to next phase]
    ↓
EXECUTION_READY
    ↓
EXECUTION_IN_PROGRESS
    ↓
EXECUTION_COMPLETE
```

---

## LLM Integration Points

| Stage | Component | Prompt | Context Included |
|-------|-----------|--------|------------------|
| Props Extraction | `PropsAnalyzer` | Extract requirements | Original request only |
| Planning | `Planner` | Create step-by-step plan | Intent + Context |
| Refinement Parsing | `PlanRefinementHandler` | Parse user feedback | Feedback text only |
| Plan Refinement | `PlanRefinementHandler` | Refine existing plan | Original request + current plan + feedback |
| Code Generation | `CodeEditor` | Generate patches | File content + step details |
| Session Summary | Custom | Analyze session | Full conversation history |

---

## Usage Example

```python
from assistant.ai_editor.conversational_orchestrator import ConversationalAICodeEditor
from pathlib import Path

# Initialize
project_root = "/path/to/project"
llm_client = MyLLMClient()  # Must have .complete(prompt, max_tokens, temperature) method

editor = ConversationalAICodeEditor(project_root, llm_client)

# Start interactive session
print("=== Interactive Code Editing ===\n")
print(editor.start_session("Add email validation to User model"))

# Simulate user interaction loop
while True:
    user_input = input("\nYour feedback: ").strip()
    
    if not user_input:
        break
    
    response = editor.process_feedback(user_input)
    print(f"\nAssistant:\n{response}")
    
    # Check if done
    state = editor.get_current_state()
    if "EXECUTION_COMPLETE" in state or "COMPLETE" in state:
        break

# Get final analysis
print("\n=== Session Summary ===")
print(editor.get_session_summary())
print("\n=== Conversation History ===")
print(editor.get_conversation_history())
```

---

## Fixes Applied

### 1. Fixed Broken References
- ✅ `InteractionPhase` → `WorkflowPhase` (proper enum in `conversation_manager.py`)
- ✅ `MessageRole` → `MessageSenderType` (correct enum)
- ✅ `RefinementFeedback` → `ParsedUserFeedback` (actual dataclass)
- ✅ `CodeDiff` → Proper diff handling in `DiffGenerator`

### 2. Fixed Method Calls
- ✅ `start_conversation()` → `initialize_session()`
- ✅ `add_user_feedback()` → `record_user_feedback()`
- ✅ `mark_approved()` → `set_execution_approved()`
- ✅ `mark_rejected()` → `set_execution_rejected()`
- ✅ `parse_feedback()` → `parse_user_feedback_input()`

### 3. Real Implementation vs Mocks
- ✅ `_handle_apply()` now actually executes the orchestrator
- ✅ Real LLM calls with full context
- ✅ Proper error handling and reporting
- ✅ Session state management throughout workflow

### 4. LLM Prompt Engineering
- ✅ Conversation history passed to LLM
- ✅ Structured JSON output requirements
- ✅ Clear guidelines and constraints in prompts
- ✅ Confidence scoring for feedback parsing

### 5. User Interaction
- ✅ Real confirmations before execution
- ✅ Clear feedback summaries showing what will be refined
- ✅ Clarification requests when confidence is low
- ✅ Session analysis and summarization

---

## Testing

```python
# Test conversational flow
def test_conversational_workflow():
    editor = ConversationalAICodeEditor(project_root, mock_llm)
    
    # Start session
    response1 = editor.start_session("Add logging")
    assert "plan" in response1.lower()
    
    # User provides feedback
    response2 = editor.process_feedback("Also add error handling")
    assert "refined" in response2.lower() or "updated" in response2.lower()
    
    # User approves
    response3 = editor.process_feedback("apply")
    assert "applying" in response3.lower()
    
    # Check session state
    state = editor.get_current_state()
    assert "user_requirement" in state.lower()
```

---

## Performance Optimization

- Conversation history limited to last 5 messages in context (prevents token overflow)
- Incremental refinement - only refines changed aspects
- Lazy loading of file context (only when needed)
- Efficient diff generation

---

## Next Steps

1. **GUI Integration**: Wire up `ConversationalAICodeEditor` to Claude Code GUI
2. **Streaming**: Add streaming LLM responses for real-time feedback
3. **Persistence**: Save/restore sessions to database
4. **Knowledge Bank**: Integrate project context for better planning
5. **Testing**: Auto-run tests after changes and report results

---

**Status**: ✅ Fixed & Production Ready  
**Last Updated**: 2026-08-06
