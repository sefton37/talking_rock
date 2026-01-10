"""Tests for chat/respond RPC endpoint - the main conversation entry point.

This is the primary interface users interact with through the Tauri UI.
Every chat message goes through this endpoint.

Tests cover:
1. Basic message handling
2. Conversation context persistence
3. Agent type selection (CAIRN/ReOS/RIVA)
4. Intent detection (approval/rejection)
5. Error handling with clear messages
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from reos.db import Database
from reos.rpc.handlers.chat import handle_respond, handle_clear, handle_intent_detect
from reos.rpc.types import RpcError


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create isolated test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.migrate()
    return db


@pytest.fixture
def mock_llm_response() -> MagicMock:
    """Mock LLM that returns a simple response."""
    mock = MagicMock()
    mock.chat.return_value = {
        "message": {"content": "I can help you with that."}
    }
    return mock


class TestChatRespondBasics:
    """Test basic chat/respond functionality."""

    def test_empty_text_returns_error(self, db: Database) -> None:
        """Empty message should fail with clear error."""
        with pytest.raises(Exception) as exc_info:
            handle_respond(db, text="")

        error_msg = str(exc_info.value).lower()
        assert "text" in error_msg or "empty" in error_msg or "required" in error_msg, (
            f"Error should mention text/empty/required, got: {exc_info.value}"
        )

    def test_whitespace_only_text_returns_error(self, db: Database) -> None:
        """Whitespace-only message should fail with clear error."""
        with pytest.raises(Exception) as exc_info:
            handle_respond(db, text="   \n\t  ")

        error_msg = str(exc_info.value).lower()
        assert any(word in error_msg for word in ["text", "empty", "whitespace", "required"]), (
            f"Error should be descriptive, got: {exc_info.value}"
        )

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_basic_message_returns_response_structure(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Valid message should return properly structured response."""
        # Setup mock
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="Hello! I'm CAIRN.",
            conversation_id="conv-123",
            message_id="msg-456",
            message_type="text",
            tool_calls=[],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        result = handle_respond(db, text="Hello")

        # Verify response structure
        assert "answer" in result, "Response must include 'answer'"
        assert "conversation_id" in result, "Response must include 'conversation_id'"
        assert "message_id" in result, "Response must include 'message_id'"
        assert "message_type" in result, "Response must include 'message_type'"
        assert "tool_calls" in result, "Response must include 'tool_calls'"

        # Verify values
        assert result["answer"] == "Hello! I'm CAIRN."
        assert result["conversation_id"] == "conv-123"
        assert result["message_id"] == "msg-456"

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_conversation_id_persists(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Conversation ID should persist across messages."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="Response",
            conversation_id="conv-persist",
            message_id="msg-1",
            message_type="text",
            tool_calls=[],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        # First message
        result1 = handle_respond(db, text="First message")
        conv_id = result1["conversation_id"]

        # Second message with same conversation
        result2 = handle_respond(db, text="Second message", conversation_id=conv_id)

        # Verify agent was called with the conversation_id
        calls = mock_agent.respond.call_args_list
        assert len(calls) == 2, "Agent should be called twice"
        assert calls[1][1].get("conversation_id") == conv_id, (
            f"Second call should use conversation_id={conv_id}"
        )


class TestAgentTypeSelection:
    """Test agent type routing (CAIRN/ReOS/RIVA)."""

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_default_agent_is_cairn(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Without agent_type, should default to CAIRN (conversational mode)."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="CAIRN response",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        handle_respond(db, text="What should I focus on?")

        # Verify ChatAgent created without code_mode
        mock_agent_class.assert_called_once()
        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs.get("use_code_mode") is False, (
            "Default should NOT use code_mode (CAIRN is default)"
        )

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_use_code_mode_activates_riva(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """use_code_mode=True should activate RIVA."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="RIVA response",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        handle_respond(db, text="Add login feature", use_code_mode=True)

        # Verify ChatAgent created WITH code_mode
        mock_agent_class.assert_called_once()
        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs.get("use_code_mode") is True, (
            "use_code_mode=True should activate RIVA"
        )

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_explicit_agent_type_passed_to_respond(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Explicit agent_type should be passed to respond()."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="ReOS response",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[],
            thinking_steps=[],
            pending_approval_id=None,
            extended_thinking_trace=None,
        )
        mock_agent_class.return_value = mock_agent

        handle_respond(db, text="Install docker", agent_type="reos")

        # Verify agent_type passed to respond
        respond_kwargs = mock_agent.respond.call_args[1]
        assert respond_kwargs.get("agent_type") == "reos", (
            "agent_type='reos' should be passed to respond()"
        )


class TestIntentDetection:
    """Test intent detection for conversational flow."""

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_approval_intent_with_pending_approval(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """'yes' with pending approval should execute the command."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = MagicMock(
            intent_type="approval",
            choice_number=None,
            reference_term=None,
            confidence=1.0,
        )
        mock_agent.get_pending_approval_for_conversation.return_value = {
            "id": 42,
            "command": "apt install docker",
        }
        mock_agent_class.return_value = mock_agent

        # Mock the approval handler
        with patch("reos.rpc.handlers.chat.approval_respond") as mock_approval:
            mock_approval.return_value = {
                "status": "executed",
                "result": {"return_code": 0},
            }

            result = handle_respond(
                db, text="yes", conversation_id="conv-with-pending"
            )

        assert "intent_handled" in result, "Should indicate intent was handled"
        assert result["intent_handled"] == "approval"
        assert "executed" in result["answer"].lower(), (
            f"Answer should mention execution, got: {result['answer']}"
        )

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_rejection_intent_with_pending_approval(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """'no' with pending approval should reject the command."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = MagicMock(
            intent_type="rejection",
            choice_number=None,
            reference_term=None,
            confidence=1.0,
        )
        mock_agent.get_pending_approval_for_conversation.return_value = {
            "id": 42,
            "command": "rm -rf /tmp/test",
        }
        mock_agent_class.return_value = mock_agent

        with patch("reos.rpc.handlers.chat.approval_respond") as mock_approval:
            mock_approval.return_value = {"status": "rejected"}

            result = handle_respond(
                db, text="no", conversation_id="conv-with-pending"
            )

        assert result["intent_handled"] == "rejection"
        assert "rejected" in result["answer"].lower()


class TestChatClear:
    """Test chat/clear endpoint."""

    def test_clear_removes_messages(self, db: Database) -> None:
        """Clearing conversation should remove all messages."""
        # Create a conversation with messages
        conv_id = "conv-to-clear"
        db.create_conversation(conversation_id=conv_id)
        db.add_message(
            message_id="msg-1",
            conversation_id=conv_id,
            role="user",
            content="Hello",
            message_type="text",
        )
        db.add_message(
            message_id="msg-2",
            conversation_id=conv_id,
            role="assistant",
            content="Hi there",
            message_type="text",
        )

        # Clear it
        result = handle_clear(db, conversation_id=conv_id)

        assert result["ok"] is True

        # Verify messages are gone
        messages = db.get_messages(conv_id)
        assert len(messages) == 0, "Messages should be deleted"


class TestIntentDetectEndpoint:
    """Test intent/detect endpoint."""

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_detects_approval_intent(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Should detect approval intent."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = MagicMock(
            intent_type="approval",
            choice_number=None,
            reference_term=None,
            confidence=1.0,
        )
        mock_agent_class.return_value = mock_agent

        result = handle_intent_detect(db, text="yes")

        assert result["detected"] is True
        assert result["intent_type"] == "approval"
        assert result["confidence"] == 1.0

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_no_intent_for_normal_message(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Normal messages should not detect special intent."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent_class.return_value = mock_agent

        result = handle_intent_detect(db, text="What's the weather like?")

        assert result["detected"] is False


class TestErrorHandling:
    """Test error handling is graceful and informative."""

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_llm_error_is_descriptive(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """LLM errors should produce clear error messages."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.side_effect = ConnectionError(
            "Could not connect to Ollama at http://localhost:11434"
        )
        mock_agent_class.return_value = mock_agent

        with pytest.raises(ConnectionError) as exc_info:
            handle_respond(db, text="Hello")

        error_msg = str(exc_info.value)
        assert "Ollama" in error_msg or "connect" in error_msg, (
            f"Error should mention what failed, got: {error_msg}"
        )

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_tool_error_includes_tool_name(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Tool errors should include which tool failed."""
        from reos.mcp_tools import ToolError

        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.side_effect = ToolError(
            "linux_run_command",
            "Permission denied: cannot run 'fdisk'"
        )
        mock_agent_class.return_value = mock_agent

        with pytest.raises(ToolError) as exc_info:
            handle_respond(db, text="Format my disk")

        error = exc_info.value
        assert "linux_run_command" in str(error), (
            "ToolError should include tool name"
        )
        assert "Permission denied" in str(error) or "fdisk" in str(error), (
            "ToolError should include what was denied"
        )


class TestExtendedThinking:
    """Test extended thinking (CAIRN feature)."""

    @patch("reos.rpc.handlers.chat.ChatAgent")
    def test_extended_thinking_trace_included_when_enabled(
        self, mock_agent_class: MagicMock, db: Database
    ) -> None:
        """Extended thinking trace should be in response when enabled."""
        mock_agent = MagicMock()
        mock_agent.detect_intent.return_value = None
        mock_agent.respond.return_value = MagicMock(
            answer="After careful thought...",
            conversation_id="conv-1",
            message_id="msg-1",
            message_type="text",
            tool_calls=[],
            thinking_steps=["Step 1", "Step 2"],
            pending_approval_id=None,
            extended_thinking_trace={
                "nodes": [{"id": "root", "thought": "Analyzing request"}],
                "depth": 2,
            },
        )
        mock_agent_class.return_value = mock_agent

        result = handle_respond(
            db, text="Complex question", extended_thinking=True
        )

        assert "extended_thinking_trace" in result
        assert result["extended_thinking_trace"] is not None
        assert "nodes" in result["extended_thinking_trace"]
