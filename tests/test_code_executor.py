"""Tests for CodeExecutor - the main execution loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import (
    CodeExecutor,
    CodeSandbox,
    ExecutionState,
    ExecutionResult,
    LoopStatus,
    PerspectiveManager,
    Phase,
    ANALYST,
    ARCHITECT,
    ENGINEER,
    CRITIC,
    DEBUGGER,
    DebugDiagnosis,
)
from reos.play_fs import Act


class TestPerspectives:
    """Tests for perspective management."""

    def test_shift_to_phase(self) -> None:
        """Should shift to phase perspective."""
        manager = PerspectiveManager(llm=None)

        perspective = manager.shift_to(Phase.INTENT)

        assert perspective == ANALYST
        assert manager.current_perspective == ANALYST

    def test_get_perspective_without_shift(self) -> None:
        """Should get perspective without changing current."""
        manager = PerspectiveManager(llm=None)
        manager.shift_to(Phase.INTENT)

        perspective = manager.get_perspective(Phase.BUILD)

        assert perspective == ENGINEER
        assert manager.current_perspective == ANALYST  # Unchanged

    def test_phase_perspectives_mapping(self) -> None:
        """Should have correct phase-perspective mapping."""
        manager = PerspectiveManager(llm=None)

        assert manager.get_perspective(Phase.INTENT) == ANALYST
        assert manager.get_perspective(Phase.CONTRACT) == ARCHITECT
        assert manager.get_perspective(Phase.BUILD) == ENGINEER
        assert manager.get_perspective(Phase.VERIFY) == CRITIC

    def test_perspective_has_system_prompt(self) -> None:
        """Each perspective should have a system prompt."""
        perspectives = [ANALYST, ARCHITECT, ENGINEER, CRITIC, DEBUGGER]

        for p in perspectives:
            assert p.system_prompt
            assert len(p.system_prompt) > 100

    def test_debugger_perspective_exists(self) -> None:
        """DEBUGGER perspective should exist and be properly configured."""
        assert DEBUGGER.name == "Debugger"
        assert DEBUGGER.role == "Failure Analysis Specialist"
        assert "root_cause" in DEBUGGER.system_prompt
        assert "failure_type" in DEBUGGER.system_prompt

    def test_phase_debug_maps_to_debugger(self) -> None:
        """Phase.DEBUG should map to DEBUGGER perspective."""
        manager = PerspectiveManager(llm=None)
        perspective = manager.get_perspective(Phase.DEBUG)
        assert perspective == DEBUGGER

    def test_loop_status_debugging_exists(self) -> None:
        """LoopStatus.DEBUGGING should exist."""
        assert LoopStatus.DEBUGGING.value == "debug"


class TestCodeExecutor:
    """Tests for the main executor."""

    def test_init(self, temp_git_repo: Path) -> None:
        """Should initialize executor."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)

        assert executor.sandbox == sandbox

    def test_execute_creates_state(self, temp_git_repo: Path) -> None:
        """Execute should create execution state."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a hello function",
            act,
            max_iterations=1,  # Limit for testing
        )

        assert isinstance(result, ExecutionResult)
        assert isinstance(result.state, ExecutionState)

    def test_execute_discovers_intent(self, temp_git_repo: Path) -> None:
        """Execute should discover intent."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a hello function",
            act,
            max_iterations=1,
        )

        assert result.state.intent is not None

    def test_execute_builds_contract(self, temp_git_repo: Path) -> None:
        """Execute should build contract."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=1,
        )

        assert result.state.current_contract is not None
        assert len(result.state.contracts) > 0

    def test_execute_respects_max_iterations(self, temp_git_repo: Path) -> None:
        """Execute should stop at max iterations."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a complex feature",
            act,
            max_iterations=2,
        )

        assert result.state.current_iteration <= 2

    def test_execute_tracks_iterations(self, temp_git_repo: Path) -> None:
        """Execute should track iteration history."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=2,
        )

        assert len(result.state.iterations) > 0
        for iteration in result.state.iterations:
            assert iteration.started_at is not None

    def test_step_execution_with_session_logging(self, temp_git_repo: Path) -> None:
        """Exercise full step execution path including session logging.

        This test catches attribute errors in the step execution path (like
        accessing non-existent attributes on ContractStep) by running through
        the complete execution loop with session logging enabled.

        DEBUG STRATEGY: If this test fails, check:
        1. Does contract have steps? (decomposition working)
        2. Were steps attempted? (execution loop running)
        3. What was the error message? (captured in result)
        """
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        # Use "add" action verb - this triggers create_file action in heuristic decomposition
        # Avoid game/web keywords which trigger edit_file steps in criteria generation
        result = executor.execute(
            "add a calculator module",  # Simple verb + target = create_file step
            act,
            max_iterations=2,
        )

        # Diagnostic info for debugging test failures
        intent = result.state.intent
        all_contracts = result.state.contracts
        all_steps = []
        for c in all_contracts:
            all_steps.extend(c.steps)

        diag_info = {
            "status": result.state.status.value,
            "message": result.message[:200] if result.message else None,
            "iterations": result.state.current_iteration,
            "num_contracts": len(all_contracts),
            "total_steps": len(all_steps),
            "step_statuses": [s.status for s in all_steps],
            "step_actions": [s.action for s in all_steps],
            # Intent debugging
            "action_verb": intent.prompt_intent.action_verb if intent else None,
            "target": intent.prompt_intent.target if intent else None,
        }

        # Must have at least one contract with steps
        assert len(all_contracts) > 0, f"No contracts built. Diag: {diag_info}"
        assert len(all_steps) > 0, f"No steps in any contract. Diag: {diag_info}"

        # Check for steps that were at least started (across ALL contracts)
        # "completed" or "failed" means step execution was attempted
        # "pending" means step was never attempted
        attempted_steps = [s for s in all_steps if s.status != "pending"]

        # More detailed diagnostic message
        if len(attempted_steps) == 0:
            # Show step details to help debug why nothing was attempted
            step_details = [
                f"Step {i}: status={s.status}, action={s.action}, target={s.target_file}"
                for i, s in enumerate(all_steps)
            ]
            diag_info["step_details"] = step_details

        # At least one step should have been attempted across all contracts
        # This exercises the session logging code path
        assert len(attempted_steps) > 0, (
            f"No steps were attempted - session logging path not tested.\n"
            f"Diagnostic info: {diag_info}"
        )

        # Verify step attributes that session logging code uses
        # This catches typos like `step.criterion` instead of `step.action`
        for step in all_steps:
            # These are the attributes log_step_start needs - catch typos early
            assert hasattr(step, "action"), "ContractStep missing 'action' attribute"
            assert hasattr(step, "target_file"), "ContractStep missing 'target_file' attribute"
            assert hasattr(step, "description"), "ContractStep missing 'description' attribute"
            assert hasattr(step, "id"), "ContractStep missing 'id' attribute"
            # Verify action is a valid string (not None, not a method)
            assert step.action in ("create_file", "edit_file", "run_command"), (
                f"Invalid step action: {step.action!r} for step {step.description}"
            )
            # These attributes should NOT exist (catch accidental usage)
            assert not hasattr(step, "criterion"), (
                "ContractStep should not have 'criterion' attribute. "
                "Use 'target_criteria' (list of IDs) instead."
            )


class TestExecutionState:
    """Tests for execution state management."""

    def test_initial_status(self) -> None:
        """Initial status should be pending."""
        state = ExecutionState(
            session_id="test",
            prompt="test prompt",
        )

        assert state.status == LoopStatus.PENDING

    def test_has_timestamps(self) -> None:
        """Should have started_at timestamp."""
        state = ExecutionState(
            session_id="test",
            prompt="test prompt",
        )

        assert state.started_at is not None


class TestExecutionResult:
    """Tests for execution results."""

    def test_result_message(self, temp_git_repo: Path) -> None:
        """Result should have message."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=1,
        )

        assert result.message
        assert len(result.message) > 0

    def test_result_has_iteration_count(self, temp_git_repo: Path) -> None:
        """Result should have iteration count."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=2,
        )

        assert result.total_iterations >= 0


class TestPreviewPlan:
    """Tests for plan preview generation."""

    def test_preview_includes_intent(self, temp_git_repo: Path) -> None:
        """Preview should include intent summary."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=1,
        )

        preview = executor.preview_plan(result.state)

        assert "Intent" in preview or "Plan" in preview

    def test_preview_includes_contract(self, temp_git_repo: Path) -> None:
        """Preview should include contract summary."""
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        result = executor.execute(
            "add a function",
            act,
            max_iterations=1,
        )

        preview = executor.preview_plan(result.state)

        assert "Contract" in preview or "Criteria" in preview


class TestDebugDiagnosis:
    """Tests for debug diagnosis structure."""

    def test_debug_diagnosis_creation(self) -> None:
        """Should create DebugDiagnosis with all fields."""
        diagnosis = DebugDiagnosis(
            root_cause="Missing import statement",
            failure_type="code_bug",
            fix_location={"file": "src/example.py", "area": "imports"},
            fix_action={"old_str": "# imports", "new_str": "import os\n# imports"},
            confidence="high",
        )

        assert diagnosis.root_cause == "Missing import statement"
        assert diagnosis.failure_type == "code_bug"
        assert diagnosis.fix_location["file"] == "src/example.py"
        assert diagnosis.confidence == "high"
        assert not diagnosis.needs_more_info

    def test_debug_diagnosis_needs_more_info(self) -> None:
        """Should handle needs_more_info flag."""
        diagnosis = DebugDiagnosis(
            root_cause="Unclear error",
            failure_type="unknown",
            fix_location={},
            fix_action={},
            confidence="low",
            needs_more_info=True,
        )

        assert diagnosis.needs_more_info is True
        assert diagnosis.confidence == "low"

    def test_debug_diagnosis_with_raw_output(self) -> None:
        """Should store raw LLM output."""
        raw = '{"root_cause": "test", "failure_type": "code_bug"}'
        diagnosis = DebugDiagnosis(
            root_cause="test",
            failure_type="code_bug",
            fix_location={},
            fix_action={},
            confidence="medium",
            raw_output=raw,
        )

        assert diagnosis.raw_output == raw


class TestCriticPerspective:
    """Tests for the Critic perspective's execution-first approach."""

    def test_critic_emphasizes_execution(self) -> None:
        """Critic should emphasize test execution as ground truth."""
        assert "GROUND TRUTH" in CRITIC.system_prompt
        assert "execution" in CRITIC.system_prompt.lower()
        assert "RUN THE TESTS" in CRITIC.system_prompt

    def test_critic_mentions_test_output(self) -> None:
        """Critic should trust test output as evidence."""
        assert "tests pass" in CRITIC.system_prompt.lower() or "test" in CRITIC.system_prompt.lower()
        assert "evidence" in CRITIC.system_prompt.lower()

    def test_critic_is_skeptical_of_ai(self) -> None:
        """Critic should be skeptical of AI-generated code."""
        assert "skeptical" in CRITIC.system_prompt.lower()
        assert "AI" in CRITIC.system_prompt
        assert "guilty until proven innocent" in CRITIC.system_prompt
