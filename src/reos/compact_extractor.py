"""Compact Extractor - Extract lessons and facts from conversations.

Uses the LLM to synthesize knowledge from chat history for long-term storage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .ollama import OllamaClient

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are analyzing a conversation to extract valuable knowledge for long-term memory.

Review the conversation and extract:
1. **Facts**: Concrete information about the user, their system, preferences, or projects
2. **Lessons**: Insights learned from problem-solving or discussions
3. **Decisions**: Choices made about tools, approaches, or architecture
4. **Preferences**: User preferences for communication, workflow, or style
5. **Observations**: Patterns or notable behaviors worth remembering

Rules:
- Be concise - each entry should be 1-2 sentences max
- Be specific - include context that makes the knowledge useful later
- Avoid redundancy - don't repeat similar points
- Focus on durable knowledge - skip ephemeral details
- Skip trivial observations - only extract genuinely useful knowledge
- Maximum 10 entries total across all categories

Return JSON in this exact format:
{
  "entries": [
    {"category": "fact", "content": "User's primary development machine runs Ubuntu 24.04"},
    {"category": "lesson", "content": "When user says 'hit it', they want immediate implementation without further planning"},
    {"category": "decision", "content": "Project uses Tauri + Rust backend with Python kernel for flexibility"},
    {"category": "preference", "content": "User prefers concise commit messages focused on the 'what'"},
    {"category": "observation", "content": "User iterates quickly and prefers working code over perfect code"}
  ]
}

If no meaningful knowledge can be extracted, return: {"entries": []}
"""


def extract_knowledge_from_messages(
    messages: list[dict[str, Any]],
    ollama: OllamaClient | None = None,
    existing_knowledge: str = "",
) -> list[dict[str, str]]:
    """Extract learned knowledge from conversation messages.

    Args:
        messages: The conversation messages to analyze
        ollama: Optional OllamaClient (creates default if not provided)
        existing_knowledge: Current learned KB to avoid duplicates

    Returns:
        List of {"category": ..., "content": ...} entries
    """
    if not messages:
        return []

    if ollama is None:
        ollama = OllamaClient()

    # Format conversation for analysis
    conversation_text = format_messages_for_analysis(messages)

    system = EXTRACTION_PROMPT
    if existing_knowledge:
        system += f"\n\nEXISTING KNOWLEDGE (avoid duplicating these):\n{existing_knowledge}"

    user = f"CONVERSATION TO ANALYZE:\n\n{conversation_text}"

    try:
        raw = ollama.chat_json(system=system, user=user, temperature=0.3)
        data = json.loads(raw)
        entries = data.get("entries", [])

        # Validate entries
        valid_entries = []
        valid_categories = {"fact", "lesson", "decision", "preference", "observation"}

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            category = entry.get("category", "").lower()
            content = entry.get("content", "")

            if category not in valid_categories:
                category = "observation"

            if content and len(content) > 5:  # Skip very short entries
                valid_entries.append({"category": category, "content": content})

        logger.info("Extracted %d knowledge entries from %d messages",
                   len(valid_entries), len(messages))
        return valid_entries

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to extract knowledge: %s", e)
        return []


def format_messages_for_analysis(messages: list[dict[str, Any]]) -> str:
    """Format messages into readable text for LLM analysis."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")

        # Truncate very long messages
        if len(content) > 2000:
            content = content[:2000] + "... [truncated]"

        lines.append(f"{role}: {content}")
        lines.append("")  # Blank line between messages

    return "\n".join(lines)


def generate_archive_summary(
    messages: list[dict[str, Any]],
    ollama: OllamaClient | None = None,
) -> str:
    """Generate a brief summary of a conversation for archive metadata.

    Args:
        messages: The conversation messages
        ollama: Optional OllamaClient

    Returns:
        1-2 sentence summary
    """
    if not messages:
        return ""

    if ollama is None:
        ollama = OllamaClient()

    conversation_text = format_messages_for_analysis(messages[-10:])  # Last 10 messages

    system = """Summarize this conversation in 1-2 sentences.
Focus on what was accomplished or discussed.
Be specific but concise."""

    try:
        summary = ollama.chat_text(system=system, user=conversation_text, temperature=0.3)
        return summary.strip()[:500]  # Cap length
    except Exception as e:
        logger.warning("Failed to generate summary: %s", e)
        return ""
