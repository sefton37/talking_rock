from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import Database
from .mcp_tools import Tool, ToolError, call_tool, list_tools, render_tool_result
from .ollama import OllamaClient
from .play_fs import list_acts as play_list_acts
from .play_fs import read_me_markdown as play_read_me_markdown


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


class ChatAgent:
    """Minimal tool-using chat agent for ReOS.

    Principles:
    - Local-only (Ollama).
    - Metadata-first; diffs only on explicit opt-in.
    - Repo-first; repo selection is configured via REOS_REPO_PATH or by running inside a git repo.
    """

    def __init__(self, *, db: Database, ollama: OllamaClient | None = None) -> None:
        self._db = db
        self._ollama_override = ollama

    def _get_persona(self) -> dict[str, Any]:
        persona_id = self._db.get_active_persona_id()
        if persona_id:
            row = self._db.get_agent_persona(persona_id=persona_id)
            if row is not None:
                return row

        return {
            "system_prompt": (
                "You are ReOS, a local-first companion for a developer. "
                "Protect, reflect, and return attention. "
                "Be descriptive, compassionate, and transparent about tool use."
            ),
            "default_context": "",
            "temperature": 0.2,
            "top_p": 0.9,
            "tool_call_limit": 3,
        }

    def _get_ollama_client(self) -> OllamaClient:
        if self._ollama_override is not None:
            return self._ollama_override

        url = self._db.get_state(key="ollama_url")
        model = self._db.get_state(key="ollama_model")
        return OllamaClient(
            url=url if isinstance(url, str) and url else None,
            model=model if isinstance(model, str) and model else None,
        )

    def respond(self, user_text: str) -> str:
        tools = list_tools()

        persona = self._get_persona()
        temperature = float(persona.get("temperature") or 0.2)
        top_p = float(persona.get("top_p") or 0.9)
        tool_call_limit = int(persona.get("tool_call_limit") or 3)
        tool_call_limit = max(0, min(6, tool_call_limit))

        persona_system = str(persona.get("system_prompt") or "")
        persona_context = str(persona.get("default_context") or "")
        persona_prefix = persona_system
        if persona_context:
            persona_prefix = persona_prefix + "\n\n" + persona_context

        play_context = self._get_play_context()
        if play_context:
            persona_prefix = persona_prefix + "\n\n" + play_context

        ollama = self._get_ollama_client()

        wants_diff = self._user_opted_into_diff(user_text)

        tool_calls = self._select_tools(
            user_text=user_text,
            tools=tools,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
            tool_call_limit=tool_call_limit,
        )

        tool_results: list[dict[str, Any]] = []
        for call in tool_calls[:tool_call_limit]:
            try:
                if call.name == "reos_git_summary" and not wants_diff:
                    args = {k: v for k, v in call.arguments.items() if k != "include_diff"}
                    call = ToolCall(name=call.name, arguments=args)

                result = call_tool(self._db, name=call.name, arguments=call.arguments)
                tool_results.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": True,
                        "result": result,
                    }
                )
            except ToolError as exc:
                tool_results.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message, "data": exc.data},
                    }
                )

        answer = self._answer(
            user_text=user_text,
            tools=tools,
            tool_results=tool_results,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
        )
        return answer

    def _get_play_context(self) -> str:
        try:
            acts, active_id = play_list_acts()
        except Exception:  # noqa: BLE001
            return ""

        if not active_id:
            return ""

        act = next((a for a in acts if a.act_id == active_id), None)
        if act is None:
            return ""

        ctx = f"ACTIVE_ACT: {act.title}".strip()
        if act.notes.strip():
            ctx = ctx + "\n" + f"ACT_NOTES: {act.notes.strip()}"

        try:
            me = play_read_me_markdown().strip()
        except Exception:  # noqa: BLE001
            me = ""

        if me:
            # Keep this small and stable; it should be identity-level context,
            # not a task list.
            cap = 2000
            if len(me) > cap:
                me = me[:cap] + "\n…"
            ctx = ctx + "\n\n" + "ME_CONTEXT:\n" + me

        return ctx

    def _user_opted_into_diff(self, user_text: str) -> bool:
        t = user_text.lower()
        return any(
            phrase in t
            for phrase in [
                "include diff",
                "show diff",
                "full diff",
                "git diff",
                "patch",
                "unified diff",
            ]
        )

    def _select_tools(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
        tool_call_limit: int,
    ) -> list[ToolCall]:
        tool_specs = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

        system = (
            persona_prefix
            + "\n\n"
            + "You are deciding which tools (if any) to call to answer the user.\n\n"
            + "Rules:\n"
            + "- Prefer metadata-first tools (git summary) before reading files.\n"
            + "- Only request include_diff=true if the user explicitly opted in.\n"
            + f"- Keep tool calls minimal (0-{tool_call_limit}).\n\n"
            + "Return JSON with this shape:\n"
            + "{\n"
            + "  \"tool_calls\": [\n"
            + "    {\"name\": \"tool_name\", \"arguments\": {}}\n"
            + "  ]\n"
            + "}\n"
        )

        user = (
            "TOOLS:\n" + json.dumps(tool_specs, indent=2) + "\n\n" +
            "USER_MESSAGE:\n" + user_text + "\n\n" +
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n"
        )

        raw = ollama.chat_json(system=system, user=user, temperature=temperature, top_p=top_p)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return [ToolCall(name="reos_git_summary", arguments={})]

        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return []

        out: list[ToolCall] = []
        for c in calls:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            args = c.get("arguments")
            if isinstance(name, str) and isinstance(args, dict):
                out.append(ToolCall(name=name, arguments=args))

        return out

    def _answer(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        tool_results: list[dict[str, Any]],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
    ) -> str:
        tool_dump = []
        for r in tool_results:
            rendered = render_tool_result(r.get("result")) if r.get("ok") else json.dumps(r.get("error"), indent=2)
            tool_dump.append(
                {
                    "name": r.get("name"),
                    "arguments": r.get("arguments"),
                    "ok": r.get("ok"),
                    "output": rendered,
                }
            )

        system = (
            persona_prefix
            + "\n\n"
            + "Answer the user using the available tool outputs.\n\n"
            + "Rules:\n"
            + "- Be descriptive, non-judgmental, and local-first.\n"
            + "- If no repo is configured/detected, ask the user to set REOS_REPO_PATH or run ReOS inside a git repo.\n"
            + "- Do not fabricate repository state; rely on tool outputs.\n"
            + "- If the user did not opt into diffs, do not ask for or display diffs.\n"
        )

        user = (
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n\n"
            "USER_MESSAGE:\n" + user_text + "\n\n"
            "TOOL_RESULTS:\n" + json.dumps(tool_dump, indent=2, ensure_ascii=False)
        )

        return ollama.chat_text(system=system, user=user, temperature=temperature, top_p=top_p)
