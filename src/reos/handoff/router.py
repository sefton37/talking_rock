"""Domain router for Talking Rock handoffs.

Uses RIVA-style intent verification to:
1. Detect which domain(s) a request belongs to
2. Identify the primary intent for multi-domain requests
3. Decide whether current agent can handle simply or should handoff

Agents are flexible - they handle simple out-of-domain tasks.
Handoffs are for complex domain-specific work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from reos.handoff.models import (
    AgentType,
    DomainConfidence,
    HandoffContext,
    HandoffDecision,
)


# Domain keyword patterns for each agent
# These are fallback heuristics - the LLM can also decide to handoff
DOMAIN_PATTERNS: dict[AgentType, dict[str, list[str]]] = {
    AgentType.CAIRN: {
        "strong": [
            "remind", "reminder", "todo", "task list", "calendar", "schedule",
            "meeting", "appointment", "priority", "prioritize", "focus",
            "knowledge base", "note", "journal", "defer", "later", "tomorrow",
            "next week", "someday", "backlog", "waiting on", "email summary",
        ],
        "moderate": [
            "organize", "plan", "track", "remember", "save this", "note that",
            "what's next", "what should i", "help me decide", "too much",
        ],
    },
    AgentType.REOS: {
        "strong": [
            "install", "uninstall", "update", "upgrade", "restart", "reboot",
            "service", "systemd", "process", "kill", "memory", "cpu", "disk",
            "storage", "network", "docker", "container", "package", "apt",
            "dnf", "pacman", "terminal", "shell", "command", "linux", "system",
            "sudo", "permission", "firewall", "port", "ssh",
        ],
        "moderate": [
            "run", "execute", "check", "status", "monitor", "log", "server",
            "machine", "computer", "os", "operating system",
        ],
    },
    AgentType.RIVA: {
        "strong": [
            "code", "function", "class", "method", "variable", "bug", "error",
            "exception", "refactor", "implement", "write code", "fix the code",
            "add feature", "git", "commit", "push", "pull", "branch", "merge",
            "repository", "repo", "test", "unittest", "pytest", "debug",
            "breakpoint", "syntax", "compile", "build", "lint", "type error",
        ],
        "moderate": [
            "script", "program", "application", "api", "endpoint", "database",
            "query", "schema", "model", "controller", "view", "component",
        ],
    },
}

# Complexity indicators - suggests handoff even for moderate matches
COMPLEXITY_INDICATORS = [
    "multiple", "several", "all the", "entire", "whole",
    "refactor", "redesign", "overhaul", "migrate", "convert",
    "troubleshoot", "investigate", "analyze", "diagnose",
]

# Simplicity indicators - suggests current agent can handle
SIMPLICITY_INDICATORS = [
    "just", "simply", "quick", "small", "minor", "single",
    "one", "only", "brief", "fast",
]


@dataclass
class DomainScore:
    """Score for how well a message matches a domain."""

    agent: AgentType
    strong_matches: list[str]
    moderate_matches: list[str]

    @property
    def score(self) -> float:
        """Calculate weighted score."""
        return len(self.strong_matches) * 2.0 + len(self.moderate_matches) * 0.5

    @property
    def has_matches(self) -> bool:
        """Check if any matches found."""
        return bool(self.strong_matches or self.moderate_matches)


def analyze_domain(message: str) -> dict[AgentType, DomainScore]:
    """Analyze which domains a message belongs to.

    Args:
        message: The user's message.

    Returns:
        Dict mapping each agent to its domain score.
    """
    message_lower = message.lower()
    scores: dict[AgentType, DomainScore] = {}

    for agent, patterns in DOMAIN_PATTERNS.items():
        strong_matches = [
            kw for kw in patterns["strong"]
            if kw in message_lower
        ]
        moderate_matches = [
            kw for kw in patterns["moderate"]
            if kw in message_lower
        ]
        scores[agent] = DomainScore(
            agent=agent,
            strong_matches=strong_matches,
            moderate_matches=moderate_matches,
        )

    return scores


def is_complex_request(message: str) -> bool:
    """Check if request appears complex."""
    message_lower = message.lower()
    return any(ind in message_lower for ind in COMPLEXITY_INDICATORS)


def is_simple_request(message: str) -> bool:
    """Check if request appears simple."""
    message_lower = message.lower()
    return any(ind in message_lower for ind in SIMPLICITY_INDICATORS)


def detect_handoff_need(
    current_agent: AgentType,
    message: str,
    conversation_context: list[str] | None = None,
) -> HandoffDecision:
    """Analyze whether a handoff is needed.

    Uses RIVA-style intent verification:
    1. Identify all domains present in the request
    2. Determine primary intent
    3. Decide if current agent can handle or should handoff

    Agents are flexible - simple out-of-domain tasks stay with current agent.

    Args:
        current_agent: The currently active agent.
        message: The user's current message.
        conversation_context: Optional recent conversation for context.

    Returns:
        HandoffDecision with recommendation.
    """
    scores = analyze_domain(message)
    is_complex = is_complex_request(message)
    is_simple = is_simple_request(message)

    # Get domains with matches
    matched_domains = [
        agent for agent, score in scores.items()
        if score.has_matches
    ]

    # Sort by score
    sorted_domains = sorted(
        matched_domains,
        key=lambda a: scores[a].score,
        reverse=True,
    )

    # Current agent's score
    current_score = scores[current_agent]

    # No matches anywhere - stay with current agent
    if not matched_domains:
        return HandoffDecision(
            should_handoff=False,
            confidence=DomainConfidence.LOW,
            reason="No specific domain keywords detected. I'll help with this.",
            detected_domains=[],
            can_handle_simply=True,
        )

    # Only current agent matches - definitely stay
    if matched_domains == [current_agent]:
        return HandoffDecision(
            should_handoff=False,
            confidence=DomainConfidence.HIGH,
            reason="This is clearly in my domain.",
            detected_domains=[current_agent],
            can_handle_simply=True,
        )

    # Current agent has strong matches - stay
    if current_score.strong_matches:
        other_strong = any(
            scores[a].strong_matches
            for a in matched_domains
            if a != current_agent
        )
        if not other_strong:
            return HandoffDecision(
                should_handoff=False,
                confidence=DomainConfidence.HIGH,
                reason="This matches my specialty.",
                detected_domains=matched_domains,
                can_handle_simply=True,
            )

    # Determine best target (not current agent)
    other_domains = [a for a in sorted_domains if a != current_agent]

    if not other_domains:
        return HandoffDecision(
            should_handoff=False,
            confidence=DomainConfidence.MEDIUM,
            reason="I can handle this.",
            detected_domains=matched_domains,
            can_handle_simply=True,
        )

    best_target = other_domains[0]
    best_score = scores[best_target]

    # Simple request to other domain - current agent can handle
    if is_simple and not best_score.strong_matches:
        return HandoffDecision(
            should_handoff=False,
            confidence=DomainConfidence.MEDIUM,
            reason=f"This touches {best_target.value} domain but seems simple enough for me to help with.",
            detected_domains=matched_domains,
            can_handle_simply=True,
        )

    # Strong match in other domain - recommend handoff
    if best_score.strong_matches:
        confidence = DomainConfidence.HIGH if len(best_score.strong_matches) >= 2 else DomainConfidence.MEDIUM

        # Multi-domain request
        if len(matched_domains) > 1:
            primary_intent = _identify_primary_intent(message, best_target)
            deferred = _identify_deferred_intents(message, matched_domains, best_target)

            return HandoffDecision(
                should_handoff=True,
                target_agent=best_target,
                confidence=DomainConfidence.MIXED,
                reason=f"This request involves multiple domains. The primary focus appears to be {best_target.value} ({', '.join(best_score.strong_matches)}). Other aspects can be addressed after.",
                detected_domains=matched_domains,
                primary_intent=primary_intent,
                deferred_intents=deferred,
                can_handle_simply=False,
            )

        return HandoffDecision(
            should_handoff=True,
            target_agent=best_target,
            confidence=confidence,
            reason=f"This is best handled by {best_target.value} (detected: {', '.join(best_score.strong_matches)}).",
            detected_domains=matched_domains,
            primary_intent=message,
            can_handle_simply=False,
        )

    # Moderate match + complex - recommend handoff
    if is_complex and best_score.moderate_matches:
        return HandoffDecision(
            should_handoff=True,
            target_agent=best_target,
            confidence=DomainConfidence.MEDIUM,
            reason=f"This seems like a complex {best_target.value} task that would benefit from specialized handling.",
            detected_domains=matched_domains,
            can_handle_simply=False,
        )

    # Default: stay with current agent for moderate/ambiguous requests
    return HandoffDecision(
        should_handoff=False,
        confidence=DomainConfidence.LOW,
        reason="I can help with this, though you could ask a more specialized agent if needed.",
        detected_domains=matched_domains,
        can_handle_simply=True,
    )


def _identify_primary_intent(message: str, primary_domain: AgentType) -> str:
    """Extract the primary intent for the target domain.

    Args:
        message: The user's message.
        primary_domain: The domain we're handing off to.

    Returns:
        A focused statement of the primary intent.
    """
    # Simple extraction - take the clause containing the strongest keyword
    patterns = DOMAIN_PATTERNS[primary_domain]["strong"]
    message_lower = message.lower()

    for pattern in patterns:
        if pattern in message_lower:
            # Find the sentence/clause containing this keyword
            sentences = re.split(r'[.!?;]', message)
            for sentence in sentences:
                if pattern in sentence.lower():
                    return sentence.strip()

    return message


def _identify_deferred_intents(
    message: str,
    domains: list[AgentType],
    primary: AgentType,
) -> list[str]:
    """Identify secondary intents that might need handling later.

    Args:
        message: The user's message.
        domains: All detected domains.
        primary: The primary domain being handed off to.

    Returns:
        List of deferred intent descriptions.
    """
    deferred = []
    message_lower = message.lower()

    for domain in domains:
        if domain == primary:
            continue

        patterns = DOMAIN_PATTERNS[domain]["strong"]
        matches = [p for p in patterns if p in message_lower]

        if matches:
            deferred.append(
                f"{domain.value}: {', '.join(matches[:3])}"
            )

    return deferred


def build_handoff_context(
    user_goal: str,
    handoff_reason: str,
    conversation_history: list[dict[str, str]] | None = None,
    detected_paths: list[str] | None = None,
    detected_entities: list[str] | None = None,
) -> HandoffContext:
    """Build structured context for a handoff.

    Args:
        user_goal: What the user is trying to accomplish.
        handoff_reason: Why we're handing off.
        conversation_history: Recent conversation messages.
        detected_paths: File paths mentioned.
        detected_entities: Entities (services, contacts, etc.) mentioned.

    Returns:
        HandoffContext ready to pass to target agent.
    """
    recent_messages = []
    relevant_details = []

    if conversation_history:
        # Extract last 5 user messages
        user_messages = [
            m["content"] for m in conversation_history
            if m.get("role") == "user"
        ][-5:]
        recent_messages = user_messages

        # Extract any details that seem important
        for msg in conversation_history[-10:]:
            content = msg.get("content", "")
            # Look for specific details (paths, names, etc.)
            if any(c in content for c in ['/', '~', '.py', '.js', '.ts', '.sh']):
                relevant_details.append(f"Mentioned: {content[:100]}")

    return HandoffContext(
        user_goal=user_goal,
        handoff_reason=handoff_reason,
        relevant_details=relevant_details[:5],  # Cap at 5
        relevant_paths=detected_paths or [],
        relevant_entities=detected_entities or [],
        recent_messages=recent_messages,
    )


def suggest_handoff_for_agent(
    current_agent: AgentType,
    message: str,
) -> tuple[AgentType | None, str]:
    """Simple helper to suggest a handoff target.

    Args:
        current_agent: Current agent.
        message: User message.

    Returns:
        Tuple of (target agent or None, reason string).
    """
    decision = detect_handoff_need(current_agent, message)

    if decision.should_handoff and decision.target_agent:
        return decision.target_agent, decision.reason

    return None, decision.reason
