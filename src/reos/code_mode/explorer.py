"""Multi-path Explorer - Generate and evaluate alternative approaches.

When a step fails and debugging doesn't help, the explorer generates
alternative implementations. Each alternative takes a meaningfully
different approach to solving the same problem.

This is step-level exploration: we try different code, not different
contracts or intents.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

# Runtime import - needed for instantiation
from reos.code_mode.contract import ContractStep

if TYPE_CHECKING:
    from reos.code_mode.intent import DiscoveredIntent
    from reos.code_mode.perspectives import PerspectiveManager, Phase
    from reos.code_mode.sandbox import CodeSandbox

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class StepAlternative:
    """An alternative approach for a step.

    Each alternative represents a meaningfully different way to accomplish
    the same goal. Not just a bug fix, but a different algorithm, library,
    pattern, or approach.
    """

    id: str  # alt-{step_id}-{n}
    step_id: str  # Original step ID
    approach: str  # Short name for this approach
    rationale: str  # Why this might work better
    implementation: str  # The actual code/command to try
    score: float  # 0.0-1.0 likelihood of success

    # Execution tracking
    attempted: bool = False
    succeeded: bool = False
    debug_attempted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "step_id": self.step_id,
            "approach": self.approach,
            "rationale": self.rationale,
            "implementation": self.implementation[:200] + "..." if len(self.implementation) > 200 else self.implementation,
            "score": self.score,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "debug_attempted": self.debug_attempted,
            "error": self.error,
        }


@dataclass
class ExplorationState:
    """Tracks exploration across a step.

    When a step fails and we start exploring alternatives, this tracks
    what we've tried and what worked.
    """

    step_id: str
    original_approach: str  # What we tried first
    original_error: str  # Why it failed

    alternatives: list[StepAlternative] = field(default_factory=list)
    current_alternative_idx: int = 0

    # Results
    successful_approach: StepAlternative | None = None
    all_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "step_id": self.step_id,
            "original_approach": self.original_approach,
            "original_error": self.original_error[:200] if self.original_error else None,
            "alternatives": [alt.to_dict() for alt in self.alternatives],
            "current_alternative_idx": self.current_alternative_idx,
            "successful_approach": self.successful_approach.to_dict() if self.successful_approach else None,
            "all_failed": self.all_failed,
        }


# =============================================================================
# LLM Prompt for Alternative Generation
# =============================================================================

ALTERNATIVES_PROMPT = """You are exploring alternative approaches for a failed code step.

## FAILED STEP
Action: {action}
Target: {target_file}
Description: {description}

## ORIGINAL IMPLEMENTATION
```
{original_code}
```

## ERROR
{error}

## CONTEXT
Goal: {intent_goal}
Language: {language}
Related files: {related_files}
Existing patterns: {patterns}

## TASK
Generate {n_alternatives} DIFFERENT approaches to accomplish this step.

Each alternative should be MEANINGFULLY DIFFERENT from the original:
- Different algorithm or data structure
- Different library or built-in approach
- Simpler implementation without external dependencies
- Different code organization or pattern

For each alternative, provide:
1. A brief name for the approach
2. Why this approach might succeed where the original failed
3. Complete implementation code that can replace the original

Respond with JSON:
{{
  "alternatives": [
    {{
      "approach": "Brief name (3-5 words)",
      "rationale": "Why this might work better",
      "implementation": "Complete code to try",
      "score": 0.8
    }}
  ]
}}

SCORING GUIDELINES:
- 0.9+: Very likely to work (simpler, avoids the error directly)
- 0.7-0.9: Good chance (different approach, addresses root cause)
- 0.5-0.7: Worth trying (alternative pattern, may have other issues)
- <0.5: Long shot (major change, uncertain outcome)

IMPORTANT:
- Each alternative must be genuinely different, not just a syntax fix
- Include ALL necessary imports and setup in the implementation
- Consider: stdlib alternatives, different algorithms, simpler approaches
- Score honestly - overconfident scores waste exploration budget
"""


# =============================================================================
# Step Explorer
# =============================================================================


class StepExplorer:
    """Generate alternative implementations for a failed step.

    When a step fails and debugging doesn't help, the explorer generates
    alternative approaches. Each alternative is executed in turn until
    one succeeds or all are exhausted.
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        perspectives: PerspectiveManager,
    ) -> None:
        """Initialize the explorer.

        Args:
            sandbox: Code sandbox for file access.
            perspectives: Perspective manager for LLM invocation.
        """
        self.sandbox = sandbox
        self._perspectives = perspectives

    def generate_alternatives(
        self,
        step: ContractStep,
        original_error: str,
        intent: DiscoveredIntent,
        original_code: str = "",
        n_alternatives: int = 3,
    ) -> list[StepAlternative]:
        """Generate N alternative approaches for a failed step.

        Args:
            step: The step that failed.
            original_error: Error message from the failure.
            intent: The discovered intent for context.
            original_code: The code that was attempted.
            n_alternatives: Number of alternatives to generate.

        Returns:
            List of StepAlternative objects, sorted by score descending.
        """
        from reos.code_mode.perspectives import Phase

        logger.info(
            "Generating %d alternatives for step %s: %s",
            n_alternatives,
            step.id,
            step.description[:50],
        )

        # Build context for the prompt
        context = self._build_context(step, original_error, intent, original_code, n_alternatives)

        try:
            # Use ENGINEER perspective with higher temperature for diversity
            response = self._perspectives.invoke_json(
                Phase.BUILD,
                ALTERNATIVES_PROMPT.format(**context),
                temperature=0.7,  # Higher temp for creative alternatives
            )

            # Parse response
            data = json.loads(response) if isinstance(response, str) else response
            alternatives = self._parse_alternatives(data, step)

            # Sort by score descending
            alternatives.sort(key=lambda a: a.score, reverse=True)

            logger.info(
                "Generated %d alternatives: %s",
                len(alternatives),
                [a.approach for a in alternatives],
            )

            return alternatives

        except Exception as e:
            logger.warning("Failed to generate alternatives: %s", e)
            # Return empty list on failure - caller will handle
            return []

    def _build_context(
        self,
        step: ContractStep,
        original_error: str,
        intent: DiscoveredIntent,
        original_code: str,
        n_alternatives: int,
    ) -> dict[str, str]:
        """Build context dictionary for the prompt."""
        # Get codebase info from intent
        codebase = intent.codebase_intent

        # Determine what code was attempted
        if not original_code:
            if step.content:
                original_code = step.content
            elif step.new_content:
                original_code = step.new_content
            elif step.command:
                original_code = step.command
            else:
                original_code = "(no code captured)"

        return {
            "action": step.action,
            "target_file": step.target_file or "(none)",
            "description": step.description,
            "original_code": original_code,
            "error": original_error[:1000] if original_error else "Unknown error",
            "intent_goal": intent.goal,
            "language": codebase.language or "unknown",
            "related_files": ", ".join(codebase.related_files[:5]) if codebase.related_files else "(none)",
            "patterns": ", ".join(codebase.existing_patterns[:3]) if codebase.existing_patterns else "(none)",
            "n_alternatives": str(n_alternatives),
        }

    def _parse_alternatives(
        self,
        data: dict[str, Any],
        step: ContractStep,
    ) -> list[StepAlternative]:
        """Parse LLM response into StepAlternative objects."""
        alternatives = []

        raw_alts = data.get("alternatives", [])
        if not isinstance(raw_alts, list):
            logger.warning("Invalid alternatives format: %s", type(raw_alts))
            return alternatives

        for i, alt_data in enumerate(raw_alts):
            if not isinstance(alt_data, dict):
                continue

            alt = StepAlternative(
                id=f"alt-{step.id}-{i}",
                step_id=step.id,
                approach=alt_data.get("approach", f"Alternative {i + 1}"),
                rationale=alt_data.get("rationale", ""),
                implementation=alt_data.get("implementation", ""),
                score=self._parse_score(alt_data.get("score", 0.5)),
            )

            # Only include alternatives with actual implementation
            if alt.implementation.strip():
                alternatives.append(alt)

        return alternatives

    def _parse_score(self, score: Any) -> float:
        """Parse and clamp score to valid range."""
        try:
            s = float(score)
            return max(0.0, min(1.0, s))
        except (ValueError, TypeError):
            return 0.5

    def create_exploration_state(
        self,
        step: ContractStep,
        original_error: str,
        alternatives: list[StepAlternative],
    ) -> ExplorationState:
        """Create an ExplorationState for tracking.

        Args:
            step: The step being explored.
            original_error: Error from the original attempt.
            alternatives: Generated alternatives.

        Returns:
            ExplorationState ready for tracking.
        """
        return ExplorationState(
            step_id=step.id,
            original_approach=step.description,
            original_error=original_error,
            alternatives=alternatives,
        )

    def create_step_from_alternative(
        self,
        alternative: StepAlternative,
        original_step: ContractStep,
    ) -> ContractStep:
        """Create a new ContractStep from an alternative.

        This creates a temporary step that can be executed using the standard
        executor flow. The alternative's implementation replaces the original
        step's content.

        Args:
            alternative: The StepAlternative to convert.
            original_step: The original step that failed.

        Returns:
            ContractStep ready for execution.
        """
        # Create a new step based on the original
        new_step = ContractStep(
            id=alternative.id,
            description=f"{original_step.description} (via {alternative.approach})",
            action=original_step.action,
            target_file=original_step.target_file,
            target_criteria=original_step.target_criteria,
            # Replace content with alternative implementation
            content=alternative.implementation if original_step.action == "create_file" else original_step.content,
            new_content=alternative.implementation if original_step.action == "edit_file" else original_step.new_content,
            command=alternative.implementation if original_step.action == "run_command" else original_step.command,
        )
        return new_step
