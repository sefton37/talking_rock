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

import difflib
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .agent import ChatAgent
from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools
from .projects_fs import get_project_paths, is_valid_project_id, kb_relative_tree, read_text, workspace_root

_JSON = dict[str, Any]


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


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

    db.upsert_agent_persona(
        persona_id=str(persona["id"]),
        name=str(persona["name"]),
        system_prompt=str(persona["system_prompt"]),
        default_context=str(persona["default_context"]),
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


def _handle_projects_list(db: Database) -> dict[str, Any]:
    # We intentionally treat projects as filesystem-backed first.
    from .projects_fs import list_project_ids

    return {
        "projects": list_project_ids(),
        "active_project_id": db.get_active_project_id(),
    }


def _handle_project_set_active(db: Database, *, project_id: str | None) -> dict[str, Any]:
    if project_id is None:
        db.set_active_project_id(project_id=None)
        return {"ok": True}

    if not isinstance(project_id, str) or not project_id:
        raise RpcError(code=-32602, message="project_id must be a non-empty string or null")
    if not is_valid_project_id(project_id):
        raise RpcError(code=-32602, message="invalid project_id")
    db.set_active_project_id(project_id=project_id)
    return {"ok": True}


def _handle_kb_tree(db: Database, *, project_id: str | None) -> dict[str, Any]:
    if project_id is None:
        project_id = db.get_active_project_id()
    if not project_id:
        return {"files": [], "project_id": None}
    if not is_valid_project_id(project_id):
        raise RpcError(code=-32602, message="invalid project_id")
    return {"files": kb_relative_tree(project_id), "project_id": project_id}


def _resolve_kb_path(*, project_id: str, rel_path: str) -> Path:
    # Only allow reads under: projects/<project-id>/kb/
    if not is_valid_project_id(project_id):
        raise RpcError(code=-32602, message="invalid project_id")
    if not isinstance(rel_path, str) or not rel_path:
        raise RpcError(code=-32602, message="path is required")

    root = workspace_root()
    paths = get_project_paths(project_id)
    kb_root = paths.kb_dir.resolve()

    # Allow either:
    # - "projects/<id>/kb/..." (workspace-relative)
    # - "kb/..." or "pages/..." (kb-relative)
    candidate: Path
    if rel_path.startswith("projects/"):
        candidate = (root / rel_path).resolve()
    else:
        candidate = (kb_root / rel_path).resolve()

    if kb_root not in candidate.parents and candidate != kb_root:
        raise RpcError(code=-32602, message="path escapes kb root")
    return candidate


def _handle_kb_read(db: Database, *, project_id: str | None, path: str) -> dict[str, Any]:
    if project_id is None:
        project_id = db.get_active_project_id()
    if not project_id:
        raise RpcError(code=-32602, message="project_id is required (or set an active project)")

    abs_path = _resolve_kb_path(project_id=project_id, rel_path=path)
    if not abs_path.exists() or not abs_path.is_file():
        raise RpcError(code=-32602, message="file not found")
    return {
        "path": str(abs_path.relative_to(workspace_root())),
        "text": read_text(abs_path),
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _handle_kb_write_preview(
    db: Database,
    *,
    project_id: str | None,
    path: str,
    text: str,
) -> dict[str, Any]:
    if project_id is None:
        project_id = db.get_active_project_id()
    if not project_id:
        raise RpcError(code=-32602, message="project_id is required (or set an active project)")

    abs_path = _resolve_kb_path(project_id=project_id, rel_path=path)
    if abs_path.exists() and abs_path.is_dir():
        raise RpcError(code=-32602, message="path points to a directory")

    exists = abs_path.exists() and abs_path.is_file()
    current = read_text(abs_path) if exists else ""

    current_sha = _sha256_text(current)
    new_sha = _sha256_text(text)

    rel = str(abs_path.relative_to(workspace_root()))
    diff_lines = difflib.unified_diff(
        current.splitlines(keepends=True),
        text.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        lineterm="",
    )
    diff = "\n".join(diff_lines)
    return {
        "project_id": project_id,
        "path": rel,
        "exists": exists,
        "sha256_current": current_sha,
        "sha256_new": new_sha,
        "diff": diff,
    }


def _handle_kb_write_apply(
    db: Database,
    *,
    project_id: str | None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    if project_id is None:
        project_id = db.get_active_project_id()
    if not project_id:
        raise RpcError(code=-32602, message="project_id is required (or set an active project)")
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=-32602, message="expected_sha256_current is required")

    abs_path = _resolve_kb_path(project_id=project_id, rel_path=path)
    if abs_path.exists() and abs_path.is_dir():
        raise RpcError(code=-32602, message="path points to a directory")

    exists = abs_path.exists() and abs_path.is_file()
    current = read_text(abs_path) if exists else ""
    current_sha = _sha256_text(current)
    if current_sha != expected_sha256_current:
        raise RpcError(
            code=-32009,
            message="conflict: file changed since preview",
            data={
                "path": str(abs_path.relative_to(workspace_root())),
                "sha256_current": current_sha,
            },
        )

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(text, encoding="utf-8")
    after_sha = _sha256_text(text)
    return {
        "ok": True,
        "project_id": project_id,
        "path": str(abs_path.relative_to(workspace_root())),
        "sha256_current": after_sha,
    }


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
            text = params.get("text")
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
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
            key = params.get("key")
            value = params.get("value")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            if value is not None and not isinstance(value, str):
                raise RpcError(code=-32602, message="value must be a string or null")
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

        if method == "projects/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_projects_list(db))

        if method == "projects/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            project_id = params.get("project_id")
            if project_id is not None and not isinstance(project_id, str):
                raise RpcError(code=-32602, message="project_id must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_project_set_active(db, project_id=project_id))

        if method == "kb/tree":
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            project_id = params.get("project_id")
            if project_id is not None and not isinstance(project_id, str):
                raise RpcError(code=-32602, message="project_id must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_kb_tree(db, project_id=project_id))

        if method == "kb/read":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            project_id = params.get("project_id")
            path = params.get("path")
            if project_id is not None and not isinstance(project_id, str):
                raise RpcError(code=-32602, message="project_id must be a string or null")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_kb_read(db, project_id=project_id, path=path),
            )

        if method == "kb/write_preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            project_id = params.get("project_id")
            path = params.get("path")
            text = params.get("text")
            if project_id is not None and not isinstance(project_id, str):
                raise RpcError(code=-32602, message="project_id must be a string or null")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_kb_write_preview(db, project_id=project_id, path=path, text=text),
            )

        if method == "kb/write_apply":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            project_id = params.get("project_id")
            path = params.get("path")
            text = params.get("text")
            expected_sha256_current = params.get("expected_sha256_current")
            if project_id is not None and not isinstance(project_id, str):
                raise RpcError(code=-32602, message="project_id must be a string or null")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
                raise RpcError(code=-32602, message="expected_sha256_current is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_kb_write_apply(
                    db,
                    project_id=project_id,
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
