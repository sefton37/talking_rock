from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alignment import get_head_sha, is_git_repo
from .commit_review import CommitReviewInput, CommitReviewer
from .db import Database
from .settings import settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CommitReviewEvent:
    event_id: str
    project_id: str
    repo_id: str
    repo_path: str
    commit_sha: str
    subject: str
    review_text: str


def poll_commits_and_review(
    *,
    db: Database,
    reviewer: CommitReviewer | None = None,
    limit_projects: int = 50,
) -> list[CommitReviewEvent]:
    """Detect new commits and run a code review for each (opt-in).

    This watches the HEAD SHA for repos linked to project charters.
    When HEAD changes, it reviews the new commit.

    Privacy:
    - Disabled by default.
    - When enabled with include_diff, it reads commit patches via `git show`.
    """

    if not settings.auto_review_commits:
        return []

    if not settings.auto_review_commits_include_diff:
        # User explicitly asked for "actual code reviewer". We still require explicit opt-in
        # to read diffs/patches, so this feature is a no-op unless they consent.
        return []

    now = _utcnow()
    cooldown = timedelta(seconds=max(1, settings.auto_review_commits_cooldown_seconds))

    reviewer = reviewer or CommitReviewer()

    out: list[CommitReviewEvent] = []
    projects = db.iter_project_charters()[: max(0, limit_projects)]

    for proj in projects:
        project_id = proj.get("project_id")
        repo_id = proj.get("repo_id")
        project_name = proj.get("project_name")
        if not isinstance(project_id, str) or not project_id:
            continue
        if not isinstance(repo_id, str) or not repo_id:
            continue
        if not isinstance(project_name, str) or not project_name:
            project_name = project_id

        repo_path_str = db.get_repo_path(repo_id=repo_id)
        if not repo_path_str:
            continue

        repo_path = Path(repo_path_str).resolve()
        if not is_git_repo(repo_path):
            continue

        state_key = f"commit_watch:last_head:{repo_id}"
        last_head = db.get_state(key=state_key)

        try:
            head = get_head_sha(repo_path)
        except Exception:
            continue

        # Initialize state without reviewing historical commits.
        if last_head is None:
            db.set_state(key=state_key, value=head)
            continue

        if head == last_head:
            continue

        # Simple cooldown per repo to avoid rapid double-reviews.
        cooldown_key = f"commit_watch:last_review_ts:{repo_id}"
        last_review_ts_raw = db.get_state(key=cooldown_key)
        if last_review_ts_raw:
            try:
                last_review_ts = datetime.fromisoformat(last_review_ts_raw)
                if now - last_review_ts < cooldown:
                    db.set_state(key=state_key, value=head)
                    continue
            except Exception:
                pass

        charter = db.get_project_charter(project_id=project_id)
        review_text = reviewer.review(
            CommitReviewInput(
                repo_path=repo_path,
                project_id=project_id,
                project_name=project_name,
                commit_sha=head,
                charter=charter,
            )
        )

        from .alignment import get_commit_subject

        subject = ""
        try:
            subject = get_commit_subject(repo_path, commit_sha=head)
        except Exception:
            subject = ""

        payload = {
            "kind": "commit_review",
            "project_id": project_id,
            "project_name": project_name,
            "repo_id": repo_id,
            "repo": str(repo_path),
            "commit_sha": head,
            "subject": subject,
            "review": review_text,
        }

        event_id = str(uuid.uuid4())
        db.insert_event(
            event_id=event_id,
            source="reos",
            kind="commit_review",
            ts=now.isoformat(),
            payload_metadata=json.dumps(payload),
            note=(f"Commit review: {head[:10]} {subject}" if subject else f"Commit review: {head[:10]}"),
        )

        db.set_state(key=state_key, value=head)
        db.set_state(key=cooldown_key, value=now.isoformat())

        out.append(
            CommitReviewEvent(
                event_id=event_id,
                project_id=project_id,
                repo_id=repo_id,
                repo_path=str(repo_path),
                commit_sha=head,
                subject=subject,
                review_text=review_text,
            )
        )

    return out
