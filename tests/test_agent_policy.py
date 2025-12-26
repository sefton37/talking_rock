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
            {"name": "reos_git_summary", "arguments": {"include_diff": True}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
    _answer = agent.respond("How does the repo look?")

    assert any(c["name"] == "reos_git_summary" for c in calls)
    git_call = next(c for c in calls if c["name"] == "reos_git_summary")
    assert "include_diff" not in git_call["arguments"]


def test_agent_allows_include_diff_when_user_opts_in(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_persona_tool_limit(3)

    calls: list[dict[str, Any]] = []

    def fake_call_tool(db, *, name: str, arguments: dict[str, Any] | None):  # noqa: ANN001
        calls.append({"name": name, "arguments": arguments or {}})
        return {"ok": True}

    import reos.agent as agent_mod

    monkeypatch.setattr(agent_mod, "call_tool", fake_call_tool)

    tool_plan = {
        "tool_calls": [
            {"name": "reos_git_summary", "arguments": {"include_diff": True}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
    _answer = agent.respond("Please include diff in the git summary")

    git_call = next(c for c in calls if c["name"] == "reos_git_summary")
    assert git_call["arguments"].get("include_diff") is True


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
            {"name": "reos_git_summary", "arguments": {}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "**/*.py"}},
        ]
    }

    agent = ChatAgent(db=get_db(), ollama=FakeOllama(tool_plan_json=json.dumps(tool_plan)))
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
    _answer = agent.respond("Hello")

    # Fallback should attempt a minimal metadata-first call.
    assert calls[:1] == ["reos_git_summary"]
