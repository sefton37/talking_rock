"""Git-first observation loop.

ReOS is a companion to Git: it observes repo state locally and produces
alignment checkpoints by comparing changes to the tech roadmap + charter.

This module polls git metadata (status/diffstat/numstat) and stores a lightweight
"git_poll" event in SQLite. Trigger logic is handled by storage hooks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .alignment import get_default_repo_path, get_git_summary
from .errors import record_error
from .logging_setup import configure_logging
from .models import Event
from .storage import append_event

logger = logging.getLogger(__name__)


def poll_git_repo() -> dict[str, Any]:
    """Poll the configured repo and record a git metadata snapshot.

    Returns a summary dict suitable for UI display.
    """

    configure_logging()
    repo_path = get_default_repo_path()
    if repo_path is None:
        return {"status": "no_repo_detected"}

    try:
        summary = get_git_summary(repo_path, include_diff=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Git polling failed")
        record_error(
            source="git",
            operation="poll_git_repo",
            exc=exc,
            context={"repo": str(repo_path)},
        )
        return {"status": "error", "repo": str(repo_path), "message": str(exc)}
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
