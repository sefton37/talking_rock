from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alignment import get_default_repo_path, get_review_context_budget, is_git_repo
from .db import Database, get_db
from .models import Event
from .settings import settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


def append_event(event: Event) -> str:
    """Store an event to SQLite; fallback to JSONL for debugging."""
    db = get_db()
    event_id = str(uuid.uuid4())

    # Try SQLite first
    try:
        db.insert_event(
            event_id=event_id,
            source=event.source,
            kind=event.payload_metadata.get("kind") if event.payload_metadata else None,
            ts=event.ts.isoformat(),
            payload_metadata=json.dumps(event.payload_metadata) if event.payload_metadata else None,
            note=event.note,
        )
        _maybe_emit_alignment_trigger(db=db, recent_event_payload=event.payload_metadata)
        return event_id
    except Exception as exc:
        # Fallback to JSONL for debugging/recovery
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "id": event_id,
            "source": event.source,
            "ts": event.ts.isoformat(),
            "payload_metadata": event.payload_metadata,
            "note": event.note,
            "error": f"SQLite failed, fell back to JSONL: {str(exc)}",
        }
        with settings.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")
        return event_id


def _maybe_emit_review_trigger(
    *,
    db: Database,
    recent_event_payload: dict[str, object] | None,
) -> None:
    """Insert a review-trigger event if context budget is nearing capacity.

    This runs during ingestion so triggers can happen in the background.
    The trigger is throttled by a cooldown to avoid spamming.
    """

    try:
        repo_path = get_default_repo_path()
        if repo_path is None:
            return

        if not is_git_repo(repo_path):
            return

        roadmap_path = repo_path / "docs" / "tech-roadmap.md"
        charter_path = repo_path / "ReOS_charter.md"

        budget = get_review_context_budget(
            repo_path=repo_path,
            roadmap_path=roadmap_path,
            charter_path=charter_path,
        )

        if not budget.should_trigger:
            return

        # Throttle based on most recent triggers in DB.
        cooldown = timedelta(minutes=max(1, settings.review_trigger_cooldown_minutes))
        now = _utcnow()
        for evt in db.iter_events_recent(limit=200):
            if evt.get("kind") != "review_trigger":
                continue
            try:
                ts = datetime.fromisoformat(str(evt.get("ts")))
            except Exception:
                continue
            if now - ts < cooldown:
                return

        trigger_id = str(uuid.uuid4())
        trigger_ts = now.isoformat()
        payload = {
            "kind": "review_trigger",
            "repo": str(repo_path),
            "context_limit_tokens": budget.context_limit_tokens,
            "estimated_total_tokens": budget.total_tokens,
            "utilization": budget.utilization,
            "trigger_ratio": budget.trigger_ratio,
            "breakdown": {
                "roadmap_tokens": budget.roadmap_tokens,
                "charter_tokens": budget.charter_tokens,
                "changes_tokens": budget.changes_tokens,
                "overhead_tokens": budget.overhead_tokens,
            },
            "note": (
                "Estimated review context is nearing the configured limit. "
                "Consider running an alignment review to checkpoint before adding more context."
            ),
        }

        # Insert directly to avoid recursive trigger loops.
        db.insert_event(
            event_id=trigger_id,
            source="reos",
            kind="review_trigger",
            ts=trigger_ts,
            payload_metadata=json.dumps(payload),
            note="Review checkpoint suggested (context budget nearing limit)",
        )
    except Exception:
        # Best-effort only; ingestion should not fail if budgeting fails.
        return


def _maybe_emit_alignment_trigger(
    *,
    db: Database,
    recent_event_payload: dict[str, object] | None,
) -> None:
    """Insert an alignment/scope checkpoint event (metadata-only).

    This asks two quiet questions:
    - Are we drifting from roadmap/charter?
    - Are we taking on too many threads at once?

    Trigger logic is heuristic and throttled.
    """

    try:
        # Prefer the active project's repoPath (from projects/<id>/kb/settings.md).
        repo_path: Path | None = None
        active_repo = db.get_active_project_repo_path()
        if isinstance(active_repo, str) and active_repo.strip():
            repo_path = Path(active_repo).resolve()

        if repo_path is None:
            repo_path = get_default_repo_path()

        if repo_path is None or not is_git_repo(repo_path):
            return

        cooldown = timedelta(minutes=max(1, settings.review_trigger_cooldown_minutes))
        now = _utcnow()
        for evt in db.iter_events_recent(limit=200):
            if evt.get("kind") != "alignment_trigger":
                continue
            try:
                ts = datetime.fromisoformat(str(evt.get("ts")))
            except Exception:
                continue
            if now - ts < cooldown:
                return

        # Compute metadata-only alignment signals.
        from .alignment import analyze_alignment

        # analyze_alignment is project-aware and will prefer KB roadmap/charter when present.
        report = analyze_alignment(db=db, repo_path=repo_path, include_diff=False)
        alignment = report.get("alignment", {}) if isinstance(report, dict) else {}
        unmapped = alignment.get("unmapped_changed_files", [])
        scope = alignment.get("scope", {}) if isinstance(alignment, dict) else {}

        unmapped_count = len(unmapped) if isinstance(unmapped, list) else 0
        if isinstance(scope, dict):
            changed_file_count = int(scope.get("changed_file_count", 0))
            area_count = int(scope.get("area_count", 0))
        else:
            changed_file_count = 0
            area_count = 0

        # Heuristic thresholds; keep conservative to avoid noise.
        should_trigger = unmapped_count >= 5 or changed_file_count >= 15 or area_count >= 4
        if not should_trigger:
            return

        project_id = db.get_active_project_id()
        repo_info = report.get("repo", {}) if isinstance(report, dict) else {}
        roadmap_info = report.get("roadmap", {}) if isinstance(report, dict) else {}
        charter_info = report.get("charter", {}) if isinstance(report, dict) else {}

        payload = {
            "kind": "alignment_trigger",
            "project_id": project_id if isinstance(project_id, str) and project_id else None,
            "repo": str(repo_info.get("path") or repo_path),
            "roadmap": {"path": str(roadmap_info.get("path") or "")},
            "charter": {"path": str(charter_info.get("path") or "")},
            "signals": {
                "unmapped_changed_files_count": unmapped_count,
                "changed_file_count": changed_file_count,
                "area_count": area_count,
            },
            "examples": {
                "unmapped_changed_files": (unmapped[:10] if isinstance(unmapped, list) else []),
            },
            "questions": [
                "Do these changes still map to the roadmap + charter?",
                "Are multiple threads open at once?",
            ],
            "note": (
                "This is metadata-only and heuristic. For a deeper check, run `review_alignment` "
                "(optionally include diffs if you consent)."
            ),
        }

        db.insert_event(
            event_id=str(uuid.uuid4()),
            source="reos",
            kind="alignment_trigger",
            ts=now.isoformat(),
            payload_metadata=json.dumps(payload),
            note="Alignment checkpoint suggested",
        )
    except Exception:
        return


def iter_events(limit: int | None = None) -> Iterable[tuple[str, Event]]:
    """Yield events from SQLite storage (newest first)."""
    db = get_db()
    rows = db.iter_events_recent(limit=limit or 1000)

    for row in rows:
        try:
            payload = None
            payload_metadata = row["payload_metadata"]
            if payload_metadata:
                payload = json.loads(str(payload_metadata))

            ts_str = row["ts"]
            # Parse the ISO format timestamp back to datetime
            from datetime import datetime

            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))

            evt = Event(
                source=str(row["source"]),
                ts=ts,
                payload_metadata=payload,
                note=str(row["note"]) if row["note"] else None,
            )
            event_id = str(row["id"])
            yield event_id, evt
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
