"""Alignment analysis: relate code changes to roadmap and charter.

This module is intentionally local-first and metadata-first.
Default behavior avoids capturing file contents; it only inspects git metadata
(file paths, diffstat). Optionally, callers can opt-in to include diffs.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context_budget import ReviewContextBudget, build_review_context_budget, safe_read_text
from .db import Database
from .errors import record_error
from .logging_setup import configure_logging
from .settings import settings

logger = logging.getLogger(__name__)


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
    r"(?P<path>(?:src|tests|docs|\.github)/[\w\-./]+\.[\w\-]+)"
)


def get_default_repo_path() -> Path | None:
    """Return the default repo path ReOS should observe (Git-first).

    Preference order:
    1) `REOS_REPO_PATH` (settings.repo_path)
    2) workspace root (settings.root_dir) if it is a git repo
    """

    if settings.repo_path is not None and is_git_repo(settings.repo_path):
        return settings.repo_path

    if is_git_repo(settings.root_dir):
        return settings.root_dir

    return None


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


def _git_numstat(repo_path: Path) -> str:
    """Return `git diff --numstat` output (metadata only)."""

    return _run_git(repo_path, ["diff", "--numstat"]).strip()


def get_head_sha(repo_path: Path) -> str:
    """Return the current HEAD commit SHA."""

    if not is_git_repo(repo_path):
        raise RuntimeError(f"Not a git repository: {repo_path}")
    return _run_git(repo_path, ["rev-parse", "HEAD"]).strip()


def get_commit_subject(repo_path: Path, *, commit_sha: str) -> str:
    """Return the subject line for a given commit."""

    if not commit_sha:
        raise ValueError("commit_sha is required")
    return _run_git(repo_path, ["show", "-s", "--format=%s", commit_sha]).strip()


def get_commit_patch(repo_path: Path, *, commit_sha: str, max_bytes: int = 1_000_000) -> str:
    """Return the patch text for a given commit.

    This reads commit content via `git show` and should only be used with explicit user opt-in.
    """

    if not commit_sha:
        raise ValueError("commit_sha is required")

    patch = _run_git(
        repo_path,
        [
            "show",
            "--no-color",
            "--format=commit %H%nAuthor: %an <%ae>%nDate: %ad%nSubject: %s%n",
            "--patch",
            "--unified=3",
            commit_sha,
        ],
    )

    if len(patch.encode("utf-8", errors="ignore")) > max_bytes:
        # Avoid runaway context sizes.
        return patch[:max_bytes]
    return patch


def get_review_context_budget(
    *,
    repo_path: Path,
    roadmap_path: Path,
    charter_path: Path,
) -> ReviewContextBudget:
    """Estimate review context usage for current changes.

    Uses project docs (roadmap/charter text) plus git numstat (line counts).
    """

    roadmap_text = safe_read_text(roadmap_path)
    charter_text = safe_read_text(charter_path)
    numstat_text = _git_numstat(repo_path)

    return build_review_context_budget(
        context_limit_tokens=settings.llm_context_tokens,
        trigger_ratio=settings.review_trigger_ratio,
        roadmap_text=roadmap_text,
        charter_text=charter_text,
        numstat_text=numstat_text,
        overhead_tokens=settings.review_overhead_tokens,
        tokens_per_changed_line=settings.tokens_per_changed_line,
        tokens_per_file=settings.tokens_per_changed_file,
    )


def infer_active_repo_path(db: Database) -> Path | None:
    """Legacy helper: infer a repo from stored events.

    ReOS is Git-first; prefer `get_default_repo_path()`.
    This remains for backward compatibility with older event sources.
    """

    return get_default_repo_path()


def get_recent_active_files(db: Database, *, limit: int = 100) -> list[str]:
    """Legacy helper: return recent editor URIs if event sources provide them."""
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
    inferred_repo = repo_path

    if inferred_repo is None:
        state_repo = db.get_state(key="repo_path")
        if isinstance(state_repo, str) and state_repo.strip():
            candidate = Path(state_repo).resolve()
            if is_git_repo(candidate):
                inferred_repo = candidate

    if inferred_repo is None:
        inferred_repo = get_default_repo_path()
    if inferred_repo is None:
        return {
            "status": "no_repo_detected",
            "message": "No git repo detected. Set REOS_REPO_PATH or run ReOS inside a repo.",
        }

    roadmap: Path | None = roadmap_path
    charter: Path | None = charter_path

    roadmap = roadmap or (inferred_repo / "docs" / "tech-roadmap.md")
    charter = charter or (inferred_repo / "ReOS_charter.md")

    configure_logging()
    try:
        git_summary = get_git_summary(inferred_repo, include_diff=include_diff)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to collect git summary")
        record_error(
            source="reos",
            operation="analyze_alignment_get_git_summary",
            exc=exc,
            context={"repo": str(inferred_repo), "include_diff": include_diff},
        )
        return {
            "status": "error",
            "repo": {"path": str(inferred_repo)},
            "message": str(exc),
        }

    roadmap_text = safe_read_text(roadmap)
    charter_text = safe_read_text(charter)

    roadmap_mentions = extract_file_mentions(roadmap_text)
    charter_mentions = extract_file_mentions(charter_text)

    context_budget = get_review_context_budget(
        repo_path=inferred_repo,
        roadmap_path=roadmap,
        charter_path=charter,
    )

    unmapped_files = [
        f
        for f in git_summary.changed_files
        if f not in roadmap_mentions and f not in charter_mentions
    ]

    changed_areas = sorted({f.split("/", 1)[0] for f in git_summary.changed_files if "/" in f})
    changed_file_count = len(git_summary.changed_files)
    area_count = len(changed_areas)

    # Git-first: no editor telemetry required.
    recent_files: list[str] = []

    questions: list[str] = []
    if unmapped_files:
        questions.append(
            "Some changed files aren't referenced in the roadmap/charter. "
            "Is this intentional exploration, or are we drifting from stated milestones?"
        )

    if changed_file_count >= 10 or area_count >= 3:
        questions.append(
            "Your changes span many files/areas. Is this one coherent move, "
            "or have multiple threads opened at once?"
        )

    # Intentionally avoids judging based on switching/telemetry. Keep questions plan-anchored.

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
            "scope": {
                "changed_file_count": changed_file_count,
                "changed_areas": changed_areas,
                "area_count": area_count,
            },
        },
        "questions": questions,
        "diff": git_summary.diff_text if include_diff else None,
        "context_budget": {
            "estimate": {
                "context_limit_tokens": context_budget.context_limit_tokens,
                "total_tokens": context_budget.total_tokens,
                "utilization": context_budget.utilization,
                "should_trigger": context_budget.should_trigger,
                "roadmap_tokens": context_budget.roadmap_tokens,
                "charter_tokens": context_budget.charter_tokens,
                "changes_tokens": context_budget.changes_tokens,
                "overhead_tokens": context_budget.overhead_tokens,
            },
            "note": (
                "Token counts are heuristic estimates. Changes are estimated from "
                "`git diff --numstat` (metadata-only) unless you opt into include_diff "
                "in the alignment review itself."
            ),
        },
        "note": (
            "This analysis is heuristic and local-first. "
            "Default mode avoids capturing file contents; set include_diff=true to inspect patches."
        ),
    }
