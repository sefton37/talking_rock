from __future__ import annotations

from pathlib import Path

import pytest

from reos.alignment import analyze_alignment, get_git_summary
from reos.db import get_db


def test_get_git_summary_include_diff_contract(temp_git_repo: Path) -> None:
    repo = temp_git_repo

    # Make a working tree change.
    p = repo / "src" / "reos" / "example.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# change\n", encoding="utf-8")

    summary_meta = get_git_summary(repo, include_diff=False)
    assert summary_meta.diff_text is None
    assert "src/reos/example.py" in summary_meta.changed_files

    summary_diff = get_git_summary(repo, include_diff=True)
    assert isinstance(summary_diff.diff_text, str)
    assert "example.py" in summary_diff.diff_text


def test_analyze_alignment_reports_unmapped_changed_files(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Create a changed file that is NOT mentioned in roadmap/charter.
    unmapped = repo / "src" / "reos" / "unmapped.py"
    unmapped.write_text("x = 1\n", encoding="utf-8")

    # Ensure it shows up as a change.
    from conftest import run_git  # type: ignore[import-not-found]

    run_git(repo, ["add", str(unmapped.relative_to(repo))])

    # Analyze uses `git diff` against index; staged changes still appear.
    # (Also add a working tree change to be safe.)
    unmapped.write_text("x = 2\n", encoding="utf-8")

    # Force the analyzer to look at our temp repo (avoid workspace root).
    import reos.alignment as alignment_mod

    monkeypatch.setattr(alignment_mod, "get_default_repo_path", lambda: repo)

    db = get_db()
    report = analyze_alignment(db=db, repo_path=repo, include_diff=False)

    assert report["status"] == "ok"
    unmapped_files = report["alignment"]["unmapped_changed_files"]
    assert "src/reos/unmapped.py" in unmapped_files
    assert report["diff"] is None
