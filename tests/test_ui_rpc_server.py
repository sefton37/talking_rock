"""Tests for UI RPC Server - the bridge between Tauri UI and Python kernel.

The UI RPC server is the main entry point for the desktop app. It handles:
1. JSON-RPC protocol over stdio
2. Authentication (login/logout/validate)
3. Chat messages (delegates to chat handlers)
4. Tool calls (delegates to MCP tools)
5. Play operations (CAIRN's knowledge base)
6. Code execution (RIVA)
7. System operations (ReOS)

These tests verify the RPC layer works correctly WITHOUT requiring
actual LLM calls or system access.
"""

from __future__ import annotations

import json
import pytest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

from reos.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create isolated test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.migrate()
    return db


@pytest.fixture
def reset_rate_limiter():
    """Reset rate limiter between tests."""
    from reos.security import get_rate_limiter
    limiter = get_rate_limiter()
    limiter._requests.clear()
    yield


class TestRpcErrorHandling:
    """Test RPC error handling produces clear messages."""

    def test_rpc_error_has_code_and_message(self) -> None:
        """RpcError should have code and message."""
        from reos.ui_rpc_server import RpcError

        error = RpcError(code=-32600, message="Invalid Request")

        assert error.code == -32600
        assert error.message == "Invalid Request"
        assert str(error) == "Invalid Request"

    def test_rpc_error_can_include_data(self) -> None:
        """RpcError can include additional data for debugging."""
        from reos.ui_rpc_server import RpcError

        error = RpcError(
            code=-32602,
            message="Invalid params",
            data={"param": "text", "error": "must be non-empty"}
        )

        assert error.data["param"] == "text"
        assert "non-empty" in error.data["error"]

    def test_jsonrpc_error_format(self) -> None:
        """Error responses should follow JSON-RPC 2.0 format."""
        from reos.ui_rpc_server import _jsonrpc_error

        response = _jsonrpc_error(
            req_id=42,
            code=-32600,
            message="Invalid Request"
        )

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 42
        assert "error" in response
        assert response["error"]["code"] == -32600
        assert response["error"]["message"] == "Invalid Request"
        assert "result" not in response

    def test_jsonrpc_result_format(self) -> None:
        """Success responses should follow JSON-RPC 2.0 format."""
        from reos.ui_rpc_server import _jsonrpc_result

        response = _jsonrpc_result(
            req_id=42,
            result={"answer": "Hello"}
        )

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 42
        assert "result" in response
        assert response["result"]["answer"] == "Hello"
        assert "error" not in response


class TestAuthenticationHandlers:
    """Test authentication RPC handlers."""

    def test_login_rate_limited_after_threshold(
        self, db: Database, reset_rate_limiter
    ) -> None:
        """Login should be rate limited to prevent brute force."""
        from reos.ui_rpc_server import _handle_auth_login

        # Make many login attempts
        for i in range(10):
            with patch("reos.ui_rpc_server.auth.login") as mock_login:
                mock_login.return_value = {"success": False, "error": "invalid"}
                _handle_auth_login(username="attacker", password="wrong")

        # Next attempt should be rate limited
        result = _handle_auth_login(username="attacker", password="wrong")

        assert result["success"] is False
        assert "rate" in result.get("error", "").lower() or "limit" in result.get("error", "").lower(), (
            f"Should mention rate limit, got: {result}"
        )

    def test_login_success_returns_session_token(
        self, db: Database, reset_rate_limiter
    ) -> None:
        """Successful login should return session token."""
        from reos.ui_rpc_server import _handle_auth_login

        with patch("reos.ui_rpc_server.auth.login") as mock_login:
            mock_login.return_value = {
                "success": True,
                "session_token": "secure-token-12345",
                "username": "testuser",
            }

            result = _handle_auth_login(username="testuser", password="correct")

        assert result["success"] is True
        assert "session_token" in result
        assert result["username"] == "testuser"

    def test_logout_invalidates_session(self) -> None:
        """Logout should invalidate the session."""
        from reos.ui_rpc_server import _handle_auth_logout

        with patch("reos.ui_rpc_server.auth.logout") as mock_logout:
            mock_logout.return_value = {"success": True}

            result = _handle_auth_logout(session_token="token-to-destroy")

        assert result["success"] is True
        mock_logout.assert_called_once_with("token-to-destroy")

    def test_validate_session_checks_token(self) -> None:
        """Validate should check if session is still valid."""
        from reos.ui_rpc_server import _handle_auth_validate

        with patch("reos.ui_rpc_server.auth.validate_session") as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "username": "testuser",
                "expires_in": 3600,
            }

            result = _handle_auth_validate(session_token="valid-token")

        assert result["valid"] is True
        assert result["username"] == "testuser"


class TestToolsHandlers:
    """Test MCP tools RPC handlers."""

    def test_tools_list_returns_all_tools(self) -> None:
        """tools/list should return all available tools."""
        from reos.ui_rpc_server import _tools_list
        from reos.mcp_tools import Tool

        with patch("reos.ui_rpc_server.list_tools") as mock_list:
            mock_list.return_value = [
                Tool(
                    name="linux_system_info",
                    description="Get system information",
                    input_schema={"type": "object", "properties": {}},
                    handler=lambda: {},
                ),
                Tool(
                    name="linux_run_command",
                    description="Run a shell command",
                    input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
                    handler=lambda: {},
                ),
            ]

            result = _tools_list()

        assert "tools" in result
        assert len(result["tools"]) == 2

        tool_names = [t["name"] for t in result["tools"]]
        assert "linux_system_info" in tool_names
        assert "linux_run_command" in tool_names

        # Each tool should have required fields
        for tool in result["tools"]:
            assert "name" in tool, "Tool must have name"
            assert "description" in tool, "Tool must have description"
            assert "inputSchema" in tool, "Tool must have inputSchema"

    def test_tools_call_executes_tool(self, db: Database) -> None:
        """tools/call should execute the specified tool."""
        from reos.ui_rpc_server import _handle_tools_call

        with patch("reos.ui_rpc_server.call_tool") as mock_call:
            mock_call.return_value = {"hostname": "my-machine", "distro": "Ubuntu"}

            result = _handle_tools_call(
                db,
                name="linux_system_info",
                arguments={}
            )

        assert result["hostname"] == "my-machine"
        mock_call.assert_called_once_with(db, name="linux_system_info", arguments={})

    def test_tools_call_error_is_descriptive(self, db: Database) -> None:
        """Tool errors should be descriptive."""
        from reos.ui_rpc_server import _handle_tools_call
        from reos.mcp_tools import ToolError

        with patch("reos.ui_rpc_server.call_tool") as mock_call:
            mock_call.side_effect = ToolError(
                "linux_run_command",
                "Command blocked: 'rm -rf /' is dangerous"
            )

            with pytest.raises(ToolError) as exc_info:
                _handle_tools_call(
                    db,
                    name="linux_run_command",
                    arguments={"command": "rm -rf /"}
                )

        error_msg = str(exc_info.value)
        assert "linux_run_command" in error_msg, "Should include tool name"
        assert "blocked" in error_msg.lower() or "dangerous" in error_msg.lower(), (
            "Should explain why it failed"
        )


class TestChatHandlers:
    """Test chat RPC handlers delegated from UI server."""

    def test_chat_respond_delegates_to_handler(self, db: Database) -> None:
        """chat/respond should delegate to chat handler."""
        # This is tested more thoroughly in test_chat_respond.py
        # Here we just verify the delegation works
        from reos.rpc.handlers.chat import handle_respond

        with patch("reos.rpc.handlers.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.detect_intent.return_value = None
            mock_agent.respond.return_value = MagicMock(
                answer="Test response",
                conversation_id="conv-1",
                message_id="msg-1",
                message_type="text",
                tool_calls=[],
                thinking_steps=[],
                pending_approval_id=None,
                extended_thinking_trace=None,
            )
            mock_agent_class.return_value = mock_agent

            result = handle_respond(db, text="Hello")

        assert result["answer"] == "Test response"


class TestPlayHandlers:
    """Test Play (CAIRN knowledge base) RPC handlers."""

    def test_play_list_acts_returns_acts(self, db: Database) -> None:
        """play/acts/list should return all acts."""
        from reos.ui_rpc_server import _jsonrpc_result
        from reos.play_fs import list_acts, create_act

        # Create some acts
        create_act(db, act_id="act-1", title="Work")
        create_act(db, act_id="act-2", title="Health")

        acts = list_acts(db)

        assert len(acts) >= 2
        titles = [a.title for a in acts]
        assert "Work" in titles
        assert "Health" in titles

    def test_play_create_act_requires_title(self, db: Database) -> None:
        """Creating an act requires a title."""
        from reos.play_fs import create_act

        # Empty title should fail
        with pytest.raises(Exception) as exc_info:
            create_act(db, act_id="act-bad", title="")

        error_msg = str(exc_info.value).lower()
        assert "title" in error_msg or "empty" in error_msg or "required" in error_msg, (
            f"Error should mention title issue, got: {exc_info.value}"
        )


class TestCodeExecutionHandlers:
    """Test code execution (RIVA) RPC handlers."""

    def test_code_exec_requires_prompt(self, db: Database) -> None:
        """Code execution requires a prompt."""
        # The actual code execution is tested in test_riva_integration.py
        # Here we verify the RPC layer validates inputs
        pass  # Placeholder - actual validation in handler


class TestSecurityIntegration:
    """Test security features in UI RPC server."""

    def test_audit_log_called_on_login(
        self, db: Database, reset_rate_limiter
    ) -> None:
        """Login attempts should be audited."""
        from reos.ui_rpc_server import _handle_auth_login

        with patch("reos.ui_rpc_server.auth.login") as mock_login, \
             patch("reos.ui_rpc_server.audit_log") as mock_audit:
            mock_login.return_value = {"success": True, "session_token": "tok"}

            _handle_auth_login(username="testuser", password="pass")

        # Verify audit was called
        mock_audit.assert_called()
        call_args = mock_audit.call_args[0]
        # First arg is event type
        from reos.security import AuditEventType
        assert call_args[0] == AuditEventType.AUTH_LOGIN_SUCCESS

    def test_rate_limit_audited(
        self, db: Database, reset_rate_limiter
    ) -> None:
        """Rate limit violations should be audited."""
        from reos.ui_rpc_server import _handle_auth_login

        with patch("reos.ui_rpc_server.audit_log") as mock_audit:
            # Exhaust rate limit
            for _ in range(15):
                with patch("reos.ui_rpc_server.auth.login") as mock_login:
                    mock_login.return_value = {"success": False}
                    _handle_auth_login(username="attacker", password="wrong")

        # Check that rate limit was audited
        audit_calls = mock_audit.call_args_list
        rate_limit_calls = [
            c for c in audit_calls
            if len(c[0]) > 0 and "RATE_LIMIT" in str(c[0][0])
        ]
        assert len(rate_limit_calls) > 0, "Rate limit should be audited"


class TestJsonRpcProtocol:
    """Test JSON-RPC 2.0 protocol compliance."""

    def test_response_includes_jsonrpc_version(self) -> None:
        """All responses must include jsonrpc: '2.0'."""
        from reos.ui_rpc_server import _jsonrpc_result, _jsonrpc_error

        result = _jsonrpc_result(req_id=1, result={"ok": True})
        assert result["jsonrpc"] == "2.0"

        error = _jsonrpc_error(req_id=1, code=-32600, message="Error")
        assert error["jsonrpc"] == "2.0"

    def test_response_includes_matching_id(self) -> None:
        """Response ID must match request ID."""
        from reos.ui_rpc_server import _jsonrpc_result, _jsonrpc_error

        # Numeric ID
        result = _jsonrpc_result(req_id=42, result={})
        assert result["id"] == 42

        # String ID
        result = _jsonrpc_result(req_id="req-abc", result={})
        assert result["id"] == "req-abc"

        # Null ID (notification response)
        result = _jsonrpc_result(req_id=None, result={})
        assert result["id"] is None

    def test_error_response_has_code_and_message(self) -> None:
        """Error responses must have code and message."""
        from reos.ui_rpc_server import _jsonrpc_error

        error = _jsonrpc_error(
            req_id=1,
            code=-32601,
            message="Method not found"
        )

        assert "error" in error
        assert "code" in error["error"]
        assert "message" in error["error"]
        assert error["error"]["code"] == -32601
        assert error["error"]["message"] == "Method not found"

    def test_error_codes_follow_spec(self) -> None:
        """Error codes should follow JSON-RPC spec."""
        # -32700: Parse error
        # -32600: Invalid Request
        # -32601: Method not found
        # -32602: Invalid params
        # -32603: Internal error
        # -32000 to -32099: Server error (reserved)

        from reos.ui_rpc_server import _jsonrpc_error

        parse_error = _jsonrpc_error(req_id=1, code=-32700, message="Parse error")
        assert parse_error["error"]["code"] == -32700

        invalid_request = _jsonrpc_error(req_id=1, code=-32600, message="Invalid Request")
        assert invalid_request["error"]["code"] == -32600


class TestStdioProtocol:
    """Test stdio communication protocol."""

    def test_write_outputs_json_with_newline(self) -> None:
        """_write should output JSON followed by newline."""
        from reos.ui_rpc_server import _write

        output = StringIO()
        with patch("sys.stdout", output):
            _write({"test": "value"})

        written = output.getvalue()
        assert written.endswith("\n"), "Output must end with newline"

        # Should be valid JSON
        parsed = json.loads(written.strip())
        assert parsed["test"] == "value"

    def test_broken_pipe_causes_clean_exit(self) -> None:
        """Broken pipe (UI closed) should exit cleanly, not crash."""
        from reos.ui_rpc_server import _write

        mock_stdout = MagicMock()
        mock_stdout.write.side_effect = BrokenPipeError()

        with patch("sys.stdout", mock_stdout):
            with pytest.raises(SystemExit) as exc_info:
                _write({"test": "value"})

        # Should exit with code 0 (clean shutdown)
        assert exc_info.value.code == 0
