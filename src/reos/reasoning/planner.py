"""Task planning for ReOS reasoning system.

Decomposes complex requests into discrete, verifiable steps with
dependency management and risk assessment.
"""

from __future__ import annotations

import logging
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

    def is_ready(self, completed_steps: set[str]) -> bool:
        """Check if this step's dependencies are satisfied."""
        return all(dep in completed_steps for dep in self.depends_on)


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
        """Get the next step ready for execution."""
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                if step.is_ready(self.completed_steps):
                    return step
        return None

    def is_complete(self) -> bool:
        """Check if all steps are done (completed or skipped)."""
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
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

        # Try templates first
        template_plan = self._try_template_match(request, system_context or {})
        if template_plan:
            plan.steps = template_plan
        elif self.llm_planner:
            # Use LLM for custom planning
            llm_steps = self.llm_planner(request, system_context or {})
            plan.steps = self._parse_llm_steps(llm_steps)
        else:
            # Fallback: create a basic diagnostic plan
            plan.steps = self._create_fallback_plan(request)

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

        # Add captured groups
        if "package" not in subs and captures:
            subs["package"] = captures[0]
        if "service" not in subs and captures:
            subs["service"] = captures[0]

        # Detect package manager if needed
        if "pkg_manager" not in subs:
            subs["pkg_manager"] = self._detect_pkg_manager()

        steps = []
        for step_def in template["steps"]:
            step = TaskStep(
                id=step_def.get("id", self._next_step_id()),
                title=self._substitute(step_def["title"], subs),
                description=self._substitute(step_def["description"], subs),
                step_type=step_def["step_type"],
                action=self._substitute_dict(step_def["action"], subs),
                depends_on=step_def.get("depends_on", []),
                rollback_command=self._substitute(step_def.get("rollback_command", ""), subs) or None,
                explanation=f"This step will {step_def['description'].lower()}",
            )
            steps.append(step)

        return steps

    def _substitute(self, text: str, subs: dict[str, str]) -> str:
        """Substitute {variables} in text."""
        for key, value in subs.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text

    def _substitute_dict(self, d: dict, subs: dict[str, str]) -> dict:
        """Recursively substitute variables in a dict."""
        result = {}
        for key, value in d.items():
            if isinstance(value, str):
                result[key] = self._substitute(value, subs)
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
        """Parse steps from LLM response."""
        steps = []
        for i, step_data in enumerate(llm_steps):
            step_type = StepType.COMMAND
            if step_data.get("type") == "verify":
                step_type = StepType.VERIFICATION
            elif step_data.get("type") == "diagnostic":
                step_type = StepType.DIAGNOSTIC
            elif step_data.get("type") == "prompt":
                step_type = StepType.USER_PROMPT

            step = TaskStep(
                id=step_data.get("id", f"llm_step_{i}"),
                title=step_data.get("title", f"Step {i + 1}"),
                description=step_data.get("description", ""),
                step_type=step_type,
                action=step_data.get("action", {}),
                depends_on=step_data.get("depends_on", []),
                rollback_command=step_data.get("rollback"),
                explanation=step_data.get("explanation", ""),
            )
            steps.append(step)

        return steps

    def _create_fallback_plan(self, request: str) -> list[TaskStep]:
        """Create a basic diagnostic plan when no template matches."""
        return [
            TaskStep(
                id="gather_info",
                title="Gather system information",
                description="Collect relevant system state",
                step_type=StepType.DIAGNOSTIC,
                action={"tool": "linux_system_info", "args": {}},
                explanation="First, let's understand your current system state",
            ),
            TaskStep(
                id="analyze",
                title="Analyze request",
                description="Determine specific actions needed",
                step_type=StepType.USER_PROMPT,
                action={"prompt": f"Based on the system info, what specific steps are needed for: {request}"},
                depends_on=["gather_info"],
                explanation="I'll analyze what needs to be done based on your system",
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

                if step.risk.level.value > highest_risk.value:
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
