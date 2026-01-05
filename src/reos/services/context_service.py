"""Context Service - Context management, compaction, and source toggling.

Provides unified interface for context budget management and
conversation compaction across CLI and RPC interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..db import Database
from ..context_meter import (
    calculate_context_stats,
    estimate_tokens,
    ContextStats,
    ContextSource,
    MODEL_CONTEXT_LIMITS,
    RESERVED_TOKENS,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextStatsResult:
    """Context usage statistics."""

    estimated_tokens: int
    context_limit: int
    reserved_tokens: int
    available_tokens: int
    usage_percent: float
    message_count: int
    warning_level: str
    sources: list[dict[str, Any]] | None = None

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
            result["sources"] = self.sources
        return result

    @classmethod
    def from_context_stats(cls, stats: ContextStats) -> ContextStatsResult:
        return cls(
            estimated_tokens=stats.estimated_tokens,
            context_limit=stats.context_limit,
            reserved_tokens=stats.reserved_tokens,
            available_tokens=stats.available_tokens,
            usage_percent=stats.usage_percent,
            message_count=stats.message_count,
            warning_level=stats.warning_level,
            sources=[s.to_dict() for s in stats.sources] if stats.sources else None,
        )


@dataclass
class CompactionResult:
    """Result from a compaction operation."""

    success: bool
    archive_id: str | None = None
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_saved: int = 0
    learned_entries_added: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "archive_id": self.archive_id,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "learned_entries_added": self.learned_entries_added,
            "error": self.error,
        }


class ContextService:
    """Unified service for context management."""

    def __init__(self, db: Database):
        self._db = db
        self._disabled_sources: set[str] = set()

    def get_stats(
        self,
        conversation_id: str | None = None,
        include_breakdown: bool = True,
    ) -> ContextStatsResult:
        """Get context usage statistics.

        Args:
            conversation_id: Optional conversation to analyze
            include_breakdown: Whether to include per-source breakdown

        Returns:
            ContextStatsResult with usage information
        """
        # Get messages for the conversation
        messages = []
        if conversation_id:
            messages = self._db.get_messages(conversation_id=conversation_id, limit=1000)

        # Get context components
        system_prompt, play_context, learned_kb, system_state, codebase_context = self._get_context_components()

        # Calculate stats
        stats = calculate_context_stats(
            messages=messages,
            system_prompt=system_prompt,
            play_context=play_context,
            learned_kb=learned_kb,
            system_state=system_state,
            codebase_context=codebase_context,
            include_breakdown=include_breakdown,
            disabled_sources=self._disabled_sources,
        )

        return ContextStatsResult.from_context_stats(stats)

    def toggle_source(
        self,
        source_name: str,
        enabled: bool,
    ) -> ContextStatsResult:
        """Enable or disable a context source.

        Args:
            source_name: Name of the source (system_prompt, play_context, etc.)
            enabled: Whether to enable the source

        Returns:
            Updated context stats
        """
        if source_name == "messages":
            # Cannot disable messages - core conversation
            logger.warning("Cannot disable messages source")
            return self.get_stats()

        if enabled:
            self._disabled_sources.discard(source_name)
        else:
            self._disabled_sources.add(source_name)

        logger.info("Context source %s: %s", source_name, "enabled" if enabled else "disabled")
        return self.get_stats()

    def get_disabled_sources(self) -> list[str]:
        """Get list of currently disabled sources."""
        return list(self._disabled_sources)

    def compact(
        self,
        conversation_id: str,
        archive: bool = True,
        extract_knowledge: bool = True,
    ) -> CompactionResult:
        """Compact a conversation to reduce context usage.

        This:
        1. Archives the conversation (if archive=True)
        2. Extracts knowledge entries (if extract_knowledge=True)
        3. Clears the conversation messages

        Args:
            conversation_id: The conversation to compact
            archive: Whether to save messages to archive
            extract_knowledge: Whether to extract learned knowledge

        Returns:
            CompactionResult with details of the operation
        """
        try:
            from ..knowledge_store import KnowledgeStore
            from ..compact_extractor import extract_knowledge_from_messages, generate_archive_summary
            from ..play_fs import list_acts as play_list_acts

            # Get current stats
            stats_before = self.get_stats(conversation_id)
            tokens_before = stats_before.estimated_tokens

            # Get messages
            messages = self._db.get_messages(conversation_id=conversation_id, limit=10000)
            if not messages:
                return CompactionResult(
                    success=False,
                    error="No messages to compact",
                )

            # Get active act for knowledge storage
            _, active_act_id = play_list_acts()

            archive_id = None
            learned_count = 0

            if archive or extract_knowledge:
                store = KnowledgeStore()

                if archive:
                    # Generate summary
                    summary = generate_archive_summary(messages)

                    # Save archive
                    archive_obj = store.save_archive(
                        messages=messages,
                        act_id=active_act_id,
                        summary=summary,
                    )
                    archive_id = archive_obj.archive_id

                if extract_knowledge:
                    # Extract knowledge entries
                    entries = extract_knowledge_from_messages(messages)
                    if entries:
                        added = store.add_learned_entries(
                            entries=entries,
                            act_id=active_act_id,
                            source_archive_id=archive_id,
                        )
                        learned_count = len(added)

            # Clear the conversation
            self._db.clear_messages(conversation_id=conversation_id)

            # Get stats after
            stats_after = self.get_stats(conversation_id)
            tokens_after = stats_after.estimated_tokens

            return CompactionResult(
                success=True,
                archive_id=archive_id,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                tokens_saved=tokens_before - tokens_after,
                learned_entries_added=learned_count,
            )

        except Exception as e:
            logger.error("Compaction failed: %s", e)
            return CompactionResult(
                success=False,
                error=str(e),
            )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return estimate_tokens(text)

    def get_model_limits(self) -> dict[str, int]:
        """Get context limits for different model sizes."""
        return dict(MODEL_CONTEXT_LIMITS)

    def set_context_limit(self, limit: int) -> None:
        """Override the context limit.

        Args:
            limit: New context limit in tokens
        """
        # Store in database state for persistence
        self._db.set_state(key="context_limit", value=str(limit))
        logger.info("Context limit set to %d tokens", limit)

    def get_context_limit(self) -> int:
        """Get the current context limit."""
        limit = self._db.get_state(key="context_limit")
        if limit and isinstance(limit, str):
            try:
                return int(limit)
            except ValueError:
                pass
        return MODEL_CONTEXT_LIMITS["medium"]

    def _get_context_components(self) -> tuple[str, str, str, str, str]:
        """Get all context components for stats calculation.

        Returns:
            Tuple of (system_prompt, play_context, learned_kb, system_state, codebase_context)
        """
        from ..play_fs import read_me_markdown as play_read_me_markdown, list_acts as play_list_acts
        from ..knowledge_store import KnowledgeStore
        from ..system_state import SteadyStateCollector

        # System prompt (approximate)
        system_prompt = (
            "You are ReOS. You embody No One: presence that waits to be invited..."
            # This is just an approximation for token counting
        )

        # Play context
        play_context = ""
        try:
            play_context = play_read_me_markdown()
        except Exception:
            pass

        # Learned knowledge
        learned_kb = ""
        try:
            _, active_act_id = play_list_acts()
            store = KnowledgeStore()
            learned_kb = store.get_learned_markdown(active_act_id)
        except Exception:
            pass

        # System state
        system_state = ""
        try:
            collector = SteadyStateCollector()
            state = collector.refresh_if_stale(max_age_seconds=3600)
            system_state = state.to_context_string()
        except Exception:
            pass

        # Codebase context (self-awareness)
        codebase_context = ""
        try:
            from ..codebase_index import get_codebase_context
            codebase_context = get_codebase_context()
        except Exception:
            pass

        return system_prompt, play_context, learned_kb, system_state, codebase_context

    # --- Archive Access ---

    def list_archives(self, act_id: str | None = None) -> list[dict[str, Any]]:
        """List conversation archives.

        Args:
            act_id: Filter by act (None for play level)

        Returns:
            List of archive metadata dicts
        """
        from ..knowledge_store import KnowledgeStore

        store = KnowledgeStore()
        archives = store.list_archives(act_id)

        return [
            {
                "archive_id": a.archive_id,
                "title": a.title,
                "created_at": a.created_at,
                "archived_at": a.archived_at,
                "message_count": a.message_count,
                "summary": a.summary,
            }
            for a in archives
        ]

    def get_archive(self, archive_id: str, act_id: str | None = None) -> dict[str, Any] | None:
        """Get a specific archive with messages.

        Returns:
            Archive dict with messages, or None if not found
        """
        from ..knowledge_store import KnowledgeStore

        store = KnowledgeStore()
        archive = store.get_archive(archive_id, act_id)

        if archive is None:
            return None

        return archive.to_dict()

    def search_archives(
        self,
        query: str,
        act_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search archives by content.

        Returns:
            List of matching archive metadata
        """
        from ..knowledge_store import KnowledgeStore

        store = KnowledgeStore()
        archives = store.search_archives(query, act_id, limit)

        return [
            {
                "archive_id": a.archive_id,
                "title": a.title,
                "created_at": a.created_at,
                "archived_at": a.archived_at,
                "message_count": a.message_count,
                "summary": a.summary,
            }
            for a in archives
        ]

    def delete_archive(self, archive_id: str, act_id: str | None = None) -> bool:
        """Delete an archive.

        Returns:
            True if deleted successfully
        """
        from ..knowledge_store import KnowledgeStore

        store = KnowledgeStore()
        return store.delete_archive(archive_id, act_id)
