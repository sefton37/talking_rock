"""Tests for roadmap/charter alignment analysis helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from reos.alignment import extract_file_mentions, infer_active_repo_path
from reos.db import Database


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


def test_extract_file_mentions_basic() -> None:
    text = """
    See src/reos/db.py and src/reos/gui/main_window.py.
    Also check docs/tech-roadmap.md.
    """
    mentions = extract_file_mentions(text)
    assert "src/reos/db.py" in mentions
    assert "src/reos/gui/main_window.py" in mentions
    assert "docs/tech-roadmap.md" in mentions


def test_infer_active_repo_path_from_event(temp_db: Database) -> None:
    temp_db.insert_event(
        event_id="evt-1",
        source="git",
        kind="active_editor",
        ts="2025-12-17T00:00:00+00:00",
        payload_metadata=json.dumps({"workspaceFolder": "/tmp/myrepo", "uri": "file:///tmp/x.py"}),
        note=None,
    )

    # Git-first: repo path comes from settings/workspace, not event payloads.
    inferred = infer_active_repo_path(temp_db)
    assert inferred is not None
