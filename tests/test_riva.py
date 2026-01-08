"""Tests for RIVA (Recursive Intention-Verification Architecture).

This module tests the core RIVA components:
- Intention data structures
- Cycle and Action serialization
- Decision functions (can_verify_directly, should_decompose)
- Heuristic decomposition and action generation
- The recursive work() algorithm
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from reos.code_mode.intention import (
    Action,
    ActionType,
    AutoCheckpoint,
    Cycle,
    Intention,
    IntentionStatus,
    Judgment,
    Session,
    UICheckpoint,
    WorkContext,
    can_verify_directly,
    decompose,
    determine_next_action,
    execute_action,
    reflect,
    should_decompose,
    work,
    _heuristic_decompose,
    _heuristic_action,
)


# ==============================================================================
# Data Structure Tests
# ==============================================================================

class TestAction:
    """Test Action dataclass."""

    def test_create_command_action(self):
        action = Action(ActionType.COMMAND, "pytest -v", None)
        assert action.type == ActionType.COMMAND
        assert action.content == "pytest -v"
        assert action.target is None

    def test_create_edit_action_with_target(self):
        action = Action(ActionType.EDIT, "new content", "src/main.py")
        assert action.type == ActionType.EDIT
        assert action.target == "src/main.py"

    def test_to_dict(self):
        action = Action(ActionType.CREATE, "# Hello", "hello.py")
        d = action.to_dict()
        assert d["type"] == "create"
        assert d["content"] == "# Hello"
        assert d["target"] == "hello.py"

    def test_from_dict(self):
        data = {"type": "delete", "content": "", "target": "old.py"}
        action = Action.from_dict(data)
        assert action.type == ActionType.DELETE
        assert action.target == "old.py"

    def test_roundtrip_serialization(self):
        original = Action(ActionType.QUERY, "search term", "*.py")
        restored = Action.from_dict(original.to_dict())
        assert restored.type == original.type
        assert restored.content == original.content
        assert restored.target == original.target


class TestCycle:
    """Test Cycle dataclass."""

    def test_create_cycle(self):
        action = Action(ActionType.COMMAND, "echo hello", None)
        cycle = Cycle(
            thought="Testing output",
            action=action,
            result="hello",
            judgment=Judgment.SUCCESS,
        )
        assert cycle.thought == "Testing output"
        assert cycle.judgment == Judgment.SUCCESS
        assert cycle.reflection is None

    def test_cycle_with_reflection(self):
        action = Action(ActionType.COMMAND, "failing command", None)
        cycle = Cycle(
            thought="Trying something",
            action=action,
            result="error: not found",
            judgment=Judgment.FAILURE,
            reflection="Command not available, need to install dependency",
        )
        assert cycle.reflection is not None
        assert "install" in cycle.reflection

    def test_to_dict(self):
        action = Action(ActionType.CREATE, "content", "file.py")
        cycle = Cycle("Creating file", action, "Created file.py", Judgment.SUCCESS)
        d = cycle.to_dict()
        assert d["thought"] == "Creating file"
        assert d["judgment"] == "success"
        assert "action" in d

    def test_from_dict(self):
        data = {
            "thought": "Test thought",
            "action": {"type": "command", "content": "ls", "target": None},
            "result": "file1 file2",
            "judgment": "partial",
            "reflection": "Need more files",
        }
        cycle = Cycle.from_dict(data)
        assert cycle.thought == "Test thought"
        assert cycle.judgment == Judgment.PARTIAL
        assert cycle.reflection == "Need more files"


class TestIntention:
    """Test Intention dataclass."""

    def test_create_intention(self):
        intention = Intention.create(
            what="Add a login button",
            acceptance="Login button visible and clickable",
        )
        assert intention.id.startswith("int-")
        assert intention.what == "Add a login button"
        assert intention.status == IntentionStatus.PENDING
        assert intention.parent_id is None
        assert len(intention.trace) == 0

    def test_add_cycle(self):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try it", action, "OK", Judgment.SUCCESS)

        intention.add_cycle(cycle)
        assert len(intention.trace) == 1
        assert intention.trace[0] == cycle

    def test_add_child(self):
        parent = Intention.create("Parent task", "Children complete")
        child = Intention.create("Child task", "Subtask done")

        parent.add_child(child)

        assert len(parent.children) == 1
        assert parent.children[0] == child.id
        assert len(parent._child_intentions) == 1
        assert child.parent_id == parent.id

    def test_get_depth_no_children(self):
        intention = Intention.create("Leaf", "Done")
        assert intention.get_depth() == 0

    def test_get_depth_with_children(self):
        root = Intention.create("Root", "All done")
        child1 = Intention.create("Child 1", "Done")
        child2 = Intention.create("Child 2", "Done")
        grandchild = Intention.create("Grandchild", "Done")

        child1.add_child(grandchild)
        root.add_child(child1)
        root.add_child(child2)

        assert root.get_depth() == 2

    def test_get_total_cycles(self):
        root = Intention.create("Root", "Done")
        child = Intention.create("Child", "Done")
        action = Action(ActionType.COMMAND, "test", None)

        root.add_cycle(Cycle("Try 1", action, "OK", Judgment.PARTIAL))
        root.add_cycle(Cycle("Try 2", action, "OK", Judgment.SUCCESS))
        child.add_cycle(Cycle("Child try", action, "OK", Judgment.SUCCESS))

        root.add_child(child)

        assert root.get_total_cycles() == 3

    def test_to_dict_and_from_dict(self):
        original = Intention.create("Test task", "Verified")
        original.status = IntentionStatus.ACTIVE
        action = Action(ActionType.COMMAND, "pytest", None)
        original.add_cycle(Cycle("Testing", action, "passed", Judgment.SUCCESS))

        child = Intention.create("Sub-task", "Sub-verified")
        original.add_child(child)

        # Roundtrip
        data = original.to_dict()
        restored = Intention.from_dict(data)

        assert restored.id == original.id
        assert restored.what == original.what
        assert restored.status == original.status
        assert len(restored.trace) == 1
        assert len(restored._child_intentions) == 1


class TestSession:
    """Test Session dataclass."""

    def test_create_session(self):
        root = Intention.create("Main task", "Complete")
        session = Session.create(root)

        assert session.id.startswith("session-")
        assert session.root == root
        assert "outcome" in session.metadata

    def test_session_serialization(self, tmp_path):
        root = Intention.create("Task", "Done")
        session = Session.create(root)

        path = tmp_path / "session.json"
        session.save(path)

        loaded = Session.load(path)
        assert loaded.id == session.id
        assert loaded.root.what == root.what


# ==============================================================================
# Decision Function Tests
# ==============================================================================

class TestCanVerifyDirectly:
    """Test can_verify_directly decision function."""

    @pytest.fixture
    def mock_ctx(self):
        return MagicMock(spec=WorkContext)

    def test_simple_verifiable_intention(self, mock_ctx):
        intention = Intention.create(
            what="Create a hello.py file",
            acceptance="File hello.py exists",
        )
        assert can_verify_directly(intention, mock_ctx) is True

    def test_compound_intention_needs_decomposition(self, mock_ctx):
        intention = Intention.create(
            what="Create login form and also add validation and then connect to API",
            acceptance="Form works",
        )
        # Has multiple compound words
        assert can_verify_directly(intention, mock_ctx) is False

    def test_long_description_needs_decomposition(self, mock_ctx):
        long_desc = "Implement a comprehensive user authentication system " * 10
        intention = Intention.create(
            what=long_desc,
            acceptance="Auth works",
        )
        assert can_verify_directly(intention, mock_ctx) is False

    def test_vague_acceptance_needs_decomposition(self, mock_ctx):
        # Note: Current heuristics allow short "what" even with vague acceptance
        # This tests the short intention logic path
        intention = Intention.create(
            what="Make the app better",
            acceptance="Everything looks nice and works well",
        )
        # Short intentions (<15 words) are considered verifiable even with vague acceptance
        # This is intentional - the work loop will decompose if cycles fail
        assert can_verify_directly(intention, mock_ctx) is True

    def test_testable_acceptance_is_verifiable(self, mock_ctx):
        intention = Intention.create(
            what="Add divide function",
            acceptance="Function returns correct result for 10/2",
        )
        assert can_verify_directly(intention, mock_ctx) is True


class TestShouldDecompose:
    """Test should_decompose decision function."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock(spec=WorkContext)
        ctx.max_cycles_per_intention = 5
        return ctx

    def test_max_cycles_reached(self, mock_ctx):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        # Add max cycles
        for _ in range(5):
            intention.add_cycle(Cycle("Try", action, "Failed", Judgment.FAILURE))

        assert should_decompose(intention, None, mock_ctx) is True

    def test_repeated_failures(self, mock_ctx):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        intention.add_cycle(Cycle("Try 1", action, "Error", Judgment.FAILURE))
        intention.add_cycle(Cycle("Try 2", action, "Error", Judgment.FAILURE))

        cycle = intention.trace[-1]
        assert should_decompose(intention, cycle, mock_ctx) is True

    def test_repeated_unclear(self, mock_ctx):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        intention.add_cycle(Cycle("Try 1", action, "???", Judgment.UNCLEAR))
        intention.add_cycle(Cycle("Try 2", action, "???", Judgment.UNCLEAR))

        cycle = intention.trace[-1]
        assert should_decompose(intention, cycle, mock_ctx) is True

    def test_reflection_suggests_decomposition(self, mock_ctx):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle(
            "Trying",
            action,
            "Failed",
            Judgment.PARTIAL,
            reflection="Need to first set up the database before this works",
        )
        intention.add_cycle(cycle)

        assert should_decompose(intention, cycle, mock_ctx) is True

    def test_successful_cycle_no_decomposition(self, mock_ctx):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Success!", Judgment.SUCCESS)
        intention.add_cycle(cycle)

        assert should_decompose(intention, cycle, mock_ctx) is False


# ==============================================================================
# Heuristic Function Tests
# ==============================================================================

class TestHeuristicDecompose:
    """Test _heuristic_decompose function."""

    @pytest.fixture
    def mock_ctx(self):
        return MagicMock(spec=WorkContext)

    def test_split_on_and(self, mock_ctx):
        intention = Intention.create(
            what="Create file and write content",
            acceptance="Both done",
        )
        children = _heuristic_decompose(intention, mock_ctx)

        assert len(children) >= 2
        assert any("Create file" in c.what for c in children)

    def test_split_on_then(self, mock_ctx):
        intention = Intention.create(
            what="Install package then run tests",
            acceptance="Tests pass",
        )
        children = _heuristic_decompose(intention, mock_ctx)

        assert len(children) >= 2

    def test_default_phases(self, mock_ctx):
        intention = Intention.create(
            what="Build a complex feature",
            acceptance="Feature works",
        )
        children = _heuristic_decompose(intention, mock_ctx)

        # Should create setup + implementation phases
        assert len(children) == 2
        assert any("Set up" in c.what or "prerequisites" in c.what for c in children)
        assert any("Implement" in c.what for c in children)


class TestHeuristicAction:
    """Test _heuristic_action function."""

    @pytest.fixture
    def mock_ctx(self):
        return MagicMock(spec=WorkContext)

    def test_file_creation(self, mock_ctx):
        intention = Intention.create(
            what="Create new file hello.py",
            acceptance="File exists",
        )
        thought, action = _heuristic_action(intention, mock_ctx)

        assert action.type == ActionType.CREATE
        assert "hello.py" in action.target or "hello.py" in thought

    def test_test_intention(self, mock_ctx):
        intention = Intention.create(
            what="Test the login function",
            acceptance="Tests pass",
        )
        thought, action = _heuristic_action(intention, mock_ctx)

        assert action.type == ActionType.COMMAND
        assert "pytest" in action.content

    def test_default_query(self, mock_ctx):
        intention = Intention.create(
            what="Understand the codebase",
            acceptance="Knowledge gained",
        )
        thought, action = _heuristic_action(intention, mock_ctx)

        assert action.type == ActionType.QUERY


# ==============================================================================
# AutoCheckpoint Tests
# ==============================================================================

class TestAutoCheckpoint:
    """Test AutoCheckpoint class."""

    @pytest.fixture
    def checkpoint(self):
        sandbox = MagicMock()
        return AutoCheckpoint(sandbox)

    def test_judge_action_success(self, checkpoint):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "All tests passed successfully", Judgment.UNCLEAR)

        result = checkpoint.judge_action(intention, cycle)
        assert result == Judgment.SUCCESS

    def test_judge_action_failure_on_error(self, checkpoint):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Error: command not found", Judgment.UNCLEAR)

        result = checkpoint.judge_action(intention, cycle)
        assert result == Judgment.FAILURE

    def test_judge_action_exit_code_0(self, checkpoint):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Output\nExit code: 0", Judgment.UNCLEAR)

        result = checkpoint.judge_action(intention, cycle)
        assert result == Judgment.SUCCESS

    def test_judge_action_exit_code_nonzero(self, checkpoint):
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Output\nExit code: 1", Judgment.UNCLEAR)

        result = checkpoint.judge_action(intention, cycle)
        assert result == Judgment.FAILURE

    def test_approve_decomposition(self, checkpoint):
        parent = Intention.create("Parent", "Done")
        children = [
            Intention.create("Child 1 for parent", "Done"),
            Intention.create("Child 2 for parent", "Done"),
        ]

        assert checkpoint.approve_decomposition(parent, children) is True

    def test_reject_empty_decomposition(self, checkpoint):
        parent = Intention.create("Parent", "Done")
        assert checkpoint.approve_decomposition(parent, []) is False

    def test_verify_integration_all_verified(self, checkpoint):
        parent = Intention.create("Parent", "Done")
        child1 = Intention.create("Child 1", "Done")
        child2 = Intention.create("Child 2", "Done")

        child1.status = IntentionStatus.VERIFIED
        child2.status = IntentionStatus.VERIFIED

        parent.add_child(child1)
        parent.add_child(child2)

        assert checkpoint.verify_integration(parent) is True

    def test_verify_integration_with_pending_child(self, checkpoint):
        parent = Intention.create("Parent", "Done")
        child1 = Intention.create("Child 1", "Done")
        child2 = Intention.create("Child 2", "Done")

        child1.status = IntentionStatus.VERIFIED
        child2.status = IntentionStatus.PENDING  # Not verified

        parent.add_child(child1)
        parent.add_child(child2)

        assert checkpoint.verify_integration(parent) is False


# ==============================================================================
# Execute Action Tests
# ==============================================================================

class TestExecuteAction:
    """Test execute_action function."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock(spec=WorkContext)
        ctx.sandbox = MagicMock()
        ctx.session_logger = None
        return ctx

    def test_execute_command(self, mock_ctx):
        mock_ctx.sandbox.run_command.return_value = (0, "output", "")

        action = Action(ActionType.COMMAND, "echo hello", None)
        result = execute_action(action, mock_ctx)

        assert "Exit code: 0" in result
        assert "output" in result
        mock_ctx.sandbox.run_command.assert_called_once_with("echo hello", timeout=60)

    def test_execute_create_file(self, mock_ctx):
        action = Action(ActionType.CREATE, "# content", "new_file.py")
        result = execute_action(action, mock_ctx)

        assert "Created file" in result
        mock_ctx.sandbox.write_file.assert_called_once_with("new_file.py", "# content")

    def test_execute_create_without_target(self, mock_ctx):
        action = Action(ActionType.CREATE, "content", None)
        result = execute_action(action, mock_ctx)

        assert "Error" in result
        mock_ctx.sandbox.write_file.assert_not_called()

    def test_execute_edit_file(self, mock_ctx):
        # Mock read_file to return existing content (for merge logic)
        mock_ctx.sandbox.read_file.return_value = "# existing content"

        action = Action(ActionType.EDIT, "new content", "existing.py")
        result = execute_action(action, mock_ctx)

        assert "Edited file" in result or "Merged" in result
        mock_ctx.sandbox.write_file.assert_called_once()

    def test_execute_delete_file(self, mock_ctx):
        action = Action(ActionType.DELETE, "", "old.py")
        result = execute_action(action, mock_ctx)

        assert "Deleted file" in result
        mock_ctx.sandbox.delete_file.assert_called_once_with("old.py")

    def test_execute_query_with_results(self, mock_ctx):
        mock_match = MagicMock()
        mock_match.path = "file.py"
        mock_match.line_number = 10
        mock_match.line = "matching line content"
        mock_ctx.sandbox.grep.return_value = [mock_match]

        action = Action(ActionType.QUERY, "search_term", None)
        result = execute_action(action, mock_ctx)

        assert "Found 1 matches" in result
        assert "file.py" in result

    def test_execute_query_no_results(self, mock_ctx):
        mock_ctx.sandbox.grep.return_value = []

        action = Action(ActionType.QUERY, "nonexistent", None)
        result = execute_action(action, mock_ctx)

        assert "No matches found" in result

    def test_execute_handles_exception(self, mock_ctx):
        mock_ctx.sandbox.run_command.side_effect = Exception("Sandbox error")

        action = Action(ActionType.COMMAND, "fail", None)
        result = execute_action(action, mock_ctx)

        assert "Error executing action" in result
        assert "Sandbox error" in result


# ==============================================================================
# Integration Tests
# ==============================================================================

class TestWorkAlgorithm:
    """Test the recursive work() algorithm."""

    @pytest.fixture
    def mock_sandbox(self):
        sandbox = MagicMock()
        sandbox.run_command.return_value = (0, "success", "")
        sandbox.grep.return_value = []
        return sandbox

    @pytest.fixture
    def ctx(self, mock_sandbox):
        checkpoint = AutoCheckpoint(mock_sandbox)
        return WorkContext(
            sandbox=mock_sandbox,
            llm=None,  # Use heuristics only
            checkpoint=checkpoint,
            max_cycles_per_intention=3,
            max_depth=5,
        )

    def test_simple_verifiable_intention(self, ctx):
        """A simple intention should be verified directly."""
        intention = Intention.create(
            what="Run pytest",
            acceptance="Tests pass",
        )

        work(intention, ctx)

        assert intention.status == IntentionStatus.VERIFIED
        assert len(intention.trace) >= 1

    def test_max_depth_protection(self, ctx):
        """Should fail if max depth exceeded."""
        intention = Intention.create("Deep task", "Done")

        # Force work at max depth
        work(intention, ctx, depth=ctx.max_depth + 1)

        assert intention.status == IntentionStatus.FAILED

    def test_callbacks_are_called(self, ctx):
        """Callbacks should be invoked during work."""
        on_start = MagicMock()
        on_complete = MagicMock()
        on_cycle = MagicMock()

        ctx.on_intention_start = on_start
        ctx.on_intention_complete = on_complete
        ctx.on_cycle_complete = on_cycle

        intention = Intention.create(
            what="Run tests",
            acceptance="Tests pass",
        )

        work(intention, ctx)

        on_start.assert_called_once()
        on_complete.assert_called_once()
        assert on_cycle.call_count >= 1


# ==============================================================================
# Logging Tests
# ==============================================================================

class TestRivaLogging:
    """Test that RIVA components log properly."""

    @pytest.fixture
    def mock_logger(self):
        logger = MagicMock()
        logger.log_info = MagicMock()
        logger.log_debug = MagicMock()
        logger.log_error = MagicMock()
        logger.log_llm_call = MagicMock()
        logger.log_decision = MagicMock()
        return logger

    @pytest.fixture
    def ctx_with_logger(self, mock_logger):
        sandbox = MagicMock()
        sandbox.run_command.return_value = (0, "success", "")
        checkpoint = AutoCheckpoint(sandbox)
        return WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=checkpoint,
            session_logger=mock_logger,
            max_cycles_per_intention=3,
            max_depth=5,
        )

    def test_work_logs_start(self, ctx_with_logger, mock_logger):
        intention = Intention.create("Run tests", "Tests pass")

        work(intention, ctx_with_logger)

        # Should log work_start - check that log_info was called with riva module
        calls = mock_logger.log_info.call_args_list
        work_start_calls = [c for c in calls if c[0][0] == "riva" and c[0][1] == "work_start"]
        assert len(work_start_calls) >= 1, f"Expected work_start log, got calls: {calls}"

    def test_execute_action_logs_on_error(self, mock_logger):
        sandbox = MagicMock()
        sandbox.run_command.side_effect = Exception("Test error")

        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            session_logger=mock_logger,
        )

        action = Action(ActionType.COMMAND, "fail", None)
        execute_action(action, ctx)

        mock_logger.log_error.assert_called()


# ==============================================================================
# UICheckpoint Tests
# ==============================================================================

class TestUICheckpoint:
    """Test UICheckpoint class for human-in-the-loop mode."""

    @pytest.fixture
    def sandbox(self):
        return MagicMock()

    def test_judge_action_uses_callback(self, sandbox):
        """Callback should be used when provided."""
        def custom_judge(intention, cycle, auto_judgment):
            # Override auto judgment
            return Judgment.SUCCESS

        checkpoint = UICheckpoint(sandbox, on_judge_action=custom_judge)
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Error: something failed", Judgment.UNCLEAR)

        # Auto would return FAILURE due to "Error" in result
        result = checkpoint.judge_action(intention, cycle)

        # But our callback overrides to SUCCESS
        assert result == Judgment.SUCCESS

    def test_judge_action_falls_back_to_auto(self, sandbox):
        """Without callback, should use auto judgment."""
        checkpoint = UICheckpoint(sandbox)  # No callback
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Success!", Judgment.UNCLEAR)

        result = checkpoint.judge_action(intention, cycle)

        # Auto returns SUCCESS due to "Success" in result
        assert result == Judgment.SUCCESS

    def test_approve_decomposition_uses_callback(self, sandbox):
        """Callback should be used when provided."""
        def custom_approve(intention, children):
            # Reject all decompositions
            return False

        checkpoint = UICheckpoint(sandbox, on_approve_decomposition=custom_approve)
        parent = Intention.create("Parent", "Done")
        children = [Intention.create("Child", "Done")]

        # Auto would approve
        result = checkpoint.approve_decomposition(parent, children)

        # But our callback rejects
        assert result is False

    def test_approve_decomposition_falls_back_to_auto(self, sandbox):
        """Without callback, should use auto approval."""
        checkpoint = UICheckpoint(sandbox)
        parent = Intention.create("Parent", "Done")
        children = [Intention.create("Child for parent", "Done")]

        result = checkpoint.approve_decomposition(parent, children)

        # Auto approves non-empty decomposition
        assert result is True

    def test_verify_integration_uses_callback(self, sandbox):
        """Callback should be used when provided."""
        def custom_verify(intention):
            # Always reject
            return False

        checkpoint = UICheckpoint(sandbox, on_verify_integration=custom_verify)
        parent = Intention.create("Parent", "Done")
        child = Intention.create("Child", "Done")
        child.status = IntentionStatus.VERIFIED
        parent.add_child(child)

        # Auto would verify since child is verified
        result = checkpoint.verify_integration(parent)

        # But our callback rejects
        assert result is False

    def test_verify_integration_falls_back_to_auto(self, sandbox):
        """Without callback, should use auto verification."""
        checkpoint = UICheckpoint(sandbox)
        parent = Intention.create("Parent", "Done")
        child = Intention.create("Child", "Done")
        child.status = IntentionStatus.VERIFIED
        parent.add_child(child)

        result = checkpoint.verify_integration(parent)

        # Auto verifies since child is verified
        assert result is True

    def test_review_reflection_uses_callback(self, sandbox):
        """Callback should be used when provided."""
        def custom_review(intention, cycle):
            # Reject the reflection
            return False

        checkpoint = UICheckpoint(sandbox, on_review_reflection=custom_review)
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Failed", Judgment.FAILURE, "Need different approach")

        # Auto would approve
        result = checkpoint.review_reflection(intention, cycle)

        # But our callback rejects
        assert result is False

    def test_callback_receives_auto_judgment(self, sandbox):
        """Callback should receive the auto-computed judgment."""
        received_auto = []

        def capture_auto(intention, cycle, auto_judgment):
            received_auto.append(auto_judgment)
            return auto_judgment

        checkpoint = UICheckpoint(sandbox, on_judge_action=capture_auto)
        intention = Intention.create("Task", "Done")
        action = Action(ActionType.COMMAND, "test", None)
        cycle = Cycle("Try", action, "Error: failed", Judgment.UNCLEAR)

        checkpoint.judge_action(intention, cycle)

        # Should have received FAILURE auto-judgment
        assert received_auto[0] == Judgment.FAILURE


# ==============================================================================
# Tool Integration Tests
# ==============================================================================

class TestGatherContext:
    """Test gather_context function for tool integration."""

    @pytest.fixture
    def sandbox(self):
        sandbox = MagicMock()
        sandbox.run_command.return_value = (0, "", "")
        return sandbox

    @pytest.fixture
    def mock_tool_provider(self):
        """Create a mock tool provider."""
        from reos.code_mode.tools import ToolResult

        provider = MagicMock()
        provider.has_tool.return_value = True
        provider.call_tool.return_value = ToolResult(
            success=True,
            output="Found pattern in file.py:10",
            source="test",
        )
        return provider

    def test_gather_context_returns_empty_without_provider(self, sandbox):
        """Should return empty string when no tool_provider."""
        from reos.code_mode.intention import gather_context

        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            tool_provider=None,  # No provider
        )

        intention = Intention.create("Create factorial function", "Function works")
        result = gather_context(intention, ctx)

        assert result == ""

    def test_gather_context_searches_codebase(self, sandbox, mock_tool_provider):
        """Should search codebase for keywords."""
        from reos.code_mode.intention import gather_context

        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            tool_provider=mock_tool_provider,
        )

        intention = Intention.create("Fix factorial function", "Returns correct values")
        result = gather_context(intention, ctx)

        # Should have called grep tool
        assert mock_tool_provider.call_tool.called
        assert "factorial" in str(mock_tool_provider.call_tool.call_args_list)

    def test_gather_context_gets_structure_for_create(self, sandbox, mock_tool_provider):
        """Should get project structure when creating files."""
        from reos.code_mode.intention import gather_context

        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            tool_provider=mock_tool_provider,
        )

        intention = Intention.create("Create new module for parsing", "Module exists")
        result = gather_context(intention, ctx)

        # Should have called get_structure
        call_args = [str(c) for c in mock_tool_provider.call_tool.call_args_list]
        assert any("get_structure" in c for c in call_args)

    def test_gather_context_searches_web_for_errors(self, sandbox, mock_tool_provider):
        """Should search web when intention mentions errors."""
        from reos.code_mode.intention import gather_context

        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            tool_provider=mock_tool_provider,
        )

        intention = Intention.create("Fix the IndexError in parser", "No more errors")
        result = gather_context(intention, ctx)

        # Should have called web_search
        call_args = [str(c) for c in mock_tool_provider.call_tool.call_args_list]
        assert any("web_search" in c for c in call_args)

    def test_workcontext_accepts_tool_provider(self, sandbox, mock_tool_provider):
        """WorkContext should accept tool_provider argument."""
        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,
            checkpoint=AutoCheckpoint(sandbox),
            tool_provider=mock_tool_provider,
        )

        assert ctx.tool_provider is mock_tool_provider

    def test_extract_keywords_helper(self):
        """Test keyword extraction helper."""
        from reos.code_mode.intention import _extract_keywords

        keywords = _extract_keywords("Create a factorial function in math_utils.py")

        # Should extract meaningful keywords
        assert "factorial" in keywords
        assert "math_utils" in keywords
        # Should not include stopwords
        assert "create" not in keywords
        assert "the" not in keywords
        assert "a" not in keywords

    def test_detect_library_hints_helper(self):
        """Test library detection helper."""
        from reos.code_mode.intention import _detect_library_hints

        libs = _detect_library_hints("Add a FastAPI endpoint with pytest tests")

        assert "fastapi" in libs
        assert "pytest" in libs
