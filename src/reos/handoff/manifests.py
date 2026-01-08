"""Agent tool manifests for Talking Rock.

Defines the tool set for each agent with a hard cap of 15 tools.
Research shows LLMs experience significant decision-making degradation
when presented with more than ~20 tools simultaneously.

Each agent has:
- Core tools (domain-specific, ~12 tools)
- Shared tools (3 tools for handoffs and context)
- Total: ≤15 tools

Tool Selection Philosophy:
- Prefer general tools over narrow ones
- Combine related operations when sensible
- Agents are flexible - can handle simple out-of-domain tasks
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reos.handoff.models import AgentType
from reos.handoff.tools import SHARED_TOOL_DEFINITIONS, SharedTool


MAX_TOOLS_PER_AGENT = 15
SHARED_TOOL_COUNT = len(SHARED_TOOL_DEFINITIONS)  # 3
MAX_CORE_TOOLS = MAX_TOOLS_PER_AGENT - SHARED_TOOL_COUNT  # 12


@dataclass(frozen=True)
class CoreTool:
    """Definition of an agent's core tool."""

    name: str
    description: str
    parameters: dict[str, Any]


# =============================================================================
# CAIRN Core Tools (Attention Minder)
# Domain: life organization, knowledge base, calendars, reminders, priorities
# =============================================================================

CAIRN_CORE_TOOLS: list[CoreTool] = [
    # Knowledge Base CRUD
    CoreTool(
        name="kb_create_item",
        description=(
            "Create a new knowledge base entry (todo, note, project, reference). "
            "Use for capturing tasks, ideas, or information."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Brief title"},
                "content": {"type": "string", "description": "Full content"},
                "item_type": {
                    "type": "string",
                    "enum": ["todo", "note", "project", "reference"],
                },
                "priority": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Priority 1-5 (5 = highest)",
                },
                "due_date": {"type": "string", "description": "Due date (ISO format)"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "item_type"],
        },
    ),
    CoreTool(
        name="kb_query",
        description=(
            "Search and filter knowledge base items. "
            "Find todos, notes, projects by various criteria."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "item_type": {
                    "type": "string",
                    "enum": ["all", "todo", "note", "project", "reference"],
                },
                "kanban_state": {
                    "type": "string",
                    "enum": ["active", "backlog", "waiting", "someday", "done"],
                },
                "has_priority": {"type": "boolean"},
                "is_overdue": {"type": "boolean"},
                "limit": {"type": "number", "description": "Max results (default: 20)"},
            },
        },
    ),
    CoreTool(
        name="kb_update_item",
        description="Update an existing knowledge base item.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "Item ID to update"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "priority": {"type": "number", "minimum": 1, "maximum": 5},
                "kanban_state": {
                    "type": "string",
                    "enum": ["active", "backlog", "waiting", "someday", "done"],
                },
                "due_date": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["item_id"],
        },
    ),
    CoreTool(
        name="kb_delete_item",
        description="Remove an item from the knowledge base.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "Item ID to delete"},
                "confirm": {"type": "boolean", "description": "Confirm deletion"},
            },
            "required": ["item_id", "confirm"],
        },
    ),
    # Attention Management
    CoreTool(
        name="get_today_focus",
        description=(
            "Get what needs attention today: calendar events, due items, "
            "high-priority tasks, and items needing decisions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_calendar": {"type": "boolean", "default": True},
                "include_overdue": {"type": "boolean", "default": True},
                "max_items": {"type": "number", "default": 10},
            },
        },
    ),
    CoreTool(
        name="defer_item",
        description=(
            "Defer an item to a later date. Moves to 'someday' state "
            "and sets a defer-until date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "defer_until": {"type": "string", "description": "Date (ISO format)"},
                "reason": {"type": "string", "description": "Why deferring (optional)"},
            },
            "required": ["item_id", "defer_until"],
        },
    ),
    CoreTool(
        name="set_reminder",
        description="Set a time-based or context-based reminder.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "remind_at": {"type": "string", "description": "When to remind (ISO datetime)"},
                "context": {
                    "type": "string",
                    "description": "Context trigger (e.g., 'when I open VSCode')",
                },
                "related_item_id": {"type": "string", "description": "Link to KB item"},
            },
            "required": ["message"],
        },
    ),
    CoreTool(
        name="prioritize_items",
        description="Set or adjust priorities for multiple items at once.",
        parameters={
            "type": "object",
            "properties": {
                "priorities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "priority": {"type": "number", "minimum": 1, "maximum": 5},
                        },
                    },
                    "description": "List of {item_id, priority} pairs",
                },
            },
            "required": ["priorities"],
        },
    ),
    # Calendar Integration
    CoreTool(
        name="calendar_query",
        description="Query calendar events from Thunderbird.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start (ISO date)"},
                "end_date": {"type": "string", "description": "End (ISO date)"},
                "include_todos": {"type": "boolean", "default": False},
            },
        },
    ),
    CoreTool(
        name="calendar_create",
        description="Create a calendar event (requires confirmation).",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "Start datetime (ISO)"},
                "end": {"type": "string", "description": "End datetime (ISO)"},
                "location": {"type": "string"},
                "description": {"type": "string"},
                "all_day": {"type": "boolean", "default": False},
            },
            "required": ["title", "start"],
        },
    ),
    # Contact Integration
    CoreTool(
        name="contact_search",
        description="Search Thunderbird contacts by name, email, or organization.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "number", "default": 10},
            },
            "required": ["query"],
        },
    ),
    CoreTool(
        name="contact_link",
        description="Link a contact to a knowledge base item (project, task).",
        parameters={
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "item_id": {"type": "string"},
                "relationship": {
                    "type": "string",
                    "enum": ["owner", "collaborator", "stakeholder", "waiting_on"],
                },
                "notes": {"type": "string"},
            },
            "required": ["contact_id", "item_id", "relationship"],
        },
    ),
]


# =============================================================================
# ReOS Core Tools (System Agent)
# Domain: Linux system administration, services, packages, terminal
# =============================================================================

REOS_CORE_TOOLS: list[CoreTool] = [
    # System Information
    CoreTool(
        name="system_info",
        description=(
            "Get comprehensive system information: CPU, memory, disk, "
            "network, OS version, uptime."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_network": {"type": "boolean", "default": True},
                "include_disk": {"type": "boolean", "default": True},
            },
        },
    ),
    CoreTool(
        name="process_list",
        description="List running processes, optionally sorted by resource usage.",
        parameters={
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "enum": ["cpu", "memory", "name"],
                    "default": "cpu",
                },
                "limit": {"type": "number", "default": 20},
                "filter": {"type": "string", "description": "Filter by process name"},
            },
        },
    ),
    CoreTool(
        name="service_status",
        description="Get status of systemd services.",
        parameters={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Specific service, or omit for overview",
                },
                "show_failed_only": {"type": "boolean", "default": False},
            },
        },
    ),
    # System Actions
    CoreTool(
        name="shell_execute",
        description=(
            "Execute a shell command. Destructive commands require "
            "user confirmation. Returns output and exit code."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "timeout": {"type": "number", "default": 30, "description": "Timeout seconds"},
                "cwd": {"type": "string", "description": "Working directory"},
                "confirm_destructive": {
                    "type": "boolean",
                    "description": "Set true to confirm destructive commands",
                },
            },
            "required": ["command"],
        },
    ),
    CoreTool(
        name="service_control",
        description="Start, stop, restart, or enable/disable systemd services.",
        parameters={
            "type": "object",
            "properties": {
                "service_name": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "enable", "disable", "status"],
                },
                "confirm": {"type": "boolean", "description": "Confirm the action"},
            },
            "required": ["service_name", "action"],
        },
    ),
    CoreTool(
        name="package_search",
        description="Search for packages using the system package manager.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "installed_only": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    ),
    CoreTool(
        name="package_install",
        description="Install a package (requires confirmation).",
        parameters={
            "type": "object",
            "properties": {
                "package_name": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Confirm installation"},
            },
            "required": ["package_name"],
        },
    ),
    CoreTool(
        name="package_remove",
        description="Remove a package (requires confirmation).",
        parameters={
            "type": "object",
            "properties": {
                "package_name": {"type": "string"},
                "purge": {"type": "boolean", "default": False, "description": "Remove config too"},
                "confirm": {"type": "boolean", "description": "Confirm removal"},
            },
            "required": ["package_name"],
        },
    ),
    # File Operations
    CoreTool(
        name="file_list",
        description="List directory contents with details.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "show_hidden": {"type": "boolean", "default": False},
                "details": {"type": "boolean", "default": True},
            },
        },
    ),
    CoreTool(
        name="file_read",
        description="Read file contents (text files).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "lines": {"type": "number", "description": "Max lines (default: all)"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path"],
        },
    ),
    CoreTool(
        name="file_search",
        description="Find files by name pattern or content.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "name_pattern": {"type": "string", "description": "Filename glob pattern"},
                "content_pattern": {"type": "string", "description": "Content to search for"},
                "max_results": {"type": "number", "default": 50},
            },
        },
    ),
    # Docker
    CoreTool(
        name="docker_status",
        description="Get Docker status: containers, images, resource usage.",
        parameters={
            "type": "object",
            "properties": {
                "show_all_containers": {"type": "boolean", "default": False},
                "show_images": {"type": "boolean", "default": True},
            },
        },
    ),
]


# =============================================================================
# RIVA Core Tools (Code Agent)
# Domain: software development, code editing, debugging, testing, git
# =============================================================================

RIVA_CORE_TOOLS: list[CoreTool] = [
    # Code Understanding
    CoreTool(
        name="code_read_file",
        description=(
            "Read source file with syntax awareness. "
            "Supports line ranges for large files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "number"},
                "end_line": {"type": "number"},
            },
            "required": ["path"],
        },
    ),
    CoreTool(
        name="code_search",
        description=(
            "Search codebase for patterns. Uses ripgrep for speed. "
            "Supports regex and file type filtering."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "path": {"type": "string", "default": ".", "description": "Search root"},
                "file_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to include (e.g., ['py', 'js'])",
                },
                "max_results": {"type": "number", "default": 50},
            },
            "required": ["pattern"],
        },
    ),
    CoreTool(
        name="code_symbols",
        description=(
            "Get symbols (functions, classes, variables) from a file. "
            "Uses AST parsing for Python, regex for other languages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "symbol_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Types: function, class, variable, import",
                },
            },
            "required": ["path"],
        },
    ),
    CoreTool(
        name="code_references",
        description="Find all references to a symbol in the codebase.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name to find"},
                "path": {"type": "string", "description": "Scope search to path"},
            },
            "required": ["symbol"],
        },
    ),
    # Code Modification
    CoreTool(
        name="code_edit",
        description=(
            "Edit code with diff preview. Shows changes before applying. "
            "Supports search/replace and line-based edits."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                        },
                    },
                    "description": "List of {old_text, new_text} replacements",
                },
                "preview_only": {"type": "boolean", "default": True},
            },
            "required": ["path", "edits"],
        },
    ),
    CoreTool(
        name="code_create_file",
        description="Create a new source file with content.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
    ),
    CoreTool(
        name="code_rename_symbol",
        description=(
            "Rename a symbol across the codebase. "
            "Shows all affected locations before applying."
        ),
        parameters={
            "type": "object",
            "properties": {
                "old_name": {"type": "string"},
                "new_name": {"type": "string"},
                "path": {"type": "string", "description": "Scope to path"},
                "preview_only": {"type": "boolean", "default": True},
            },
            "required": ["old_name", "new_name"],
        },
    ),
    # Verification
    CoreTool(
        name="code_run_tests",
        description="Run test suite. Supports pytest, jest, cargo test, go test.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Test path or pattern"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "pytest", "jest", "cargo", "go"],
                    "default": "auto",
                },
                "verbose": {"type": "boolean", "default": False},
            },
        },
    ),
    CoreTool(
        name="code_lint",
        description="Run linter/formatter. Supports ruff, eslint, clippy, etc.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "fix": {"type": "boolean", "default": False, "description": "Auto-fix issues"},
            },
        },
    ),
    CoreTool(
        name="code_typecheck",
        description="Run type checker if available (pyright, tsc, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
            },
        },
    ),
    # Git Operations
    CoreTool(
        name="git_status",
        description="Get repository status: branch, staged, unstaged, untracked.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
            },
        },
    ),
    CoreTool(
        name="git_diff",
        description="Show changes (staged, unstaged, or between refs).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "staged": {"type": "boolean", "default": False},
                "ref": {"type": "string", "description": "Compare to ref (e.g., HEAD~1)"},
            },
        },
    ),
]


# =============================================================================
# Manifest Assembly
# =============================================================================

def get_agent_manifest(agent: AgentType) -> dict[str, Any]:
    """Get the complete tool manifest for an agent.

    Args:
        agent: Which agent's manifest to get.

    Returns:
        Dict with agent info and tools list.
    """
    if agent == AgentType.CAIRN:
        core_tools = CAIRN_CORE_TOOLS
        role = "Attention Minder"
        description = "Life organization, knowledge base, calendars, reminders, priorities"
    elif agent == AgentType.REOS:
        core_tools = REOS_CORE_TOOLS
        role = "System Agent"
        description = "Linux system administration, services, packages, terminal"
    elif agent == AgentType.RIVA:
        core_tools = RIVA_CORE_TOOLS
        role = "Code Agent"
        description = "Software development, code editing, testing, git"
    else:
        raise ValueError(f"Unknown agent: {agent}")

    # Validate tool count
    total_tools = len(core_tools) + SHARED_TOOL_COUNT
    if total_tools > MAX_TOOLS_PER_AGENT:
        raise ValueError(
            f"{agent.value} has {total_tools} tools, exceeds cap of {MAX_TOOLS_PER_AGENT}"
        )

    # Build tool schemas
    tools = []

    # Add shared tools first
    for tool in SHARED_TOOL_DEFINITIONS:
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        })

    # Add core tools
    for tool in core_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        })

    return {
        "agent": agent.value,
        "role": role,
        "description": description,
        "tool_count": total_tools,
        "max_tools": MAX_TOOLS_PER_AGENT,
        "shared_tools": SHARED_TOOL_COUNT,
        "core_tools": len(core_tools),
        "tools": tools,
    }


def get_tool_names_for_agent(agent: AgentType) -> list[str]:
    """Get list of tool names available to an agent.

    Args:
        agent: Which agent.

    Returns:
        List of tool names.
    """
    manifest = get_agent_manifest(agent)
    return [t["function"]["name"] for t in manifest["tools"]]


def validate_all_manifests() -> dict[str, Any]:
    """Validate all agent manifests.

    Returns:
        Validation results.
    """
    results = {
        "valid": True,
        "agents": {},
    }

    for agent in AgentType:
        try:
            manifest = get_agent_manifest(agent)
            results["agents"][agent.value] = {
                "valid": True,
                "tool_count": manifest["tool_count"],
                "under_cap": manifest["tool_count"] <= MAX_TOOLS_PER_AGENT,
            }
        except Exception as e:
            results["valid"] = False
            results["agents"][agent.value] = {
                "valid": False,
                "error": str(e),
            }

    return results
