"""Linux system tools for ReOS - Making Linux as easy as chatting with AI.

This module provides tools for interacting with the Linux system:
- Shell command execution (with safety guardrails)
- System monitoring (CPU, RAM, disk, network)
- Package management (apt/dnf/pacman/zypper detection)
- Service management (systemd)
- Process management
- File operations
- Docker/container management
- Log analysis
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SECURITY, TIMEOUTS
from .types import (
    ServiceStatus,
    DiskUsageInfo,
    DirectoryEntry,
    LogFileResult,
    EnvironmentInfo,
    InterfaceInfo,
    AddressInfo,
)
from .security import (
    is_command_dangerous as security_is_command_dangerous,
    audit_log,
    AuditEventType,
    RateLimiter,
    RateLimitExceeded,
)

logger = logging.getLogger(__name__)

# Module-level rate limiter for tool-layer enforcement
_rate_limiter = RateLimiter()

# Sudo escalation counter (per-session, resets on module reload)
_sudo_escalation_count = 0
_MAX_SUDO_ESCALATIONS = SECURITY.MAX_SUDO_ESCALATIONS

# Dangerous commands that should never be executed (exact patterns)
# These use regex to avoid false positives like "rm -rf /tmp/testdir"
DANGEROUS_COMMAND_PATTERNS = [
    r"^rm\s+(-[rf]+\s+)*/$",           # rm -rf /
    r"^rm\s+(-[rf]+\s+)*/\*",          # rm -rf /*
    r"dd\s+if=/dev/zero\s+of=/dev/sd", # dd to disk
    r"^mkfs\s+/dev/sd",                # mkfs on physical disk
    r":\(\)\{:\|:&\};:",               # Fork bomb
    r"^chmod\s+-R\s+[07]{3}\s+/$",     # chmod -R 777 /
    r">\s*/dev/sd",                    # Redirect to disk
    r"^mv\s+/\s+/dev/null",            # mv / /dev/null
]

# Commands that require confirmation
RISKY_PATTERNS = [
    r"rm\s+-rf\s+",
    r"dd\s+if=",
    r"mkfs\.",
    r"fdisk",
    r"parted",
    r"shutdown",
    r"reboot",
    r"init\s+0",
    r"poweroff",
    r"halt",
]


@dataclass(frozen=True)
class CommandResult:
    """Result of a shell command execution."""
    command: str
    returncode: int
    stdout: str
    stderr: str
    success: bool


@dataclass(frozen=True)
class SystemInfo:
    """System information snapshot."""
    hostname: str
    kernel: str
    distro: str
    uptime: str
    cpu_model: str
    cpu_cores: int
    memory_total_mb: int
    memory_used_mb: int
    memory_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_percent: float
    load_avg: tuple[float, float, float]


@dataclass(frozen=True)
class ProcessInfo:
    """Information about a running process."""
    pid: int
    user: str
    cpu_percent: float
    mem_percent: float
    command: str
    status: str


@dataclass(frozen=True)
class ServiceInfo:
    """Information about a systemd service."""
    name: str
    load_state: str
    active_state: str
    sub_state: str
    description: str


def detect_package_manager() -> str | None:
    """Detect the system's package manager."""
    managers = [
        ("apt", "/usr/bin/apt"),
        ("dnf", "/usr/bin/dnf"),
        ("yum", "/usr/bin/yum"),
        ("pacman", "/usr/bin/pacman"),
        ("zypper", "/usr/bin/zypper"),
        ("apk", "/sbin/apk"),
        ("emerge", "/usr/bin/emerge"),
        ("nix-env", "/run/current-system/sw/bin/nix-env"),
    ]
    for name, path in managers:
        if os.path.exists(path):
            return name
    return None


def check_sudo_available() -> tuple[bool, str | None]:
    """Check if the user can run sudo without a password prompt.

    Returns:
        Tuple of (can_sudo, error_message).
        If can_sudo is True, error_message is None.
        If can_sudo is False, error_message explains why.
    """
    try:
        # -n = non-interactive, will fail if password is required
        result = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, None
        # sudo exists but requires password
        return False, (
            "sudo requires a password. Either:\n"
            "  1. Run 'sudo -v' first to cache credentials, or\n"
            "  2. Configure passwordless sudo for package management"
        )
    except FileNotFoundError:
        return False, "sudo is not installed on this system"
    except subprocess.TimeoutExpired:
        return False, "sudo check timed out"
    except Exception as e:
        return False, f"Failed to check sudo availability: {e}"


def detect_distro() -> str:
    """Detect the Linux distribution."""
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        # Fallback to lsb_release
        result = subprocess.run(
            ["lsb_release", "-d", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug("Failed to detect distro: %s", e)
    return "Linux (unknown distro)"


def is_command_safe(command: str) -> tuple[bool, str | None]:
    """Check if a command is safe to execute.

    Uses the security module's comprehensive pattern matching plus local patterns.
    Returns (is_safe, warning_message).

    Safety levels:
    - Dangerous: Blocked unconditionally (rm -rf /, fork bombs, etc.)
    - Risky: Blocked by default, requires explicit approval workflow
    - Normal: Allowed
    """
    global _sudo_escalation_count

    cmd_stripped = command.strip()

    # SECURITY: Use the more comprehensive security module patterns first
    is_dangerous, reason = security_is_command_dangerous(command)
    if is_dangerous:
        audit_log(AuditEventType.COMMAND_BLOCKED, {
            "command": command[:200],
            "reason": reason,
        })
        return False, f"Blocked dangerous command: {reason}"

    # Legacy check: local dangerous command patterns
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd_stripped, re.IGNORECASE):
            audit_log(AuditEventType.COMMAND_BLOCKED, {
                "command": command[:200],
                "reason": f"Pattern: {pattern}",
            })
            return False, f"Blocked dangerous command matching pattern: {pattern}"

    # Check for sudo escalation limit
    if cmd_stripped.startswith("sudo ") or " sudo " in cmd_stripped:
        if _sudo_escalation_count >= _MAX_SUDO_ESCALATIONS:
            audit_log(AuditEventType.COMMAND_BLOCKED, {
                "command": command[:200],
                "reason": "Sudo escalation limit reached",
                "count": _sudo_escalation_count,
                "max": _MAX_SUDO_ESCALATIONS,
            })
            return False, f"Sudo escalation limit reached ({_MAX_SUDO_ESCALATIONS} max per session)"
        _sudo_escalation_count += 1
        logger.info("Sudo escalation %d/%d: %s", _sudo_escalation_count, _MAX_SUDO_ESCALATIONS, command[:50])

    # Check for risky patterns - now BLOCKED, not just warned
    # These require explicit approval through the approval workflow, not direct execution
    for pattern in RISKY_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            audit_log(AuditEventType.COMMAND_BLOCKED, {
                "command": command[:200],
                "reason": f"Risky pattern requires approval: {pattern}",
            })
            return False, f"Risky command blocked: {pattern}. Use the approval workflow for destructive operations."

    return True, None


def reset_sudo_escalation_count() -> None:
    """Reset the sudo escalation counter. Called at session boundaries."""
    global _sudo_escalation_count
    _sudo_escalation_count = 0
    logger.debug("Sudo escalation counter reset")


def get_sudo_escalation_status() -> tuple[int, int]:
    """Get current sudo escalation status.

    Returns:
        Tuple of (current_count, max_allowed)
    """
    return _sudo_escalation_count, _MAX_SUDO_ESCALATIONS


def _make_command_noninteractive(command: str) -> str:
    """Add non-interactive flags to package manager commands.

    This prevents commands from hanging waiting for user input when run
    via subprocess with captured stdin.

    Args:
        command: The command to modify

    Returns:
        Modified command with appropriate flags added
    """
    import re

    cmd = command.strip()

    # apt/apt-get install/remove/upgrade without -y
    # Match: sudo apt install pkg, apt-get upgrade, etc.
    if re.search(r'(sudo\s+)?(apt(?:-get)?)\s+(install|remove|purge|upgrade|dist-upgrade|autoremove)', cmd):
        if ' -y' not in cmd and ' --yes' not in cmd:
            # Insert -y after the action word
            cmd = re.sub(
                r'((sudo\s+)?(apt(?:-get)?)\s+(install|remove|purge|upgrade|dist-upgrade|autoremove))',
                r'\1 -y',
                cmd,
                count=1
            )

    # dnf/yum install/remove/upgrade without -y
    if re.search(r'(sudo\s+)?(dnf|yum)\s+(install|remove|erase|upgrade|update)', cmd):
        if ' -y' not in cmd and ' --assumeyes' not in cmd:
            cmd = re.sub(
                r'((sudo\s+)?(dnf|yum)\s+(install|remove|erase|upgrade|update))',
                r'\1 -y',
                cmd,
                count=1
            )

    # pacman without --noconfirm
    if re.search(r'(sudo\s+)?pacman\s+-S', cmd) and '--noconfirm' not in cmd:
        cmd = re.sub(r'(pacman\s+-S)', r'\1 --noconfirm', cmd, count=1)

    # zypper without -y or -n
    if re.search(r'(sudo\s+)?zypper\s+(install|remove|update)', cmd):
        if ' -y' not in cmd and ' -n' not in cmd and ' --non-interactive' not in cmd:
            cmd = re.sub(r'(zypper)\s+(install|remove|update)', r'\1 -n \2', cmd, count=1)

    return cmd


def execute_command(
    command: str,
    *,
    timeout: int = 30,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    rate_limit_category: str | None = None,
    interactive: bool = False,
) -> CommandResult:
    """Execute a shell command safely.

    Args:
        command: The command to execute
        timeout: Maximum execution time in seconds
        cwd: Working directory
        env: Environment variables to add
        rate_limit_category: Optional category for rate limiting (e.g., "sudo", "service")
        interactive: If True, run with stdin/stdout/stderr connected to terminal
                    (allows user input but output won't be captured)

    Returns:
        CommandResult with output and status
    """
    # Check rate limit if category specified
    if rate_limit_category:
        try:
            _rate_limiter.check(rate_limit_category)
        except RateLimitExceeded as e:
            audit_log(AuditEventType.COMMAND_BLOCKED, {
                "command": command[:200],
                "reason": f"Rate limit exceeded: {rate_limit_category}",
            })
            return CommandResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=str(e),
                success=False,
            )

    # Auto-detect rate limit category from command if not specified
    cmd_lower = command.lower().strip()
    if rate_limit_category is None:
        if cmd_lower.startswith("sudo "):
            try:
                _rate_limiter.check("sudo")
            except RateLimitExceeded as e:
                return CommandResult(
                    command=command,
                    returncode=-1,
                    stdout="",
                    stderr=str(e),
                    success=False,
                )

    is_safe, warning = is_command_safe(command)
    if not is_safe:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout="",
            stderr=warning or "Command blocked for safety",
            success=False,
        )

    # Check if we're running in terminal mode (from shell_cli)
    # In terminal mode, commands run with full terminal access so users can interact
    terminal_mode = os.environ.get("REOS_TERMINAL_MODE") == "1"

    # Only add -y flags if NOT in terminal mode (GUI/API context)
    # In terminal mode, let the user respond to prompts naturally
    if not terminal_mode:
        command = _make_command_noninteractive(command)

    # Prepare environment
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        if interactive or terminal_mode:
            # Terminal mode: use os.system() for full terminal pass-through
            # This is the most reliable way to run interactive commands because
            # it runs the command directly in a shell with full terminal inheritance.
            # subprocess.run() can have issues with stdin even when explicitly passed.
            #
            # Note: os.system() doesn't support timeout, but interactive commands
            # need user input anyway, so timeout doesn't make sense here.

            # Save current directory, change if needed
            old_cwd = None
            if cwd:
                old_cwd = os.getcwd()
                os.chdir(cwd)

            # Set environment variables
            old_env: dict[str, str | None] = {}
            for key, value in (env or {}).items():
                old_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                # os.system() runs with full terminal access - stdin, stdout, stderr
                # all connected to the terminal. Interactive prompts work naturally.
                returncode = os.system(command)
                # os.system returns the wait status, need to extract exit code
                if os.name == 'posix':
                    returncode = os.waitstatus_to_exitcode(returncode) if hasattr(os, 'waitstatus_to_exitcode') else returncode >> 8
            finally:
                # Restore environment
                for key, old_value in old_env.items():
                    if old_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old_value
                # Restore directory
                if old_cwd:
                    os.chdir(old_cwd)

            return CommandResult(
                command=command,
                returncode=returncode,
                stdout="(command executed in terminal)",
                stderr="",
                success=returncode == 0,
            )
        else:
            # Non-interactive mode (GUI/API): capture output
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=run_env,
            )
            return CommandResult(
                command=command,
                returncode=result.returncode,
                stdout=result.stdout[:10000] if result.stdout else "",  # Limit output
                stderr=result.stderr[:5000] if result.stderr else "",
                success=result.returncode == 0,
            )
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            success=False,
        )
    except Exception as e:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout="",
            stderr=str(e),
            success=False,
        )


@dataclass(frozen=True)
class CommandPreview:
    """Preview of what a command would do before execution."""
    command: str
    is_destructive: bool
    description: str
    affected_paths: list[str]
    warnings: list[str]
    can_undo: bool
    undo_command: str | None


def preview_command(command: str, cwd: str | None = None) -> CommandPreview:
    """Analyze a command and preview what it would do.

    This allows users to see the effects before executing destructive commands.
    Supports the principle: "Mistakes are recoverable - you can say 'wait, undo that'"

    The preview is used in the approval workflow to show users what a command
    would do before they approve it. Even blocked commands get previewed so
    users understand what they're being asked to approve.

    Args:
        command: The command to preview
        cwd: Working directory for resolving relative paths

    Returns:
        CommandPreview with details about what the command would do
    """
    is_safe, warning = is_command_safe(command)
    working_dir = Path(cwd) if cwd else Path.cwd()

    affected_paths: list[str] = []
    warnings: list[str] = []
    description = "Execute command"
    is_destructive = False
    can_undo = False
    undo_command: str | None = None

    if warning:
        warnings.append(warning)

    # Check for truly dangerous patterns that should never be previewed
    # (these are catastrophic like rm -rf / or fork bombs)
    cmd_stripped = command.strip()
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd_stripped, re.IGNORECASE):
            return CommandPreview(
                command=command,
                is_destructive=True,
                description="BLOCKED: Dangerous command",
                affected_paths=[],
                warnings=warnings,
                can_undo=False,
                undo_command=None,
            )

    # For risky commands, continue with preview (approval workflow will handle)
    if not is_safe:
        is_destructive = True  # Mark as destructive for approval workflow

    # Analyze rm commands
    rm_match = re.match(r'^rm\s+(.*)', command, re.IGNORECASE)
    if rm_match:
        is_destructive = True
        args = rm_match.group(1)
        description = "Delete files/directories"

        # Parse flags and paths
        parts = args.split()
        paths_to_check = []
        for part in parts:
            if not part.startswith('-'):
                paths_to_check.append(part)

        for path_str in paths_to_check:
            # Expand globs
            import glob
            expanded = glob.glob(str(working_dir / path_str))
            if expanded:
                affected_paths.extend(expanded[:50])  # Limit to 50 paths
            else:
                # Path doesn't exist yet or is a literal
                full_path = working_dir / path_str
                if full_path.exists():
                    affected_paths.append(str(full_path))

        if '-r' in args or '-rf' in args or '-fr' in args:
            warnings.append("Recursive deletion - will delete entire directory trees")
        if '-f' in args:
            warnings.append("Force mode - will not prompt for confirmation")

        can_undo = False  # rm cannot be undone without backup
        undo_command = None

    # Analyze mv commands
    mv_match = re.match(r'^mv\s+(.+)\s+(\S+)$', command)
    if mv_match:
        is_destructive = True
        sources = mv_match.group(1).split()
        dest = mv_match.group(2)
        description = f"Move/rename to {dest}"

        for src in sources:
            if not src.startswith('-'):
                full_path = working_dir / src
                if full_path.exists():
                    affected_paths.append(str(full_path))

        if affected_paths:
            can_undo = True
            # Generate undo command (simplified - assumes single file move)
            if len(affected_paths) == 1:
                undo_command = f"mv {dest} {affected_paths[0]}"

    # Analyze package manager operations
    pkg_patterns = [
        (r'^(apt|apt-get)\s+(install|remove|purge)', "Package installation/removal"),
        (r'^dnf\s+(install|remove)', "Package installation/removal"),
        (r'^pacman\s+-[SR]', "Package installation/removal"),
        (r'^yum\s+(install|remove)', "Package installation/removal"),
    ]

    for pattern, desc in pkg_patterns:
        if re.match(pattern, command, re.IGNORECASE):
            is_destructive = True
            description = desc
            warnings.append("Package operations modify system-wide software")

            # Try dry-run to see what would change
            dry_run_cmd = None
            if 'apt' in command.lower():
                dry_run_cmd = command + ' --dry-run'
            elif 'dnf' in command.lower():
                dry_run_cmd = command + ' --assumeno'

            if dry_run_cmd:
                try:
                    result = subprocess.run(
                        dry_run_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=cwd,
                    )
                    # Package names from dry-run output would be in affected_paths
                    for line in result.stdout.splitlines()[:20]:
                        if line.strip():
                            affected_paths.append(f"[package] {line.strip()}")
                except Exception as e:
                    logger.debug("Failed to run package dry-run: %s", e)
            break

    # Analyze service management
    if re.match(r'^(systemctl|service)\s+(stop|disable|mask)', command, re.IGNORECASE):
        is_destructive = True
        description = "Stop/disable system service"
        warnings.append("Stopping services may affect system functionality")
        can_undo = True

        # Extract service name and create undo command
        service_match = re.search(r'(stop|disable|mask)\s+(\S+)', command)
        if service_match:
            action, service = service_match.groups()
            undo_actions = {'stop': 'start', 'disable': 'enable', 'mask': 'unmask'}
            undo_action = undo_actions.get(action, 'start')
            if 'systemctl' in command:
                undo_command = f"systemctl {undo_action} {service}"
            else:
                undo_command = f"service {service} {undo_action}"

    return CommandPreview(
        command=command,
        is_destructive=is_destructive,
        description=description,
        affected_paths=affected_paths,
        warnings=warnings,
        can_undo=can_undo,
        undo_command=undo_command,
    )


def get_system_info() -> SystemInfo:
    """Get comprehensive system information."""
    hostname = "unknown"
    kernel = "unknown"
    uptime = "unknown"
    cpu_model = "unknown"
    cpu_cores = 0
    memory_total_mb = 0
    memory_used_mb = 0
    memory_percent = 0.0
    disk_total_gb = 0.0
    disk_used_gb = 0.0
    disk_percent = 0.0
    load_avg = (0.0, 0.0, 0.0)

    try:
        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception as e:
        logger.debug("Failed to get hostname: %s", e)

    try:
        kernel = subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception as e:
        logger.debug("Failed to get kernel version: %s", e)

    distro = detect_distro()

    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            uptime = f"{days}d {hours}h {minutes}m"
    except Exception as e:
        logger.debug("Failed to get uptime: %s", e)

    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        cpu_cores = os.cpu_count() or 0
    except Exception as e:
        logger.debug("Failed to get CPU info: %s", e)

    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = int(parts[1].strip().split()[0])  # Value in kB
                    meminfo[key] = value

            memory_total_mb = meminfo.get("MemTotal", 0) // 1024
            mem_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            memory_used_mb = (meminfo.get("MemTotal", 0) - mem_available) // 1024
            if memory_total_mb > 0:
                memory_percent = (memory_used_mb / memory_total_mb) * 100
    except Exception as e:
        logger.debug("Failed to get memory info: %s", e)

    try:
        stat = os.statvfs("/")
        disk_total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
        disk_used_gb = ((stat.f_blocks - stat.f_bfree) * stat.f_frsize) / (1024**3)
        if disk_total_gb > 0:
            disk_percent = (disk_used_gb / disk_total_gb) * 100
    except Exception as e:
        logger.debug("Failed to get disk info: %s", e)

    try:
        load_avg = os.getloadavg()
    except Exception as e:
        logger.debug("Failed to get load average: %s", e)

    return SystemInfo(
        hostname=hostname,
        kernel=kernel,
        distro=distro,
        uptime=uptime,
        cpu_model=cpu_model,
        cpu_cores=cpu_cores,
        memory_total_mb=memory_total_mb,
        memory_used_mb=memory_used_mb,
        memory_percent=round(memory_percent, 1),
        disk_total_gb=round(disk_total_gb, 1),
        disk_used_gb=round(disk_used_gb, 1),
        disk_percent=round(disk_percent, 1),
        load_avg=load_avg,
    )


def get_network_info() -> dict[str, Any]:
    """Get network interface information."""
    interfaces = {}

    try:
        result = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            for iface in data:
                name = iface.get("ifname", "unknown")
                addrs = []
                for addr_info in iface.get("addr_info", []):
                    addrs.append({
                        "family": addr_info.get("family"),
                        "address": addr_info.get("local"),
                        "prefix": addr_info.get("prefixlen"),
                    })
                interfaces[name] = {
                    "state": iface.get("operstate", "unknown"),
                    "mac": iface.get("address"),
                    "addresses": addrs,
                }
    except Exception as e:
        logger.debug("Failed to parse JSON network info, falling back: %s", e)
        # Fallback to basic parsing
        try:
            result = subprocess.run(
                ["ip", "addr", "show"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                current_iface = None
                for line in result.stdout.splitlines():
                    if line and not line.startswith(" "):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            current_iface = parts[1].strip()
                            interfaces[current_iface] = {"addresses": []}
                    elif current_iface and "inet " in line:
                        match = re.search(r"inet (\S+)", line)
                        if match:
                            interfaces[current_iface]["addresses"].append({
                                "family": "inet",
                                "address": match.group(1).split("/")[0],
                            })
        except Exception as e2:
            logger.debug("Failed to get network info: %s", e2)

    return interfaces


def list_processes(sort_by: str = "cpu", limit: int = 20) -> list[ProcessInfo]:
    """List running processes."""
    processes = []

    try:
        # Use ps for process listing
        result = subprocess.run(
            ["ps", "aux", "--sort=-" + ("%cpu" if sort_by == "cpu" else "%mem")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()[1:limit+1]  # Skip header
            for line in lines:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append(ProcessInfo(
                        pid=int(parts[1]),
                        user=parts[0],
                        cpu_percent=float(parts[2]),
                        mem_percent=float(parts[3]),
                        status=parts[7] if len(parts) > 7 else "?",
                        command=parts[10] if len(parts) > 10 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to list processes: %s", e)

    return processes


def list_services(filter_active: bool = False) -> list[ServiceInfo]:
    """List systemd services."""
    services = []

    try:
        cmd = ["systemctl", "list-units", "--type=service", "--no-pager", "--no-legend"]
        if filter_active:
            cmd.append("--state=active")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 4:
                    name = parts[0].replace(".service", "")
                    services.append(ServiceInfo(
                        name=name,
                        load_state=parts[1],
                        active_state=parts[2],
                        sub_state=parts[3],
                        description=parts[4] if len(parts) > 4 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to list services: %s", e)

    return services


def get_service_status(service_name: str) -> ServiceStatus:
    """Get detailed status of a systemd service."""
    result: ServiceStatus = {
        "name": service_name,
        "exists": False,
        "active": False,
        "enabled": False,
        "status_output": "",
    }

    try:
        # Check if service exists and get status
        status_result = subprocess.run(
            ["systemctl", "status", service_name, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        result["exists"] = status_result.returncode in (0, 3)  # 3 = inactive but exists
        result["status_output"] = status_result.stdout[:2000]

        # Check if active
        is_active = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["active"] = is_active.returncode == 0

        # Check if enabled
        is_enabled = subprocess.run(
            ["systemctl", "is-enabled", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["enabled"] = is_enabled.returncode == 0
    except Exception as e:
        result["error"] = str(e)

    return result


def manage_service(service_name: str, action: str) -> CommandResult:
    """Manage a systemd service (start, stop, restart, enable, disable)."""
    valid_actions = {"start", "stop", "restart", "reload", "enable", "disable"}
    if action not in valid_actions:
        return CommandResult(
            command=f"systemctl {action} {service_name}",
            returncode=-1,
            stdout="",
            stderr=f"Invalid action: {action}. Valid: {', '.join(valid_actions)}",
            success=False,
        )

    return execute_command(f"systemctl {action} {service_name}", timeout=30)


def search_packages(query: str, limit: int = 20) -> list[dict[str, str]]:
    """Search for packages using the system's package manager."""
    packages: list[dict[str, str]] = []
    pm = detect_package_manager()

    if not pm:
        return packages

    try:
        if pm == "apt":
            result = subprocess.run(
                ["apt-cache", "search", query],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines()[:limit]:
                    parts = line.split(" - ", 1)
                    if len(parts) == 2:
                        packages.append({"name": parts[0], "description": parts[1]})

        elif pm == "dnf" or pm == "yum":
            result = subprocess.run(
                [pm, "search", query, "-q"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines()[:limit]:
                    parts = line.split(" : ", 1)
                    if len(parts) == 2:
                        packages.append({"name": parts[0].split(".")[0], "description": parts[1]})

        elif pm == "pacman":
            result = subprocess.run(
                ["pacman", "-Ss", query],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                lines = result.stdout.splitlines()
                for i in range(0, len(lines), 2):
                    if i + 1 < len(lines):
                        name = lines[i].split()[0] if lines[i] else ""
                        desc = lines[i + 1].strip() if lines[i + 1] else ""
                        if name:
                            packages.append({"name": name, "description": desc})
                    if len(packages) >= limit:
                        break
    except Exception as e:
        logger.debug("Failed to search packages: %s", e)

    return packages


def install_package(package_name: str, confirm: bool = False) -> CommandResult:
    """Install a package using the system's package manager.

    Note: This typically requires sudo privileges.
    """
    pm = detect_package_manager()

    if not pm:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported package manager detected",
            success=False,
        )

    # Sanitize package name to prevent shell injection
    safe_package = shlex.quote(package_name)

    # Build the install command
    if pm == "apt":
        cmd = f"sudo apt install -y {safe_package}"
    elif pm == "dnf":
        cmd = f"sudo dnf install -y {safe_package}"
    elif pm == "yum":
        cmd = f"sudo yum install -y {safe_package}"
    elif pm == "pacman":
        cmd = f"sudo pacman -S --noconfirm {safe_package}"
    elif pm == "zypper":
        cmd = f"sudo zypper install -y {safe_package}"
    elif pm == "apk":
        cmd = f"sudo apk add {safe_package}"
    else:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr=f"Unsupported package manager: {pm}",
            success=False,
        )

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    # Check sudo availability before attempting privileged operation
    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=300)


def remove_package(package_name: str, confirm: bool = False, purge: bool = False) -> CommandResult:
    """Remove a package using the system's package manager.

    Args:
        package_name: Name of the package to remove
        confirm: If False, returns what would be done without executing
        purge: If True, also remove configuration files (apt/dpkg only)

    Note: This typically requires sudo privileges.
    """
    pm = detect_package_manager()

    if not pm:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported package manager detected",
            success=False,
        )

    # Sanitize package name to prevent shell injection
    safe_package = shlex.quote(package_name)

    # Build the remove command
    if pm == "apt":
        action = "purge" if purge else "remove"
        cmd = f"sudo apt {action} -y {safe_package}"
    elif pm == "dnf":
        cmd = f"sudo dnf remove -y {safe_package}"
    elif pm == "yum":
        cmd = f"sudo yum remove -y {safe_package}"
    elif pm == "pacman":
        # -Rs removes package and unneeded dependencies
        cmd = f"sudo pacman -Rs --noconfirm {safe_package}"
    elif pm == "zypper":
        cmd = f"sudo zypper remove -y {safe_package}"
    elif pm == "apk":
        cmd = f"sudo apk del {safe_package}"
    else:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr=f"Unsupported package manager: {pm}",
            success=False,
        )

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.\n\nWarning: This will remove the package and may affect system functionality.",
            stderr="",
            success=True,
        )

    # Check sudo availability before attempting privileged operation
    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=300)


def list_installed_packages(search: str | None = None) -> list[str]:
    """List installed packages, optionally filtered by search term."""
    packages: list[str] = []
    pm = detect_package_manager()

    if not pm:
        return packages

    try:
        if pm == "apt":
            result = subprocess.run(
                ["dpkg", "--get-selections"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts and parts[-1] == "install":
                        pkg = parts[0]
                        if not search or search.lower() in pkg.lower():
                            packages.append(pkg)

        elif pm in ("dnf", "yum"):
            result = subprocess.run(
                [pm, "list", "installed", "-q"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts:
                        pkg = parts[0].split(".")[0]
                        if not search or search.lower() in pkg.lower():
                            packages.append(pkg)

        elif pm == "pacman":
            result = subprocess.run(
                ["pacman", "-Q"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts:
                        pkg = parts[0]
                        if not search or search.lower() in pkg.lower():
                            packages.append(pkg)
    except Exception as e:
        logger.debug("Failed to list installed packages: %s", e)

    return packages[:500]  # Limit output


def get_disk_usage(path: str = "/") -> DiskUsageInfo:
    """Get disk usage for a path."""
    result: DiskUsageInfo = {"path": path, "total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent": 0.0}

    try:
        stat = os.statvfs(path)
        result["total_gb"] = round((stat.f_blocks * stat.f_frsize) / (1024**3), 2)
        result["used_gb"] = round(((stat.f_blocks - stat.f_bfree) * stat.f_frsize) / (1024**3), 2)
        result["free_gb"] = round((stat.f_bavail * stat.f_frsize) / (1024**3), 2)
        if result["total_gb"] > 0:
            result["percent"] = round((result["used_gb"] / result["total_gb"]) * 100, 1)
    except Exception as e:
        result["error"] = str(e)

    return result


def list_directory(
    path: str,
    *,
    show_hidden: bool = False,
    details: bool = False,
) -> list[DirectoryEntry]:
    """List directory contents."""
    entries: list[DirectoryEntry] = []
    dir_path = Path(path).expanduser().resolve()

    if not dir_path.exists():
        return [{"error": f"Path does not exist: {path}"}]

    if not dir_path.is_dir():
        return [{"error": f"Not a directory: {path}"}]

    try:
        for entry in sorted(dir_path.iterdir()):
            if not show_hidden and entry.name.startswith("."):
                continue

            entry_info: DirectoryEntry = {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            }

            if details:
                try:
                    stat = entry.stat()
                    entry_info["size"] = stat.st_size
                    entry_info["mode"] = oct(stat.st_mode)[-3:]
                    entry_info["modified"] = stat.st_mtime
                except OSError:
                    # Expected for broken symlinks, inaccessible files
                    pass

            entries.append(entry_info)
    except PermissionError:
        return [{"error": f"Permission denied: {path}"}]
    except Exception as e:
        return [{"error": str(e)}]

    return entries[:200]  # Limit output


def find_files(
    path: str,
    *,
    name: str | None = None,
    extension: str | None = None,
    max_depth: int = 3,
    limit: int = 50,
) -> list[str]:
    """Find files matching criteria."""
    results = []
    start_path = Path(path).expanduser().resolve()

    if not start_path.exists():
        return []

    try:
        for root, dirs, files in os.walk(start_path):
            # Limit depth
            depth = str(root).count(os.sep) - str(start_path).count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue

            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in files:
                if filename.startswith("."):
                    continue

                matches = True
                if name and name.lower() not in filename.lower():
                    matches = False
                if extension and not filename.endswith(extension):
                    matches = False

                if matches:
                    results.append(os.path.join(root, filename))
                    if len(results) >= limit:
                        return results
    except Exception as e:
        logger.debug("Error while searching files in %s: %s", path, e)

    return results


def read_log_file(
    path: str,
    *,
    lines: int = 100,
    filter_pattern: str | None = None,
) -> LogFileResult:
    """Read and optionally filter a log file."""
    result: LogFileResult = {"path": path, "lines": [], "total_lines": 0}
    log_path = Path(path).expanduser().resolve()

    if not log_path.exists():
        result["error"] = f"File not found: {path}"
        return result

    if not log_path.is_file():
        result["error"] = f"Not a file: {path}"
        return result

    try:
        with open(log_path) as f:
            all_lines = f.readlines()

        result["total_lines"] = len(all_lines)

        # Get last N lines
        recent_lines = all_lines[-lines:]

        # Apply filter if specified
        if filter_pattern:
            pattern = re.compile(filter_pattern, re.IGNORECASE)
            recent_lines = [line for line in recent_lines if pattern.search(line)]

        result["lines"] = [line.rstrip() for line in recent_lines]
    except PermissionError:
        result["error"] = f"Permission denied: {path}"
    except Exception as e:
        result["error"] = str(e)

    return result


def check_docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug("Docker not available: %s", e)
        return False


def list_docker_containers(all_containers: bool = False) -> list[dict[str, str]]:
    """List Docker containers."""
    containers: list[dict[str, str]] = []

    if not check_docker_available():
        return containers

    try:
        cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]
        if all_containers:
            cmd.insert(2, "-a")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "id": parts[0],
                        "image": parts[1],
                        "status": parts[2],
                        "name": parts[3],
                    })
    except Exception as e:
        logger.debug("Failed to list Docker containers: %s", e)

    return containers


def list_docker_images() -> list[dict[str, str]]:
    """List Docker images."""
    images: list[dict[str, str]] = []

    if not check_docker_available():
        return images

    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    images.append({
                        "repository": parts[0],
                        "tag": parts[1],
                        "size": parts[2],
                        "id": parts[3],
                    })
    except Exception as e:
        logger.debug("Failed to list Docker images: %s", e)

    return images


def get_environment_info() -> dict[str, Any]:
    """Get environment information useful for troubleshooting."""
    info: dict[str, Any] = {
        "shell": os.environ.get("SHELL", "unknown"),
        "user": os.environ.get("USER", "unknown"),
        "home": os.environ.get("HOME", "unknown"),
        "path": os.environ.get("PATH", "").split(":"),
        "display": os.environ.get("DISPLAY"),
        "wayland": os.environ.get("WAYLAND_DISPLAY"),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "lang": os.environ.get("LANG"),
        "term": os.environ.get("TERM"),
    }

    # Check for common tools
    tools = ["git", "python", "python3", "node", "npm", "cargo", "go", "java", "docker", "kubectl"]
    info["available_tools"] = {}
    for tool in tools:
        path = shutil.which(tool)
        if path:
            info["available_tools"][tool] = path

    return info


# =============================================================================
# Firewall Management
# =============================================================================

@dataclass(frozen=True)
class FirewallStatus:
    """Status of the system firewall."""
    enabled: bool
    backend: str  # "ufw", "firewalld", or "none"
    default_policy: str
    rules: list[dict[str, str]]


def detect_firewall() -> str | None:
    """Detect which firewall is available on the system.

    Returns:
        "ufw" for Ubuntu/Debian, "firewalld" for RHEL/Fedora, or None
    """
    # Check for ufw (Ubuntu, Debian)
    if os.path.exists("/usr/sbin/ufw"):
        return "ufw"
    # Check for firewall-cmd (RHEL, Fedora, CentOS)
    if os.path.exists("/usr/bin/firewall-cmd"):
        return "firewalld"
    return None


def get_firewall_status() -> FirewallStatus:
    """Get the current firewall status and rules."""
    backend = detect_firewall()

    if backend == "ufw":
        return _get_ufw_status()
    elif backend == "firewalld":
        return _get_firewalld_status()
    else:
        return FirewallStatus(
            enabled=False,
            backend="none",
            default_policy="unknown",
            rules=[],
        )


def _get_ufw_status() -> FirewallStatus:
    """Get UFW firewall status."""
    enabled = False
    default_policy = "unknown"
    rules: list[dict[str, str]] = []

    try:
        result = subprocess.run(
            ["sudo", "-n", "ufw", "status", "verbose"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = result.stdout
            if "Status: active" in output:
                enabled = True

            # Parse default policy
            for line in output.splitlines():
                if line.startswith("Default:"):
                    default_policy = line.split(":", 1)[1].strip()
                    break

            # Parse rules (after "---" line)
            in_rules = False
            for line in output.splitlines():
                if "---" in line:
                    in_rules = True
                    continue
                if in_rules and line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        rules.append({
                            "to": parts[0],
                            "action": parts[1] if len(parts) > 1 else "",
                            "from": parts[2] if len(parts) > 2 else "Anywhere",
                            "raw": line.strip(),
                        })
    except Exception as e:
        logger.debug("Failed to get UFW status: %s", e)

    return FirewallStatus(
        enabled=enabled,
        backend="ufw",
        default_policy=default_policy,
        rules=rules,
    )


def _get_firewalld_status() -> FirewallStatus:
    """Get firewalld status."""
    enabled = False
    default_policy = "unknown"
    rules: list[dict[str, str]] = []

    try:
        # Check if running
        result = subprocess.run(
            ["firewall-cmd", "--state"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        enabled = result.returncode == 0 and "running" in result.stdout

        # Get default zone
        result = subprocess.run(
            ["firewall-cmd", "--get-default-zone"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            default_policy = result.stdout.strip()

        # Get active services in default zone
        result = subprocess.run(
            ["firewall-cmd", "--list-all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("services:"):
                    services = line.split(":", 1)[1].strip().split()
                    for svc in services:
                        rules.append({
                            "type": "service",
                            "name": svc,
                            "action": "allow",
                        })
                elif line.startswith("ports:"):
                    ports = line.split(":", 1)[1].strip().split()
                    for port in ports:
                        rules.append({
                            "type": "port",
                            "name": port,
                            "action": "allow",
                        })
    except Exception as e:
        logger.debug("Failed to get firewalld status: %s", e)

    return FirewallStatus(
        enabled=enabled,
        backend="firewalld",
        default_policy=default_policy,
        rules=rules,
    )


def firewall_allow(
    port: int | str,
    protocol: str = "tcp",
    confirm: bool = False,
) -> CommandResult:
    """Allow a port through the firewall.

    Args:
        port: Port number or service name (e.g., 80, "ssh", "http")
        protocol: "tcp" or "udp"
        confirm: If False, returns what would be done without executing
    """
    backend = detect_firewall()

    if not backend:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported firewall detected (ufw or firewalld)",
            success=False,
        )

    # Sanitize inputs
    safe_port = shlex.quote(str(port))
    safe_protocol = shlex.quote(protocol.lower())

    if backend == "ufw":
        if str(port).isdigit():
            cmd = f"sudo ufw allow {safe_port}/{safe_protocol}"
        else:
            cmd = f"sudo ufw allow {safe_port}"
    else:  # firewalld
        if str(port).isdigit():
            cmd = f"sudo firewall-cmd --add-port={safe_port}/{safe_protocol} --permanent"
        else:
            cmd = f"sudo firewall-cmd --add-service={safe_port} --permanent"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    result = execute_command(cmd, timeout=30)

    # Reload firewalld if successful
    if result.success and backend == "firewalld":
        execute_command("sudo firewall-cmd --reload", timeout=10)

    return result


def firewall_deny(
    port: int | str,
    protocol: str = "tcp",
    confirm: bool = False,
) -> CommandResult:
    """Block a port through the firewall.

    Args:
        port: Port number or service name
        protocol: "tcp" or "udp"
        confirm: If False, returns what would be done without executing
    """
    backend = detect_firewall()

    if not backend:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported firewall detected (ufw or firewalld)",
            success=False,
        )

    safe_port = shlex.quote(str(port))
    safe_protocol = shlex.quote(protocol.lower())

    if backend == "ufw":
        if str(port).isdigit():
            cmd = f"sudo ufw deny {safe_port}/{safe_protocol}"
        else:
            cmd = f"sudo ufw deny {safe_port}"
    else:  # firewalld
        if str(port).isdigit():
            cmd = f"sudo firewall-cmd --remove-port={safe_port}/{safe_protocol} --permanent"
        else:
            cmd = f"sudo firewall-cmd --remove-service={safe_port} --permanent"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    result = execute_command(cmd, timeout=30)

    if result.success and backend == "firewalld":
        execute_command("sudo firewall-cmd --reload", timeout=10)

    return result


def firewall_enable(confirm: bool = False) -> CommandResult:
    """Enable the firewall."""
    backend = detect_firewall()

    if not backend:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported firewall detected",
            success=False,
        )

    if backend == "ufw":
        cmd = "sudo ufw --force enable"
    else:
        cmd = "sudo systemctl enable --now firewalld"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.\n\nWarning: Enabling firewall may block network access if not configured properly.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


def firewall_disable(confirm: bool = False) -> CommandResult:
    """Disable the firewall."""
    backend = detect_firewall()

    if not backend:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No supported firewall detected",
            success=False,
        )

    if backend == "ufw":
        cmd = "sudo ufw disable"
    else:
        cmd = "sudo systemctl disable --now firewalld"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.\n\nWarning: Disabling firewall will expose all network services.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


# =============================================================================
# Journalctl / Systemd Logging
# =============================================================================

@dataclass(frozen=True)
class JournalEntry:
    """A single journal log entry."""
    timestamp: str
    unit: str
    priority: str
    message: str


def get_service_logs(
    service_name: str,
    *,
    lines: int = 50,
    since: str | None = None,
    priority: str | None = None,
) -> list[JournalEntry]:
    """Get logs for a systemd service using journalctl.

    Args:
        service_name: Name of the service (with or without .service suffix)
        lines: Number of lines to retrieve
        since: Time specification (e.g., "1 hour ago", "today", "2024-01-01")
        priority: Filter by priority (emerg, alert, crit, err, warning, notice, info, debug)

    Returns:
        List of JournalEntry objects
    """
    entries: list[JournalEntry] = []

    # Normalize service name
    if not service_name.endswith(".service"):
        service_name = f"{service_name}.service"

    cmd = ["journalctl", "-u", service_name, "-n", str(lines), "--no-pager", "-o", "short-iso"]

    if since:
        cmd.extend(["--since", since])

    if priority:
        cmd.extend(["-p", priority])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Parse short-iso format: 2024-01-15T10:30:45+0000 hostname unit[pid]: message
                if not line.strip():
                    continue
                parts = line.split(" ", 3)
                if len(parts) >= 4:
                    entries.append(JournalEntry(
                        timestamp=parts[0],
                        unit=parts[2].rstrip(":"),
                        priority="info",  # Priority not in short format
                        message=parts[3] if len(parts) > 3 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to get service logs: %s", e)

    return entries


def get_system_logs(
    *,
    lines: int = 100,
    since: str | None = None,
    priority: str | None = None,
    grep: str | None = None,
) -> list[JournalEntry]:
    """Get system-wide logs using journalctl.

    Args:
        lines: Number of lines to retrieve
        since: Time specification (e.g., "1 hour ago", "today")
        priority: Filter by priority level
        grep: Filter messages containing this pattern

    Returns:
        List of JournalEntry objects
    """
    entries: list[JournalEntry] = []

    cmd = ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"]

    if since:
        cmd.extend(["--since", since])

    if priority:
        cmd.extend(["-p", priority])

    if grep:
        cmd.extend(["-g", grep])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    entries.append(JournalEntry(
                        timestamp=parts[0],
                        unit=parts[2].rstrip(":") if len(parts) > 2 else "",
                        priority=priority or "info",
                        message=parts[3] if len(parts) > 3 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to get system logs: %s", e)

    return entries


def get_boot_logs(*, current_boot: bool = True, lines: int = 100) -> list[JournalEntry]:
    """Get boot logs.

    Args:
        current_boot: If True, show only current boot; otherwise show previous boot
        lines: Number of lines to retrieve
    """
    entries: list[JournalEntry] = []

    boot_flag = "-b" if current_boot else "-b -1"
    cmd = f"journalctl {boot_flag} -n {lines} --no-pager -o short-iso"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    entries.append(JournalEntry(
                        timestamp=parts[0],
                        unit=parts[2].rstrip(":") if len(parts) > 2 else "",
                        priority="info",
                        message=parts[3] if len(parts) > 3 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to get boot logs: %s", e)

    return entries


def get_failed_services() -> list[ServiceInfo]:
    """Get list of failed systemd services."""
    services: list[ServiceInfo] = []

    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=failed", "--no-pager", "--plain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts and parts[0].endswith(".service"):
                    services.append(ServiceInfo(
                        name=parts[0],
                        load_state=parts[1] if len(parts) > 1 else "unknown",
                        active_state=parts[2] if len(parts) > 2 else "failed",
                        sub_state=parts[3] if len(parts) > 3 else "failed",
                        description=" ".join(parts[4:]) if len(parts) > 4 else "",
                    ))
    except Exception as e:
        logger.debug("Failed to get failed services: %s", e)

    return services


# =============================================================================
# Container Management (Docker + Podman)
# =============================================================================

def detect_container_runtime() -> str | None:
    """Detect available container runtime.

    Returns:
        "docker", "podman", or None
    """
    # Check for podman first (preferred on newer Fedora/RHEL)
    if shutil.which("podman"):
        try:
            result = subprocess.run(
                ["podman", "info"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "podman"
        except Exception as e:
            logger.debug("Podman info check failed: %s", e)

    # Check for docker
    if shutil.which("docker"):
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "docker"
        except Exception as e:
            logger.debug("Docker info check failed: %s", e)

    return None


def list_containers(all_containers: bool = False) -> list[dict[str, str]]:
    """List containers using Docker or Podman.

    Args:
        all_containers: If True, include stopped containers
    """
    containers: list[dict[str, str]] = []
    runtime = detect_container_runtime()

    if not runtime:
        return containers

    try:
        cmd = [runtime, "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]
        if all_containers:
            cmd.insert(2, "-a")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "id": parts[0],
                        "image": parts[1],
                        "status": parts[2],
                        "name": parts[3],
                        "runtime": runtime,
                    })
    except Exception as e:
        logger.debug("Failed to list containers: %s", e)

    return containers


def list_container_images() -> list[dict[str, str]]:
    """List container images using Docker or Podman."""
    images: list[dict[str, str]] = []
    runtime = detect_container_runtime()

    if not runtime:
        return images

    try:
        result = subprocess.run(
            [runtime, "images", "--format", "{{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    images.append({
                        "repository": parts[0],
                        "tag": parts[1],
                        "size": parts[2],
                        "id": parts[3],
                        "runtime": runtime,
                    })
    except Exception as e:
        logger.debug("Failed to list container images: %s", e)

    return images


def get_container_logs(
    container_id: str,
    *,
    lines: int = 100,
    follow: bool = False,
) -> CommandResult:
    """Get logs from a container.

    Args:
        container_id: Container ID or name
        lines: Number of lines to retrieve
        follow: If True, return command to follow logs (not executed)
    """
    runtime = detect_container_runtime()

    if not runtime:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No container runtime detected (docker or podman)",
            success=False,
        )

    safe_id = shlex.quote(container_id)

    if follow:
        cmd = f"{runtime} logs -f --tail {lines} {safe_id}"
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"To follow logs, run: {cmd}",
            stderr="",
            success=True,
        )

    cmd = f"{runtime} logs --tail {lines} {safe_id}"
    return execute_command(cmd, timeout=30)


def container_exec(
    container_id: str,
    command: str,
    *,
    confirm: bool = False,
) -> CommandResult:
    """Execute a command in a running container.

    Args:
        container_id: Container ID or name
        command: Command to execute
        confirm: If False, returns what would be done without executing
    """
    runtime = detect_container_runtime()

    if not runtime:
        return CommandResult(
            command="",
            returncode=-1,
            stdout="",
            stderr="No container runtime detected",
            success=False,
        )

    safe_id = shlex.quote(container_id)
    safe_command = shlex.quote(command)
    cmd = f"{runtime} exec {safe_id} {safe_command}"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    return execute_command(cmd, timeout=60)


# =============================================================================
# User and Group Management
# =============================================================================

@dataclass(frozen=True)
class UserInfo:
    """Information about a system user."""
    username: str
    uid: int
    gid: int
    home: str
    shell: str
    groups: list[str]


def list_users(system_users: bool = False) -> list[UserInfo]:
    """List system users.

    Args:
        system_users: If True, include system users (UID < 1000)
    """
    users: list[UserInfo] = []

    try:
        with open("/etc/passwd") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) >= 7:
                    uid = int(parts[2])
                    # Skip system users unless requested
                    if not system_users and uid < 1000 and uid != 0:
                        continue

                    username = parts[0]
                    groups = _get_user_groups(username)

                    users.append(UserInfo(
                        username=username,
                        uid=uid,
                        gid=int(parts[3]),
                        home=parts[5],
                        shell=parts[6],
                        groups=groups,
                    ))
    except Exception as e:
        logger.debug("Failed to list users: %s", e)

    return users


def _get_user_groups(username: str) -> list[str]:
    """Get groups for a user."""
    groups: list[str] = []
    try:
        result = subprocess.run(
            ["groups", username],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Output format: "username : group1 group2 group3"
            parts = result.stdout.split(":")
            if len(parts) >= 2:
                groups = parts[1].strip().split()
    except Exception as e:
        logger.debug("Failed to get user groups: %s", e)
    return groups


def list_groups() -> list[dict[str, Any]]:
    """List system groups."""
    groups: list[dict[str, Any]] = []

    try:
        with open("/etc/group") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) >= 4:
                    gid = int(parts[2])
                    # Skip most system groups
                    if gid < 1000 and gid != 0 and parts[0] not in ("sudo", "wheel", "docker", "admin"):
                        continue

                    groups.append({
                        "name": parts[0],
                        "gid": gid,
                        "members": parts[3].split(",") if parts[3] else [],
                    })
    except Exception as e:
        logger.debug("Failed to list groups: %s", e)

    return groups


def add_user(
    username: str,
    *,
    home_dir: str | None = None,
    shell: str | None = None,
    groups: list[str] | None = None,
    create_home: bool = True,
    confirm: bool = False,
) -> CommandResult:
    """Add a new user.

    Args:
        username: Username to create
        home_dir: Home directory path (default: /home/username)
        shell: Login shell (default: /bin/bash)
        groups: Additional groups to add user to
        create_home: Whether to create home directory
        confirm: If False, returns what would be done without executing
    """
    safe_username = shlex.quote(username)

    cmd_parts = ["sudo", "useradd"]

    if create_home:
        cmd_parts.append("-m")

    if home_dir:
        cmd_parts.extend(["-d", shlex.quote(home_dir)])

    if shell:
        cmd_parts.extend(["-s", shlex.quote(shell)])
    else:
        cmd_parts.extend(["-s", "/bin/bash"])

    if groups:
        safe_groups = ",".join(shlex.quote(g) for g in groups)
        cmd_parts.extend(["-G", safe_groups])

    cmd_parts.append(safe_username)
    cmd = " ".join(cmd_parts)

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


def delete_user(
    username: str,
    *,
    remove_home: bool = False,
    confirm: bool = False,
) -> CommandResult:
    """Delete a user.

    Args:
        username: Username to delete
        remove_home: If True, also remove home directory
        confirm: If False, returns what would be done without executing
    """
    safe_username = shlex.quote(username)

    if remove_home:
        cmd = f"sudo userdel -r {safe_username}"
    else:
        cmd = f"sudo userdel {safe_username}"

    if not confirm:
        warning = ""
        if remove_home:
            warning = "\n\nWarning: This will permanently delete the user's home directory!"
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.{warning}",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


def add_user_to_group(
    username: str,
    group: str,
    *,
    confirm: bool = False,
) -> CommandResult:
    """Add a user to a group.

    Args:
        username: Username
        group: Group to add user to
        confirm: If False, returns what would be done without executing
    """
    safe_username = shlex.quote(username)
    safe_group = shlex.quote(group)
    cmd = f"sudo usermod -aG {safe_group} {safe_username}"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.\n\nNote: User may need to log out and back in for group changes to take effect.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


def remove_user_from_group(
    username: str,
    group: str,
    *,
    confirm: bool = False,
) -> CommandResult:
    """Remove a user from a group.

    Args:
        username: Username
        group: Group to remove user from
        confirm: If False, returns what would be done without executing
    """
    safe_username = shlex.quote(username)
    safe_group = shlex.quote(group)
    cmd = f"sudo gpasswd -d {safe_username} {safe_group}"

    if not confirm:
        return CommandResult(
            command=cmd,
            returncode=0,
            stdout=f"Would run: {cmd}\nSet confirm=true to execute.",
            stderr="",
            success=True,
        )

    can_sudo, sudo_error = check_sudo_available()
    if not can_sudo:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=sudo_error or "Cannot run sudo",
            success=False,
        )

    return execute_command(cmd, timeout=30)


# =============================================================================
# Network Monitoring Functions
# =============================================================================


@dataclass
class ListeningPort:
    """Information about a listening port."""
    protocol: str  # tcp, udp
    port: int
    address: str  # 0.0.0.0, 127.0.0.1, ::, etc.
    process: str  # Process name or PID
    pid: int | None


def list_listening_ports() -> list[ListeningPort]:
    """List all listening network ports on the system."""
    ports = []

    try:
        # Try ss first (modern), fall back to netstat
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 5:
                    # Parse Local Address:Port
                    local = parts[3]
                    if ":" in local:
                        addr, port_str = local.rsplit(":", 1)
                        try:
                            port = int(port_str)
                        except ValueError:
                            continue

                        # Parse process info from last column
                        process = ""
                        pid = None
                        if len(parts) >= 6:
                            proc_info = parts[5]
                            # Format: users:(("nginx",pid=1234,fd=6))
                            if 'pid=' in proc_info:
                                try:
                                    pid_str = proc_info.split('pid=')[1].split(',')[0].split(')')[0]
                                    pid = int(pid_str)
                                except (IndexError, ValueError):
                                    pass
                            if '(("' in proc_info:
                                try:
                                    process = proc_info.split('(("')[1].split('"')[0]
                                except IndexError:
                                    pass

                        ports.append(ListeningPort(
                            protocol="tcp",
                            port=port,
                            address=addr.strip("[]"),
                            process=process,
                            pid=pid,
                        ))
    except FileNotFoundError:
        # Fall back to netstat
        try:
            result = subprocess.run(
                ["netstat", "-tlnp"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines()[2:]:  # Skip headers
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] in ("tcp", "tcp6"):
                        local = parts[3]
                        if ":" in local:
                            addr, port_str = local.rsplit(":", 1)
                            try:
                                port = int(port_str)
                            except ValueError:
                                continue

                            process = ""
                            pid = None
                            if len(parts) >= 7 and parts[6] != "-":
                                proc_info = parts[6]
                                if "/" in proc_info:
                                    pid_str, process = proc_info.split("/", 1)
                                    try:
                                        pid = int(pid_str)
                                    except ValueError:
                                        pass

                            ports.append(ListeningPort(
                                protocol="tcp",
                                port=port,
                                address=addr,
                                process=process,
                                pid=pid,
                            ))
        except Exception as e:
            logger.debug("Failed to list ports with netstat: %s", e)
    except Exception as e:
        logger.debug("Failed to list ports with ss: %s", e)

    # Sort by port number
    return sorted(ports, key=lambda p: p.port)


@dataclass
class NetworkTraffic:
    """Network traffic statistics for an interface."""
    interface: str
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int


def get_network_traffic() -> list[NetworkTraffic]:
    """Get network traffic statistics for all interfaces."""
    traffic = []

    try:
        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()[2:]  # Skip headers

        for line in lines:
            parts = line.split()
            if len(parts) >= 10:
                interface = parts[0].rstrip(":")
                # Skip loopback
                if interface == "lo":
                    continue

                traffic.append(NetworkTraffic(
                    interface=interface,
                    rx_bytes=int(parts[1]),
                    rx_packets=int(parts[2]),
                    rx_errors=int(parts[3]),
                    tx_bytes=int(parts[9]),
                    tx_packets=int(parts[10]),
                    tx_errors=int(parts[11]),
                ))
    except Exception as e:
        logger.debug("Failed to read network traffic: %s", e)

    return traffic


def format_bytes(bytes_val: int | float) -> str:
    """Format bytes into human-readable string."""
    val: float = float(bytes_val)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"
