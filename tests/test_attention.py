"""Tests for attention metrics and fragmentation detection."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reos.attention import (
    calculate_fragmentation,
    classify_attention_pattern,
    get_current_session_summary,
)
from reos.db import Database


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


def test_fragmentation_detection(temp_db: Database) -> None:
    """Test fragmentation score calculation from file switch events."""
    now = datetime.now(timezone.utc)

    # Insert simulated editor events: rapid file switching
    for i in range(10):
        file_uri = f"file:///project/file{i % 3}.py"  # Only 3 unique files
        ts = (now - timedelta(seconds=300 - i * 10)).isoformat()
        temp_db.insert_event(
            event_id=f"evt-{i}",
            source="vscode-extension",
            kind="active_editor",
            ts=ts,
            payload_metadata=json.dumps(
                {
                    "uri": file_uri,
                    "languageId": "python",
                    "projectName": "test-project",
                }
            ),
            note=None,
        )

    # Calculate fragmentation for last 5 minutes
    metrics = calculate_fragmentation(temp_db, time_window_seconds=300, switch_threshold=8)

    # 10 events across 3 files = 8-9 switches (fragmented)
    # The algorithm captures 8 switches (unique files - 1)
    assert metrics.switch_count >= 8
    assert metrics.fragmentation_score > 0.5  # Should be high
    assert "Fragmented" in metrics.explanation or "scattered" in metrics.explanation


def test_session_summary(temp_db: Database) -> None:
    """Test aggregating current session data."""
    now = datetime.now(timezone.utc)

    # Insert events across two projects
    projects = ["frontend", "backend"]
    for project in projects:
        for i in range(5):
            file_uri = f"file:///dev/{project}/file{i}.py"
            ts = (now - timedelta(seconds=600 - i * 30)).isoformat()
            temp_db.insert_event(
                event_id=f"{project}-evt-{i}",
                source="vscode-extension",
                kind="active_editor",
                ts=ts,
                payload_metadata=json.dumps(
                    {
                        "uri": file_uri,
                        "languageId": "python",
                        "projectName": project,
                        "editorChangeTime": ts,
                    }
                ),
                note=None,
            )

    # Add heartbeat events for time tracking
    for i in range(3):
        ts = (now - timedelta(seconds=300 - i * 60)).isoformat()
        temp_db.insert_event(
            event_id=f"heartbeat-{i}",
            source="vscode-extension",
            kind="heartbeat",
            ts=ts,
            payload_metadata=json.dumps(
                {
                    "projectName": "frontend",
                    "timeInFileSeconds": 120,
                    "fileHistoryCount": 5,
                }
            ),
            note=None,
        )

    summary = get_current_session_summary(temp_db)

    # Should have active status
    assert summary["status"] == "active"

    # Should have projects listed
    projects_list = summary.get("projects", [])
    assert len(projects_list) > 0

    # Should have fragmentation metric
    frag = summary.get("fragmentation", {})
    assert "score" in frag
    assert "explanation" in frag


def test_attention_classification(temp_db: Database) -> None:
    """Test high-level classification of attention patterns."""
    now = datetime.now(timezone.utc)

    # Insert events: single project, moderate switching
    for i in range(4):
        file_uri = f"file:///project/file{i}.py"
        ts = (now - timedelta(seconds=300 - i * 60)).isoformat()
        temp_db.insert_event(
            event_id=f"evt-{i}",
            source="vscode-extension",
            kind="active_editor",
            ts=ts,
            payload_metadata=json.dumps(
                {
                    "uri": file_uri,
                    "projectName": "single-project",
                    "languageId": "python",
                }
            ),
            note=None,
        )

    classification = classify_attention_pattern(temp_db)

    # Should classify the pattern
    assert "fragmentation" in classification
    assert "pattern" in classification
    assert "explanation" in classification

    # Single project → evolutionary
    assert "evolutionary" in classification["pattern"] or "mixed" in classification["pattern"]

    # Moderate switches → not extreme
    assert "coherent" in classification["fragmentation"] or "mixed" in classification["fragmentation"]
