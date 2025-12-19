from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from reos.commit_watch import poll_commits_and_review
from reos.commit_review import CommitReviewInput
from reos.db import get_db
from reos.settings import settings


class _FakeReviewer:
    def review(self, inp: CommitReviewInput) -> str:
        return f"Reviewed {inp.commit_sha} in {inp.project_name}"


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.mark.usefixtures("isolated_db_singleton")
def test_poll_commits_and_review_creates_event(
    temp_git_repo: Path,
    active_project_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = get_db()
    project_id = db.get_active_project_id()
    assert isinstance(project_id, str) and project_id
    repo_path = active_project_repo

    # Enable commit review + diff capture (explicit opt-in).
    monkeypatch.setattr(
        "reos.commit_watch.settings",
        replace(settings, auto_review_commits=True, auto_review_commits_include_diff=True),
    )

    # First poll should initialize last_head without reviewing.
    first = poll_commits_and_review(db=db, reviewer=_FakeReviewer())
    assert first == []

    # Create a new commit.
    target = repo_path / "src" / "reos" / "example.py"
    _write(target, "print('hello')\n")

    from tests.conftest import run_git  # type: ignore

    run_git(repo_path, ["add", str(target.relative_to(repo_path))])
    run_git(repo_path, ["commit", "-m", "Add hello"])

    reviews = poll_commits_and_review(db=db, reviewer=_FakeReviewer())
    assert len(reviews) == 1

    # Validate persisted event.
    evts = db.iter_events_recent(limit=20)
    commit_evts = [e for e in evts if e.get("kind") == "commit_review"]
    assert commit_evts, "expected a commit_review event"

    payload_raw = commit_evts[0].get("payload_metadata")
    assert isinstance(payload_raw, str)
    payload = json.loads(payload_raw)

    assert payload["kind"] == "commit_review"
    assert payload["project_id"] == project_id
    assert payload["repo"] == str(repo_path)
    assert isinstance(payload["commit_sha"], str) and payload["commit_sha"]
    assert "Reviewed" in payload["review"]
