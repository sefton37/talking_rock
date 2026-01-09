"""Approval handlers.

Manages the approval workflow for commands requiring user confirmation.
"""

from __future__ import annotations

import json
from typing import Any

from reos.db import Database
from reos.rpc.router import register
from reos.rpc.types import INVALID_PARAMS, RpcError
from reos.security import (
    AuditEventType,
    RateLimitExceeded,
    audit_log,
    check_rate_limit,
    get_auditor,
    is_command_safe,
)


@register("approval/pending", needs_db=True)
def handle_pending(
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


@register("approval/respond", needs_db=True)
def handle_respond(
    db: Database,
    *,
    approval_id: str,
    action: str,  # 'approve', 'reject'
    edited_command: str | None = None,
) -> dict[str, Any]:
    """Respond to an approval request."""
    from reos.linux_tools import execute_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(INVALID_PARAMS, f"Approval not found: {approval_id}")

    if approval.get("status") != "pending":
        raise RpcError(INVALID_PARAMS, "Approval already resolved")

    # SECURITY: Rate limit approval actions
    try:
        check_rate_limit("approval")
    except RateLimitExceeded as e:
        audit_log(
            AuditEventType.RATE_LIMIT_EXCEEDED,
            {"category": "approval", "action": action},
        )
        raise RpcError(-32429, str(e)) from e

    if action == "reject":
        db.resolve_approval(approval_id=approval_id, status="rejected")
        audit_log(
            AuditEventType.APPROVAL_DENIED,
            {
                "approval_id": approval_id,
                "original_command": approval.get("command"),
            },
        )
        return {"status": "rejected", "result": None}

    if action == "approve":
        original_command = str(approval.get("command"))
        command = edited_command if edited_command else original_command
        was_edited = edited_command is not None and edited_command != original_command

        # SECURITY: Re-validate command if it was edited
        if was_edited:
            audit_log(
                AuditEventType.APPROVAL_EDITED,
                {
                    "approval_id": approval_id,
                    "original_command": original_command[:200],
                    "edited_command": command[:200],
                },
            )

            # Check if edited command is safe
            safe, warning = is_command_safe(command)
            if not safe:
                audit_log(
                    AuditEventType.COMMAND_BLOCKED,
                    {
                        "approval_id": approval_id,
                        "command": command[:200],
                        "reason": warning,
                    },
                )
                raise RpcError(
                    INVALID_PARAMS,
                    f"Edited command blocked: {warning}. Cannot bypass safety checks by editing.",
                )

        # SECURITY: Rate limit sudo commands
        if "sudo " in command:
            try:
                check_rate_limit("sudo")
            except RateLimitExceeded as e:
                audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "sudo"})
                raise RpcError(-32429, str(e)) from e

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
            audit_log(
                AuditEventType.COMMAND_EXECUTED,
                {
                    "approval_id": approval_id,
                    "command": command[:200],
                    "error": str(exc),
                },
                success=False,
            )
            return {
                "status": "error",
                "result": {"error": str(exc), "command": command},
            }

    raise RpcError(INVALID_PARAMS, f"Invalid action: {action}")


@register("approval/explain", needs_db=True)
def handle_explain(
    db: Database,
    *,
    approval_id: str,
) -> dict[str, Any]:
    """Get detailed explanation for an approval."""
    from reos.linux_tools import preview_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(INVALID_PARAMS, f"Approval not found: {approval_id}")

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
