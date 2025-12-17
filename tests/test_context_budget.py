from __future__ import annotations

from reos.context_budget import (
    build_review_context_budget,
    estimate_tokens_for_changes,
    parse_git_numstat,
)


def test_parse_git_numstat_basic() -> None:
    numstat = "10\t2\tsrc/reos/foo.py\n3\t0\tdocs/tech-roadmap.md\n"
    stats = parse_git_numstat(numstat)
    assert stats == [("src/reos/foo.py", 10, 2), ("docs/tech-roadmap.md", 3, 0)]


def test_estimate_tokens_for_changes_counts_lines_and_files() -> None:
    numstat = "10\t2\tsrc/reos/foo.py\n3\t0\tdocs/tech-roadmap.md\n"
    # changed_lines = 15, file_count = 2
    tokens = estimate_tokens_for_changes(numstat, tokens_per_changed_line=6, tokens_per_file=40)
    assert tokens == 15 * 6 + 2 * 40


def test_budget_should_trigger_when_over_ratio() -> None:
    budget = build_review_context_budget(
        context_limit_tokens=100,
        trigger_ratio=0.8,
        roadmap_text="x" * 200,  # ~50 tokens
        charter_text="y" * 200,  # ~50 tokens
        numstat_text="1\t1\tsrc/reos/foo.py\n",  # lines=2
        overhead_tokens=10,
        tokens_per_changed_line=6,
        tokens_per_file=40,
    )
    # total ~= 50 + 50 + (2*6 + 1*40) + 10 = 162 => utilization 1.62
    assert budget.should_trigger is True
