"""Task planning for ReOS reasoning system.

Decomposes complex requests into discrete, verifiable steps with
dependency management and risk assessment.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from .safety import RiskAssessment, RiskLevel, SafetyManager

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a task step."""

    PENDING = "pending"
    READY = "ready"          # Dependencies satisfied
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"      # Dependency failed


class StepType(Enum):
    """Type of step for execution handling."""

    COMMAND = "command"           # Shell command
    TOOL_CALL = "tool_call"       # ReOS tool invocation
    VERIFICATION = "verification"  # Check that something worked
    USER_PROMPT = "user_prompt"   # Need user input
    DIAGNOSTIC = "diagnostic"     # Gather information
    CONDITIONAL = "conditional"   # Branch based on condition


@dataclass
class TaskStep:
    """A single step in a task plan."""

    id: str
    title: str
    description: str
    step_type: StepType
    action: dict[str, Any]  # Tool name + args, or command

    # Dependencies
    depends_on: list[str] = field(default_factory=list)

    # Risk and safety
    risk: RiskAssessment | None = None
    rollback_command: str | None = None
    backup_paths: list[str] = field(default_factory=list)

    # Execution state
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Alternatives if this step fails
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    # Human-readable explanation
    explanation: str = ""

    def is_ready(self, completed_steps: set[str], failed_steps: set[str] | None = None) -> bool:
        """Check if this step's dependencies are satisfied.

        Args:
            completed_steps: Set of step IDs that have completed successfully
            failed_steps: Set of step IDs that have failed (optional)

        Returns:
            True if all dependencies are completed and none have failed
        """
        # If any dependency failed, this step cannot proceed
        if failed_steps and any(dep in failed_steps for dep in self.depends_on):
            return False
        # All dependencies must be completed
        return all(dep in completed_steps for dep in self.depends_on)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "step_type": self.step_type.value,
            "action": self.action,
            "depends_on": list(self.depends_on),
            "risk": self.risk.to_dict() if self.risk else None,
            "rollback_command": self.rollback_command,
            "backup_paths": list(self.backup_paths),
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "alternatives": list(self.alternatives),
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            step_type=StepType(data["step_type"]),
            action=data["action"],
            depends_on=data.get("depends_on", []),
            risk=RiskAssessment.from_dict(data["risk"]) if data.get("risk") else None,
            rollback_command=data.get("rollback_command"),
            backup_paths=data.get("backup_paths", []),
            status=StepStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            alternatives=data.get("alternatives", []),
            explanation=data.get("explanation", ""),
        )


@dataclass
class TaskPlan:
    """A complete plan for executing a complex task."""

    id: str
    title: str
    original_request: str
    created_at: datetime

    steps: list[TaskStep] = field(default_factory=list)

    # Summary information
    total_estimated_duration: int = 0  # seconds
    requires_reboot: bool = False
    highest_risk: RiskLevel = RiskLevel.SAFE

    # User approval
    approved: bool = False
    approved_at: datetime | None = None

    # Execution state
    current_step_index: int = 0
    completed_steps: set[str] = field(default_factory=set)
    failed_steps: set[str] = field(default_factory=set)

    def get_next_step(self) -> TaskStep | None:
        """Get the next step ready for execution.

        Returns the next PENDING step whose dependencies are all completed
        and none have failed. Steps with failed dependencies are marked BLOCKED.
        """
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                # Check if any dependency has failed
                if any(dep in self.failed_steps for dep in step.depends_on):
                    step.status = StepStatus.BLOCKED
                    continue
                # Check if all dependencies are completed
                if step.is_ready(self.completed_steps, self.failed_steps):
                    return step
        return None

    def is_complete(self) -> bool:
        """Check if all steps are done (completed, skipped, or blocked)."""
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.BLOCKED)
            for s in self.steps
        )

    def has_failed(self) -> bool:
        """Check if any critical step has failed."""
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def get_progress(self) -> tuple[int, int]:
        """Get (completed, total) step counts."""
        completed = sum(
            1 for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return completed, len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "id": self.id,
            "title": self.title,
            "original_request": self.original_request,
            "created_at": self.created_at.isoformat(),
            "steps": [step.to_dict() for step in self.steps],
            "total_estimated_duration": self.total_estimated_duration,
            "requires_reboot": self.requires_reboot,
            "highest_risk": self.highest_risk.value,
            "approved": self.approved,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "current_step_index": self.current_step_index,
            "completed_steps": list(self.completed_steps),
            "failed_steps": list(self.failed_steps),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        """Deserialize from dictionary."""
        plan = cls(
            id=data["id"],
            title=data["title"],
            original_request=data["original_request"],
            created_at=datetime.fromisoformat(data["created_at"]),
            steps=[TaskStep.from_dict(s) for s in data.get("steps", [])],
            total_estimated_duration=data.get("total_estimated_duration", 0),
            requires_reboot=data.get("requires_reboot", False),
            highest_risk=RiskLevel(data.get("highest_risk", "safe")),
            approved=data.get("approved", False),
            approved_at=datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None,
            current_step_index=data.get("current_step_index", 0),
            completed_steps=set(data.get("completed_steps", [])),
            failed_steps=set(data.get("failed_steps", [])),
        )
        return plan


# Common task templates for caching
TASK_TEMPLATES = {
    "install_package": {
        "pattern": r"install\s+(\w+)",
        "steps": [
            {
                "id": "update_cache",
                "title": "Update package cache",
                "description": "Refresh package manager cache",
                "step_type": StepType.COMMAND,
                "action": {"command": "{pkg_manager} update"},
                "risk_level": RiskLevel.LOW,
            },
            {
                "id": "install",
                "title": "Install package",
                "description": "Install the requested package",
                "step_type": StepType.COMMAND,
                "action": {"command": "{pkg_manager} install -y {package}"},
                "depends_on": ["update_cache"],
                "risk_level": RiskLevel.MEDIUM,
            },
            {
                "id": "verify",
                "title": "Verify installation",
                "description": "Check that the package is installed",
                "step_type": StepType.VERIFICATION,
                "action": {"tool": "linux_run_command", "args": {"command": "which {package} || dpkg -l {package}"}},
                "depends_on": ["install"],
            },
        ],
    },
    "service_restart": {
        "pattern": r"restart\s+(\w+)\s+service",
        "steps": [
            {
                "id": "check_status",
                "title": "Check current status",
                "description": "Verify service exists and get current state",
                "step_type": StepType.DIAGNOSTIC,
                "action": {"tool": "linux_service_status", "args": {"service_name": "{service}"}},
            },
            {
                "id": "restart",
                "title": "Restart service",
                "description": "Restart the service",
                "step_type": StepType.COMMAND,
                "action": {"command": "sudo systemctl restart {service}"},
                "depends_on": ["check_status"],
                "rollback_command": "sudo systemctl start {service}",
                "risk_level": RiskLevel.MEDIUM,
            },
            {
                "id": "verify",
                "title": "Verify restart",
                "description": "Confirm service is running",
                "step_type": StepType.VERIFICATION,
                "action": {"tool": "linux_service_status", "args": {"service_name": "{service}"}},
                "depends_on": ["restart"],
            },
        ],
    },
    # Docker container operations
    "container_stop": {
        "pattern": r"stop\s+(?:the\s+)?(\S+)\s*container",
        "steps": [
            {
                "id": "list_containers",
                "title": "List running containers",
                "description": "Find the container to stop",
                "step_type": StepType.DIAGNOSTIC,
                "action": {"tool": "linux_containers", "args": {}},
            },
            {
                "id": "stop_container",
                "title": "Stop container",
                "description": "Stop the container: {container}",
                "step_type": StepType.COMMAND,
                "action": {"tool": "linux_run_command", "args": {"command": "docker stop {container}"}},
                "depends_on": ["list_containers"],
                "rollback_command": "docker start {container}",
                "risk_level": RiskLevel.MEDIUM,
            },
        ],
    },
    "container_remove": {
        "pattern": r"(?:remove|delete|rm)\s+(?:the\s+)?(\S+)\s*container",
        "steps": [
            {
                "id": "list_containers",
                "title": "List containers",
                "description": "Find the container to remove",
                "step_type": StepType.DIAGNOSTIC,
                "action": {"tool": "linux_containers", "args": {}},
            },
            {
                "id": "stop_container",
                "title": "Stop container (if running)",
                "description": "Stop the container before removing: {container}",
                "step_type": StepType.COMMAND,
                "action": {"tool": "linux_run_command", "args": {"command": "docker stop {container} 2>/dev/null || true"}},
                "depends_on": ["list_containers"],
                "risk_level": RiskLevel.MEDIUM,
            },
            {
                "id": "remove_container",
                "title": "Remove container",
                "description": "Remove the container: {container}",
                "step_type": StepType.COMMAND,
                "action": {"tool": "linux_run_command", "args": {"command": "docker rm {container}"}},
                "depends_on": ["stop_container"],
                "risk_level": RiskLevel.HIGH,
            },
        ],
    },
    "container_stop_remove": {
        "pattern": r"stop\s+(?:and\s+)?(?:remove|delete)\s+(?:the\s+)?(\S+)\s*container",
        "steps": [
            {
                "id": "list_containers",
                "title": "List running containers",
                "description": "Find the container",
                "step_type": StepType.DIAGNOSTIC,
                "action": {"tool": "linux_containers", "args": {}},
            },
            {
                "id": "stop_container",
                "title": "Stop container",
                "description": "Stop the container: {container}",
                "step_type": StepType.COMMAND,
                "action": {"tool": "linux_run_command", "args": {"command": "docker stop {container}"}},
                "depends_on": ["list_containers"],
                "rollback_command": "docker start {container}",
                "risk_level": RiskLevel.MEDIUM,
            },
            {
                "id": "remove_container",
                "title": "Remove container",
                "description": "Remove the container: {container}",
                "step_type": StepType.COMMAND,
                "action": {"tool": "linux_run_command", "args": {"command": "docker rm {container}"}},
                "depends_on": ["stop_container"],
                "risk_level": RiskLevel.HIGH,
            },
        ],
    },
}


class TaskPlanner:
    """Plans multi-step tasks for complex requests.

    Uses LLM for decomposition with templates for common operations.
    """

    def __init__(
        self,
        safety_manager: SafetyManager,
        llm_planner: Callable[[str, dict], list[dict]] | None = None,
    ) -> None:
        """Initialize the task planner.

        Args:
            safety_manager: For risk assessment and backup management
            llm_planner: Optional callback to use LLM for planning
        """
        self.safety = safety_manager
        self.llm_planner = llm_planner
        self._step_counter = 0

    def _next_step_id(self) -> str:
        """Generate unique step ID."""
        self._step_counter += 1
        return f"step_{self._step_counter}"

    def create_plan(
        self,
        request: str,
        system_context: dict[str, Any] | None = None,
    ) -> TaskPlan:
        """Create a task plan for a complex request.

        Args:
            request: The user's request
            system_context: Current system state information

        Returns:
            TaskPlan with steps to execute
        """
        import hashlib

        plan = TaskPlan(
            id=hashlib.sha256(f"{datetime.now().isoformat()}{request}".encode()).hexdigest()[:12],
            title=self._generate_title(request),
            original_request=request,
            created_at=datetime.now(),
        )

        # Prefer LLM planner for intelligent intent parsing with system context
        # LLM understands natural language variations and can match against
        # actual system state (containers, services, packages)
        if self.llm_planner:
            llm_steps = self.llm_planner(request, system_context or {})
            if llm_steps:
                logger.debug("Using LLM planner: %d steps generated", len(llm_steps))
                plan.steps = self._parse_llm_steps(llm_steps)
            else:
                # LLM failed or low confidence - fall back to templates/regex
                logger.debug("LLM planner returned no steps, falling back")
                plan.steps = self._fallback_plan(request, system_context)
        else:
            # No LLM available - use templates and regex fallback
            plan.steps = self._fallback_plan(request, system_context)

        # Assess risks for all steps
        self._assess_plan_risks(plan)

        return plan

    def _generate_title(self, request: str) -> str:
        """Generate a short title for the plan."""
        words = request.split()[:6]
        title = " ".join(words)
        if len(request.split()) > 6:
            title += "..."
        return title.capitalize()

    def _fallback_plan(
        self,
        request: str,
        system_context: dict[str, Any] | None = None,
    ) -> list[TaskStep]:
        """Fallback planning when LLM is unavailable or fails.

        Tries templates first, then regex-based intent parsing.
        """
        # Try templates
        template_plan = self._try_template_match(request, system_context or {})
        if template_plan:
            logger.debug("Using template-based plan")
            return template_plan

        # Fall back to regex-based intent parsing
        logger.debug("Using regex fallback plan")
        return self._create_fallback_plan(request, system_context)

    def _try_template_match(
        self,
        request: str,
        context: dict[str, Any],
    ) -> list[TaskStep] | None:
        """Try to match request against known templates."""
        import re

        request_lower = request.lower()

        for template_name, template in TASK_TEMPLATES.items():
            match = re.search(template["pattern"], request_lower)
            if match:
                logger.debug("Matched template: %s", template_name)
                return self._instantiate_template(template, match.groups(), context)

        return None

    def _instantiate_template(
        self,
        template: dict,
        captures: tuple,
        context: dict[str, Any],
    ) -> list[TaskStep]:
        """Create steps from a template with variable substitution."""
        # Build substitution context
        subs = dict(context)

        # Add captured groups - use first capture for common variable names
        if captures:
            first_capture = captures[0]
            if "package" not in subs:
                subs["package"] = first_capture
            if "service" not in subs:
                # Try to resolve service name from system context
                subs["service"] = self._resolve_service_name(first_capture, context)
            if "container" not in subs:
                # Try to resolve container name from system context
                subs["container"] = self._resolve_container_name(first_capture, context)

        # Detect package manager if needed
        if "pkg_manager" not in subs:
            # Use package manager from context if available
            subs["pkg_manager"] = context.get("package_manager") or self._detect_pkg_manager()

        steps = []
        for step_def in template["steps"]:
            description = self._substitute(step_def["description"], subs)
            step = TaskStep(
                id=step_def.get("id", self._next_step_id()),
                title=self._substitute(step_def["title"], subs),
                description=description,
                step_type=step_def["step_type"],
                action=self._substitute_dict(step_def["action"], subs),
                depends_on=step_def.get("depends_on", []),
                rollback_command=self._substitute(step_def.get("rollback_command", ""), subs) or None,
                explanation=f"This step will {description.lower()}",
            )
            steps.append(step)

        return steps

    def _substitute(self, text: str, subs: dict[str, str], shell_escape: bool = False) -> str:
        """Substitute {variables} in text.

        Args:
            text: Text with {variable} placeholders
            subs: Substitution mapping
            shell_escape: If True, escape values for safe shell usage
        """
        for key, value in subs.items():
            safe_value = shlex.quote(str(value)) if shell_escape else str(value)
            text = text.replace(f"{{{key}}}", safe_value)
        return text

    def _substitute_dict(self, d: dict, subs: dict[str, str]) -> dict:
        """Recursively substitute variables in a dict.

        Uses shell escaping for 'command' keys to prevent injection.
        """
        result = {}
        for key, value in d.items():
            if isinstance(value, str):
                # Shell-escape values in command strings to prevent injection
                shell_escape = key == "command"
                result[key] = self._substitute(value, subs, shell_escape=shell_escape)
            elif isinstance(value, dict):
                result[key] = self._substitute_dict(value, subs)
            else:
                result[key] = value
        return result

    def _detect_pkg_manager(self) -> str:
        """Detect the system's package manager."""
        import os

        if os.path.exists("/usr/bin/apt"):
            return "sudo apt"
        elif os.path.exists("/usr/bin/dnf"):
            return "sudo dnf"
        elif os.path.exists("/usr/bin/pacman"):
            return "sudo pacman -S"
        elif os.path.exists("/usr/bin/zypper"):
            return "sudo zypper"
        return "sudo apt"  # Default fallback

    def _parse_llm_steps(self, llm_steps: list[dict]) -> list[TaskStep]:
        """Parse steps from LLM response.

        Handles action format conversion:
        - If action has 'tool: linux_run_command' with args.command, extract as COMMAND type
        - Other tools become TOOL_CALL type
        """
        steps = []
        for i, step_data in enumerate(llm_steps):
            # Determine step type based on explicit type or action structure
            step_type = StepType.COMMAND
            if step_data.get("type") == "verify":
                step_type = StepType.VERIFICATION
            elif step_data.get("type") == "diagnostic":
                step_type = StepType.DIAGNOSTIC
            elif step_data.get("type") == "prompt":
                step_type = StepType.USER_PROMPT

            # Convert action format to match executor expectations
            raw_action = step_data.get("action", {})
            action: dict[str, Any] = {}

            # Handle LLM-generated tool actions
            if isinstance(raw_action, dict) and "tool" in raw_action:
                tool_name = raw_action.get("tool", "")
                tool_args = raw_action.get("args", {})

                if tool_name == "linux_run_command" and "command" in tool_args:
                    # Extract command for direct execution
                    action = {"command": tool_args["command"]}
                    step_type = StepType.COMMAND
                else:
                    # Use as tool call
                    action = {"tool": tool_name, "args": tool_args}
                    step_type = StepType.TOOL_CALL
            elif isinstance(raw_action, dict) and "command" in raw_action:
                # Already in correct format
                action = raw_action
                step_type = StepType.COMMAND
            else:
                action = raw_action

            step = TaskStep(
                id=step_data.get("id", f"llm_step_{i}"),
                title=step_data.get("title", f"Step {i + 1}"),
                description=step_data.get("description", ""),
                step_type=step_type,
                action=action,
                depends_on=step_data.get("depends_on", []),
                rollback_command=step_data.get("rollback"),
                explanation=step_data.get("explanation", ""),
            )
            steps.append(step)

        return steps

    def _create_fallback_plan(self, request: str, context: dict[str, Any] | None = None) -> list[TaskStep]:
        """Create a goal-oriented plan based on intent parsing.

        Instead of useless diagnostic steps, this parses the user's intent
        and creates steps that actually accomplish the goal.
        """
        context = context or {}
        intent = self._parse_intent(request)

        if not intent:
            # Truly ambiguous - need clarification
            return [
                TaskStep(
                    id="clarify",
                    title="Need clarification",
                    description="I couldn't determine what action you want to take",
                    step_type=StepType.USER_PROMPT,
                    action={"prompt": f"Could you clarify what you'd like me to do? Request was: {request}"},
                    explanation="I need more details to create an actionable plan",
                ),
            ]

        action = intent["action"]
        resource_type = intent["resource_type"]
        filter_term = intent.get("filter")

        # Generate plan based on intent
        if resource_type == "container":
            return self._plan_container_action(action, filter_term, context)
        elif resource_type == "service":
            return self._plan_service_action(action, filter_term, context)
        elif resource_type == "package":
            return self._plan_package_action(action, filter_term, context)
        else:
            # Generic command execution
            return self._plan_generic_action(request, context)

    def _parse_intent(self, request: str) -> dict[str, Any] | None:
        """Parse user intent: action + resource type + optional filter.

        Examples:
            "remove all nextcloud containers" -> {action: "remove", resource_type: "container", filter: "nextcloud"}
            "stop the redis service" -> {action: "stop", resource_type: "service", filter: "redis"}
            "install nginx" -> {action: "install", resource_type: "package", filter: "nginx"}
        """
        import re
        request_lower = request.lower()

        # Container actions
        container_match = re.search(
            r"\b(stop|remove|delete|rm|kill|restart|start)\b.*?\b(all\s+)?(\w+)?\s*containers?\b",
            request_lower,
        )
        if container_match:
            action = container_match.group(1)
            if action in ("delete", "rm"):
                action = "remove"
            filter_term = container_match.group(3)
            return {"action": action, "resource_type": "container", "filter": filter_term}

        # Also match "containers" before action: "nextcloud containers remove"
        container_match2 = re.search(
            r"\b(\w+)\s+containers?\s+(stop|remove|delete|rm|kill|restart|start)\b",
            request_lower,
        )
        if container_match2:
            filter_term = container_match2.group(1)
            action = container_match2.group(2)
            if action in ("delete", "rm"):
                action = "remove"
            return {"action": action, "resource_type": "container", "filter": filter_term}

        # Service actions
        service_match = re.search(
            r"\b(stop|start|restart|enable|disable|status)\b.*?\b(\w+)?\s*services?\b",
            request_lower,
        )
        if service_match:
            return {
                "action": service_match.group(1),
                "resource_type": "service",
                "filter": service_match.group(2),
            }

        # Also: "restart nginx" / "stop docker"
        service_match2 = re.search(
            r"\b(restart|stop|start|enable|disable)\s+(\w+)\b",
            request_lower,
        )
        if service_match2:
            action = service_match2.group(1)
            target = service_match2.group(2)
            # Heuristic: if target looks like a service name
            if target not in ("all", "the", "my", "this"):
                return {"action": action, "resource_type": "service", "filter": target}

        # Package actions
        package_match = re.search(
            r"\b(install|remove|uninstall|update|upgrade)\s+(\w+)\b",
            request_lower,
        )
        if package_match:
            action = package_match.group(1)
            if action == "uninstall":
                action = "remove"
            return {
                "action": action,
                "resource_type": "package",
                "filter": package_match.group(2),
            }

        return None

    def _plan_container_action(
        self,
        action: str,
        filter_term: str | None,
        context: dict[str, Any],
    ) -> list[TaskStep]:
        """Create plan for container operations."""
        container_names = context.get("container_names", [])

        # Find matching containers
        if filter_term:
            matching = [
                name for name in container_names
                if filter_term.lower() in name.lower()
            ]
        else:
            matching = list(container_names)

        if not matching and filter_term:
            # No matches found
            return [
                TaskStep(
                    id="no_match",
                    title=f"No containers matching '{filter_term}'",
                    description=f"Could not find any containers matching '{filter_term}'",
                    step_type=StepType.USER_PROMPT,
                    action={"prompt": f"No containers found matching '{filter_term}'. Available: {container_names}"},
                    explanation=f"I couldn't find containers matching '{filter_term}'",
                ),
            ]

        steps = []

        # Create steps for each matching container
        for i, container in enumerate(matching):
            step_id = f"{action}_{i}"

            if action == "stop":
                steps.append(TaskStep(
                    id=step_id,
                    title=f"Stop {container}",
                    description=f"Stop container: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker stop {shlex.quote(container)}"}},
                    rollback_command=f"docker start {shlex.quote(container)}",
                    explanation=f"Stop the {container} container",
                ))
            elif action == "remove":
                # Stop first, then remove
                stop_id = f"stop_{i}"
                steps.append(TaskStep(
                    id=stop_id,
                    title=f"Stop {container}",
                    description=f"Stop container before removal: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker stop {shlex.quote(container)} 2>/dev/null || true"}},
                    explanation=f"Stop {container} before removing it",
                ))
                steps.append(TaskStep(
                    id=step_id,
                    title=f"Remove {container}",
                    description=f"Remove container: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker rm {shlex.quote(container)}"}},
                    depends_on=[stop_id],
                    explanation=f"Remove the {container} container",
                ))
            elif action == "restart":
                steps.append(TaskStep(
                    id=step_id,
                    title=f"Restart {container}",
                    description=f"Restart container: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker restart {shlex.quote(container)}"}},
                    explanation=f"Restart the {container} container",
                ))
            elif action == "start":
                steps.append(TaskStep(
                    id=step_id,
                    title=f"Start {container}",
                    description=f"Start container: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker start {shlex.quote(container)}"}},
                    explanation=f"Start the {container} container",
                ))
            elif action == "kill":
                steps.append(TaskStep(
                    id=step_id,
                    title=f"Kill {container}",
                    description=f"Force kill container: {container}",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"docker kill {shlex.quote(container)}"}},
                    rollback_command=f"docker start {shlex.quote(container)}",
                    explanation=f"Force kill the {container} container",
                ))

        return steps

    def _plan_service_action(
        self,
        action: str,
        filter_term: str | None,
        context: dict[str, Any],
    ) -> list[TaskStep]:
        """Create plan for service operations."""
        service_names = context.get("service_names", [])

        # Resolve service name
        if filter_term:
            resolved = self._resolve_service_name(filter_term, context)
        else:
            resolved = filter_term

        steps = []

        if action in ("stop", "start", "restart", "enable", "disable"):
            steps.append(TaskStep(
                id=f"{action}_service",
                title=f"{action.capitalize()} {resolved}",
                description=f"{action.capitalize()} the {resolved} service",
                step_type=StepType.COMMAND,
                action={"tool": "linux_run_command", "args": {"command": f"sudo systemctl {action} {shlex.quote(resolved)}"}},
                explanation=f"{action.capitalize()} the {resolved} service using systemctl",
            ))
            # Add verification step
            steps.append(TaskStep(
                id="verify_service",
                title=f"Verify {resolved} status",
                description=f"Check the status of {resolved}",
                step_type=StepType.VERIFICATION,
                action={"tool": "linux_service_status", "args": {"service_name": resolved}},
                depends_on=[f"{action}_service"],
                explanation=f"Verify that {resolved} is in the expected state",
            ))
        elif action == "status":
            steps.append(TaskStep(
                id="check_status",
                title=f"Check {resolved} status",
                description=f"Get status of {resolved}",
                step_type=StepType.DIAGNOSTIC,
                action={"tool": "linux_service_status", "args": {"service_name": resolved}},
                explanation=f"Check the current status of {resolved}",
            ))

        return steps

    def _plan_package_action(
        self,
        action: str,
        package: str | None,
        context: dict[str, Any],
    ) -> list[TaskStep]:
        """Create plan for package operations."""
        pkg_manager = context.get("package_manager") or self._detect_pkg_manager()

        steps = []

        if action == "install":
            steps.append(TaskStep(
                id="update_cache",
                title="Update package cache",
                description="Refresh package manager cache",
                step_type=StepType.COMMAND,
                action={"tool": "linux_run_command", "args": {"command": f"{pkg_manager} update"}},
                explanation="Update package lists to get latest versions",
            ))
            steps.append(TaskStep(
                id="install_package",
                title=f"Install {package}",
                description=f"Install the {package} package",
                step_type=StepType.COMMAND,
                action={"tool": "linux_run_command", "args": {"command": f"{pkg_manager} install -y {shlex.quote(package)}"}},
                depends_on=["update_cache"],
                explanation=f"Install {package} using {pkg_manager}",
            ))
        elif action == "remove":
            steps.append(TaskStep(
                id="remove_package",
                title=f"Remove {package}",
                description=f"Remove the {package} package",
                step_type=StepType.COMMAND,
                action={"tool": "linux_run_command", "args": {"command": f"{pkg_manager} remove -y {shlex.quote(package)}"}},
                explanation=f"Remove {package} using {pkg_manager}",
            ))
        elif action in ("update", "upgrade"):
            if package:
                steps.append(TaskStep(
                    id="upgrade_package",
                    title=f"Upgrade {package}",
                    description=f"Upgrade the {package} package",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"{pkg_manager} install --only-upgrade -y {shlex.quote(package)}"}},
                    explanation=f"Upgrade {package} to the latest version",
                ))
            else:
                steps.append(TaskStep(
                    id="upgrade_all",
                    title="Upgrade all packages",
                    description="Upgrade all installed packages",
                    step_type=StepType.COMMAND,
                    action={"tool": "linux_run_command", "args": {"command": f"{pkg_manager} upgrade -y"}},
                    explanation="Upgrade all packages to their latest versions",
                ))

        return steps

    def _plan_generic_action(self, request: str, context: dict[str, Any]) -> list[TaskStep]:
        """Create a generic plan when intent is unclear but request is actionable."""
        # For truly unknown requests, provide a helpful response
        return [
            TaskStep(
                id="clarify",
                title="Need more details",
                description=f"I understand you want to: {request}",
                step_type=StepType.USER_PROMPT,
                action={"prompt": f"I'd like to help with: '{request}'. Could you be more specific about what action you'd like me to take?"},
                explanation="I need a bit more detail to create an actionable plan",
            ),
        ]

    def _assess_plan_risks(self, plan: TaskPlan) -> None:
        """Assess risks for all steps in a plan."""
        total_duration = 0
        highest_risk = RiskLevel.SAFE

        for step in plan.steps:
            if step.step_type == StepType.COMMAND:
                command = step.action.get("command", "")
                step.risk = self.safety.assess_command_risk(command)
                total_duration += step.risk.estimated_duration_seconds

                if step.risk.level > highest_risk:
                    highest_risk = step.risk.level

                if step.risk.requires_reboot:
                    plan.requires_reboot = True

        plan.total_estimated_duration = total_duration
        plan.highest_risk = highest_risk

    def add_step(
        self,
        plan: TaskPlan,
        title: str,
        action: dict[str, Any],
        step_type: StepType = StepType.COMMAND,
        depends_on: list[str] | None = None,
        explanation: str = "",
    ) -> TaskStep:
        """Add a step to an existing plan.

        Args:
            plan: The plan to modify
            title: Step title
            action: Step action (command or tool call)
            step_type: Type of step
            depends_on: Dependencies
            explanation: Human-readable explanation

        Returns:
            The created step
        """
        step = TaskStep(
            id=self._next_step_id(),
            title=title,
            description=explanation or title,
            step_type=step_type,
            action=action,
            depends_on=depends_on or [],
            explanation=explanation,
        )

        if step_type == StepType.COMMAND:
            step.risk = self.safety.assess_command_risk(action.get("command", ""))

        plan.steps.append(step)
        self._assess_plan_risks(plan)  # Re-assess totals

        return step

    def get_plan_summary(self, plan: TaskPlan) -> dict[str, Any]:
        """Get a summary of the plan for display.

        Returns:
            Dictionary with plan summary suitable for natural language output
        """
        return {
            "title": plan.title,
            "step_count": len(plan.steps),
            "estimated_duration_minutes": round(plan.total_estimated_duration / 60, 1),
            "requires_reboot": plan.requires_reboot,
            "highest_risk": plan.highest_risk.value,
            "steps": [
                {
                    "number": i + 1,
                    "title": s.title,
                    "explanation": s.explanation or s.description,
                    "risk": s.risk.level.value if s.risk else "safe",
                    "reversible": s.risk.reversible if s.risk else True,
                }
                for i, s in enumerate(plan.steps)
            ],
        }

    def _resolve_container_name(self, user_ref: str, context: dict[str, Any]) -> str:
        """Resolve a user's container reference to an actual container name.

        Matches user input like "redis" to actual container names like "nextcloud-redis".
        Uses fuzzy matching: substring, prefix, suffix.

        Args:
            user_ref: User's reference (e.g., "redis", "nextcloud")
            context: System context with container_names list

        Returns:
            Resolved container name, or original reference if no match
        """
        container_names = context.get("container_names", [])
        if not container_names:
            return user_ref

        user_ref_lower = user_ref.lower()

        # Exact match first
        for name in container_names:
            if name.lower() == user_ref_lower:
                return name

        # Substring match (e.g., "redis" matches "nextcloud-redis")
        matches = [name for name in container_names if user_ref_lower in name.lower()]
        if len(matches) == 1:
            logger.debug("Resolved container '%s' -> '%s'", user_ref, matches[0])
            return matches[0]
        elif len(matches) > 1:
            # Multiple matches - log and return first
            logger.debug(
                "Multiple containers match '%s': %s, using first",
                user_ref,
                matches,
            )
            return matches[0]

        # Prefix match (e.g., "next" matches "nextcloud")
        prefix_matches = [name for name in container_names if name.lower().startswith(user_ref_lower)]
        if prefix_matches:
            return prefix_matches[0]

        # No match found
        logger.debug("No container match for '%s' in %s", user_ref, container_names)
        return user_ref

    def _resolve_service_name(self, user_ref: str, context: dict[str, Any]) -> str:
        """Resolve a user's service reference to an actual service name.

        Matches user input like "nginx" to actual service names like "nginx.service".

        Args:
            user_ref: User's reference (e.g., "nginx", "docker")
            context: System context with service_names list

        Returns:
            Resolved service name, or original reference if no match
        """
        service_names = context.get("service_names", [])
        if not service_names:
            return user_ref

        user_ref_lower = user_ref.lower()

        # Exact match first
        for name in service_names:
            if name.lower() == user_ref_lower:
                return name

        # Strip .service suffix for matching
        normalized_services = {
            name.replace(".service", "").lower(): name
            for name in service_names
        }

        # Check against normalized names
        if user_ref_lower in normalized_services:
            return normalized_services[user_ref_lower]

        # Substring match
        matches = [
            name for name in service_names
            if user_ref_lower in name.lower().replace(".service", "")
        ]
        if len(matches) == 1:
            logger.debug("Resolved service '%s' -> '%s'", user_ref, matches[0])
            return matches[0]
        elif len(matches) > 1:
            logger.debug(
                "Multiple services match '%s': %s, using first",
                user_ref,
                matches,
            )
            return matches[0]

        # No match found
        logger.debug("No service match for '%s' in %s", user_ref, service_names)
        return user_ref
