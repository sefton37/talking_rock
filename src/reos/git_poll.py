"""Git-first observation loop.

ReOS is a companion to Git: it observes repo state locally and produces
alignment checkpoints by comparing changes to the tech roadmap + charter.

This module polls git metadata (status/diffstat/numstat) and stores a lightweight
"git_poll" event in SQLite. Trigger logic is handled by storage hooks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .alignment import get_default_repo_path, get_git_summary
from .models import Event
from .storage import append_event


def poll_git_repo() -> dict[str, Any]:
    """Poll the configured repo and record a git metadata snapshot.

    Returns a summary dict suitable for UI display.
    """

    repo_path = get_default_repo_path()
    if repo_path is None:
        return {"status": "no_repo_detected"}

    summary = get_git_summary(repo_path, include_diff=False)
    payload = {
        "kind": "git_poll",
        "repo": str(repo_path),
        "branch": summary.branch,
        "changed_files": summary.changed_files,
        "diff_stat": summary.diff_stat,
        "status_porcelain": summary.status_porcelain,
        "ts": datetime.now(UTC).isoformat(),
    }

    append_event(Event(source="git", ts=datetime.now(UTC), payload_metadata=payload))

    return {
        "status": "ok",
        "repo": str(repo_path),
        "branch": summary.branch,
        "changed_files_count": len(summary.changed_files),
        "diff_stat": summary.diff_stat,
    }
