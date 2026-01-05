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
class ContextStats:
    """Statistics about current context usage."""

    estimated_tokens: int
    context_limit: int
    reserved_tokens: int
    available_tokens: int
    usage_percent: float
    message_count: int
    warning_level: str  # "ok", "warning", "critical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "context_limit": self.context_limit,
            "reserved_tokens": self.reserved_tokens,
            "available_tokens": self.available_tokens,
            "usage_percent": round(self.usage_percent, 1),
            "message_count": self.message_count,
            "warning_level": self.warning_level,
        }


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
    context_limit: int | None = None,
) -> ContextStats:
    """Calculate comprehensive context statistics.

    Args:
        messages: List of conversation messages
        system_prompt: The system prompt text
        play_context: The Play hierarchy context
        learned_kb: Learned knowledge from previous compactions
        context_limit: Override for context limit (defaults to medium model)

    Returns:
        ContextStats with usage information
    """
    if context_limit is None:
        context_limit = MODEL_CONTEXT_LIMITS["medium"]

    estimated_tokens = estimate_context_tokens(
        system_prompt=system_prompt,
        play_context=play_context,
        learned_kb=learned_kb,
        messages=messages,
    )

    available_tokens = max(0, context_limit - RESERVED_TOKENS - estimated_tokens)
    usage_percent = (estimated_tokens / (context_limit - RESERVED_TOKENS)) * 100
    usage_percent = min(100.0, usage_percent)  # Cap at 100%

    return ContextStats(
        estimated_tokens=estimated_tokens,
        context_limit=context_limit,
        reserved_tokens=RESERVED_TOKENS,
        available_tokens=available_tokens,
        usage_percent=usage_percent,
        message_count=len(messages) if messages else 0,
        warning_level=get_warning_level(usage_percent),
    )
