from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from reos.db import Database
from reos.errors import record_error


@pytest.fixture
def temp_db() -> Iterator[Database]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


def test_record_error_inserts_event(temp_db: Database) -> None:
    event_id = record_error(
        source="reos",
        operation="unit_test",
        exc=RuntimeError("boom"),
        context={"k": "v"},
        db=temp_db,
        dedupe_window_seconds=0,
    )

    assert isinstance(event_id, str)

    rows = temp_db.iter_events_recent(limit=5)
    assert len(rows) == 1
    assert rows[0]["kind"] == "error"
    assert rows[0]["source"] == "reos"

    payload_raw = rows[0]["payload_metadata"]
    assert isinstance(payload_raw, str)
    payload = json.loads(payload_raw)
    assert payload["kind"] == "error"
    assert payload["operation"] == "unit_test"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert payload["context"] == {"k": "v"}
    assert isinstance(payload["signature"], str)


def test_record_error_dedupes_within_window(temp_db: Database) -> None:
    first = record_error(
        source="reos",
        operation="unit_test_dedupe",
        exc=ValueError("same"),
        db=temp_db,
        dedupe_window_seconds=3600,
    )
    second = record_error(
        source="reos",
        operation="unit_test_dedupe",
        exc=ValueError("same"),
        db=temp_db,
        dedupe_window_seconds=3600,
    )

    assert first is not None
    assert second is None

    rows = temp_db.iter_events_recent(limit=10)
    assert len(rows) == 1


def test_poll_git_repo_reports_error(monkeypatch) -> None:
    from reos import git_poll

    monkeypatch.setattr(git_poll, "get_default_repo_path", lambda: Path("/tmp/repo"))

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("git failed")

    monkeypatch.setattr(git_poll, "get_git_summary", _boom)

    called: dict[str, object] = {}

    def _record_error(**kwargs):  # noqa: ANN001
        called["ok"] = True
        return None

    monkeypatch.setattr(git_poll, "record_error", _record_error)

    res = git_poll.poll_git_repo()
    assert res["status"] == "error"
    assert "message" in res
    assert called.get("ok") is True
