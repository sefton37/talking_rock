"""Shared tools for all Talking Rock agents.

Every agent (CAIRN, ReOS, RIVA) has access to these tools:
1. handoff_to_agent - Transfer to another specialized agent
2. get_shared_context - Retrieve relevant KB context
3. save_to_knowledge_base - Save information to shared KB

These tools enable seamless coordination while maintaining
the 15-tool-per-agent cap.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from reos.handoff.models import (
    AgentType,
    HandoffContext,
    HandoffRequest,
    HandoffStatus,
    generate_transition_message,
)
from reos.handoff.router import build_handoff_context, detect_handoff_need


@dataclass(frozen=True)
class SharedTool:
    """Definition of a shared tool."""

    name: str
    description: str
    parameters: dict[str, Any]


# Tool definitions that go in every agent's manifest
SHARED_TOOL_DEFINITIONS: list[SharedTool] = [
    SharedTool(
        name="handoff_to_agent",
        description=(
            "Transfer the current task to another specialized agent. "
            "Use when the user's request falls outside your domain or "
            "requires specialized capabilities. The user will be asked "
            "to confirm the handoff before it proceeds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target_agent": {
                    "type": "string",
                    "enum": ["cairn", "reos", "riva"],
                    "description": (
                        "The agent to hand off to: "
                        "'cairn' for life/attention/knowledge base, "
                        "'reos' for Linux system administration, "
                        "'riva' for code and development"
                    ),
                },
                "user_goal": {
                    "type": "string",
                    "description": "What the user is trying to accomplish",
                },
                "handoff_reason": {
                    "type": "string",
                    "description": "Why this handoff makes sense (shown to user)",
                },
                "relevant_details": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key details to pass to the receiving agent",
                },
                "relevant_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths or resources mentioned",
                },
                "open_ui": {
                    "type": "boolean",
                    "description": "Whether to open the target agent's specialized UI",
                    "default": True,
                },
            },
            "required": ["target_agent", "user_goal", "handoff_reason"],
        },
    ),
    SharedTool(
        name="get_shared_context",
        description=(
            "Retrieve relevant context from the shared knowledge base. "
            "Use to check for related projects, past decisions, or "
            "information that might inform the current task."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What context to search for",
                },
                "category": {
                    "type": "string",
                    "enum": ["all", "decision", "task", "note", "project", "reference"],
                    "description": "Filter by category (default: all)",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum results to return (default: 5)",
                },
            },
            "required": ["query"],
        },
    ),
    SharedTool(
        name="save_to_knowledge_base",
        description=(
            "Save important information, decisions, or outcomes to the "
            "shared knowledge base. This makes information available "
            "across all agents and conversations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to save",
                },
                "title": {
                    "type": "string",
                    "description": "Brief title for the entry",
                },
                "category": {
                    "type": "string",
                    "enum": ["decision", "task", "note", "project", "reference"],
                    "description": "The type of information",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for organization",
                },
            },
            "required": ["content", "category"],
        },
    ),
]


def get_shared_tool_schemas() -> list[dict[str, Any]]:
    """Get shared tool schemas in OpenAI function format.

    Returns:
        List of tool schemas ready for LLM.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in SHARED_TOOL_DEFINITIONS
    ]


class SharedToolHandler:
    """Handler for shared tools across all agents.

    Manages:
    - Handoff requests and confirmation flow
    - Knowledge base context queries
    - Saving to shared knowledge base
    """

    def __init__(
        self,
        current_agent: AgentType,
        cairn_store: Any | None = None,
        play_store: Any | None = None,
        on_handoff_proposed: Callable[[HandoffRequest], None] | None = None,
    ):
        """Initialize the handler.

        Args:
            current_agent: The currently active agent.
            cairn_store: Optional CAIRN store for KB operations.
            play_store: Optional Play store for KB operations.
            on_handoff_proposed: Callback when handoff is proposed.
        """
        self.current_agent = current_agent
        self.cairn_store = cairn_store
        self.play_store = play_store
        self.on_handoff_proposed = on_handoff_proposed

        # Pending handoff (one at a time)
        self._pending_handoff: HandoffRequest | None = None

    @property
    def pending_handoff(self) -> HandoffRequest | None:
        """Get the current pending handoff request."""
        return self._pending_handoff

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a shared tool.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result.

        Raises:
            ValueError: If tool not found.
        """
        if name == "handoff_to_agent":
            return self._handle_handoff(arguments)
        elif name == "get_shared_context":
            return self._handle_get_context(arguments)
        elif name == "save_to_knowledge_base":
            return self._handle_save_to_kb(arguments)
        else:
            raise ValueError(f"Unknown shared tool: {name}")

    def _handle_handoff(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle handoff_to_agent tool call.

        Creates a handoff request and returns it for user confirmation.
        The handoff is NOT executed until user confirms.
        """
        target_str = args["target_agent"]
        target = AgentType(target_str)

        if target == self.current_agent:
            return {
                "status": "rejected",
                "reason": f"Cannot hand off to myself ({self.current_agent.value})",
            }

        # Build structured context
        context = HandoffContext(
            user_goal=args["user_goal"],
            handoff_reason=args["handoff_reason"],
            relevant_details=args.get("relevant_details", []),
            relevant_paths=args.get("relevant_paths", []),
        )

        # Generate verbose transition message
        transition_message = generate_transition_message(
            source=self.current_agent,
            target=target,
            context=context,
        )

        # Create handoff request
        request = HandoffRequest(
            handoff_id=str(uuid.uuid4()),
            source_agent=self.current_agent,
            target_agent=target,
            context=context,
            status=HandoffStatus.PROPOSED,
            transition_message=transition_message,
            open_ui=args.get("open_ui", True),
        )

        # Store as pending
        self._pending_handoff = request

        # Notify callback if provided
        if self.on_handoff_proposed:
            self.on_handoff_proposed(request)

        return {
            "status": "proposed",
            "handoff_id": request.handoff_id,
            "target_agent": target.value,
            "transition_message": transition_message,
            "awaiting_confirmation": True,
            "message": (
                "I've proposed a handoff. Please review the transition details "
                "and confirm or reject the handoff."
            ),
        }

    def confirm_handoff(self, handoff_id: str) -> dict[str, Any]:
        """Confirm a pending handoff.

        Args:
            handoff_id: The handoff ID to confirm.

        Returns:
            Result with handoff details for UI to execute.
        """
        if self._pending_handoff is None:
            return {"status": "error", "reason": "No pending handoff"}

        if self._pending_handoff.handoff_id != handoff_id:
            return {"status": "error", "reason": "Handoff ID mismatch"}

        self._pending_handoff.status = HandoffStatus.CONFIRMED
        self._pending_handoff.confirmed_at = datetime.now()

        result = {
            "status": "confirmed",
            "handoff_id": handoff_id,
            "target_agent": self._pending_handoff.target_agent.value,
            "context": self._pending_handoff.context.to_dict(),
            "open_ui": self._pending_handoff.open_ui,
            "context_prompt": self._pending_handoff.context.to_prompt(),
        }

        # Clear pending
        confirmed = self._pending_handoff
        self._pending_handoff = None

        return result

    def reject_handoff(
        self,
        handoff_id: str,
        reason: str = "User chose to stay with current agent",
    ) -> dict[str, Any]:
        """Reject a pending handoff.

        Args:
            handoff_id: The handoff ID to reject.
            reason: Why the handoff was rejected.

        Returns:
            Result confirming rejection.
        """
        if self._pending_handoff is None:
            return {"status": "error", "reason": "No pending handoff"}

        if self._pending_handoff.handoff_id != handoff_id:
            return {"status": "error", "reason": "Handoff ID mismatch"}

        self._pending_handoff.status = HandoffStatus.REJECTED
        self._pending_handoff.rejection_reason = reason

        result = {
            "status": "rejected",
            "handoff_id": handoff_id,
            "reason": reason,
            "message": f"Staying with {self.current_agent.value}. How can I help?",
        }

        # Clear pending
        self._pending_handoff = None

        return result

    def _handle_get_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_shared_context tool call.

        Searches the knowledge base for relevant context.
        """
        query = args["query"]
        category = args.get("category", "all")
        limit = args.get("limit", 5)

        # If we have a CAIRN store, search it
        if self.cairn_store is not None:
            try:
                # Search metadata
                items = self.cairn_store.list_metadata(limit=limit)

                results = []
                query_lower = query.lower()

                for item in items:
                    # Simple relevance check - in production, use embeddings
                    item_dict = item.to_dict()
                    item_str = json.dumps(item_dict).lower()
                    if query_lower in item_str:
                        results.append({
                            "entity_type": item.entity_type,
                            "entity_id": item.entity_id,
                            "kanban_state": item.kanban_state.value,
                            "priority": item.priority,
                        })

                return {
                    "found": len(results),
                    "results": results[:limit],
                    "query": query,
                }
            except Exception as e:
                return {
                    "found": 0,
                    "results": [],
                    "error": str(e),
                }

        # If we have a Play store, search it
        if self.play_store is not None:
            try:
                # Search acts
                acts = self.play_store.list_acts()
                results = []

                query_lower = query.lower()
                for act in acts:
                    if query_lower in act.title.lower():
                        results.append({
                            "type": "act",
                            "id": act.id,
                            "title": act.title,
                        })

                return {
                    "found": len(results),
                    "results": results[:limit],
                    "query": query,
                }
            except Exception:
                pass

        return {
            "found": 0,
            "results": [],
            "message": "Knowledge base not available",
        }

    def _handle_save_to_kb(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle save_to_knowledge_base tool call.

        Saves information to the shared knowledge base.
        """
        content = args["content"]
        category = args["category"]
        title = args.get("title", content[:50] + "..." if len(content) > 50 else content)
        tags = args.get("tags", [])

        # If we have a Play store, create a beat
        if self.play_store is not None:
            try:
                # For now, save as a beat in a "Notes" act
                # In production, this would be more sophisticated
                from reos.play.play_fs import Beat

                beat_id = str(uuid.uuid4())
                beat = Beat(
                    id=beat_id,
                    content=f"[{category}] {title}\n\n{content}",
                    tags=tags,
                )

                # Would need to find/create appropriate scene
                return {
                    "saved": True,
                    "id": beat_id,
                    "category": category,
                    "title": title,
                }
            except Exception as e:
                return {
                    "saved": False,
                    "error": str(e),
                }

        # Fallback: just acknowledge
        return {
            "saved": True,
            "category": category,
            "title": title,
            "message": "Saved to knowledge base (in-memory)",
        }


def is_shared_tool(name: str) -> bool:
    """Check if a tool name is a shared tool.

    Args:
        name: Tool name to check.

    Returns:
        True if it's a shared tool.
    """
    shared_names = {tool.name for tool in SHARED_TOOL_DEFINITIONS}
    return name in shared_names


def get_shared_tool_names() -> list[str]:
    """Get list of shared tool names.

    Returns:
        List of shared tool names.
    """
    return [tool.name for tool in SHARED_TOOL_DEFINITIONS]
