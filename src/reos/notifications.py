"""D-Bus notification support for ReOS.

Provides desktop notifications using the FreeDesktop Notifications spec.
Falls back gracefully when D-Bus is not available.

Usage:
    from reos.notifications import notify

    notify(
        summary="ReOS Checkpoint",
        body="Your changes appear to be drifting from the roadmap.",
        urgency="normal",
    )
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

# Notification urgency levels
Urgency = Literal["low", "normal", "critical"]


@dataclass
class Notification:
    """A desktop notification."""

    summary: str
    body: str = ""
    urgency: Urgency = "normal"
    timeout_ms: int = 5000
    icon: str = "dialog-information"
    app_name: str = "ReOS"
    actions: list[tuple[str, str]] | None = None  # [(action_id, label), ...]


def notify(
    summary: str,
    body: str = "",
    urgency: Urgency = "normal",
    timeout_ms: int = 5000,
    icon: str = "dialog-information",
) -> bool:
    """Send a desktop notification.

    Tries multiple backends in order:
    1. Native D-Bus via dbus-python (if available)
    2. notify-send CLI tool
    3. Silent fallback (logs warning)

    Args:
        summary: Notification title
        body: Notification body text
        urgency: "low", "normal", or "critical"
        timeout_ms: Auto-dismiss timeout in milliseconds
        icon: Icon name or path

    Returns:
        True if notification was sent, False otherwise
    """
    notification = Notification(
        summary=summary,
        body=body,
        urgency=urgency,
        timeout_ms=timeout_ms,
        icon=icon,
    )

    # Try D-Bus first
    if _notify_dbus(notification):
        return True

    # Fall back to notify-send
    if _notify_send(notification):
        return True

    # Log and fail silently
    import logging

    logging.getLogger(__name__).debug(
        f"Could not send notification: {summary}"
    )
    return False


def _notify_dbus(notification: Notification) -> bool:
    """Send notification via D-Bus directly."""
    try:
        import dbus  # type: ignore[import-not-found]

        bus = dbus.SessionBus()
        notify_obj = bus.get_object(
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications"
        )
        notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")

        # Map urgency to D-Bus hint
        urgency_map = {"low": 0, "normal": 1, "critical": 2}
        hints = {"urgency": dbus.Byte(urgency_map.get(notification.urgency, 1))}

        # Actions: list of [action_id, label, ...]
        actions: list[str] = []
        if notification.actions:
            for action_id, label in notification.actions:
                actions.extend([action_id, label])

        notify_iface.Notify(
            notification.app_name,  # app_name
            0,  # replaces_id (0 = don't replace)
            notification.icon,  # icon
            notification.summary,  # summary
            notification.body,  # body
            actions,  # actions
            hints,  # hints
            notification.timeout_ms,  # timeout
        )
        return True

    except ImportError:
        return False
    except Exception:
        return False


def _notify_send(notification: Notification) -> bool:
    """Send notification via notify-send CLI."""
    if sys.platform != "linux":
        return False

    try:
        cmd = [
            "notify-send",
            "--app-name", notification.app_name,
            "--urgency", notification.urgency,
            "--expire-time", str(notification.timeout_ms),
            "--icon", notification.icon,
            notification.summary,
        ]
        if notification.body:
            cmd.append(notification.body)

        subprocess.run(cmd, capture_output=True, timeout=5)
        return True

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:
        return False


# Convenience functions for common notification types


def notify_checkpoint(
    message: str,
    details: str = "",
) -> bool:
    """Send an alignment checkpoint notification."""
    return notify(
        summary="ReOS Checkpoint",
        body=f"{message}\n\n{details}" if details else message,
        urgency="normal",
        icon="dialog-warning",
    )


def notify_review_ready(
    commit_ref: str = "HEAD",
) -> bool:
    """Notify that a review is ready."""
    return notify(
        summary="Review Ready",
        body=f"Review for {commit_ref} is complete.",
        urgency="low",
        icon="dialog-information",
    )


def notify_error(
    message: str,
    details: str = "",
) -> bool:
    """Send an error notification."""
    return notify(
        summary="ReOS Error",
        body=f"{message}\n\n{details}" if details else message,
        urgency="critical",
        icon="dialog-error",
    )


def notify_kernel_status(
    status: Literal["started", "stopped", "error"],
) -> bool:
    """Notify about kernel status changes."""
    messages = {
        "started": ("ReOS Kernel Started", "The attention kernel is now running."),
        "stopped": ("ReOS Kernel Stopped", "The attention kernel has stopped."),
        "error": ("ReOS Kernel Error", "The attention kernel encountered an error."),
    }
    summary, body = messages.get(status, ("ReOS", "Unknown status"))
    return notify(
        summary=summary,
        body=body,
        urgency="critical" if status == "error" else "low",
    )
