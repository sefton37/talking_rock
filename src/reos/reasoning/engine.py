"""Main reasoning engine for ReOS.

Integrates complexity assessment, planning, execution, and conversation
into a unified interface for processing user requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .complexity import ComplexityAssessor, ComplexityLevel, ComplexityResult
from .planner import TaskPlanner, TaskPlan
from .executor import ExecutionEngine, ExecutionContext, ExecutionState
from .conversation import ConversationManager, ConversationPreferences, VerbosityLevel
from .safety import SafetyManager

logger = logging.getLogger(__name__)


@dataclass
class ReasoningConfig:
    """Configuration for the reasoning engine."""

    # Core settings
    enabled: bool = True
    auto_assess: bool = True
    always_confirm: bool = False
    explain_steps: bool = True

    # Safety settings
    require_approval_for_permanent: bool = True
    auto_backup_configs: bool = True
    verify_each_step: bool = True
    rollback_on_failure: bool = True

    # Conversation settings
    verbosity: VerbosityLevel = VerbosityLevel.NORMAL
    show_commands: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReasoningConfig:
        """Create config from dictionary (e.g., loaded from TOML)."""
        config = cls()

        if "reasoning" in data:
            r = data["reasoning"]
            config.enabled = r.get("enabled", config.enabled)
            config.auto_assess = r.get("auto_assess", config.auto_assess)
            config.always_confirm = r.get("always_confirm", config.always_confirm)
            config.explain_steps = r.get("explain_steps", config.explain_steps)

        if "safety" in data:
            s = data["safety"]
            config.require_approval_for_permanent = s.get(
                "require_approval_for_permanent",
                config.require_approval_for_permanent,
            )
            config.auto_backup_configs = s.get("auto_backup_configs", config.auto_backup_configs)
            config.verify_each_step = s.get("verify_each_step", config.verify_each_step)
            config.rollback_on_failure = s.get("rollback_on_failure", config.rollback_on_failure)

        if "conversation" in data:
            c = data["conversation"]
            if "verbosity" in c:
                config.verbosity = VerbosityLevel(c["verbosity"])
            config.show_commands = c.get("show_commands", config.show_commands)

        return config

    @classmethod
    def load_from_file(cls, path: Path | str | None = None) -> ReasoningConfig:
        """Load configuration from TOML file.

        Args:
            path: Path to config file. Defaults to ~/.config/reos/settings.toml
        """
        if path is None:
            path = Path.home() / ".config" / "reos" / "settings.toml"
        else:
            path = Path(path)

        if not path.exists():
            logger.debug("Config file not found, using defaults: %s", path)
            return cls()

        try:
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return cls.from_dict(data)
        except ImportError:
            # Python < 3.11
            try:
                import tomli
                with open(path, "rb") as f:
                    data = tomli.load(f)
                return cls.from_dict(data)
            except ImportError:
                logger.warning("No TOML library available, using defaults")
                return cls()
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", path, e)
            return cls()


@dataclass
class ProcessingResult:
    """Result of processing a user request."""

    response: str
    complexity: ComplexityResult | None = None
    plan: TaskPlan | None = None
    execution_context: ExecutionContext | None = None
    needs_approval: bool = False
    needs_input: bool = False
    input_prompt: str | None = None


class ReasoningEngine:
    """Main entry point for the ReOS reasoning system.

    Processes user requests through:
    1. Complexity assessment
    2. Task planning (if needed)
    3. User approval (if risky)
    4. Execution with monitoring
    5. Natural language response

    Example:
        engine = ReasoningEngine(db)
        result = await engine.process("speed up my boot time")
        print(result.response)
    """

    def __init__(
        self,
        db: Any = None,  # Database for knowledge storage
        tool_executor: Callable[[str, dict], Any] | None = None,
        llm_planner: Callable[[str, dict], list[dict]] | None = None,
        config: ReasoningConfig | None = None,
    ) -> None:
        """Initialize the reasoning engine.

        Args:
            db: Database for storing knowledge and state
            tool_executor: Callback to execute ReOS tools
            llm_planner: Callback to use LLM for planning
            config: Configuration settings
        """
        self.db = db
        self.config = config or ReasoningConfig.load_from_file()

        # Initialize components
        self.assessor = ComplexityAssessor()
        self.safety = SafetyManager()
        self.planner = TaskPlanner(self.safety, llm_planner)
        self.executor = ExecutionEngine(self.safety, tool_executor)

        # Conversation settings from config
        conv_prefs = ConversationPreferences(
            verbosity=self.config.verbosity,
            show_commands=self.config.show_commands,
        )
        self.conversation = ConversationManager(conv_prefs)

        # Active contexts for multi-turn interactions
        self._active_contexts: dict[str, ExecutionContext] = {}
        self._pending_plan: TaskPlan | None = None

    def process(
        self,
        request: str,
        system_context: dict[str, Any] | None = None,
    ) -> ProcessingResult:
        """Process a user request.

        This is the main entry point. It:
        1. Assesses complexity
        2. Creates a plan if needed
        3. Returns response (may need approval for execution)

        Args:
            request: The user's natural language request
            system_context: Optional current system state

        Returns:
            ProcessingResult with response and any pending actions
        """
        if not self.config.enabled:
            return ProcessingResult(
                response="Reasoning system is disabled. Passing request directly to agent.",
            )

        # Handle special commands
        if self._is_approval(request):
            return self._handle_approval()

        if self._is_rejection(request):
            return self._handle_rejection()

        if self._is_undo_request(request):
            return self._handle_undo()

        # Assess complexity
        complexity = self.assessor.assess(request)

        # Simple requests - direct execution
        if complexity.level == ComplexityLevel.SIMPLE and not self.config.always_confirm:
            return ProcessingResult(
                response="",  # Empty - let agent handle directly
                complexity=complexity,
            )

        # Complex/risky/diagnostic - create plan
        plan = self.planner.create_plan(request, system_context)

        # Format the plan for presentation
        intro = self.conversation.format_complexity_result(
            complexity.level.value,
            request,
        )
        plan_text = self.conversation.format_plan_presentation(plan)

        self._pending_plan = plan

        return ProcessingResult(
            response=f"{intro}\n\n{plan_text}" if intro else plan_text,
            complexity=complexity,
            plan=plan,
            needs_approval=True,
        )

    def _is_approval(self, text: str) -> bool:
        """Check if text is an approval of pending plan."""
        text = text.lower().strip()
        approvals = {"yes", "y", "ok", "okay", "go ahead", "do it", "proceed", "yep", "sure", "go"}
        return text in approvals or text.startswith(("yes", "go ahead", "do it"))

    def _is_rejection(self, text: str) -> bool:
        """Check if text is a rejection of pending plan."""
        text = text.lower().strip()
        rejections = {"no", "n", "cancel", "stop", "don't", "abort", "nope", "nevermind"}
        return text in rejections or text.startswith(("no", "cancel", "don't"))

    def _is_undo_request(self, text: str) -> bool:
        """Check if text is an undo/rollback request."""
        text = text.lower()
        return any(word in text for word in ["undo", "rollback", "revert", "undo that"])

    def _handle_approval(self) -> ProcessingResult:
        """Handle approval of pending plan."""
        if not self._pending_plan:
            return ProcessingResult(
                response="Nothing pending to approve. What would you like me to do?",
            )

        plan = self._pending_plan
        plan.approved = True
        self._pending_plan = None

        # Start execution
        context = self.executor.start_execution(
            plan,
            callbacks={
                "on_progress": lambda c, t, s: logger.info("Progress: %d/%d - %s", c, t, s),
            },
        )

        # Execute all steps
        success = self.executor.execute_all(context)

        # Format response
        response = self.conversation.format_execution_complete(context)

        return ProcessingResult(
            response=response,
            plan=plan,
            execution_context=context,
        )

    def _handle_rejection(self) -> ProcessingResult:
        """Handle rejection of pending plan."""
        if self._pending_plan:
            self._pending_plan = None
            return ProcessingResult(
                response="No problem, cancelled. What else can I help with?",
            )
        return ProcessingResult(
            response="Nothing to cancel. What would you like me to do?",
        )

    def _handle_undo(self) -> ProcessingResult:
        """Handle undo/rollback request."""
        rollback_stack = self.safety.get_rollback_stack()

        if not rollback_stack:
            return ProcessingResult(
                response="Nothing to undo - no recent actions recorded.",
            )

        # Show what can be undone
        last_action = rollback_stack[0]

        success, message = self.safety.rollback_last()

        if success:
            return ProcessingResult(
                response=f"Done! Undid: {last_action.description}\n{message}",
            )
        else:
            return ProcessingResult(
                response=f"Couldn't undo automatically: {message}\n"
                         f"You may need to manually revert: {last_action.description}",
            )

    def should_bypass_reasoning(self, request: str) -> bool:
        """Check if request should bypass reasoning entirely.

        Some requests are so simple they should go straight to the agent.
        """
        if not self.config.enabled or not self.config.auto_assess:
            return True

        complexity = self.assessor.assess(request)
        return (
            complexity.level == ComplexityLevel.SIMPLE
            and complexity.confidence > 0.8
            and not self.config.always_confirm
        )

    def get_pending_plan(self) -> TaskPlan | None:
        """Get the currently pending plan awaiting approval."""
        return self._pending_plan

    def cancel_pending(self) -> None:
        """Cancel any pending plan."""
        self._pending_plan = None

    def set_verbosity(self, level: VerbosityLevel) -> None:
        """Update conversation verbosity."""
        self.config.verbosity = level
        self.conversation.prefs.verbosity = level

    def get_rollback_stack(self) -> list[dict]:
        """Get list of actions that can be undone."""
        return [
            {
                "id": a.id,
                "description": a.description,
                "timestamp": a.timestamp.isoformat(),
                "can_undo": a.rollback_command is not None or a.backup_path is not None,
            }
            for a in self.safety.get_rollback_stack()
        ]

    def explain_last_operation(self) -> str:
        """Explain what the last operation did."""
        stack = self.safety.get_rollback_stack()
        if not stack:
            return "No recent operations to explain."

        last = stack[0]
        lines = [f"Last operation: {last.description}"]

        if last.rollback_command:
            lines.append(f"Can be undone with: {last.rollback_command}")

        if last.backup_path:
            lines.append(f"Backup saved at: {last.backup_path}")

        return "\n".join(lines)
