"""Knowledge Service - Learned knowledge and archive management.

Provides unified interface for managing learned knowledge entries
and conversation archives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..knowledge_store import KnowledgeStore, LearnedEntry, Archive

logger = logging.getLogger(__name__)


@dataclass
class LearnedEntryInfo:
    """Information about a learned knowledge entry."""

    entry_id: str
    category: str  # "fact", "lesson", "decision", "preference", "observation"
    content: str
    learned_at: str
    source_archive_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "category": self.category,
            "content": self.content,
            "learned_at": self.learned_at,
            "source_archive_id": self.source_archive_id,
        }

    @classmethod
    def from_learned_entry(cls, entry: LearnedEntry) -> LearnedEntryInfo:
        return cls(
            entry_id=entry.entry_id,
            category=entry.category,
            content=entry.content,
            learned_at=entry.learned_at,
            source_archive_id=entry.source_archive_id,
        )


@dataclass
class KnowledgeStats:
    """Statistics about learned knowledge."""

    total_entries: int
    facts: int
    lessons: int
    decisions: int
    preferences: int
    observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "facts": self.facts,
            "lessons": self.lessons,
            "decisions": self.decisions,
            "preferences": self.preferences,
            "observations": self.observations,
        }


class KnowledgeService:
    """Unified service for learned knowledge management."""

    def __init__(self):
        self._store = KnowledgeStore()

    def search(
        self,
        query: str,
        act_id: str | None = None,
        limit: int = 20,
    ) -> list[LearnedEntryInfo]:
        """Search learned knowledge by content.

        Args:
            query: Search query
            act_id: Filter by act (None for play level)
            limit: Maximum results

        Returns:
            List of matching LearnedEntryInfo
        """
        query_lower = query.lower()
        kb = self._store.load_learned(act_id)

        results = []
        for entry in kb.entries:
            if query_lower in entry.content.lower():
                results.append(LearnedEntryInfo.from_learned_entry(entry))
                if len(results) >= limit:
                    break

        return results

    def list_entries(
        self,
        act_id: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[LearnedEntryInfo]:
        """List learned knowledge entries.

        Args:
            act_id: Filter by act (None for play level)
            category: Filter by category
            limit: Maximum results

        Returns:
            List of LearnedEntryInfo
        """
        kb = self._store.load_learned(act_id)

        results = []
        for entry in kb.entries:
            if category and entry.category != category:
                continue
            results.append(LearnedEntryInfo.from_learned_entry(entry))
            if len(results) >= limit:
                break

        return results

    def add_entry(
        self,
        content: str,
        category: str = "observation",
        act_id: str | None = None,
        source_archive_id: str | None = None,
    ) -> LearnedEntryInfo | None:
        """Add a new learned knowledge entry.

        Args:
            content: The knowledge content
            category: Category (fact, lesson, decision, preference, observation)
            act_id: The act to associate with (None for play level)
            source_archive_id: Optional archive this came from

        Returns:
            The added entry, or None if duplicate
        """
        entries = self._store.add_learned_entries(
            entries=[{"category": category, "content": content}],
            act_id=act_id,
            source_archive_id=source_archive_id,
            deduplicate=True,
        )

        if entries:
            return LearnedEntryInfo.from_learned_entry(entries[0])
        return None

    def add_entries_batch(
        self,
        entries: list[dict[str, str]],
        act_id: str | None = None,
        source_archive_id: str | None = None,
    ) -> list[LearnedEntryInfo]:
        """Add multiple learned knowledge entries.

        Args:
            entries: List of {"category": ..., "content": ...} dicts
            act_id: The act to associate with
            source_archive_id: Optional archive these came from

        Returns:
            List of actually added entries (after deduplication)
        """
        added = self._store.add_learned_entries(
            entries=entries,
            act_id=act_id,
            source_archive_id=source_archive_id,
            deduplicate=True,
        )

        return [LearnedEntryInfo.from_learned_entry(e) for e in added]

    def delete_entry(
        self,
        entry_id: str,
        act_id: str | None = None,
    ) -> bool:
        """Delete a learned knowledge entry.

        Returns:
            True if deleted, False if not found
        """
        kb = self._store.load_learned(act_id)

        original_count = len(kb.entries)
        kb.entries = [e for e in kb.entries if e.entry_id != entry_id]

        if len(kb.entries) < original_count:
            self._store.save_learned(kb)
            return True
        return False

    def get_stats(self, act_id: str | None = None) -> KnowledgeStats:
        """Get statistics about learned knowledge.

        Args:
            act_id: Filter by act (None for play level)

        Returns:
            KnowledgeStats with counts by category
        """
        kb = self._store.load_learned(act_id)

        counts = {
            "fact": 0,
            "lesson": 0,
            "decision": 0,
            "preference": 0,
            "observation": 0,
        }

        for entry in kb.entries:
            counts[entry.category] = counts.get(entry.category, 0) + 1

        return KnowledgeStats(
            total_entries=len(kb.entries),
            facts=counts["fact"],
            lessons=counts["lesson"],
            decisions=counts["decision"],
            preferences=counts["preference"],
            observations=counts["observation"],
        )

    def get_markdown(self, act_id: str | None = None) -> str:
        """Get learned knowledge as markdown for context injection.

        Args:
            act_id: Filter by act (None for play level)

        Returns:
            Markdown-formatted string
        """
        return self._store.get_learned_markdown(act_id)

    def clear(self, act_id: str | None = None) -> None:
        """Clear all learned knowledge for an act.

        Args:
            act_id: The act to clear (None for play level)
        """
        self._store.clear_learned(act_id)

    # --- Archive Integration ---

    def get_entry_count(self, act_id: str | None = None) -> int:
        """Get count of learned entries."""
        return self._store.get_learned_entry_count(act_id)

    def get_categories(self) -> list[str]:
        """Get list of valid categories."""
        return ["fact", "lesson", "decision", "preference", "observation"]

    def export_to_dict(self, act_id: str | None = None) -> dict[str, Any]:
        """Export all learned knowledge as a dict.

        Returns:
            Dict with entries grouped by category
        """
        kb = self._store.load_learned(act_id)

        by_category: dict[str, list[dict[str, Any]]] = {
            "facts": [],
            "lessons": [],
            "decisions": [],
            "preferences": [],
            "observations": [],
        }

        category_map = {
            "fact": "facts",
            "lesson": "lessons",
            "decision": "decisions",
            "preference": "preferences",
            "observation": "observations",
        }

        for entry in kb.entries:
            key = category_map.get(entry.category, "observations")
            by_category[key].append({
                "entry_id": entry.entry_id,
                "content": entry.content,
                "learned_at": entry.learned_at,
                "source_archive_id": entry.source_archive_id,
            })

        return {
            "act_id": act_id,
            "total_entries": len(kb.entries),
            "last_updated": kb.last_updated,
            **by_category,
        }

    def import_from_dict(
        self,
        data: dict[str, Any],
        act_id: str | None = None,
        merge: bool = True,
    ) -> int:
        """Import learned knowledge from a dict.

        Args:
            data: Export dict with category lists
            act_id: The act to import into
            merge: If True, merge with existing; if False, replace

        Returns:
            Number of entries imported
        """
        if not merge:
            self.clear(act_id)

        entries_to_add = []

        category_map = {
            "facts": "fact",
            "lessons": "lesson",
            "decisions": "decision",
            "preferences": "preference",
            "observations": "observation",
        }

        for key, category in category_map.items():
            for item in data.get(key, []):
                content = item.get("content")
                if content:
                    entries_to_add.append({
                        "category": category,
                        "content": content,
                    })

        added = self._store.add_learned_entries(
            entries=entries_to_add,
            act_id=act_id,
            deduplicate=True,
        )

        return len(added)
