"""Play handlers.

Manages The Play structure: Acts, Scenes, Beats, Knowledge Base, and Attachments.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from reos.db import Database
from reos.play_fs import (
    add_attachment as play_add_attachment,
    assign_repo_to_act as play_assign_repo_to_act,
    create_act as play_create_act,
    create_beat as play_create_beat,
    create_scene as play_create_scene,
    kb_list_files as play_kb_list_files,
    kb_read as play_kb_read,
    kb_write_apply as play_kb_write_apply,
    kb_write_preview as play_kb_write_preview,
    list_acts as play_list_acts,
    list_attachments as play_list_attachments,
    list_beats as play_list_beats,
    list_scenes as play_list_scenes,
    read_me_markdown as play_read_me_markdown,
    remove_attachment as play_remove_attachment,
    set_active_act_id as play_set_active_act_id,
    update_act as play_update_act,
    update_beat as play_update_beat,
    update_scene as play_update_scene,
    write_me_markdown as play_write_me_markdown,
)
from reos.rpc.router import register
from reos.rpc.types import INVALID_PARAMS, RpcError


# -------------------------------------------------------------------------
# Me handlers (identity)
# -------------------------------------------------------------------------


@register("play/me/read", needs_db=True)
def handle_me_read(_db: Database) -> dict[str, Any]:
    """Read me.md identity document."""
    return {"markdown": play_read_me_markdown()}


@register("play/me/write", needs_db=True)
def handle_me_write(_db: Database, *, text: str) -> dict[str, Any]:
    """Write me.md identity document."""
    play_write_me_markdown(text)
    return {"ok": True}


# -------------------------------------------------------------------------
# Acts handlers
# -------------------------------------------------------------------------


def _acts_response(acts: list, active_id: str | None = None) -> dict[str, Any]:
    """Helper to format acts response."""
    return {
        "active_act_id": active_id,
        "acts": [
            {
                "act_id": a.act_id,
                "title": a.title,
                "active": bool(a.active),
                "notes": a.notes,
                "repo_path": a.repo_path,
            }
            for a in acts
        ],
    }


@register("play/acts/list", needs_db=True)
def handle_acts_list(_db: Database) -> dict[str, Any]:
    """List all acts."""
    acts, active_id = play_list_acts()
    return _acts_response(acts, active_id)


@register("play/acts/set_active", needs_db=True)
def handle_acts_set_active(_db: Database, *, act_id: str | None) -> dict[str, Any]:
    """Set active act, or clear it if act_id is None."""
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _acts_response(acts, active_id)


@register("play/acts/create", needs_db=True)
def handle_acts_create(_db: Database, *, title: str, notes: str | None = None) -> dict[str, Any]:
    """Create a new act."""
    try:
        acts, created_id = play_create_act(title=title, notes=notes or "")
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return {
        "created_act_id": created_id,
        **_acts_response(acts),
    }


@register("play/acts/update", needs_db=True)
def handle_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update an existing act."""
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes)
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _acts_response(acts, active_id)


@register("play/acts/assign_repo", needs_db=True)
def handle_acts_assign_repo(
    _db: Database,
    *,
    act_id: str,
    repo_path: str,
) -> dict[str, Any]:
    """Assign a repository path to an act. Creates the directory if it doesn't exist."""
    path = Path(repo_path).expanduser().resolve()

    # Create directory if it doesn't exist
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    # Initialize git repo if not already a git repo
    git_dir = path / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        # Create initial commit to have a valid repo
        readme = path / "README.md"
        if not readme.exists():
            readme.write_text("# Project\n\nCreated by ReOS\n")
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), capture_output=True, check=True)

    try:
        acts, _active_id = play_assign_repo_to_act(act_id=act_id, repo_path=str(path))
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc

    return {
        "success": True,
        "repo_path": str(path),
        **_acts_response(acts),
    }


# -------------------------------------------------------------------------
# Scenes handlers
# -------------------------------------------------------------------------


def _scenes_response(scenes: list) -> dict[str, Any]:
    """Helper to format scenes response."""
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


@register("play/scenes/list", needs_db=True)
def handle_scenes_list(_db: Database, *, act_id: str) -> dict[str, Any]:
    """List scenes for an act."""
    scenes = play_list_scenes(act_id=act_id)
    return _scenes_response(scenes)


@register("play/scenes/create", needs_db=True)
def handle_scenes_create(
    _db: Database,
    *,
    act_id: str,
    title: str,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new scene in an act."""
    try:
        scenes = play_create_scene(
            act_id=act_id,
            title=title,
            intent=intent or "",
            status=status or "",
            time_horizon=time_horizon or "",
            notes=notes or "",
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _scenes_response(scenes)


@register("play/scenes/update", needs_db=True)
def handle_scenes_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update an existing scene."""
    try:
        scenes = play_update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            intent=intent,
            status=status,
            time_horizon=time_horizon,
            notes=notes,
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _scenes_response(scenes)


# -------------------------------------------------------------------------
# Beats handlers
# -------------------------------------------------------------------------


def _beats_response(beats: list) -> dict[str, Any]:
    """Helper to format beats response."""
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
            }
            for b in beats
        ]
    }


@register("play/beats/list", needs_db=True)
def handle_beats_list(_db: Database, *, act_id: str, scene_id: str) -> dict[str, Any]:
    """List beats for a scene."""
    beats = play_list_beats(act_id=act_id, scene_id=scene_id)
    return _beats_response(beats)


@register("play/beats/create", needs_db=True)
def handle_beats_create(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    """Create a new beat in a scene."""
    try:
        beats = play_create_beat(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            status=status or "",
            notes=notes or "",
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _beats_response(beats)


@register("play/beats/update", needs_db=True)
def handle_beats_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    beat_id: str,
    title: str | None = None,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    """Update an existing beat."""
    try:
        beats = play_update_beat(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            title=title,
            status=status,
            notes=notes,
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _beats_response(beats)


# -------------------------------------------------------------------------
# Knowledge Base handlers
# -------------------------------------------------------------------------


@register("play/kb/list", needs_db=True)
def handle_kb_list(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    """List knowledge base files."""
    try:
        files = play_kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return {"files": files}


@register("play/kb/read", needs_db=True)
def handle_kb_read(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str = "kb.md",
) -> dict[str, Any]:
    """Read a knowledge base file."""
    try:
        text = play_kb_read(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path)
    except FileNotFoundError as exc:
        raise RpcError(code=INVALID_PARAMS, message=f"file not found: {exc}") from exc
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return {"path": path, "text": text}


@register("play/kb/write_preview", needs_db=True)
def handle_kb_write_preview(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    """Preview changes to a knowledge base file before applying."""
    try:
        res = play_kb_write_preview(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path, text=text)
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return {
        "path": path,
        "expected_sha256_current": res["sha256_current"],
        **res,
    }


@register("play/kb/write_apply", needs_db=True)
def handle_kb_write_apply(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    """Apply changes to a knowledge base file with conflict detection."""
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=INVALID_PARAMS, message="expected_sha256_current is required")
    try:
        res = play_kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256_current,
        )
    except ValueError as exc:
        # Surface conflicts as a deterministic JSON-RPC error.
        raise RpcError(code=-32009, message=str(exc)) from exc
    return {"path": path, **res}


# -------------------------------------------------------------------------
# Attachments handlers
# -------------------------------------------------------------------------


def _attachments_response(attachments: list) -> dict[str, Any]:
    """Helper to format attachments response."""
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


@register("play/attachments/list", needs_db=True)
def handle_attachments_list(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    """List attachments."""
    try:
        attachments = play_list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _attachments_response(attachments)


@register("play/attachments/add", needs_db=True)
def handle_attachments_add(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Add an attachment."""
    try:
        attachments = play_add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            file_path=file_path,
            file_name=file_name,
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _attachments_response(attachments)


@register("play/attachments/remove", needs_db=True)
def handle_attachments_remove(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    attachment_id: str,
) -> dict[str, Any]:
    """Remove an attachment."""
    try:
        attachments = play_remove_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise RpcError(code=INVALID_PARAMS, message=str(exc)) from exc
    return _attachments_response(attachments)
