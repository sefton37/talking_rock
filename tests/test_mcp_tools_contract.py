from __future__ import annotations

from pathlib import Path

import pytest

from reos.db import get_db
from reos.mcp_tools import ToolError, call_tool


def test_git_summary_metadata_only_by_default(configured_repo: Path) -> None:
    db = get_db()

    res = call_tool(db, name="reos_git_summary", arguments={})
    assert isinstance(res, dict)
    assert res["repo"].endswith("/repo")
    assert res["diff"] is None


def test_git_summary_include_diff_true_returns_diff(configured_repo: Path) -> None:
    repo = configured_repo

    # Make a working tree change so diff is non-empty.
    p = repo / "src" / "reos" / "example.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# diff\n", encoding="utf-8")

    db = get_db()
    res = call_tool(db, name="reos_git_summary", arguments={"include_diff": True})
    assert isinstance(res.get("diff"), str)
    assert "example.py" in res["diff"]


def test_repo_list_files_glob(configured_repo: Path) -> None:
    db = get_db()
    files = call_tool(db, name="reos_repo_list_files", arguments={"glob": "src/reos/*.py"})
    assert "src/reos/example.py" in files


def test_repo_read_file_line_range(configured_repo: Path) -> None:
    db = get_db()
    out = call_tool(
        db,
        name="reos_repo_read_file",
        arguments={"path": "src/reos/example.py", "start_line": 1, "end_line": 2},
    )
    assert "def hello" in out


def test_repo_read_file_blocks_escape(configured_repo: Path) -> None:
    db = get_db()
    with pytest.raises(ToolError) as exc:
        call_tool(
            db,
            name="reos_repo_read_file",
            arguments={"path": "../secrets.txt", "start_line": 1, "end_line": 1},
        )
    assert exc.value.code in {"path_escape", "invalid_args"}


def test_repo_read_file_range_too_large(configured_repo: Path) -> None:
    db = get_db()
    with pytest.raises(ToolError) as exc:
        call_tool(
            db,
            name="reos_repo_read_file",
            arguments={"path": "src/reos/example.py", "start_line": 1, "end_line": 9999},
        )
    assert exc.value.code == "range_too_large"


def test_repo_grep_finds_matches(configured_repo: Path) -> None:
    db = get_db()
    results = call_tool(db, name="reos_repo_grep", arguments={"query": "def hello"})
    assert isinstance(results, list)
    assert any(r.get("path") == "src/reos/example.py" for r in results)


def test_tools_require_repo_config(
    isolated_db_singleton,  # noqa: ANN001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No repo configured in this DB, and ensure we don't fall back to the
    # workspace root repo (this test suite runs inside a git repo).
    from reos import mcp_tools as mcp_tools_mod
    from reos.settings import Settings

    monkeypatch.setattr(
        mcp_tools_mod,
        "settings",
        Settings(root_dir=tmp_path, repo_path=None),
        raising=True,
    )

    db = get_db()

    with pytest.raises(ToolError) as exc:
        call_tool(db, name="reos_git_summary", arguments={})
    assert exc.value.code == "no_repo_detected"
