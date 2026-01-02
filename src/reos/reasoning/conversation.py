"""Natural language conversation manager for ReOS.

Translates technical operations into friendly, natural language
while adapting to user preferences for verbosity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .planner import TaskPlan, TaskStep, StepStatus
from .executor import ExecutionContext, ExecutionState, StepResult
from .safety import RiskLevel

logger = logging.getLogger(__name__)


class VerbosityLevel(Enum):
    """How detailed responses should be."""

    MINIMAL = "minimal"    # Just results, no explanations
    NORMAL = "normal"      # Balanced explanations
    DETAILED = "detailed"  # Full step-by-step with reasoning


@dataclass
class ConversationPreferences:
    """User preferences for conversation style."""

    verbosity: VerbosityLevel = VerbosityLevel.NORMAL
    use_technical_terms: bool = True
    show_commands: bool = True  # Show actual commands being run
    show_progress: bool = True
    friendly_tone: bool = True


class ConversationManager:
    """Manages natural language output for ReOS reasoning system.

    Principles:
    - Feel like talking to a knowledgeable sysadmin friend
    - Never be robotic or use ALL CAPS status messages
    - Adapt to user's technical level over time
    - Be concise but not cryptic
    """

    def __init__(self, preferences: ConversationPreferences | None = None) -> None:
        """Initialize the conversation manager.

        Args:
            preferences: User preferences for output style
        """
        self.prefs = preferences or ConversationPreferences()

    def format_complexity_result(self, level: str, request: str) -> str:
        """Format the complexity assessment naturally.

        This is used when deciding whether to plan or execute directly.
        """
        if level == "simple":
            # Don't mention it's simple, just do it
            return ""

        if level == "diagnostic":
            return "Let me check what's going on first..."

        if level == "complex":
            phrases = [
                "This will take a few steps. Let me plan it out...",
                "Okay, this needs some planning. Here's what I'm thinking...",
                "Let me break this down into steps for you...",
            ]
            return phrases[hash(request) % len(phrases)]

        if level == "risky":
            return "This involves some system changes. Let me show you exactly what I'll do before we proceed."

        return ""

    def format_plan_presentation(self, plan: TaskPlan) -> str:
        """Format a plan for user approval in natural language."""
        lines = []

        # Opening - conversational
        if plan.highest_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            lines.append(f"Here's what I'll do for \"{plan.original_request}\":\n")
        else:
            lines.append(f"Alright, here's the plan:\n")

        # Steps - numbered but natural
        for i, step in enumerate(plan.steps, 1):
            prefix = f"{i}. "

            if self.prefs.verbosity == VerbosityLevel.MINIMAL:
                lines.append(f"{prefix}{step.title}")
            else:
                # Include explanation
                desc = step.explanation or step.description
                lines.append(f"{prefix}{step.title}")
                if desc and desc != step.title:
                    lines.append(f"   {desc}")

                # Show command if enabled
                if self.prefs.show_commands and step.action.get("command"):
                    cmd = step.action["command"]
                    lines.append(f"   → `{cmd}`")

                # Risk warning
                if step.risk and step.risk.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    lines.append(f"   ⚠️  {', '.join(step.risk.reasons)}")

        lines.append("")

        # Summary footer
        duration = plan.total_estimated_duration
        if duration < 60:
            time_str = f"about {duration} seconds"
        else:
            time_str = f"about {duration // 60} minute{'s' if duration >= 120 else ''}"

        lines.append(f"This should take {time_str}.")

        if plan.requires_reboot:
            lines.append("Note: You'll need to reboot after this.")

        if plan.highest_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            lines.append("\n⚠️  This includes some system changes. I'll create backups first.")

        lines.append("\nWant me to go ahead?")

        return "\n".join(lines)

    def format_step_start(self, step: TaskStep, progress: tuple[int, int]) -> str:
        """Format a step starting message."""
        completed, total = progress

        if self.prefs.verbosity == VerbosityLevel.MINIMAL:
            return ""

        if self.prefs.verbosity == VerbosityLevel.NORMAL:
            return f"[{completed + 1}/{total}] {step.title}..."

        # Detailed
        lines = [f"\n[{completed + 1}/{total}] {step.title}"]
        if step.explanation:
            lines.append(f"  {step.explanation}")
        if self.prefs.show_commands and step.action.get("command"):
            lines.append(f"  Running: `{step.action['command']}`")
        return "\n".join(lines)

    def format_step_complete(self, step: TaskStep, result: StepResult) -> str:
        """Format a step completion message."""
        if self.prefs.verbosity == VerbosityLevel.MINIMAL:
            return ""

        if result.success:
            check = "✓" if self.prefs.friendly_tone else "OK"

            if self.prefs.verbosity == VerbosityLevel.NORMAL:
                return f"  {check} Done"

            # Detailed - include output preview
            lines = [f"  {check} {step.title} completed"]
            if result.output and len(result.output) < 200:
                lines.append(f"  Output: {result.output.strip()}")
            return "\n".join(lines)

        else:
            cross = "✗" if self.prefs.friendly_tone else "FAILED"
            lines = [f"  {cross} {step.title} failed"]
            if result.error:
                lines.append(f"  Error: {result.error}")
            return "\n".join(lines)

    def format_execution_complete(self, context: ExecutionContext) -> str:
        """Format the final execution summary."""
        lines = []

        if context.state == ExecutionState.COMPLETED:
            if self.prefs.verbosity == VerbosityLevel.MINIMAL:
                return "Done."

            lines.append("All done! ✓")

            # Summary of what was accomplished
            completed, total = context.plan.get_progress()
            if completed == total:
                lines.append(f"Completed all {total} steps successfully.")
            else:
                lines.append(f"Completed {completed} of {total} steps.")

            # Duration
            if context.start_time and context.end_time:
                duration = (context.end_time - context.start_time).total_seconds()
                if duration < 60:
                    lines.append(f"Took {duration:.1f} seconds.")
                else:
                    lines.append(f"Took {duration / 60:.1f} minutes.")

        elif context.state == ExecutionState.FAILED:
            lines.append("Ran into a problem.")

            # Show which step failed
            for step_id, result in context.step_results.items():
                if not result.success:
                    lines.append(f"Failed at: {step_id}")
                    if result.error:
                        lines.append(f"Error: {result.error}")
                    break

            lines.append("\nI've kept backups of anything that was changed.")

        elif context.state == ExecutionState.ROLLED_BACK:
            lines.append("Something went wrong, so I've undone the changes.")
            lines.append("Your system is back to how it was before.")

        return "\n".join(lines)

    def format_diagnostic_result(self, findings: list[dict[str, Any]]) -> str:
        """Format diagnostic findings naturally."""
        if not findings:
            return "Everything looks normal - I didn't find any issues."

        lines = []

        if len(findings) == 1:
            finding = findings[0]
            lines.append(f"Found something: {finding.get('summary', 'Issue detected')}")
            if finding.get("details"):
                lines.append(f"\n{finding['details']}")
        else:
            lines.append(f"Found {len(findings)} things to look at:\n")
            for i, finding in enumerate(findings, 1):
                lines.append(f"{i}. {finding.get('summary', 'Issue')}")
                if finding.get("severity") == "high":
                    lines.append("   ⚠️  This might be important")

        lines.append("\nWould you like me to fix any of these?")
        return "\n".join(lines)

    def format_options(self, options: list[dict[str, str]]) -> str:
        """Format a list of options for user choice."""
        lines = ["I can:"]

        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt.get('title', opt.get('description', 'Option'))}")
            if opt.get("note"):
                lines.append(f"   ({opt['note']})")

        lines.append("\nWhat sounds good?")
        return "\n".join(lines)

    def format_simple_result(self, result: Any, request: str) -> str:
        """Format a simple (non-planned) operation result."""
        if isinstance(result, dict):
            # Handle common result types
            if "stdout" in result:
                output = result.get("stdout", "").strip()
                if result.get("success", True):
                    return output if output else "Done."
                else:
                    error = result.get("stderr", "")
                    return f"That didn't work: {error}" if error else "Something went wrong."

            if "error" in result:
                return f"Hmm, ran into an issue: {result['error']}"

            # Generic dict result
            if self.prefs.verbosity == VerbosityLevel.MINIMAL:
                return str(result)

        if isinstance(result, str):
            return result

        return str(result)

    def format_approval_request(self, step: TaskStep) -> str:
        """Format a request for user approval before a risky step."""
        lines = []

        if step.risk and step.risk.level == RiskLevel.CRITICAL:
            lines.append("⚠️  This is a significant change:")
        else:
            lines.append("Just to check before I continue:")

        lines.append(f"\n{step.title}")

        if step.risk:
            if step.risk.reasons:
                for reason in step.risk.reasons[:3]:
                    lines.append(f"• {reason}")

            if not step.risk.reversible:
                lines.append("\n⚠️  This can't be undone automatically.")

            if step.risk.data_loss_possible:
                lines.append("⚠️  There's a chance of data loss.")

        if step.rollback_command:
            lines.append(f"\nIf needed, I can undo this with: `{step.rollback_command}`")

        lines.append("\nOkay to proceed?")
        return "\n".join(lines)

    def format_progress(self, completed: int, total: int, current_step: str) -> str:
        """Format a progress update."""
        if self.prefs.verbosity == VerbosityLevel.MINIMAL:
            return ""

        percent = (completed / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * completed / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)

        return f"[{bar}] {completed}/{total} - {current_step}"

    def format_error(self, error: str, context: str = "") -> str:
        """Format an error message naturally."""
        lines = []

        if self.prefs.friendly_tone:
            lines.append("Oops, something went wrong.")
        else:
            lines.append("Error encountered.")

        lines.append(f"\n{error}")

        if context:
            lines.append(f"\nContext: {context}")

        lines.append("\nLet me know if you'd like me to try a different approach.")
        return "\n".join(lines)

    def format_rollback_info(self, rollbacks: list[dict]) -> str:
        """Format information about available rollbacks."""
        if not rollbacks:
            return "No recent actions to undo."

        lines = ["Recent actions I can undo:\n"]

        for i, action in enumerate(rollbacks[:5], 1):
            lines.append(f"{i}. {action.get('description', 'Action')}")
            if action.get("timestamp"):
                lines.append(f"   (from {action['timestamp']})")

        lines.append("\nSay 'undo' or 'rollback' to undo the most recent action.")
        return "\n".join(lines)
