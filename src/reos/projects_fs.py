"""Filesystem-backed Projects + Knowledge Base.

A ReOS "project" is represented as a folder inside the ReOS workspace repo:

  projects/<project-id>/kb/
    charter.md
    roadmap.md
    settings.md
    pages/
    tables/

This is intentionally git-first: the KB is just files on disk. The GUI is a
surface over those files.

This module is small and dependency-free so it can be used by both GUI and
core code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class ProjectPaths:
    project_id: str
    project_dir: Path
    kb_dir: Path
    charter_md: Path
    roadmap_md: Path
    settings_md: Path
    pages_dir: Path
    tables_dir: Path


def workspace_root() -> Path:
    """Return the ReOS workspace repository root.

    Assumes the standard layout: <root>/src/reos/projects_fs.py.
    """

    return Path(__file__).resolve().parents[2]


def projects_root() -> Path:
    """Return the projects/ directory path (may not exist yet)."""

    return workspace_root() / "projects"


def is_valid_project_id(project_id: str) -> bool:
    """Validate a project id (folder name).

    Constraints:
    - lower-case, git-friendly
    - 2..64 chars
    - starts with alnum
    - remaining chars: alnum, _, -
    """

    return bool(_PROJECT_ID_RE.match(project_id))


def get_project_paths(project_id: str) -> ProjectPaths:
    """Return canonical paths for a project."""

    root = projects_root()
    project_dir = root / project_id
    kb_dir = project_dir / "kb"
    return ProjectPaths(
        project_id=project_id,
        project_dir=project_dir,
        kb_dir=kb_dir,
        charter_md=kb_dir / "charter.md",
        roadmap_md=kb_dir / "roadmap.md",
        settings_md=kb_dir / "settings.md",
        pages_dir=kb_dir / "pages",
        tables_dir=kb_dir / "tables",
    )


def list_project_ids() -> list[str]:
    """List project ids based on folders under projects/."""

    root = projects_root()
    if not root.exists():
        return []

    out: list[str] = []
    for p in root.iterdir():
        if p.is_dir() and is_valid_project_id(p.name):
            out.append(p.name)
    return sorted(out)


def ensure_project_skeleton(project_id: str) -> ProjectPaths:
    """Create the on-disk skeleton for a project if missing."""

    if not is_valid_project_id(project_id):
        raise ValueError("Invalid project id")

    paths = get_project_paths(project_id)
    paths.kb_dir.mkdir(parents=True, exist_ok=True)
    paths.pages_dir.mkdir(parents=True, exist_ok=True)
    paths.tables_dir.mkdir(parents=True, exist_ok=True)

    if not paths.charter_md.exists():
        paths.charter_md.write_text("# Charter\n\n", encoding="utf-8")
    if not paths.roadmap_md.exists():
        paths.roadmap_md.write_text("# Roadmap\n\n", encoding="utf-8")
    if not paths.settings_md.exists():
        paths.settings_md.write_text(
            "# Settings\n\n"
            "repoPath: \n",
            encoding="utf-8",
        )

    return paths


def read_text(path: Path) -> str:
    """Read UTF-8 text from disk (replace errors)."""

    return path.read_text(encoding="utf-8", errors="replace")


def extract_repo_path(settings_md_text: str) -> str | None:
    """Extract repoPath from settings.md content.

    Accepts either:
    - a line like: repoPath: /abs/path
    - a fenced codeblock with repoPath: ...

    Returns a string if present and non-empty.
    """

    for line in settings_md_text.splitlines():
        m = re.match(r"^\s*repoPath\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        val = m.group(1).strip()
        return val or None
    return None


def kb_relative_tree(project_id: str) -> list[str]:
    """Return KB file paths (relative to workspace root) for tree display."""

    paths = get_project_paths(project_id)
    if not paths.kb_dir.exists():
        return []

    rels: list[str] = []
    root = workspace_root()
    for p in sorted(paths.kb_dir.rglob("*")):
        if p.is_file():
            rels.append(str(p.relative_to(root)))
    return rels
