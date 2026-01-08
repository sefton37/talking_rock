"""Tests for the unified ToolProvider system."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import CodeSandbox
from reos.code_mode.tools import (
    ToolCategory,
    ToolInfo,
    ToolResult,
    ToolProvider,
    SandboxToolProvider,
    CompositeToolProvider,
    NullToolProvider,
    create_tool_provider,
)


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_successful_result(self) -> None:
        result = ToolResult(
            success=True,
            output="file contents here",
            source="sandbox.read_file",
        )
        assert result.success
        assert "file contents" in result.output
        assert result.error is None

    def test_failed_result(self) -> None:
        result = ToolResult(
            success=False,
            output="",
            error="File not found",
            source="sandbox.read_file",
        )
        assert not result.success
        assert result.error == "File not found"

    def test_to_context_success(self) -> None:
        result = ToolResult(
            success=True,
            output="def hello(): pass",
            source="sandbox.read_file",
        )
        context = result.to_context()
        assert "[Tool Result" in context
        assert "sandbox.read_file" in context
        assert "def hello()" in context

    def test_to_context_error(self) -> None:
        result = ToolResult(
            success=False,
            output="",
            error="Permission denied",
            source="sandbox.read_file",
        )
        context = result.to_context()
        assert "[Tool Error" in context
        assert "Permission denied" in context


class TestToolInfo:
    """Tests for ToolInfo dataclass."""

    def test_tool_info_creation(self) -> None:
        tool = ToolInfo(
            name="read_file",
            description="Read a file",
            category=ToolCategory.SANDBOX,
            input_schema={"type": "object"},
            use_when="need to read code",
        )
        assert tool.name == "read_file"
        assert tool.category == ToolCategory.SANDBOX


class TestSandboxToolProvider:
    """Tests for SandboxToolProvider."""

    def test_list_tools(self, temp_git_repo: Path) -> None:
        """Should list all sandbox tools."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        tools = provider.list_tools()

        assert len(tools) >= 5  # At least 5 tools
        tool_names = [t.name for t in tools]
        assert "read_file" in tool_names
        assert "grep" in tool_names
        assert "find_files" in tool_names
        assert "git_status" in tool_names

    def test_has_tool(self, temp_git_repo: Path) -> None:
        """Should check if tool exists."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        assert provider.has_tool("read_file")
        assert provider.has_tool("grep")
        assert not provider.has_tool("nonexistent_tool")

    def test_call_read_file(self, temp_git_repo: Path) -> None:
        """Should read file contents."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("read_file", {"path": "src/reos/example.py"})

        assert result.success
        assert "def hello()" in result.output
        assert result.source == "sandbox.read_file"

    def test_call_read_file_not_found(self, temp_git_repo: Path) -> None:
        """Should handle missing file."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("read_file", {"path": "nonexistent.py"})

        assert not result.success
        assert result.error is not None

    def test_call_grep(self, temp_git_repo: Path) -> None:
        """Should search for patterns."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("grep", {"pattern": "def hello"})

        assert result.success
        assert "example.py" in result.output or "hello" in result.output

    def test_call_find_files(self, temp_git_repo: Path) -> None:
        """Should find files by pattern."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("find_files", {"pattern": "**/*.py"})

        assert result.success
        assert "example.py" in result.output

    def test_call_git_status(self, temp_git_repo: Path) -> None:
        """Should get git status."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("git_status", {})

        assert result.success
        # Clean repo after initial commit
        assert "clean" in result.output.lower() or result.output

    def test_call_unknown_tool(self, temp_git_repo: Path) -> None:
        """Should handle unknown tool gracefully."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("nonexistent_tool", {})

        assert not result.success
        assert "Unknown tool" in result.error

    def test_implements_protocol(self, temp_git_repo: Path) -> None:
        """Should implement ToolProvider protocol."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        assert isinstance(provider, ToolProvider)


class TestNullToolProvider:
    """Tests for NullToolProvider."""

    def test_list_tools_empty(self) -> None:
        """Should return empty list."""
        provider = NullToolProvider()
        assert provider.list_tools() == []

    def test_has_tool_false(self) -> None:
        """Should always return False."""
        provider = NullToolProvider()
        assert not provider.has_tool("anything")

    def test_call_tool_fails(self) -> None:
        """Should fail with disabled message."""
        provider = NullToolProvider()
        result = provider.call_tool("read_file", {"path": "test.py"})

        assert not result.success
        assert "disabled" in result.error.lower()


class TestCompositeToolProvider:
    """Tests for CompositeToolProvider."""

    def test_combines_tools(self, temp_git_repo: Path) -> None:
        """Should combine tools from multiple providers."""
        sandbox = CodeSandbox(temp_git_repo)
        sandbox_provider = SandboxToolProvider(sandbox)
        null_provider = NullToolProvider()

        composite = CompositeToolProvider([sandbox_provider, null_provider])
        tools = composite.list_tools()

        # Should have sandbox tools
        tool_names = [t.name for t in tools]
        assert "read_file" in tool_names

    def test_no_duplicates(self, temp_git_repo: Path) -> None:
        """Should not duplicate tool names."""
        sandbox = CodeSandbox(temp_git_repo)
        provider1 = SandboxToolProvider(sandbox)
        provider2 = SandboxToolProvider(sandbox)

        composite = CompositeToolProvider([provider1, provider2])
        tools = composite.list_tools()

        # Should only have one read_file
        read_file_count = sum(1 for t in tools if t.name == "read_file")
        assert read_file_count == 1

    def test_call_tool_first_provider(self, temp_git_repo: Path) -> None:
        """Should call tool from first provider that has it."""
        sandbox = CodeSandbox(temp_git_repo)
        sandbox_provider = SandboxToolProvider(sandbox)
        null_provider = NullToolProvider()

        composite = CompositeToolProvider([sandbox_provider, null_provider])
        result = composite.call_tool("read_file", {"path": "src/reos/example.py"})

        assert result.success
        assert "hello" in result.output

    def test_call_unknown_tool(self, temp_git_repo: Path) -> None:
        """Should fail for unknown tools."""
        sandbox = CodeSandbox(temp_git_repo)
        composite = CompositeToolProvider([SandboxToolProvider(sandbox)])

        result = composite.call_tool("unknown", {})

        assert not result.success
        assert "No provider" in result.error

    def test_add_provider(self, temp_git_repo: Path) -> None:
        """Should allow adding providers dynamically."""
        composite = CompositeToolProvider([NullToolProvider()])
        assert not composite.has_tool("read_file")

        sandbox = CodeSandbox(temp_git_repo)
        composite.add_provider(SandboxToolProvider(sandbox))

        assert composite.has_tool("read_file")


class TestCreateToolProvider:
    """Tests for the factory function."""

    def test_with_sandbox(self, temp_git_repo: Path) -> None:
        """Should create sandbox provider."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = create_tool_provider(sandbox=sandbox)

        assert provider.has_tool("read_file")

    def test_without_sandbox(self) -> None:
        """Should return null provider when nothing configured."""
        provider = create_tool_provider()

        assert isinstance(provider, NullToolProvider)
        assert not provider.has_tool("read_file")

    def test_provider_is_protocol(self, temp_git_repo: Path) -> None:
        """Factory should return ToolProvider compatible object."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = create_tool_provider(sandbox=sandbox)

        # Should be able to call protocol methods
        tools = provider.list_tools()
        assert len(tools) > 0


# ==============================================================================
# New Tool Tests
# ==============================================================================

class TestNewTools:
    """Tests for the new production-grade tools."""

    def test_has_all_new_tools(self, temp_git_repo: Path) -> None:
        """Provider should have all new tools."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        new_tools = [
            "run_tests",
            "type_check",
            "lint_file",
            "format_code",
            "git_blame",
            "git_log",
            "coverage_check",
            "parse_symbols",
        ]

        for tool_name in new_tools:
            assert provider.has_tool(tool_name), f"Missing tool: {tool_name}"

    def test_run_tests_python(self, temp_git_repo: Path) -> None:
        """Should run pytest for Python projects."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("run_tests", {"verbose": True, "fail_fast": True})

        # May fail since no tests, but should have run the command
        assert result.data.get("command") is not None
        assert "pytest" in result.data.get("command", "")
        assert result.data.get("language") == "python"

    def test_git_log(self, temp_git_repo: Path) -> None:
        """Should get git commit history."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("git_log", {"max_count": 5, "oneline": True})

        assert result.success
        assert "Initial commit" in result.output or result.output  # Has some output

    def test_git_blame(self, temp_git_repo: Path) -> None:
        """Should get git blame for a file."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("git_blame", {"path": "src/reos/example.py"})

        assert result.success
        assert result.output  # Has blame output

    def test_parse_symbols_python(self, temp_git_repo: Path) -> None:
        """Should parse Python symbols."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("parse_symbols", {
            "path": "src/reos/example.py",
            "include_signatures": True,
        })

        assert result.success
        assert "hello" in result.output.lower()  # Should find the hello function
        assert "Functions:" in result.output

    def test_parse_symbols_with_docstrings(self, temp_git_repo: Path) -> None:
        """Should include docstrings when requested."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("parse_symbols", {
            "path": "src/reos/example.py",
            "include_docstrings": True,
        })

        assert result.success
        assert result.data.get("functions") is not None

    def test_type_check_returns_result(self, temp_git_repo: Path) -> None:
        """Should attempt type checking."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("type_check", {"path": "src/reos/example.py"})

        # May fail if pyright/mypy not installed, but should have attempted
        assert result.data.get("command") is not None
        assert result.data.get("language") == "python"

    def test_lint_file_returns_result(self, temp_git_repo: Path) -> None:
        """Should attempt linting."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("lint_file", {"path": "src/reos/example.py"})

        # May fail if ruff not installed, but should have attempted
        assert result.data.get("command") is not None
        assert result.data.get("language") == "python"

    def test_format_code_check_only(self, temp_git_repo: Path) -> None:
        """Should check formatting without modifying."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        result = provider.call_tool("format_code", {
            "path": "src/reos/example.py",
            "check_only": True,
        })

        # May fail if black not installed, but should have attempted
        assert result.data.get("command") is not None
        assert "--check" in result.data.get("command", "")

    def test_detect_project_language(self, temp_git_repo: Path) -> None:
        """Should detect Python as project language."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        lang = provider._detect_project_language()

        assert lang == "python"  # Our test repo has Python files

    def test_get_file_language(self, temp_git_repo: Path) -> None:
        """Should detect language from file extension."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        assert provider._get_file_language("test.py") == "python"
        assert provider._get_file_language("test.ts") == "typescript"
        assert provider._get_file_language("test.rs") == "rust"
        assert provider._get_file_language("test.go") == "go"
        assert provider._get_file_language("test.js") == "javascript"

    def test_tool_info_has_proper_schema(self, temp_git_repo: Path) -> None:
        """New tools should have proper input schemas."""
        sandbox = CodeSandbox(temp_git_repo)
        provider = SandboxToolProvider(sandbox)

        tools = provider.list_tools()
        for tool in tools:
            assert tool.input_schema is not None
            assert tool.category is not None
            assert tool.description
