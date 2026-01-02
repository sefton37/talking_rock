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
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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

    Returns (is_safe, warning_message).
    """
    cmd_stripped = command.strip()

    # Check for obviously dangerous commands using regex patterns
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd_stripped, re.IGNORECASE):
            return False, f"Blocked dangerous command matching pattern: {pattern}"

    # Check for risky patterns that need confirmation
    for pattern in RISKY_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, "This command matches a risky pattern and could cause data loss"

    return True, None


def execute_command(
    command: str,
    *,
    timeout: int = 30,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Execute a shell command safely.

    Args:
        command: The command to execute
        timeout: Maximum execution time in seconds
        cwd: Working directory
        env: Environment variables to add

    Returns:
        CommandResult with output and status
    """
    is_safe, warning = is_command_safe(command)
    if not is_safe:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout="",
            stderr=warning or "Command blocked for safety",
            success=False,
        )

    # Prepare environment
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
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

    if not is_safe:
        return CommandPreview(
            command=command,
            is_destructive=True,
            description="BLOCKED: Dangerous command",
            affected_paths=[],
            warnings=warnings,
            can_undo=False,
            undo_command=None,
        )

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


def get_service_status(service_name: str) -> dict[str, Any]:
    """Get detailed status of a systemd service."""
    result = {
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
    packages = []
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

    # Build the install command
    if pm == "apt":
        cmd = f"sudo apt install -y {package_name}"
    elif pm == "dnf":
        cmd = f"sudo dnf install -y {package_name}"
    elif pm == "yum":
        cmd = f"sudo yum install -y {package_name}"
    elif pm == "pacman":
        cmd = f"sudo pacman -S --noconfirm {package_name}"
    elif pm == "zypper":
        cmd = f"sudo zypper install -y {package_name}"
    elif pm == "apk":
        cmd = f"sudo apk add {package_name}"
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

    return execute_command(cmd, timeout=300)


def list_installed_packages(search: str | None = None) -> list[str]:
    """List installed packages, optionally filtered by search term."""
    packages = []
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


def get_disk_usage(path: str = "/") -> dict[str, Any]:
    """Get disk usage for a path."""
    result = {"path": path, "total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

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
) -> list[dict[str, Any]]:
    """List directory contents."""
    entries = []
    dir_path = Path(path).expanduser().resolve()

    if not dir_path.exists():
        return [{"error": f"Path does not exist: {path}"}]

    if not dir_path.is_dir():
        return [{"error": f"Not a directory: {path}"}]

    try:
        for entry in sorted(dir_path.iterdir()):
            if not show_hidden and entry.name.startswith("."):
                continue

            info: dict[str, Any] = {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            }

            if details:
                try:
                    stat = entry.stat()
                    info["size"] = stat.st_size
                    info["mode"] = oct(stat.st_mode)[-3:]
                    info["modified"] = stat.st_mtime
                except OSError:
                    # Expected for broken symlinks, inaccessible files
                    pass

            entries.append(info)
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
        logger.debug("Error while searching files in %s: %s", directory, e)

    return results


def read_log_file(
    path: str,
    *,
    lines: int = 100,
    filter_pattern: str | None = None,
) -> dict[str, Any]:
    """Read and optionally filter a log file."""
    result: dict[str, Any] = {"path": path, "lines": [], "total_lines": 0}
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
    containers = []

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
    images = []

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
