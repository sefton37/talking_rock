from __future__ import annotations

import json
from pathlib import Path

import pytest

from reos.db import get_db


def _extract_text_content(result: dict) -> str:
    assert isinstance(result, dict)
    content = result.get("content")
    assert isinstance(content, list)
    assert len(content) >= 1
    first = content[0]
    assert isinstance(first, dict)
    assert first.get("type") == "text"
    text = first.get("text")
    assert isinstance(text, str)
    return text


def test_mcp_tools_call_returns_text_envelope(configured_repo: Path) -> None:
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(
        db,
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "reos_repo_list_files", "arguments": {"glob": "src/reos/*.py"}},
        },
    )

    assert resp is not None
    assert "result" in resp

    text = _extract_text_content(resp["result"])
    # Tool results are rendered JSON strings.
    payload = json.loads(text)
    assert "src/reos/example.py" in payload


def test_mcp_tools_call_invalid_args_maps_to_32602(configured_repo: Path) -> None:
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(
        db,
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "reos_repo_list_files", "arguments": {}},
        },
    )

    assert resp is not None
    assert resp["error"]["code"] == -32602


def test_mcp_tools_call_path_escape_maps_to_32000(configured_repo: Path) -> None:
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(
        db,
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "reos_repo_read_file",
                "arguments": {"path": "../secrets.txt", "start_line": 1, "end_line": 1},
            },
        },
    )

    assert resp is not None
    assert resp["error"]["code"] == -32000
    data = resp["error"].get("data")
    assert isinstance(data, dict)
    assert data.get("path") == "../secrets.txt"


def test_mcp_notifications_are_ignored(configured_repo: Path) -> None:
    import reos.mcp_server as mcp

    db = get_db()
    # Notification: no id
    resp = mcp._handle_jsonrpc_request(
        db,
        {
            "jsonrpc": "2.0",
            "method": "tools/list",
        },
    )
    assert resp is None
