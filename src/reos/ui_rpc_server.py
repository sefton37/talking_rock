"""UI RPC server for the ReOS desktop app.

This is a small JSON-RPC 2.0 server over stdio intended to be used by a
TypeScript desktop shell (Tauri).

Design goals:
- Local-only (stdio; no network listener).
- Metadata-first by default.
- Stable, explicit contract between UI and kernel.

This is intentionally *not* MCP; it's a UI-facing RPC layer. We still expose
`tools/list` + `tools/call` by delegating to the existing repo-scoped tool
catalog so the UI can reuse those capabilities.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .agent import ChatAgent
from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools
from .security import (
    ValidationError,
    validate_service_name,
    validate_container_id,
    escape_shell_arg,
    is_command_safe,
    check_rate_limit,
    RateLimitExceeded,
    audit_log,
    AuditEventType,
    get_auditor,
    configure_auditor,
)
from .play_fs import create_act as play_create_act
from .play_fs import create_beat as play_create_beat
from .play_fs import create_scene as play_create_scene
from .play_fs import kb_list_files as play_kb_list_files
from .play_fs import kb_read as play_kb_read
from .play_fs import kb_write_apply as play_kb_write_apply
from .play_fs import kb_write_preview as play_kb_write_preview
from .play_fs import list_acts as play_list_acts
from .play_fs import list_beats as play_list_beats
from .play_fs import list_scenes as play_list_scenes
from .play_fs import read_me_markdown as play_read_me_markdown
from .play_fs import set_active_act_id as play_set_active_act_id
from .play_fs import update_act as play_update_act
from .play_fs import update_beat as play_update_beat
from .play_fs import update_scene as play_update_scene

_JSON = dict[str, Any]


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _jsonrpc_error(*, req_id: Any, code: int, message: str, data: Any | None = None) -> _JSON:
    err: _JSON = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _jsonrpc_result(*, req_id: Any, result: Any) -> _JSON:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _readline() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line


def _write(obj: Any) -> None:
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Client closed the pipe (e.g., UI exited). Treat as a clean shutdown.
        raise SystemExit(0) from None


def _tools_list() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in list_tools()
        ]
    }


def _handle_tools_call(db: Database, *, name: str, arguments: dict[str, Any] | None) -> Any:
    try:
        return call_tool(db, name=name, arguments=arguments)
    except ToolError as exc:
        # -32602: invalid params
        code = -32602 if exc.code in {"invalid_args", "path_escape"} else -32000
        raise RpcError(code=code, message=exc.message, data=exc.data) from exc


def _handle_chat_respond(
    db: Database,
    *,
    text: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    agent = ChatAgent(db=db)

    # Check for conversational intents (Phase 6)
    if conversation_id:
        intent = agent.detect_intent(text)

        if intent:
            # Handle approval/rejection of pending approvals
            if intent.intent_type in ("approval", "rejection"):
                pending = agent.get_pending_approval_for_conversation(conversation_id)
                if pending:
                    action = "approve" if intent.intent_type == "approval" else "reject"
                    result = _handle_approval_respond(
                        db,
                        approval_id=str(pending["id"]),
                        action=action,
                    )
                    # Return a synthetic response
                    import uuid
                    message_id = uuid.uuid4().hex[:12]
                    if action == "approve":
                        if result.get("status") == "executed":
                            answer = f"Command executed. Return code: {result.get('result', {}).get('return_code', 'unknown')}"
                        else:
                            answer = f"Command execution failed: {result.get('result', {}).get('error', 'unknown error')}"
                    else:
                        answer = "Command rejected."

                    # Store the response
                    db.add_message(
                        message_id=message_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content=answer,
                        message_type="text",
                    )

                    return {
                        "answer": answer,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "message_type": "text",
                        "tool_calls": [],
                        "pending_approval_id": None,
                        "intent_handled": intent.intent_type,
                    }

            # Handle reference resolution
            if intent.intent_type == "reference" and intent.reference_term:
                resolved = agent.resolve_reference(intent.reference_term, conversation_id)
                if resolved:
                    # Expand the text to include the resolved entity
                    text = text.replace(
                        intent.reference_term,
                        f"{intent.reference_term} ({resolved.get('type', '')}: {resolved.get('name', resolved.get('id', ''))})"
                    )

    response = agent.respond(text, conversation_id=conversation_id)
    return {
        "answer": response.answer,
        "conversation_id": response.conversation_id,
        "message_id": response.message_id,
        "message_type": response.message_type,
        "tool_calls": response.tool_calls,
        "pending_approval_id": response.pending_approval_id,
    }


def _handle_intent_detect(
    db: Database,
    *,
    text: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Detect the intent of a user message."""
    agent = ChatAgent(db=db)
    intent = agent.detect_intent(text)

    if not intent:
        return {"detected": False}

    result: dict[str, Any] = {
        "detected": True,
        "intent_type": intent.intent_type,
        "confidence": intent.confidence,
    }

    if intent.choice_number is not None:
        result["choice_number"] = intent.choice_number

    if intent.reference_term:
        result["reference_term"] = intent.reference_term

        # Try to resolve the reference if we have a conversation
        if conversation_id:
            resolved = agent.resolve_reference(intent.reference_term, conversation_id)
            if resolved:
                result["resolved_entity"] = resolved

    return result


# -------------------------------------------------------------------------
# Conversation management handlers
# -------------------------------------------------------------------------


def _handle_conversation_start(db: Database, *, title: str | None = None) -> dict[str, Any]:
    import uuid

    conversation_id = uuid.uuid4().hex[:12]
    db.create_conversation(conversation_id=conversation_id, title=title)
    return {"conversation_id": conversation_id}


def _handle_conversation_list(db: Database, *, limit: int = 50) -> dict[str, Any]:
    conversations = db.iter_conversations(limit=limit)
    return {
        "conversations": [
            {
                "id": str(c.get("id")),
                "title": c.get("title"),
                "started_at": c.get("started_at"),
                "last_active_at": c.get("last_active_at"),
            }
            for c in conversations
        ]
    }


def _handle_conversation_get_messages(
    db: Database,
    *,
    conversation_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    messages = db.get_messages(conversation_id=conversation_id, limit=limit)
    return {
        "messages": [
            {
                "id": str(m.get("id")),
                "role": m.get("role"),
                "content": m.get("content"),
                "message_type": m.get("message_type"),
                "metadata": m.get("metadata"),
                "created_at": m.get("created_at"),
            }
            for m in messages
        ]
    }


# -------------------------------------------------------------------------
# Approval workflow handlers
# -------------------------------------------------------------------------


def _handle_approval_pending(
    db: Database,
    *,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Get all pending approvals."""
    approvals = db.get_pending_approvals(conversation_id=conversation_id)
    return {
        "approvals": [
            {
                "id": str(a.get("id")),
                "conversation_id": a.get("conversation_id"),
                "command": a.get("command"),
                "explanation": a.get("explanation"),
                "risk_level": a.get("risk_level"),
                "affected_paths": json.loads(a.get("affected_paths") or "[]"),
                "undo_command": a.get("undo_command"),
                "plan_id": a.get("plan_id"),
                "step_id": a.get("step_id"),
                "created_at": a.get("created_at"),
            }
            for a in approvals
        ]
    }


def _handle_approval_respond(
    db: Database,
    *,
    approval_id: str,
    action: str,  # 'approve', 'reject'
    edited_command: str | None = None,
) -> dict[str, Any]:
    """Respond to an approval request."""
    from .linux_tools import execute_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(code=-32602, message=f"Approval not found: {approval_id}")

    if approval.get("status") != "pending":
        raise RpcError(code=-32602, message="Approval already resolved")

    # SECURITY: Rate limit approval actions
    try:
        check_rate_limit("approval")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "approval", "action": action})
        raise RpcError(code=-32429, message=str(e))

    if action == "reject":
        db.resolve_approval(approval_id=approval_id, status="rejected")
        audit_log(AuditEventType.APPROVAL_DENIED, {
            "approval_id": approval_id,
            "original_command": approval.get("command"),
        })
        return {"status": "rejected", "result": None}

    if action == "approve":
        original_command = str(approval.get("command"))
        command = edited_command if edited_command else original_command
        was_edited = edited_command is not None and edited_command != original_command

        # SECURITY: Re-validate command if it was edited
        if was_edited:
            audit_log(AuditEventType.APPROVAL_EDITED, {
                "approval_id": approval_id,
                "original_command": original_command[:200],
                "edited_command": command[:200],
            })

            # Check if edited command is safe
            safe, warning = is_command_safe(command)
            if not safe:
                audit_log(AuditEventType.COMMAND_BLOCKED, {
                    "approval_id": approval_id,
                    "command": command[:200],
                    "reason": warning,
                })
                raise RpcError(
                    code=-32602,
                    message=f"Edited command blocked: {warning}. Cannot bypass safety checks by editing.",
                )

        # SECURITY: Rate limit sudo commands
        if "sudo " in command:
            try:
                check_rate_limit("sudo")
            except RateLimitExceeded as e:
                audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "sudo"})
                raise RpcError(code=-32429, message=str(e))

        # Execute the command
        try:
            result = execute_command(command)
            db.resolve_approval(approval_id=approval_id, status="approved")

            # SECURITY: Log command execution
            get_auditor().log_command_execution(
                command=command,
                success=result.returncode == 0,
                return_code=result.returncode,
                approval_id=approval_id,
                edited=was_edited,
            )

            return {
                "status": "executed",
                "result": {
                    "success": result.returncode == 0,
                    "stdout": result.stdout[:10000] if result.stdout else "",
                    "stderr": result.stderr[:10000] if result.stderr else "",
                    "return_code": result.returncode,
                    "command": command,
                },
            }
        except Exception as exc:
            db.resolve_approval(approval_id=approval_id, status="approved")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "approval_id": approval_id,
                "command": command[:200],
                "error": str(exc),
            }, success=False)
            return {
                "status": "error",
                "result": {"error": str(exc), "command": command},
            }

    raise RpcError(code=-32602, message=f"Invalid action: {action}")


def _handle_approval_explain(
    db: Database,
    *,
    approval_id: str,
) -> dict[str, Any]:
    """Get detailed explanation for an approval."""
    from .linux_tools import preview_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(code=-32602, message=f"Approval not found: {approval_id}")

    command = str(approval.get("command"))
    preview = preview_command(command)

    return {
        "command": command,
        "explanation": approval.get("explanation") or preview.description,
        "detailed_explanation": (
            f"Command: {command}\n\n"
            f"Description: {preview.description}\n\n"
            f"Affected paths: {', '.join(preview.affected_paths) if preview.affected_paths else 'None'}\n\n"
            f"Warnings: {', '.join(preview.warnings) if preview.warnings else 'None'}\n\n"
            f"Reversible: {'Yes' if preview.can_undo else 'No'}\n"
            f"Undo command: {preview.undo_command or 'N/A'}"
        ),
        "is_destructive": preview.is_destructive,
        "can_undo": preview.can_undo,
        "undo_command": preview.undo_command,
        "affected_paths": preview.affected_paths,
        "warnings": preview.warnings,
    }


# -------------------------------------------------------------------------
# Plan and Execution handlers (Phase 3 - Reasoning System)
# -------------------------------------------------------------------------

# Store active reasoning engines and executions per session
_reasoning_engines: dict[str, Any] = {}
_active_executions: dict[str, Any] = {}


def _get_reasoning_engine(conversation_id: str, db: Database) -> Any:
    """Get or create a reasoning engine for a conversation."""
    from .reasoning.engine import ReasoningEngine

    if conversation_id not in _reasoning_engines:
        _reasoning_engines[conversation_id] = ReasoningEngine(db=db)
    return _reasoning_engines[conversation_id]


def _handle_plan_preview(
    db: Database,
    *,
    request: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Preview a plan for a request without executing it."""
    engine = _get_reasoning_engine(conversation_id, db)
    result = engine.process(request)

    if not result.plan:
        return {
            "has_plan": False,
            "response": result.response,
            "complexity": result.complexity.level.value if result.complexity else None,
        }

    # Format plan steps
    steps = []
    for i, step in enumerate(result.plan.steps):
        risk_info = {}
        if step.risk:
            risk_info = {
                "level": step.risk.level.value if hasattr(step.risk.level, 'value') else str(step.risk.level),
                "requires_confirmation": step.risk.requires_confirmation,
                "reversible": step.risk.reversible,
            }

        steps.append({
            "number": i + 1,
            "id": step.id,
            "title": step.title,
            "command": step.command,
            "explanation": step.explanation,
            "risk": risk_info,
        })

    return {
        "has_plan": True,
        "plan_id": result.plan.id,
        "title": result.plan.title,
        "steps": steps,
        "needs_approval": result.needs_approval,
        "response": result.response,
        "complexity": result.complexity.level.value if result.complexity else None,
    }


def _handle_plan_approve(
    db: Database,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    """Approve and execute the pending plan."""
    engine = _get_reasoning_engine(conversation_id, db)

    if not engine.get_pending_plan():
        raise RpcError(code=-32602, message="No pending plan to approve")

    # Approve by sending "yes"
    result = engine.process("yes")

    # Track the execution context
    if result.execution_context:
        execution_id = result.plan.id if result.plan else conversation_id
        _active_executions[execution_id] = result.execution_context

    return {
        "status": "executed" if result.execution_context else "no_execution",
        "response": result.response,
        "execution_id": result.plan.id if result.plan else None,
    }


def _handle_plan_cancel(
    db: Database,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    """Cancel the pending plan."""
    engine = _get_reasoning_engine(conversation_id, db)
    engine.cancel_pending()
    return {"ok": True, "message": "Plan cancelled"}


def _handle_execution_status(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Get the status of an execution."""
    context = _active_executions.get(execution_id)

    if not context:
        raise RpcError(code=-32602, message=f"Execution not found: {execution_id}")

    completed_steps = []
    for step_id, result in context.step_results.items():
        completed_steps.append({
            "step_id": step_id,
            "success": result.success,
            "output_preview": result.output[:200] if result.output else "",
        })

    return {
        "execution_id": execution_id,
        "state": context.state.value if hasattr(context.state, 'value') else str(context.state),
        "current_step": context.plan.current_step_index if context.plan else 0,
        "total_steps": len(context.plan.steps) if context.plan else 0,
        "completed_steps": completed_steps,
    }


def _handle_execution_pause(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Pause an execution (for future implementation with async execution)."""
    # Note: Current executor is synchronous, so pause is limited
    return {"ok": True, "message": "Pause requested (takes effect at next step boundary)"}


def _handle_execution_abort(
    db: Database,
    *,
    execution_id: str,
    rollback: bool = True,
) -> dict[str, Any]:
    """Abort an execution and optionally rollback."""
    context = _active_executions.get(execution_id)

    if not context:
        raise RpcError(code=-32602, message=f"Execution not found: {execution_id}")

    # Clean up
    if execution_id in _active_executions:
        del _active_executions[execution_id]

    return {"ok": True, "message": "Execution aborted"}


def _handle_execution_rollback(
    db: Database,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    """Rollback the last operation."""
    engine = _get_reasoning_engine(conversation_id, db)
    result = engine.process("undo")
    return {"response": result.response}


# -------------------------------------------------------------------------
# Streaming execution handlers (Phase 4)
# -------------------------------------------------------------------------


def _handle_execution_start(
    db: Database,
    *,
    command: str,
    execution_id: str,
    cwd: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Start a streaming command execution."""
    from .streaming_executor import get_streaming_executor

    executor = get_streaming_executor()
    executor.start(
        command,
        execution_id=execution_id,
        cwd=cwd,
        timeout=timeout,
    )

    return {
        "execution_id": execution_id,
        "status": "started",
    }


def _handle_execution_output(
    db: Database,
    *,
    execution_id: str,
    since_line: int = 0,
) -> dict[str, Any]:
    """Get streaming output from an execution."""
    from .streaming_executor import get_streaming_executor

    executor = get_streaming_executor()
    lines, is_complete = executor.get_output(execution_id, since_line=since_line)

    result: dict[str, Any] = {
        "lines": lines,
        "is_complete": is_complete,
        "next_line": since_line + len(lines),
    }

    if is_complete:
        final_result = executor.get_result(execution_id)
        if final_result:
            result["return_code"] = final_result["return_code"]
            result["success"] = final_result["success"]
            result["error"] = final_result["error"]
            result["duration_seconds"] = final_result["duration_seconds"]

    return result


def _handle_execution_kill(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Kill a running execution."""
    from .streaming_executor import get_streaming_executor

    executor = get_streaming_executor()
    killed = executor.kill(execution_id)

    return {"ok": killed, "message": "Execution killed" if killed else "Execution not found or already complete"}


# -------------------------------------------------------------------------
# System Dashboard handlers (Phase 5)
# -------------------------------------------------------------------------


def _handle_system_live_state(db: Database) -> dict[str, Any]:
    """Get comprehensive system state for dashboard."""
    from . import linux_tools

    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "memory": {"used_mb": 0, "total_mb": 0, "percent": 0.0},
        "disks": [],
        "load_avg": [0.0, 0.0, 0.0],
        "services": [],
        "containers": [],
        "network": [],
    }

    # Get system info
    try:
        info = linux_tools.get_system_info()
        result["cpu_percent"] = info.get("cpu_percent", 0.0)
        result["memory"] = {
            "used_mb": info.get("memory_used_mb", 0),
            "total_mb": info.get("memory_total_mb", 0),
            "percent": info.get("memory_percent", 0.0),
        }
        result["disks"] = [
            {
                "mount": "/",
                "used_gb": info.get("disk_used_gb", 0),
                "total_gb": info.get("disk_total_gb", 0),
                "percent": info.get("disk_percent", 0.0),
            }
        ]
        result["load_avg"] = info.get("load_avg", [0.0, 0.0, 0.0])
    except Exception:
        pass

    # Get services (top 10 most relevant)
    try:
        services = linux_tools.list_services(limit=10)
        result["services"] = [
            {
                "name": s.get("name", ""),
                "status": s.get("status", "unknown"),
                "active": s.get("active", False),
            }
            for s in services
        ]
    except Exception:
        pass

    # Get containers if Docker is available
    try:
        containers = linux_tools.list_docker_containers()
        result["containers"] = [
            {
                "id": c.get("id", "")[:12],
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "status": c.get("status", "unknown"),
                "ports": c.get("ports", ""),
            }
            for c in containers[:10]
        ]
    except Exception:
        pass

    # Get network interfaces
    try:
        network = linux_tools.get_network_info()
        if "interfaces" in network:
            result["network"] = [
                {
                    "interface": iface.get("name", ""),
                    "ip": iface.get("ipv4", ""),
                    "state": iface.get("state", "unknown"),
                }
                for iface in network["interfaces"][:5]
            ]
    except Exception:
        pass

    return result


def _handle_service_action(
    db: Database,
    *,
    name: str,
    action: str,
) -> dict[str, Any]:
    """Perform an action on a systemd service."""
    from . import linux_tools

    # SECURITY: Validate service name to prevent command injection
    try:
        name = validate_service_name(name)
    except ValidationError as e:
        audit_log(AuditEventType.VALIDATION_FAILED, {"field": "name", "value": name[:50], "error": e.message})
        raise RpcError(code=-32602, message=e.message)

    valid_actions = {"start", "stop", "restart", "status", "logs"}
    if action not in valid_actions:
        raise RpcError(code=-32602, message=f"Invalid action: {action}. Must be one of: {', '.join(valid_actions)}")

    # SECURITY: Rate limit service operations
    try:
        check_rate_limit("service")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "service", "action": action})
        raise RpcError(code=-32429, message=str(e))

    # SECURITY: Escape service name for shell (defense in depth)
    safe_name = escape_shell_arg(name)

    # For logs, return recent journal entries
    if action == "logs":
        try:
            result = linux_tools.execute_command(f"journalctl -u {safe_name} -n 50 --no-pager")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "command": f"journalctl -u {name}",
                "action": action,
                "return_code": result.returncode,
            }, success=result.returncode == 0)
            return {
                "ok": result.returncode == 0,
                "logs": result.stdout if result.stdout else result.stderr,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For status, just check the service
    if action == "status":
        try:
            result = linux_tools.execute_command(f"systemctl status {safe_name} --no-pager")
            return {
                "ok": True,
                "status": result.stdout if result.stdout else result.stderr,
                "active": result.returncode == 0,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For start/stop/restart, create an approval request
    import uuid
    approval_id = uuid.uuid4().hex[:12]
    command = f"sudo systemctl {action} {safe_name}"

    db.create_approval(
        approval_id=approval_id,
        conversation_id="system",
        command=command,
        explanation=f"{action.capitalize()} the {name} service",
        risk_level="medium",
    )

    audit_log(AuditEventType.APPROVAL_REQUESTED, {
        "approval_id": approval_id,
        "command": command,
        "service": name,
        "action": action,
    })

    return {
        "requires_approval": True,
        "approval_id": approval_id,
        "command": command,
        "message": f"Service {action} requires approval",
    }


def _handle_container_action(
    db: Database,
    *,
    container_id: str,
    action: str,
) -> dict[str, Any]:
    """Perform an action on a Docker container."""
    from . import linux_tools

    # SECURITY: Validate container ID to prevent command injection
    try:
        container_id = validate_container_id(container_id)
    except ValidationError as e:
        audit_log(AuditEventType.VALIDATION_FAILED, {"field": "container_id", "value": container_id[:50], "error": e.message})
        raise RpcError(code=-32602, message=e.message)

    valid_actions = {"start", "stop", "restart", "logs"}
    if action not in valid_actions:
        raise RpcError(code=-32602, message=f"Invalid action: {action}. Must be one of: {', '.join(valid_actions)}")

    # SECURITY: Rate limit container operations
    try:
        check_rate_limit("container")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "container", "action": action})
        raise RpcError(code=-32429, message=str(e))

    # SECURITY: Escape container ID for shell (defense in depth)
    safe_id = escape_shell_arg(container_id)

    # For logs, return recent container logs
    if action == "logs":
        try:
            result = linux_tools.execute_command(f"docker logs --tail 50 {safe_id}")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "command": f"docker logs {container_id}",
                "action": action,
                "return_code": result.returncode,
            }, success=result.returncode == 0)
            return {
                "ok": result.returncode == 0,
                "logs": result.stdout if result.stdout else result.stderr,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For start/stop/restart
    try:
        result = linux_tools.execute_command(f"docker {action} {safe_id}")
        audit_log(AuditEventType.COMMAND_EXECUTED, {
            "command": f"docker {action} {container_id}",
            "action": action,
            "return_code": result.returncode,
        }, success=result.returncode == 0)
        return {
            "ok": result.returncode == 0,
            "message": result.stdout if result.stdout else f"Container {action} completed",
            "error": result.stderr if result.returncode != 0 else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _handle_state_get(db: Database, *, key: str) -> dict[str, Any]:
    return {"key": key, "value": db.get_state(key=key)}


def _handle_state_set(db: Database, *, key: str, value: str | None) -> dict[str, Any]:
    db.set_state(key=key, value=value)
    return {"ok": True}


def _handle_personas_list(db: Database) -> dict[str, Any]:
    return {"personas": db.iter_agent_personas(), "active_persona_id": db.get_active_persona_id()}


def _handle_persona_get(db: Database, *, persona_id: str) -> dict[str, Any]:
    persona = db.get_agent_persona(persona_id=persona_id)
    return {"persona": persona}


def _handle_persona_upsert(db: Database, *, persona: dict[str, Any]) -> dict[str, Any]:
    required = {
        "id",
        "name",
        "system_prompt",
        "default_context",
        "temperature",
        "top_p",
        "tool_call_limit",
    }
    missing = sorted(required - set(persona.keys()))
    if missing:
        raise RpcError(code=-32602, message=f"persona missing fields: {', '.join(missing)}")

    db.upsert_agent_persona(
        persona_id=str(persona["id"]),
        name=str(persona["name"]),
        system_prompt=str(persona["system_prompt"]),
        default_context=str(persona["default_context"]),
        temperature=float(persona["temperature"]),
        top_p=float(persona["top_p"]),
        tool_call_limit=int(persona["tool_call_limit"]),
    )
    return {"ok": True}


def _handle_persona_set_active(db: Database, *, persona_id: str | None) -> dict[str, Any]:
    if persona_id is not None and not isinstance(persona_id, str):
        raise RpcError(code=-32602, message="persona_id must be a string or null")
    db.set_active_persona_id(persona_id=persona_id)
    return {"ok": True}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _handle_play_me_read(_db: Database) -> dict[str, Any]:
    return {"markdown": play_read_me_markdown()}


def _handle_play_acts_list(_db: Database) -> dict[str, Any]:
    acts, active_id = play_list_acts()
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_set_active(_db: Database, *, act_id: str) -> dict[str, Any]:
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_scenes_list(_db: Database, *, act_id: str) -> dict[str, Any]:
    scenes = play_list_scenes(act_id=act_id)
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_beats_list(_db: Database, *, act_id: str, scene_id: str) -> dict[str, Any]:
    beats = play_list_beats(act_id=act_id, scene_id=scene_id)
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
            }
            for b in beats
        ]
    }


def _handle_play_acts_create(_db: Database, *, title: str, notes: str | None = None) -> dict[str, Any]:
    try:
        acts, created_id = play_create_act(title=title, notes=notes or "")
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "created_act_id": created_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_scenes_create(
    _db: Database,
    *,
    act_id: str,
    title: str,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        scenes = play_create_scene(
            act_id=act_id,
            title=title,
            intent=intent or "",
            status=status or "",
            time_horizon=time_horizon or "",
            notes=notes or "",
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_scenes_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        scenes = play_update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            intent=intent,
            status=status,
            time_horizon=time_horizon,
            notes=notes,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_beats_create(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_create_beat(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            status=status or "",
            notes=notes or "",
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
            }
            for b in beats
        ]
    }


def _handle_play_beats_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    beat_id: str,
    title: str | None = None,
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_update_beat(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            title=title,
            status=status,
            notes=notes,
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
            }
            for b in beats
        ]
    }


def _handle_play_kb_list(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    try:
        files = play_kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"files": files}


def _handle_play_kb_read(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str = "kb.md",
) -> dict[str, Any]:
    try:
        text = play_kb_read(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path)
    except FileNotFoundError as exc:
        raise RpcError(code=-32602, message=f"file not found: {exc}") from exc
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"path": path, "text": text}


def _handle_play_kb_write_preview(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    try:
        res = play_kb_write_preview(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path, text=text)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "path": path,
        "expected_sha256_current": res["sha256_current"],
        **res,
    }


def _handle_play_kb_write_apply(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=-32602, message="expected_sha256_current is required")
    try:
        res = play_kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256_current,
        )
    except ValueError as exc:
        # Surface conflicts as a deterministic JSON-RPC error.
        raise RpcError(code=-32009, message=str(exc)) from exc
    return {"path": path, **res}


def _handle_jsonrpc_request(db: Database, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "jsonrpc-2.0",
                "serverInfo": {"name": "reos-ui-kernel", "version": "0.1.0"},
            }
            return _jsonrpc_result(req_id=req_id, result=result)

        # Notifications can omit id; ignore.
        if req_id is None:
            return None

        if method == "ping":
            return _jsonrpc_result(req_id=req_id, result={"ok": True})

        if method == "tools/list":
            return _jsonrpc_result(req_id=req_id, result=_tools_list())

        if method == "tools/call":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str) or not name:
                raise RpcError(code=-32602, message="name is required")
            if arguments is not None and not isinstance(arguments, dict):
                raise RpcError(code=-32602, message="arguments must be an object")
            result = _handle_tools_call(db, name=name, arguments=arguments)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "chat/respond":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = params.get("text")
            conversation_id = params.get("conversation_id")
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise RpcError(code=-32602, message="conversation_id must be a string or null")
            result = _handle_chat_respond(db, text=text, conversation_id=conversation_id)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "intent/detect":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = params.get("text")
            conversation_id = params.get("conversation_id")
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise RpcError(code=-32602, message="conversation_id must be a string or null")
            result = _handle_intent_detect(db, text=text, conversation_id=conversation_id)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "conversation/start":
            title = None
            if isinstance(params, dict):
                title = params.get("title")
                if title is not None and not isinstance(title, str):
                    raise RpcError(code=-32602, message="title must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_conversation_start(db, title=title))

        if method == "conversation/list":
            limit = 50
            if isinstance(params, dict):
                limit_param = params.get("limit")
                if limit_param is not None:
                    if not isinstance(limit_param, int) or limit_param < 1:
                        raise RpcError(code=-32602, message="limit must be a positive integer")
                    limit = limit_param
            return _jsonrpc_result(req_id=req_id, result=_handle_conversation_list(db, limit=limit))

        if method == "conversation/get_messages":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            limit = params.get("limit", 50)
            if not isinstance(limit, int) or limit < 1:
                raise RpcError(code=-32602, message="limit must be a positive integer")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_conversation_get_messages(db, conversation_id=conversation_id, limit=limit),
            )

        if method == "approval/pending":
            conversation_id = None
            if isinstance(params, dict):
                conversation_id = params.get("conversation_id")
                if conversation_id is not None and not isinstance(conversation_id, str):
                    raise RpcError(code=-32602, message="conversation_id must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_pending(db, conversation_id=conversation_id),
            )

        if method == "approval/respond":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            approval_id = params.get("approval_id")
            action = params.get("action")
            edited_command = params.get("edited_command")
            if not isinstance(approval_id, str) or not approval_id:
                raise RpcError(code=-32602, message="approval_id is required")
            if not isinstance(action, str) or action not in ("approve", "reject"):
                raise RpcError(code=-32602, message="action must be 'approve' or 'reject'")
            if edited_command is not None and not isinstance(edited_command, str):
                raise RpcError(code=-32602, message="edited_command must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_respond(
                    db, approval_id=approval_id, action=action, edited_command=edited_command
                ),
            )

        if method == "approval/explain":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            approval_id = params.get("approval_id")
            if not isinstance(approval_id, str) or not approval_id:
                raise RpcError(code=-32602, message="approval_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_explain(db, approval_id=approval_id),
            )

        # Plan and Execution methods (Phase 3)
        if method == "plan/preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            request = params.get("request")
            conversation_id = params.get("conversation_id")
            if not isinstance(request, str) or not request.strip():
                raise RpcError(code=-32602, message="request is required")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_plan_preview(db, request=request, conversation_id=conversation_id),
            )

        if method == "plan/approve":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_plan_approve(db, conversation_id=conversation_id),
            )

        if method == "plan/cancel":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_plan_cancel(db, conversation_id=conversation_id),
            )

        if method == "execution/status":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_status(db, execution_id=execution_id),
            )

        if method == "execution/pause":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_pause(db, execution_id=execution_id),
            )

        if method == "execution/abort":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            rollback = params.get("rollback", True)
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_abort(db, execution_id=execution_id, rollback=bool(rollback)),
            )

        if method == "execution/rollback":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_rollback(db, conversation_id=conversation_id),
            )

        # Streaming execution methods (Phase 4)
        if method == "execution/start":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            command = params.get("command")
            execution_id = params.get("execution_id")
            cwd = params.get("cwd")
            timeout = params.get("timeout", 300)
            if not isinstance(command, str) or not command.strip():
                raise RpcError(code=-32602, message="command is required")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            if cwd is not None and not isinstance(cwd, str):
                raise RpcError(code=-32602, message="cwd must be a string or null")
            if not isinstance(timeout, int) or timeout < 1:
                timeout = 300
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_start(
                    db, command=command, execution_id=execution_id, cwd=cwd, timeout=timeout
                ),
            )

        if method == "execution/output":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            since_line = params.get("since_line", 0)
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            if not isinstance(since_line, int) or since_line < 0:
                since_line = 0
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_output(db, execution_id=execution_id, since_line=since_line),
            )

        if method == "execution/kill":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_kill(db, execution_id=execution_id),
            )

        # System Dashboard methods (Phase 5)
        if method == "system/live_state":
            return _jsonrpc_result(req_id=req_id, result=_handle_system_live_state(db))

        if method == "service/action":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            name = params.get("name")
            action = params.get("action")
            if not isinstance(name, str) or not name:
                raise RpcError(code=-32602, message="name is required")
            if not isinstance(action, str) or not action:
                raise RpcError(code=-32602, message="action is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_service_action(db, name=name, action=action),
            )

        if method == "container/action":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            container_id = params.get("container_id")
            action = params.get("action")
            if not isinstance(container_id, str) or not container_id:
                raise RpcError(code=-32602, message="container_id is required")
            if not isinstance(action, str) or not action:
                raise RpcError(code=-32602, message="action is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_container_action(db, container_id=container_id, action=action),
            )

        if method == "state/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = params.get("key")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_state_get(db, key=key))

        if method == "state/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = params.get("key")
            value = params.get("value")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            if value is not None and not isinstance(value, str):
                raise RpcError(code=-32602, message="value must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_state_set(db, key=key, value=value))

        if method == "personas/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_personas_list(db))

        if method == "personas/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if not isinstance(persona_id, str) or not persona_id:
                raise RpcError(code=-32602, message="persona_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_get(db, persona_id=persona_id))

        if method == "personas/upsert":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona = params.get("persona")
            if not isinstance(persona, dict):
                raise RpcError(code=-32602, message="persona must be an object")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_upsert(db, persona=persona))

        if method == "personas/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if persona_id is not None and not isinstance(persona_id, str):
                raise RpcError(code=-32602, message="persona_id must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_set_active(db, persona_id=persona_id))

        if method == "play/me/read":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_me_read(db))

        if method == "play/acts/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_list(db))

        if method == "play/acts/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            title = params.get("title")
            notes = params.get("notes")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            if notes is not None and not isinstance(notes, str):
                raise RpcError(code=-32602, message="notes must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_create(db, title=title, notes=notes))

        if method == "play/acts/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            notes = params.get("notes")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if title is not None and not isinstance(title, str):
                raise RpcError(code=-32602, message="title must be a string or null")
            if notes is not None and not isinstance(notes, str):
                raise RpcError(code=-32602, message="notes must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_acts_update(db, act_id=act_id, title=title, notes=notes),
            )

        if method == "play/acts/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_set_active(db, act_id=act_id))

        if method == "play/scenes/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_scenes_list(db, act_id=act_id))

        if method == "play/scenes/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_create(
                    db,
                    act_id=act_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/scenes/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            title = params.get("title")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "title": title,
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/beats/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_list(db, act_id=act_id, scene_id=scene_id),
            )

        if method == "play/beats/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"status": status, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_create(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    status=status,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/beats/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(beat_id, str) or not beat_id:
                raise RpcError(code=-32602, message="beat_id is required")
            title = params.get("title")
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"title": title, "status": status, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    title=title,
                    status=status,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/kb/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_list(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id),
            )

        if method == "play/kb/read":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path", "kb.md")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id, "path": path}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_read(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path),
            )

        if method == "play/kb/write_preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path")
            text = params.get("text")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_preview(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                ),
            )

        if method == "play/kb/write_apply":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path")
            text = params.get("text")
            expected_sha256_current = params.get("expected_sha256_current")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
                raise RpcError(code=-32602, message="expected_sha256_current is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_apply(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                    expected_sha256_current=expected_sha256_current,
                ),
            )

        raise RpcError(code=-32601, message=f"Method not found: {method}")

    except RpcError as exc:
        return _jsonrpc_error(req_id=req_id, code=exc.code, message=exc.message, data=exc.data)
    except Exception as exc:  # noqa: BLE001
        return _jsonrpc_error(
            req_id=req_id,
            code=-32099,
            message="Internal error",
            data={"error": str(exc)},
        )


def run_stdio_server() -> None:
    """Run the UI kernel server over stdio."""

    db = get_db()
    db.migrate()

    while True:
        line = _readline()
        if line is None:
            return

        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(req, dict):
            continue

        resp = _handle_jsonrpc_request(db, req)
        if resp is not None:
            _write(resp)


def main() -> None:
    run_stdio_server()


if __name__ == "__main__":
    main()
