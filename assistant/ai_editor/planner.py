"""Planning agent that creates step-by-step editing plans."""

import json
import logging
from typing import Optional

from .schemas import IntentAnalysis, PlanResult, PlanStep, RetrievalResult

logger = logging.getLogger(__name__)


class Planner:
    """Create structured editing plans from intent and context."""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM client with complete() method
        """
        self.llm = llm_client

    def plan(
        self,
        intent: IntentAnalysis,
        retrieval: RetrievalResult,
        user_request: str,
    ) -> PlanResult:
        """Generate step-by-step plan."""

        prompt = self._build_prompt(intent, retrieval, user_request)

        # Call LLM
        response = self.llm.complete(
            prompt, max_tokens=2000, temperature=0.1
        )

        # Parse response
        plan_data = self._parse_response(response)
        steps = self._build_plan_steps(plan_data.get("steps", []))

        plan_result = PlanResult(
            plan_id=plan_data.get("plan_id", "plan-unknown"),
            steps=steps,
            summary=plan_data.get("summary", ""),
            estimated_impact=plan_data.get("estimated_impact", {}),
            estimated_tokens=plan_data.get("estimated_tokens", 2000),
            raw=response,
        )

        logger.info(f"Plan created: {len(steps)} steps")
        return plan_result

    def _build_prompt(
        self,
        intent: IntentAnalysis,
        retrieval: RetrievalResult,
        user_request: str,
    ) -> str:
        """Build prompt for plan generation."""

        file_list = "\n".join(
            [f"- {f.file_path} ({len(f.content)} chars, {f.language})"
             for f in retrieval.files[:8]]
        )

        symbols_list = "\n".join(
            [
                f"- {name}: {loc.type} in {loc.file}:{loc.line}"
                for name, loc in list(retrieval.symbols.items())[:10]
            ]
        )

        prompt = f"""
REQUEST: {user_request}

INTENT ANALYSIS:
- Type: {intent.intent_type.value}
- Complexity: {intent.complexity_score}/5
- Confidence: {intent.confidence:.0%}

RELEVANT FILES:
{file_list}

KEY SYMBOLS:
{symbols_list}

TASK: Create a step-by-step PLAN (NO CODE YET).

For each step, specify:
1. Action (understand/modify/create/delete/test)
2. File to affect
3. What to change specifically
4. Why this change matters

Output ONLY valid JSON (no markdown, no explanation):
{{
  "plan_id": "plan-YYYYMMDD-NNN",
  "summary": "Brief plan overview",
  "steps": [
    {{
      "step_number": 1,
      "action": "understand",
      "file": "path/to/file.py",
      "goal": "Read current implementation",
      "details": "Understand what needs to change"
    }},
    {{
      "step_number": 2,
      "action": "modify",
      "file": "path/to/file.py",
      "target_function": "function_name",
      "change_type": "add_logic",
      "details": "Add new validation logic"
    }}
  ],
  "estimated_impact": {{
    "files_to_modify": 1,
    "files_to_create": 0,
    "breaking_changes": 0
  }},
  "estimated_tokens": 2500
}}

Start with JSON opening brace immediately.
"""

        return prompt

    def _parse_response(self, response: str) -> dict:
        """Parse LLM response as JSON."""
        # Find JSON content
        response = response.strip()

        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass

        # Fallback
        logger.warning("Could not parse plan response as JSON")
        return {"steps": [], "summary": "Parse failed"}

    def _build_plan_steps(self, steps_data: list) -> list:
        """Convert step data to PlanStep objects."""
        steps = []

        for i, step_data in enumerate(steps_data):
            step = PlanStep(
                step_number=step_data.get("step_number", i + 1),
                action=step_data.get("action", "understand"),
                file=step_data.get("file", ""),
                target_function=step_data.get("target_function"),
                change_type=step_data.get("change_type"),
                details=step_data.get("details", ""),
                goal=step_data.get("goal", ""),
                depends_on=step_data.get("depends_on", []),
            )
            steps.append(step)

        return steps
