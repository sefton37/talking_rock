"""Attention metrics: fragmentation detection, focus depth, switching patterns."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import Database


@dataclass
class FragmentationMetrics:
    """Metrics for fragmentation/coherence of attention."""

    switch_count: int  # File switches in window
    window_seconds: int  # Time window analyzed
    fragmentation_score: float  # 0.0 (coherent) to 1.0 (highly fragmented)
    unique_files: int  # Number of unique files in window
    files: list[str]  # File URIs involved
    explanation: str  # Human-readable explanation


def calculate_fragmentation(
    db: Database,
    time_window_seconds: int = 300,
    switch_threshold: int = 8,
) -> FragmentationMetrics | None:
    """
    Calculate fragmentation score from recent file switching events.

    Bifocal principle: fragmentation is MEASURED from VSCode events, not assumed.
    """
    cutoff_time = (datetime.now(UTC) - timedelta(seconds=time_window_seconds)).isoformat()

    # Get recent file switch events (active_editor events)
    events = db._execute(
        """
        SELECT payload_metadata, ts FROM events
        WHERE kind = 'active_editor'
        AND ts > ?
        ORDER BY ts ASC
        """,
        (cutoff_time,),
    ).fetchall()

    if not events:
        return None

    # Parse file URIs from events
    files_seen = []
    unique_files_set = set()

    for row in events:
        try:
            if row[0]:  # payload_metadata is JSON string
                import json

                meta = json.loads(row[0])
                if "uri" in meta:
                    files_seen.append(meta["uri"])
                    unique_files_set.add(meta["uri"])
        except Exception:
            pass

    if len(files_seen) < 2:
        # Only one file or less—not fragmented
        return FragmentationMetrics(
            switch_count=0,
            window_seconds=time_window_seconds,
            fragmentation_score=0.0,
            unique_files=1,
            files=list(unique_files_set),
            explanation="Only one file open. Coherent focus.",
        )

    # Calculate fragmentation score:
    # - More switches in the window → higher fragmentation
    # - Normalized: 0 switches = 0.0, threshold switches = 1.0, beyond threshold = capped at 1.0
    switch_count = len(files_seen) - 1
    raw_score = min(1.0, switch_count / max(1, switch_threshold))

    # Adjust based on unique files: more unique files = more fragmented
    unique_penalty = min(0.2, len(unique_files_set) / 10.0)
    final_score = min(1.0, raw_score + unique_penalty)

    # Determine explanation
    if final_score < 0.3:
        explanation = (
            f"Coherent focus: {switch_count} switches across "
            f"{len(unique_files_set)} files."
        )
    elif final_score < 0.7:
        explanation = (
            f"Moderate switching: {switch_count} switches across {len(unique_files_set)} files. "
            f"Settling in? Or exploring intentionally?"
        )
    else:
        explanation = (
            f"Fragmented attention: {switch_count} switches across {len(unique_files_set)} files "
            f"in {time_window_seconds}s. Intention check: is this exploration or distraction?"
        )

    return FragmentationMetrics(
        switch_count=switch_count,
        window_seconds=time_window_seconds,
        fragmentation_score=final_score,
        unique_files=len(unique_files_set),
        files=list(unique_files_set),
        explanation=explanation,
    )


def get_current_session_summary(db: Database) -> dict[str, Any]:
    """
    Get a summary of the current coding session.

    Includes: active project, time in project, file history, fragmentation.
    """
    # Get last 100 editor events (recent file activity)
    events = db._execute(
        """
        SELECT payload_metadata, ts, kind FROM events
        WHERE kind IN ('active_editor', 'heartbeat')
        ORDER BY ts DESC
        LIMIT 100
        """
    ).fetchall()

    if not events:
        return {"status": "no_activity"}

    # Parse events to extract project info
    from dataclasses import dataclass, field

    @dataclass
    class ProjectInfo:
        """Info about a project."""

        files: set[str] = field(default_factory=set)
        duration_seconds: int = 0

    project_map: dict[str, ProjectInfo] = {}
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    for row in events:
        try:
            if row[0]:  # payload_metadata
                import json

                meta = json.loads(row[0])
                project = meta.get("projectName", "unknown")
                if project not in project_map:
                    project_map[project] = ProjectInfo()

                project_map[project].files.add(meta.get("uri", ""))
                if meta.get("timeInFileSeconds"):
                    project_map[project].duration_seconds += meta["timeInFileSeconds"]

                # Track timestamps
                if row[1]:  # ts
                    ts = datetime.fromisoformat(row[1])
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
        except Exception:
            pass

    # Calculate total duration
    total_duration = 0
    if first_ts and last_ts:
        total_duration = int((last_ts - first_ts).total_seconds())

    # Get fragmentation for this session
    frag = calculate_fragmentation(db, time_window_seconds=600)

    # Build summary
    projects = [
        {
            "name": proj,
            "file_count": len(info.files),
            "estimated_duration_seconds": info.duration_seconds,
        }
        for proj, info in sorted(
            project_map.items(),
            key=lambda x: x[1].duration_seconds,
            reverse=True,
        )
    ]

    return {
        "status": "active",
        "total_duration_seconds": total_duration,
        "projects": projects,
        "fragmentation": {
            "score": frag.fragmentation_score if frag else 0.0,
            "switches": frag.switch_count if frag else 0,
            "explanation": frag.explanation if frag else "No data",
        },
    }


def classify_attention_pattern(
    db: Database, session_id: str | None = None
) -> dict[str, Any]:
    """
    Classify the current attention pattern as coherent/fragmented, revolution/evolution.

    Returns classification with explanation (non-prescriptive, reflective language).
    """
    frag = calculate_fragmentation(db)
    summary = get_current_session_summary(db)

    if summary.get("status") == "no_activity":
        return {"pattern": "idle", "explanation": "No recent activity to classify."}

    # Determine fragmentation classification
    if frag and frag.fragmentation_score > 0.7:
        fragmentation_class = "fragmented"
        fragmentation_msg = "Your attention is scattered across multiple files."
    elif frag and frag.fragmentation_score > 0.4:
        fragmentation_class = "mixed"
        fragmentation_msg = "Your attention is shifting between files."
    else:
        fragmentation_class = "coherent"
        fragmentation_msg = "Your attention is sustained in focused work."

    # Determine revolution vs evolution based on project count
    projects = summary.get("projects", [])
    if len(projects) > 3:
        pattern_class = "revolutionary"
        pattern_msg = (
            "You're spanning many projects—is this intentional "
            "exploration or unplanned fragmentation?"
        )
    elif len(projects) > 1:
        pattern_class = "mixed"
        pattern_msg = "You're working across multiple projects with some depth."
    else:
        pattern_class = "evolutionary"
        pattern_msg = "You're focused on one project—building depth gradually."

    return {
        "fragmentation": fragmentation_class,
        "pattern": pattern_class,
        "fragmentation_message": fragmentation_msg,
        "pattern_message": pattern_msg,
        "metrics": summary.get("fragmentation", {}),
        "explanation": (
            f"{fragmentation_msg} {pattern_msg} "
            "What was your intention with this work?"
        ),
    }
