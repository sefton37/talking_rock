"""Tests for Linux system tools."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from reos import linux_tools


class TestCommandSafety:
    """Test command safety checks."""

    def test_safe_command_allowed(self) -> None:
        """Safe commands should be allowed."""
        is_safe, warning = linux_tools.is_command_safe("ls -la")
        assert is_safe is True
        assert warning is None

    def test_safe_command_echo(self) -> None:
        """Echo command should be allowed."""
        is_safe, warning = linux_tools.is_command_safe("echo hello")
        assert is_safe is True
        assert warning is None

    def test_dangerous_rm_rf_root_blocked(self) -> None:
        """rm -rf / should be blocked."""
        is_safe, warning = linux_tools.is_command_safe("rm -rf /")
        assert is_safe is False
        assert warning is not None
        assert "blocked" in warning.lower()

    def test_dangerous_rm_rf_wildcard_blocked(self) -> None:
        """rm -rf /* should be blocked."""
        is_safe, warning = linux_tools.is_command_safe("rm -rf /*")
        assert is_safe is False
        assert warning is not None

    def test_fork_bomb_blocked(self) -> None:
        """Fork bomb should be blocked."""
        is_safe, warning = linux_tools.is_command_safe(":(){:|:&};:")
        assert is_safe is False
        assert warning is not None

    def test_dd_risky_warning(self) -> None:
        """dd command should have a warning."""
        is_safe, warning = linux_tools.is_command_safe("dd if=/dev/sda of=backup.img")
        assert is_safe is True  # Allowed but with warning
        assert warning is not None
        assert "risky" in warning.lower()

    def test_shutdown_risky_warning(self) -> None:
        """shutdown command should have a warning."""
        is_safe, warning = linux_tools.is_command_safe("shutdown -h now")
        assert is_safe is True
        assert warning is not None


class TestExecuteCommand:
    """Test command execution."""

    def test_simple_command(self) -> None:
        """Simple command should execute successfully."""
        result = linux_tools.execute_command("echo 'hello world'")
        assert result.success is True
        assert result.returncode == 0
        assert "hello world" in result.stdout

    def test_command_with_error(self) -> None:
        """Command with error should return non-zero."""
        result = linux_tools.execute_command("ls /nonexistent_directory_xyz")
        assert result.success is False
        assert result.returncode != 0

    def test_dangerous_command_blocked(self) -> None:
        """Dangerous command should be blocked."""
        result = linux_tools.execute_command("rm -rf /")
        assert result.success is False
        assert "blocked" in result.stderr.lower() or "dangerous" in result.stderr.lower()

    def test_timeout(self) -> None:
        """Command should timeout."""
        result = linux_tools.execute_command("sleep 10", timeout=1)
        assert result.success is False
        assert "timed out" in result.stderr.lower()

    def test_working_directory(self) -> None:
        """Command should run in specified directory."""
        result = linux_tools.execute_command("pwd", cwd="/tmp")
        assert result.success is True
        assert "/tmp" in result.stdout


class TestSystemInfo:
    """Test system information gathering."""

    def test_get_system_info(self) -> None:
        """Should return system info dataclass."""
        info = linux_tools.get_system_info()
        assert info is not None
        assert isinstance(info.hostname, str)
        assert isinstance(info.cpu_cores, int)
        assert info.cpu_cores >= 0
        assert isinstance(info.memory_total_mb, int)
        assert info.memory_total_mb >= 0

    def test_distro_detection(self) -> None:
        """Should detect Linux distribution."""
        distro = linux_tools.detect_distro()
        assert distro is not None
        assert isinstance(distro, str)
        assert len(distro) > 0


class TestPackageManager:
    """Test package manager detection."""

    def test_detect_package_manager(self) -> None:
        """Should detect package manager or return None."""
        pm = linux_tools.detect_package_manager()
        # pm can be None if no supported package manager is found
        if pm is not None:
            assert pm in ["apt", "dnf", "yum", "pacman", "zypper", "apk", "emerge", "nix-env"]

    @patch("os.path.exists")
    def test_detect_apt(self, mock_exists: MagicMock) -> None:
        """Should detect apt on Debian/Ubuntu."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/apt"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "apt"

    @patch("os.path.exists")
    def test_detect_dnf(self, mock_exists: MagicMock) -> None:
        """Should detect dnf on Fedora."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/dnf"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "dnf"

    @patch("os.path.exists")
    def test_detect_pacman(self, mock_exists: MagicMock) -> None:
        """Should detect pacman on Arch."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/pacman"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "pacman"


class TestNetworkInfo:
    """Test network information gathering."""

    def test_get_network_info(self) -> None:
        """Should return network interfaces."""
        interfaces = linux_tools.get_network_info()
        assert isinstance(interfaces, dict)
        # Should have at least loopback
        if len(interfaces) > 0:
            for name, info in interfaces.items():
                assert isinstance(name, str)
                assert isinstance(info, dict)


class TestProcessManagement:
    """Test process listing."""

    def test_list_processes(self) -> None:
        """Should return list of processes."""
        processes = linux_tools.list_processes(limit=10)
        assert isinstance(processes, list)
        # Should have at least one process (ourselves)
        if len(processes) > 0:
            p = processes[0]
            assert hasattr(p, "pid")
            assert hasattr(p, "command")
            assert isinstance(p.pid, int)

    def test_list_processes_by_memory(self) -> None:
        """Should sort by memory."""
        processes = linux_tools.list_processes(sort_by="mem", limit=5)
        assert isinstance(processes, list)


class TestServiceManagement:
    """Test systemd service management."""

    def test_list_services(self) -> None:
        """Should return list of services."""
        services = linux_tools.list_services()
        assert isinstance(services, list)
        # May be empty if systemd not available
        if len(services) > 0:
            s = services[0]
            assert hasattr(s, "name")
            assert hasattr(s, "active_state")

    def test_get_service_status(self) -> None:
        """Should return service status dict."""
        # Test with a service that likely doesn't exist
        status = linux_tools.get_service_status("nonexistent_service_xyz")
        assert isinstance(status, dict)
        assert "name" in status
        assert status["name"] == "nonexistent_service_xyz"

    def test_manage_service_invalid_action(self) -> None:
        """Should reject invalid action."""
        result = linux_tools.manage_service("test", "invalid_action")
        assert result.success is False
        assert "invalid" in result.stderr.lower()


class TestDiskUsage:
    """Test disk usage information."""

    def test_get_disk_usage_root(self) -> None:
        """Should return disk usage for /."""
        usage = linux_tools.get_disk_usage("/")
        assert isinstance(usage, dict)
        assert "total_gb" in usage
        assert "used_gb" in usage
        assert "free_gb" in usage
        assert usage["total_gb"] > 0

    def test_get_disk_usage_home(self) -> None:
        """Should return disk usage for home."""
        usage = linux_tools.get_disk_usage(os.path.expanduser("~"))
        assert isinstance(usage, dict)
        assert usage["total_gb"] > 0


class TestDirectoryOperations:
    """Test directory listing and file finding."""

    def test_list_directory(self) -> None:
        """Should list directory contents."""
        entries = linux_tools.list_directory("/tmp")
        assert isinstance(entries, list)
        # /tmp should exist and be readable
        if entries and "error" not in entries[0]:
            for entry in entries:
                assert "name" in entry
                assert "type" in entry

    def test_list_directory_with_details(self) -> None:
        """Should include details when requested."""
        entries = linux_tools.list_directory("/tmp", details=True)
        assert isinstance(entries, list)
        if entries and "error" not in entries[0]:
            for entry in entries:
                assert "name" in entry
                # With details, should have size info
                if entry["type"] == "file":
                    assert "size" in entry

    def test_list_directory_nonexistent(self) -> None:
        """Should handle nonexistent directory."""
        entries = linux_tools.list_directory("/nonexistent_dir_xyz")
        assert isinstance(entries, list)
        assert len(entries) == 1
        assert "error" in entries[0]

    def test_find_files(self) -> None:
        """Should find files matching criteria."""
        files = linux_tools.find_files("/tmp", limit=10)
        assert isinstance(files, list)

    def test_find_files_by_extension(self) -> None:
        """Should filter by extension."""
        files = linux_tools.find_files("/tmp", extension=".py", limit=10)
        assert isinstance(files, list)
        for f in files:
            assert f.endswith(".py")


class TestLogReading:
    """Test log file reading."""

    def test_read_log_file(self) -> None:
        """Should read log file."""
        # Use a file we know exists
        result = linux_tools.read_log_file("/etc/passwd", lines=5)
        assert isinstance(result, dict)
        assert "path" in result
        if "error" not in result:
            assert "lines" in result
            assert isinstance(result["lines"], list)

    def test_read_log_file_nonexistent(self) -> None:
        """Should handle nonexistent file."""
        result = linux_tools.read_log_file("/nonexistent_log.log")
        assert isinstance(result, dict)
        assert "error" in result

    def test_read_log_with_filter(self) -> None:
        """Should filter log lines."""
        result = linux_tools.read_log_file("/etc/passwd", filter_pattern="root")
        assert isinstance(result, dict)
        if "error" not in result and result["lines"]:
            for line in result["lines"]:
                assert "root" in line.lower()


class TestDockerIntegration:
    """Test Docker integration."""

    def test_check_docker_available(self) -> None:
        """Should check Docker availability."""
        available = linux_tools.check_docker_available()
        assert isinstance(available, bool)

    def test_list_docker_containers(self) -> None:
        """Should list Docker containers."""
        containers = linux_tools.list_docker_containers()
        assert isinstance(containers, list)

    def test_list_docker_images(self) -> None:
        """Should list Docker images."""
        images = linux_tools.list_docker_images()
        assert isinstance(images, list)


class TestEnvironmentInfo:
    """Test environment information."""

    def test_get_environment_info(self) -> None:
        """Should return environment info."""
        env = linux_tools.get_environment_info()
        assert isinstance(env, dict)
        assert "shell" in env
        assert "user" in env
        assert "home" in env
        assert "available_tools" in env
        assert isinstance(env["available_tools"], dict)


class TestDataclasses:
    """Test dataclass properties."""

    def test_command_result_frozen(self) -> None:
        """CommandResult should be frozen."""
        result = linux_tools.CommandResult(
            command="test",
            returncode=0,
            stdout="output",
            stderr="",
            success=True,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.command = "modified"  # type: ignore

    def test_system_info_frozen(self) -> None:
        """SystemInfo should be frozen."""
        info = linux_tools.get_system_info()
        with pytest.raises(Exception):
            info.hostname = "modified"  # type: ignore

    def test_process_info_frozen(self) -> None:
        """ProcessInfo should be frozen."""
        info = linux_tools.ProcessInfo(
            pid=1,
            user="root",
            cpu_percent=0.0,
            mem_percent=0.0,
            command="init",
            status="S",
        )
        with pytest.raises(Exception):
            info.pid = 2  # type: ignore


class TestCommandPreview:
    """Test command preview functionality."""

    def test_preview_safe_command(self) -> None:
        """Non-destructive commands should not be marked destructive."""
        preview = linux_tools.preview_command("ls -la")
        assert preview.is_destructive is False
        assert preview.can_undo is False

    def test_preview_rm_command(self) -> None:
        """rm commands should be marked as destructive."""
        preview = linux_tools.preview_command("rm -rf /tmp/testdir")
        assert preview.is_destructive is True
        assert preview.can_undo is False
        assert "Delete" in preview.description
        assert any("Recursive" in w for w in preview.warnings)

    def test_preview_mv_command(self) -> None:
        """mv commands should be marked as destructive with undo."""
        # Create a temp file for testing
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            preview = linux_tools.preview_command(f"mv {temp_path} /tmp/newname")
            assert preview.is_destructive is True
            assert preview.can_undo is True
            assert preview.undo_command is not None
            assert "Move" in preview.description
        finally:
            os.unlink(temp_path)

    def test_preview_blocked_command(self) -> None:
        """Dangerous commands should be blocked."""
        preview = linux_tools.preview_command("rm -rf /")
        assert preview.is_destructive is True
        assert "BLOCKED" in preview.description
        assert len(preview.warnings) > 0

    def test_preview_service_command(self) -> None:
        """Service commands should show undo options."""
        preview = linux_tools.preview_command("systemctl stop nginx")
        assert preview.is_destructive is True
        assert preview.can_undo is True
        assert preview.undo_command == "systemctl start nginx"

    def test_preview_package_command(self) -> None:
        """Package commands should be marked destructive."""
        preview = linux_tools.preview_command("apt install vim")
        assert preview.is_destructive is True
        assert any("Package" in w for w in preview.warnings)


class TestIntegrationWithMcpTools:
    """Test integration with MCP tools.

    These tests require the full reos package with all dependencies.
    They are skipped if dependencies like pydantic are not available.
    """

    @pytest.fixture(autouse=True)
    def check_dependencies(self) -> None:
        """Skip if reos package dependencies are not available."""
        try:
            from reos.mcp_tools import list_tools  # noqa: F401
        except ImportError:
            pytest.skip("Full reos package dependencies not available")

    def test_tools_registered(self) -> None:
        """Linux tools should be registered in MCP tools."""
        from reos.mcp_tools import list_tools

        tools = list_tools()
        tool_names = [t.name for t in tools]

        linux_tool_names = [
            "linux_run_command",
            "linux_preview_command",
            "linux_system_info",
            "linux_network_info",
            "linux_list_processes",
            "linux_list_services",
            "linux_service_status",
            "linux_manage_service",
            "linux_search_packages",
            "linux_install_package",
            "linux_list_installed_packages",
            "linux_disk_usage",
            "linux_list_directory",
            "linux_find_files",
            "linux_read_log",
            "linux_docker_containers",
            "linux_docker_images",
            "linux_environment",
            "linux_package_manager",
        ]

        for name in linux_tool_names:
            assert name in tool_names, f"Tool {name} not found in registered tools"

    def test_call_linux_system_info(self) -> None:
        """Should be able to call linux_system_info via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_system_info", arguments={})
        assert isinstance(result, dict)
        assert "hostname" in result
        assert "kernel" in result

    def test_call_linux_environment(self) -> None:
        """Should be able to call linux_environment via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_environment", arguments={})
        assert isinstance(result, dict)
        assert "shell" in result
        assert "user" in result

    def test_call_linux_run_command(self) -> None:
        """Should be able to call linux_run_command via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_run_command", arguments={"command": "echo test"})
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "test" in result["stdout"]

    def test_call_linux_disk_usage(self) -> None:
        """Should be able to call linux_disk_usage via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_disk_usage", arguments={"path": "/"})
        assert isinstance(result, dict)
        assert "total_gb" in result
        assert result["total_gb"] > 0
