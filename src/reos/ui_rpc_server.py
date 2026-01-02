"""UI RPC server for the ReOS desktop app.

This is a small JSON-RPC 2.0 server over stdio intended to be used by a
TypeScript desktop shell (Tauri).

Design goals:
- Local-only (stdio; no network listener).
- Metadata-first by default.
- Stable, explicit contract between UI and kernel.

This is intentionally *not* MCP; it's a UI-facing RPC layer. We still expose
`tools/list` + `tools/call` by delegating to the existing repo-scoped tool
catalog so the UI can reuse those capabilities.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .agent import ChatAgent
from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools
from .play_fs import create_act as play_create_act
from .play_fs import create_beat as play_create_beat
from .play_fs import create_scene as play_create_scene
from .play_fs import kb_list_files as play_kb_list_files
from .play_fs import kb_read as play_kb_read
from .play_fs import kb_write_apply as play_kb_write_apply
from .play_fs import kb_write_preview as play_kb_write_preview
from .play_fs import list_acts as play_list_acts
from .play_fs import list_beats as play_list_beats
from .play_fs import list_scenes as play_list_scenes
from .play_fs import read_me_markdown as play_read_me_markdown
from .play_fs import set_active_act_id as play_set_active_act_id
from .play_fs import update_act as play_update_act
from .play_fs import update_beat as play_update_beat
from .play_fs import update_scene as play_update_scene

_JSON = dict[str, Any]

# Input validation limits to prevent resource exhaustion
MAX_TITLE_LENGTH = 500
MAX_NOTES_LENGTH = 50_000  # 50KB
MAX_TEXT_LENGTH = 500_000  # 500KB for KB files
MAX_PATH_LENGTH = 1000
MAX_ID_LENGTH = 200
MAX_SYSTEM_PROMPT_LENGTH = 100_000  # 100KB
MAX_LIST_LIMIT = 10_000


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _validate_string_length(value: str, max_length: int, field_name: str) -> None:
    """Validate that a string doesn't exceed the maximum length."""
    if len(value) > max_length:
        raise RpcError(
            code=-32602,
            message=f"{field_name} exceeds maximum length of {max_length} characters",
        )


def _validate_required_string(
    params: dict[str, Any], key: str, max_length: int, *, allow_empty: bool = False
) -> str:
    """Extract and validate a required string parameter."""
    value = params.get(key)
    if not isinstance(value, str):
        raise RpcError(code=-32602, message=f"{key} is required")
    if not allow_empty and not value.strip():
        raise RpcError(code=-32602, message=f"{key} is required")
    _validate_string_length(value, max_length, key)
    return value


def _validate_optional_string(
    params: dict[str, Any], key: str, max_length: int, *, default: str | None = None
) -> str | None:
    """Extract and validate an optional string parameter."""
    value = params.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RpcError(code=-32602, message=f"{key} must be a string or null")
    _validate_string_length(value, max_length, key)
    return value


def _jsonrpc_error(*, req_id: Any, code: int, message: str, data: Any | None = None) -> _JSON:
    err: _JSON = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _jsonrpc_result(*, req_id: Any, result: Any) -> _JSON:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _readline() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line


def _write(obj: Any) -> None:
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Client closed the pipe (e.g., UI exited). Treat as a clean shutdown.
        raise SystemExit(0) from None


def _tools_list() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in list_tools()
        ]
    }


def _handle_tools_call(db: Database, *, name: str, arguments: dict[str, Any] | None) -> Any:
    try:
        return call_tool(db, name=name, arguments=arguments)
    except ToolError as exc:
        # -32602: invalid params
        code = -32602 if exc.code in {"invalid_args", "path_escape"} else -32000
        raise RpcError(code=code, message=exc.message, data=exc.data) from exc


def _handle_chat_respond(db: Database, *, text: str) -> dict[str, Any]:
    agent = ChatAgent(db=db)
    answer = agent.respond(text)
    return {"answer": answer}


def _handle_state_get(db: Database, *, key: str) -> dict[str, Any]:
    return {"key": key, "value": db.get_state(key=key)}


def _handle_state_set(db: Database, *, key: str, value: str | None) -> dict[str, Any]:
    db.set_state(key=key, value=value)
    return {"ok": True}


def _handle_personas_list(db: Database) -> dict[str, Any]:
    return {"personas": db.iter_agent_personas(), "active_persona_id": db.get_active_persona_id()}


def _handle_persona_get(db: Database, *, persona_id: str) -> dict[str, Any]:
    persona = db.get_agent_persona(persona_id=persona_id)
    return {"persona": persona}


def _handle_persona_upsert(db: Database, *, persona: dict[str, Any]) -> dict[str, Any]:
    required = {
        "id",
        "name",
        "system_prompt",
        "default_context",
        "temperature",
        "top_p",
        "tool_call_limit",
    }
    missing = sorted(required - set(persona.keys()))
    if missing:
        raise RpcError(code=-32602, message=f"persona missing fields: {', '.join(missing)}")

    # Validate string field lengths
    persona_id = str(persona["id"])
    name = str(persona["name"])
    system_prompt = str(persona["system_prompt"])
    default_context = str(persona["default_context"])

    _validate_string_length(persona_id, MAX_ID_LENGTH, "id")
    _validate_string_length(name, MAX_TITLE_LENGTH, "name")
    _validate_string_length(system_prompt, MAX_SYSTEM_PROMPT_LENGTH, "system_prompt")
    _validate_string_length(default_context, MAX_SYSTEM_PROMPT_LENGTH, "default_context")

    db.upsert_agent_persona(
        persona_id=persona_id,
        name=name,
        system_prompt=system_prompt,
        default_context=default_context,
        temperature=float(persona["temperature"]),
        top_p=float(persona["top_p"]),
        tool_call_limit=int(persona["tool_call_limit"]),
    )
    return {"ok": True}


def _handle_persona_set_active(db: Database, *, persona_id: str | None) -> dict[str, Any]:
    if persona_id is not None and not isinstance(persona_id, str):
        raise RpcError(code=-32602, message="persona_id must be a string or null")
    db.set_active_persona_id(persona_id=persona_id)
    return {"ok": True}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _handle_play_me_read(_db: Database) -> dict[str, Any]:
    return {"markdown": play_read_me_markdown()}


def _handle_play_acts_list(_db: Database) -> dict[str, Any]:
    acts, active_id = play_list_acts()
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_set_active(_db: Database, *, act_id: str) -> dict[str, Any]:
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_scenes_list(_db: Database, *, act_id: str) -> dict[str, Any]:
    scenes = play_list_scenes(act_id=act_id)
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


def _handle_play_beats_list(_db: Database, *, act_id: str, scene_id: str) -> dict[str, Any]:
    beats = play_list_beats(act_id=act_id, scene_id=scene_id)
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


def _handle_play_acts_create(_db: Database, *, title: str, notes: str | None = None) -> dict[str, Any]:
    try:
        acts, created_id = play_create_act(title=title, notes=notes or "")
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "created_act_id": created_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_scenes_create(
    _db: Database,
    *,
    act_id: str,
    title: str,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
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
        raise RpcError(code=-32602, message=str(exc)) from exc
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


def _handle_play_scenes_update(
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
        raise RpcError(code=-32602, message=str(exc)) from exc
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


def _handle_play_beats_create(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
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
        raise RpcError(code=-32602, message=str(exc)) from exc
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


def _handle_play_beats_update(
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
        raise RpcError(code=-32602, message=str(exc)) from exc
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


def _handle_play_kb_list(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    try:
        files = play_kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"files": files}


def _handle_play_kb_read(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str = "kb.md",
) -> dict[str, Any]:
    try:
        text = play_kb_read(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path)
    except FileNotFoundError as exc:
        raise RpcError(code=-32602, message=f"file not found: {exc}") from exc
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"path": path, "text": text}


def _handle_play_kb_write_preview(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    try:
        res = play_kb_write_preview(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path, text=text)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "path": path,
        "expected_sha256_current": res["sha256_current"],
        **res,
    }


def _handle_play_kb_write_apply(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=-32602, message="expected_sha256_current is required")
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


def _handle_jsonrpc_request(db: Database, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "jsonrpc-2.0",
                "serverInfo": {"name": "reos-ui-kernel", "version": "0.1.0"},
            }
            return _jsonrpc_result(req_id=req_id, result=result)

        # Notifications can omit id; ignore.
        if req_id is None:
            return None

        if method == "ping":
            return _jsonrpc_result(req_id=req_id, result={"ok": True})

        if method == "tools/list":
            return _jsonrpc_result(req_id=req_id, result=_tools_list())

        if method == "tools/call":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str) or not name:
                raise RpcError(code=-32602, message="name is required")
            if arguments is not None and not isinstance(arguments, dict):
                raise RpcError(code=-32602, message="arguments must be an object")
            result = _handle_tools_call(db, name=name, arguments=arguments)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "chat/respond":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = _validate_required_string(params, "text", MAX_TEXT_LENGTH)
            result = _handle_chat_respond(db, text=text)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "state/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = params.get("key")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_state_get(db, key=key))

        if method == "state/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = _validate_required_string(params, "key", MAX_ID_LENGTH)
            value = _validate_optional_string(params, "value", MAX_NOTES_LENGTH)
            return _jsonrpc_result(req_id=req_id, result=_handle_state_set(db, key=key, value=value))

        if method == "personas/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_personas_list(db))

        if method == "personas/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if not isinstance(persona_id, str) or not persona_id:
                raise RpcError(code=-32602, message="persona_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_get(db, persona_id=persona_id))

        if method == "personas/upsert":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona = params.get("persona")
            if not isinstance(persona, dict):
                raise RpcError(code=-32602, message="persona must be an object")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_upsert(db, persona=persona))

        if method == "personas/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if persona_id is not None and not isinstance(persona_id, str):
                raise RpcError(code=-32602, message="persona_id must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_set_active(db, persona_id=persona_id))

        if method == "play/me/read":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_me_read(db))

        if method == "play/acts/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_list(db))

        if method == "play/acts/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            title = _validate_required_string(params, "title", MAX_TITLE_LENGTH)
            notes = _validate_optional_string(params, "notes", MAX_NOTES_LENGTH)
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_create(db, title=title, notes=notes))

        if method == "play/acts/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = _validate_required_string(params, "act_id", MAX_ID_LENGTH)
            title = _validate_optional_string(params, "title", MAX_TITLE_LENGTH)
            notes = _validate_optional_string(params, "notes", MAX_NOTES_LENGTH)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_acts_update(db, act_id=act_id, title=title, notes=notes),
            )

        if method == "play/acts/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_set_active(db, act_id=act_id))

        if method == "play/scenes/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_scenes_list(db, act_id=act_id))

        if method == "play/scenes/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_create(
                    db,
                    act_id=act_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/scenes/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            title = params.get("title")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "title": title,
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/beats/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_list(db, act_id=act_id, scene_id=scene_id),
            )

        if method == "play/beats/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"status": status, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_create(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    status=status,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/beats/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(beat_id, str) or not beat_id:
                raise RpcError(code=-32602, message="beat_id is required")
            title = params.get("title")
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"title": title, "status": status, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    title=title,
                    status=status,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/kb/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_list(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id),
            )

        if method == "play/kb/read":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path", "kb.md")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id, "path": path}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_read(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path),
            )

        if method == "play/kb/write_preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = _validate_required_string(params, "act_id", MAX_ID_LENGTH)
            scene_id = _validate_optional_string(params, "scene_id", MAX_ID_LENGTH)
            beat_id = _validate_optional_string(params, "beat_id", MAX_ID_LENGTH)
            path = _validate_required_string(params, "path", MAX_PATH_LENGTH)
            text = _validate_required_string(params, "text", MAX_TEXT_LENGTH, allow_empty=True)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_preview(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                ),
            )

        if method == "play/kb/write_apply":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = _validate_required_string(params, "act_id", MAX_ID_LENGTH)
            scene_id = _validate_optional_string(params, "scene_id", MAX_ID_LENGTH)
            beat_id = _validate_optional_string(params, "beat_id", MAX_ID_LENGTH)
            path = _validate_required_string(params, "path", MAX_PATH_LENGTH)
            text = _validate_required_string(params, "text", MAX_TEXT_LENGTH, allow_empty=True)
            expected_sha256_current = _validate_required_string(params, "expected_sha256_current", MAX_ID_LENGTH)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_apply(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                    expected_sha256_current=expected_sha256_current,
                ),
            )

        raise RpcError(code=-32601, message=f"Method not found: {method}")

    except RpcError as exc:
        return _jsonrpc_error(req_id=req_id, code=exc.code, message=exc.message, data=exc.data)
    except Exception as exc:  # noqa: BLE001
        return _jsonrpc_error(
            req_id=req_id,
            code=-32099,
            message="Internal error",
            data={"error": str(exc)},
        )


def run_stdio_server() -> None:
    """Run the UI kernel server over stdio."""

    db = get_db()
    db.migrate()

    while True:
        line = _readline()
        if line is None:
            return

        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(req, dict):
            continue

        resp = _handle_jsonrpc_request(db, req)
        if resp is not None:
            _write(resp)


def main() -> None:
    run_stdio_server()


if __name__ == "__main__":
    main()
