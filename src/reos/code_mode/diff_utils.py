"""Diff utilities for Code Mode.

Generates unified diffs for file changes, enabling the diff preview UI
to show exactly what will change before applying.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.sandbox import CodeSandbox


class ChangeType(Enum):
    """Type of file change."""

    CREATE = "create"      # New file
    MODIFY = "modify"      # Edit existing file
    DELETE = "delete"      # Remove file
    RENAME = "rename"      # Rename/move file


@dataclass
class Hunk:
    """A single diff hunk (a contiguous block of changes)."""

    old_start: int       # Starting line in old file
    old_count: int       # Number of lines from old file
    new_start: int       # Starting line in new file
    new_count: int       # Number of lines in new file
    lines: list[str]     # Diff lines (prefixed with +, -, or space)
    header: str = ""     # @@ -old_start,old_count +new_start,new_count @@

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "old_start": self.old_start,
            "old_count": self.old_count,
            "new_start": self.new_start,
            "new_count": self.new_count,
            "lines": self.lines,
            "header": self.header,
        }


@dataclass
class FileChange:
    """A single file change with diff information."""

    path: str                          # Relative path within repo
    change_type: ChangeType
    old_content: str | None = None     # Content before change (None for create)
    new_content: str | None = None     # Content after change (None for delete)
    hunks: list[Hunk] = field(default_factory=list)
    diff_text: str = ""                # Full unified diff text
    old_sha256: str | None = None      # Hash of old content
    new_sha256: str | None = None      # Hash of new content
    additions: int = 0                 # Lines added
    deletions: int = 0                 # Lines removed
    binary: bool = False               # Is this a binary file?

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": self.path,
            "change_type": self.change_type.value,
            "hunks": [h.to_dict() for h in self.hunks],
            "diff_text": self.diff_text,
            "old_sha256": self.old_sha256,
            "new_sha256": self.new_sha256,
            "additions": self.additions,
            "deletions": self.deletions,
            "binary": self.binary,
        }


@dataclass
class DiffPreview:
    """Preview of all pending changes."""

    changes: list[FileChange] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0
    total_files: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    preview_id: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "preview_id": self.preview_id,
            "changes": [c.to_dict() for c in self.changes],
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "total_files": self.total_files,
            "created_at": self.created_at.isoformat(),
        }


def _compute_sha256(content: str | None) -> str | None:
    """Compute SHA256 hash of content."""
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _is_binary(content: str) -> bool:
    """Check if content appears to be binary."""
    # Check for null bytes
    if "\x00" in content:
        return True
    # Check if too many non-printable characters
    non_printable = sum(1 for c in content[:1000] if ord(c) < 32 and c not in "\n\r\t")
    return non_printable > 50


def _parse_hunks(diff_lines: list[str]) -> list[Hunk]:
    """Parse unified diff lines into hunks."""
    hunks = []
    current_hunk: Hunk | None = None

    for line in diff_lines:
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            if current_hunk:
                hunks.append(current_hunk)

            parts = line.split("@@")
            if len(parts) >= 2:
                range_info = parts[1].strip()
                # Parse -old_start,old_count +new_start,new_count
                old_range = "1,0"
                new_range = "1,0"
                for part in range_info.split():
                    if part.startswith("-"):
                        old_range = part[1:]
                    elif part.startswith("+"):
                        new_range = part[1:]

                def parse_range(r: str) -> tuple[int, int]:
                    if "," in r:
                        start, count = r.split(",")
                        return int(start), int(count)
                    return int(r), 1

                old_start, old_count = parse_range(old_range)
                new_start, new_count = parse_range(new_range)

                current_hunk = Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=[],
                    header=line,
                )

        elif current_hunk is not None:
            # Skip --- and +++ header lines
            if line.startswith("---") or line.startswith("+++"):
                continue
            current_hunk.lines.append(line)

    if current_hunk:
        hunks.append(current_hunk)

    return hunks


def generate_diff(
    path: str,
    old_content: str | None,
    new_content: str | None,
    context_lines: int = 3,
) -> FileChange:
    """Generate a diff between old and new content.

    Args:
        path: File path (for display)
        old_content: Original content (None for new files)
        new_content: New content (None for deletions)
        context_lines: Number of context lines around changes

    Returns:
        FileChange with diff information
    """
    # Determine change type
    if old_content is None and new_content is not None:
        change_type = ChangeType.CREATE
    elif old_content is not None and new_content is None:
        change_type = ChangeType.DELETE
    elif old_content is not None and new_content is not None:
        change_type = ChangeType.MODIFY
    else:
        # Both None - shouldn't happen
        change_type = ChangeType.MODIFY

    # Check for binary
    if (old_content and _is_binary(old_content)) or (new_content and _is_binary(new_content)):
        return FileChange(
            path=path,
            change_type=change_type,
            old_content=old_content,
            new_content=new_content,
            binary=True,
            old_sha256=_compute_sha256(old_content),
            new_sha256=_compute_sha256(new_content),
            diff_text="Binary file changed",
        )

    # Split into lines
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)

    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    ))

    # Count additions and deletions
    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    # Parse hunks
    hunks = _parse_hunks(diff_lines)

    return FileChange(
        path=path,
        change_type=change_type,
        old_content=old_content,
        new_content=new_content,
        hunks=hunks,
        diff_text="".join(diff_lines),
        old_sha256=_compute_sha256(old_content),
        new_sha256=_compute_sha256(new_content),
        additions=additions,
        deletions=deletions,
    )


def generate_edit_diff(
    path: str,
    old_content: str,
    old_str: str,
    new_str: str,
) -> FileChange:
    """Generate a diff for an edit operation (find/replace).

    Args:
        path: File path
        old_content: Current file content
        old_str: String to find
        new_str: String to replace with

    Returns:
        FileChange with diff information
    """
    new_content = old_content.replace(old_str, new_str, 1)
    return generate_diff(path, old_content, new_content)


class DiffPreviewManager:
    """Manages diff previews for pending changes."""

    def __init__(self, sandbox: CodeSandbox) -> None:
        self.sandbox = sandbox
        self._pending_changes: dict[str, FileChange] = {}  # path -> change
        self._preview_id: str = ""

    def clear(self) -> None:
        """Clear all pending changes."""
        self._pending_changes = {}
        self._preview_id = ""

    def add_create(self, path: str, content: str) -> FileChange:
        """Add a file creation to the preview."""
        change = generate_diff(path, None, content)
        self._pending_changes[path] = change
        return change

    def add_edit(self, path: str, old_str: str, new_str: str) -> FileChange:
        """Add a file edit to the preview."""
        # Get current content from sandbox
        try:
            old_content = self.sandbox.read_file(path)
        except Exception:
            old_content = ""

        change = generate_edit_diff(path, old_content, old_str, new_str)
        self._pending_changes[path] = change
        return change

    def add_write(self, path: str, new_content: str) -> FileChange:
        """Add a file write to the preview."""
        # Get current content from sandbox
        try:
            old_content = self.sandbox.read_file(path)
        except Exception:
            old_content = None

        change = generate_diff(path, old_content, new_content)
        self._pending_changes[path] = change
        return change

    def add_delete(self, path: str) -> FileChange:
        """Add a file deletion to the preview."""
        try:
            old_content = self.sandbox.read_file(path)
        except Exception:
            old_content = ""

        change = generate_diff(path, old_content, None)
        self._pending_changes[path] = change
        return change

    def get_preview(self) -> DiffPreview:
        """Get the current preview of all changes."""
        changes = list(self._pending_changes.values())

        total_additions = sum(c.additions for c in changes)
        total_deletions = sum(c.deletions for c in changes)

        # Generate preview ID from content hashes
        import uuid
        self._preview_id = str(uuid.uuid4())[:8]

        return DiffPreview(
            preview_id=self._preview_id,
            changes=changes,
            total_additions=total_additions,
            total_deletions=total_deletions,
            total_files=len(changes),
        )

    def apply_all(self) -> list[str]:
        """Apply all pending changes.

        Returns:
            List of paths that were changed.
        """
        applied = []
        for path, change in self._pending_changes.items():
            if change.change_type == ChangeType.DELETE:
                self.sandbox.delete_file(path)
            elif change.new_content is not None:
                self.sandbox.write_file(path, change.new_content)
            applied.append(path)

        self.clear()
        return applied

    def apply_file(self, path: str) -> bool:
        """Apply change for a specific file.

        Returns:
            True if the change was applied.
        """
        if path not in self._pending_changes:
            return False

        change = self._pending_changes[path]
        if change.change_type == ChangeType.DELETE:
            self.sandbox.delete_file(path)
        elif change.new_content is not None:
            self.sandbox.write_file(path, change.new_content)

        del self._pending_changes[path]
        return True

    def reject_file(self, path: str) -> bool:
        """Reject (remove from preview) a specific file's changes.

        Returns:
            True if the change was removed.
        """
        if path not in self._pending_changes:
            return False
        del self._pending_changes[path]
        return True

    def reject_all(self) -> None:
        """Reject all pending changes."""
        self.clear()
