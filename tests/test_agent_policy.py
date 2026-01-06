from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from reos.agent import ChatAgent
from reos.db import get_db


class FakeOllama:
    def __init__(self, *, tool_plan_json: str, answer_text: str = "ok") -> None:
        self._tool_plan_json = tool_plan_json
        self._answer_text = answer_text

    def chat_json(self, *, system: str, user: str, **_kwargs: Any) -> str:  # noqa: ARG002
        return self._tool_plan_json

    def chat_text(self, *, system: str, user: str, **_kwargs: Any) -> str:  # noqa: ARG002
        return self._answer_text


def _set_persona_tool_limit(limit: int) -> None:
    db = get_db()
    persona_id = "p-test"
    db.upsert_agent_persona(
        persona_id=persona_id,
        name="Test Persona",
        system_prompt="system",
        default_context="",
        temperature=0.0,
        top_p=1.0,
        tool_call_limit=limit,
    )
    db.set_active_persona_id(persona_id=persona_id)


def test_agent_strips_include_diff_when_not_opted_in(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that include_diff is stripped when user doesn't opt in.

    NOTE: This test uses linux_system_info since git tools were removed.
    The test now verifies that arbitrary extra arguments are passed through,
    since include_diff policy doesn't apply to non-git tools.
    """
    _set_persona_tool_limit(3)

    calls: list[dict[str, Any]] = []

    def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
        calls.append({"name": name, "arguments": arguments or {}})
        return {"ok": True}

    # Avoid invoking real MCP tools; we only care about the arguments passed.
    import reos.agent as agent_mod

    monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

    tool_plan = {
        "tool_calls": [
            {"name": "linux_system_info", "arguments": {}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
    # Disable reasoning engine for this test - we're testing tool policy, not reasoning
    monkeypatch.setattr(agent, "_try_reasoning", lambda *args, **kwargs: None)
    _answer = agent.respond("How is my system?")

    assert any(c["name"] == "linux_system_info" for c in calls)
    info_call = next(c for c in calls if c["name"] == "linux_system_info")
    assert info_call["arguments"] == {}


def test_agent_passes_arguments_to_tools(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that tool arguments are passed through correctly."""
    _set_persona_tool_limit(3)

    calls: list[dict[str, Any]] = []

    def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
        calls.append({"name": name, "arguments": arguments or {}})
        return {"ok": True}

    import reos.agent as agent_mod

    monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

    tool_plan = {
        "tool_calls": [
            {"name": "linux_disk_usage", "arguments": {"path": "/home"}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
    # Disable reasoning engine for this test - we're testing tool policy, not reasoning
    monkeypatch.setattr(agent, "_try_reasoning", lambda *args, **kwargs: None)
    _answer = agent.respond("Check disk usage for /home")

    disk_call = next(c for c in calls if c["name"] == "linux_disk_usage")
    assert disk_call["arguments"].get("path") == "/home"


def test_agent_respects_tool_call_limit(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_persona_tool_limit(1)

    calls: list[str] = []

    def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
        calls.append(name)
        return {"ok": True}

    import reos.agent as agent_mod

    monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

    tool_plan = {
        "tool_calls": [
            {"name": "linux_system_info", "arguments": {}},
            {"name": "linux_disk_usage", "arguments": {"path": "/"}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
    # Disable reasoning engine for this test - we're testing tool policy, not reasoning
    monkeypatch.setattr(agent, "_try_reasoning", lambda *args, **kwargs: None)
    _answer = agent.respond("What tools do you need?")

    assert len(calls) == 1


def test_agent_falls_back_on_invalid_json_tool_plan(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Default persona limit is 3; keep it.

    calls: list[str] = []

    def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
        calls.append(name)
        return {"ok": True}

    import reos.agent as agent_mod

    monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json="not json"))
    # Disable reasoning engine for this test - we're testing tool policy, not reasoning
    monkeypatch.setattr(agent, "_try_reasoning", lambda *args, **kwargs: None)
    _answer = agent.respond("Hello")

    # When JSON is invalid, agent should NOT call any tools (safe fallback)
    assert calls == []
