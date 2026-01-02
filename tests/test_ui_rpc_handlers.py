"""Tests for UI RPC server handlers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def rpc_context(
    tmp_path: Path, isolated_db_singleton: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Path]:
    """Set up isolated context for RPC handler tests."""
    from reos.db import get_db

    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path))
    db = get_db()
    return db, tmp_path


def _call_rpc(db: Any, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Helper to call RPC handler directly."""
    from reos.ui_rpc_server import _handle_jsonrpc_request

    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    return _handle_jsonrpc_request(db, req)


class TestInitializeAndPing:
    def test_initialize_returns_protocol_info(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "initialize")
        assert resp["result"]["protocolVersion"] == "jsonrpc-2.0"
        assert resp["result"]["serverInfo"]["name"] == "reos-ui-kernel"

    def test_ping_returns_ok(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "ping")
        assert resp["result"]["ok"] is True


class TestToolsRpc:
    def test_tools_list_returns_tools(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "tools/list")
        assert "tools" in resp["result"]
        tools = resp["result"]["tools"]
        assert isinstance(tools, list)
        # Should have at least some tools
        assert len(tools) > 0
        # Each tool should have required fields
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


class TestStateRpc:
    def test_state_get_missing_key(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "state/get", {"key": "nonexistent"})
        assert resp["result"]["key"] == "nonexistent"
        assert resp["result"]["value"] is None

    def test_state_set_and_get(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Set
        resp = _call_rpc(db, "state/set", {"key": "test_key", "value": "test_value"})
        assert resp["result"]["ok"] is True

        # Get
        resp = _call_rpc(db, "state/get", {"key": "test_key"})
        assert resp["result"]["value"] == "test_value"

    def test_state_set_requires_key(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "state/set", {"value": "test"})
        assert "error" in resp
        assert resp["error"]["code"] == -32602


class TestPlayActsRpc:
    def test_acts_list_initially_empty(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "play/acts/list")
        assert resp["result"]["acts"] == []
        assert resp["result"]["active_act_id"] is None

    def test_acts_create(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "play/acts/create", {"title": "My First Act"})
        result = resp["result"]
        assert "created_act_id" in result
        assert len(result["acts"]) == 1
        assert result["acts"][0]["title"] == "My First Act"
        # First act should be active
        assert result["acts"][0]["active"] is True

    def test_acts_create_requires_title(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "play/acts/create", {"title": ""})
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    def test_acts_update(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Create
        create_resp = _call_rpc(db, "play/acts/create", {"title": "Original"})
        act_id = create_resp["result"]["created_act_id"]

        # Update
        resp = _call_rpc(
            db, "play/acts/update", {"act_id": act_id, "title": "Updated", "notes": "Some notes"}
        )
        updated = [a for a in resp["result"]["acts"] if a["act_id"] == act_id][0]
        assert updated["title"] == "Updated"
        assert updated["notes"] == "Some notes"

    def test_acts_set_active(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Create two acts
        _call_rpc(db, "play/acts/create", {"title": "Act One"})
        resp = _call_rpc(db, "play/acts/create", {"title": "Act Two"})
        act2_id = resp["result"]["created_act_id"]

        # First act should be active initially
        list_resp = _call_rpc(db, "play/acts/list")
        assert list_resp["result"]["acts"][0]["active"] is True

        # Set second act as active
        resp = _call_rpc(db, "play/acts/set_active", {"act_id": act2_id})
        assert resp["result"]["active_act_id"] == act2_id

    def test_acts_set_active_unknown_id(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "play/acts/set_active", {"act_id": "nonexistent"})
        assert "error" in resp
        assert resp["error"]["code"] == -32602


class TestPlayScenesRpc:
    def test_scenes_list_empty(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Create act first
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        resp = _call_rpc(db, "play/scenes/list", {"act_id": act_id})
        assert resp["result"]["scenes"] == []

    def test_scenes_create(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        resp = _call_rpc(
            db,
            "play/scenes/create",
            {
                "act_id": act_id,
                "title": "Scene One",
                "intent": "Test the system",
                "status": "in_progress",
            },
        )
        scenes = resp["result"]["scenes"]
        assert len(scenes) == 1
        assert scenes[0]["title"] == "Scene One"
        assert scenes[0]["intent"] == "Test the system"

    def test_scenes_update(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        scene_resp = _call_rpc(
            db, "play/scenes/create", {"act_id": act_id, "title": "Original Scene"}
        )
        scene_id = scene_resp["result"]["scenes"][0]["scene_id"]

        resp = _call_rpc(
            db,
            "play/scenes/update",
            {"act_id": act_id, "scene_id": scene_id, "title": "Updated Scene", "status": "done"},
        )
        updated = resp["result"]["scenes"][0]
        assert updated["title"] == "Updated Scene"
        assert updated["status"] == "done"


class TestPlayBeatsRpc:
    def test_beats_create_and_list(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Setup: create act and scene
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        scene_resp = _call_rpc(db, "play/scenes/create", {"act_id": act_id, "title": "Test Scene"})
        scene_id = scene_resp["result"]["scenes"][0]["scene_id"]

        # Create beat
        resp = _call_rpc(
            db,
            "play/beats/create",
            {
                "act_id": act_id,
                "scene_id": scene_id,
                "title": "Beat One",
                "status": "pending",
                "link": "https://example.com",
            },
        )
        beats = resp["result"]["beats"]
        assert len(beats) == 1
        assert beats[0]["title"] == "Beat One"
        assert beats[0]["link"] == "https://example.com"

        # List
        list_resp = _call_rpc(db, "play/beats/list", {"act_id": act_id, "scene_id": scene_id})
        assert len(list_resp["result"]["beats"]) == 1


class TestPlayKbRpc:
    def test_kb_list_creates_default(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        resp = _call_rpc(db, "play/kb/list", {"act_id": act_id})
        files = resp["result"]["files"]
        assert "kb.md" in files

    def test_kb_read_default(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        resp = _call_rpc(db, "play/kb/read", {"act_id": act_id, "path": "kb.md"})
        assert resp["result"]["path"] == "kb.md"
        assert "# KB" in resp["result"]["text"]

    def test_kb_write_preview_and_apply(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        # Preview
        preview_resp = _call_rpc(
            db,
            "play/kb/write_preview",
            {"act_id": act_id, "path": "kb.md", "text": "# Updated\n\nNew content.\n"},
        )
        preview = preview_resp["result"]
        assert "diff" in preview
        expected_sha = preview["expected_sha256_current"]

        # Apply
        apply_resp = _call_rpc(
            db,
            "play/kb/write_apply",
            {
                "act_id": act_id,
                "path": "kb.md",
                "text": "# Updated\n\nNew content.\n",
                "expected_sha256_current": expected_sha,
            },
        )
        assert apply_resp["result"]["ok"] is True

        # Verify
        read_resp = _call_rpc(db, "play/kb/read", {"act_id": act_id, "path": "kb.md"})
        assert read_resp["result"]["text"] == "# Updated\n\nNew content.\n"

    def test_kb_write_apply_conflict(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        # Try to apply with wrong sha
        resp = _call_rpc(
            db,
            "play/kb/write_apply",
            {
                "act_id": act_id,
                "path": "kb.md",
                "text": "# Bad\n",
                "expected_sha256_current": "0" * 64,
            },
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32009  # Conflict error code
        assert "conflict" in resp["error"]["message"]


class TestPersonasRpc:
    def test_personas_list_initially_empty(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "personas/list")
        assert resp["result"]["personas"] == []
        assert resp["result"]["active_persona_id"] is None

    def test_persona_upsert_and_get(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        persona = {
            "id": "test-persona",
            "name": "Test Persona",
            "system_prompt": "You are a test assistant.",
            "default_context": "Testing context",
            "temperature": 0.7,
            "top_p": 0.9,
            "tool_call_limit": 5,
        }
        resp = _call_rpc(db, "personas/upsert", {"persona": persona})
        assert resp["result"]["ok"] is True

        # Get
        get_resp = _call_rpc(db, "personas/get", {"persona_id": "test-persona"})
        assert get_resp["result"]["persona"] is not None

    def test_persona_set_active(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        # Create persona
        persona = {
            "id": "active-test",
            "name": "Active Test",
            "system_prompt": "Test",
            "default_context": "",
            "temperature": 0.5,
            "top_p": 1.0,
            "tool_call_limit": 3,
        }
        _call_rpc(db, "personas/upsert", {"persona": persona})

        # Set active
        resp = _call_rpc(db, "personas/set_active", {"persona_id": "active-test"})
        assert resp["result"]["ok"] is True

        # Verify
        list_resp = _call_rpc(db, "personas/list")
        assert list_resp["result"]["active_persona_id"] == "active-test"


class TestErrorHandling:
    def test_unknown_method_returns_error(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "unknown/method")
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_missing_params_returns_error(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        resp = _call_rpc(db, "play/acts/create", {})  # Missing title
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    def test_invalid_params_type_returns_error(self, rpc_context: tuple) -> None:
        db, _ = rpc_context
        from reos.ui_rpc_server import _handle_jsonrpc_request

        req = {"jsonrpc": "2.0", "id": 1, "method": "state/get", "params": "not-an-object"}
        resp = _handle_jsonrpc_request(db, req)
        assert "error" in resp
        assert resp["error"]["code"] == -32602


class TestInputValidation:
    """Tests for input validation to prevent resource exhaustion."""

    def test_title_length_validation(self, rpc_context: tuple) -> None:
        """Title exceeding MAX_TITLE_LENGTH should be rejected."""
        db, _ = rpc_context
        long_title = "x" * 600  # Exceeds MAX_TITLE_LENGTH (500)
        resp = _call_rpc(db, "play/acts/create", {"title": long_title})
        assert "error" in resp
        assert resp["error"]["code"] == -32602
        assert "maximum length" in resp["error"]["message"]

    def test_notes_length_validation(self, rpc_context: tuple) -> None:
        """Notes exceeding MAX_NOTES_LENGTH should be rejected."""
        db, _ = rpc_context
        # Create act first
        act_resp = _call_rpc(db, "play/acts/create", {"title": "Test Act"})
        act_id = act_resp["result"]["created_act_id"]

        long_notes = "x" * 60_000  # Exceeds MAX_NOTES_LENGTH (50_000)
        resp = _call_rpc(
            db, "play/acts/update", {"act_id": act_id, "notes": long_notes}
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32602
        assert "maximum length" in resp["error"]["message"]

    def test_persona_system_prompt_length_validation(self, rpc_context: tuple) -> None:
        """Persona system_prompt exceeding MAX_SYSTEM_PROMPT_LENGTH should be rejected."""
        db, _ = rpc_context
        long_prompt = "x" * 110_000  # Exceeds MAX_SYSTEM_PROMPT_LENGTH (100_000)
        persona = {
            "id": "test-long-prompt",
            "name": "Test",
            "system_prompt": long_prompt,
            "default_context": "",
            "temperature": 0.7,
            "top_p": 0.9,
            "tool_call_limit": 5,
        }
        resp = _call_rpc(db, "personas/upsert", {"persona": persona})
        assert "error" in resp
        assert resp["error"]["code"] == -32602
        assert "maximum length" in resp["error"]["message"]

    def test_persona_id_length_validation(self, rpc_context: tuple) -> None:
        """Persona id exceeding MAX_ID_LENGTH should be rejected."""
        db, _ = rpc_context
        long_id = "x" * 250  # Exceeds MAX_ID_LENGTH (200)
        persona = {
            "id": long_id,
            "name": "Test",
            "system_prompt": "test",
            "default_context": "",
            "temperature": 0.7,
            "top_p": 0.9,
            "tool_call_limit": 5,
        }
        resp = _call_rpc(db, "personas/upsert", {"persona": persona})
        assert "error" in resp
        assert resp["error"]["code"] == -32602
        assert "maximum length" in resp["error"]["message"]

    def test_valid_length_inputs_accepted(self, rpc_context: tuple) -> None:
        """Inputs within limits should be accepted."""
        db, _ = rpc_context
        # Just under limit should work
        title = "x" * 499  # Under MAX_TITLE_LENGTH (500)
        resp = _call_rpc(db, "play/acts/create", {"title": title})
        assert "error" not in resp
        assert "created_act_id" in resp["result"]
