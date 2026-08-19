"""Props analyzer for extracting detailed requirements from user requests."""

import json
import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RequirementType(str, Enum):
    """Types of requirements extracted from user request."""
    FUNCTIONAL = "functional"  # What the code should do
    PERFORMANCE = "performance"  # Performance requirements
    SECURITY = "security"  # Security/safety requirements
    COMPATIBILITY = "compatibility"  # Compatibility requirements
    REFACTOR = "refactor"  # Code quality/refactoring
    TEST = "test"  # Testing requirements
    DOCUMENTATION = "documentation"  # Documentation requirements


@dataclass
class Requirement:
    """Single requirement extracted from request."""
    type: RequirementType
    description: str
    priority: str  # "high", "medium", "low"
    estimated_effort: str  # "small", "medium", "large"
    related_keywords: List[str] = field(default_factory=list)
    validation_criteria: Optional[str] = None


@dataclass
class PropsAnalysis:
    """Detailed analysis of user request properties."""
    raw_request: str
    requirements: List[Requirement]
    affected_components: List[str]
    dependencies: List[str]
    breaking_changes_possible: bool
    estimated_complexity: int  # 1-5
    estimated_files_to_modify: int
    scope_description: str
    assumptions: List[str]
    clarifications_needed: List[str]
    confidence_score: float  # 0.0-1.0


class PropsAnalyzer:
    """Extract detailed properties and requirements from user requests."""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM client with complete() method
        """
        self.llm = llm_client

    def analyze(self, request: str) -> PropsAnalysis:
        """Analyze user request and extract detailed properties."""
        logger.info(f"Analyzing request: {request[:100]}...")

        # Extract using heuristics first
        heuristic_analysis = self._heuristic_analysis(request)

        # Use LLM for detailed extraction
        llm_analysis = self._llm_based_analysis(request)

        # Merge results
        merged = self._merge_analyses(request, heuristic_analysis, llm_analysis)

        logger.info(
            f"Analysis complete: {len(merged.requirements)} requirements, "
            f"complexity {merged.estimated_complexity}/5"
        )

        return merged

    def _heuristic_analysis(self, request: str) -> Dict[str, Any]:
        """Quick heuristic-based analysis."""
        keywords = request.lower().split()
        text = request.lower()

        # Detect requirement types
        req_patterns = {
            RequirementType.FUNCTIONAL: [
                "add", "create", "implement", "support", "enable", "allow",
                "feature", "capability", "function"
            ],
            RequirementType.PERFORMANCE: [
                "fast", "slow", "optimize", "improve", "speed", "performance",
                "efficient", "latency", "throughput"
            ],
            RequirementType.SECURITY: [
                "secure", "safety", "validate", "sanitize", "encrypt", "auth",
                "permission", "access", "vulnerability", "fix", "bug"
            ],
            RequirementType.COMPATIBILITY: [
                "support", "compatible", "version", "platform", "backwards",
                "legacy", "migrate"
            ],
            RequirementType.REFACTOR: [
                "clean", "improve", "refactor", "simplify", "readable",
                "maintainable", "structure", "reorganize"
            ],
            RequirementType.TEST: [
                "test", "coverage", "unit", "integration", "e2e", "pytest"
            ],
            RequirementType.DOCUMENTATION: [
                "doc", "comment", "readme", "document", "explain", "docstring"
            ],
        }

        detected_types = set()
        for req_type, patterns in req_patterns.items():
            if any(p in text for p in patterns):
                detected_types.add(req_type)

        # Detect affected components
        affected = []
        component_keywords = {
            "auth": ["auth", "login", "permission", "token", "session"],
            "database": ["db", "database", "query", "sql", "orm", "model"],
            "api": ["api", "endpoint", "route", "request", "response"],
            "ui": ["ui", "component", "button", "input", "form", "page"],
            "config": ["config", "setting", "configuration", "env"],
            "validation": ["validate", "validation", "check", "verify"],
            "cache": ["cache", "redis", "memcache", "performance"],
            "logging": ["log", "logging", "debug", "trace"],
        }

        for component, keywords_list in component_keywords.items():
            if any(k in text for k in keywords_list):
                affected.append(component)

        # Detect breaking changes possibility
        breaking_indicators = [
            "remove", "delete", "deprecate", "change signature",
            "modify interface", "breaking"
        ]
        has_breaking = any(i in text for i in breaking_indicators)

        # Estimate complexity
        complexity = 1
        if len(request) > 300:
            complexity = 3
        if len(detected_types) > 2:
            complexity = min(5, complexity + 1)
        if has_breaking:
            complexity = min(5, complexity + 1)

        return {
            "detected_types": list(detected_types),
            "affected_components": affected,
            "has_breaking_changes": has_breaking,
            "estimated_complexity": complexity,
        }

    def _llm_based_analysis(self, request: str) -> Dict[str, Any]:
        """Use LLM for detailed requirement extraction."""
        prompt = self._build_analysis_prompt(request)

        try:
            response = self.llm.complete(
                prompt, max_tokens=1500, temperature=0.3
            )
            return self._parse_analysis_response(response)
        except Exception as e:
            logger.warning(f"LLM analysis failed, using heuristics: {e}")
            return {
                "requirements": [],
                "assumptions": [],
                "clarifications": [],
            }

    def _build_analysis_prompt(self, request: str) -> str:
        """Build optimized prompt for detailed requirement analysis."""
        return f"""# DETAILED REQUIREMENTS ANALYSIS

## USER REQUEST
{request}

## YOUR TASK
Analyze this code request comprehensively and extract all requirements, dependencies, and risks.

Think about:
1. **What** needs to be changed (requirements)
2. **Where** it will impact (affected components)
3. **How** complex it is (complexity score)
4. **Whether** it breaks existing functionality (breaking changes)
5. **What** assumptions are being made
6. **What** clarifications are needed

## REQUIREMENT TYPES

Identify all applicable requirement types:
- **functional**: New features, capabilities, behavior changes
- **performance**: Speed, optimization, efficiency improvements
- **security**: Authorization, validation, data protection
- **compatibility**: Version support, platform support, legacy support
- **refactor**: Code quality, maintainability, structure improvements
- **test**: Test coverage, unit tests, integration tests
- **documentation**: Comments, docstrings, README updates

## COMPLEXITY FACTORS

Consider these when determining complexity (1=trivial, 5=very complex):
- Number of files to modify
- Interdependencies between changes
- Risk of breaking changes
- Testing requirements
- Documentation needs
- Whether new frameworks/libraries needed

## RESPONSE FORMAT

Return ONLY valid JSON (no markdown, no explanation):

```json
{{
  "requirements": [
    {{
      "type": "functional",
      "description": "Add email validation to user registration",
      "priority": "high",
      "effort": "small",
      "keywords": ["validation", "email", "registration"]
    }},
    {{
      "type": "test",
      "description": "Add unit tests for email validation",
      "priority": "high",
      "effort": "small",
      "keywords": ["tests", "validation"]
    }}
  ],
  "affected_components": [
    "user_model",
    "registration_service",
    "validators"
  ],
  "dependencies": [
    "email-validator",
    "pytest"
  ],
  "breaking_changes": false,
  "complexity": 2,
  "estimated_files_to_modify": 3,
  "scope": "Add email validation to user registration flow without breaking existing functionality",
  "assumptions": [
    "User model exists and is modifiable",
    "Tests are required before merging",
    "Email format follows RFC 5322 standards"
  ],
  "clarifications_needed": [
    "Should bounce validation be included?",
    "Should international emails be supported?"
  ],
  "confidence": 0.90
}}
```

## FIELD DEFINITIONS

- **requirements**: Array of specific requirements with priority and effort
- **affected_components**: Which parts of system will be affected
- **dependencies**: External libraries or internal dependencies needed
- **breaking_changes**: Whether this breaks existing code/API
- **complexity**: Overall complexity score (1-5)
- **estimated_files_to_modify**: Rough estimate of affected files
- **scope**: Clear description of what will be changed
- **assumptions**: Assumptions about existing code/environment
- **clarifications_needed**: Questions that should be clarified before implementation
- **confidence**: Your confidence in the analysis (0.0-1.0)

## GUIDELINES

- Be comprehensive: capture ALL requirements
- Be specific: describe what exactly needs to change
- Be realistic: estimate effort and complexity accurately
- Be cautious: flag potential breaking changes
- Be clear: state assumptions explicitly
- Be thorough: ask clarifying questions if something is ambiguous

**Critical:** Start response with opening brace `{{` immediately.
"""

    def _parse_analysis_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM analysis response."""
        try:
            # Extract JSON
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Could not parse analysis JSON: {e}")

        return {
            "requirements": [],
            "assumptions": [],
            "clarifications": [],
        }

    def _merge_analyses(
        self, request: str, heuristic: Dict, llm_analysis: Dict
    ) -> PropsAnalysis:
        """Merge heuristic and LLM analyses."""

        # Build requirements list
        requirements = []

        # From LLM
        for req_data in llm_analysis.get("requirements", []):
            try:
                req = Requirement(
                    type=RequirementType(req_data.get("type", "functional")),
                    description=req_data.get("description", ""),
                    priority=req_data.get("priority", "medium"),
                    estimated_effort=req_data.get("effort", "medium"),
                    related_keywords=req_data.get("keywords", []),
                )
                requirements.append(req)
            except (ValueError, KeyError):
                continue

        # From heuristics if no LLM requirements
        if not requirements and heuristic.get("detected_types"):
            for req_type in heuristic["detected_types"]:
                req = Requirement(
                    type=req_type,
                    description=f"Detected {req_type.value} requirement",
                    priority="medium",
                    estimated_effort="medium",
                )
                requirements.append(req)

        # Merge component lists
        components = set(
            llm_analysis.get("affected_components", [])
            + heuristic.get("affected_components", [])
        )

        # Final complexity
        complexity = max(
            heuristic.get("estimated_complexity", 1),
            llm_analysis.get("complexity", 1),
        )

        return PropsAnalysis(
            raw_request=request,
            requirements=requirements,
            affected_components=list(components),
            dependencies=llm_analysis.get("dependencies", []),
            breaking_changes_possible=(
                heuristic.get("has_breaking_changes", False)
                or llm_analysis.get("breaking_changes", False)
            ),
            estimated_complexity=min(5, complexity),
            estimated_files_to_modify=llm_analysis.get("files_to_modify", 1),
            scope_description=llm_analysis.get("scope", "Code modification"),
            assumptions=llm_analysis.get("assumptions", []),
            clarifications_needed=llm_analysis.get("clarifications", []),
            confidence_score=llm_analysis.get("confidence", 0.6),
        )
