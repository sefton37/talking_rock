"""Request complexity assessment for ReOS.

Determines whether a user request should be executed directly or needs
multi-step planning. Uses fast heuristics for 90% of cases.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ComplexityLevel(Enum):
    """Classification of request complexity."""

    SIMPLE = "simple"      # Direct execution, single command
    COMPLEX = "complex"    # Needs planning, multiple steps
    RISKY = "risky"        # Potentially destructive, needs confirmation
    DIAGNOSTIC = "diagnostic"  # Needs investigation before action


@dataclass(frozen=True)
class ComplexityResult:
    """Result of complexity assessment."""

    level: ComplexityLevel
    confidence: float  # 0.0 to 1.0
    reason: str
    suggested_approach: str
    keywords_matched: list[str]


# Simple request patterns - direct execution
SIMPLE_PATTERNS = [
    # Single command operations
    (r"\b(open|launch|start|run)\s+\w+\b", "application launch"),
    (r"\b(show|display|what('s| is)|tell me)\s+(my\s+)?(ip|disk|memory|cpu|ram)\b", "info query"),
    (r"\b(list|show)\s+(running\s+)?(processes|services|packages)\b", "listing"),
    (r"\binstall\s+\w+\b", "single package install"),
    (r"\b(is|check if)\s+\w+\s+(running|installed|active)\b", "status check"),
    (r"\bhow much\s+(ram|memory|disk|space)\b", "resource query"),
    (r"\bwhat time\b", "simple query"),
    (r"\bwho am i\b", "identity query"),
    (r"\bwhat's my (username|hostname)\b", "identity query"),
    (r"\b(ping|traceroute|nslookup)\s+", "network diagnostic"),
    (r"\b(cat|head|tail|less)\s+", "file viewing"),
    (r"\bls\s+", "directory listing"),
    (r"\bdf\b", "disk space"),
    (r"\bfree\b", "memory info"),
    (r"\btop\b", "process monitor"),
    (r"\buptime\b", "uptime query"),
    (r"\bdate\b", "date query"),
]

# Complex request patterns - needs planning
COMPLEX_PATTERNS = [
    # Multi-step operations
    (r"\bset\s*up\b.*\b(environment|development|server)\b", "environment setup"),
    (r"\bconfigure\b.*\b(for|to)\b", "system configuration"),
    (r"\bswitch\s+(from|to)\b", "system migration"),
    (r"\bmigrate\b", "data/system migration"),
    (r"\bupgrade\b.*\b(system|distribution|os)\b", "major upgrade"),
    (r"\b(speed|make)\b.*\b(up|faster|quicker)\b", "performance optimization"),
    (r"\boptimize\b", "optimization"),
    (r"\b(clean|free)\s*(up)?\b.*\b(disk|space|storage)\b", "cleanup operation"),
    (r"\bbackup\b", "backup operation"),
    (r"\brestore\b", "restore operation"),
    (r"\binstall\b.*\band\b.*\bconfigure\b", "install with config"),
    (r"\b(secure|harden)\b.*\b(system|server)\b", "security hardening"),
    (r"\bset\s*up\b.*\b(ssh|firewall|vpn|nginx|apache)\b", "service setup"),
    (r"\bcreate\b.*\b(user|account)\b.*\bwith\b", "user creation with config"),
    (r"\bautomate\b", "automation setup"),
    (r"\bschedule\b", "scheduled task setup"),
]

# Diagnostic patterns - needs investigation first
DIAGNOSTIC_PATTERNS = [
    (r"\bwhy\s+(is|does|isn't|won't)\b", "diagnostic question"),
    (r"\b(isn't|not)\s+working\b", "troubleshooting"),
    (r"\b(slow|sluggish|laggy|unresponsive)\b", "performance issue"),
    (r"\b(hot|overheating|fan\s+(loud|noisy|running))\b", "thermal issue"),
    (r"\b(error|problem|issue|bug|crash)\b", "error diagnosis"),
    (r"\bwhat's\s+(wrong|happening|going\s+on)\b", "diagnostic question"),
    (r"\bcan't\s+(connect|access|open|run)\b", "connectivity/access issue"),
    (r"\b(broken|failed|failing)\b", "failure diagnosis"),
    (r"\bdebug\b", "debugging"),
    (r"\btroubleshoot\b", "troubleshooting"),
    (r"\b(wifi|network|internet)\s+(down|not working|disconnected)\b", "network issue"),
    (r"\b(boot|startup)\s+(slow|problem|hang)\b", "boot issue"),
]

# Risky patterns - needs explicit confirmation
RISKY_PATTERNS = [
    (r"\b(delete|remove|erase)\s+(all|every)\b", "bulk deletion"),
    (r"\brm\s+-rf\b", "recursive delete"),
    (r"\bformat\b.*\b(disk|drive|partition)\b", "disk formatting"),
    (r"\b(wipe|destroy)\b", "data destruction"),
    (r"\bupgrade\b.*\bkernel\b", "kernel upgrade"),
    (r"\bdistro\s*upgrade\b", "distribution upgrade"),
    (r"\b(disable|stop)\b.*\b(firewall|security)\b", "security reduction"),
    (r"\bchmod\s+777\b", "permissive permissions"),
    (r"\bsudo\s+rm\b", "root deletion"),
    (r"\brepartition\b", "disk repartitioning"),
    (r"\breinstall\b.*\b(os|system)\b", "system reinstall"),
    (r"\bpurge\b", "package purge"),
    (r"\b(downgrade|rollback)\b", "version rollback"),
]


class ComplexityAssessor:
    """Assesses the complexity of user requests.

    Uses pattern matching and heuristics for fast assessment (<100ms).
    Falls back to LLM for ambiguous cases.
    """

    def __init__(self, use_llm_fallback: bool = True) -> None:
        """Initialize the assessor.

        Args:
            use_llm_fallback: Whether to use LLM for ambiguous cases
        """
        self.use_llm_fallback = use_llm_fallback
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        self._simple = [(re.compile(p, re.IGNORECASE), d) for p, d in SIMPLE_PATTERNS]
        self._complex = [(re.compile(p, re.IGNORECASE), d) for p, d in COMPLEX_PATTERNS]
        self._diagnostic = [(re.compile(p, re.IGNORECASE), d) for p, d in DIAGNOSTIC_PATTERNS]
        self._risky = [(re.compile(p, re.IGNORECASE), d) for p, d in RISKY_PATTERNS]

    def assess(self, request: str) -> ComplexityResult:
        """Assess the complexity of a user request.

        Args:
            request: The user's natural language request

        Returns:
            ComplexityResult with classification and reasoning
        """
        request = request.strip()
        if not request:
            return ComplexityResult(
                level=ComplexityLevel.SIMPLE,
                confidence=1.0,
                reason="Empty request",
                suggested_approach="Ask for clarification",
                keywords_matched=[],
            )

        # Check patterns in priority order
        risky_matches = self._match_patterns(request, self._risky)
        if risky_matches:
            return ComplexityResult(
                level=ComplexityLevel.RISKY,
                confidence=0.9,
                reason=f"Potentially destructive operation: {risky_matches[0][1]}",
                suggested_approach="Present clear plan with warnings before execution",
                keywords_matched=[m[1] for m in risky_matches],
            )

        diagnostic_matches = self._match_patterns(request, self._diagnostic)
        if diagnostic_matches:
            return ComplexityResult(
                level=ComplexityLevel.DIAGNOSTIC,
                confidence=0.85,
                reason=f"Needs investigation: {diagnostic_matches[0][1]}",
                suggested_approach="Gather system information before suggesting solutions",
                keywords_matched=[m[1] for m in diagnostic_matches],
            )

        complex_matches = self._match_patterns(request, self._complex)
        if complex_matches:
            return ComplexityResult(
                level=ComplexityLevel.COMPLEX,
                confidence=0.85,
                reason=f"Multi-step operation: {complex_matches[0][1]}",
                suggested_approach="Create step-by-step plan with verification",
                keywords_matched=[m[1] for m in complex_matches],
            )

        simple_matches = self._match_patterns(request, self._simple)
        if simple_matches:
            return ComplexityResult(
                level=ComplexityLevel.SIMPLE,
                confidence=0.9,
                reason=f"Direct operation: {simple_matches[0][1]}",
                suggested_approach="Execute directly and report result",
                keywords_matched=[m[1] for m in simple_matches],
            )

        # No clear pattern match - use heuristics
        return self._heuristic_assessment(request)

    def _match_patterns(
        self, text: str, patterns: list[tuple[re.Pattern, str]]
    ) -> list[tuple[re.Match, str]]:
        """Match text against a list of compiled patterns.

        Returns list of (match, description) tuples.
        """
        matches = []
        for pattern, description in patterns:
            match = pattern.search(text)
            if match:
                matches.append((match, description))
        return matches

    def _heuristic_assessment(self, request: str) -> ComplexityResult:
        """Apply heuristics when pattern matching is inconclusive."""
        words = request.lower().split()
        word_count = len(words)

        # Short requests are usually simple
        if word_count <= 3:
            return ComplexityResult(
                level=ComplexityLevel.SIMPLE,
                confidence=0.6,
                reason="Short request, likely simple operation",
                suggested_approach="Execute and verify",
                keywords_matched=[],
            )

        # Requests with multiple actions are complex
        action_words = {"and", "then", "after", "before", "also", "plus"}
        action_count = sum(1 for w in words if w in action_words)
        if action_count >= 2:
            return ComplexityResult(
                level=ComplexityLevel.COMPLEX,
                confidence=0.7,
                reason="Multiple sequential actions implied",
                suggested_approach="Break down into steps",
                keywords_matched=list(action_words & set(words)),
            )

        # Questions about "how" often need planning
        if request.lower().startswith("how"):
            return ComplexityResult(
                level=ComplexityLevel.COMPLEX,
                confidence=0.6,
                reason="How-to question may need multi-step explanation",
                suggested_approach="Provide steps with explanations",
                keywords_matched=["how"],
            )

        # Default to simple with low confidence
        return ComplexityResult(
            level=ComplexityLevel.SIMPLE,
            confidence=0.5,
            reason="No clear complexity indicators",
            suggested_approach="Execute and adapt if needed",
            keywords_matched=[],
        )

    def should_plan(self, result: ComplexityResult) -> bool:
        """Determine if a request needs planning based on assessment.

        Args:
            result: The complexity assessment result

        Returns:
            True if planning is recommended
        """
        return result.level in (
            ComplexityLevel.COMPLEX,
            ComplexityLevel.RISKY,
            ComplexityLevel.DIAGNOSTIC,
        )
