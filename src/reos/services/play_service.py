"""Play Service - The Play file and hierarchy management.

Wraps play_fs.py to provide a unified interface for managing
The Play hierarchy (Acts, Scenes, Beats, KB files, Attachments).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .. import play_fs

logger = logging.getLogger(__name__)


@dataclass
class ActInfo:
    """Information about an Act."""

    act_id: str
    title: str
    active: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "act_id": self.act_id,
            "title": self.title,
            "active": self.active,
            "notes": self.notes,
        }

    @classmethod
    def from_play_fs(cls, act: play_fs.Act) -> ActInfo:
        return cls(
            act_id=act.act_id,
            title=act.title,
            active=act.active,
            notes=act.notes,
        )


@dataclass
class SceneInfo:
    """Information about a Scene."""

    scene_id: str
    title: str
    intent: str = ""
    status: str = ""
    time_horizon: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "intent": self.intent,
            "status": self.status,
            "time_horizon": self.time_horizon,
            "notes": self.notes,
        }

    @classmethod
    def from_play_fs(cls, scene: play_fs.Scene) -> SceneInfo:
        return cls(
            scene_id=scene.scene_id,
            title=scene.title,
            intent=scene.intent,
            status=scene.status,
            time_horizon=scene.time_horizon,
            notes=scene.notes,
        )


@dataclass
class BeatInfo:
    """Information about a Beat."""

    beat_id: str
    title: str
    status: str = ""
    notes: str = ""
    link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "title": self.title,
            "status": self.status,
            "notes": self.notes,
            "link": self.link,
        }

    @classmethod
    def from_play_fs(cls, beat: play_fs.Beat) -> BeatInfo:
        return cls(
            beat_id=beat.beat_id,
            title=beat.title,
            status=beat.status,
            notes=beat.notes,
            link=beat.link,
        )


@dataclass
class AttachmentInfo:
    """Information about a file attachment."""

    attachment_id: str
    file_path: str
    file_name: str
    file_type: str
    added_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "added_at": self.added_at,
        }

    @classmethod
    def from_play_fs(cls, att: play_fs.FileAttachment) -> AttachmentInfo:
        return cls(
            attachment_id=att.attachment_id,
            file_path=att.file_path,
            file_name=att.file_name,
            file_type=att.file_type,
            added_at=att.added_at,
        )


class PlayService:
    """Unified service for The Play hierarchy management."""

    # --- Your Story (me.md) ---

    def read_story(self) -> str:
        """Read the user's story (me.md content)."""
        return play_fs.read_me_markdown()

    def write_story(self, content: str) -> bool:
        """Write the user's story.

        Args:
            content: The new story content

        Returns:
            True if successful
        """
        try:
            play_fs.write_me_markdown(content)
            return True
        except Exception as e:
            logger.error("Failed to write story: %s", e)
            return False

    # --- Acts ---

    def list_acts(self) -> tuple[list[ActInfo], str | None]:
        """List all acts and the active act ID.

        Returns:
            Tuple of (list of ActInfo, active_act_id or None)
        """
        acts, active_id = play_fs.list_acts()
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def create_act(self, title: str, notes: str = "") -> tuple[list[ActInfo], str]:
        """Create a new act.

        Args:
            title: Act title
            notes: Optional notes

        Returns:
            Tuple of (updated act list, new act_id)
        """
        acts, act_id = play_fs.create_act(title=title, notes=notes)
        return [ActInfo.from_play_fs(a) for a in acts], act_id

    def update_act(
        self,
        act_id: str,
        title: str | None = None,
        notes: str | None = None,
    ) -> tuple[list[ActInfo], str | None]:
        """Update an act's fields.

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.update_act(act_id=act_id, title=title, notes=notes)
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def set_active_act(self, act_id: str | None) -> tuple[list[ActInfo], str | None]:
        """Set the active act (or clear if None).

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.set_active_act_id(act_id=act_id)
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    # --- Scenes ---

    def list_scenes(self, act_id: str) -> list[SceneInfo]:
        """List scenes under an act."""
        scenes = play_fs.list_scenes(act_id=act_id)
        return [SceneInfo.from_play_fs(s) for s in scenes]

    def create_scene(
        self,
        act_id: str,
        title: str,
        intent: str = "",
        status: str = "",
        time_horizon: str = "",
        notes: str = "",
    ) -> list[SceneInfo]:
        """Create a new scene under an act.

        Returns:
            Updated list of scenes
        """
        scenes = play_fs.create_scene(
            act_id=act_id,
            title=title,
            intent=intent,
            status=status,
            time_horizon=time_horizon,
            notes=notes,
        )
        return [SceneInfo.from_play_fs(s) for s in scenes]

    def update_scene(
        self,
        act_id: str,
        scene_id: str,
        title: str | None = None,
        intent: str | None = None,
        status: str | None = None,
        time_horizon: str | None = None,
        notes: str | None = None,
    ) -> list[SceneInfo]:
        """Update a scene's fields.

        Returns:
            Updated list of scenes
        """
        scenes = play_fs.update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            intent=intent,
            status=status,
            time_horizon=time_horizon,
            notes=notes,
        )
        return [SceneInfo.from_play_fs(s) for s in scenes]

    # --- Beats ---

    def list_beats(self, act_id: str, scene_id: str) -> list[BeatInfo]:
        """List beats under a scene."""
        beats = play_fs.list_beats(act_id=act_id, scene_id=scene_id)
        return [BeatInfo.from_play_fs(b) for b in beats]

    def create_beat(
        self,
        act_id: str,
        scene_id: str,
        title: str,
        status: str = "",
        notes: str = "",
        link: str | None = None,
    ) -> list[BeatInfo]:
        """Create a new beat under a scene.

        Returns:
            Updated list of beats
        """
        beats = play_fs.create_beat(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            status=status,
            notes=notes,
            link=link,
        )
        return [BeatInfo.from_play_fs(b) for b in beats]

    def update_beat(
        self,
        act_id: str,
        scene_id: str,
        beat_id: str,
        title: str | None = None,
        status: str | None = None,
        notes: str | None = None,
        link: str | None = None,
    ) -> list[BeatInfo]:
        """Update a beat's fields.

        Returns:
            Updated list of beats
        """
        beats = play_fs.update_beat(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            title=title,
            status=status,
            notes=notes,
            link=link,
        )
        return [BeatInfo.from_play_fs(b) for b in beats]

    # --- Knowledge Base (KB) Files ---

    def list_kb_files(
        self,
        act_id: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[str]:
        """List KB files at the specified level.

        Returns:
            List of relative file paths
        """
        return play_fs.kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)

    def read_kb_file(
        self,
        act_id: str,
        path: str = "kb.md",
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> str:
        """Read a KB file.

        Args:
            act_id: The act ID
            path: Relative file path (default: kb.md)
            scene_id: Optional scene ID
            beat_id: Optional beat ID

        Returns:
            File content as string
        """
        return play_fs.kb_read(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
        )

    def preview_kb_write(
        self,
        act_id: str,
        path: str,
        text: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview a KB file write (diff, hashes).

        Returns:
            Dict with exists, sha256_current, sha256_new, diff
        """
        return play_fs.kb_write_preview(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
        )

    def apply_kb_write(
        self,
        act_id: str,
        path: str,
        text: str,
        expected_sha256: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply a KB file write with hash verification.

        Args:
            expected_sha256: SHA256 of current content (from preview)

        Returns:
            Dict with ok and sha256_current
        """
        return play_fs.kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256,
        )

    # --- Attachments ---

    def list_attachments(
        self,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """List attachments at the specified level.

        Args:
            act_id: None for Play-level attachments

        Returns:
            List of AttachmentInfo
        """
        attachments = play_fs.list_attachments(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    def add_attachment(
        self,
        file_path: str,
        file_name: str | None = None,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """Add a file attachment.

        Args:
            file_path: Absolute path to the file
            file_name: Optional display name
            act_id: None for Play-level

        Returns:
            Updated list of attachments
        """
        attachments = play_fs.add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            file_path=file_path,
            file_name=file_name,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    def remove_attachment(
        self,
        attachment_id: str,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """Remove a file attachment.

        Returns:
            Updated list of attachments
        """
        attachments = play_fs.remove_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            attachment_id=attachment_id,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    # --- Utility Methods ---

    def get_active_act_context(self) -> dict[str, Any] | None:
        """Get full context for the active act.

        Returns dict with act, scenes, beats hierarchy or None if no active act.
        """
        acts, active_id = self.list_acts()
        if not active_id:
            return None

        active_act = next((a for a in acts if a.act_id == active_id), None)
        if not active_act:
            return None

        scenes = self.list_scenes(active_id)
        scenes_with_beats = []
        for scene in scenes:
            beats = self.list_beats(active_id, scene.scene_id)
            scenes_with_beats.append({
                **scene.to_dict(),
                "beats": [b.to_dict() for b in beats],
            })

        return {
            "act": active_act.to_dict(),
            "scenes": scenes_with_beats,
        }

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search across all Play content.

        Searches story, act titles, scene titles/notes, beat titles/notes.

        Returns:
            List of matching items with type and content
        """
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Search story
        story = self.read_story()
        if query_lower in story.lower():
            results.append({
                "type": "story",
                "title": "Your Story",
                "snippet": self._extract_snippet(story, query_lower),
            })

        # Search acts
        acts, _ = self.list_acts()
        for act in acts:
            if query_lower in act.title.lower() or query_lower in act.notes.lower():
                results.append({
                    "type": "act",
                    "act_id": act.act_id,
                    "title": act.title,
                    "snippet": self._extract_snippet(
                        act.title + " " + act.notes, query_lower
                    ),
                })

            # Search scenes under this act
            scenes = self.list_scenes(act.act_id)
            for scene in scenes:
                if query_lower in scene.title.lower() or query_lower in scene.notes.lower():
                    results.append({
                        "type": "scene",
                        "act_id": act.act_id,
                        "scene_id": scene.scene_id,
                        "title": scene.title,
                        "snippet": self._extract_snippet(
                            scene.title + " " + scene.notes, query_lower
                        ),
                    })

                # Search beats under this scene
                beats = self.list_beats(act.act_id, scene.scene_id)
                for beat in beats:
                    if query_lower in beat.title.lower() or query_lower in beat.notes.lower():
                        results.append({
                            "type": "beat",
                            "act_id": act.act_id,
                            "scene_id": scene.scene_id,
                            "beat_id": beat.beat_id,
                            "title": beat.title,
                            "snippet": self._extract_snippet(
                                beat.title + " " + beat.notes, query_lower
                            ),
                        })

        return results

    def _extract_snippet(self, text: str, query: str, context: int = 50) -> str:
        """Extract a snippet around the query match."""
        idx = text.lower().find(query)
        if idx < 0:
            return text[:100] + "..." if len(text) > 100 else text

        start = max(0, idx - context)
        end = min(len(text), idx + len(query) + context)

        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet
