"""Context Meter - Track conversation context usage.

Estimates token count and provides context fullness metrics
to help users know when to archive, compact, or clear conversations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Default context limits by model size category
MODEL_CONTEXT_LIMITS = {
    "small": 4096,      # 4K models
    "medium": 8192,     # 8K models (default)
    "large": 32768,     # 32K models
    "xlarge": 131072,   # 128K models
}

# Reserve some context for system prompt and response
RESERVED_TOKENS = 2048


@dataclass
class ContextSource:
    """A single source contributing to context."""

    name: str
    display_name: str
    tokens: int
    percent: float
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "tokens": self.tokens,
            "percent": round(self.percent, 1),
            "enabled": self.enabled,
            "description": self.description,
        }


@dataclass
class ContextStats:
    """Statistics about current context usage."""

    estimated_tokens: int
    context_limit: int
    reserved_tokens: int
    available_tokens: int
    usage_percent: float
    message_count: int
    warning_level: str  # "ok", "warning", "critical"
    sources: list[ContextSource] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "estimated_tokens": self.estimated_tokens,
            "context_limit": self.context_limit,
            "reserved_tokens": self.reserved_tokens,
            "available_tokens": self.available_tokens,
            "usage_percent": round(self.usage_percent, 1),
            "message_count": self.message_count,
            "warning_level": self.warning_level,
        }
        if self.sources:
            result["sources"] = [s.to_dict() for s in self.sources]
        return result


def estimate_tokens(text: str) -> int:
    """Estimate token count from text.

    Uses a simple heuristic: ~4 characters per token for English text.
    This is a reasonable approximation for most LLMs.
    """
    if not text:
        return 0
    # Rough estimate: 1 token ≈ 4 characters
    # Add small buffer for special tokens
    return len(text) // 4 + 1


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # Add overhead for role/metadata (~4 tokens per message)
        total += 4
    return total


def estimate_context_tokens(
    *,
    system_prompt: str = "",
    play_context: str = "",
    learned_kb: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate total tokens used in current context."""
    total = 0
    total += estimate_tokens(system_prompt)
    total += estimate_tokens(play_context)
    total += estimate_tokens(learned_kb)
    if messages:
        total += estimate_message_tokens(messages)
    return total


def get_warning_level(usage_percent: float) -> str:
    """Determine warning level based on usage percentage."""
    if usage_percent >= 90:
        return "critical"
    elif usage_percent >= 75:
        return "warning"
    return "ok"


def calculate_context_stats(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str = "",
    play_context: str = "",
    learned_kb: str = "",
    system_state: str = "",
    codebase_context: str = "",
    context_limit: int | None = None,
    include_breakdown: bool = False,
    disabled_sources: set[str] | None = None,
) -> ContextStats:
    """Calculate comprehensive context statistics.

    Args:
        messages: List of conversation messages
        system_prompt: The system prompt text
        play_context: The Play hierarchy context
        learned_kb: Learned knowledge from previous compactions
        system_state: System state/RAG context
        context_limit: Override for context limit (defaults to medium model)
        include_breakdown: Whether to include per-source breakdown
        disabled_sources: Set of source names that are disabled

    Returns:
        ContextStats with usage information
    """
    if context_limit is None:
        context_limit = MODEL_CONTEXT_LIMITS["medium"]

    if disabled_sources is None:
        disabled_sources = set()

    # Calculate tokens per source
    system_tokens = estimate_tokens(system_prompt) if "system_prompt" not in disabled_sources else 0
    play_tokens = estimate_tokens(play_context) if "play_context" not in disabled_sources else 0
    learned_tokens = estimate_tokens(learned_kb) if "learned_kb" not in disabled_sources else 0
    state_tokens = estimate_tokens(system_state) if "system_state" not in disabled_sources else 0
    codebase_tokens = estimate_tokens(codebase_context) if "codebase" not in disabled_sources else 0
    message_tokens = estimate_message_tokens(messages) if messages and "messages" not in disabled_sources else 0

    estimated_tokens = system_tokens + play_tokens + learned_tokens + state_tokens + codebase_tokens + message_tokens

    available_tokens = max(0, context_limit - RESERVED_TOKENS - estimated_tokens)
    usable_context = context_limit - RESERVED_TOKENS
    usage_percent = (estimated_tokens / usable_context) * 100 if usable_context > 0 else 0
    usage_percent = min(100.0, usage_percent)  # Cap at 100%

    sources = None
    if include_breakdown:
        # Calculate percentage of usable context for each source
        sources = [
            ContextSource(
                name="system_prompt",
                display_name="System Prompt",
                tokens=estimate_tokens(system_prompt),
                percent=(estimate_tokens(system_prompt) / usable_context * 100) if usable_context > 0 else 0,
                enabled="system_prompt" not in disabled_sources,
                description="Core instructions defining ReOS behavior and personality",
            ),
            ContextSource(
                name="play_context",
                display_name="The Play",
                tokens=estimate_tokens(play_context),
                percent=(estimate_tokens(play_context) / usable_context * 100) if usable_context > 0 else 0,
                enabled="play_context" not in disabled_sources,
                description="Your story, goals, acts, scenes, and beats",
            ),
            ContextSource(
                name="learned_kb",
                display_name="Learned Knowledge",
                tokens=estimate_tokens(learned_kb),
                percent=(estimate_tokens(learned_kb) / usable_context * 100) if usable_context > 0 else 0,
                enabled="learned_kb" not in disabled_sources,
                description="Facts and preferences learned from past conversations",
            ),
            ContextSource(
                name="system_state",
                display_name="System State",
                tokens=estimate_tokens(system_state),
                percent=(estimate_tokens(system_state) / usable_context * 100) if usable_context > 0 else 0,
                enabled="system_state" not in disabled_sources,
                description="Current machine state - CPU, memory, services, containers",
            ),
            ContextSource(
                name="codebase",
                display_name="Codebase Reference",
                tokens=estimate_tokens(codebase_context),
                percent=(estimate_tokens(codebase_context) / usable_context * 100) if usable_context > 0 else 0,
                enabled="codebase" not in disabled_sources,
                description="ReOS source code structure for self-awareness",
            ),
            ContextSource(
                name="messages",
                display_name="Conversation",
                tokens=estimate_message_tokens(messages) if messages else 0,
                percent=(estimate_message_tokens(messages) / usable_context * 100) if usable_context > 0 and messages else 0,
                enabled="messages" not in disabled_sources,
                description=f"Current chat messages ({len(messages) if messages else 0} messages)",
            ),
        ]

    return ContextStats(
        estimated_tokens=estimated_tokens,
        context_limit=context_limit,
        reserved_tokens=RESERVED_TOKENS,
        available_tokens=available_tokens,
        usage_percent=usage_percent,
        message_count=len(messages) if messages else 0,
        warning_level=get_warning_level(usage_percent),
        sources=sources,
    )
