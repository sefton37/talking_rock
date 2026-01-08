"""Unified Tool Provider for Code Mode.

This module provides a unified interface for tools that RIVA can use
during code execution. It avoids duplication by wrapping existing
implementations (CodeSandbox, MCP tools, etc.) behind a common protocol.

The goal: When RIVA is uncertain or can't verify, it can call tools
to gather information, search for solutions, or fetch documentation.

Tool Categories:
1. Sandbox Tools - File operations within the repository
2. Web Tools - Search, fetch documentation, lookup errors
3. MCP Bridge - Access to external MCP servers (optional)
4. System Tools - Bridge to linux_tools (optional)

Usage:
    provider = SandboxToolProvider(sandbox)
    result = provider.call_tool("read_file", {"path": "src/main.py"})

    # Composite provider for multiple sources
    provider = CompositeToolProvider([
        SandboxToolProvider(sandbox),
        WebToolProvider(),
    ])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .sandbox import CodeSandbox

logger = logging.getLogger(__name__)


# =============================================================================
# Core Data Structures
# =============================================================================


class ToolCategory(Enum):
    """Categories of tools available to RIVA."""

    SANDBOX = "sandbox"      # File operations within repo
    WEB = "web"              # Web search, fetch, docs
    MCP = "mcp"              # External MCP servers
    SYSTEM = "system"        # Linux system tools


@dataclass(frozen=True)
class ToolInfo:
    """Metadata about an available tool."""

    name: str
    description: str
    category: ToolCategory
    input_schema: dict[str, Any] = field(default_factory=dict)

    # When should RIVA consider using this tool?
    use_when: str = ""  # e.g., "uncertain about API usage", "error debugging"


@dataclass
class ToolResult:
    """Result from calling a tool."""

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # Metadata for RIVA to understand the result
    confidence: float = 1.0  # How reliable is this result?
    source: str = ""         # Where did this come from?

    def to_context(self) -> str:
        """Format result as context for LLM prompt."""
        if self.success:
            return f"[Tool Result - {self.source}]\n{self.output}"
        else:
            return f"[Tool Error - {self.source}]\n{self.error}"


# =============================================================================
# Tool Provider Protocol
# =============================================================================


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol for tool providers.

    Any class implementing this protocol can provide tools to RIVA.
    This allows composing multiple tool sources (sandbox, web, MCP, etc.)
    """

    def list_tools(self) -> list[ToolInfo]:
        """List all available tools from this provider."""
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool by name with given arguments."""
        ...

    def has_tool(self, name: str) -> bool:
        """Check if this provider has a tool with the given name."""
        ...


# =============================================================================
# Sandbox Tool Provider - Wraps CodeSandbox
# =============================================================================


class SandboxToolProvider:
    """Tool provider that wraps CodeSandbox methods.

    This avoids duplicating file operation logic - we just expose
    the existing sandbox methods through the ToolProvider interface.
    """

    def __init__(self, sandbox: "CodeSandbox") -> None:
        self._sandbox = sandbox
        self._tools = self._build_tool_list()

    def _build_tool_list(self) -> list[ToolInfo]:
        """Build list of available sandbox tools."""
        return [
            ToolInfo(
                name="read_file",
                description="Read contents of a file in the repository",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "start_line": {"type": "integer", "description": "Starting line (1-indexed)"},
                        "end_line": {"type": "integer", "description": "Ending line (inclusive)"},
                    },
                    "required": ["path"],
                },
                use_when="need to understand existing code structure or content",
            ),
            ToolInfo(
                name="grep",
                description="Search for patterns in repository files",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search"},
                        "path": {"type": "string", "description": "Path to search in (default: repo root)"},
                        "include_glob": {"type": "string", "description": "Glob pattern for files to include"},
                        "max_results": {"type": "integer", "description": "Maximum results (default: 50)"},
                    },
                    "required": ["pattern"],
                },
                use_when="looking for usage patterns, function definitions, or specific code",
            ),
            ToolInfo(
                name="find_files",
                description="Find files matching a glob pattern",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py')"},
                        "max_results": {"type": "integer", "description": "Maximum results"},
                    },
                    "required": ["pattern"],
                },
                use_when="exploring repository structure or finding related files",
            ),
            ToolInfo(
                name="get_structure",
                description="Get repository directory structure",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "max_depth": {"type": "integer", "description": "Maximum depth (default: 3)"},
                        "include_hidden": {"type": "boolean", "description": "Include hidden files"},
                    },
                },
                use_when="need overview of project layout",
            ),
            ToolInfo(
                name="git_status",
                description="Get current git status (modified files, staged changes)",
                category=ToolCategory.SANDBOX,
                input_schema={"type": "object", "properties": {}},
                use_when="need to understand current state of changes",
            ),
            ToolInfo(
                name="git_diff",
                description="Get diff of changes",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "staged": {"type": "boolean", "description": "Show staged changes only"},
                    },
                },
                use_when="need to see exactly what has changed",
            ),
            ToolInfo(
                name="run_command",
                description="Run a shell command in the repository",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to run"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
                    },
                    "required": ["command"],
                },
                use_when="need to run tests, linters, or other commands",
            ),
            # === NEW TOOLS (Language-Agnostic) ===
            ToolInfo(
                name="run_tests",
                description="Run tests (auto-detects: pytest, jest, cargo test, go test)",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Test file or directory"},
                        "pattern": {"type": "string", "description": "Test name pattern to match"},
                        "verbose": {"type": "boolean", "description": "Verbose output"},
                        "fail_fast": {"type": "boolean", "description": "Stop on first failure"},
                    },
                },
                use_when="need to run tests and verify code works",
            ),
            ToolInfo(
                name="type_check",
                description="Run type checking (auto-detects: mypy/pyright for Python, tsc for TS, cargo check for Rust)",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File or directory to check"},
                        "strict": {"type": "boolean", "description": "Use strict mode"},
                    },
                },
                use_when="need to find type errors before running tests",
            ),
            ToolInfo(
                name="lint_file",
                description="Run linter (auto-detects: ruff for Python, eslint for JS/TS, clippy for Rust)",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File or directory to lint"},
                        "fix": {"type": "boolean", "description": "Auto-fix issues where possible"},
                    },
                },
                use_when="need to check code quality and style",
            ),
            ToolInfo(
                name="format_code",
                description="Format code (auto-detects: black for Python, prettier for JS/TS, rustfmt for Rust)",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File or directory to format"},
                        "check_only": {"type": "boolean", "description": "Only check, don't modify"},
                    },
                },
                use_when="need to format code to match project style",
            ),
            ToolInfo(
                name="git_blame",
                description="Show who last modified each line of a file",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File to blame"},
                        "line_start": {"type": "integer", "description": "Starting line"},
                        "line_end": {"type": "integer", "description": "Ending line"},
                    },
                    "required": ["path"],
                },
                use_when="need to understand change history of specific code",
            ),
            ToolInfo(
                name="git_log",
                description="Show commit history",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File or directory to show history for"},
                        "max_count": {"type": "integer", "description": "Maximum commits to show (default: 10)"},
                        "oneline": {"type": "boolean", "description": "Compact one-line format"},
                        "since": {"type": "string", "description": "Show commits since date (e.g., '1 week ago')"},
                    },
                },
                use_when="need to understand project history and recent changes",
            ),
            ToolInfo(
                name="coverage_check",
                description="Run tests with coverage (auto-detects: pytest-cov, jest --coverage, cargo tarpaulin)",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Test file or directory"},
                        "source": {"type": "string", "description": "Source directory to measure coverage for"},
                        "min_coverage": {"type": "integer", "description": "Minimum coverage percentage to pass"},
                    },
                },
                use_when="need to check test coverage of code",
            ),
            ToolInfo(
                name="parse_symbols",
                description="Extract symbols from source file (functions, classes, imports) - supports Python, JS/TS, Rust, Go",
                category=ToolCategory.SANDBOX,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Source file to parse"},
                        "include_docstrings": {"type": "boolean", "description": "Include docstrings/comments"},
                        "include_signatures": {"type": "boolean", "description": "Include full function signatures"},
                    },
                    "required": ["path"],
                },
                use_when="need to understand code structure without reading full file",
            ),
        ]

    def list_tools(self) -> list[ToolInfo]:
        """List all sandbox tools."""
        return self._tools.copy()

    def has_tool(self, name: str) -> bool:
        """Check if tool exists."""
        return any(t.name == name for t in self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a sandbox tool."""
        try:
            if name == "read_file":
                # Sandbox uses: read_file(path, start, end)
                content = self._sandbox.read_file(
                    path=arguments["path"],
                    start=arguments.get("start_line", 1),
                    end=arguments.get("end_line"),
                )
                return ToolResult(
                    success=True,
                    output=content,
                    source="sandbox.read_file",
                )

            elif name == "grep":
                # Sandbox uses: grep(pattern, glob_pattern, ignore_case, max_results)
                glob_pattern = arguments.get("include_glob", "**/*")
                matches = self._sandbox.grep(
                    pattern=arguments["pattern"],
                    glob_pattern=glob_pattern,
                    max_results=arguments.get("max_results", 50),
                )
                output_lines = []
                for m in matches:
                    output_lines.append(f"{m.path}:{m.line_number}: {m.line_content}")
                return ToolResult(
                    success=True,
                    output="\n".join(output_lines) if output_lines else "No matches found",
                    data={"matches": len(matches)},
                    source="sandbox.grep",
                )

            elif name == "find_files":
                # Sandbox uses: find_files(glob_pattern, ignore_patterns)
                files = self._sandbox.find_files(
                    glob_pattern=arguments["pattern"],
                )
                # Apply max_results limit manually
                max_results = arguments.get("max_results", 100)
                files = files[:max_results]
                return ToolResult(
                    success=True,
                    output="\n".join(files) if files else "No files found",
                    data={"count": len(files)},
                    source="sandbox.find_files",
                )

            elif name == "get_structure":
                structure = self._sandbox.get_structure(
                    max_depth=arguments.get("max_depth", 3),
                    include_hidden=arguments.get("include_hidden", False),
                )
                return ToolResult(
                    success=True,
                    output=structure,
                    source="sandbox.get_structure",
                )

            elif name == "git_status":
                status = self._sandbox.git_status()
                lines = []
                if status.modified:
                    lines.append(f"Modified: {', '.join(status.modified)}")
                if status.staged:
                    lines.append(f"Staged: {', '.join(status.staged)}")
                if status.untracked:
                    lines.append(f"Untracked: {', '.join(status.untracked)}")
                return ToolResult(
                    success=True,
                    output="\n".join(lines) if lines else "Working tree clean",
                    data={
                        "modified": status.modified,
                        "staged": status.staged,
                        "untracked": status.untracked,
                    },
                    source="sandbox.git_status",
                )

            elif name == "git_diff":
                diff = self._sandbox.git_diff(staged=arguments.get("staged", False))
                return ToolResult(
                    success=True,
                    output=diff if diff else "No changes",
                    source="sandbox.git_diff",
                )

            elif name == "run_command":
                result = self._sandbox.run_command(
                    command=arguments["command"],
                    timeout=arguments.get("timeout", 30),
                )
                return ToolResult(
                    success=result.returncode == 0,
                    output=result.stdout,
                    error=result.stderr if result.returncode != 0 else None,
                    data={"returncode": result.returncode},
                    source="sandbox.run_command",
                )

            # === NEW TOOL IMPLEMENTATIONS ===

            elif name == "run_tests":
                return self._run_tests(arguments)

            elif name == "type_check":
                return self._type_check(arguments)

            elif name == "lint_file":
                return self._lint_file(arguments)

            elif name == "format_code":
                return self._format_code(arguments)

            elif name == "git_blame":
                return self._git_blame(arguments)

            elif name == "git_log":
                return self._git_log(arguments)

            elif name == "coverage_check":
                return self._coverage_check(arguments)

            elif name == "parse_symbols":
                return self._parse_symbols(arguments)

            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Unknown tool: {name}",
                    source="sandbox",
                )

        except Exception as e:
            logger.exception("Tool call failed: %s", name)
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                source=f"sandbox.{name}",
            )

    def _detect_project_language(self) -> str:
        """Detect the primary language of the project."""
        try:
            # Check for language-specific config files
            if self._sandbox.find_files("pyproject.toml") or self._sandbox.find_files("setup.py"):
                return "python"
            if self._sandbox.find_files("package.json"):
                # Check for TypeScript
                if self._sandbox.find_files("tsconfig.json"):
                    return "typescript"
                return "javascript"
            if self._sandbox.find_files("Cargo.toml"):
                return "rust"
            if self._sandbox.find_files("go.mod"):
                return "go"
            if self._sandbox.find_files("pom.xml") or self._sandbox.find_files("build.gradle"):
                return "java"

            # Fallback: count file extensions
            py_files = len(self._sandbox.find_files("**/*.py"))
            js_files = len(self._sandbox.find_files("**/*.js")) + len(self._sandbox.find_files("**/*.ts"))
            rs_files = len(self._sandbox.find_files("**/*.rs"))
            go_files = len(self._sandbox.find_files("**/*.go"))

            counts = {"python": py_files, "javascript": js_files, "rust": rs_files, "go": go_files}
            return max(counts, key=counts.get) if max(counts.values()) > 0 else "python"
        except Exception:
            return "python"  # Default fallback

    def _get_file_language(self, path: str) -> str:
        """Get language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        for ext, lang in ext_map.items():
            if path.endswith(ext):
                return lang
        return self._detect_project_language()

    def _run_tests(self, arguments: dict[str, Any]) -> ToolResult:
        """Run tests with auto-detection of test framework."""
        path = arguments.get("path", "")
        pattern = arguments.get("pattern", "")
        verbose = arguments.get("verbose", False)
        fail_fast = arguments.get("fail_fast", False)

        lang = self._detect_project_language()

        if lang == "python":
            cmd = "python -m pytest"
            if path:
                cmd += f" {path}"
            if pattern:
                cmd += f" -k '{pattern}'"
            if verbose:
                cmd += " -v"
            if fail_fast:
                cmd += " -x"
        elif lang in ("javascript", "typescript"):
            cmd = "npm test"
            if path:
                cmd += f" -- {path}"
            if pattern:
                cmd += f" --testNamePattern='{pattern}'"
            if fail_fast:
                cmd += " --bail"
        elif lang == "rust":
            cmd = "cargo test"
            if pattern:
                cmd += f" {pattern}"
            if fail_fast:
                cmd += " -- --test-threads=1"
        elif lang == "go":
            cmd = "go test"
            if path:
                cmd += f" {path}"
            else:
                cmd += " ./..."
            if verbose:
                cmd += " -v"
            if pattern:
                cmd += f" -run '{pattern}'"
        else:
            cmd = f"echo 'Unknown language: {lang}'"

        returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=120)
        return ToolResult(
            success=returncode == 0,
            output=stdout,
            error=stderr if returncode != 0 else None,
            data={"returncode": returncode, "command": cmd, "language": lang},
            source="sandbox.run_tests",
        )

    def _type_check(self, arguments: dict[str, Any]) -> ToolResult:
        """Run type checking with auto-detection."""
        path = arguments.get("path", ".")
        strict = arguments.get("strict", False)

        lang = self._get_file_language(path) if path != "." else self._detect_project_language()

        if lang == "python":
            # Try pyright first, fall back to mypy
            cmd = f"python -m pyright {path}"
            if strict:
                cmd += " --strict"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
            if returncode != 0 and "No module named pyright" in stderr:
                cmd = f"python -m mypy {path}"
                if strict:
                    cmd += " --strict"
                returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang in ("typescript", "javascript"):
            cmd = "npx tsc --noEmit"
            if path and path != ".":
                cmd += f" {path}"
            if strict:
                cmd += " --strict"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang == "rust":
            cmd = "cargo check"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=120)
        elif lang == "go":
            cmd = "go vet"
            if path and path != ".":
                cmd += f" {path}"
            else:
                cmd += " ./..."
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Type checking not supported for {lang}",
                source="sandbox.type_check",
            )

        return ToolResult(
            success=returncode == 0,
            output=stdout + stderr,
            error=None if returncode == 0 else "Type errors found",
            data={"returncode": returncode, "command": cmd, "language": lang},
            source="sandbox.type_check",
        )

    def _lint_file(self, arguments: dict[str, Any]) -> ToolResult:
        """Run linter with auto-detection."""
        path = arguments.get("path", ".")
        fix = arguments.get("fix", False)

        lang = self._get_file_language(path) if path != "." else self._detect_project_language()

        if lang == "python":
            cmd = f"python -m ruff check {path}"
            if fix:
                cmd += " --fix"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
            # Fall back to pylint if ruff not available
            if returncode != 0 and "No module named ruff" in stderr:
                cmd = f"python -m pylint {path}"
                returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang in ("typescript", "javascript"):
            cmd = f"npx eslint {path}"
            if fix:
                cmd += " --fix"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang == "rust":
            cmd = "cargo clippy"
            if fix:
                cmd += " --fix --allow-dirty"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=120)
        elif lang == "go":
            cmd = f"golangci-lint run {path}"
            if fix:
                cmd += " --fix"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Linting not supported for {lang}",
                source="sandbox.lint_file",
            )

        return ToolResult(
            success=returncode == 0,
            output=stdout + stderr,
            error=None if returncode == 0 else "Lint issues found",
            data={"returncode": returncode, "command": cmd, "language": lang},
            source="sandbox.lint_file",
        )

    def _format_code(self, arguments: dict[str, Any]) -> ToolResult:
        """Format code with auto-detection."""
        path = arguments.get("path", ".")
        check_only = arguments.get("check_only", False)

        lang = self._get_file_language(path) if path != "." else self._detect_project_language()

        if lang == "python":
            cmd = f"python -m black {path}"
            if check_only:
                cmd += " --check --diff"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang in ("typescript", "javascript"):
            cmd = f"npx prettier {path}"
            if check_only:
                cmd += " --check"
            else:
                cmd += " --write"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang == "rust":
            cmd = "cargo fmt"
            if check_only:
                cmd += " --check"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        elif lang == "go":
            if check_only:
                cmd = f"gofmt -d {path}"
            else:
                cmd = f"gofmt -w {path}"
            returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=60)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Formatting not supported for {lang}",
                source="sandbox.format_code",
            )

        return ToolResult(
            success=returncode == 0,
            output=stdout + stderr,
            error=None if returncode == 0 else "Formatting issues found",
            data={"returncode": returncode, "command": cmd, "language": lang},
            source="sandbox.format_code",
        )

    def _git_blame(self, arguments: dict[str, Any]) -> ToolResult:
        """Run git blame on a file."""
        path = arguments["path"]
        line_start = arguments.get("line_start")
        line_end = arguments.get("line_end")

        cmd = f"git blame {path}"
        if line_start and line_end:
            cmd += f" -L {line_start},{line_end}"
        elif line_start:
            cmd += f" -L {line_start},"

        returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=30)
        return ToolResult(
            success=returncode == 0,
            output=stdout,
            error=stderr if returncode != 0 else None,
            data={"returncode": returncode},
            source="sandbox.git_blame",
        )

    def _git_log(self, arguments: dict[str, Any]) -> ToolResult:
        """Show git commit history."""
        path = arguments.get("path", "")
        max_count = arguments.get("max_count", 10)
        oneline = arguments.get("oneline", True)
        since = arguments.get("since", "")

        cmd = "git log"
        cmd += f" -n {max_count}"
        if oneline:
            cmd += " --oneline"
        else:
            cmd += " --format='%h %s (%an, %ar)'"
        if since:
            cmd += f" --since='{since}'"
        if path:
            cmd += f" -- {path}"

        returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=30)
        return ToolResult(
            success=returncode == 0,
            output=stdout,
            error=stderr if returncode != 0 else None,
            data={"returncode": returncode},
            source="sandbox.git_log",
        )

    def _coverage_check(self, arguments: dict[str, Any]) -> ToolResult:
        """Run tests with coverage."""
        path = arguments.get("path", "")
        source = arguments.get("source", "src")
        min_coverage = arguments.get("min_coverage", 0)

        lang = self._detect_project_language()

        if lang == "python":
            cmd = f"python -m pytest --cov={source}"
            if path:
                cmd += f" {path}"
            cmd += " --cov-report=term-missing"
            if min_coverage > 0:
                cmd += f" --cov-fail-under={min_coverage}"
        elif lang in ("typescript", "javascript"):
            cmd = "npm test -- --coverage"
            if path:
                cmd += f" {path}"
        elif lang == "rust":
            cmd = "cargo tarpaulin"
            if min_coverage > 0:
                cmd += f" --fail-under {min_coverage}"
        elif lang == "go":
            cmd = "go test -cover ./..."
            if path:
                cmd = f"go test -cover {path}"
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Coverage not supported for {lang}",
                source="sandbox.coverage_check",
            )

        returncode, stdout, stderr = self._sandbox.run_command(cmd, timeout=180)
        return ToolResult(
            success=returncode == 0,
            output=stdout + stderr,
            error=None if returncode == 0 else "Coverage check failed",
            data={"returncode": returncode, "command": cmd, "language": lang},
            source="sandbox.coverage_check",
        )

    def _parse_symbols(self, arguments: dict[str, Any]) -> ToolResult:
        """Parse source file and extract symbols."""
        path = arguments["path"]
        include_docstrings = arguments.get("include_docstrings", False)
        include_signatures = arguments.get("include_signatures", True)

        lang = self._get_file_language(path)

        try:
            content = self._sandbox.read_file(path)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Could not read file: {e}",
                source="sandbox.parse_symbols",
            )

        if lang == "python":
            return self._parse_python_symbols(content, include_docstrings, include_signatures)
        elif lang in ("typescript", "javascript"):
            return self._parse_js_symbols(content, include_docstrings, include_signatures)
        elif lang == "rust":
            return self._parse_rust_symbols(content, include_signatures)
        elif lang == "go":
            return self._parse_go_symbols(content, include_signatures)
        else:
            # Fallback: regex-based extraction
            return self._parse_generic_symbols(content, lang)

    def _parse_python_symbols(self, content: str, include_docstrings: bool, include_signatures: bool) -> ToolResult:
        """Parse Python source and extract symbols using AST."""
        import ast

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Syntax error: {e}",
                source="sandbox.parse_symbols",
            )

        symbols = {"imports": [], "classes": [], "functions": [], "constants": []}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    symbols["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    symbols["imports"].append(f"{module}.{alias.name}")
            elif isinstance(node, ast.ClassDef):
                cls_info = {"name": node.name, "line": node.lineno, "methods": []}
                if include_docstrings:
                    cls_info["docstring"] = ast.get_docstring(node) or ""
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_info = {"name": item.name, "line": item.lineno}
                        if include_signatures:
                            args = [a.arg for a in item.args.args]
                            method_info["signature"] = f"({', '.join(args)})"
                        cls_info["methods"].append(method_info)
                symbols["classes"].append(cls_info)
            elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                func_info = {"name": node.name, "line": node.lineno}
                if include_docstrings:
                    func_info["docstring"] = ast.get_docstring(node) or ""
                if include_signatures:
                    args = [a.arg for a in node.args.args]
                    func_info["signature"] = f"({', '.join(args)})"
                symbols["functions"].append(func_info)
            elif isinstance(node, ast.Assign) and node.col_offset == 0:
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        symbols["constants"].append(target.id)

        # Format output
        output_lines = []
        if symbols["imports"]:
            output_lines.append(f"Imports: {', '.join(symbols['imports'][:10])}")
        if symbols["classes"]:
            output_lines.append("\nClasses:")
            for cls in symbols["classes"]:
                output_lines.append(f"  class {cls['name']} (line {cls['line']})")
                for method in cls["methods"][:5]:
                    sig = method.get("signature", "()")
                    output_lines.append(f"    def {method['name']}{sig}")
        if symbols["functions"]:
            output_lines.append("\nFunctions:")
            for func in symbols["functions"]:
                sig = func.get("signature", "()")
                output_lines.append(f"  def {func['name']}{sig} (line {func['line']})")
        if symbols["constants"]:
            output_lines.append(f"\nConstants: {', '.join(symbols['constants'][:10])}")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            data=symbols,
            source="sandbox.parse_symbols",
        )

    def _parse_js_symbols(self, content: str, include_docstrings: bool, include_signatures: bool) -> ToolResult:
        """Parse JS/TS source using regex (no external parser needed)."""
        import re

        symbols = {"imports": [], "classes": [], "functions": [], "exports": []}

        # Extract imports
        import_pattern = r"import\s+(?:{[^}]+}|\*\s+as\s+\w+|\w+)\s+from\s+['\"]([^'\"]+)['\"]"
        symbols["imports"] = re.findall(import_pattern, content)

        # Extract classes
        class_pattern = r"class\s+(\w+)(?:\s+extends\s+\w+)?\s*\{"
        for match in re.finditer(class_pattern, content):
            symbols["classes"].append({"name": match.group(1), "line": content[:match.start()].count("\n") + 1})

        # Extract functions (named functions, arrow functions assigned to const)
        func_pattern = r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)"
        for match in re.finditer(func_pattern, content):
            name = match.group(1) or match.group(2)
            if name:
                symbols["functions"].append({"name": name, "line": content[:match.start()].count("\n") + 1})

        # Extract exports
        export_pattern = r"export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)"
        symbols["exports"] = re.findall(export_pattern, content)

        # Format output
        output_lines = []
        if symbols["imports"]:
            output_lines.append(f"Imports: {', '.join(symbols['imports'][:10])}")
        if symbols["classes"]:
            output_lines.append("\nClasses:")
            for cls in symbols["classes"]:
                output_lines.append(f"  class {cls['name']} (line {cls['line']})")
        if symbols["functions"]:
            output_lines.append("\nFunctions:")
            for func in symbols["functions"]:
                output_lines.append(f"  {func['name']} (line {func['line']})")
        if symbols["exports"]:
            output_lines.append(f"\nExports: {', '.join(symbols['exports'][:10])}")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            data=symbols,
            source="sandbox.parse_symbols",
        )

    def _parse_rust_symbols(self, content: str, include_signatures: bool) -> ToolResult:
        """Parse Rust source using regex."""
        import re

        symbols = {"uses": [], "structs": [], "enums": [], "functions": [], "impls": []}

        # Extract use statements
        use_pattern = r"use\s+([^;]+);"
        symbols["uses"] = re.findall(use_pattern, content)[:10]

        # Extract structs
        struct_pattern = r"(?:pub\s+)?struct\s+(\w+)"
        for match in re.finditer(struct_pattern, content):
            symbols["structs"].append({"name": match.group(1), "line": content[:match.start()].count("\n") + 1})

        # Extract enums
        enum_pattern = r"(?:pub\s+)?enum\s+(\w+)"
        for match in re.finditer(enum_pattern, content):
            symbols["enums"].append({"name": match.group(1), "line": content[:match.start()].count("\n") + 1})

        # Extract functions
        fn_pattern = r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)"
        for match in re.finditer(fn_pattern, content):
            func_info = {"name": match.group(1), "line": content[:match.start()].count("\n") + 1}
            if include_signatures:
                func_info["signature"] = f"({match.group(2).strip()})"
            symbols["functions"].append(func_info)

        # Extract impl blocks
        impl_pattern = r"impl(?:<[^>]+>)?\s+(\w+)"
        symbols["impls"] = re.findall(impl_pattern, content)[:10]

        # Format output
        output_lines = []
        if symbols["uses"]:
            output_lines.append(f"Uses: {', '.join(symbols['uses'][:5])}")
        if symbols["structs"]:
            output_lines.append("\nStructs:")
            for s in symbols["structs"]:
                output_lines.append(f"  struct {s['name']} (line {s['line']})")
        if symbols["enums"]:
            output_lines.append("\nEnums:")
            for e in symbols["enums"]:
                output_lines.append(f"  enum {e['name']} (line {e['line']})")
        if symbols["functions"]:
            output_lines.append("\nFunctions:")
            for func in symbols["functions"]:
                sig = func.get("signature", "()")
                output_lines.append(f"  fn {func['name']}{sig} (line {func['line']})")
        if symbols["impls"]:
            output_lines.append(f"\nImpl blocks: {', '.join(symbols['impls'])}")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            data=symbols,
            source="sandbox.parse_symbols",
        )

    def _parse_go_symbols(self, content: str, include_signatures: bool) -> ToolResult:
        """Parse Go source using regex."""
        import re

        symbols = {"package": "", "imports": [], "types": [], "functions": [], "interfaces": []}

        # Extract package
        pkg_match = re.search(r"package\s+(\w+)", content)
        symbols["package"] = pkg_match.group(1) if pkg_match else ""

        # Extract imports
        import_pattern = r"import\s+(?:\(\s*([^)]+)\s*\)|\"([^\"]+)\")"
        for match in re.finditer(import_pattern, content):
            if match.group(1):
                imports = re.findall(r"\"([^\"]+)\"", match.group(1))
                symbols["imports"].extend(imports)
            elif match.group(2):
                symbols["imports"].append(match.group(2))

        # Extract types (structs)
        type_pattern = r"type\s+(\w+)\s+struct\s*\{"
        for match in re.finditer(type_pattern, content):
            symbols["types"].append({"name": match.group(1), "line": content[:match.start()].count("\n") + 1})

        # Extract interfaces
        interface_pattern = r"type\s+(\w+)\s+interface\s*\{"
        for match in re.finditer(interface_pattern, content):
            symbols["interfaces"].append({"name": match.group(1), "line": content[:match.start()].count("\n") + 1})

        # Extract functions
        func_pattern = r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)"
        for match in re.finditer(func_pattern, content):
            func_info = {"name": match.group(1), "line": content[:match.start()].count("\n") + 1}
            if include_signatures:
                func_info["signature"] = f"({match.group(2).strip()})"
            symbols["functions"].append(func_info)

        # Format output
        output_lines = []
        if symbols["package"]:
            output_lines.append(f"Package: {symbols['package']}")
        if symbols["imports"]:
            output_lines.append(f"Imports: {', '.join(symbols['imports'][:5])}")
        if symbols["types"]:
            output_lines.append("\nTypes:")
            for t in symbols["types"]:
                output_lines.append(f"  type {t['name']} struct (line {t['line']})")
        if symbols["interfaces"]:
            output_lines.append("\nInterfaces:")
            for i in symbols["interfaces"]:
                output_lines.append(f"  type {i['name']} interface (line {i['line']})")
        if symbols["functions"]:
            output_lines.append("\nFunctions:")
            for func in symbols["functions"]:
                sig = func.get("signature", "()")
                output_lines.append(f"  func {func['name']}{sig} (line {func['line']})")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            data=symbols,
            source="sandbox.parse_symbols",
        )

    def _parse_generic_symbols(self, content: str, lang: str) -> ToolResult:
        """Fallback regex-based symbol extraction for unknown languages."""
        import re

        # Try common patterns
        functions = re.findall(r"(?:def|function|fn|func)\s+(\w+)", content)
        classes = re.findall(r"(?:class|struct|type)\s+(\w+)", content)

        output_lines = [f"Language: {lang} (generic parser)"]
        if classes:
            output_lines.append(f"Classes/Types: {', '.join(classes[:10])}")
        if functions:
            output_lines.append(f"Functions: {', '.join(functions[:10])}")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            data={"classes": classes, "functions": functions},
            source="sandbox.parse_symbols",
        )


# =============================================================================
# Composite Tool Provider - Combines Multiple Providers
# =============================================================================


class CompositeToolProvider:
    """Combines multiple tool providers into one.

    Tools are searched in order - first provider with a matching tool wins.

    Usage:
        provider = CompositeToolProvider([
            SandboxToolProvider(sandbox),
            WebToolProvider(),
            MCPBridgeProvider(db),
        ])
    """

    def __init__(self, providers: list[ToolProvider]) -> None:
        self._providers = providers

    def list_tools(self) -> list[ToolInfo]:
        """List all tools from all providers."""
        all_tools: list[ToolInfo] = []
        seen_names: set[str] = set()

        for provider in self._providers:
            for tool in provider.list_tools():
                if tool.name not in seen_names:
                    all_tools.append(tool)
                    seen_names.add(tool.name)

        return all_tools

    def has_tool(self, name: str) -> bool:
        """Check if any provider has this tool."""
        return any(p.has_tool(name) for p in self._providers)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call tool from first provider that has it."""
        for provider in self._providers:
            if provider.has_tool(name):
                return provider.call_tool(name, arguments)

        return ToolResult(
            success=False,
            output="",
            error=f"No provider has tool: {name}",
            source="composite",
        )

    def add_provider(self, provider: ToolProvider) -> None:
        """Add a provider to the composite."""
        self._providers.append(provider)


# =============================================================================
# Null Tool Provider - For when tools are disabled
# =============================================================================


class NullToolProvider:
    """A tool provider that has no tools.

    Use this when tools are disabled or not configured.
    """

    def list_tools(self) -> list[ToolInfo]:
        return []

    def has_tool(self, name: str) -> bool:
        return False

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            output="",
            error="Tools are disabled",
            source="null",
        )


# =============================================================================
# Factory Function
# =============================================================================


def create_tool_provider(
    sandbox: "CodeSandbox | None" = None,
    enable_web: bool = False,
    enable_mcp: bool = False,
) -> ToolProvider:
    """Create a tool provider with the specified capabilities.

    Args:
        sandbox: CodeSandbox for repository operations
        enable_web: Enable web search/fetch tools
        enable_mcp: Enable MCP bridge tools (Phase 5 - not yet implemented)

    Returns:
        A configured ToolProvider
    """
    providers: list[ToolProvider] = []

    if sandbox is not None:
        providers.append(SandboxToolProvider(sandbox))

    # Phase 3: Web tools for search and documentation
    if enable_web:
        from .web_tools import WebToolProvider
        providers.append(WebToolProvider())

    # Phase 5: MCP bridge (future)
    # if enable_mcp:
    #     providers.append(MCPBridgeProvider(db))

    if not providers:
        return NullToolProvider()

    if len(providers) == 1:
        return providers[0]

    return CompositeToolProvider(providers)
