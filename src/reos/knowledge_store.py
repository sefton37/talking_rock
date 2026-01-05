"""Knowledge Store - Persistent AI memory from conversations.

Handles:
- Archives: Full conversation storage for search
- Learned KB: Extracted facts/lessons/observations per Act
- Deduplication: Prevent redundant knowledge entries
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Archive:
    """A saved conversation archive."""

    archive_id: str
    act_id: str | None  # None = Play level
    title: str
    created_at: str  # ISO timestamp of first message
    archived_at: str  # ISO timestamp when archived
    message_count: int
    messages: list[dict[str, Any]]
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive_id": self.archive_id,
            "act_id": self.act_id,
            "title": self.title,
            "created_at": self.created_at,
            "archived_at": self.archived_at,
            "message_count": self.message_count,
            "messages": self.messages,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Archive:
        return cls(
            archive_id=data["archive_id"],
            act_id=data.get("act_id"),
            title=data["title"],
            created_at=data["created_at"],
            archived_at=data["archived_at"],
            message_count=data["message_count"],
            messages=data["messages"],
            summary=data.get("summary", ""),
        )


@dataclass
class LearnedEntry:
    """A single learned fact/lesson/observation."""

    entry_id: str
    category: str  # "fact", "lesson", "decision", "preference", "observation"
    content: str
    learned_at: str  # ISO timestamp
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
    def from_dict(cls, data: dict[str, Any]) -> LearnedEntry:
        return cls(
            entry_id=data["entry_id"],
            category=data["category"],
            content=data["content"],
            learned_at=data["learned_at"],
            source_archive_id=data.get("source_archive_id"),
        )


@dataclass
class LearnedKnowledge:
    """Collection of learned entries for an Act."""

    act_id: str | None  # None = Play level
    entries: list[LearnedEntry] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "act_id": self.act_id,
            "entries": [e.to_dict() for e in self.entries],
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnedKnowledge:
        return cls(
            act_id=data.get("act_id"),
            entries=[LearnedEntry.from_dict(e) for e in data.get("entries", [])],
            last_updated=data.get("last_updated", ""),
        )

    def to_markdown(self) -> str:
        """Render as markdown for context injection."""
        if not self.entries:
            return ""

        sections: dict[str, list[str]] = {
            "fact": [],
            "lesson": [],
            "decision": [],
            "preference": [],
            "observation": [],
        }

        for entry in self.entries:
            date = entry.learned_at[:10] if entry.learned_at else "unknown"
            sections.setdefault(entry.category, []).append(
                f"- [{date}] {entry.content}"
            )

        lines = ["# Learned Knowledge", ""]

        category_titles = {
            "fact": "Facts",
            "lesson": "Lessons",
            "decision": "Decisions",
            "preference": "Preferences",
            "observation": "Observations",
        }

        for cat, title in category_titles.items():
            if sections.get(cat):
                lines.append(f"## {title}")
                lines.extend(sections[cat])
                lines.append("")

        return "\n".join(lines)


class KnowledgeStore:
    """Manages archives and learned knowledge storage."""

    def __init__(self, data_root: Path | None = None):
        if data_root is None:
            from .play_fs import play_root
            data_root = play_root()
        self._root = data_root

    def _archives_dir(self, act_id: str | None) -> Path:
        """Get archives directory for an act (or play level)."""
        if act_id:
            return self._root / "acts" / act_id / "archives"
        return self._root / "archives"

    def _learned_path(self, act_id: str | None) -> Path:
        """Get learned knowledge file path for an act (or play level)."""
        if act_id:
            return self._root / "acts" / act_id / "learned.json"
        return self._root / "learned.json"

    def _ensure_dirs(self, act_id: str | None) -> None:
        """Ensure directories exist."""
        self._archives_dir(act_id).mkdir(parents=True, exist_ok=True)

    # --- Archive Operations ---

    def save_archive(
        self,
        *,
        messages: list[dict[str, Any]],
        act_id: str | None = None,
        title: str | None = None,
        summary: str = "",
    ) -> Archive:
        """Save a conversation as an archive."""
        self._ensure_dirs(act_id)

        archive_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()

        # Auto-generate title from first user message if not provided
        if not title:
            for msg in messages:
                if msg.get("role") == "user":
                    content = str(msg.get("content", ""))[:50]
                    title = content + ("..." if len(content) >= 50 else "")
                    break
            if not title:
                title = f"Conversation {now[:10]}"

        # Get creation time from first message or now
        created_at = now
        if messages:
            first_ts = messages[0].get("created_at") or messages[0].get("timestamp")
            if first_ts:
                created_at = first_ts

        archive = Archive(
            archive_id=archive_id,
            act_id=act_id,
            title=title,
            created_at=created_at,
            archived_at=now,
            message_count=len(messages),
            messages=messages,
            summary=summary,
        )

        path = self._archives_dir(act_id) / f"{archive_id}.json"
        path.write_text(json.dumps(archive.to_dict(), indent=2), encoding="utf-8")

        logger.info("Saved archive %s with %d messages", archive_id, len(messages))
        return archive

    def list_archives(self, act_id: str | None = None) -> list[Archive]:
        """List all archives for an act (or play level)."""
        archives_dir = self._archives_dir(act_id)
        if not archives_dir.exists():
            return []

        archives = []
        for path in archives_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                archives.append(Archive.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load archive %s: %s", path, e)

        # Sort by archived_at descending (newest first)
        archives.sort(key=lambda a: a.archived_at, reverse=True)
        return archives

    def get_archive(self, archive_id: str, act_id: str | None = None) -> Archive | None:
        """Get a specific archive by ID."""
        path = self._archives_dir(act_id) / f"{archive_id}.json"
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Archive.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load archive %s: %s", archive_id, e)
            return None

    def delete_archive(self, archive_id: str, act_id: str | None = None) -> bool:
        """Delete an archive."""
        path = self._archives_dir(act_id) / f"{archive_id}.json"
        if path.exists():
            path.unlink()
            logger.info("Deleted archive %s", archive_id)
            return True
        return False

    def search_archives(
        self,
        query: str,
        act_id: str | None = None,
        limit: int = 20,
    ) -> list[Archive]:
        """Search archives by text content."""
        query_lower = query.lower()
        results = []

        for archive in self.list_archives(act_id):
            # Search in title and messages
            if query_lower in archive.title.lower():
                results.append(archive)
                continue

            for msg in archive.messages:
                content = str(msg.get("content", "")).lower()
                if query_lower in content:
                    results.append(archive)
                    break

            if len(results) >= limit:
                break

        return results

    # --- Learned Knowledge Operations ---

    def load_learned(self, act_id: str | None = None) -> LearnedKnowledge:
        """Load learned knowledge for an act (or play level)."""
        path = self._learned_path(act_id)
        if not path.exists():
            return LearnedKnowledge(act_id=act_id)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return LearnedKnowledge.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load learned KB: %s", e)
            return LearnedKnowledge(act_id=act_id)

    def save_learned(self, kb: LearnedKnowledge) -> None:
        """Save learned knowledge."""
        path = self._learned_path(kb.act_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        kb.last_updated = datetime.now().isoformat()
        path.write_text(json.dumps(kb.to_dict(), indent=2), encoding="utf-8")
        logger.info("Saved learned KB with %d entries", len(kb.entries))

    def add_learned_entries(
        self,
        entries: list[dict[str, str]],
        act_id: str | None = None,
        source_archive_id: str | None = None,
        deduplicate: bool = True,
    ) -> list[LearnedEntry]:
        """Add new learned entries with optional deduplication.

        Args:
            entries: List of {"category": ..., "content": ...} dicts
            act_id: Act to add to (None = Play level)
            source_archive_id: Archive this knowledge came from
            deduplicate: If True, skip entries similar to existing ones

        Returns:
            List of actually added entries
        """
        kb = self.load_learned(act_id)
        now = datetime.now().isoformat()

        existing_contents = {e.content.lower().strip() for e in kb.entries}
        added = []

        for entry_data in entries:
            content = entry_data.get("content", "").strip()
            category = entry_data.get("category", "observation")

            if not content:
                continue

            # Simple deduplication: exact match (case-insensitive)
            if deduplicate and content.lower() in existing_contents:
                logger.debug("Skipping duplicate: %s", content[:50])
                continue

            entry = LearnedEntry(
                entry_id=uuid.uuid4().hex[:8],
                category=category,
                content=content,
                learned_at=now,
                source_archive_id=source_archive_id,
            )
            kb.entries.append(entry)
            existing_contents.add(content.lower())
            added.append(entry)

        if added:
            self.save_learned(kb)
            logger.info("Added %d new learned entries", len(added))

        return added

    def get_learned_markdown(self, act_id: str | None = None) -> str:
        """Get learned knowledge as markdown for context injection."""
        kb = self.load_learned(act_id)
        return kb.to_markdown()

    def get_learned_entry_count(self, act_id: str | None = None) -> int:
        """Get count of learned entries."""
        kb = self.load_learned(act_id)
        return len(kb.entries)

    def clear_learned(self, act_id: str | None = None) -> None:
        """Clear all learned knowledge for an act."""
        path = self._learned_path(act_id)
        if path.exists():
            path.unlink()
            logger.info("Cleared learned KB for act %s", act_id or "play")
