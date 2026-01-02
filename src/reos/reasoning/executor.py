"""Execution engine for ReOS reasoning system.

Executes planned steps with monitoring, verification, and rollback capability.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from .planner import TaskPlan, TaskStep, StepStatus, StepType
from .safety import SafetyManager, RiskLevel

logger = logging.getLogger(__name__)


class ExecutionState(Enum):
    """Overall execution state."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"          # Waiting for user input
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class StepResult:
    """Result of executing a single step."""

    step_id: str
    success: bool
    output: str
    error: str | None = None
    duration_seconds: float = 0.0
    needs_user_input: bool = False
    user_prompt: str | None = None


@dataclass
class ExecutionContext:
    """Context maintained during plan execution."""

    plan: TaskPlan
    state: ExecutionState = ExecutionState.IDLE
    current_step: TaskStep | None = None
    step_results: dict[str, StepResult] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Callbacks
    on_step_start: Callable[[TaskStep], None] | None = None
    on_step_complete: Callable[[TaskStep, StepResult], None] | None = None
    on_step_error: Callable[[TaskStep, str], None] | None = None
    on_need_approval: Callable[[TaskStep], bool] | None = None
    on_progress: Callable[[int, int, str], None] | None = None


class ExecutionEngine:
    """Executes task plans with monitoring and rollback.

    Features:
    - Step-by-step execution with verification
    - Automatic rollback on critical failures
    - Progress reporting
    - User approval for risky operations
    - Alternative step execution on failure
    """

    def __init__(
        self,
        safety_manager: SafetyManager,
        tool_executor: Callable[[str, dict], Any] | None = None,
    ) -> None:
        """Initialize the execution engine.

        Args:
            safety_manager: For backups and rollback
            tool_executor: Callback to execute ReOS tools
        """
        self.safety = safety_manager
        self.tool_executor = tool_executor
        self._contexts: dict[str, ExecutionContext] = {}

    def start_execution(
        self,
        plan: TaskPlan,
        callbacks: dict[str, Callable] | None = None,
    ) -> ExecutionContext:
        """Start executing a plan.

        Args:
            plan: The plan to execute
            callbacks: Optional callbacks for progress/approval

        Returns:
            ExecutionContext for tracking
        """
        if not plan.approved:
            raise ValueError("Plan must be approved before execution")

        context = ExecutionContext(plan=plan)

        if callbacks:
            context.on_step_start = callbacks.get("on_step_start")
            context.on_step_complete = callbacks.get("on_step_complete")
            context.on_step_error = callbacks.get("on_step_error")
            context.on_need_approval = callbacks.get("on_need_approval")
            context.on_progress = callbacks.get("on_progress")

        self._contexts[plan.id] = context
        context.state = ExecutionState.RUNNING
        context.start_time = datetime.now()

        logger.info("Started execution of plan: %s", plan.title)
        return context

    def execute_next_step(self, context: ExecutionContext) -> StepResult | None:
        """Execute the next ready step in the plan.

        Args:
            context: The execution context

        Returns:
            StepResult if a step was executed, None if no steps ready
        """
        if context.state not in (ExecutionState.RUNNING, ExecutionState.PAUSED):
            return None

        step = context.plan.get_next_step()
        if not step:
            # Check if we're done
            if context.plan.is_complete():
                context.state = ExecutionState.COMPLETED
                context.end_time = datetime.now()
                logger.info("Plan completed: %s", context.plan.title)
            return None

        context.current_step = step
        step.status = StepStatus.IN_PROGRESS
        step.started_at = datetime.now()

        if context.on_step_start:
            context.on_step_start(step)

        # Report progress
        completed, total = context.plan.get_progress()
        if context.on_progress:
            context.on_progress(completed, total, step.title)

        # Check if approval needed
        if step.risk and step.risk.requires_confirmation:
            if context.on_need_approval:
                approved = context.on_need_approval(step)
                if not approved:
                    step.status = StepStatus.SKIPPED
                    step.completed_at = datetime.now()
                    return StepResult(
                        step_id=step.id,
                        success=True,
                        output="Step skipped by user",
                    )

        # Execute based on step type
        start_time = datetime.now()
        try:
            result = self._execute_step(step, context)
        except Exception as e:
            logger.error("Step execution error: %s", e)
            result = StepResult(
                step_id=step.id,
                success=False,
                output="",
                error=str(e),
            )

        # Calculate duration
        result.duration_seconds = (datetime.now() - start_time).total_seconds()

        # Update step status
        if result.success:
            step.status = StepStatus.COMPLETED
            step.result = result.output
            context.plan.completed_steps.add(step.id)
        else:
            step.status = StepStatus.FAILED
            step.error = result.error
            context.plan.failed_steps.add(step.id)

            # Try alternatives if available
            if step.alternatives:
                alt_result = self._try_alternatives(step, context)
                if alt_result and alt_result.success:
                    result = alt_result
                    step.status = StepStatus.COMPLETED
                    context.plan.completed_steps.add(step.id)
                    context.plan.failed_steps.discard(step.id)

            # Auto-rollback on critical failure
            if step.status == StepStatus.FAILED and step.risk:
                if step.risk.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    self._handle_critical_failure(step, context)

        step.completed_at = datetime.now()
        context.step_results[step.id] = result

        if context.on_step_complete:
            context.on_step_complete(step, result)

        if step.status == StepStatus.FAILED and context.on_step_error:
            context.on_step_error(step, result.error or "Unknown error")

        return result

    def _execute_step(self, step: TaskStep, context: ExecutionContext) -> StepResult:
        """Execute a single step based on its type."""

        if step.step_type == StepType.COMMAND:
            return self._execute_command(step)

        elif step.step_type == StepType.TOOL_CALL:
            return self._execute_tool(step)

        elif step.step_type == StepType.VERIFICATION:
            return self._execute_verification(step, context)

        elif step.step_type == StepType.DIAGNOSTIC:
            return self._execute_diagnostic(step)

        elif step.step_type == StepType.USER_PROMPT:
            return StepResult(
                step_id=step.id,
                success=True,
                output="",
                needs_user_input=True,
                user_prompt=step.action.get("prompt", "Please provide input"),
            )

        else:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error=f"Unknown step type: {step.step_type}",
            )

    def _execute_command(self, step: TaskStep) -> StepResult:
        """Execute a shell command step."""
        command = step.action.get("command", "")
        if not command:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error="No command specified",
            )

        # Create backup if needed
        if step.risk and step.risk.requires_backup:
            for path in step.backup_paths:
                self.safety.backup_file(path)

        # Record action for rollback
        if step.rollback_command:
            self.safety.record_action(
                description=step.title,
                rollback_command=step.rollback_command,
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=step.risk.estimated_duration_seconds * 2 if step.risk else 120,
            )

            return StepResult(
                step_id=step.id,
                success=result.returncode == 0,
                output=result.stdout[:10000] if result.stdout else "",
                error=result.stderr if result.returncode != 0 else None,
            )

        except subprocess.TimeoutExpired:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error="Command timed out",
            )
        except Exception as e:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error=str(e),
            )

    def _execute_tool(self, step: TaskStep) -> StepResult:
        """Execute a ReOS tool step."""
        tool_name = step.action.get("tool", "")
        tool_args = step.action.get("args", {})

        if not tool_name:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error="No tool specified",
            )

        if not self.tool_executor:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error="Tool executor not available",
            )

        try:
            result = self.tool_executor(tool_name, tool_args)
            return StepResult(
                step_id=step.id,
                success=True,
                output=str(result) if result else "",
            )
        except Exception as e:
            return StepResult(
                step_id=step.id,
                success=False,
                output="",
                error=str(e),
            )

    def _execute_verification(self, step: TaskStep, context: ExecutionContext) -> StepResult:
        """Execute a verification step."""
        # Verifications can be commands or tool calls
        if "command" in step.action:
            result = self._execute_command(step)
            # For verification, non-zero exit is not necessarily failure
            # Check output for expected patterns
            expected = step.action.get("expected", None)
            if expected and expected in result.output:
                result.success = True
            return result

        elif "tool" in step.action:
            return self._execute_tool(step)

        else:
            return StepResult(
                step_id=step.id,
                success=True,
                output="Verification passed (no check defined)",
            )

    def _execute_diagnostic(self, step: TaskStep) -> StepResult:
        """Execute a diagnostic step (gather information)."""
        # Diagnostics are usually tool calls or safe commands
        if "tool" in step.action:
            return self._execute_tool(step)
        elif "command" in step.action:
            return self._execute_command(step)
        else:
            return StepResult(
                step_id=step.id,
                success=True,
                output="Diagnostic step (no action)",
            )

    def _try_alternatives(self, step: TaskStep, context: ExecutionContext) -> StepResult | None:
        """Try alternative approaches when a step fails."""
        for i, alt in enumerate(step.alternatives):
            logger.info("Trying alternative %d for step %s", i + 1, step.id)

            alt_step = TaskStep(
                id=f"{step.id}_alt_{i}",
                title=f"{step.title} (alternative {i + 1})",
                description=alt.get("description", step.description),
                step_type=step.step_type,
                action=alt,
            )

            result = self._execute_step(alt_step, context)
            if result.success:
                return result

        return None

    def _handle_critical_failure(self, step: TaskStep, context: ExecutionContext) -> None:
        """Handle a critical step failure with rollback."""
        logger.warning("Critical failure in step: %s", step.title)

        # Attempt automatic rollback
        if step.rollback_command:
            success, message = self.safety.rollback_last()
            if success:
                logger.info("Automatic rollback succeeded: %s", message)
            else:
                logger.error("Automatic rollback failed: %s", message)
                context.state = ExecutionState.FAILED

    def execute_all(self, context: ExecutionContext) -> bool:
        """Execute all steps in sequence.

        Args:
            context: The execution context

        Returns:
            True if all steps completed successfully
        """
        while context.state == ExecutionState.RUNNING:
            result = self.execute_next_step(context)

            if result is None:
                break

            if result.needs_user_input:
                context.state = ExecutionState.PAUSED
                break

            if not result.success:
                step = context.current_step
                if step and step.risk and step.risk.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    context.state = ExecutionState.FAILED
                    break

        return context.plan.is_complete() and not context.plan.has_failed()

    def pause_execution(self, context: ExecutionContext) -> None:
        """Pause execution (e.g., for user input)."""
        context.state = ExecutionState.PAUSED

    def resume_execution(self, context: ExecutionContext, user_input: str | None = None) -> None:
        """Resume paused execution.

        Args:
            context: The execution context
            user_input: Optional user input for prompt steps
        """
        if context.state != ExecutionState.PAUSED:
            return

        # If there was a pending user prompt, store the input
        if user_input and context.current_step:
            context.step_results[context.current_step.id] = StepResult(
                step_id=context.current_step.id,
                success=True,
                output=user_input,
            )
            context.current_step.status = StepStatus.COMPLETED
            context.plan.completed_steps.add(context.current_step.id)

        context.state = ExecutionState.RUNNING

    def abort_execution(self, context: ExecutionContext, rollback: bool = True) -> None:
        """Abort execution and optionally rollback.

        Args:
            context: The execution context
            rollback: Whether to rollback completed steps
        """
        context.state = ExecutionState.FAILED
        context.end_time = datetime.now()

        if rollback:
            # Rollback in reverse order
            while self.safety.get_rollback_stack():
                success, message = self.safety.rollback_last()
                logger.info("Rollback: %s - %s", "success" if success else "failed", message)

            context.state = ExecutionState.ROLLED_BACK

    def get_execution_summary(self, context: ExecutionContext) -> dict[str, Any]:
        """Get a summary of the execution.

        Returns:
            Dictionary with execution summary
        """
        completed, total = context.plan.get_progress()

        duration = None
        if context.start_time:
            end = context.end_time or datetime.now()
            duration = (end - context.start_time).total_seconds()

        return {
            "plan_id": context.plan.id,
            "title": context.plan.title,
            "state": context.state.value,
            "progress": f"{completed}/{total}",
            "duration_seconds": duration,
            "steps_completed": completed,
            "steps_failed": len(context.plan.failed_steps),
            "current_step": context.current_step.title if context.current_step else None,
            "results": {
                step_id: {
                    "success": result.success,
                    "output_preview": result.output[:200] if result.output else "",
                    "error": result.error,
                }
                for step_id, result in context.step_results.items()
            },
        }
