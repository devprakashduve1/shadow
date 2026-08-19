"""Handle refinement of plans based on user feedback."""

import logging
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedUserFeedback:
    """Structured representation of parsed user feedback."""
    original_feedback: str
    requirements_to_add: List[str]
    requirements_to_remove: List[str]
    requirements_to_modify: List[str]
    documented_concerns: List[str]
    clarification_questions: List[str]
    parsing_confidence_score: float


class PlanRefinementHandler:
    """Process user feedback and refine execution plans."""

    def __init__(self, llm_client):
        """Initialize plan refinement handler.

        Args:
            llm_client: Language model client
        """
        self.language_model = llm_client

    def parse_user_feedback_input(self, feedback_text: str) -> ParsedUserFeedback:
        """Parse natural language user feedback into structured requirements.

        Args:
            feedback_text: User feedback as text

        Returns:
            Structured ParsedUserFeedback object
        """
        analysis_prompt = f"""# PARSE USER FEEDBACK INTO STRUCTURED REFINEMENTS

## USER FEEDBACK
"{feedback_text}"

## YOUR TASK
Parse the user's feedback to identify:
1. New requirements to add
2. Existing requirements to remove
3. Existing requirements to modify
4. Concerns or risks mentioned
5. Questions or clarifications needed
6. Your confidence in understanding the feedback

## GUIDELINES
- Be comprehensive: capture ALL aspects of feedback
- Be precise: extract specific, actionable items
- Be cautious: flag ambiguous feedback
- Be realistic: assess your confidence level

## RESPONSE FORMAT

Return ONLY valid JSON (no markdown, no explanation):

```json
{{
  "requirements_to_add": [
    "Add rate limiting for API endpoints",
    "Use async/await for I/O operations"
  ],
  "requirements_to_remove": [
    "Don't modify the authentication flow"
  ],
  "requirements_to_modify": [
    "Make validation more strict",
    "Support international characters"
  ],
  "documented_concerns": [
    "Performance might be impacted",
    "Backward compatibility needs checking"
  ],
  "clarification_questions": [
    "Should caching be enabled?",
    "Which version should be targeted?"
  ],
  "parsing_confidence": 0.85
}}
```

**Critical:** Start response with opening brace `{{` immediately."""

        response = self.language_model.complete(
            analysis_prompt,
            max_tokens=500,
            temperature=0.3
        )

        try:
            parsed_data = json.loads(response)
            return ParsedUserFeedback(
                original_feedback=feedback_text,
                requirements_to_add=parsed_data.get("requirements_to_add", []),
                requirements_to_remove=parsed_data.get("requirements_to_remove", []),
                requirements_to_modify=parsed_data.get("requirements_to_modify", []),
                documented_concerns=parsed_data.get("documented_concerns", []),
                clarification_questions=parsed_data.get("clarification_questions", []),
                parsing_confidence_score=parsed_data.get("parsing_confidence", 0.5),
            )
        except Exception as e:
            logger.warning(f"Feedback parsing failed: {e}")
            return ParsedUserFeedback(
                original_feedback=feedback_text,
                requirements_to_add=[],
                requirements_to_remove=[],
                requirements_to_modify=[],
                documented_concerns=[],
                clarification_questions=[],
                parsing_confidence_score=0.0,
            )

    def refine_plan(
        self,
        original_plan: Dict[str, Any],
        feedback: ParsedUserFeedback,
        original_request: str,
    ) -> Dict[str, Any]:
        """Refine plan based on feedback."""
        logger.info(
            f"Refining plan based on {len(feedback.requirements_to_add)} additions, "
            f"{len(feedback.requirements_to_remove)} removals"
        )

        prompt = self._build_refinement_prompt(
            original_plan, feedback, original_request
        )

        response = self.language_model.complete(
            prompt, max_tokens=2000, temperature=0.3
        )

        refined_plan = self._parse_refined_plan(response)
        return refined_plan

    def _build_refinement_prompt(
        self,
        original_plan: Dict[str, Any],
        feedback: ParsedUserFeedback,
        original_request: str,
    ) -> str:
        """Build optimized prompt for plan refinement."""
        return f"""# REFINE EDITING PLAN BASED ON USER FEEDBACK

## ORIGINAL USER REQUEST
{original_request}

## CURRENT PLAN
{self._format_plan_for_prompt(original_plan)}

## USER FEEDBACK RECEIVED
**Raw Feedback:** "{feedback.original_feedback}"

**Parsed Feedback:**
- Add Requirements: {feedback.requirements_to_add or "None"}
- Remove Requirements: {feedback.requirements_to_remove or "None"}
- Modify Requirements: {feedback.requirements_to_modify or "None"}
- Concerns: {feedback.documented_concerns or "None"}
- Questions: {feedback.clarification_questions or "None"}

**Feedback Confidence:** {feedback.parsing_confidence_score:.0%}

## YOUR TASK
Create a refined plan that:
1. ✅ Incorporates ALL user feedback
2. ✅ Keeps existing steps that are still relevant
3. ✅ Removes/updates steps that user doesn't want
4. ✅ Adds new steps for new requirements
5. ✅ Maintains coherence and logical flow
6. ✅ Addresses user concerns

## REFINEMENT STRATEGY
- **Don't remove too much**: Only discard steps the user explicitly asked to remove
- **Be comprehensive**: Add ALL new requirements the user mentioned
- **Be thoughtful**: Modify existing steps to accommodate feedback
- **Be clear**: Explain why changes were made
- **Be realistic**: Adjust complexity and effort estimates

## RESPONSE FORMAT

Return ONLY valid JSON (no markdown, no explanation):

```json
{{
  "plan_id": "plan-refined-{original_request[:20].replace(' ', '-')}",
  "summary": "Updated plan that incorporates all user feedback",
  "refinements_made": [
    "Added async/await support for I/O operations",
    "Removed database migration step per user request",
    "Modified test strategy to focus on rate limiting"
  ],
  "steps": [
    {{
      "step_number": 1,
      "action": "understand",
      "file": "src/api/handlers.py",
      "target_function": null,
      "details": "Understand current API implementation",
      "reason": "Establish baseline understanding",
      "dependencies": []
    }},
    {{
      "step_number": 2,
      "action": "modify",
      "file": "src/api/handlers.py",
      "target_function": "handle_request",
      "details": "Add async/await for I/O operations",
      "reason": "User requested async support for performance",
      "dependencies": [1]
    }},
    {{
      "step_number": 3,
      "action": "create",
      "file": "src/middleware/rate_limiter.py",
      "target_function": null,
      "details": "Create rate limiting middleware",
      "reason": "User added rate limiting requirement",
      "dependencies": [1]
    }},
    {{
      "step_number": 4,
      "action": "test",
      "file": "tests/test_rate_limiting.py",
      "target_function": null,
      "details": "Add tests for rate limiting",
      "reason": "Ensure reliability of new middleware",
      "dependencies": [3]
    }}
  ],
  "estimated_impact": {{
    "files_to_modify": 1,
    "files_to_create": 2,
    "files_to_delete": 0,
    "breaking_changes": 0,
    "risk_level": "low"
  }},
  "estimated_tokens": 2500,
  "user_requests_addressed": [
    "Async/await for performance",
    "Rate limiting added",
    "Authentication flow unchanged"
  ],
  "open_questions": [
    "Should caching be considered for performance?",
    "What rate limit should be set?"
  ]
}}
```

**Critical:** Start response with opening brace `{{` immediately."""

    def _format_plan_for_prompt(self, plan: Dict[str, Any]) -> str:
        """Format plan for inclusion in prompt."""
        output = []
        output.append(f"Summary: {plan.get('summary', 'N/A')}")
        output.append(f"Steps: {len(plan.get('steps', []))}")

        for step in plan.get("steps", [])[:5]:
            output.append(
                f"  - Step {step.get('step_number')}: "
                f"{step.get('action')} {step.get('file')}"
            )

        return "\n".join(output)

    def _parse_refined_plan(self, response: str) -> Dict[str, Any]:
        """Parse LLM response as refined plan."""
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                return json.loads(json_str)
        except Exception as e:
            logger.warning(f"Could not parse refined plan: {e}")

        return {"steps": [], "summary": "Refinement failed"}

    def generate_refinement_summary(self, feedback: ParsedUserFeedback) -> str:
        """Generate summary of what will be refined."""
        output = []

        output.append("\n" + "=" * 70)
        output.append("PLAN REFINEMENT")
        output.append("=" * 70)

        if feedback.requirements_to_add:
            output.append("\n✅ Will ADD:")
            for req in feedback.requirements_to_add:
                output.append(f"  • {req}")

        if feedback.requirements_to_remove:
            output.append("\n❌ Will REMOVE:")
            for req in feedback.requirements_to_remove:
                output.append(f"  • {req}")

        if feedback.requirements_to_modify:
            output.append("\n🔄 Will MODIFY:")
            for req in feedback.requirements_to_modify:
                output.append(f"  • {req}")

        if feedback.documented_concerns:
            output.append("\n⚠️  Concerns noted:")
            for concern in feedback.documented_concerns:
                output.append(f"  • {concern}")

        if feedback.clarification_questions:
            output.append("\n❓ Questions:")
            for question in feedback.clarification_questions:
                output.append(f"  • {question}")

        output.append(f"\n🎯 Understanding confidence: {feedback.parsing_confidence_score:.0%}")
        output.append("\n" + "=" * 70)

        return "\n".join(output)

    @staticmethod
    def should_refine(feedback_confidence: float) -> bool:
        """Decide if feedback is clear enough to refine."""
        return feedback_confidence > 0.6

    def ask_for_clarification(self, feedback: ParsedUserFeedback) -> str:
        """Generate request for clarification if confidence is low."""
        output = []

        output.append("\n⚠️  I'm not entirely sure what you mean. Could you clarify?\n")

        output.append("Your feedback mentioned:")
        output.append(f"  • {feedback.original_feedback}\n")

        output.append("Did you mean:")
        output.append("  A) Add new features?")
        output.append("  B) Remove existing requirements?")
        output.append("  C) Modify the approach?")
        output.append("  D) Something else?\n")

        output.append("Please rephrase or pick A/B/C/D:")

        return "\n".join(output)
