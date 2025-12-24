from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reos.models import Event
from reos.storage import append_event


def test_alignment_trigger_payload_includes_project_and_paths(
    active_project_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = active_project_repo

    # Create enough unmapped tracked changes to force an alignment_trigger.
    created: list[Path] = []
    for i in range(6):
        p = repo / "src" / "reos" / f"unmapped_payload_{i}.py"
        p.write_text(f"# unmapped payload {i}\n", encoding="utf-8")
        created.append(p)

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add unmapped payload files"],
        check=True,
        capture_output=True,
        text=True,
    )

    for p in created:
        p.write_text(p.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    import reos.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_default_repo_path", lambda: repo)

    append_event(Event(source="test", ts=datetime.now(UTC), payload_metadata={"kind": "smoke"}))

    from reos.db import get_db

    rows = get_db().iter_events_recent(limit=50)
    triggers = [r for r in rows if r.get("kind") == "alignment_trigger"]
    assert len(triggers) == 1

    payload_raw = triggers[0].get("payload_metadata")
    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}

    assert payload.get("kind") == "alignment_trigger"
    assert payload.get("project_id") == "proj-test-1"

    repo_path = payload.get("repo")
    assert isinstance(repo_path, str)
    assert str(repo) in repo_path

    roadmap = payload.get("roadmap")
    charter = payload.get("charter")
    assert isinstance(roadmap, dict)
    assert isinstance(charter, dict)
    assert "docs/tech-roadmap.md" in str(roadmap.get("path"))
    assert "ReOS_charter.md" in str(charter.get("path"))

    signals = payload.get("signals")
    assert isinstance(signals, dict)
    assert int(signals.get("unmapped_changed_files_count")) >= 5

    examples = payload.get("examples")
    assert isinstance(examples, dict)
    unmapped_examples = examples.get("unmapped_changed_files")
    assert isinstance(unmapped_examples, list)
    assert any("unmapped_payload_" in str(x) for x in unmapped_examples)
