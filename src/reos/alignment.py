"""Alignment analysis: relate code changes to roadmap and charter.

This module is intentionally local-first and metadata-first.
Default behavior avoids capturing file contents; it only inspects git metadata
(file paths, diffstat). Optionally, callers can opt-in to include diffs.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import Database


@dataclass(frozen=True)
class GitSummary:
    """A lightweight summary of the repo's working tree state."""

    repo_path: Path
    branch: str | None
    status_porcelain: list[str]
    changed_files: list[str]
    diff_stat: str
    diff_text: str | None


_FILE_PATH_PATTERN = re.compile(
    r"(?P<path>(?:src|tests|docs|vscode-extension|\.github)/[\w\-./]+\.[\w\-]+)"
)


def _run_git(repo_path: Path, args: list[str]) -> str:
    """Run a git command and return stdout.

    Raises RuntimeError if git is missing or the command fails.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "(no details)"
        raise RuntimeError(f"git command failed: git {' '.join(args)} :: {detail}") from exc

    return completed.stdout


def is_git_repo(repo_path: Path) -> bool:
    """Return True if repo_path is inside a git repository."""
    try:
        out = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    except RuntimeError:
        return False
    return out.strip() == "true"


def get_git_summary(repo_path: Path, *, include_diff: bool = False) -> GitSummary:
    """Collect a git summary for the repo.

    Default behavior is metadata-only (file lists + diffstat).
    Set include_diff=True to include the full patch text (local-only).
    """
    if not is_git_repo(repo_path):
        raise RuntimeError(f"Not a git repository: {repo_path}")

    branch_out = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    branch = branch_out if branch_out and branch_out != "HEAD" else None

    status_raw = _run_git(repo_path, ["status", "--porcelain=v1"]).splitlines()
    changed_files = [
        line[3:].strip()
        for line in status_raw
        if len(line) >= 4 and line[3:].strip()
    ]

    diff_stat = _run_git(repo_path, ["diff", "--stat"]).strip()

    diff_text: str | None = None
    if include_diff:
        diff_text = _run_git(repo_path, ["diff"]).strip()

    return GitSummary(
        repo_path=repo_path,
        branch=branch,
        status_porcelain=status_raw,
        changed_files=changed_files,
        diff_stat=diff_stat,
        diff_text=diff_text,
    )


def extract_file_mentions(markdown_text: str) -> set[str]:
    """Extract workspace-relative file path mentions from markdown.

    This is a heuristic that looks for common project path prefixes.
    """
    return {m.group("path") for m in _FILE_PATH_PATTERN.finditer(markdown_text)}


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def infer_active_repo_path(db: Database) -> Path | None:
    """Infer the active repo path from recent VSCode events.

    Uses the most recent event with a `workspaceFolder` field.
    """
    for evt in db.iter_events_recent(limit=200):
        payload = evt.get("payload_metadata")
        if not isinstance(payload, str) or not payload:
            continue
        try:
            import json

            meta = json.loads(payload)
        except Exception:
            continue

        folder = meta.get("workspaceFolder")
        if isinstance(folder, str) and folder:
            return Path(folder)

    return None


def get_recent_active_files(db: Database, *, limit: int = 100) -> list[str]:
    """Return recent active editor URIs (best-effort)."""
    files: list[str] = []
    seen: set[str] = set()

    for evt in db.iter_events_recent(limit=limit):
        if evt.get("kind") != "active_editor":
            continue
        payload = evt.get("payload_metadata")
        if not isinstance(payload, str) or not payload:
            continue
        try:
            import json

            meta = json.loads(payload)
        except Exception:
            continue

        uri = meta.get("uri")
        if not isinstance(uri, str) or not uri:
            continue
        if uri in seen:
            continue
        seen.add(uri)
        files.append(uri)

    return files


def analyze_alignment(
    *,
    db: Database,
    repo_path: Path | None = None,
    roadmap_path: Path | None = None,
    charter_path: Path | None = None,
    include_diff: bool = False,
) -> dict[str, Any]:
    """Analyze how current code changes relate to roadmap and charter.

    This is intentionally heuristic-driven and reflective:
    - highlights changed files not mentioned in the roadmap
    - surfaces possible drift: changes far from current milestones
    - offers questions rather than prescriptions
    """
    inferred_repo = repo_path or infer_active_repo_path(db)
    if inferred_repo is None:
        return {
            "status": "no_repo_detected",
            "message": "No workspaceFolder found in recent VSCode events.",
        }

    roadmap = roadmap_path or (inferred_repo / "docs" / "tech-roadmap.md")
    charter = charter_path or (inferred_repo / "ReOS_charter.md")

    git_summary = get_git_summary(inferred_repo, include_diff=include_diff)

    roadmap_text = _safe_read_text(roadmap)
    charter_text = _safe_read_text(charter)

    roadmap_mentions = extract_file_mentions(roadmap_text)
    charter_mentions = extract_file_mentions(charter_text)

    unmapped_files = [
        f
        for f in git_summary.changed_files
        if f not in roadmap_mentions and f not in charter_mentions
    ]

    recent_files = get_recent_active_files(db, limit=100)

    questions: list[str] = []
    if unmapped_files:
        questions.append(
            "Some changed files aren't referenced in the roadmap/charter. "
            "Is this intentional exploration, or are we drifting from stated milestones?"
        )

    if len(set(recent_files)) >= 8:
        questions.append(
            "Your recent work spans many files. Is this creative exploration, "
            "or did something pull you away from the current thread?"
        )

    if git_summary.changed_files and not recent_files:
        questions.append(
            "There are uncommitted changes but no recent active editor events. "
            "Are these changes coming from a tool/automation, or from another editor?"
        )

    return {
        "status": "ok",
        "repo": {
            "path": str(inferred_repo),
            "branch": git_summary.branch,
            "changed_files": git_summary.changed_files,
            "diff_stat": git_summary.diff_stat,
            "status_porcelain": git_summary.status_porcelain,
        },
        "roadmap": {
            "path": str(roadmap),
            "mentioned_files_count": len(roadmap_mentions),
        },
        "charter": {
            "path": str(charter),
            "mentioned_files_count": len(charter_mentions),
        },
        "alignment": {
            "unmapped_changed_files": unmapped_files,
            "recent_active_files": recent_files[:20],
        },
        "questions": questions,
        "diff": git_summary.diff_text if include_diff else None,
        "note": (
            "This analysis is heuristic and local-first. "
            "Default mode avoids capturing file contents; set include_diff=true to inspect patches."
        ),
    }
