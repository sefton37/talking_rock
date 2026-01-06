"""Tests for Code Mode diff utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import (
    CodeSandbox,
    DiffPreviewManager,
    DiffPreview,
    FileChange,
    ChangeType,
    Hunk,
    generate_diff,
    generate_edit_diff,
)


class TestGenerateDiff:
    """Tests for the generate_diff function."""

    def test_create_new_file(self) -> None:
        """Should generate diff for new file creation."""
        change = generate_diff("test.py", None, "print('hello')\n")

        assert change.change_type == ChangeType.CREATE
        assert change.path == "test.py"
        assert change.old_content is None
        assert change.new_content == "print('hello')\n"
        assert change.additions == 1
        assert change.deletions == 0

    def test_delete_file(self) -> None:
        """Should generate diff for file deletion."""
        change = generate_diff("test.py", "print('hello')\n", None)

        assert change.change_type == ChangeType.DELETE
        assert change.old_content == "print('hello')\n"
        assert change.new_content is None
        assert change.additions == 0
        assert change.deletions == 1

    def test_modify_file(self) -> None:
        """Should generate diff for file modification."""
        old = "line1\nline2\nline3\n"
        new = "line1\nmodified\nline3\n"

        change = generate_diff("test.py", old, new)

        assert change.change_type == ChangeType.MODIFY
        assert change.additions == 1
        assert change.deletions == 1
        assert len(change.hunks) == 1

    def test_no_changes(self) -> None:
        """Should handle identical content."""
        content = "same content\n"
        change = generate_diff("test.py", content, content)

        assert change.change_type == ChangeType.MODIFY
        assert change.additions == 0
        assert change.deletions == 0
        assert len(change.hunks) == 0

    def test_multiple_hunks(self) -> None:
        """Should generate multiple hunks for separate changes."""
        old = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n"
        new = "changed1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nchanged10\n"

        change = generate_diff("test.py", old, new, context_lines=1)

        assert change.additions == 2
        assert change.deletions == 2
        # Should have 2 hunks because changes are far apart
        assert len(change.hunks) == 2

    def test_sha256_hashes(self) -> None:
        """Should compute SHA256 hashes."""
        change = generate_diff("test.py", "old\n", "new\n")

        assert change.old_sha256 is not None
        assert change.new_sha256 is not None
        assert len(change.old_sha256) == 16  # Truncated to 16 chars
        assert len(change.new_sha256) == 16

    def test_binary_detection(self) -> None:
        """Should detect binary content."""
        binary_content = "normal\x00binary\x00content"
        change = generate_diff("test.bin", None, binary_content)

        assert change.binary is True
        assert change.diff_text == "Binary file changed"


class TestGenerateEditDiff:
    """Tests for the generate_edit_diff function."""

    def test_simple_edit(self) -> None:
        """Should generate diff for find/replace edit."""
        old_content = "def foo():\n    return 'old'\n"

        change = generate_edit_diff("test.py", old_content, "'old'", "'new'")

        assert change.change_type == ChangeType.MODIFY
        assert "'new'" in change.new_content
        assert change.additions == 1
        assert change.deletions == 1

    def test_edit_first_occurrence_only(self) -> None:
        """Should only replace first occurrence."""
        old_content = "hello world hello world\n"

        change = generate_edit_diff("test.py", old_content, "hello", "goodbye")

        assert change.new_content == "goodbye world hello world\n"


class TestHunk:
    """Tests for the Hunk dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        hunk = Hunk(
            old_start=1,
            old_count=3,
            new_start=1,
            new_count=4,
            lines=["-old", "+new", " context"],
            header="@@ -1,3 +1,4 @@",
        )

        d = hunk.to_dict()

        assert d["old_start"] == 1
        assert d["old_count"] == 3
        assert d["lines"] == ["-old", "+new", " context"]


class TestFileChange:
    """Tests for the FileChange dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        change = FileChange(
            path="test.py",
            change_type=ChangeType.CREATE,
            new_content="print('hello')\n",
            additions=1,
            deletions=0,
        )

        d = change.to_dict()

        assert d["path"] == "test.py"
        assert d["change_type"] == "create"
        assert d["additions"] == 1


class TestDiffPreview:
    """Tests for the DiffPreview dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        preview = DiffPreview(
            preview_id="abc123",
            changes=[
                FileChange(path="a.py", change_type=ChangeType.CREATE, additions=5),
                FileChange(path="b.py", change_type=ChangeType.MODIFY, additions=3, deletions=2),
            ],
            total_additions=8,
            total_deletions=2,
            total_files=2,
        )

        d = preview.to_dict()

        assert d["preview_id"] == "abc123"
        assert d["total_additions"] == 8
        assert d["total_deletions"] == 2
        assert d["total_files"] == 2
        assert len(d["changes"]) == 2


class TestDiffPreviewManager:
    """Tests for the DiffPreviewManager class."""

    def test_add_create(self, temp_git_repo: Path) -> None:
        """Should add a create change."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        change = manager.add_create("new_file.py", "print('new')\n")

        assert change.change_type == ChangeType.CREATE
        assert change.path == "new_file.py"

    def test_add_write_existing_file(self, temp_git_repo: Path) -> None:
        """Should add a write change for existing file."""
        sandbox = CodeSandbox(temp_git_repo)
        # Create a file first
        sandbox.write_file("existing.py", "original content\n")

        manager = DiffPreviewManager(sandbox)
        change = manager.add_write("existing.py", "new content\n")

        assert change.change_type == ChangeType.MODIFY
        assert change.old_content == "original content\n"

    def test_add_edit(self, temp_git_repo: Path) -> None:
        """Should add an edit change."""
        sandbox = CodeSandbox(temp_git_repo)
        sandbox.write_file("edit_me.py", "def foo(): pass\n")

        manager = DiffPreviewManager(sandbox)
        change = manager.add_edit("edit_me.py", "pass", "return 42")

        assert change.change_type == ChangeType.MODIFY
        assert "return 42" in change.new_content

    def test_add_delete(self, temp_git_repo: Path) -> None:
        """Should add a delete change."""
        sandbox = CodeSandbox(temp_git_repo)
        sandbox.write_file("delete_me.py", "to be deleted\n")

        manager = DiffPreviewManager(sandbox)
        change = manager.add_delete("delete_me.py")

        assert change.change_type == ChangeType.DELETE

    def test_get_preview(self, temp_git_repo: Path) -> None:
        """Should get preview with all changes."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("a.py", "print('a')\n")
        manager.add_create("b.py", "print('b')\n")

        preview = manager.get_preview()

        assert preview.total_files == 2
        assert preview.total_additions == 2
        assert preview.preview_id != ""

    def test_apply_all(self, temp_git_repo: Path) -> None:
        """Should apply all pending changes."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("applied.py", "print('applied')\n")

        applied = manager.apply_all()

        assert "applied.py" in applied
        assert sandbox.read_file("applied.py") == "print('applied')\n"

    def test_apply_file(self, temp_git_repo: Path) -> None:
        """Should apply single file change."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("one.py", "print('one')\n")
        manager.add_create("two.py", "print('two')\n")

        result = manager.apply_file("one.py")

        assert result is True
        assert sandbox.read_file("one.py") == "print('one')\n"
        # two.py should not exist yet
        assert not (temp_git_repo / "two.py").exists()

    def test_reject_file(self, temp_git_repo: Path) -> None:
        """Should reject single file change."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("keep.py", "print('keep')\n")
        manager.add_create("reject.py", "print('reject')\n")

        result = manager.reject_file("reject.py")

        assert result is True
        # Only keep.py should be in preview now
        preview = manager.get_preview()
        assert preview.total_files == 1

    def test_reject_all(self, temp_git_repo: Path) -> None:
        """Should reject all changes."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("a.py", "print('a')\n")
        manager.add_create("b.py", "print('b')\n")

        manager.reject_all()

        preview = manager.get_preview()
        assert preview.total_files == 0

    def test_clear(self, temp_git_repo: Path) -> None:
        """Should clear all pending changes."""
        sandbox = CodeSandbox(temp_git_repo)
        manager = DiffPreviewManager(sandbox)

        manager.add_create("temp.py", "print('temp')\n")
        manager.clear()

        preview = manager.get_preview()
        assert preview.total_files == 0

    def test_delete_change_applied(self, temp_git_repo: Path) -> None:
        """Should delete file when applying delete change."""
        sandbox = CodeSandbox(temp_git_repo)
        sandbox.write_file("to_delete.py", "delete me\n")

        manager = DiffPreviewManager(sandbox)
        manager.add_delete("to_delete.py")
        manager.apply_all()

        assert not (temp_git_repo / "to_delete.py").exists()
