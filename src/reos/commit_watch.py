from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alignment import get_default_repo_path, get_head_sha, is_git_repo
from .commit_review import CommitReviewInput, CommitReviewer
from .db import Database
from .settings import settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CommitReviewEvent:
    event_id: str
    repo_path: str
    commit_sha: str
    subject: str
    review_text: str


def poll_commits_and_review(
    *,
    db: Database,
    reviewer: CommitReviewer | None = None,
) -> list[CommitReviewEvent]:
    """Detect new commits and run a code review for each (opt-in).

    This watches the HEAD SHA for the configured repo.
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
    repo_path: Path | None = None
    state_repo = db.get_state(key="repo_path")
    if isinstance(state_repo, str) and state_repo.strip():
        candidate = Path(state_repo).resolve()
        if is_git_repo(candidate):
            repo_path = candidate

    if repo_path is None:
        repo_path = get_default_repo_path()
    if repo_path is None:
        return []

    repo_path = repo_path.resolve()
    if not is_git_repo(repo_path):
        return []

    repo_key = hashlib.sha256(str(repo_path).encode("utf-8")).hexdigest()[:16]
    state_key = f"commit_watch:last_head:{repo_key}"
    last_head = db.get_state(key=state_key)

    try:
        head = get_head_sha(repo_path)
    except Exception:
        return []

    # Initialize state without reviewing historical commits.
    if last_head is None:
        db.set_state(key=state_key, value=head)
        return []

    if head == last_head:
        return []

    # Simple cooldown per repo to avoid rapid double-reviews.
    cooldown_key = f"commit_watch:last_review_ts:{repo_key}"
    last_review_ts_raw = db.get_state(key=cooldown_key)
    if last_review_ts_raw:
        try:
            last_review_ts = datetime.fromisoformat(last_review_ts_raw)
            if now - last_review_ts < cooldown:
                db.set_state(key=state_key, value=head)
                return []
        except Exception:
            pass

    review_text = reviewer.review(CommitReviewInput(repo_path=repo_path, commit_sha=head))

    from .alignment import get_commit_subject

    subject = ""
    try:
        subject = get_commit_subject(repo_path, commit_sha=head)
    except Exception:
        subject = ""

    payload = {
        "kind": "commit_review",
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
            repo_path=str(repo_path),
            commit_sha=head,
            subject=subject,
            review_text=review_text,
        )
    )

    return out
