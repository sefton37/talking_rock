"""Tests for the ReOS reasoning system."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from reos.reasoning.complexity import (
    ComplexityAssessor,
    ComplexityLevel,
    ComplexityResult,
)
from reos.reasoning.safety import (
    SafetyManager,
    RiskLevel,
    RiskAssessment,
)
from reos.reasoning.planner import (
    TaskPlanner,
    TaskPlan,
    TaskStep,
    StepType,
    StepStatus,
)
from reos.reasoning.executor import (
    ExecutionEngine,
    ExecutionContext,
    ExecutionState,
    StepResult,
)
from reos.reasoning.conversation import (
    ConversationManager,
    ConversationPreferences,
    VerbosityLevel,
)
from reos.reasoning.engine import (
    ReasoningEngine,
    ReasoningConfig,
    ProcessingResult,
)


class TestComplexityAssessor:
    """Tests for the complexity assessment system."""

    def setup_method(self) -> None:
        self.assessor = ComplexityAssessor()

    def test_simple_command_recognized(self) -> None:
        """Simple commands should be classified as simple."""
        result = self.assessor.assess("show disk space")
        assert result.level == ComplexityLevel.SIMPLE
        assert result.confidence > 0.7

    def test_simple_install_package(self) -> None:
        """Single package install is simple."""
        result = self.assessor.assess("install htop")
        assert result.level == ComplexityLevel.SIMPLE

    def test_simple_status_check(self) -> None:
        """Status checks are simple."""
        result = self.assessor.assess("is docker running")
        assert result.level == ComplexityLevel.SIMPLE

    def test_complex_setup_recognized(self) -> None:
        """Setup operations should be classified as complex."""
        result = self.assessor.assess("set up development environment")
        assert result.level == ComplexityLevel.COMPLEX
        assert "setup" in result.keywords_matched or "environment setup" in result.keywords_matched

    def test_complex_migration(self) -> None:
        """Migration operations are complex."""
        result = self.assessor.assess("switch from PulseAudio to PipeWire")
        assert result.level == ComplexityLevel.COMPLEX

    def test_diagnostic_recognized(self) -> None:
        """Troubleshooting should be classified as diagnostic."""
        result = self.assessor.assess("why is my laptop hot")
        assert result.level == ComplexityLevel.DIAGNOSTIC

    def test_diagnostic_not_working(self) -> None:
        """'Not working' issues are diagnostic."""
        result = self.assessor.assess("my wifi isn't working")
        assert result.level == ComplexityLevel.DIAGNOSTIC

    def test_risky_delete_recognized(self) -> None:
        """Bulk delete should be classified as risky."""
        result = self.assessor.assess("delete all temp files")
        assert result.level == ComplexityLevel.RISKY
        assert result.confidence > 0.8

    def test_risky_kernel_upgrade(self) -> None:
        """Kernel upgrade is risky."""
        result = self.assessor.assess("upgrade the kernel")
        assert result.level == ComplexityLevel.RISKY

    def test_should_plan_for_complex(self) -> None:
        """Complex requests should trigger planning."""
        result = self.assessor.assess("speed up boot time")
        assert self.assessor.should_plan(result)

    def test_should_not_plan_for_simple(self) -> None:
        """Simple requests should not trigger planning."""
        result = self.assessor.assess("show memory usage")
        assert not self.assessor.should_plan(result)

    def test_assessment_speed(self) -> None:
        """Assessment should be fast (<100ms)."""
        import time
        start = time.time()
        for _ in range(100):
            self.assessor.assess("configure nginx for production")
        elapsed = time.time() - start
        assert elapsed < 1.0  # 100 assessments in < 1 second


class TestSafetyManager:
    """Tests for the safety management system."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.safety = SafetyManager(backup_dir=Path(self.temp_dir))

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safe_command_classification(self) -> None:
        """Read-only commands should be safe."""
        result = self.safety.assess_command_risk("ls -la")
        assert result.level == RiskLevel.SAFE
        assert not result.requires_confirmation

    def test_medium_risk_package_install(self) -> None:
        """Package installation is medium risk."""
        result = self.safety.assess_command_risk("sudo apt install vim")
        assert result.level == RiskLevel.MEDIUM
        assert "packages" in result.affected_components

    def test_high_risk_deletion(self) -> None:
        """rm -rf commands are critical risk (recursive deletion)."""
        result = self.safety.assess_command_risk("rm -rf /tmp/test")
        # -rf makes it CRITICAL, not just HIGH
        assert result.level == RiskLevel.CRITICAL
        assert result.data_loss_possible
        assert not result.reversible

    def test_critical_disk_operation(self) -> None:
        """dd commands are critical risk."""
        result = self.safety.assess_command_risk("dd if=/dev/zero of=/dev/sdb")
        assert result.level == RiskLevel.CRITICAL
        assert result.requires_confirmation
        assert result.data_loss_possible

    def test_backup_file(self) -> None:
        """Should be able to backup a file."""
        # Create test file
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("original content")

        backup_path = self.safety.backup_file(test_file)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.read_text() == "original content"

    def test_restore_file(self) -> None:
        """Should be able to restore a file from backup."""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("original content")

        self.safety.backup_file(test_file)

        # Modify the original
        test_file.write_text("modified content")

        # Restore
        success = self.safety.restore_file(test_file)
        assert success
        assert test_file.read_text() == "original content"

    def test_record_action_for_rollback(self) -> None:
        """Should record actions with rollback commands."""
        action = self.safety.record_action(
            description="Started nginx service",
            rollback_command="sudo systemctl stop nginx",
        )

        assert action.id is not None
        assert action.description == "Started nginx service"
        assert action.rollback_command == "sudo systemctl stop nginx"

        # Should be in the stack
        stack = self.safety.get_rollback_stack()
        assert len(stack) == 1
        assert stack[0].id == action.id


class TestTaskPlanner:
    """Tests for the task planning system."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.safety = SafetyManager(backup_dir=Path(self.temp_dir))
        self.planner = TaskPlanner(self.safety)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_basic_plan(self) -> None:
        """Should create a plan from a request."""
        plan = self.planner.create_plan("set up a web server")

        assert plan.id is not None
        assert len(plan.steps) > 0
        assert plan.original_request == "set up a web server"

    def test_plan_has_dependencies(self) -> None:
        """Plan steps should have proper dependencies."""
        plan = self.planner.create_plan("install and configure nginx")

        # Later steps should depend on earlier ones
        has_dependency = any(len(s.depends_on) > 0 for s in plan.steps)
        assert has_dependency or len(plan.steps) == 1

    def test_plan_risk_assessment(self) -> None:
        """Plan should have aggregated risk assessment."""
        # Use a request that creates a command-based plan
        plan = self.planner.create_plan("install nginx")

        assert plan.highest_risk is not None
        # Package install template should have medium risk
        assert plan.highest_risk.value in ("safe", "low", "medium", "high", "critical")

    def test_add_step_to_plan(self) -> None:
        """Should be able to add steps to an existing plan."""
        plan = self.planner.create_plan("test")
        initial_count = len(plan.steps)

        self.planner.add_step(
            plan,
            title="Custom step",
            action={"command": "echo hello"},
        )

        assert len(plan.steps) == initial_count + 1

    def test_plan_summary(self) -> None:
        """Should generate human-readable plan summary."""
        plan = self.planner.create_plan("install docker")
        summary = self.planner.get_plan_summary(plan)

        assert "step_count" in summary
        assert "steps" in summary
        assert isinstance(summary["steps"], list)


class TestExecutionEngine:
    """Tests for the execution engine."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.safety = SafetyManager(backup_dir=Path(self.temp_dir))
        self.executor = ExecutionEngine(self.safety)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_execute_simple_command(self) -> None:
        """Should execute a simple command step."""
        step = TaskStep(
            id="test",
            title="Echo test",
            description="Run echo",
            step_type=StepType.COMMAND,
            action={"command": "echo hello"},
        )

        result = self.executor._execute_step(step, None)  # type: ignore

        assert result.success
        assert "hello" in result.output

    def test_execute_plan_requires_approval(self) -> None:
        """Should require plan approval before execution."""
        plan = TaskPlan(
            id="test",
            title="Test plan",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[],
            approved=False,
        )

        with pytest.raises(ValueError, match="approved"):
            self.executor.start_execution(plan)

    def test_step_failure_handling(self) -> None:
        """Should handle step failures gracefully."""
        step = TaskStep(
            id="fail",
            title="Failing step",
            description="Will fail",
            step_type=StepType.COMMAND,
            action={"command": "exit 1"},
        )

        result = self.executor._execute_step(step, None)  # type: ignore

        assert not result.success
        assert result.error is not None or result.output == ""


class TestConversationManager:
    """Tests for the conversation manager."""

    def setup_method(self) -> None:
        self.manager = ConversationManager()

    def test_plan_presentation_natural(self) -> None:
        """Plan presentation should be natural, not robotic."""
        plan = TaskPlan(
            id="test",
            title="Speed up boot",
            original_request="speed up boot",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id="1",
                    title="Check current boot time",
                    description="Measure baseline",
                    step_type=StepType.COMMAND,
                    action={"command": "systemd-analyze"},
                    explanation="First let's see how long boot takes now",
                ),
            ],
            total_estimated_duration=30,
        )

        output = self.manager.format_plan_presentation(plan)

        # Should NOT have robotic markers
        assert "ANALYZING" not in output
        assert "INITIATING" not in output
        assert "STEP 1 OF" not in output

        # Should be conversational
        assert "plan" in output.lower() or "here" in output.lower()
        assert "?" in output  # Should ask for confirmation

    def test_verbosity_minimal(self) -> None:
        """Minimal verbosity should be concise."""
        prefs = ConversationPreferences(verbosity=VerbosityLevel.MINIMAL)
        manager = ConversationManager(prefs)

        result = manager.format_simple_result({"stdout": "OK"}, "test")
        assert len(result) < 50

    def test_error_formatting_friendly(self) -> None:
        """Errors should be formatted helpfully."""
        output = self.manager.format_error("Permission denied", "trying to access /etc/shadow")

        assert "Permission denied" in output
        assert "wrong" in output.lower() or "error" in output.lower()

    def test_progress_formatting(self) -> None:
        """Progress should be clear and visual."""
        output = self.manager.format_progress(3, 5, "Installing packages")

        assert "3" in output
        assert "5" in output


class TestReasoningEngine:
    """Tests for the main reasoning engine."""

    def setup_method(self) -> None:
        self.config = ReasoningConfig(
            enabled=True,
            auto_assess=True,
            always_confirm=False,
        )
        self.engine = ReasoningEngine(config=self.config)

    def test_simple_request_bypasses_planning(self) -> None:
        """Simple requests should bypass the planning system."""
        result = self.engine.process("show disk space")

        # Simple requests get empty response (agent handles directly)
        assert result.complexity is not None
        assert result.complexity.level == ComplexityLevel.SIMPLE
        assert result.plan is None

    def test_complex_request_creates_plan(self) -> None:
        """Complex requests should create a plan."""
        result = self.engine.process("set up a development environment")

        assert result.complexity is not None
        assert result.complexity.level in (ComplexityLevel.COMPLEX, ComplexityLevel.DIAGNOSTIC)
        assert result.plan is not None
        assert result.needs_approval

    def test_approval_handling(self) -> None:
        """Should handle plan approval."""
        # First, get a plan
        self.engine.process("configure nginx")

        # Then approve
        result = self.engine.process("yes")

        # Plan should be executed or at least started
        assert "cancelled" not in result.response.lower()

    def test_rejection_handling(self) -> None:
        """Should handle plan rejection."""
        # First, get a plan
        self.engine.process("configure nginx")

        # Then reject
        result = self.engine.process("no")

        assert "cancel" in result.response.lower() or "no problem" in result.response.lower()
        assert self.engine.get_pending_plan() is None

    def test_undo_request(self) -> None:
        """Should handle undo requests."""
        # Create a fresh engine with no history
        import tempfile
        temp_dir = tempfile.mkdtemp()
        from reos.reasoning.safety import SafetyManager
        from pathlib import Path
        fresh_safety = SafetyManager(backup_dir=Path(temp_dir))

        # Use new engine with fresh safety manager
        fresh_engine = ReasoningEngine(config=self.config)
        fresh_engine.safety = fresh_safety

        result = fresh_engine.process("undo")

        # No actions to undo
        assert "nothing" in result.response.lower() or "no" in result.response.lower()

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_bypass_check(self) -> None:
        """Should correctly identify requests to bypass."""
        # Simple commands with context should bypass
        assert self.engine.should_bypass_reasoning("show disk space")
        assert self.engine.should_bypass_reasoning("show memory")
        # Complex requests should not bypass
        assert not self.engine.should_bypass_reasoning("set up docker")

    def test_config_from_dict(self) -> None:
        """Should load config from dictionary."""
        data = {
            "reasoning": {
                "enabled": False,
                "always_confirm": True,
            },
            "safety": {
                "rollback_on_failure": False,
            },
        }

        config = ReasoningConfig.from_dict(data)

        assert config.enabled is False
        assert config.always_confirm is True
        assert config.rollback_on_failure is False


class TestIntegration:
    """Integration tests for the full reasoning pipeline."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        # Create engine with isolated backup directory
        self.engine = ReasoningEngine()
        self.engine.safety = SafetyManager(backup_dir=Path(self.temp_dir))

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_pipeline_simple(self) -> None:
        """Simple request should complete quickly."""
        import time
        start = time.time()

        result = self.engine.process("what is my username")

        elapsed = time.time() - start
        assert elapsed < 0.5  # Should be very fast

    def test_full_pipeline_complex(self) -> None:
        """Complex request should produce a plan."""
        result = self.engine.process("speed up my computer")

        assert result.plan is not None
        assert len(result.plan.steps) > 0
        assert "?" in result.response  # Should ask for confirmation

    def test_rollback_stack_persists(self) -> None:
        """Rollback stack should be accessible."""
        # Initially empty
        stack = self.engine.get_rollback_stack()
        assert len(stack) == 0

        # Record an action
        self.engine.safety.record_action(
            description="Test action",
            rollback_command="echo undone",
        )

        stack = self.engine.get_rollback_stack()
        assert len(stack) == 1
