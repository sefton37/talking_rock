"""Integration tests for ChatAgent.

These tests verify the core functionality of the ChatAgent class,
including tool calling, error handling, and persona management.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from reos.agent import ChatAgent, ToolCall
from reos.db import get_db
from reos.mcp_tools import ToolError


class FakeOllama:
    """Fake Ollama client for testing.

    Handles the LLM-first architecture with different response types:
    - Intent parsing: Returns query intent (no plan needed)
    - Plan generation: Returns empty steps (if called)
    - Tool selection: Returns tool_calls
    - Answer generation: Returns text
    """

    def __init__(
        self,
        *,
        tool_plan_json: str = '{"tool_calls": []}',
        answer_text: str = "Test response",
        chat_json_error: Exception | None = None,
        chat_text_error: Exception | None = None,
        intent_response: dict[str, Any] | None = None,
    ) -> None:
        self._tool_plan_json = tool_plan_json
        self._answer_text = answer_text
        self._chat_json_error = chat_json_error
        self._chat_text_error = chat_text_error
        # Default intent: query (no plan needed, let normal flow handle)
        self._intent_response = intent_response or {
            "action": "query",
            "resource_type": "general",
            "targets": [],
            "conditions": {},
            "confidence": 0.9,
            "explanation": "User asking a question"
        }
        self.chat_json_calls: list[dict[str, Any]] = []
        self.chat_text_calls: list[dict[str, Any]] = []

    def chat_json(self, *, system: str, user: str, **kwargs: Any) -> str:
        self.chat_json_calls.append({"system": system, "user": user, **kwargs})
        if self._chat_json_error:
            raise self._chat_json_error

        # Detect call type based on system prompt content
        # Use specific phrases to avoid false matches (e.g., "llm_planner.py" in codebase context)
        if "intent parser" in system.lower():
            # Intent parsing call - return query intent (no plan)
            return json.dumps(self._intent_response)
        elif "system administration planner" in system.lower() or "generate a plan" in system.lower():
            # Plan generation call - return empty steps
            return "[]"
        else:
            # Tool selection call - return tool plan
            return self._tool_plan_json

    def chat_text(self, *, system: str, user: str, **kwargs: Any) -> str:
        self.chat_text_calls.append({"system": system, "user": user, **kwargs})
        if self._chat_text_error:
            raise self._chat_text_error
        return self._answer_text


class TestChatAgentRespond:
    """Tests for ChatAgent.respond() method."""

    def test_respond_with_no_tool_calls(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should handle responses with no tool calls."""
        ollama = FakeOllama(
            tool_plan_json='{"tool_calls": []}',
            answer_text="No tools needed for this response.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        result = agent.respond("What is Linux?")

        assert result.answer == "No tools needed for this response."
        assert result.conversation_id is not None
        assert result.message_id is not None
        # LLM-first: 1 intent parsing + 1 tool selection = 2 calls
        assert len(ollama.chat_json_calls) == 2
        assert len(ollama.chat_text_calls) == 1

    def test_respond_with_successful_tool_calls(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent should execute tools and include results in response."""
        calls: list[dict[str, Any]] = []

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            calls.append({"name": name, "arguments": arguments or {}})
            return {"status": "success", "data": "test_data"}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        tool_plan = {
            "tool_calls": [
                {"name": "linux_system_info", "arguments": {}},
            ]
        }
        ollama = FakeOllama(
            tool_plan_json=json.dumps(tool_plan),
            answer_text="System info retrieved.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        result = agent.respond("What is my system info?")

        assert len(calls) == 1
        assert calls[0]["name"] == "linux_system_info"
        assert result.answer == "System info retrieved."
        assert len(result.tool_calls) == 1

    def test_respond_with_tool_error(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent should handle tool errors gracefully."""

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            raise ToolError(code="TOOL_FAILED", message="Tool execution failed")

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        tool_plan = {
            "tool_calls": [
                {"name": "linux_run_command", "arguments": {"command": "test"}},
            ]
        }
        ollama = FakeOllama(
            tool_plan_json=json.dumps(tool_plan),
            answer_text="Sorry, there was an error.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        result = agent.respond("Run a test command")

        # Should still get a response even with tool error
        assert result.answer == "Sorry, there was an error."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["ok"] is False

    def test_respond_with_malformed_tool_response(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent should handle malformed tool calls from LLM."""
        calls: list[str] = []

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            calls.append(name)
            return {"ok": True}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        # Malformed tool_calls (not a list)
        ollama = FakeOllama(
            tool_plan_json='{"tool_calls": "not a list"}',
            answer_text="Handled gracefully.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        result = agent.respond("Do something")

        # Should not crash, no tools called
        assert len(calls) == 0
        assert result.answer == "Handled gracefully."
        assert result.tool_calls == []

    def test_respond_with_invalid_json_from_llm(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent should fall back gracefully when LLM returns invalid JSON."""
        calls: list[str] = []

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            calls.append(name)
            return {"ok": True}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        ollama = FakeOllama(
            tool_plan_json="not valid json at all",
            answer_text="Fallback response.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        result = agent.respond("Hello")

        # When JSON is invalid, agent should NOT call any tools (safe fallback)
        assert len(calls) == 0
        # Should still return a response
        assert result.answer == "Fallback response."


class TestChatAgentDiffHandling:
    """Tests for diff opt-in/opt-out behavior."""

    def test_diff_opt_in_phrases(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should recognize various diff opt-in phrases."""
        agent = ChatAgent(db=get_db())

        opt_in_phrases = [
            "include diff",
            "show diff",
            "full diff",
            "git diff",
            "patch",
            "unified diff",
            "INCLUDE DIFF",  # case insensitive
        ]

        for phrase in opt_in_phrases:
            assert agent._user_opted_into_diff(phrase), f"Should opt in for: {phrase}"

    def test_diff_not_opted_in(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should not opt in for normal messages."""
        agent = ChatAgent(db=get_db())

        normal_phrases = [
            "What changed?",
            "Show me the changes",
            "What's different?",
            "List modified files",
        ]

        for phrase in normal_phrases:
            assert not agent._user_opted_into_diff(phrase), f"Should not opt in for: {phrase}"


class TestChatAgentPersona:
    """Tests for persona management."""

    def test_default_persona_values(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should use sensible defaults when no persona configured."""
        agent = ChatAgent(db=get_db())
        persona = agent._get_persona()

        assert "system_prompt" in persona
        assert "ReOS" in persona["system_prompt"]
        assert persona.get("temperature", 0.2) == 0.2
        assert persona.get("top_p", 0.9) == 0.9
        assert persona.get("tool_call_limit", 5) == 5

    def test_custom_persona(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should use custom persona when configured."""
        db = get_db()
        db.upsert_agent_persona(
            persona_id="custom-test",
            name="Custom Test",
            system_prompt="You are a custom assistant.",
            default_context="Custom context",
            temperature=0.5,
            top_p=0.8,
            tool_call_limit=2,
        )
        db.set_active_persona_id(persona_id="custom-test")

        agent = ChatAgent(db=db)
        persona = agent._get_persona()

        assert persona["system_prompt"] == "You are a custom assistant."
        assert persona["default_context"] == "Custom context"
        assert persona["temperature"] == 0.5
        assert persona["top_p"] == 0.8
        assert persona["tool_call_limit"] == 2


class TestChatAgentToolSelection:
    """Tests for tool selection behavior."""

    def test_tool_selection_includes_tool_specs(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM should receive tool specifications in selection phase."""

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            return {}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        ollama = FakeOllama(
            tool_plan_json='{"tool_calls": []}',
            answer_text="Done.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        agent.respond("List files")

        # Check that tool specs were included in the tool selection call
        # LLM-first: call[0] = intent parsing, call[1] = tool selection
        assert len(ollama.chat_json_calls) == 2
        # Tool selection is the second call
        user_msg = ollama.chat_json_calls[1]["user"]
        assert "TOOLS:" in user_msg

    def test_tool_call_limit_enforcement(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent should enforce maximum tool call limit of 6."""
        db = get_db()
        db.upsert_agent_persona(
            persona_id="high-limit",
            name="High Limit",
            system_prompt="test",
            default_context="",
            temperature=0.2,
            top_p=0.9,
            tool_call_limit=100,  # Try to set very high limit
        )
        db.set_active_persona_id(persona_id="high-limit")

        calls: list[str] = []

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            calls.append(name)
            return {}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        # Request 10 tool calls
        tool_plan = {
            "tool_calls": [{"name": f"tool_{i}", "arguments": {}} for i in range(10)]
        }
        ollama = FakeOllama(
            tool_plan_json=json.dumps(tool_plan),
            answer_text="Done.",
        )
        agent = ChatAgent(db=db, ollama=ollama)
        agent.respond("Run many tools")

        # Should be capped at 6
        assert len(calls) <= 6


class TestChatAgentToolCall:
    """Tests for the ToolCall dataclass."""

    def test_tool_call_immutable(self) -> None:
        """ToolCall should be immutable (frozen dataclass)."""
        call = ToolCall(name="test", arguments={"key": "value"})
        assert call.name == "test"
        assert call.arguments == {"key": "value"}

        with pytest.raises(AttributeError):
            call.name = "changed"  # type: ignore


class TestChatAgentIntentDetection:
    """Tests for intent detection (Phase 6)."""

    def test_detects_approval_intents(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should detect approval intents."""
        agent = ChatAgent(db=get_db())

        approval_phrases = ["yes", "y", "ok", "okay", "sure", "go", "yep", "do it", "YES", "Go ahead"]
        for phrase in approval_phrases:
            intent = agent.detect_intent(phrase)
            assert intent is not None, f"Should detect approval for: {phrase}"
            assert intent.intent_type == "approval", f"Wrong type for: {phrase}"

    def test_detects_rejection_intents(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should detect rejection intents."""
        agent = ChatAgent(db=get_db())

        rejection_phrases = ["no", "n", "nope", "cancel", "stop", "abort", "NO", "Never mind"]
        for phrase in rejection_phrases:
            intent = agent.detect_intent(phrase)
            assert intent is not None, f"Should detect rejection for: {phrase}"
            assert intent.intent_type == "rejection", f"Wrong type for: {phrase}"

    def test_detects_numeric_choices(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should detect numeric choices 1-9."""
        agent = ChatAgent(db=get_db())

        for i in range(1, 10):
            intent = agent.detect_intent(str(i))
            assert intent is not None, f"Should detect choice for: {i}"
            assert intent.intent_type == "choice"
            assert intent.choice_number == i

    def test_detects_ordinal_choices(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should detect ordinal choices (first, second, etc.)."""
        agent = ChatAgent(db=get_db())

        ordinals = [
            ("first", 1), ("second", 2), ("third", 3),
            ("1st", 1), ("2nd", 2), ("3rd", 3),
            ("First one", 1), ("SECOND", 2),
        ]
        for phrase, expected_num in ordinals:
            intent = agent.detect_intent(phrase)
            assert intent is not None, f"Should detect choice for: {phrase}"
            assert intent.intent_type == "choice", f"Wrong type for: {phrase}"
            assert intent.choice_number == expected_num, f"Wrong number for: {phrase}"

    def test_detects_references(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should detect reference terms in short messages."""
        agent = ChatAgent(db=get_db())

        reference_phrases = [
            ("restart it", "it"),
            ("show me that", "that"),
            ("check the service", "the service"),
            ("stop the container", "the container"),
        ]
        for phrase, expected_term in reference_phrases:
            intent = agent.detect_intent(phrase)
            assert intent is not None, f"Should detect reference for: {phrase}"
            assert intent.intent_type == "reference", f"Wrong type for: {phrase}"
            assert intent.reference_term == expected_term, f"Wrong term for: {phrase}"

    def test_no_intent_for_normal_questions(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Agent should return None for normal questions."""
        agent = ChatAgent(db=get_db())

        normal_phrases = [
            "What is the current CPU usage?",
            "How do I install nginx?",
            "Show me the logs for sshd",
            "List all running containers",
        ]
        for phrase in normal_phrases:
            intent = agent.detect_intent(phrase)
            assert intent is None, f"Should not detect intent for: {phrase}"


class TestChatAgentAnswerGeneration:
    """Tests for answer generation phase."""

    def test_answer_includes_tool_results(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM should receive tool results in answer phase."""

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            return {"output": "tool_output_data"}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        tool_plan = {
            "tool_calls": [{"name": "test_tool", "arguments": {}}]
        }
        ollama = FakeOllama(
            tool_plan_json=json.dumps(tool_plan),
            answer_text="Final answer.",
        )
        agent = ChatAgent(db=get_db(), ollama=ollama)
        agent.respond("Run test tool")

        # Check that tool results were included
        assert len(ollama.chat_text_calls) == 1
        user_msg = ollama.chat_text_calls[0]["user"]
        assert "TOOL_RESULTS:" in user_msg

    def test_answer_respects_temperature(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Answer generation should use persona temperature."""
        db = get_db()
        db.upsert_agent_persona(
            persona_id="temp-test",
            name="Temp Test",
            system_prompt="test",
            default_context="",
            temperature=0.7,
            top_p=0.95,
            tool_call_limit=3,
        )
        db.set_active_persona_id(persona_id="temp-test")

        def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
            return {}

        import reos.agent as agent_mod

        monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

        ollama = FakeOllama(
            tool_plan_json='{"tool_calls": []}',
            answer_text="Done.",
        )
        agent = ChatAgent(db=db, ollama=ollama)
        agent.respond("Hello")

        # Check temperature was passed
        assert len(ollama.chat_text_calls) == 1
        assert ollama.chat_text_calls[0]["temperature"] == 0.7
        assert ollama.chat_text_calls[0]["top_p"] == 0.95
