from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess

import pytest

from reos.models import Event
from reos.storage import append_event


def _count_kind(rows: list[dict[str, object]], kind: str) -> int:
    return sum(1 for r in rows if r.get("kind") == kind)


def test_alignment_trigger_cooldown_boundary_is_deterministic(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Create enough unmapped changed files to trigger alignment_trigger.
    # Make them tracked so we don't depend on untracked visibility.
    paths: list[Path] = []
    for i in range(6):
        p = repo / "src" / "reos" / f"unmapped_{i}.py"
        p.write_text(f"# unmapped {i}\n", encoding="utf-8")
        paths.append(p)

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add unmapped files"],
        check=True,
        capture_output=True,
        text=True,
    )

    for p in paths:
        p.write_text(p.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    import reos.storage as storage_mod
    import reos.settings as settings_mod

    monkeypatch.setattr(storage_mod, "get_default_repo_path", lambda: repo)

    # Set cooldown = 1 minute (storage enforces >= 1 minute).
    monkeypatch.setattr(
        storage_mod,
        "settings",
        replace(settings_mod.settings, review_trigger_cooldown_minutes=1),
    )

    t0 = datetime(2025, 12, 19, 0, 0, 0, tzinfo=UTC)

    # First append at t0 => should trigger once.
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t0)
    append_event(Event(source="test", ts=t0, payload_metadata={"kind": "evt"}))

    from reos.db import get_db

    db = get_db()
    rows1 = db.iter_events_recent(limit=50)
    assert _count_kind(rows1, "alignment_trigger") == 1

    # Still within cooldown (t0 + 59s) => no new trigger.
    t1 = t0 + timedelta(seconds=59)
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t1)
    append_event(Event(source="test", ts=t1, payload_metadata={"kind": "evt2"}))

    rows2 = db.iter_events_recent(limit=50)
    assert _count_kind(rows2, "alignment_trigger") == 1

    # Past cooldown (t0 + 61s) => second trigger.
    t2 = t0 + timedelta(seconds=61)
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t2)
    append_event(Event(source="test", ts=t2, payload_metadata={"kind": "evt3"}))

    rows3 = db.iter_events_recent(limit=50)
    assert _count_kind(rows3, "alignment_trigger") == 2
