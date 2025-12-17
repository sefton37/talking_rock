"""Command/tool registry: what the LLM can see and reason about."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .attention import classify_attention_pattern, get_current_session_summary
from .db import Database


@dataclass(frozen=True)
class Command:
    """A single command that the LLM can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for parameters
    handler: Callable[[dict[str, Any]], str] | None = None  # Will be set at runtime


def get_command_registry() -> list[Command]:
    """Get the list of commands the LLM can reason about.

    This is sent to the LLM in the system prompt so it can decide which tools to use.
    All commands introspect VSCode-derived attention data from SQLite.
    """
    return [
        Command(
            name="reflect_recent",
            description=(
                "Summarize your recent attention patterns from VSCode activity: "
                "switches, focus depth, fragmentation. Shows what your attention "
                "actually served. No parameters."
            ),
            parameters={},
        ),
        Command(
            name="inspect_session",
            description=(
                "Get details about your current or recent coding session: "
                "which projects, how long in each, file switching patterns."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "minutes_back": {
                        "type": "number",
                        "description": "How many minutes back to look (default 60)",
                    }
                },
            },
        ),
        Command(
            name="list_events",
            description=(
                "List recent VSCode events: editor activity, saves, file switches. "
                "Helps understand what actions your attention has taken."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "How many events to show (default 20)",
                    }
                },
            },
        ),
        Command(
            name="note",
            description=(
                "Store a reflection or observation about your attention. "
                "Example: 'This switching was creative exploration, not distraction.'"
            ),
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Your reflection"}},
                "required": ["text"],
            },
        ),
    ]


# Command handlers (will be invoked by the LLM or UI)


def handle_reflect_recent() -> str:
    """Reflect on recent attention patterns."""
    try:
        db = Database()
        classification = classify_attention_pattern(db)
        return json.dumps(classification, indent=2)
    except Exception as e:
        return f"Error reflecting on recent patterns: {e}"


def handle_inspect_session(params: dict[str, Any]) -> str:
    """Inspect the current session."""
    try:
        db = Database()
        summary = get_current_session_summary(db)
        return json.dumps(summary, indent=2)
    except Exception as e:
        return f"Error inspecting session: {e}"


def handle_list_events(params: dict[str, Any]) -> str:
    """List recent events."""
    try:
        db = Database()
        limit = int(params.get("limit", 20))
        events = db.iter_events_recent(limit=limit)
        # Summarize: show kind, timestamp, key metadata
        summary = []
        for evt in events:
            try:
                payload = evt.get("payload_metadata")
                if isinstance(payload, str):
                    meta = json.loads(payload)
                else:
                    meta = {}
                summary.append(
                    {
                        "kind": evt.get("kind"),
                        "timestamp": evt.get("ts"),
                        "project": meta.get("projectName"),
                        "uri": meta.get("uri", "")[-50:],  # Last 50 chars of URI
                    }
                )
            except Exception:
                summary.append(
                    {
                        "kind": evt.get("kind"),
                        "timestamp": evt.get("ts"),
                    }
                )
        return json.dumps(summary, indent=2)
    except Exception as e:
        return f"Error listing events: {e}"


def handle_note(params: dict[str, Any]) -> str:
    """Store a note about attention/intention."""
    try:
        text = params.get("text", "")
        db = Database()
        import uuid

        note_id = str(uuid.uuid4())
        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        db.insert_event(
            event_id=note_id,
            source="user",
            kind="reflection_note",
            ts=now,
            payload_metadata=json.dumps({"text": text}),
            note=text,
        )
        return f"Note stored: {text}"
    except Exception as e:
        return f"Error storing note: {e}"


def registry_as_json_schema() -> dict[str, Any]:
    """Serialize the command registry as a JSON schema for the LLM."""
    commands = get_command_registry()
    return {
        "type": "object",
        "description": (
            "Available commands you can call to reason about the "
            "user's attention and projects."
        ),
        "commands": [
            {
                "name": cmd.name,
                "description": cmd.description,
                "parameters": cmd.parameters,
            }
            for cmd in commands
        ],
    }
