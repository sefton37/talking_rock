"""Executor - the main execution loop for Code Mode.

The execution loop follows a principled cycle:
1. INTENT - Discover what the user truly wants
2. CONTRACT - Define explicit, testable success criteria
3. DECOMPOSE - Break into atomic steps
4. BUILD - Execute the most concrete step
5. VERIFY - Test that step fulfills its part
6. INTEGRATE - Merge verified code
7. GAP - Check what remains, loop until complete

Each phase uses a different perspective to ensure appropriate focus.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reos.code_mode.contract import (
    AcceptanceCriterion,
    Contract,
    ContractBuilder,
    ContractStatus,
    ContractStep,
)
from reos.code_mode.intent import DiscoveredIntent, IntentDiscoverer
from reos.code_mode.intention import (
    AutoCheckpoint,
    Cycle,
    Intention,
    IntentionStatus,
    Session as RIVASession,
    WorkContext,
    work as riva_work,
)
from reos.code_mode.perspectives import (
    ENGINEER,
    Phase,
    PerspectiveManager,
)
from reos.code_mode.sandbox import CodeSandbox
from reos.code_mode.streaming import ExecutionCancelledError, ExecutionObserver
from reos.code_mode.explorer import StepExplorer, StepAlternative, ExplorationState
from reos.code_mode.session_logger import SessionLogger

if TYPE_CHECKING:
    from reos.code_mode.planner import CodeTaskPlan
    from reos.code_mode.project_memory import ProjectMemoryStore
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


class LoopStatus(Enum):
    """Status of the execution loop."""

    PENDING = "pending"             # Not started
    DISCOVERING_INTENT = "intent"   # Phase 1
    BUILDING_CONTRACT = "contract"  # Phase 2
    DECOMPOSING = "decompose"       # Phase 3
    BUILDING = "build"              # Phase 4
    VERIFYING = "verify"            # Phase 5
    DEBUGGING = "debug"             # Phase 5.5 - Analyzing failures
    EXPLORING = "exploring"         # Phase 5.6 - Trying alternative approaches
    INTEGRATING = "integrate"       # Phase 6
    ANALYZING_GAP = "gap"           # Phase 7
    COMPLETED = "completed"         # All done
    FAILED = "failed"               # Unrecoverable error
    AWAITING_APPROVAL = "approval"  # Needs user input


@dataclass
class LoopIteration:
    """Record of a single iteration through the loop."""

    iteration_number: int
    started_at: datetime
    completed_at: datetime | None = None
    phase_reached: Phase | None = None
    contract_id: str | None = None
    steps_completed: int = 0
    criteria_fulfilled: int = 0
    criteria_total: int = 0
    gap_remaining: str = ""
    error: str | None = None


@dataclass
class ExecutionState:
    """Complete state of an execution session."""

    session_id: str
    prompt: str
    status: LoopStatus = LoopStatus.PENDING
    # Core objects
    intent: DiscoveredIntent | None = None
    current_contract: Contract | None = None
    # History
    iterations: list[LoopIteration] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)
    # Metadata
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    max_iterations: int = 10
    current_iteration: int = 0


@dataclass
class DebugDiagnosis:
    """Result of debugging a failure."""

    root_cause: str
    failure_type: str  # code_bug, test_bug, environment, missing_dependency, configuration
    fix_location: dict[str, str]  # {"file": "path", "area": "function/lines"}
    fix_action: dict[str, str]  # {"old_str": "...", "new_str": "..."}
    confidence: str  # high, medium, low
    needs_more_info: bool = False
    raw_output: str = ""


@dataclass
class StepResult:
    """Result of executing a single step."""

    success: bool
    step_id: str
    output: str
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    debug_attempts: int = 0  # How many times we've tried to debug this step


@dataclass
class ExecutionResult:
    """Final result of the execution loop."""

    success: bool
    message: str
    state: ExecutionState
    files_changed: list[str] = field(default_factory=list)
    total_iterations: int = 0


class CodeExecutor:
    """Executes the code mode loop.

    The executor orchestrates the full cycle:
    Intent -> Contract -> Decompose -> Build -> Verify -> Integrate -> Gap -> Repeat

    Each phase uses a different perspective for appropriate focus.

    When project_memory is provided:
    - Records coding sessions for history
    - Tracks file changes
    - Detects user corrections (comparing generated vs final content)
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        llm: "LLMProvider | None" = None,
        project_memory: "ProjectMemoryStore | None" = None,
        observer: ExecutionObserver | None = None,
    ) -> None:
        self.sandbox = sandbox
        self._llm = llm
        self._project_memory = project_memory
        self._observer = observer
        self._perspectives = PerspectiveManager(llm)
        self._intent_discoverer = IntentDiscoverer(
            sandbox, llm, project_memory=project_memory, observer=observer
        )
        self._contract_builder = ContractBuilder(
            sandbox, llm, project_memory=project_memory, observer=observer
        )
        self._explorer = StepExplorer(sandbox, self._perspectives)
        # Track generated content for correction detection
        self._generated_content: dict[str, str] = {}
        # Track exploration states by step ID
        self._exploration_states: dict[str, ExplorationState] = {}
        # Session logger for verbose debugging (initialized per-execution)
        self._session_logger: SessionLogger | None = None

    def execute(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str = "",
        max_iterations: int = 10,
        auto_approve: bool = False,
        plan_context: "CodeTaskPlan | None" = None,
        use_riva: bool = False,
    ) -> ExecutionResult:
        """Execute the full code mode loop.

        Args:
            prompt: The user's request.
            act: The active Act with context.
            knowledge_context: Optional KB context.
            max_iterations: Maximum loop iterations.
            auto_approve: If True, skip approval prompts.
            plan_context: Optional pre-computed plan from CodePlanner.
                         When provided, reuses the plan's file analysis
                         instead of rediscovering from scratch.
            use_riva: If True, use RIVA (Recursive Intention-Verification Architecture)
                     instead of the standard contract-based loop.

        Returns:
            ExecutionResult with outcome and state.
        """
        import uuid

        session_id = f"exec-{uuid.uuid4().hex[:8]}"
        state = ExecutionState(
            session_id=session_id,
            prompt=prompt,
            max_iterations=max_iterations,
        )

        # Initialize session logger for verbose debugging
        self._session_logger = SessionLogger(session_id=session_id, prompt=prompt)
        self._session_logger.log_info("executor", "init", f"Starting execution with max {max_iterations} iterations", {
            "session_id": session_id,
            "max_iterations": max_iterations,
            "auto_approve": auto_approve,
            "has_plan_context": plan_context is not None,
        })

        # Pass session logger to subsystems for comprehensive logging
        self._intent_discoverer._session_logger = self._session_logger
        self._contract_builder._session_logger = self._session_logger

        # Clear generated content tracker for this session
        self._generated_content.clear()

        try:
            # Phase 1: Discover Intent (enhanced with plan context if available)
            state.status = LoopStatus.DISCOVERING_INTENT
            self._notify_phase_change(state.status)
            self._session_logger.log_phase_change("intent", "Discovering user intent")
            state.intent = self._discover_intent(
                prompt, act, knowledge_context, plan_context=plan_context
            )
            # Log discovered intent
            self._session_logger.log_intent_discovered(
                goal=state.intent.goal,
                confidence=state.intent.confidence,
                ambiguities=state.intent.ambiguities,
                assumptions=state.intent.assumptions,
            )

            # Branch: Use RIVA or standard contract-based loop
            if use_riva:
                return self._execute_riva(state, act)

            # Main loop (standard contract-based execution)
            while state.current_iteration < max_iterations:
                # Notify iteration start
                self._notify_iteration_start(state.current_iteration + 1, max_iterations)
                unfulfilled = state.current_contract.get_unfulfilled_criteria() if state.current_contract else []
                self._session_logger.log_iteration_start(
                    iteration=state.current_iteration + 1,
                    max_iterations=max_iterations,
                    unfulfilled_count=len(unfulfilled),
                )

                iteration = self._run_iteration(state, act, auto_approve)
                state.iterations.append(iteration)
                state.current_iteration += 1

                # Log iteration completion
                fulfilled = len(state.current_contract.acceptance_criteria) - len(state.current_contract.get_unfulfilled_criteria()) if state.current_contract else 0
                total = len(state.current_contract.acceptance_criteria) if state.current_contract else 0
                self._session_logger.log_iteration_complete(
                    iteration=state.current_iteration,
                    fulfilled_count=fulfilled,
                    total_criteria=total,
                )

                if iteration.error:
                    self._session_logger.log_error("executor", "iteration_failed", f"Iteration failed: {iteration.error}", {
                        "iteration": state.current_iteration,
                        "error": iteration.error,
                    })
                    state.status = LoopStatus.FAILED
                    self._notify_phase_change(state.status)
                    break

                # Check if complete
                if state.current_contract and state.current_contract.is_fulfilled(self.sandbox):
                    self._session_logger.log_info("executor", "contract_fulfilled", "All criteria fulfilled!")
                    state.status = LoopStatus.COMPLETED
                    state.completed_at = datetime.now(timezone.utc)
                    self._notify_phase_change(state.status)
                    break

            # If loop ended without completion (max iterations reached), mark as failed
            if state.status not in (LoopStatus.COMPLETED, LoopStatus.FAILED):
                self._session_logger.log_warn("executor", "max_iterations", f"Max iterations ({max_iterations}) reached without completion")
                state.status = LoopStatus.FAILED
                self._notify_phase_change(state.status)

            # Build result
            files_changed = self._collect_changed_files(state)

            result = ExecutionResult(
                success=state.status == LoopStatus.COMPLETED,
                message=self._generate_result_message(state),
                state=state,
                files_changed=files_changed,
                total_iterations=state.current_iteration,
            )

            # Notify completion
            self._notify_complete(result)

            # Record session in project memory
            self._record_session(state, act, result)

            # Close session logger
            outcome = "completed" if result.success else "failed"
            self._session_logger.close(outcome=outcome, final_message=result.message)
            self._session_logger.log_info("executor", "session_end", f"Session log saved to: {self._session_logger.get_log_path()}")

            return result

        except ExecutionCancelledError:
            logger.info("Execution cancelled by user")
            state.status = LoopStatus.FAILED
            result = ExecutionResult(
                success=False,
                message="Execution cancelled by user",
                state=state,
            )
            self._notify_error("Execution cancelled by user")
            self._record_session(state, act, result)
            if self._session_logger:
                self._session_logger.close(outcome="cancelled", final_message="Cancelled by user")
            return result

        except Exception as e:
            logger.exception("Execution failed: %s", e)
            state.status = LoopStatus.FAILED
            result = ExecutionResult(
                success=False,
                message=f"Execution failed: {e}",
                state=state,
            )

            # Notify error
            self._notify_error(str(e))

            # Record failed session
            self._record_session(state, act, result)

            # Close session logger with error
            if self._session_logger:
                self._session_logger.log_error("executor", "exception", f"Unhandled exception: {e}")
                self._session_logger.close(outcome="failed", final_message=str(e))

            return result

    def _discover_intent(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str,
        plan_context: "CodeTaskPlan | None" = None,
    ) -> DiscoveredIntent:
        """Phase 1: Discover intent from all sources.

        Args:
            prompt: The user's request.
            act: The active Act with context.
            knowledge_context: Optional KB context.
            plan_context: Optional pre-computed plan with file analysis.

        Returns:
            DiscoveredIntent synthesizing all sources.
        """
        self._perspectives.shift_to(Phase.INTENT)
        return self._intent_discoverer.discover(
            prompt, act, knowledge_context, plan_context=plan_context
        )

    def _execute_riva(
        self,
        state: ExecutionState,
        act: "Act",
    ) -> ExecutionResult:
        """Execute using RIVA (Recursive Intention-Verification Architecture).

        RIVA uses a single recursive principle: "If you can't verify it, decompose it."
        Instead of a fixed contract-based loop, RIVA dynamically builds an intention
        tree, working each node until verified or decomposed.

        Args:
            state: Current execution state with discovered intent.
            act: The active Act with context.

        Returns:
            ExecutionResult with outcome and state.
        """
        assert state.intent is not None, "Intent must be discovered before RIVA execution"
        assert self._session_logger is not None, "Session logger must be initialized"

        self._session_logger.log_info("executor", "riva_start",
            "Starting RIVA execution mode", {
                "goal": state.intent.goal[:100],
                "confidence": state.intent.confidence,
            })

        # Create root intention from discovered intent
        # Synthesize acceptance criteria from goal and constraints
        if state.intent.how_constraints:
            acceptance = f"Goal achieved: {state.intent.goal}. Constraints satisfied: {'; '.join(state.intent.how_constraints[:3])}"
        else:
            acceptance = f"Goal verified: {state.intent.goal}"

        root_intention = Intention.create(
            what=state.intent.goal,
            acceptance=acceptance,
        )

        # Set up callbacks for UI integration
        def on_intention_start(intention: Intention) -> None:
            """Called when work begins on an intention."""
            if self._observer:
                self._observer.on_activity(
                    f"Working on: {intention.what[:50]}...",
                    module="RIVA"
                )
            self._session_logger.log_info("riva", "intention_start",
                f"Starting: {intention.what[:50]}...", {
                    "intention_id": intention.id,
                    "acceptance": intention.acceptance[:100],
                })

        def on_intention_complete(intention: Intention) -> None:
            """Called when an intention is complete (verified or failed)."""
            if self._observer:
                status_str = "verified" if intention.status == IntentionStatus.VERIFIED else "failed"
                self._observer.on_activity(
                    f"Intention {status_str}: {intention.what[:40]}...",
                    module="RIVA"
                )
            self._session_logger.log_info("riva", "intention_complete",
                f"Completed: {intention.what[:50]}...", {
                    "intention_id": intention.id,
                    "status": intention.status.value,
                    "cycles": len(intention.trace),
                    "children": len(intention._child_intentions),
                })

        def on_cycle_complete(intention: Intention, cycle: Cycle) -> None:
            """Called after each action cycle."""
            if self._observer:
                self._observer.on_activity(
                    f"Cycle: {cycle.action.type.value} → {cycle.judgment.value}",
                    module="RIVA"
                )
            self._session_logger.log_info("riva", "cycle_complete",
                f"Cycle: {cycle.action.type.value} → {cycle.judgment.value}", {
                    "action_type": cycle.action.type.value,
                    "judgment": cycle.judgment.value,
                    "result_preview": cycle.result[:100],
                })

        def on_decomposition(intention: Intention, children: list[Intention]) -> None:
            """Called when an intention is decomposed."""
            if self._observer:
                self._observer.on_activity(
                    f"Decomposed into {len(children)} sub-tasks",
                    module="RIVA"
                )
            self._session_logger.log_info("riva", "decomposition",
                f"Decomposed: {intention.what[:40]}... → {len(children)} children", {
                    "parent_id": intention.id,
                    "children": [c.what[:50] for c in children],
                })

        # Create work context
        checkpoint = AutoCheckpoint(self.sandbox, self._llm)
        ctx = WorkContext(
            sandbox=self.sandbox,
            llm=self._llm,
            checkpoint=checkpoint,
            session_logger=self._session_logger,
            max_cycles_per_intention=5,
            max_depth=state.max_iterations,  # Use max_iterations as depth limit
            on_intention_start=on_intention_start,
            on_intention_complete=on_intention_complete,
            on_cycle_complete=on_cycle_complete,
            on_decomposition=on_decomposition,
        )

        # Notify UI of RIVA mode
        state.status = LoopStatus.BUILDING
        self._notify_phase_change(state.status)

        try:
            # Run RIVA
            riva_work(root_intention, ctx)

            # Capture session for training data
            riva_session = RIVASession.create(root_intention)
            riva_session.metadata["intent_goal"] = state.intent.goal
            riva_session.metadata["intent_confidence"] = state.intent.confidence

            # Save session
            sessions_dir = Path(".reos-data/riva_sessions")
            sessions_dir.mkdir(parents=True, exist_ok=True)
            riva_session.save(sessions_dir / f"{riva_session.id}.json")

            # Determine outcome
            success = root_intention.status == IntentionStatus.VERIFIED
            state.status = LoopStatus.COMPLETED if success else LoopStatus.FAILED
            state.completed_at = datetime.now(timezone.utc)

            # Collect changed files from all actions
            files_changed = set()
            def collect_files(intention: Intention) -> None:
                for cycle in intention.trace:
                    if cycle.action.target:
                        files_changed.add(cycle.action.target)
                for child in intention._child_intentions:
                    collect_files(child)
            collect_files(root_intention)

            self._session_logger.log_info("riva", "complete",
                f"RIVA execution complete: {root_intention.status.value}", {
                    "success": success,
                    "total_cycles": root_intention.get_total_cycles(),
                    "max_depth": root_intention.get_depth(),
                    "files_changed": list(files_changed),
                })

            # Close session logger
            self._session_logger.close(
                outcome="completed" if success else "failed",
                final_message=f"RIVA {root_intention.status.value}: {root_intention.what[:100]}",
            )

            return ExecutionResult(
                success=success,
                message=f"RIVA {'verified' if success else 'failed'}: {root_intention.what[:100]}",
                state=state,
                files_changed=list(files_changed),
                total_iterations=root_intention.get_total_cycles(),
            )

        except ExecutionCancelledError:
            state.status = LoopStatus.FAILED
            self._session_logger.log_warn("riva", "cancelled", "Execution cancelled by user")
            self._session_logger.close(outcome="cancelled", final_message="User cancelled")
            return ExecutionResult(
                success=False,
                message="Execution cancelled",
                state=state,
            )
        except Exception as e:
            state.status = LoopStatus.FAILED
            self._session_logger.log_error("riva", "error", f"RIVA execution failed: {e}")
            self._session_logger.close(outcome="failed", final_message=str(e))
            logger.exception("RIVA execution failed")
            return ExecutionResult(
                success=False,
                message=f"RIVA execution failed: {e}",
                state=state,
            )

    def _run_iteration(
        self,
        state: ExecutionState,
        act: Act,
        auto_approve: bool,
    ) -> LoopIteration:
        """Run a single iteration of the loop."""
        iteration = LoopIteration(
            iteration_number=state.current_iteration + 1,
            started_at=datetime.now(timezone.utc),
        )

        try:
            # Phase 2: Build or update contract
            if state.current_contract is None:
                state.status = LoopStatus.BUILDING_CONTRACT
                self._notify_phase_change(state.status)
                self._session_logger.log_phase_change("contract", "Building acceptance contract")
                iteration.phase_reached = Phase.CONTRACT
                state.current_contract = self._build_contract(state.intent)
                state.contracts.append(state.current_contract)
                iteration.contract_id = state.current_contract.id
                iteration.criteria_total = len(state.current_contract.acceptance_criteria)
                self._notify_contract_built(state.current_contract)
                # Log contract details
                criteria_summaries = [c.description[:60] for c in state.current_contract.acceptance_criteria]
                self._session_logger.log_contract_built(
                    contract_id=state.current_contract.id,
                    criteria_count=len(state.current_contract.acceptance_criteria),
                    criteria_summaries=criteria_summaries,
                )

            contract = state.current_contract

            # Phase 3: Decompose (already done in contract building)
            state.status = LoopStatus.DECOMPOSING
            self._notify_phase_change(state.status)
            iteration.phase_reached = Phase.DECOMPOSE

            # Phase 4: Build - execute next step
            next_step = contract.get_next_step()
            debug_attempts = getattr(next_step, '_debug_attempts', 0) if next_step else 0

            if next_step:
                state.status = LoopStatus.BUILDING
                self._notify_phase_change(state.status)
                self._session_logger.log_phase_change("build", "Executing step")
                iteration.phase_reached = Phase.BUILD
                self._notify_step_start(next_step)
                # Log step start
                step_idx = contract.steps.index(next_step) + 1 if next_step in contract.steps else 0
                self._session_logger.log_step_start(
                    step_num=step_idx,
                    total_steps=len(contract.steps),
                    description=next_step.description,
                    step_type=next_step.action,
                    target_path=next_step.target_file,
                )
                step_result = self._execute_step(next_step, state.intent, act, state)
                self._notify_step_complete(next_step, step_result.success, step_result.output)
                # Log step completion
                self._session_logger.log_step_complete(
                    step_num=step_idx,
                    success=step_result.success,
                    output=step_result.output[:500] if step_result.output else None,
                    error=step_result.error,
                )

                if step_result.success:
                    next_step.status = "completed"
                    next_step.result = step_result.output
                    next_step.completed_at = datetime.now(timezone.utc)
                    iteration.steps_completed += 1

                    # Phase 5: Verify
                    state.status = LoopStatus.VERIFYING
                    self._notify_phase_change(state.status)
                    self._session_logger.log_phase_change("verify", "Verifying step")
                    iteration.phase_reached = Phase.VERIFY
                    verification_passed = self._verify_step(next_step, contract)
                    self._session_logger.log_info("executor", "verification_result",
                        f"Verification {'PASSED' if verification_passed else 'FAILED'}", {
                            "step": next_step.description[:50],
                            "passed": verification_passed,
                        })

                    # Phase 5.5: Debug if verification failed
                    if not verification_passed and debug_attempts < 3:
                        state.status = LoopStatus.DEBUGGING
                        self._notify_phase_change(state.status)
                        self._notify_debug_start(debug_attempts + 1)
                        iteration.phase_reached = Phase.DEBUG
                        debug_result = self._debug_failure(
                            next_step, contract, step_result, state.intent, act
                        )
                        if debug_result:
                            # Applied a fix - mark step as pending to retry in next iteration
                            next_step.status = "pending"
                            # Store debug attempts on step for next iteration
                            next_step._debug_attempts = debug_attempts + 1  # type: ignore
                            # Return early - next iteration will retry this step
                            iteration.completed_at = datetime.now(timezone.utc)
                            iteration.gap_remaining = "Debug fix applied, retrying step"
                            return iteration

                    # Verification still failed after debug - try exploration
                    if not verification_passed and debug_attempts >= 3 and state.intent is not None:
                        exploration_result = self._explore_alternatives(
                            next_step, step_result, state.intent, act, state
                        )
                        if exploration_result and exploration_result.success:
                            # Alternative succeeded - re-verify
                            next_step.status = "completed"
                            next_step.result = exploration_result.output
                            # Re-run verification with new implementation
                            verification_passed = self._verify_step(next_step, contract)
                            if not verification_passed:
                                # Still failed verification - mark as failed
                                next_step.status = "failed"

                    # Phase 6: Integrate (for now, changes are direct)
                    state.status = LoopStatus.INTEGRATING
                    self._notify_phase_change(state.status)
                    iteration.phase_reached = Phase.INTEGRATE
                else:
                    # Build step failed - try to debug
                    if debug_attempts < 3:
                        state.status = LoopStatus.DEBUGGING
                        self._notify_phase_change(state.status)
                        self._notify_debug_start(debug_attempts + 1)
                        iteration.phase_reached = Phase.DEBUG
                        debug_result = self._debug_failure(
                            next_step, contract, step_result, state.intent, act
                        )
                        if debug_result:
                            # Store debug attempts on step for next iteration
                            next_step._debug_attempts = debug_attempts + 1  # type: ignore
                            # Return early - next iteration will retry this step
                            iteration.completed_at = datetime.now(timezone.utc)
                            iteration.gap_remaining = "Debug fix applied, retrying step"
                            return iteration

                    # Debug exhausted - try multi-path exploration
                    if state.intent is not None:
                        exploration_result = self._explore_alternatives(
                            next_step, step_result, state.intent, act, state
                        )
                        if exploration_result and exploration_result.success:
                            # Alternative succeeded!
                            next_step.status = "completed"
                            next_step.result = exploration_result.output
                            next_step.completed_at = datetime.now(timezone.utc)
                            iteration.steps_completed += 1
                            iteration.completed_at = datetime.now(timezone.utc)
                            iteration.gap_remaining = "Alternative approach succeeded"
                            return iteration

                    next_step.status = "failed"
                    next_step.result = step_result.error or "Unknown error"

            # Phase 7: Gap Analysis
            state.status = LoopStatus.ANALYZING_GAP
            self._notify_phase_change(state.status)
            iteration.phase_reached = Phase.GAP_ANALYSIS

            # Check fulfillment
            fulfilled = [c for c in contract.acceptance_criteria if c.verified]
            iteration.criteria_fulfilled = len(fulfilled)

            # If not all fulfilled, create gap contract
            unfulfilled = contract.get_unfulfilled_criteria()
            if unfulfilled and not contract.get_pending_steps():
                # All steps done but criteria not met - need new approach
                gap_contract = self._contract_builder.build_gap_contract(
                    contract, state.intent  # type: ignore
                )
                state.current_contract = gap_contract
                state.contracts.append(gap_contract)
                self._notify_contract_built(gap_contract)
                iteration.gap_remaining = f"{len(unfulfilled)} criteria unfulfilled"

            iteration.completed_at = datetime.now(timezone.utc)

        except ExecutionCancelledError:
            # Re-raise cancellation to be handled by execute()
            raise

        except Exception as e:
            logger.exception("Iteration failed: %s", e)
            iteration.error = str(e)
            iteration.completed_at = datetime.now(timezone.utc)

        return iteration

    def _build_contract(self, intent: DiscoveredIntent | None) -> Contract:
        """Phase 2: Build contract from intent."""
        self._perspectives.shift_to(Phase.CONTRACT)
        if intent is None:
            raise ValueError("Cannot build contract without intent")
        return self._contract_builder.build_from_intent(intent)

    def _execute_step(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
        state: ExecutionState | None = None,
    ) -> StepResult:
        """Phase 4: Execute a single step."""
        self._perspectives.shift_to(Phase.BUILD)
        step.status = "in_progress"

        try:
            if step.action == "create_file":
                return self._execute_create_file(step, intent, act, state)
            elif step.action == "edit_file":
                return self._execute_edit_file(step, intent, act, state)
            elif step.action == "run_command":
                return self._execute_command(step)
            else:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error=f"Unknown action: {step.action}",
                )
        except Exception as e:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error=str(e),
            )

    def _execute_create_file(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
        state: ExecutionState | None = None,
    ) -> StepResult:
        """Execute a file creation step."""
        if not step.target_file:
            # Need to determine target file
            if intent and intent.codebase_intent.related_files:
                # Use a related file's directory
                related = intent.codebase_intent.related_files[0]
                step.target_file = str(Path(related).parent / "new_file.py")
            else:
                step.target_file = "src/new_file.py"

        # Generate content using LLM
        content = self._generate_file_content(step, intent, act)

        if not content:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error="Could not generate file content",
            )

        # Write the file
        result = self.sandbox.write_file(step.target_file, content)

        # Track generated content for correction detection
        self._generated_content[step.target_file] = content

        # Record change in project memory
        if state:
            self._record_change(
                state.session_id,
                act,
                step.target_file,
                "create",
                content,
                step.id,
            )

        return StepResult(
            success=True,
            step_id=step.id,
            output=f"Created {step.target_file}",
            files_changed=[step.target_file],
        )

    def _execute_edit_file(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
        state: ExecutionState | None = None,
    ) -> StepResult:
        """Execute a file edit step."""
        if not step.target_file:
            # Try to determine from intent
            if intent and intent.codebase_intent.related_files:
                step.target_file = intent.codebase_intent.related_files[0]
            else:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error="No target file specified",
                )

        # Read current content
        try:
            current_content = self.sandbox.read_file(step.target_file)
        except Exception as e:
            logger.error("Failed to read file %s for editing: %s", step.target_file, e, exc_info=True)
            if self._session_logger:
                self._session_logger.log_error("executor", "file_read_failed",
                    f"Could not read {step.target_file} for editing: {e}", {
                        "target_file": step.target_file,
                        "step_id": step.id,
                        "step_description": step.description[:100],
                        "exception_type": type(e).__name__,
                    })
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error=f"Cannot read file: {e}",
            )

        # Generate edit using LLM
        edit_result = self._generate_edit(step, current_content, intent, act)

        if not edit_result:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error="Could not generate edit",
            )

        old_str, new_str = edit_result

        if old_str and new_str:
            try:
                self.sandbox.edit_file(step.target_file, old_str, new_str)

                # Track the new content for correction detection
                try:
                    new_content = self.sandbox.read_file(step.target_file)
                    self._generated_content[step.target_file] = new_content

                    # Record change in project memory
                    if state:
                        diff_summary = f"Replaced: '{old_str[:50]}...' with '{new_str[:50]}...'"
                        self._record_change(
                            state.session_id,
                            act,
                            step.target_file,
                            "edit",
                            new_content,
                            step.id,
                            old_content=current_content,
                            diff_summary=diff_summary,
                        )
                except Exception as e:
                    logger.debug("Failed to record file change: %s", e)

                return StepResult(
                    success=True,
                    step_id=step.id,
                    output=f"Edited {step.target_file}",
                    files_changed=[step.target_file],
                )
            except Exception as e:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error=f"Edit failed: {e}",
                )

        return StepResult(
            success=False,
            step_id=step.id,
            output="",
            error="No valid edit generated",
        )

    def _execute_command(self, step: ContractStep) -> StepResult:
        """Execute a command step."""
        command = step.command or "echo 'No command'"

        # Notify observer of command being run
        self._notify_command_output(f"$ {command}")

        returncode, stdout, stderr = self.sandbox.run_command(command)

        # Stream output lines to observer
        output = stdout if stdout else stderr
        if output:
            for line in output.split("\n")[:20]:  # First 20 lines
                self._notify_command_output(line)

        return StepResult(
            success=returncode == 0,
            step_id=step.id,
            output=stdout[:1000] if stdout else stderr[:1000],
            error=stderr if returncode != 0 else None,
        )

    def _generate_file_content(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> str:
        """Generate content for a new file."""
        if self._llm is None:
            return f"# {step.description}\n# TODO: Implement\n"

        # Build API documentation context
        api_context = ""
        if intent and intent.codebase_intent.api_documentation:
            api_context = "\nAVAILABLE APIs (use these correctly):\n"
            for doc in intent.codebase_intent.api_documentation[:5]:
                api_context += f"- {doc.format_for_context()}\n"

        context = f"""
STEP: {step.description}
TARGET FILE: {step.target_file}
LANGUAGE: {intent.codebase_intent.language if intent else 'python'}
CONVENTIONS: {', '.join(intent.codebase_intent.conventions) if intent else 'standard'}
{api_context}"""

        response = self._perspectives.invoke(
            Phase.BUILD,
            f"Write the complete file content for: {step.description}",
            context=context,
        )

        # Extract code from response
        return self._extract_code(response)

    def _generate_edit(
        self,
        step: ContractStep,
        current_content: str,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> tuple[str, str] | None:
        """Generate an edit (old_str, new_str) for a file."""
        if self._llm is None:
            return None

        # Build API documentation context
        api_context = ""
        if intent and intent.codebase_intent.api_documentation:
            api_context = "\nAVAILABLE APIs (use these correctly):\n"
            for doc in intent.codebase_intent.api_documentation[:5]:
                api_context += f"- {doc.format_for_context()}\n"

        context = f"""
STEP: {step.description}
TARGET FILE: {step.target_file}
{api_context}
CURRENT FILE CONTENT:
```
{current_content[:2000]}
```

Output JSON with:
{{"old_str": "exact text to replace", "new_str": "replacement text"}}
"""

        try:
            response = self._perspectives.invoke_json(
                Phase.BUILD,
                f"Generate the minimal edit for: {step.description}",
                context=context,
            )
            data = json.loads(response)
            return data.get("old_str"), data.get("new_str")
        except Exception as e:
            logger.error("LLM edit generation failed: %s", e, exc_info=True)
            if self._session_logger:
                self._session_logger.log_error("executor", "edit_generation_failed",
                    f"Failed to generate edit: {e}", {
                        "target_file": step.target_file if step.target_file else "unknown",
                        "step_description": step.description[:100],
                        "exception_type": type(e).__name__,
                        "exception": str(e),
                    })
            return None

    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response."""
        # Look for code blocks
        if "```" in response:
            parts = response.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Odd indices are code blocks
                    # Remove language identifier if present
                    lines = part.strip().split("\n")
                    if lines and lines[0] in ("python", "py", "typescript", "ts", "javascript", "js"):
                        return "\n".join(lines[1:])
                    return part.strip()

        # No code block, return as-is
        return response.strip()

    def _verify_step(self, step: ContractStep, contract: Contract) -> bool:
        """Phase 5: Verify a step's output.

        Returns:
            True if all target criteria are verified, False otherwise.
        """
        self._perspectives.shift_to(Phase.VERIFY)

        all_passed = True
        # Verify related criteria
        for criterion_id in step.target_criteria:
            for criterion in contract.acceptance_criteria:
                if criterion.id == criterion_id:
                    criterion.verified = criterion.verify(self.sandbox)
                    if criterion.verified:
                        criterion.verified_at = datetime.now(timezone.utc)
                    else:
                        all_passed = False
                    # Notify observer of verification result
                    self._notify_criterion_verified(criterion)

        return all_passed

    def _debug_failure(
        self,
        step: ContractStep,
        contract: Contract,
        step_result: StepResult,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> bool:
        """Phase 5.5: Debug a failure and attempt to fix it.

        Args:
            step: The step that failed.
            contract: The current contract.
            step_result: The result of the failed step.
            intent: The discovered intent.
            act: The active Act.

        Returns:
            True if a fix was applied and we should retry, False otherwise.
        """
        self._perspectives.shift_to(Phase.DEBUG)

        if self._llm is None:
            return False

        # Gather failure information
        failed_criteria = [
            c for c in contract.acceptance_criteria
            if c.id in step.target_criteria and not c.verified
        ]

        if not failed_criteria and not step_result.error:
            return False  # No clear failure to debug

        # Build context for debugger
        error_output = step_result.error or ""
        verification_outputs = "\n".join(
            f"- {c.description}: {c.verification_output}"
            for c in failed_criteria
        )

        # Read the file that was changed if available
        file_content = ""
        if step.target_file:
            try:
                file_content = self.sandbox.read_file(step.target_file)
            except Exception as e:
                logger.debug("Failed to read target file for debug context: %s", e)

        context = f"""
STEP DESCRIPTION: {step.description}
TARGET FILE: {step.target_file or 'N/A'}
STEP ACTION: {step.action}

ERROR OUTPUT:
{error_output}

FAILED VERIFICATIONS:
{verification_outputs if verification_outputs else 'No specific verification failures'}

FILE CONTENT (if relevant):
```
{file_content[:3000] if file_content else 'N/A'}
```
"""

        try:
            response = self._perspectives.invoke_json(
                Phase.DEBUG,
                "Analyze this failure and provide a fix.",
                context=context,
            )
            data = json.loads(response)

            diagnosis = DebugDiagnosis(
                root_cause=data.get("root_cause", "Unknown"),
                failure_type=data.get("failure_type", "unknown"),
                fix_location=data.get("fix_location", {}),
                fix_action=data.get("fix_action", {}),
                confidence=data.get("confidence", "low"),
                needs_more_info=data.get("needs_more_info", False),
                raw_output=response,
            )

            # Notify observer of diagnosis
            self._notify_debug_diagnosis(diagnosis)

            # Apply fix if confident enough
            if diagnosis.confidence in ("high", "medium") and not diagnosis.needs_more_info:
                fix_applied = self._apply_debug_fix(diagnosis, step)
                if fix_applied:
                    logger.info(
                        "Applied debug fix: %s (confidence: %s)",
                        diagnosis.root_cause,
                        diagnosis.confidence,
                    )
                    return True

            logger.warning(
                "Debug diagnosis: %s (confidence: %s, needs_more_info: %s)",
                diagnosis.root_cause,
                diagnosis.confidence,
                diagnosis.needs_more_info,
            )
            return False

        except Exception as e:
            logger.warning("Debug analysis failed: %s", e)
            return False

    def _apply_debug_fix(self, diagnosis: DebugDiagnosis, step: ContractStep) -> bool:
        """Apply a fix from debug diagnosis.

        Args:
            diagnosis: The debug diagnosis with fix information.
            step: The step being fixed.

        Returns:
            True if fix was applied successfully.
        """
        fix_action = diagnosis.fix_action
        if not fix_action:
            return False

        old_str = fix_action.get("old_str", "")
        new_str = fix_action.get("new_str", "")

        if not old_str or not new_str:
            return False

        # Determine target file
        target_file = diagnosis.fix_location.get("file") or step.target_file
        if not target_file:
            return False

        try:
            self.sandbox.edit_file(target_file, old_str, new_str)
            return True
        except Exception as e:
            logger.error("Failed to apply debug fix to %s: %s", target_file, e, exc_info=True)
            if self._session_logger:
                self._session_logger.log_error("executor", "fix_application_failed",
                    f"Could not apply recommended debug fix: {e}", {
                        "target_file": target_file,
                        "old_str_preview": old_str[:80] if old_str else "",
                        "new_str_preview": new_str[:80] if new_str else "",
                        "exception_type": type(e).__name__,
                    })
            return False

    def _explore_alternatives(
        self,
        step: ContractStep,
        original_result: StepResult,
        intent: DiscoveredIntent,
        act: Act,
        state: ExecutionState,
    ) -> StepResult | None:
        """Try alternative approaches for a failed step.

        Called when a step fails and debugging doesn't help. Generates
        multiple alternative implementations and tries each one.

        Args:
            step: The step that failed.
            original_result: Result from the failed attempt.
            intent: The discovered intent for context.
            act: The active Act.
            state: Current execution state.

        Returns:
            StepResult if an alternative succeeded, None if all failed.
        """
        state.status = LoopStatus.EXPLORING
        self._notify_phase_change(state.status)

        # Get or create exploration state
        exploration = self._exploration_states.get(step.id)
        original_code = step.content or step.new_content or step.command or ""

        if exploration is None:
            # First time exploring this step - generate alternatives
            alternatives = self._explorer.generate_alternatives(
                step,
                original_result.error or "Unknown error",
                intent,
                original_code=original_code,
                n_alternatives=3,
            )

            if not alternatives:
                logger.info("No alternatives generated for step %s", step.id)
                return None

            exploration = self._explorer.create_exploration_state(
                step,
                original_result.error or "Unknown error",
                alternatives,
            )
            self._exploration_states[step.id] = exploration

            # Notify observer of exploration start
            self._notify_exploration_start(step, len(alternatives))

        # Try each untried alternative
        while exploration.current_alternative_idx < len(exploration.alternatives):
            alt = exploration.alternatives[exploration.current_alternative_idx]

            if alt.attempted and alt.debug_attempted:
                # Already tried this alternative with debug, move on
                exploration.current_alternative_idx += 1
                continue

            if not alt.attempted:
                # First attempt at this alternative
                alt.attempted = True
                self._notify_alternative_start(step, alt, exploration.current_alternative_idx)

                # Create a step from the alternative and execute it
                alt_step = self._explorer.create_step_from_alternative(alt, step)
                alt_result = self._execute_step(alt_step, intent, act, state)

                if alt_result.success:
                    # Alternative worked!
                    alt.succeeded = True
                    exploration.successful_approach = alt
                    self._notify_alternative_result(alt, True)
                    self._notify_exploration_complete(step, True)

                    # Copy result to original step
                    step.content = alt_step.content
                    step.new_content = alt_step.new_content
                    step.command = alt_step.command

                    logger.info(
                        "Alternative '%s' succeeded for step %s",
                        alt.approach,
                        step.id,
                    )
                    return alt_result

                # Alternative failed - try debug once
                alt.error = alt_result.error
                self._notify_alternative_result(alt, False)

            # Try debug on this alternative if not yet done
            if not alt.debug_attempted:
                alt.debug_attempted = True
                self._notify_debug_start(1)

                alt_step = self._explorer.create_step_from_alternative(alt, step)
                debug_success = self._debug_failure(
                    alt_step, state.current_contract, original_result, intent, act
                )

                if debug_success:
                    # Debug fix applied - retry the alternative
                    retry_result = self._execute_step(alt_step, intent, act, state)
                    if retry_result.success:
                        alt.succeeded = True
                        exploration.successful_approach = alt
                        self._notify_alternative_result(alt, True)
                        self._notify_exploration_complete(step, True)

                        # Copy result to original step
                        step.content = alt_step.content
                        step.new_content = alt_step.new_content
                        step.command = alt_step.command

                        logger.info(
                            "Alternative '%s' succeeded after debug for step %s",
                            alt.approach,
                            step.id,
                        )
                        return retry_result

            # Move to next alternative
            exploration.current_alternative_idx += 1

        # All alternatives exhausted
        exploration.all_failed = True
        self._notify_exploration_complete(step, False)
        logger.warning("All alternatives exhausted for step %s", step.id)
        return None

    def _collect_changed_files(self, state: ExecutionState) -> list[str]:
        """Collect all files changed during execution."""
        files = set()
        for contract in state.contracts:
            for step in contract.steps:
                if step.status == "completed" and step.target_file:
                    files.add(step.target_file)
        return sorted(files)

    def _generate_result_message(self, state: ExecutionState) -> str:
        """Generate a human-readable result message."""
        if state.status == LoopStatus.COMPLETED:
            files = self._collect_changed_files(state)
            return (
                f"Completed in {state.current_iteration} iteration(s).\n"
                f"Files changed: {', '.join(files) if files else 'none'}"
            )
        elif state.status == LoopStatus.FAILED:
            # Try to get a meaningful error message
            last_error = ""
            if state.iterations:
                last_iter = state.iterations[-1]
                last_error = last_iter.error or ""

                # If no explicit error, check for unfulfilled criteria
                if not last_error and state.current_contract:
                    unfulfilled = state.current_contract.get_unfulfilled_criteria()
                    if unfulfilled:
                        criteria_desc = [c.description for c in unfulfilled[:3]]
                        last_error = f"Unfulfilled criteria: {'; '.join(criteria_desc)}"
                        if len(unfulfilled) > 3:
                            last_error += f" (+{len(unfulfilled) - 3} more)"

            if not last_error:
                last_error = "Max iterations reached without completing all criteria"

            return f"Failed after {state.current_iteration} iteration(s): {last_error}"
        else:
            return f"Stopped at status: {state.status.value}"

    def preview_plan(self, state: ExecutionState) -> str:
        """Generate a preview of the execution plan."""
        lines = ["## Execution Plan Preview", ""]

        if state.intent:
            lines.append("### Intent")
            lines.append(state.intent.summary())
            lines.append("")

        if state.current_contract:
            lines.append("### Contract")
            lines.append(state.current_contract.summary())
            lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Observer Notifications
    # -------------------------------------------------------------------------

    def _notify_phase_change(self, status: LoopStatus) -> None:
        """Notify observer of phase change."""
        if self._observer is not None:
            self._observer.on_phase_change(status)

    def _notify_iteration_start(self, iteration: int, max_iterations: int) -> None:
        """Notify observer of iteration start."""
        if self._observer is not None:
            self._observer.on_iteration_start(iteration, max_iterations)

    def _notify_contract_built(self, contract: Contract) -> None:
        """Notify observer when contract is built."""
        if self._observer is not None:
            self._observer.on_contract_built(contract)

    def _notify_step_start(self, step: ContractStep) -> None:
        """Notify observer when step starts."""
        if self._observer is not None:
            self._observer.on_step_start(step)

    def _notify_step_complete(self, step: ContractStep, success: bool, output: str = "") -> None:
        """Notify observer when step completes."""
        if self._observer is not None:
            self._observer.on_step_complete(step, success, output)

    def _notify_criterion_verified(self, criterion: AcceptanceCriterion) -> None:
        """Notify observer when criterion is verified."""
        if self._observer is not None:
            self._observer.on_criterion_verified(criterion)

    def _notify_debug_start(self, attempt: int) -> None:
        """Notify observer when debug starts."""
        if self._observer is not None:
            self._observer.on_debug_start(attempt)

    def _notify_debug_diagnosis(self, diagnosis: DebugDiagnosis) -> None:
        """Notify observer of debug diagnosis."""
        if self._observer is not None:
            self._observer.on_debug_diagnosis(diagnosis)

    def _notify_command_output(self, line: str) -> None:
        """Notify observer of command output."""
        if self._observer is not None:
            self._observer.on_command_output(line)

    def _notify_complete(self, result: ExecutionResult) -> None:
        """Notify observer of completion."""
        if self._observer is not None:
            self._observer.on_complete(result)

    def _notify_error(self, error: str) -> None:
        """Notify observer of error."""
        if self._observer is not None:
            self._observer.on_error(error)

    def _notify_exploration_start(self, step: ContractStep, n_alternatives: int) -> None:
        """Notify observer when exploration starts."""
        if self._observer is not None:
            self._observer.on_exploration_start(step, n_alternatives)

    def _notify_alternative_start(self, step: ContractStep, alt: StepAlternative, idx: int) -> None:
        """Notify observer when trying an alternative."""
        if self._observer is not None:
            self._observer.on_alternative_start(step, alt, idx)

    def _notify_alternative_result(self, alt: StepAlternative, success: bool) -> None:
        """Notify observer of alternative result."""
        if self._observer is not None:
            self._observer.on_alternative_result(alt, success)

    def _notify_exploration_complete(self, step: ContractStep, success: bool) -> None:
        """Notify observer when exploration finishes."""
        if self._observer is not None:
            self._observer.on_exploration_complete(step, success)

    # -------------------------------------------------------------------------
    # Project Memory Integration
    # -------------------------------------------------------------------------

    def _record_session(
        self,
        state: ExecutionState,
        act: Act,
        result: ExecutionResult,
    ) -> None:
        """Record the coding session in project memory."""
        if self._project_memory is None:
            return

        try:
            outcome = "completed" if result.success else "failed"
            if state.status == LoopStatus.AWAITING_APPROVAL:
                outcome = "partial"

            self._project_memory.record_session(
                session_id=state.session_id,
                repo_path=act.repo_path,
                prompt_summary=state.prompt[:200],
                started_at=state.started_at,
                ended_at=state.completed_at or datetime.now(timezone.utc),
                outcome=outcome,
                files_changed=result.files_changed,
                intent_summary=state.intent.goal if state.intent else "",
                contract_fulfilled=result.success,
                iteration_count=result.total_iterations,
            )
            logger.debug("Recorded session: %s", state.session_id)
        except Exception as e:
            logger.error("Failed to record session %s: %s", state.session_id, e, exc_info=True)
            if self._session_logger:
                self._session_logger.log_error("executor", "session_record_failed",
                    f"Failed to record session in project memory: {e}", {
                        "session_id": state.session_id,
                        "exception_type": type(e).__name__,
                        "exception": str(e),
                    })

    def _record_change(
        self,
        session_id: str,
        act: Act,
        file_path: str,
        change_type: str,
        new_content: str,
        step_id: str | None = None,
        old_content: str | None = None,
        diff_summary: str = "",
    ) -> None:
        """Record a code change in project memory."""
        if self._project_memory is None:
            return

        try:
            import hashlib

            new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]
            old_hash = None
            if old_content:
                old_hash = hashlib.sha256(old_content.encode()).hexdigest()[:16]

            if not diff_summary:
                diff_summary = f"{change_type.capitalize()}d file ({len(new_content)} bytes)"

            self._project_memory.record_change(
                repo_path=act.repo_path,
                session_id=session_id,
                file_path=file_path,
                change_type=change_type,
                diff_summary=diff_summary,
                new_content_hash=new_hash,
                old_content_hash=old_hash,
                contract_step_id=step_id,
            )
        except Exception as e:
            logger.warning("Failed to record code change for %s: %s", file_path, e, exc_info=True)
            if self._session_logger:
                self._session_logger.log_warn("executor", "change_record_failed",
                    f"Failed to record change for {file_path}: {e}", {
                        "file_path": file_path,
                        "session_id": session_id,
                        "change_type": change_type,
                        "exception": str(e),
                    })

    def detect_corrections(
        self,
        session_id: str,
        act: Act,
    ) -> list[dict[str, Any]]:
        """Detect user corrections by comparing generated vs current content.

        Call this after a session to find where the user modified AI-generated code.
        These corrections are learning opportunities.

        Args:
            session_id: The session ID to check corrections for.
            act: The active Act with repository path.

        Returns:
            List of corrections found, each with:
            - file_path: Path to the corrected file
            - original_code: What was generated
            - corrected_code: Current content
            - correction_type: Inferred type of correction
        """
        corrections = []

        for file_path, generated_content in self._generated_content.items():
            try:
                current_content = self.sandbox.read_file(file_path)

                # Compare generated vs current
                if current_content != generated_content:
                    # User made changes - this is a correction
                    correction_type = self._infer_correction_type(
                        generated_content, current_content
                    )

                    correction = {
                        "file_path": file_path,
                        "original_code": generated_content,
                        "corrected_code": current_content,
                        "correction_type": correction_type,
                    }
                    corrections.append(correction)

                    # Record in project memory if available
                    if self._project_memory is not None:
                        inferred_rule = self._infer_correction_rule(
                            generated_content, current_content, correction_type
                        )
                        self._project_memory.record_correction(
                            repo_path=act.repo_path,
                            session_id=session_id,
                            file_path=file_path,
                            original_code=generated_content[:2000],
                            corrected_code=current_content[:2000],
                            correction_type=correction_type,
                            inferred_rule=inferred_rule,
                        )
                        logger.info(
                            "Detected correction in %s: %s",
                            file_path,
                            inferred_rule[:50] if inferred_rule else correction_type,
                        )

            except Exception as e:
                logger.warning("Failed to analyze user correction for %s: %s", file_path, e, exc_info=True)
                if self._session_logger:
                    self._session_logger.log_warn("executor", "correction_analysis_failed",
                        f"Could not analyze correction for {file_path}: {e}", {
                            "file_path": file_path,
                            "session_id": session_id,
                            "exception": str(e),
                        })

        return corrections

    def _infer_correction_type(
        self,
        original: str,
        corrected: str,
    ) -> str:
        """Infer the type of correction from the difference."""
        original_lines = original.splitlines()
        corrected_lines = corrected.splitlines()

        # Simple heuristics
        if len(corrected_lines) > len(original_lines) * 1.2:
            return "missing"  # User added significant content
        if len(corrected_lines) < len(original_lines) * 0.8:
            return "structure"  # User removed significant content

        # Check for naming changes
        import re
        orig_names = set(re.findall(r'\b[a-z_][a-z0-9_]*\b', original.lower()))
        corr_names = set(re.findall(r'\b[a-z_][a-z0-9_]*\b', corrected.lower()))
        if len(orig_names - corr_names) > 3 or len(corr_names - orig_names) > 3:
            return "naming"

        # Default to style
        return "style"

    def _infer_correction_rule(
        self,
        original: str,
        corrected: str,
        correction_type: str,
    ) -> str:
        """Attempt to infer a rule from the correction.

        This is a simple heuristic. For better results, use LLM.
        """
        if self._llm is None:
            # Simple heuristic rules
            if correction_type == "naming":
                return "Prefer different naming conventions"
            elif correction_type == "missing":
                return "Include more comprehensive implementation"
            elif correction_type == "structure":
                return "Use simpler code structure"
            return "Code style preference"

        # Use LLM to infer rule
        try:
            prompt = f"""Analyze this code correction and infer a single rule:

ORIGINAL (AI-generated):
```
{original[:1000]}
```

CORRECTED (by user):
```
{corrected[:1000]}
```

Output a single sentence rule like: "Use dataclasses instead of TypedDict"
"""
            response = self._llm.chat(
                system="You analyze code corrections and infer coding rules. Output a single concise rule.",
                user=prompt,
                temperature=0.2,
            )
            return response.strip()[:200]
        except Exception as e:
            logger.debug("Failed to generate rule description: %s", e)
            return f"Code {correction_type} preference"
