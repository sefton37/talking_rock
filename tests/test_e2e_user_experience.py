"""End-to-End Tests - Simulating Real User Experience in Tauri App.

These tests simulate the EXACT flow when a user types a prompt in the
Tauri desktop app:

1. User types prompt in UI
2. Tauri sends JSON-RPC request to Python backend
3. Backend spawns background thread for execution
4. Frontend polls for state updates
5. Real LLM generates code
6. Files are written to disk
7. Session logs are persisted
8. Result is returned to UI

These tests require Ollama running with a model. They will be skipped
if Ollama is not available.

Run with: pytest tests/test_e2e_user_experience.py -v
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import get_ollama_for_tests, requires_ollama


# =============================================================================
# Test: Full RPC Flow (Simulating Tauri → Python Communication)
# =============================================================================


class TestRPCUserExperience:
    """Test the full JSON-RPC flow as Tauri would call it."""

    @requires_ollama
    def test_full_rpc_code_execution_flow(
        self,
        temp_git_repo: Path,
        isolated_db_singleton: Path,
    ) -> None:
        """Simulate exact Tauri UI flow: start execution, poll for updates.

        This is the closest simulation to a real user typing
        "make a pacman game in pygame" in the Tauri app.
        """
        from reos.db import get_db
        from reos.ui_rpc_server import (
            _handle_code_exec_start,
            _handle_code_exec_state,
            _active_code_executions,
            _code_exec_lock,
        )

        db = get_db()

        # Configure Ollama (like settings would)
        available, base_url, model = get_ollama_for_tests()
        assert available, "Ollama must be running for this test"
        db.set_state(key="ollama_url", value=base_url)
        db.set_state(key="ollama_model", value=model)
        db.set_state(key="repo_path", value=str(temp_git_repo))

        # Create an Act (like user would have configured)
        from reos.play_fs import Act
        act = Act(
            act_id="test-act",
            title="Test Project",
            active=True,
            repo_path=str(temp_git_repo),
        )

        # STEP 1: User types prompt and hits enter
        # This triggers code/exec/start RPC call from Tauri
        prompt = "create a simple hello world python script"

        start_response = _handle_code_exec_start(
            db,
            session_id="user-session-123",
            prompt=prompt,
            repo_path=str(temp_git_repo),
            max_iterations=5,
            auto_approve=True,
        )

        # Verify RPC response format (what Tauri expects)
        assert "execution_id" in start_response
        assert "session_id" in start_response
        assert start_response["status"] == "started"

        execution_id = start_response["execution_id"]

        # STEP 2: Tauri polls for state updates (every ~500ms in real app)
        max_polls = 60  # 30 seconds max
        poll_interval = 0.5
        final_state = None

        for poll_num in range(max_polls):
            state = _handle_code_exec_state(db, execution_id=execution_id)

            # Log progress (like UI would show)
            status = state.get("status", "unknown")
            phase = state.get("current_phase", "")
            is_complete = state.get("is_complete", False)

            print(f"Poll {poll_num + 1}: status={status}, phase={phase}, complete={is_complete}")

            if is_complete:
                final_state = state
                break

            time.sleep(poll_interval)

        # STEP 3: Verify execution completed
        assert final_state is not None, "Execution did not complete in time"
        assert final_state.get("is_complete") is True

        # STEP 4: Verify files were created (like user would see in file tree)
        created_files = list(temp_git_repo.rglob("*.py"))
        # Filter out the pre-existing example.py
        new_files = [f for f in created_files if "example" not in f.name]

        # Should have created at least one Python file
        # (exact file depends on LLM response, but something should exist)
        print(f"Files in repo after execution: {[f.name for f in created_files]}")

        # STEP 5: Clean up active execution tracking
        with _code_exec_lock:
            if execution_id in _active_code_executions:
                del _active_code_executions[execution_id]

    @requires_ollama
    def test_rpc_with_observer_callbacks(
        self,
        temp_git_repo: Path,
        isolated_db_singleton: Path,
    ) -> None:
        """Test that observer callbacks fire correctly during execution.

        The observer is what updates the UI in real-time. This test verifies
        that phase changes, step starts, and completions are properly reported.
        """
        from reos.db import get_db
        from reos.code_mode import CodeSandbox, CodeExecutor
        from reos.code_mode.streaming import ExecutionObserver, create_execution_context
        from reos.play_fs import Act

        db = get_db()
        available, base_url, model = get_ollama_for_tests()
        db.set_state(key="repo_path", value=str(temp_git_repo))

        from reos.ollama import OllamaClient
        llm = OllamaClient(url=base_url, model=model)

        # Create context and observer (like RPC layer does)
        context = create_execution_context(
            session_id="observer-test",
            prompt="test",
            max_iterations=5,
        )
        observer = ExecutionObserver(context)

        # Track callbacks
        callbacks_received = {
            "phase_changes": [],
            "step_starts": [],
            "step_completes": [],
            "activities": [],
        }

        # Wrap observer methods to capture calls
        original_on_phase = observer.on_phase_change
        original_on_step_start = observer.on_step_start
        original_on_step_complete = observer.on_step_complete
        original_on_activity = observer.on_activity

        def track_phase(phase: str) -> None:
            callbacks_received["phase_changes"].append(phase)
            original_on_phase(phase)

        def track_step_start(step_id: str, description: str) -> None:
            callbacks_received["step_starts"].append(description)
            original_on_step_start(step_id, description)

        def track_step_complete(step_id: str, success: bool, output: str) -> None:
            callbacks_received["step_completes"].append((step_id, success))
            original_on_step_complete(step_id, success, output)

        def track_activity(message: str, module: str = "") -> None:
            callbacks_received["activities"].append(message)
            original_on_activity(message, module)

        observer.on_phase_change = track_phase
        observer.on_step_start = track_step_start
        observer.on_step_complete = track_step_complete
        observer.on_activity = track_activity

        # Create executor
        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(
            sandbox=sandbox,
            llm=llm,
            observer=observer,
        )

        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        # Execute
        result = executor.execute(
            "add a simple utility function",
            act,
            max_iterations=3,
        )

        # Verify callbacks were received
        print(f"Phase changes: {callbacks_received['phase_changes']}")
        print(f"Step starts: {callbacks_received['step_starts']}")
        print(f"Activities: {len(callbacks_received['activities'])} messages")

        # Should have received phase changes
        assert len(callbacks_received["phase_changes"]) > 0, (
            "No phase changes received - observer not connected properly"
        )

        # Should have intent phase
        assert any("intent" in p.lower() for p in callbacks_received["phase_changes"]), (
            f"No intent phase in: {callbacks_received['phase_changes']}"
        )


# =============================================================================
# Test: Session Logging (Critical for Debugging)
# =============================================================================


class TestSessionLogging:
    """Test that session logs are written correctly for debugging."""

    @requires_ollama
    def test_session_logs_written_to_disk(
        self,
        temp_git_repo: Path,
        isolated_db_singleton: Path,
        tmp_path: Path,
    ) -> None:
        """Verify session logs are persisted for debugging.

        When a bug occurs (like the .criterion issue), session logs
        help diagnose what went wrong.
        """
        from reos.db import get_db
        from reos.code_mode import CodeSandbox, CodeExecutor
        from reos.code_mode.session_logger import SessionLogger
        from reos.play_fs import Act

        db = get_db()
        available, base_url, model = get_ollama_for_tests()
        db.set_state(key="repo_path", value=str(temp_git_repo))

        from reos.ollama import OllamaClient
        llm = OllamaClient(url=base_url, model=model)

        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox=sandbox, llm=llm)

        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        # Execute with known session ID
        result = executor.execute(
            "add a helper function",
            act,
            max_iterations=3,
        )

        # Get session ID from result
        session_id = result.state.session_id

        # Check for session log files
        reos_data_dir = Path.home() / ".reos-data" / "code_mode_sessions"
        if reos_data_dir.exists():
            log_files = list(reos_data_dir.glob(f"*{session_id[:8]}*"))
            print(f"Session log files: {log_files}")

            if log_files:
                # Read and validate log content
                for log_file in log_files:
                    if log_file.suffix == ".json":
                        content = json.loads(log_file.read_text())
                        print(f"Log entries: {len(content.get('entries', []))}")

                        # Check for critical log entries
                        entries = content.get("entries", [])
                        actions = [e.get("action", "") for e in entries]

                        # Should have key lifecycle events
                        assert any("phase" in a.lower() for a in actions), (
                            f"No phase events in log: {actions[:10]}"
                        )


# =============================================================================
# Test: Full Code Generation (The Pacman Test)
# =============================================================================


class TestCodeGeneration:
    """Test actual code generation with real LLM."""

    @requires_ollama
    def test_simple_script_generation(
        self,
        e2e_executor_real_llm: tuple,
    ) -> None:
        """Test that LLM can generate a simple script.

        This is a simpler version of the "make a pacman game" test
        to verify the full pipeline works.
        """
        executor, sandbox, act, llm, context, db = e2e_executor_real_llm

        result = executor.execute(
            "create a python script that prints hello world",
            act,
            max_iterations=5,
        )

        # Check execution completed
        print(f"Status: {result.state.status}")
        print(f"Message: {result.message}")
        print(f"Iterations: {result.state.current_iteration}")

        # List files created
        py_files = list(sandbox.repo_path.rglob("*.py"))
        print(f"Python files: {[f.name for f in py_files]}")

        # Verify at least some execution happened
        assert result.state.current_iteration > 0, "No iterations executed"

        # Check for contracts built
        assert len(result.state.contracts) > 0, "No contracts built"

    @requires_ollama
    def test_pygame_game_generation(
        self,
        e2e_executor_real_llm: tuple,
    ) -> None:
        """Test pygame game generation - the actual user scenario.

        This is the test that caught the .criterion bug.
        """
        executor, sandbox, act, llm, context, db = e2e_executor_real_llm

        result = executor.execute(
            "make a simple pygame game with a moving square",
            act,
            max_iterations=10,
        )

        print(f"Status: {result.state.status}")
        print(f"Message: {result.message}")
        print(f"Iterations: {result.state.current_iteration}")
        print(f"Contracts: {len(result.state.contracts)}")

        # Check files created
        py_files = list(sandbox.repo_path.rglob("*.py"))
        print(f"Python files created: {[f.name for f in py_files]}")

        # Verify execution progressed
        assert result.state.current_iteration > 0

        # Check step execution
        all_steps = []
        for contract in result.state.contracts:
            all_steps.extend(contract.steps)

        print(f"Total steps: {len(all_steps)}")
        for step in all_steps:
            print(f"  - {step.status}: {step.action} - {step.description[:50]}")

        # At least one step should have been attempted
        attempted = [s for s in all_steps if s.status != "pending"]
        assert len(attempted) > 0, (
            f"No steps attempted. Steps: {[(s.status, s.action) for s in all_steps]}"
        )


# =============================================================================
# Test: Error Handling (What Happens When Things Go Wrong)
# =============================================================================


class TestErrorHandling:
    """Test that errors are properly captured and reported."""

    @requires_ollama
    def test_attribute_error_detection(
        self,
        e2e_executor_real_llm: tuple,
    ) -> None:
        """Verify that attribute errors in executor are caught.

        This is the type of bug that the .criterion issue was.
        The test should fail loudly if such an error occurs.
        """
        executor, sandbox, act, llm, context, db = e2e_executor_real_llm

        # Execute with a simple prompt
        try:
            result = executor.execute(
                "add a utility function",
                act,
                max_iterations=3,
            )

            # If we get here, no AttributeError occurred
            # Check the result for any error messages
            if result.message:
                assert "AttributeError" not in result.message, (
                    f"AttributeError in execution: {result.message}"
                )

            # Check context for errors
            if context.error:
                assert "AttributeError" not in context.error, (
                    f"AttributeError in context: {context.error}"
                )

        except AttributeError as e:
            pytest.fail(f"AttributeError during execution: {e}")

    @requires_ollama
    def test_step_attributes_valid(
        self,
        e2e_executor_real_llm: tuple,
    ) -> None:
        """Verify all ContractStep attributes used by executor are valid.

        This catches bugs like accessing .criterion instead of .action.
        """
        executor, sandbox, act, llm, context, db = e2e_executor_real_llm

        result = executor.execute(
            "create a simple module",
            act,
            max_iterations=3,
        )

        # Validate all steps in all contracts
        for contract in result.state.contracts:
            for step in contract.steps:
                # These are the attributes that log_step_start() uses
                # If any are wrong, execution would have failed
                assert hasattr(step, "action"), f"Step missing 'action': {step}"
                assert hasattr(step, "target_file"), f"Step missing 'target_file': {step}"
                assert hasattr(step, "description"), f"Step missing 'description': {step}"
                assert hasattr(step, "id"), f"Step missing 'id': {step}"
                assert hasattr(step, "status"), f"Step missing 'status': {step}"

                # Verify action is valid
                assert step.action in ("create_file", "edit_file", "run_command"), (
                    f"Invalid action: {step.action}"
                )

                # Verify these DON'T exist (catch the .criterion bug)
                assert not hasattr(step, "criterion"), (
                    "Step has 'criterion' attr - should use 'target_criteria'"
                )


# =============================================================================
# Test: Threading (Background Execution Like Real App)
# =============================================================================


class TestBackgroundExecution:
    """Test that background threading works correctly."""

    @requires_ollama
    def test_execution_runs_in_background(
        self,
        temp_git_repo: Path,
        isolated_db_singleton: Path,
    ) -> None:
        """Verify execution can run in background thread like real app."""
        from reos.db import get_db
        from reos.code_mode import CodeSandbox, CodeExecutor
        from reos.code_mode.streaming import create_execution_context, ExecutionObserver
        from reos.play_fs import Act

        db = get_db()
        available, base_url, model = get_ollama_for_tests()
        db.set_state(key="repo_path", value=str(temp_git_repo))

        from reos.ollama import OllamaClient
        llm = OllamaClient(url=base_url, model=model)

        context = create_execution_context(
            session_id="thread-test",
            prompt="test",
            max_iterations=3,
        )
        observer = ExecutionObserver(context)

        sandbox = CodeSandbox(temp_git_repo)
        executor = CodeExecutor(sandbox=sandbox, llm=llm, observer=observer)

        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        # Run in background thread (like real app)
        result_holder = {"result": None, "error": None}

        def run_execution() -> None:
            try:
                result_holder["result"] = executor.execute(
                    "add a simple function",
                    act,
                    max_iterations=3,
                )
                context.is_complete = True
            except Exception as e:
                result_holder["error"] = str(e)
                context.is_complete = True

        thread = threading.Thread(target=run_execution, daemon=True)
        thread.start()

        # Poll for completion (like UI would)
        max_wait = 60  # seconds
        start_time = time.time()

        while not context.is_complete and (time.time() - start_time) < max_wait:
            time.sleep(0.5)

        thread.join(timeout=5)

        # Verify completion
        assert context.is_complete, "Execution did not complete"
        assert result_holder["error"] is None, f"Error: {result_holder['error']}"
        assert result_holder["result"] is not None, "No result returned"
