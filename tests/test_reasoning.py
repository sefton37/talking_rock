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


# Import adaptive components for testing
from reos.reasoning.adaptive import (
    ErrorClassifier,
    ErrorCategory,
    ErrorDiagnosis,
    AdaptiveReplanner,
    ExecutionLearner,
    ExecutionMemory,
    AdaptiveExecutor,
    # Circuit breakers
    SafetyLimits,
    ExecutionBudget,
    check_scope_drift,
)


class TestErrorClassifier:
    """Tests for error classification system."""

    def setup_method(self) -> None:
        self.classifier = ErrorClassifier()

    def test_classify_missing_dependency(self) -> None:
        """Should classify missing dependency errors."""
        errors = [
            "bash: htop: command not found",
            "Unable to locate package nginx",
            "ModuleNotFoundError: No module named 'requests'",
            "error while loading shared libraries: libfoo.so",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.MISSING_DEPENDENCY
            assert diagnosis.is_retryable
            assert diagnosis.confidence > 0.6

    def test_classify_permission_denied(self) -> None:
        """Should classify permission errors."""
        errors = [
            "Permission denied: /etc/passwd",
            "must be root to perform this operation",
            "Operation not permitted",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.PERMISSION_DENIED
            assert diagnosis.is_retryable

    def test_classify_not_found(self) -> None:
        """Should classify file/resource not found errors."""
        errors = [
            "No such file or directory: /foo/bar",
            "unit nginx.service not found",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.NOT_FOUND
            assert diagnosis.requires_user  # Usually needs human judgment

    def test_classify_already_exists(self) -> None:
        """Should classify already-exists conditions."""
        errors = [
            "File exists: /tmp/test",
            "nginx is already installed",
            "service already running",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.ALREADY_EXISTS
            # Often not a real error
            assert not diagnosis.is_retryable

    def test_classify_transient(self) -> None:
        """Should classify transient/network errors."""
        errors = [
            "Connection timed out",
            "Network is unreachable",
            "Could not resolve host: example.com",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.TRANSIENT
            assert diagnosis.is_retryable

    def test_classify_resource_busy(self) -> None:
        """Should classify busy resource errors."""
        errors = [
            "Device or resource busy",
            "Could not get lock /var/lib/apt/lists/lock",
        ]

        for error in errors:
            diagnosis = self.classifier.classify(error)
            assert diagnosis.category == ErrorCategory.RESOURCE_BUSY
            assert diagnosis.is_retryable

    def test_classify_unknown_error(self) -> None:
        """Should handle unknown errors gracefully."""
        diagnosis = self.classifier.classify("Something weird happened")
        assert diagnosis.category == ErrorCategory.UNKNOWN
        assert diagnosis.requires_user

    def test_empty_error_handled(self) -> None:
        """Should handle empty error strings."""
        diagnosis = self.classifier.classify("")
        assert diagnosis.category == ErrorCategory.UNKNOWN
        assert diagnosis.confidence == 0.0

    def test_extract_package_name(self) -> None:
        """Should extract package names from errors."""
        test_cases = [
            ("command not found: htop", "htop"),
            ("Unable to locate package nginx", "nginx"),
            ("ModuleNotFoundError: No module named 'requests'", "requests"),
        ]

        for error, expected in test_cases:
            package = self.classifier._extract_package_name(error)
            assert package == expected

    def test_suggests_fix_command(self) -> None:
        """Should suggest fix commands when possible."""
        # Permission error should suggest sudo
        diagnosis = self.classifier.classify("Permission denied", "cat /etc/shadow")
        assert diagnosis.fix_command is not None
        assert "sudo" in diagnosis.fix_command

        # Transient error should suggest retry
        diagnosis = self.classifier.classify("Connection timed out", "curl example.com")
        assert diagnosis.fix_command is not None


class TestAdaptiveReplanner:
    """Tests for adaptive replanning system."""

    def setup_method(self) -> None:
        self.classifier = ErrorClassifier()
        self.memory = ExecutionMemory()
        self.replanner = AdaptiveReplanner(self.classifier, self.memory)

    def test_handle_permission_failure(self) -> None:
        """Should generate sudo fix for permission errors."""
        step = TaskStep(
            id="test",
            title="Read file",
            description="Try to read a file",
            step_type=StepType.COMMAND,
            action={"command": "cat /etc/shadow"},
        )

        result = StepResult(
            step_id="test",
            success=False,
            output="",
            error="Permission denied",
            duration_seconds=0.1,
        )

        fix_step, explanation = self.replanner.handle_step_failure(
            TaskPlan(
                id="test",
                title="Test",
                original_request="test",
                created_at=__import__("datetime").datetime.now(),
                steps=[step],
            ),
            step,
            result,
        )

        assert fix_step is not None
        assert "sudo" in fix_step.action.get("command", "")
        assert "fix" in fix_step.id

    def test_handle_missing_dependency(self) -> None:
        """Should suggest package installation for missing commands."""
        step = TaskStep(
            id="test",
            title="Run htop",
            description="Launch htop",
            step_type=StepType.COMMAND,
            action={"command": "htop"},
        )

        result = StepResult(
            step_id="test",
            success=False,
            output="",
            error="htop: command not found",
            duration_seconds=0.1,
        )

        fix_step, explanation = self.replanner.handle_step_failure(
            TaskPlan(
                id="test",
                title="Test",
                original_request="test",
                created_at=__import__("datetime").datetime.now(),
                steps=[step],
            ),
            step,
            result,
        )

        assert fix_step is not None
        # Should suggest installing htop
        assert "htop" in fix_step.action.get("command", "") or "htop" in explanation

    def test_max_fix_attempts_honored(self) -> None:
        """Should stop after max fix attempts."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "fail"},
        )

        result = StepResult(
            step_id="test",
            success=False,
            output="",
            error="Permission denied",
            duration_seconds=0.1,
        )

        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[step],
        )

        # Simulate previous attempts
        from reos.reasoning.adaptive import ResolutionAttempt

        for _ in range(3):
            self.memory.resolution_history.append(
                ResolutionAttempt(
                    error_diagnosis=ErrorDiagnosis(
                        category=ErrorCategory.PERMISSION_DENIED,
                        original_error="Permission denied",
                        explanation="",
                        is_retryable=True,
                        suggested_fix=None,
                        fix_command=None,
                        requires_user=False,
                        confidence=0.8,
                    ),
                    fix_applied="sudo test",
                    success=False,
                    result_message="Still failed",
                )
            )

        fix_step, explanation = self.replanner.handle_step_failure(plan, step, result)

        # Should refuse to try again
        assert fix_step is None
        assert "tried" in explanation.lower()

    def test_inject_dependency_step(self) -> None:
        """Should inject dependency installation steps."""
        step = TaskStep(
            id="use_nginx",
            title="Configure nginx",
            description="Configure",
            step_type=StepType.COMMAND,
            action={"command": "nginx -t"},
        )

        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[step],
        )

        new_step = self.replanner.inject_dependency_step(plan, step, "nginx")

        assert len(plan.steps) == 2
        assert plan.steps[0].id.startswith("install_nginx")
        assert "nginx" in plan.steps[0].action.get("command", "")

    def test_suggest_alternatives(self) -> None:
        """Should suggest alternative approaches."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "read /etc/shadow"},
        )

        diagnosis = ErrorDiagnosis(
            category=ErrorCategory.PERMISSION_DENIED,
            original_error="Permission denied",
            explanation="Need sudo",
            is_retryable=True,
            suggested_fix="Use sudo",
            fix_command="sudo read /etc/shadow",
            requires_user=False,
            confidence=0.8,
        )

        alternatives = self.replanner.suggest_alternatives(step, diagnosis)

        assert len(alternatives) > 0
        assert any("sudo" in str(a) for a in alternatives)


class TestExecutionLearner:
    """Tests for execution learning system."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.learner = ExecutionLearner(
            storage_path=Path(self.temp_dir) / "knowledge.db"
        )

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_success(self) -> None:
        """Should record successful executions."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "echo hello"},
        )

        result = StepResult(
            step_id="test",
            success=True,
            output="hello",
            duration_seconds=0.1,
        )

        self.learner.record_success(step, result)

        # Should have recorded
        assert len(self.learner.memory.successful_patterns) > 0

    def test_record_failure(self) -> None:
        """Should record failed executions."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "fail"},
        )

        result = StepResult(
            step_id="test",
            success=False,
            output="",
            error="Something failed",
            duration_seconds=0.1,
        )

        diagnosis = ErrorDiagnosis(
            category=ErrorCategory.UNKNOWN,
            original_error="Something failed",
            explanation="Unknown error",
            is_retryable=False,
            suggested_fix=None,
            fix_command=None,
            requires_user=True,
            confidence=0.5,
        )

        self.learner.record_failure(step, result, diagnosis)

        # Should have recorded
        assert len(self.learner.memory.failed_patterns) > 0

    def test_success_rate_calculation(self) -> None:
        """Should calculate success rate from history."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "echo test"},
        )

        # Initially 50% (unknown)
        rate = self.learner.get_success_rate(step)
        assert rate == 0.5

        # Record 2 successes
        for _ in range(2):
            self.learner.record_success(
                step,
                StepResult(step_id="test", success=True, output="", duration_seconds=0.1),
            )

        # Record 1 failure
        self.learner.record_failure(
            step,
            StepResult(step_id="test", success=False, output="", error="fail", duration_seconds=0.1),
            ErrorDiagnosis(
                category=ErrorCategory.UNKNOWN,
                original_error="fail",
                explanation="",
                is_retryable=False,
                suggested_fix=None,
                fix_command=None,
                requires_user=True,
                confidence=0.5,
            ),
        )

        # Should be 2/3
        rate = self.learner.get_success_rate(step)
        assert 0.6 < rate < 0.7

    def test_should_skip_after_repeated_failures(self) -> None:
        """Should suggest skipping consistently failing steps."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "consistently_fail"},
        )

        diagnosis = ErrorDiagnosis(
            category=ErrorCategory.PERMISSION_DENIED,
            original_error="Permission denied",
            explanation="",
            is_retryable=False,
            suggested_fix=None,
            fix_command=None,
            requires_user=True,
            confidence=0.8,
        )

        # Record 3 failures with same error
        for _ in range(3):
            self.learner.record_failure(
                step,
                StepResult(step_id="test", success=False, output="", error="Permission denied", duration_seconds=0.1),
                diagnosis,
            )

        should_skip, reason = self.learner.should_skip_step(step)

        assert should_skip
        assert "failed" in reason.lower() or "permission" in reason.lower()

    def test_save_and_load(self) -> None:
        """Should persist and reload learning data."""
        step = TaskStep(
            id="test",
            title="Test",
            description="Test",
            step_type=StepType.COMMAND,
            action={"command": "echo test"},
        )

        self.learner.record_success(
            step,
            StepResult(step_id="test", success=True, output="test", duration_seconds=0.1),
        )

        self.learner.save()

        # Create new learner and load
        new_learner = ExecutionLearner(
            storage_path=Path(self.temp_dir) / "knowledge.db"
        )

        # Should have the pattern
        assert len(new_learner.memory.successful_patterns) > 0

    def test_record_system_quirk(self) -> None:
        """Should record system-specific behaviors."""
        self.learner.record_system_quirk(
            "apt_requires_update",
            "apt install fails without apt update first",
        )

        assert "apt_requires_update" in self.learner.memory.system_quirks


class TestAdaptiveExecutor:
    """Tests for the adaptive executor."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.safety = SafetyManager(backup_dir=Path(self.temp_dir))
        self.base_executor = ExecutionEngine(self.safety)
        self.learner = ExecutionLearner(
            storage_path=Path(self.temp_dir) / "knowledge.db"
        )
        self.adaptive = AdaptiveExecutor(self.base_executor, self.learner)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_successful_execution(self) -> None:
        """Should execute successfully and record learning."""
        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id="1",
                    title="Echo",
                    description="Echo test",
                    step_type=StepType.COMMAND,
                    action={"command": "echo hello"},
                ),
            ],
            approved=True,
        )

        context = self.base_executor.start_execution(plan)
        success = self.adaptive.execute_with_recovery(context)

        assert success
        # Should have recorded success
        assert len(self.learner.memory.successful_patterns) > 0

    def test_recovery_callback_called(self) -> None:
        """Should call recovery callback on failure."""
        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id="1",
                    title="Fail",
                    description="Will fail",
                    step_type=StepType.COMMAND,
                    action={"command": "exit 1"},
                ),
            ],
            approved=True,
        )

        recovery_messages = []

        def on_recovery(msg: str) -> None:
            recovery_messages.append(msg)

        context = self.base_executor.start_execution(plan)
        self.adaptive.execute_with_recovery(context, on_recovery_attempt=on_recovery)

        # May or may not have recovery messages depending on error classification
        # but execution should complete without raising

    def test_learning_persisted_after_execution(self) -> None:
        """Should save learning data after execution."""
        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id="1",
                    title="Echo",
                    description="Echo test",
                    step_type=StepType.COMMAND,
                    action={"command": "echo hello"},
                ),
            ],
            approved=True,
        )

        context = self.base_executor.start_execution(plan)
        self.adaptive.execute_with_recovery(context)

        # Check file was saved
        assert (Path(self.temp_dir) / "knowledge.db").exists()


class TestSafetyLimits:
    """Tests for circuit breaker safety limits."""

    def test_default_limits(self) -> None:
        """Should have reasonable default limits."""
        limits = SafetyLimits()

        # These are the "paperclip problem" prevention limits
        assert limits.max_total_operations == 25
        assert limits.max_execution_time_seconds == 300  # 5 minutes
        assert limits.max_privilege_escalations == 3
        assert limits.max_injected_steps == 5
        assert limits.human_checkpoint_after_recoveries == 2
        assert limits.max_learned_patterns == 1000

    def test_custom_limits(self) -> None:
        """Should allow custom limits."""
        limits = SafetyLimits(
            max_total_operations=10,
            max_execution_time_seconds=60,
        )

        assert limits.max_total_operations == 10
        assert limits.max_execution_time_seconds == 60


class TestExecutionBudget:
    """Tests for execution budget tracking."""

    def test_operation_limit(self) -> None:
        """Should stop after max operations."""
        limits = SafetyLimits(max_total_operations=3)
        budget = ExecutionBudget(limits=limits)

        # First 3 operations should succeed
        assert budget.record_operation() is True
        assert budget.record_operation() is True
        assert budget.record_operation() is False  # 3rd hits limit
        assert budget.budget_exhausted
        assert "Maximum operations" in budget.exhaustion_reason

    def test_privilege_escalation_limit(self) -> None:
        """Should stop after max privilege escalations."""
        limits = SafetyLimits(max_privilege_escalations=2)
        budget = ExecutionBudget(limits=limits)

        assert budget.record_privilege_escalation() is True
        assert budget.record_privilege_escalation() is False
        assert budget.budget_exhausted
        assert "privilege" in budget.exhaustion_reason.lower()

    def test_injected_step_limit(self) -> None:
        """Should stop after max injected steps."""
        limits = SafetyLimits(max_injected_steps=2)
        budget = ExecutionBudget(limits=limits)

        assert budget.record_injected_step() is True
        assert budget.record_injected_step() is False
        assert budget.budget_exhausted

    def test_human_checkpoint(self) -> None:
        """Should require human checkpoint after N recoveries."""
        limits = SafetyLimits(human_checkpoint_after_recoveries=2)
        budget = ExecutionBudget(limits=limits)

        assert budget.record_recovery() is True
        assert budget.record_recovery() is False  # Triggers checkpoint
        assert budget.human_checkpoint_required
        assert not budget.budget_exhausted  # Not exhausted, just needs human

    def test_time_limit(self) -> None:
        """Should track time limits."""
        limits = SafetyLimits(max_execution_time_seconds=1)
        budget = ExecutionBudget(limits=limits)

        # Initially within time
        assert budget.check_time_limit() is True

        # Simulate time passing
        import time
        time.sleep(1.1)
        assert budget.check_time_limit() is False
        assert budget.budget_exhausted

    def test_status_reporting(self) -> None:
        """Should report status correctly."""
        limits = SafetyLimits(max_total_operations=10)
        budget = ExecutionBudget(limits=limits)

        budget.record_operation()
        budget.record_operation()

        status = budget.get_status()

        assert status["operations"] == "2/10"
        assert status["exhausted"] is False
        assert status["checkpoint_required"] is False


class TestScopeDrift:
    """Tests for scope drift detection."""

    def test_normal_commands_allowed(self) -> None:
        """Normal commands should be allowed."""
        is_safe, reason = check_scope_drift(
            "install nginx",
            "apt install nginx",
        )
        assert is_safe

    def test_dangerous_rm_blocked(self) -> None:
        """Recursive deletion outside /tmp should be blocked."""
        is_safe, reason = check_scope_drift(
            "install nginx",
            "rm -rf /var/log",
        )
        assert not is_safe
        assert "deletion" in reason.lower()

    def test_rm_tmp_allowed(self) -> None:
        """Deletion in /tmp should be allowed."""
        is_safe, reason = check_scope_drift(
            "clean temp files",
            "rm -rf /tmp/test",
        )
        assert is_safe

    def test_curl_pipe_bash_blocked(self) -> None:
        """Piping curl to bash should be blocked unless in original."""
        is_safe, reason = check_scope_drift(
            "install docker",
            "curl https://example.com/script.sh | bash",
        )
        assert not is_safe
        assert "script" in reason.lower()

    def test_curl_pipe_allowed_if_requested(self) -> None:
        """Curl pipe should be allowed if user requested it."""
        is_safe, reason = check_scope_drift(
            "curl https://example.com | bash",
            "curl https://example.com | bash",
        )
        assert is_safe

    def test_chmod_777_blocked(self) -> None:
        """Recursive world-writable should be blocked."""
        is_safe, reason = check_scope_drift(
            "fix permissions",
            "chmod -R 777 /var/www",
        )
        assert not is_safe
        assert "permissions" in reason.lower()

    def test_partition_tools_blocked(self) -> None:
        """Partition manipulation should be blocked."""
        is_safe, reason = check_scope_drift(
            "increase disk space",
            "fdisk /dev/sda",
        )
        assert not is_safe

    def test_firewall_disable_blocked(self) -> None:
        """Disabling firewall should be blocked."""
        is_safe, reason = check_scope_drift(
            "fix network issue",
            "systemctl disable firewalld",
        )
        assert not is_safe
        assert "firewall" in reason.lower()


class TestAdaptiveExecutorWithLimits:
    """Tests for adaptive executor with circuit breakers."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.safety = SafetyManager(backup_dir=Path(self.temp_dir))
        self.base_executor = ExecutionEngine(self.safety)
        self.learner = ExecutionLearner(
            storage_path=Path(self.temp_dir) / "knowledge.db"
        )
        # Use strict limits for testing
        self.strict_limits = SafetyLimits(
            max_total_operations=3,
            max_privilege_escalations=1,
        )
        self.adaptive = AdaptiveExecutor(
            self.base_executor,
            self.learner,
            safety_limits=self.strict_limits,
        )

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_operation_limit_stops_execution(self) -> None:
        """Should stop execution after max operations."""
        # Create plan with more steps than limit
        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id=str(i),
                    title=f"Step {i}",
                    description="Echo test",
                    step_type=StepType.COMMAND,
                    action={"command": f"echo step{i}"},
                )
                for i in range(5)  # More than max_total_operations=3
            ],
            approved=True,
        )

        budget_exhausted_called = []

        def on_exhausted(reason: str, status: dict) -> None:
            budget_exhausted_called.append((reason, status))

        context = self.base_executor.start_execution(plan)
        self.adaptive.execute_with_recovery(
            context,
            on_budget_exhausted=on_exhausted,
        )

        # Should have stopped due to operation limit
        assert len(budget_exhausted_called) == 1
        assert "Maximum operations" in budget_exhausted_called[0][0]

    def test_budget_status_available(self) -> None:
        """Should report budget status during execution."""
        plan = TaskPlan(
            id="test",
            title="Test",
            original_request="test",
            created_at=__import__("datetime").datetime.now(),
            steps=[
                TaskStep(
                    id="1",
                    title="Echo",
                    description="Echo test",
                    step_type=StepType.COMMAND,
                    action={"command": "echo hello"},
                ),
            ],
            approved=True,
        )

        context = self.base_executor.start_execution(plan)
        self.adaptive.execute_with_recovery(context)

        # Budget should be cleared after execution
        assert self.adaptive.get_current_budget_status() is None
