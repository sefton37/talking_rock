from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .session import get_current_crypto_storage
from .settings import settings


_JSON = dict[str, Any]


@dataclass(frozen=True)
class Act:
    act_id: str
    title: str
    active: bool = False
    notes: str = ""


@dataclass(frozen=True)
class Scene:
    scene_id: str
    title: str
    intent: str
    status: str
    time_horizon: str
    notes: str


@dataclass(frozen=True)
class Beat:
    beat_id: str
    title: str
    status: str
    notes: str
    link: str | None = None


@dataclass(frozen=True)
class FileAttachment:
    """A file attachment reference (stores path only, not file content)."""
    attachment_id: str
    file_path: str      # Absolute path on disk
    file_name: str      # Display name
    file_type: str      # Extension (pdf, docx, etc.)
    added_at: str       # ISO timestamp


def play_root() -> Path:
    """Return the on-disk root for the theatrical model.

    If running with an authenticated session, uses per-user isolated storage
    at ~/.reos-data/{username}/play. Otherwise falls back to the repo-local
    .reos-data/ directory.

    Security:
        - Per-user data isolation when session context is active
        - Data can optionally be encrypted via CryptoStorage
    """
    # Check for per-user session context
    crypto = get_current_crypto_storage()
    if crypto is not None:
        # Use per-user isolated storage
        return crypto.user_data_root / "play"

    # Fallback to default location (development/unauthenticated mode)
    base = Path(os.environ["REOS_DATA_DIR"]) if os.environ.get("REOS_DATA_DIR") else settings.data_dir
    return base / "play"


def _acts_path() -> Path:
    return play_root() / "acts.json"


def _me_path() -> Path:
    return play_root() / "me.md"


def _act_dir(act_id: str) -> Path:
    return play_root() / "acts" / act_id


def _scenes_path(act_id: str) -> Path:
    return _act_dir(act_id) / "scenes.json"


def ensure_play_skeleton() -> None:
    root = play_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "acts").mkdir(parents=True, exist_ok=True)

    me = _me_path()
    if not me.exists():
        me.write_text(
            "# Me (The Play)\n\n"
            "Personal facts, principles, constraints, and identity-level context.\n"
            "\n"
            "This is read-mostly and slow-changing. It is not a task list.\n",
            encoding="utf-8",
        )

    acts = _acts_path()
    if not acts.exists():
        acts.write_text(json.dumps({"acts": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_me_markdown() -> str:
    ensure_play_skeleton()
    return _me_path().read_text(encoding="utf-8", errors="replace")


def _load_json(path: Path) -> _JSON:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, obj: _JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_acts() -> tuple[list[Act], str | None]:
    ensure_play_skeleton()
    data = _load_json(_acts_path())

    acts_raw = data.get("acts")
    if not isinstance(acts_raw, list):
        acts_raw = []

    acts: list[Act] = []
    active_id: str | None = None

    for item in acts_raw:
        if not isinstance(item, dict):
            continue
        act_id = item.get("act_id")
        title = item.get("title")
        active = bool(item.get("active", False))
        notes = item.get("notes")

        if not isinstance(act_id, str) or not act_id:
            continue
        if not isinstance(title, str) or not title:
            continue
        if not isinstance(notes, str):
            notes = ""

        if active and active_id is None:
            active_id = act_id

        acts.append(Act(act_id=act_id, title=title, active=active, notes=notes))

    # Enforce single-active invariant if the file has drifted.
    if active_id is not None:
        normalized: list[Act] = []
        for a in acts:
            normalized.append(Act(act_id=a.act_id, title=a.title, active=(a.act_id == active_id), notes=a.notes))
        acts = normalized
        _write_acts(acts)

    return acts, active_id


def _write_acts(acts: list[Act]) -> None:
    payload = {
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ]
    }
    _write_json(_acts_path(), payload)


def set_active_act_id(*, act_id: str) -> tuple[list[Act], str]:
    acts, _active = list_acts()
    if not any(a.act_id == act_id for a in acts):
        raise ValueError("unknown act_id")

    updated = [Act(act_id=a.act_id, title=a.title, active=(a.act_id == act_id), notes=a.notes) for a in acts]
    _write_acts(updated)
    return updated, act_id


def list_scenes(*, act_id: str) -> list[Scene]:
    ensure_play_skeleton()
    scenes_path = _scenes_path(act_id)
    if not scenes_path.exists():
        # No scenes yet.
        return []

    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        return []

    out: list[Scene] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        scene_id = item.get("scene_id")
        title = item.get("title")
        intent = item.get("intent")
        status = item.get("status")
        time_horizon = item.get("time_horizon")
        notes = item.get("notes")

        if not isinstance(scene_id, str) or not scene_id:
            continue
        if not isinstance(title, str) or not title:
            continue

        out.append(
            Scene(
                scene_id=scene_id,
                title=title,
                intent=str(intent or ""),
                status=str(status or ""),
                time_horizon=str(time_horizon or ""),
                notes=str(notes or ""),
            )
        )

    return out


def list_beats(*, act_id: str, scene_id: str) -> list[Beat]:
    ensure_play_skeleton()
    scenes_path = _scenes_path(act_id)
    if not scenes_path.exists():
        return []

    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        return []

    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            continue
        beats_raw = item.get("beats")
        if not isinstance(beats_raw, list):
            return []

        beats: list[Beat] = []
        for b in beats_raw:
            if not isinstance(b, dict):
                continue
            beat_id = b.get("beat_id")
            title = b.get("title")
            status = b.get("status")
            notes = b.get("notes")
            link = b.get("link")

            if not isinstance(beat_id, str) or not beat_id:
                continue
            if not isinstance(title, str) or not title:
                continue
            if link is not None and not isinstance(link, str):
                link = None

            beats.append(
                Beat(
                    beat_id=beat_id,
                    title=title,
                    status=str(status or ""),
                    notes=str(notes or ""),
                    link=link,
                )
            )
        return beats

    return []


def _validate_id(*, name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(part in value for part in ("/", "\\", "..")):
        raise ValueError(f"invalid {name}")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def create_act(*, title: str, notes: str = "") -> tuple[list[Act], str]:
    """Create a new Act.

    - Generates a stable act_id.
    - If no act is active yet, the new act becomes active.
    """

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")

    acts, active_id = list_acts()
    act_id = _new_id("act")

    is_active = active_id is None
    acts.append(Act(act_id=act_id, title=title.strip(), active=is_active, notes=notes))
    _write_acts(acts)

    # Ensure the act directory exists for scenes/kb.
    _act_dir(act_id).mkdir(parents=True, exist_ok=True)

    return acts, act_id


def update_act(*, act_id: str, title: str | None = None, notes: str | None = None) -> tuple[list[Act], str | None]:
    """Update an Act's user-editable fields."""

    _validate_id(name="act_id", value=act_id)

    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")

    acts, active_id = list_acts()
    found = False
    updated: list[Act] = []
    for a in acts:
        if a.act_id != act_id:
            updated.append(a)
            continue
        found = True
        updated.append(
            Act(
                act_id=a.act_id,
                title=(title.strip() if isinstance(title, str) else a.title),
                active=bool(a.active),
                notes=(notes if isinstance(notes, str) else a.notes),
            )
        )

    if not found:
        raise ValueError("unknown act_id")

    _write_acts(updated)
    return updated, active_id


def _ensure_scenes_file(*, act_id: str) -> Path:
    _validate_id(name="act_id", value=act_id)
    ensure_play_skeleton()
    act_dir = _act_dir(act_id)
    act_dir.mkdir(parents=True, exist_ok=True)
    p = _scenes_path(act_id)
    if not p.exists():
        _write_json(p, {"scenes": []})
    return p


def create_scene(
    *,
    act_id: str,
    title: str,
    intent: str = "",
    status: str = "",
    time_horizon: str = "",
    notes: str = "",
) -> list[Scene]:
    """Create a Scene under an Act."""

    _validate_id(name="act_id", value=act_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(intent, str):
        raise ValueError("intent must be a string")
    if not isinstance(status, str):
        raise ValueError("status must be a string")
    if not isinstance(time_horizon, str):
        raise ValueError("time_horizon must be a string")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    scene_id = _new_id("scene")
    scenes_raw.append(
        {
            "scene_id": scene_id,
            "title": title.strip(),
            "intent": intent,
            "status": status,
            "time_horizon": time_horizon,
            "notes": notes,
            "beats": [],
        }
    )
    _write_json(scenes_path, {"scenes": scenes_raw})
    return list_scenes(act_id=act_id)


def update_scene(
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> list[Scene]:
    """Update a Scene's fields (beats preserved)."""

    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    found = False
    out: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out.append(item)
            continue
        found = True
        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []
        new_title = title.strip() if isinstance(title, str) and title.strip() else item.get("title")
        if not isinstance(new_title, str) or not new_title.strip():
            raise ValueError("title must be a non-empty string")

        out.append(
            {
                "scene_id": scene_id,
                "title": new_title,
                "intent": (intent if isinstance(intent, str) else str(item.get("intent") or "")),
                "status": (status if isinstance(status, str) else str(item.get("status") or "")),
                "time_horizon": (
                    time_horizon if isinstance(time_horizon, str) else str(item.get("time_horizon") or "")
                ),
                "notes": (notes if isinstance(notes, str) else str(item.get("notes") or "")),
                "beats": beats,
            }
        )

    if not found:
        raise ValueError("unknown scene_id")

    _write_json(scenes_path, {"scenes": out})
    return list_scenes(act_id=act_id)


def create_beat(
    *,
    act_id: str,
    scene_id: str,
    title: str,
    status: str = "",
    notes: str = "",
    link: str | None = None,
) -> list[Beat]:
    """Create a Beat under a Scene."""

    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(status, str):
        raise ValueError("status must be a string")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    beat_id = _new_id("beat")
    found_scene = False
    out: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out.append(item)
            continue
        found_scene = True

        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []
        beats.append(
            {
                "beat_id": beat_id,
                "title": title.strip(),
                "status": status,
                "notes": notes,
                "link": link,
            }
        )
        item = dict(item)
        item["beats"] = beats
        out.append(item)

    if not found_scene:
        raise ValueError("unknown scene_id")

    _write_json(scenes_path, {"scenes": out})
    return list_beats(act_id=act_id, scene_id=scene_id)


def update_beat(
    *,
    act_id: str,
    scene_id: str,
    beat_id: str,
    title: str | None = None,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> list[Beat]:
    """Update a Beat's fields."""

    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    _validate_id(name="beat_id", value=beat_id)
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if status is not None and not isinstance(status, str):
        raise ValueError("status must be a string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    found_scene = False
    found_beat = False
    out_scenes: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out_scenes.append(item)
            continue
        found_scene = True
        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []

        out_beats: list[dict[str, Any]] = []
        for b in beats:
            if not isinstance(b, dict):
                continue
            if b.get("beat_id") != beat_id:
                out_beats.append(b)
                continue
            found_beat = True
            new_title = title.strip() if isinstance(title, str) else str(b.get("title") or "")
            if not new_title.strip():
                raise ValueError("title must be a non-empty string")

            out_beats.append(
                {
                    "beat_id": beat_id,
                    "title": new_title,
                    "status": (status if isinstance(status, str) else str(b.get("status") or "")),
                    "notes": (notes if isinstance(notes, str) else str(b.get("notes") or "")),
                    "link": (link if isinstance(link, str) else b.get("link")),
                }
            )

        item = dict(item)
        item["beats"] = out_beats
        out_scenes.append(item)

    if not found_scene:
        raise ValueError("unknown scene_id")
    if not found_beat:
        raise ValueError("unknown beat_id")

    _write_json(scenes_path, {"scenes": out_scenes})
    return list_beats(act_id=act_id, scene_id=scene_id)


def _kb_root_for(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None) -> Path:
    _validate_id(name="act_id", value=act_id)
    base = play_root() / "kb" / "acts" / act_id
    if scene_id is None:
        return base
    _validate_id(name="scene_id", value=scene_id)
    base = base / "scenes" / scene_id
    if beat_id is None:
        return base
    _validate_id(name="beat_id", value=beat_id)
    return base / "beats" / beat_id


def _resolve_kb_file(*, kb_root: Path, rel_path: str) -> Path:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("path is required")
    p = Path(rel_path)
    if p.is_absolute():
        raise ValueError("path must be relative")
    if any(part in {"..", ""} for part in p.parts):
        raise ValueError("path escapes kb root")
    candidate = (kb_root / p).resolve()
    kb_root_resolved = kb_root.resolve()
    if candidate != kb_root_resolved and kb_root_resolved not in candidate.parents:
        raise ValueError("path escapes kb root")
    return candidate


def kb_list_files(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None) -> list[str]:
    """List markdown/text files under an item's KB root.

    The default KB file is `kb.md` (created on demand).
    """

    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    default = kb_root / "kb.md"
    if not default.exists():
        default.write_text("# KB\n\n", encoding="utf-8")

    files: list[str] = []
    for path in kb_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        files.append(path.relative_to(kb_root).as_posix())

    return sorted(set(files))


def kb_read(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None, path: str = "kb.md") -> str:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)
    if not target.exists():
        if Path(path).as_posix() == "kb.md":
            target.write_text("# KB\n\n", encoding="utf-8")
        else:
            raise FileNotFoundError(path)
    return target.read_text(encoding="utf-8", errors="replace")


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kb_write_preview(
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)

    exists = target.exists() and target.is_file()
    current = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    current_sha = _sha256_text(current)
    new_sha = _sha256_text(text)

    diff_lines = difflib.unified_diff(
        current.splitlines(keepends=True),
        text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    diff = "\n".join(diff_lines)

    return {
        "exists": exists,
        "sha256_current": current_sha,
        "sha256_new": new_sha,
        "diff": diff,
    }


def kb_write_apply(
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)

    exists = target.exists() and target.is_file()
    current = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    current_sha = _sha256_text(current)
    if current_sha != expected_sha256_current:
        raise ValueError("conflict: file changed since preview")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    after_sha = _sha256_text(text)
    return {"ok": True, "sha256_current": after_sha}


# --- File Attachments (stores paths only, not file content) ---


def _attachments_path(*, act_id: str | None = None, scene_id: str | None = None, beat_id: str | None = None) -> Path:
    """Return path to attachments.json for the given level."""
    if act_id is None:
        # Play-level attachments (root level)
        return play_root() / "attachments.json"
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    return kb_root / "attachments.json"


def _load_attachments(path: Path) -> list[dict[str, Any]]:
    """Load attachments list from JSON file."""
    if not path.exists():
        return []
    data = _load_json(path)
    attachments = data.get("attachments")
    return attachments if isinstance(attachments, list) else []


def _write_attachments(path: Path, attachments: list[dict[str, Any]]) -> None:
    """Write attachments list to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"attachments": attachments})


def list_attachments(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> list[FileAttachment]:
    """List file attachments at the specified level (Play, Act, Scene, or Beat)."""
    ensure_play_skeleton()
    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    attachments: list[FileAttachment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        attachment_id = item.get("attachment_id")
        file_path = item.get("file_path")
        file_name = item.get("file_name")
        file_type = item.get("file_type")
        added_at = item.get("added_at")

        if not isinstance(attachment_id, str) or not attachment_id:
            continue
        if not isinstance(file_path, str) or not file_path:
            continue
        if not isinstance(file_name, str):
            file_name = Path(file_path).name
        if not isinstance(file_type, str):
            file_type = Path(file_path).suffix.lstrip(".").lower()
        if not isinstance(added_at, str):
            added_at = ""

        attachments.append(
            FileAttachment(
                attachment_id=attachment_id,
                file_path=file_path,
                file_name=file_name,
                file_type=file_type,
                added_at=added_at,
            )
        )

    return attachments


def add_attachment(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> list[FileAttachment]:
    """Add a file attachment (stores path only, validates file exists).

    If act_id is None, adds to Play-level attachments.
    """
    ensure_play_skeleton()
    if act_id is not None:
        _validate_id(name="act_id", value=act_id)
    if scene_id is not None:
        _validate_id(name="scene_id", value=scene_id)
    if beat_id is not None:
        _validate_id(name="beat_id", value=beat_id)

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("file_path is required")

    # Validate the file exists
    p = Path(file_path)
    if not p.exists():
        raise ValueError(f"file does not exist: {file_path}")
    if not p.is_file():
        raise ValueError(f"path is not a file: {file_path}")

    # Derive file_name and file_type if not provided
    if not file_name:
        file_name = p.name
    file_type = p.suffix.lstrip(".").lower()

    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    # Check for duplicates by path
    for item in raw:
        if isinstance(item, dict) and item.get("file_path") == file_path:
            # Already attached, return current list
            return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)

    attachment_id = _new_id("att")
    added_at = datetime.now(timezone.utc).isoformat()

    raw.append({
        "attachment_id": attachment_id,
        "file_path": file_path,
        "file_name": file_name,
        "file_type": file_type,
        "added_at": added_at,
    })

    _write_attachments(att_path, raw)
    return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)


def remove_attachment(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    attachment_id: str,
) -> list[FileAttachment]:
    """Remove a file attachment reference by ID.

    If act_id is None, removes from Play-level attachments.
    """
    ensure_play_skeleton()
    if act_id is not None:
        _validate_id(name="act_id", value=act_id)
    if scene_id is not None:
        _validate_id(name="scene_id", value=scene_id)
    if beat_id is not None:
        _validate_id(name="beat_id", value=beat_id)
    _validate_id(name="attachment_id", value=attachment_id)

    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    found = False
    updated: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("attachment_id") == attachment_id:
            found = True
            continue
        updated.append(item)

    if not found:
        raise ValueError("unknown attachment_id")

    _write_attachments(att_path, updated)
    return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
