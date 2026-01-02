"""Safety management for ReOS reasoning system.

Handles risk analysis, backup creation, and rollback capability
for system operations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk classification for operations."""

    SAFE = "safe"              # No system changes, read-only
    LOW = "low"                # Minor changes, easily reversible
    MEDIUM = "medium"          # Significant changes, reversible with effort
    HIGH = "high"              # Major changes, may require manual intervention
    CRITICAL = "critical"      # Potentially destructive, data loss possible


@dataclass(frozen=True)
class RiskAssessment:
    """Assessment of risk for an operation."""

    level: RiskLevel
    reasons: list[str]
    requires_confirmation: bool
    requires_backup: bool
    requires_reboot: bool
    estimated_duration_seconds: int
    affected_components: list[str]
    data_loss_possible: bool
    reversible: bool


@dataclass
class RollbackAction:
    """A recorded action that can be undone."""

    id: str
    timestamp: datetime
    description: str
    rollback_command: str | None
    backup_path: Path | None
    original_state: dict[str, Any]
    completed: bool = False


@dataclass
class SafetyState:
    """Current safety state including pending rollbacks."""

    backup_dir: Path
    rollback_stack: list[RollbackAction] = field(default_factory=list)
    config_backups: dict[str, Path] = field(default_factory=dict)


# Risk patterns for command analysis
SAFE_COMMANDS = frozenset([
    "ls", "cat", "head", "tail", "grep", "find", "which", "whereis",
    "whoami", "hostname", "uname", "uptime", "date", "cal",
    "df", "du", "free", "top", "htop", "ps", "pgrep",
    "ip", "ifconfig", "netstat", "ss", "ping", "traceroute", "nslookup",
    "man", "info", "help", "type", "file", "stat",
    "echo", "printf", "pwd", "env", "printenv",
])

MEDIUM_RISK_COMMANDS = frozenset([
    "apt", "apt-get", "dnf", "yum", "pacman", "zypper",  # Package managers
    "pip", "npm", "cargo",  # Language package managers
    "systemctl", "service",  # Service management
    "chmod", "chown",  # Permission changes
    "cp", "mv", "mkdir", "touch",  # File operations
    "useradd", "usermod", "groupadd",  # User management
])

HIGH_RISK_COMMANDS = frozenset([
    "rm", "rmdir",  # Deletion
    "dd",  # Disk operations
    "mkfs", "fdisk", "parted",  # Partition/format
    "mount", "umount",  # Mount operations
    "iptables", "ufw",  # Firewall
    "shutdown", "reboot", "poweroff", "init",  # Power management
    "passwd", "chpasswd",  # Password changes
])

# Files that should always be backed up before modification
CRITICAL_CONFIG_PATHS = [
    "/etc/fstab",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/sudoers",
    "/etc/ssh/sshd_config",
    "/etc/nginx/nginx.conf",
    "/etc/apache2/apache2.conf",
    "/etc/systemd/system/",
    "/boot/grub/grub.cfg",
]


class SafetyManager:
    """Manages safety, backups, and rollback for system operations."""

    def __init__(self, backup_dir: Path | None = None) -> None:
        """Initialize the safety manager.

        Args:
            backup_dir: Directory for storing backups. Defaults to ~/.reos-data/backups
        """
        if backup_dir is None:
            backup_dir = Path.home() / ".reos-data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        self.state = SafetyState(backup_dir=backup_dir)
        self._load_rollback_stack()

    def _load_rollback_stack(self) -> None:
        """Load pending rollbacks from disk."""
        stack_file = self.state.backup_dir / "rollback_stack.json"
        if stack_file.exists():
            try:
                with open(stack_file) as f:
                    data = json.load(f)
                for item in data:
                    self.state.rollback_stack.append(
                        RollbackAction(
                            id=item["id"],
                            timestamp=datetime.fromisoformat(item["timestamp"]),
                            description=item["description"],
                            rollback_command=item.get("rollback_command"),
                            backup_path=Path(item["backup_path"]) if item.get("backup_path") else None,
                            original_state=item.get("original_state", {}),
                            completed=item.get("completed", False),
                        )
                    )
            except Exception as e:
                logger.warning("Failed to load rollback stack: %s", e)

    def _save_rollback_stack(self) -> None:
        """Persist rollback stack to disk."""
        stack_file = self.state.backup_dir / "rollback_stack.json"
        data = [
            {
                "id": action.id,
                "timestamp": action.timestamp.isoformat(),
                "description": action.description,
                "rollback_command": action.rollback_command,
                "backup_path": str(action.backup_path) if action.backup_path else None,
                "original_state": action.original_state,
                "completed": action.completed,
            }
            for action in self.state.rollback_stack
        ]
        with open(stack_file, "w") as f:
            json.dump(data, f, indent=2)

    def assess_command_risk(self, command: str) -> RiskAssessment:
        """Assess the risk level of a shell command.

        Args:
            command: The command to assess

        Returns:
            RiskAssessment with risk details
        """
        parts = command.strip().split()
        if not parts:
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reasons=["Empty command"],
                requires_confirmation=False,
                requires_backup=False,
                requires_reboot=False,
                estimated_duration_seconds=0,
                affected_components=[],
                data_loss_possible=False,
                reversible=True,
            )

        base_cmd = parts[0].split("/")[-1]  # Handle full paths
        reasons = []
        affected = []

        # Check for sudo
        has_sudo = base_cmd == "sudo"
        if has_sudo and len(parts) > 1:
            base_cmd = parts[1].split("/")[-1]

        # Analyze the command
        if base_cmd in SAFE_COMMANDS:
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reasons=["Read-only operation"],
                requires_confirmation=False,
                requires_backup=False,
                requires_reboot=False,
                estimated_duration_seconds=5,
                affected_components=[],
                data_loss_possible=False,
                reversible=True,
            )

        level = RiskLevel.LOW
        requires_backup = False
        requires_reboot = False
        data_loss = False
        reversible = True
        duration = 30

        if base_cmd in MEDIUM_RISK_COMMANDS:
            level = RiskLevel.MEDIUM
            reasons.append(f"System modification command: {base_cmd}")

            if base_cmd in ("apt", "apt-get", "dnf", "yum", "pacman", "zypper"):
                affected.append("packages")
                duration = 120
                if any(x in command for x in ["remove", "purge", "autoremove"]):
                    reasons.append("Package removal")
                    requires_backup = True
                    level = RiskLevel.HIGH

            if base_cmd in ("systemctl", "service"):
                affected.append("services")
                if any(x in command for x in ["stop", "disable", "mask"]):
                    reasons.append("Service will be stopped or disabled")

            if base_cmd in ("chmod", "chown"):
                affected.append("permissions")
                if "-R" in command:
                    reasons.append("Recursive permission change")
                    level = RiskLevel.HIGH

        if base_cmd in HIGH_RISK_COMMANDS:
            level = RiskLevel.HIGH
            requires_backup = True

            if base_cmd == "rm":
                reasons.append("File/directory deletion")
                data_loss = True
                reversible = False
                affected.append("filesystem")
                if "-r" in command or "-rf" in command:
                    level = RiskLevel.CRITICAL
                    reasons.append("Recursive deletion")

            if base_cmd == "dd":
                level = RiskLevel.CRITICAL
                reasons.append("Low-level disk operation")
                data_loss = True
                reversible = False
                affected.append("disk")
                duration = 300

            if base_cmd in ("shutdown", "reboot", "poweroff"):
                requires_reboot = True
                reasons.append("System restart required")
                affected.append("system")

            if base_cmd in ("mkfs", "fdisk", "parted"):
                level = RiskLevel.CRITICAL
                reasons.append("Disk partitioning/formatting")
                data_loss = True
                reversible = False
                affected.append("disk")

        # Check for paths to critical files
        for critical_path in CRITICAL_CONFIG_PATHS:
            if critical_path in command:
                if level.value < RiskLevel.HIGH.value:
                    level = RiskLevel.HIGH
                requires_backup = True
                reasons.append(f"Affects critical config: {critical_path}")
                affected.append("system-config")

        return RiskAssessment(
            level=level,
            reasons=reasons if reasons else ["Standard operation"],
            requires_confirmation=level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            requires_backup=requires_backup,
            requires_reboot=requires_reboot,
            estimated_duration_seconds=duration,
            affected_components=affected,
            data_loss_possible=data_loss,
            reversible=reversible,
        )

    def backup_file(self, path: Path | str) -> Path | None:
        """Create a backup of a file before modification.

        Args:
            path: Path to the file to backup

        Returns:
            Path to the backup file, or None if backup failed
        """
        path = Path(path)
        if not path.exists():
            logger.debug("Cannot backup non-existent file: %s", path)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = str(path).replace("/", "_").lstrip("_")
        backup_path = self.state.backup_dir / f"{safe_name}.{timestamp}.bak"

        try:
            if path.is_dir():
                shutil.copytree(path, backup_path)
            else:
                shutil.copy2(path, backup_path)

            # Store hash for verification
            if path.is_file():
                with open(path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                with open(backup_path.with_suffix(".sha256"), "w") as f:
                    f.write(file_hash)

            logger.info("Created backup: %s -> %s", path, backup_path)
            self.state.config_backups[str(path)] = backup_path
            return backup_path

        except Exception as e:
            logger.error("Failed to backup %s: %s", path, e)
            return None

    def restore_file(self, original_path: Path | str) -> bool:
        """Restore a file from its most recent backup.

        Args:
            original_path: The original path to restore to

        Returns:
            True if restore succeeded
        """
        original_path = Path(original_path)
        backup_path = self.state.config_backups.get(str(original_path))

        if not backup_path or not backup_path.exists():
            logger.error("No backup found for: %s", original_path)
            return False

        try:
            if backup_path.is_dir():
                if original_path.exists():
                    shutil.rmtree(original_path)
                shutil.copytree(backup_path, original_path)
            else:
                shutil.copy2(backup_path, original_path)

            logger.info("Restored: %s from %s", original_path, backup_path)
            return True

        except Exception as e:
            logger.error("Failed to restore %s: %s", original_path, e)
            return False

    def record_action(
        self,
        description: str,
        rollback_command: str | None = None,
        backup_path: Path | None = None,
        original_state: dict[str, Any] | None = None,
    ) -> RollbackAction:
        """Record an action that can be rolled back.

        Args:
            description: Human-readable description of the action
            rollback_command: Command to undo this action
            backup_path: Path to backup file if applicable
            original_state: Any state information needed for rollback

        Returns:
            The created RollbackAction
        """
        action = RollbackAction(
            id=hashlib.sha256(
                f"{datetime.now().isoformat()}{description}".encode()
            ).hexdigest()[:12],
            timestamp=datetime.now(),
            description=description,
            rollback_command=rollback_command,
            backup_path=backup_path,
            original_state=original_state or {},
        )

        self.state.rollback_stack.append(action)
        self._save_rollback_stack()

        logger.info("Recorded action for rollback: %s", description)
        return action

    def rollback_last(self) -> tuple[bool, str]:
        """Roll back the most recent action.

        Returns:
            (success, message) tuple
        """
        if not self.state.rollback_stack:
            return False, "No actions to roll back"

        action = self.state.rollback_stack[-1]
        if action.completed:
            return False, f"Action already rolled back: {action.description}"

        success = False
        message = ""

        # Try rollback command first
        if action.rollback_command:
            try:
                result = subprocess.run(
                    action.rollback_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    success = True
                    message = f"Rolled back: {action.description}"
                else:
                    message = f"Rollback command failed: {result.stderr}"
            except Exception as e:
                message = f"Rollback command error: {e}"

        # Try backup restore if command failed or wasn't available
        if not success and action.backup_path:
            original_path = action.original_state.get("original_path")
            if original_path:
                if self.restore_file(original_path):
                    success = True
                    message = f"Restored from backup: {action.description}"
                else:
                    message = f"Failed to restore from backup: {action.backup_path}"

        if success:
            action.completed = True
            self._save_rollback_stack()

        return success, message

    def get_rollback_stack(self) -> list[RollbackAction]:
        """Get the current rollback stack.

        Returns:
            List of pending rollback actions (most recent first)
        """
        return list(reversed([a for a in self.state.rollback_stack if not a.completed]))

    def clear_completed_rollbacks(self, older_than_days: int = 7) -> int:
        """Clear old completed rollback entries.

        Args:
            older_than_days: Remove entries older than this many days

        Returns:
            Number of entries removed
        """
        cutoff = datetime.now().timestamp() - (older_than_days * 86400)
        original_count = len(self.state.rollback_stack)

        self.state.rollback_stack = [
            a for a in self.state.rollback_stack
            if not a.completed or a.timestamp.timestamp() > cutoff
        ]

        removed = original_count - len(self.state.rollback_stack)
        if removed > 0:
            self._save_rollback_stack()
            logger.info("Cleared %d old rollback entries", removed)

        return removed

    def create_system_snapshot(self, name: str) -> dict[str, Any]:
        """Create a snapshot of current system state for comparison.

        Args:
            name: Name for this snapshot

        Returns:
            Dictionary containing system state
        """
        snapshot = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "packages": [],
            "disk_usage": {},
        }

        # Capture running services
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts and parts[0].endswith(".service"):
                        snapshot["services"][parts[0]] = "running"
        except Exception as e:
            logger.debug("Failed to capture services: %s", e)

        # Capture disk usage
        try:
            result = subprocess.run(
                ["df", "-h", "/", "/home"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                snapshot["disk_usage"]["raw"] = result.stdout
        except Exception as e:
            logger.debug("Failed to capture disk usage: %s", e)

        # Save snapshot
        snapshot_path = self.state.backup_dir / f"snapshot_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)

        return snapshot
