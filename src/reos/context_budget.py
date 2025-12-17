"""Context budget estimation for alignment reviews.

Goal: estimate whether the *potential* review payload (roadmap + charter + change summary)
will approach or exceed the usable LLM context window.

This stays metadata-first by default:
- It reads roadmap/charter text (project docs)
- It uses `git diff --numstat` (line counts) rather than patch text

All estimates are heuristics and should be treated as guidance, not truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReviewContextBudget:
    """Token budget estimate for a review."""

    context_limit_tokens: int
    trigger_ratio: float

    roadmap_tokens: int
    charter_tokens: int
    changes_tokens: int
    overhead_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.roadmap_tokens
            + self.charter_tokens
            + self.changes_tokens
            + self.overhead_tokens
        )

    @property
    def utilization(self) -> float:
        if self.context_limit_tokens <= 0:
            return 1.0
        return self.total_tokens / float(self.context_limit_tokens)

    @property
    def should_trigger(self) -> bool:
        return self.utilization >= self.trigger_ratio


_NUMSTAT_LINE_RE = re.compile(r"^(?P<added>\d+|-)\t(?P<deleted>\d+|-)\t(?P<path>.+)$")


def estimate_tokens_for_text(text: str) -> int:
    """Estimate token count from text.

    Heuristic: ~4 characters per token (varies by language/model).
    """

    if not text:
        return 0
    return max(1, len(text) // 4)


def parse_git_numstat(numstat_text: str) -> list[tuple[str, int, int]]:
    """Parse `git diff --numstat` output.

    Returns a list of (path, added_lines, deleted_lines).

    Notes:
    - Binary files show '-' for counts; those are treated as 0/0.
    """

    stats: list[tuple[str, int, int]] = []
    for line in (numstat_text or "").splitlines():
        match = _NUMSTAT_LINE_RE.match(line.strip())
        if not match:
            continue

        added_raw = match.group("added")
        deleted_raw = match.group("deleted")
        path = match.group("path")

        added = int(added_raw) if added_raw.isdigit() else 0
        deleted = int(deleted_raw) if deleted_raw.isdigit() else 0
        stats.append((path, added, deleted))

    return stats


def estimate_tokens_for_changes(
    numstat_text: str,
    *,
    tokens_per_changed_line: int,
    tokens_per_file: int,
) -> int:
    """Estimate token count for representing changes in a review.

    This does *not* read patch text. It approximates the size of change-related context.

    - tokens_per_changed_line approximates tokens needed if diffs were summarized
    - tokens_per_file accounts for file list + per-file framing
    """

    file_stats = parse_git_numstat(numstat_text)
    if not file_stats:
        return 0

    changed_lines = sum(added + deleted for _, added, deleted in file_stats)
    file_count = len({path for path, _, _ in file_stats})

    return int(changed_lines * tokens_per_changed_line + file_count * tokens_per_file)


def build_review_context_budget(
    *,
    context_limit_tokens: int,
    trigger_ratio: float,
    roadmap_text: str,
    charter_text: str,
    numstat_text: str,
    overhead_tokens: int,
    tokens_per_changed_line: int,
    tokens_per_file: int,
) -> ReviewContextBudget:
    """Construct a `ReviewContextBudget` from inputs."""

    roadmap_tokens = estimate_tokens_for_text(roadmap_text)
    charter_tokens = estimate_tokens_for_text(charter_text)
    changes_tokens = estimate_tokens_for_changes(
        numstat_text,
        tokens_per_changed_line=tokens_per_changed_line,
        tokens_per_file=tokens_per_file,
    )

    return ReviewContextBudget(
        context_limit_tokens=context_limit_tokens,
        trigger_ratio=trigger_ratio,
        roadmap_tokens=roadmap_tokens,
        charter_tokens=charter_tokens,
        changes_tokens=changes_tokens,
        overhead_tokens=overhead_tokens,
    )


def safe_read_text(path: Path) -> str:
    """Best-effort UTF-8 read; returns empty string if missing."""

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
