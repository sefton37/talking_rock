"""Command/tool registry: what the LLM can see and reason about."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alignment import (
    analyze_alignment,
    get_review_context_budget,
    infer_active_repo_path,
    is_git_repo,
)
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
    Commands are Git-first and repo-centric.
    """
    return [
        Command(
            name="reflect_recent",
            description=(
                "Summarize recent repo activity signals derived from git snapshots "
                "and checkpoints. "
                "Descriptive, not moral. No parameters."
            ),
            parameters={},
        ),
        Command(
            name="inspect_session",
            description=(
                "Get details about recent repo state/checkpoints in the local event store."
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
                "List recent local events: git snapshots and checkpoint triggers."
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
                "Example: 'This switching was creative exploration, not thread drift.'"
            ),
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Your reflection"}},
                "required": ["text"],
            },
        ),
        Command(
            name="review_alignment",
            description=(
                "Review how your current code changes relate to the project roadmap and charter. "
                "Uses git metadata (changed files + diffstat) and compares to docs/tech-roadmap.md "
                "and ReOS_charter.md. Default is metadata-only; optionally include diffs "
                "(local-only)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_diff": {
                        "type": "boolean",
                        "description": (
                            "If true, include full `git diff` text in the output (local-only). "
                            "Default false."
                        ),
                    }
                },
            },
        ),
        Command(
            name="review_trigger_status",
            description=(
                "Estimate whether roadmap + charter + current repo changes are nearing the "
                "configured LLM context budget, and whether ReOS would trigger a review "
                "checkpoint. Metadata-only (uses `git diff --numstat`)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": (
                            "Optional path to a repo/workspace folder. If omitted, inferred from "
                            "REOS_REPO_PATH or the current workspace root."
                        ),
                    }
                },
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
                        "repo": meta.get("repo"),
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


def handle_review_alignment(params: dict[str, Any]) -> str:
    """Review current repo changes against roadmap + charter."""
    try:
        include_diff = bool(params.get("include_diff", False))
        db = Database()
        report = analyze_alignment(db=db, include_diff=include_diff)
        return json.dumps(report, indent=2)
    except Exception as e:
        return f"Error reviewing alignment: {e}"


def handle_review_trigger_status(params: dict[str, Any]) -> str:
    """Return current context budget estimate and trigger state."""
    try:
        db = Database()

        repo_path_param = params.get("repo_path")
        repo_path: Path | None = None
        if isinstance(repo_path_param, str) and repo_path_param:
            repo_path = Path(repo_path_param)
        else:
            repo_path = infer_active_repo_path(db)

        if repo_path is None:
            return json.dumps(
                {
                    "status": "no_repo_detected",
                    "message": "No git repo detected. Set REOS_REPO_PATH or run inside a repo.",
                },
                indent=2,
            )

        if not is_git_repo(repo_path):
            return json.dumps(
                {
                    "status": "not_a_git_repo",
                    "repo": str(repo_path),
                },
                indent=2,
            )

        roadmap_path = repo_path / "docs" / "tech-roadmap.md"
        charter_path = repo_path / "ReOS_charter.md"
        budget = get_review_context_budget(
            repo_path=repo_path,
            roadmap_path=roadmap_path,
            charter_path=charter_path,
        )

        return json.dumps(
            {
                "status": "ok",
                "repo": str(repo_path),
                "estimate": {
                    "context_limit_tokens": budget.context_limit_tokens,
                    "total_tokens": budget.total_tokens,
                    "utilization": budget.utilization,
                    "trigger_ratio": budget.trigger_ratio,
                    "should_trigger": budget.should_trigger,
                    "breakdown": {
                        "roadmap_tokens": budget.roadmap_tokens,
                        "charter_tokens": budget.charter_tokens,
                        "changes_tokens": budget.changes_tokens,
                        "overhead_tokens": budget.overhead_tokens,
                    },
                },
            },
            indent=2,
        )
    except Exception as e:
        return f"Error estimating review trigger status: {e}"


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
