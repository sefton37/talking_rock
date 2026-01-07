"""Code Mode planning - creates step-by-step plans for code modifications.

The planner analyzes code tasks and generates structured plans that can be
reviewed and approved before execution.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.sandbox import CodeSandbox
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


class CodeStepType(Enum):
    """Types of steps in a code task plan."""

    READ_FILES = "read_files"       # Gather context by reading files
    ANALYZE = "analyze"             # Understand structure/patterns
    PLAN = "plan"                   # Design changes
    WRITE_FILE = "write_file"       # Create or overwrite file
    EDIT_FILE = "edit_file"         # Modify existing file
    CREATE_FILE = "create_file"     # Create new file
    DELETE_FILE = "delete_file"     # Remove file
    RUN_COMMAND = "run_command"     # Shell command in repo
    RUN_TESTS = "run_tests"         # Execute test suite
    VERIFY = "verify"               # Confirm changes work


class ImpactLevel(Enum):
    """Estimated impact of a code change."""

    MINOR = "minor"           # Small change, single file, low risk
    MODERATE = "moderate"     # Multiple files or significant logic change
    MAJOR = "major"           # Architectural change, high risk


@dataclass
class CodeStep:
    """A single step in a code task plan."""

    id: str
    type: CodeStepType
    description: str
    # Step-specific details
    target_path: str | None = None      # File path for file operations
    command: str | None = None          # Command for RUN_COMMAND/RUN_TESTS
    old_content: str | None = None      # For EDIT_FILE - text to replace
    new_content: str | None = None      # For WRITE/EDIT/CREATE - new content
    glob_pattern: str | None = None     # For READ_FILES - pattern to match
    # Execution state
    status: str = "pending"             # pending, in_progress, completed, failed
    result: str | None = None           # Result message after execution
    error: str | None = None            # Error message if failed

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "target_path": self.target_path,
            "command": self.command,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "glob_pattern": self.glob_pattern,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class CodeTaskPlan:
    """A complete plan for a code modification task."""

    id: str
    goal: str
    steps: list[CodeStep]
    context_files: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    files_to_delete: list[str] = field(default_factory=list)
    estimated_impact: ImpactLevel = ImpactLevel.MINOR
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Approval state
    approved: bool = False
    rejected: bool = False
    rejection_reason: str | None = None

    def summary(self) -> str:
        """Generate human-readable summary of the plan."""
        lines = [f"## Plan: {self.goal}", ""]

        if self.context_files:
            lines.append(f"**Files to read:** {', '.join(self.context_files)}")
        if self.files_to_modify:
            lines.append(f"**Files to modify:** {', '.join(self.files_to_modify)}")
        if self.files_to_create:
            lines.append(f"**Files to create:** {', '.join(self.files_to_create)}")
        if self.files_to_delete:
            lines.append(f"**Files to delete:** {', '.join(self.files_to_delete)}")

        lines.append(f"**Estimated impact:** {self.estimated_impact.value}")
        lines.append("")
        lines.append("### Steps:")

        for i, step in enumerate(self.steps, 1):
            status_icon = {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(
                step.status, "🔄"
            )
            lines.append(f"{i}. {status_icon} [{step.type.value}] {step.description}")
            if step.target_path:
                lines.append(f"   → {step.target_path}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "context_files": self.context_files,
            "files_to_modify": self.files_to_modify,
            "files_to_create": self.files_to_create,
            "files_to_delete": self.files_to_delete,
            "estimated_impact": self.estimated_impact.value,
            "created_at": self.created_at.isoformat(),
            "approved": self.approved,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason,
        }


def _generate_step_id() -> str:
    """Generate unique step ID."""
    return f"step-{uuid.uuid4().hex[:8]}"


def _generate_plan_id() -> str:
    """Generate unique plan ID."""
    return f"plan-{uuid.uuid4().hex[:12]}"


class CodePlanner:
    """Creates plans for code modifications.

    The planner uses the sandbox to explore the repository and the LLM
    to generate intelligent step-by-step plans for code changes.
    """

    # Common libraries and their key modules/patterns
    LIBRARY_HINTS = {
        "pygame": {
            "language": "python",
            "imports": ["pygame", "pygame.sprite", "pygame.display", "pygame.time"],
            "patterns": [
                "pygame.init() at start",
                "pygame.display.set_mode() for window",
                "pygame.time.Clock() for FPS control",
                "pygame.sprite.Sprite for game objects",
                "Main game loop: while running: events, update, draw",
            ],
            "dependencies": ["pygame>=2.0.0"],
        },
        "flask": {
            "language": "python",
            "imports": ["flask", "flask.Flask"],
            "patterns": ["@app.route for endpoints", "app.run() to start"],
            "dependencies": ["flask>=2.0.0"],
        },
        "fastapi": {
            "language": "python",
            "imports": ["fastapi", "uvicorn"],
            "patterns": ["@app.get/@app.post decorators", "Pydantic models"],
            "dependencies": ["fastapi>=0.100.0", "uvicorn>=0.20.0"],
        },
        "django": {
            "language": "python",
            "imports": ["django"],
            "patterns": ["models.py, views.py, urls.py structure"],
            "dependencies": ["django>=4.0"],
        },
        "react": {
            "language": "typescript",
            "imports": ["react", "react-dom"],
            "patterns": ["Functional components", "useState, useEffect hooks"],
            "dependencies": ["react", "react-dom"],
        },
    }

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
    ) -> None:
        """Initialize planner.

        Args:
            sandbox: CodeSandbox for repository access.
            llm: Optional LLM provider for LLM-based planning.
        """
        self.sandbox = sandbox
        self._llm = llm

    def _detect_libraries(self, request: str) -> list[dict]:
        """Detect mentioned libraries and return their hints."""
        detected = []
        request_lower = request.lower()

        for lib_name, hints in self.LIBRARY_HINTS.items():
            if lib_name in request_lower:
                detected.append({"name": lib_name, **hints})

        return detected

    def create_plan(
        self,
        request: str,
        act: Act,
    ) -> CodeTaskPlan:
        """Create a plan for the given code request.

        Args:
            request: User's code modification request.
            act: The active Act with repository assignment.

        Returns:
            CodeTaskPlan with steps to accomplish the goal.
        """
        # Gather repository context
        repo_context = self._gather_repo_context()

        # Detect libraries mentioned in request (pygame, flask, etc.)
        detected_libs = self._detect_libraries(request)
        if detected_libs:
            repo_context["detected_libraries"] = detected_libs
            logger.info("Detected libraries: %s", [lib["name"] for lib in detected_libs])

        # Use LLM to generate plan if available
        if self._llm is not None:
            plan = self._generate_plan_with_llm(request, act, repo_context)
            if plan is not None:
                return plan

        # Fallback: choose appropriate plan type based on repo state
        python_files = repo_context.get("python_files", [])
        is_empty_repo = len(python_files) == 0

        if is_empty_repo:
            # New project - create concrete file creation plan
            return self._create_new_project_plan(request, act, repo_context)
        else:
            # Existing code - need to explore first
            return self._create_exploration_plan(request, act)

    def create_fix_plan(
        self,
        error_output: str,
        original_plan: CodeTaskPlan | None = None,
    ) -> CodeTaskPlan:
        """Create a plan to fix test/build failures.

        Args:
            error_output: The error message or test output.
            original_plan: Optional original plan that led to the error.

        Returns:
            CodeTaskPlan to fix the errors.
        """
        # Extract file references from error output
        files_mentioned = self._extract_file_references(error_output)

        steps = [
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.READ_FILES,
                description="Read files mentioned in error output",
                glob_pattern=None,  # Will read specific files
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.ANALYZE,
                description="Analyze error and identify root cause",
            ),
        ]

        # Add read steps for each mentioned file
        for file_path in files_mentioned[:5]:  # Limit to 5 files
            steps.append(
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.READ_FILES,
                    description=f"Read {file_path}",
                    target_path=file_path,
                )
            )

        steps.extend([
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.PLAN,
                description="Design fix based on error analysis",
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.RUN_TESTS,
                description="Verify fix by running tests",
            ),
        ])

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=f"Fix error: {error_output[:100]}...",
            steps=steps,
            context_files=files_mentioned,
            estimated_impact=ImpactLevel.MINOR,
        )

    def _gather_repo_context(self) -> dict[str, Any]:
        """Gather context about the repository."""
        context: dict[str, Any] = {}

        try:
            # Get directory structure
            context["structure"] = self.sandbox.get_structure(max_depth=2)

            # Get git status
            context["git_status"] = self.sandbox.git_status()

            # Find key files
            context["python_files"] = self.sandbox.find_files("**/*.py")[:20]
            context["test_files"] = self.sandbox.find_files("**/test_*.py")[:10]
            context["config_files"] = self.sandbox.find_files(
                "**/pyproject.toml"
            ) + self.sandbox.find_files("**/setup.py")

        except Exception as e:
            logger.warning("Error gathering repo context: %s", e)

        return context

    def _generate_plan_with_llm(
        self,
        request: str,
        act: Act,
        repo_context: dict[str, Any],
    ) -> CodeTaskPlan | None:
        """Use LLM to generate a structured plan."""
        if self._llm is None:
            return None

        # Determine if this is a new project or modifications to existing code
        python_files = repo_context.get("python_files", [])
        is_empty_repo = len(python_files) == 0

        # Build library hints section
        lib_hints_section = ""
        detected_libs = repo_context.get("detected_libraries", [])
        if detected_libs:
            lib_hints_section = "\n\nLIBRARY CONTEXT (use these patterns):"
            for lib in detected_libs:
                lib_hints_section += f"\n\n{lib['name'].upper()}:"
                lib_hints_section += f"\n- Language: {lib['language']}"
                lib_hints_section += f"\n- Dependencies: {', '.join(lib.get('dependencies', []))}"
                if lib.get('patterns'):
                    lib_hints_section += f"\n- Patterns: {'; '.join(lib['patterns'])}"

        if is_empty_repo:
            system_prompt = f"""You are a senior software architect planning a new project.

The repository is EMPTY. You are creating a new project from scratch.
{lib_hints_section}

Think like a project manager:
1. What files need to be created?
2. What is the logical structure?
3. What dependencies are needed?

Output a JSON object:
{{
    "goal": "Brief description (1 sentence)",
    "impact": "major",
    "files_to_create": ["file1.py", "file2.py", "requirements.txt"],
    "steps": [
        {{
            "type": "create_file",
            "description": "Create requirements.txt with dependencies",
            "target_path": "requirements.txt"
        }},
        {{
            "type": "create_file",
            "description": "Create main entry point",
            "target_path": "main.py"
        }}
    ]
}}

Rules:
- NO "explore" or "analyze" steps - the repo is empty, there's nothing to analyze
- Be CONCRETE: specify actual file names and paths
- Use "create_file" type for new files
- Start with requirements.txt or setup files
- Follow the library patterns above
- Keep it focused - 5-10 steps maximum"""
        else:
            system_prompt = """You are a senior software architect planning code modifications.

Repository context:
- Python files: {python_files}
- Test files: {test_files}
- Git status: {git_clean}

Output a JSON object:
{{
    "goal": "Brief description (1 sentence)",
    "impact": "minor" | "moderate" | "major",
    "context_files": ["files to read for context"],
    "files_to_modify": ["existing files to change"],
    "files_to_create": ["new files to add"],
    "steps": [
        {{
            "type": "read_files" | "edit_file" | "create_file" | "run_tests" | "verify",
            "description": "What this step does",
            "target_path": "path/to/file.py"
        }}
    ]
}}

Rules:
- Be CONCRETE: specify actual file names
- Read relevant files first to understand context
- Use "edit_file" for modifications, "create_file" for new files
- End with run_tests or verify step"""

        try:
            # Format context for prompt
            python_files_str = ", ".join(python_files[:10]) or "none"
            test_files = ", ".join(repo_context.get("test_files", [])[:5]) or "none"
            git_status = repo_context.get("git_status")
            git_clean = "clean" if git_status and git_status.clean else "has changes"

            if not is_empty_repo:
                formatted_prompt = system_prompt.format(
                    python_files=python_files_str,
                    test_files=test_files,
                    git_clean=git_clean,
                )
            else:
                formatted_prompt = system_prompt

            response = self._llm.chat_json(
                system=formatted_prompt,
                user=f"Project type: {act.artifact_type or 'software'}\n\nRequest: {request}",
                temperature=0.3,
            )

            plan_data = json.loads(response)
            return self._parse_llm_plan(plan_data)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse LLM plan: %s", e)
            # Fall back to a sensible default for new projects
            if is_empty_repo:
                return self._create_new_project_plan(request, act, repo_context)
            return None
        except Exception as e:
            logger.warning("LLM planning failed: %s", e)
            if is_empty_repo:
                return self._create_new_project_plan(request, act, repo_context)
            return None

    def _parse_llm_plan(self, data: dict[str, Any]) -> CodeTaskPlan:
        """Parse LLM response into a CodeTaskPlan."""
        steps = []
        for step_data in data.get("steps", []):
            step_type_str = step_data.get("type", "analyze")
            try:
                step_type = CodeStepType(step_type_str)
            except ValueError:
                step_type = CodeStepType.ANALYZE

            steps.append(
                CodeStep(
                    id=_generate_step_id(),
                    type=step_type,
                    description=step_data.get("description", ""),
                    target_path=step_data.get("target_path"),
                    command=step_data.get("command"),
                )
            )

        impact_str = data.get("impact", "minor")
        try:
            impact = ImpactLevel(impact_str)
        except ValueError:
            impact = ImpactLevel.MINOR

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=data.get("goal", "Code modification"),
            steps=steps,
            context_files=data.get("context_files", []),
            files_to_modify=data.get("files_to_modify", []),
            files_to_create=data.get("files_to_create", []),
            files_to_delete=data.get("files_to_delete", []),
            estimated_impact=impact,
        )

    def _create_new_project_plan(
        self,
        request: str,
        act: Act,
        repo_context: dict | None = None,
    ) -> CodeTaskPlan:
        """Create a concrete plan for a new project when LLM fails.

        For empty repos, we know what needs to happen:
        1. Create requirements/dependencies
        2. Create main entry point
        3. Create core modules
        4. Verify it runs
        """
        # Extract keywords to guess project type
        request_lower = request.lower()
        repo_context = repo_context or {}

        # Default files for a Python project
        files_to_create = ["requirements.txt", "main.py"]
        steps = []

        # Check for detected libraries
        detected_libs = repo_context.get("detected_libraries", [])

        # Detect game projects (pygame)
        if any(lib["name"] == "pygame" for lib in detected_libs) or "pygame" in request_lower:
            files_to_create = [
                "requirements.txt",
                "main.py",
                "game.py",
                "sprites.py",
            ]
            if "asteroid" in request_lower:
                files_to_create.extend(["ship.py", "asteroid.py", "ui.py"])

        # Create steps for each file
        steps.append(
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.CREATE_FILE,
                description="Create requirements.txt with project dependencies",
                target_path="requirements.txt",
            )
        )

        for file_path in files_to_create[1:]:  # Skip requirements.txt
            steps.append(
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.CREATE_FILE,
                    description=f"Create {file_path}",
                    target_path=file_path,
                )
            )

        # Add verification step
        steps.append(
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.RUN_COMMAND,
                description="Verify project runs without errors",
                command="python main.py --help || python -c 'import main'",
            )
        )

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=request[:200],
            steps=steps,
            files_to_create=files_to_create,
            estimated_impact=ImpactLevel.MAJOR,
        )

    def _create_exploration_plan(
        self,
        request: str,
        act: Act,
    ) -> CodeTaskPlan:
        """Create a fallback plan when LLM is unavailable.

        Since we can't do intelligent planning without an LLM, we create
        a plan that describes the user's goal and signals that detailed
        planning will happen during execution.

        Note: This is a FALLBACK only. The LLM should be configured properly
        for production use.
        """
        # Try to infer what kind of task this is
        request_lower = request.lower()

        # For creation tasks, describe what will be created
        if any(word in request_lower for word in ["make", "create", "build", "implement", "add"]):
            # Extract the main subject/goal from the request
            steps = [
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.CREATE_FILE,
                    description=f"Implement: {request[:100]}",
                    target_path="(to be determined during execution)",
                ),
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.RUN_TESTS,
                    description="Verify implementation works correctly",
                ),
            ]
        else:
            # For modification tasks
            steps = [
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.EDIT_FILE,
                    description=f"Modify code to: {request[:100]}",
                    target_path="(to be determined during execution)",
                ),
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.RUN_TESTS,
                    description="Verify changes work correctly",
                ),
            ]

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=request,
            steps=steps,
            estimated_impact=ImpactLevel.MODERATE,
        )

    def _extract_file_references(self, error_output: str) -> list[str]:
        """Extract file paths mentioned in error output."""
        import re

        # Common patterns for file references in errors
        patterns = [
            r'File "([^"]+\.py)"',  # Python tracebacks
            r"(\S+\.py):\d+",       # file.py:123 format
            r"in (\S+\.py)",        # "in module.py" format
        ]

        files = set()
        for pattern in patterns:
            for match in re.finditer(pattern, error_output):
                file_path = match.group(1)
                # Filter to relative paths within repo
                if not file_path.startswith("/") or "site-packages" not in file_path:
                    # Clean up absolute paths
                    if "/" in file_path:
                        # Try to extract relative path
                        parts = file_path.split("/")
                        if "src" in parts:
                            idx = parts.index("src")
                            file_path = "/".join(parts[idx:])
                        elif "tests" in parts:
                            idx = parts.index("tests")
                            file_path = "/".join(parts[idx:])
                    files.add(file_path)

        return sorted(files)
