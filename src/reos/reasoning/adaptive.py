"""Adaptive execution and error recovery for ReOS reasoning system.

This module provides intelligent failure handling:
- Error classification to determine if retry/fix is possible
- Automatic dependency resolution
- Dynamic plan revision on failure
- Execution learning for future improvements

SAFETY: Contains circuit breakers to prevent runaway execution (paperclip problem).
See SafetyLimits class for hard limits on automated behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .planner import TaskPlan, TaskStep, StepType, StepStatus
from .executor import StepResult

logger = logging.getLogger(__name__)


# =============================================================================
# CIRCUIT BREAKERS - Hard limits to prevent runaway AI behavior
# =============================================================================

@dataclass
class SafetyLimits:
    """Hard limits on automated execution to prevent runaway behavior.

    These limits exist to ensure the system cannot:
    - Execute indefinitely (paperclip problem)
    - Escalate privileges without bounds
    - Consume unlimited resources
    - Drift from the original request scope

    All limits are HARD - they cannot be overridden by the AI.
    They can only be changed by the user in config or code.
    """

    # Maximum total operations (commands/tools) per plan execution
    # After this, execution STOPS and requires human approval
    max_total_operations: int = 25

    # Maximum wall-clock time for a single plan (seconds)
    # After this, execution STOPS regardless of progress
    max_execution_time_seconds: int = 300  # 5 minutes

    # Maximum privilege escalations (sudo additions) per plan
    # Prevents unbounded privilege creep
    max_privilege_escalations: int = 3

    # Maximum steps that can be injected during recovery
    # Prevents the plan from growing without bound
    max_injected_steps: int = 5

    # Require human checkpoint after this many automated recoveries
    # Forces human oversight even during "successful" recovery
    human_checkpoint_after_recoveries: int = 2

    # Maximum patterns to store in learning memory
    # Prevents unbounded memory growth
    max_learned_patterns: int = 1000

    # Maximum age for rollback history (hours)
    # Old entries are pruned to prevent unbounded growth
    max_rollback_history_hours: int = 24


@dataclass
class ExecutionBudget:
    """Tracks resource consumption against SafetyLimits.

    This is the runtime tracker that enforces SafetyLimits.
    It's created fresh for each plan execution.
    """

    limits: SafetyLimits
    start_time: datetime = field(default_factory=datetime.now)

    # Counters - increment as operations happen
    operations_executed: int = 0
    privilege_escalations: int = 0
    steps_injected: int = 0
    automated_recoveries: int = 0

    # State flags
    human_checkpoint_required: bool = False
    budget_exhausted: bool = False
    exhaustion_reason: str = ""

    def record_operation(self) -> bool:
        """Record an operation. Returns False if budget exhausted."""
        self.operations_executed += 1
        if self.operations_executed >= self.limits.max_total_operations:
            self._exhaust("Maximum operations reached ({})".format(
                self.limits.max_total_operations
            ))
            return False
        return True

    def record_privilege_escalation(self) -> bool:
        """Record a privilege escalation (e.g., adding sudo).
        Returns False if limit reached.
        """
        self.privilege_escalations += 1
        if self.privilege_escalations >= self.limits.max_privilege_escalations:
            self._exhaust("Maximum privilege escalations reached ({})".format(
                self.limits.max_privilege_escalations
            ))
            return False
        return True

    def record_injected_step(self) -> bool:
        """Record an injected step. Returns False if limit reached."""
        self.steps_injected += 1
        if self.steps_injected >= self.limits.max_injected_steps:
            self._exhaust("Maximum injected steps reached ({})".format(
                self.limits.max_injected_steps
            ))
            return False
        return True

    def record_recovery(self) -> bool:
        """Record an automated recovery. Returns False if checkpoint needed."""
        self.automated_recoveries += 1
        if self.automated_recoveries >= self.limits.human_checkpoint_after_recoveries:
            self.human_checkpoint_required = True
            return False
        return True

    def check_time_limit(self) -> bool:
        """Check if we've exceeded the time limit."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed >= self.limits.max_execution_time_seconds:
            self._exhaust("Maximum execution time reached ({:.0f}s)".format(
                self.limits.max_execution_time_seconds
            ))
            return False
        return True

    def _exhaust(self, reason: str) -> None:
        """Mark budget as exhausted."""
        self.budget_exhausted = True
        self.exhaustion_reason = reason
        logger.warning("Execution budget exhausted: %s", reason)

    def get_status(self) -> dict[str, Any]:
        """Get current budget status for reporting."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "operations": f"{self.operations_executed}/{self.limits.max_total_operations}",
            "time": f"{elapsed:.0f}s/{self.limits.max_execution_time_seconds}s",
            "escalations": f"{self.privilege_escalations}/{self.limits.max_privilege_escalations}",
            "injected_steps": f"{self.steps_injected}/{self.limits.max_injected_steps}",
            "recoveries": f"{self.automated_recoveries}/{self.limits.human_checkpoint_after_recoveries}",
            "exhausted": self.budget_exhausted,
            "checkpoint_required": self.human_checkpoint_required,
        }


def check_scope_drift(original_request: str, proposed_action: str) -> tuple[bool, str]:
    """Check if a proposed action drifts too far from the original request.

    Returns (is_safe, reason).

    This is a heuristic check to prevent the system from deciding to
    "fix" things that weren't part of the original request.
    """
    # Normalize for comparison
    original_lower = original_request.lower()
    action_lower = proposed_action.lower()

    # Dangerous scope expansions - actions that go way beyond typical fixes
    dangerous_patterns = [
        (r"rm\s+-rf\s+/(?!tmp)", "Recursive deletion outside /tmp"),
        (r"chmod\s+-R\s+777", "World-writable recursive permissions"),
        (r"curl.*\|\s*bash", "Piping remote script to shell"),
        (r"wget.*\|\s*sh", "Piping remote script to shell"),
        (r"dd\s+if=.*/dev/", "Raw disk write"),
        (r"mkfs\.", "Filesystem creation"),
        (r"fdisk|parted|gdisk", "Partition manipulation"),
        (r"systemctl\s+(disable|mask)\s+.*firewall", "Disabling firewall"),
        (r"iptables\s+-F", "Flushing firewall rules"),
        (r"passwd|chpasswd|usermod", "User credential modification"),
        (r"visudo|sudoers", "Sudo configuration"),
        (r"ssh-keygen.*-y.*>", "SSH key extraction"),
    ]

    for pattern, reason in dangerous_patterns:
        # Use IGNORECASE since we're matching against lowercased strings
        # but patterns may have uppercase (e.g., -R for recursive)
        if (re.search(pattern, action_lower, re.IGNORECASE) and
                not re.search(pattern, original_lower, re.IGNORECASE)):
            return False, f"Scope drift detected: {reason}"

    # Check for privilege escalation in fixes (sudo being added)
    if "sudo" in action_lower and "sudo" not in original_lower:
        # This is tracked separately in ExecutionBudget
        # Just flag it for awareness
        logger.debug("Privilege escalation detected in proposed action")

    return True, "Within scope"


class ErrorCategory(Enum):
    """Classification of execution errors."""

    TRANSIENT = "transient"            # Network timeout, temporary lock - retry may work
    MISSING_DEPENDENCY = "missing_dep"  # Package/tool not installed
    PERMISSION_DENIED = "permission"    # Need sudo or different user
    NOT_FOUND = "not_found"            # File/command doesn't exist
    ALREADY_EXISTS = "exists"          # Resource already present (often OK)
    CONFLICT = "conflict"              # Version/state conflict
    RESOURCE_BUSY = "busy"             # Device/file in use
    INVALID_INPUT = "invalid"          # Bad arguments/syntax
    SYSTEM_ERROR = "system"            # Kernel/hardware issue
    UNKNOWN = "unknown"                # Can't classify


@dataclass
class ErrorDiagnosis:
    """Detailed diagnosis of an execution error."""

    category: ErrorCategory
    original_error: str
    explanation: str
    is_retryable: bool
    suggested_fix: str | None
    fix_command: str | None
    requires_user: bool  # Need human intervention
    confidence: float  # 0.0 to 1.0


@dataclass
class ResolutionAttempt:
    """Record of an attempt to resolve an error."""

    error_diagnosis: ErrorDiagnosis
    fix_applied: str
    success: bool
    result_message: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionMemory:
    """Memory of what works/fails on this system."""

    successful_patterns: dict[str, list[str]] = field(default_factory=dict)
    failed_patterns: dict[str, list[str]] = field(default_factory=dict)
    resolution_history: list[ResolutionAttempt] = field(default_factory=list)
    system_quirks: dict[str, str] = field(default_factory=dict)


# Error patterns for classification
ERROR_PATTERNS = {
    ErrorCategory.MISSING_DEPENDENCY: [
        r"command not found",
        r"No such file or directory.*bin/",
        r"package .* is not installed",
        r"Unable to locate package",
        r"E: Package '.*' has no installation candidate",
        r"error: target not found:",  # pacman
        r"No match for argument:",    # dnf
        r"ModuleNotFoundError",
        r"ImportError",
        r"cannot find.*shared library",
        r"error while loading shared libraries",
    ],
    ErrorCategory.PERMISSION_DENIED: [
        r"Permission denied",
        r"Access denied",
        r"Operation not permitted",
        r"must be root",
        r"requires root",
        r"need to be root",
        r"you do not have permission",
        r"EACCES",
        r"sudo:.*password",
    ],
    ErrorCategory.NOT_FOUND: [
        r"No such file or directory",
        r"File not found",
        r"does not exist",
        r"cannot stat",
        r"cannot access",
        r"not found$",
        r"unit .* not found",  # systemd
    ],
    ErrorCategory.ALREADY_EXISTS: [
        r"already exists",
        r"File exists",
        r"EEXIST",
        r"is already installed",
        r"already running",
        r"already enabled",
    ],
    ErrorCategory.CONFLICT: [
        r"version conflict",
        r"dependency conflict",
        r"breaks:",
        r"conflicts with",
        r"held packages",
        r"unmet dependencies",
    ],
    ErrorCategory.RESOURCE_BUSY: [
        r"Device or resource busy",
        r"Resource temporarily unavailable",
        r"already in use",
        r"lock file",
        r"Could not get lock",
        r"database is locked",
        r"EBUSY",
    ],
    ErrorCategory.TRANSIENT: [
        r"Connection timed out",
        r"Network is unreachable",
        r"Temporary failure",
        r"try again",
        r"ETIMEDOUT",
        r"ECONNREFUSED",
        r"Failed to connect",
        r"Could not resolve host",
    ],
    ErrorCategory.INVALID_INPUT: [
        r"invalid option",
        r"unrecognized option",
        r"invalid argument",
        r"syntax error",
        r"bad syntax",
        r"Usage:",
    ],
    ErrorCategory.SYSTEM_ERROR: [
        r"kernel panic",
        r"segmentation fault",
        r"core dumped",
        r"Out of memory",
        r"No space left on device",
        r"Read-only file system",
        r"I/O error",
    ],
}

# Common fixes for error categories
COMMON_FIXES = {
    ErrorCategory.MISSING_DEPENDENCY: {
        "apt": "sudo apt update && sudo apt install -y {package}",
        "dnf": "sudo dnf install -y {package}",
        "pacman": "sudo pacman -S --noconfirm {package}",
        "pip": "pip install {package}",
    },
    ErrorCategory.PERMISSION_DENIED: {
        "add_sudo": "sudo {original_command}",
        "fix_permissions": "sudo chmod +r {path}",
    },
    ErrorCategory.RESOURCE_BUSY: {
        "wait_retry": "sleep 5 && {original_command}",
        "kill_process": "sudo fuser -k {path}",
    },
    ErrorCategory.TRANSIENT: {
        "retry": "{original_command}",
        "retry_with_wait": "sleep 10 && {original_command}",
    },
}


class ErrorClassifier:
    """Classifies execution errors and suggests fixes."""

    def __init__(self) -> None:
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns."""
        self._patterns = {
            category: [re.compile(p, re.IGNORECASE) for p in patterns]
            for category, patterns in ERROR_PATTERNS.items()
        }

    def classify(self, error_text: str, command: str = "") -> ErrorDiagnosis:
        """Classify an error and suggest resolution.

        Args:
            error_text: The error message/output
            command: The command that failed (for context)

        Returns:
            ErrorDiagnosis with classification and suggestions
        """
        if not error_text:
            return ErrorDiagnosis(
                category=ErrorCategory.UNKNOWN,
                original_error="",
                explanation="No error output to analyze",
                is_retryable=False,
                suggested_fix=None,
                fix_command=None,
                requires_user=True,
                confidence=0.0,
            )

        # Find matching category
        best_match: ErrorCategory = ErrorCategory.UNKNOWN
        best_confidence = 0.0

        for category, patterns in self._patterns.items():
            for pattern in patterns:
                if pattern.search(error_text):
                    # Weight by pattern specificity
                    confidence = 0.7 + (len(pattern.pattern) / 100)
                    if confidence > best_confidence:
                        best_match = category
                        best_confidence = min(confidence, 0.95)

        # Generate diagnosis
        return self._create_diagnosis(best_match, error_text, command, best_confidence)

    def _create_diagnosis(
        self,
        category: ErrorCategory,
        error: str,
        command: str,
        confidence: float,
    ) -> ErrorDiagnosis:
        """Create a detailed diagnosis for an error category."""

        # Default values
        is_retryable = False
        suggested_fix = None
        fix_command = None
        requires_user = False

        if category == ErrorCategory.MISSING_DEPENDENCY:
            # Try to extract package name
            package = self._extract_package_name(error)
            suggested_fix = f"Install missing package: {package}" if package else "Install missing dependency"
            fix_command = self._get_install_command(package) if package else None
            is_retryable = True  # After installing the dep
            explanation = f"A required package or command is not installed: {package or 'unknown'}"

        elif category == ErrorCategory.PERMISSION_DENIED:
            suggested_fix = "Run with sudo or fix permissions"
            if command and not command.strip().startswith("sudo"):
                fix_command = f"sudo {command}"
            is_retryable = True
            explanation = "The operation requires elevated permissions"

        elif category == ErrorCategory.NOT_FOUND:
            explanation = "A required file or resource doesn't exist"
            suggested_fix = "Check path or create the resource first"
            requires_user = True  # Usually need human judgment

        elif category == ErrorCategory.ALREADY_EXISTS:
            explanation = "The resource already exists (may not be an error)"
            is_retryable = False  # Often this is fine
            # This might actually be success
            suggested_fix = "Check if the existing resource is acceptable"

        elif category == ErrorCategory.RESOURCE_BUSY:
            explanation = "A resource is locked or in use by another process"
            is_retryable = True
            suggested_fix = "Wait and retry, or stop the conflicting process"
            fix_command = f"sleep 5 && {command}" if command else None

        elif category == ErrorCategory.TRANSIENT:
            explanation = "A temporary issue occurred (network, timing)"
            is_retryable = True
            suggested_fix = "Wait and retry"
            fix_command = f"sleep 10 && {command}" if command else None

        elif category == ErrorCategory.CONFLICT:
            explanation = "There's a version or dependency conflict"
            requires_user = True
            suggested_fix = "Resolve the conflict manually or try a different version"

        elif category == ErrorCategory.INVALID_INPUT:
            explanation = "The command has incorrect syntax or arguments"
            requires_user = True
            suggested_fix = "Check command syntax and arguments"

        elif category == ErrorCategory.SYSTEM_ERROR:
            explanation = "A system-level error occurred"
            requires_user = True
            suggested_fix = "Check system resources (disk space, memory)"

        else:
            explanation = "Unable to determine the cause of the error"
            requires_user = True
            suggested_fix = "Examine the error output manually"

        return ErrorDiagnosis(
            category=category,
            original_error=error[:500],  # Truncate for storage
            explanation=explanation,
            is_retryable=is_retryable,
            suggested_fix=suggested_fix,
            fix_command=fix_command,
            requires_user=requires_user,
            confidence=confidence,
        )

    def _extract_package_name(self, error: str) -> str | None:
        """Try to extract a package name from an error message."""
        patterns = [
            r"package ['\"]?(\w[\w\-\.]+)['\"]? is not installed",
            r"Unable to locate package (\w[\w\-\.]+)",
            r"No package (\w[\w\-\.]+) available",
            r"command not found: (\w+)",
            r"(\w+): command not found",
            r"ModuleNotFoundError: No module named ['\"](\w+)['\"]",
        ]

        for pattern in patterns:
            match = re.search(pattern, error, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _get_install_command(self, package: str) -> str | None:
        """Get the install command for a package."""
        import os

        if os.path.exists("/usr/bin/apt"):
            return f"sudo apt update && sudo apt install -y {package}"
        elif os.path.exists("/usr/bin/dnf"):
            return f"sudo dnf install -y {package}"
        elif os.path.exists("/usr/bin/pacman"):
            return f"sudo pacman -S --noconfirm {package}"
        return None


class AdaptiveReplanner:
    """Dynamically revises plans based on execution feedback."""

    def __init__(
        self,
        error_classifier: ErrorClassifier,
        memory: ExecutionMemory,
    ) -> None:
        self.classifier = error_classifier
        self.memory = memory
        self.max_retries = 3
        self.max_fix_attempts = 2

    def handle_step_failure(
        self,
        plan: TaskPlan,
        step: TaskStep,
        result: StepResult,
    ) -> tuple[TaskStep | None, str]:
        """Handle a step failure and potentially generate a fix.

        Args:
            plan: The current plan
            step: The step that failed
            result: The failure result

        Returns:
            (new_step_to_try, explanation) - new_step is None if no fix available
        """
        error = result.error or result.output
        command = step.action.get("command", "")

        # Classify the error
        diagnosis = self.classifier.classify(error, command)

        logger.info(
            "Error diagnosis: category=%s, retryable=%s, fix=%s",
            diagnosis.category.value,
            diagnosis.is_retryable,
            diagnosis.fix_command,
        )

        # Check if we've already tried this fix
        step_key = f"{step.id}:{diagnosis.category.value}"
        previous_attempts = sum(
            1 for r in self.memory.resolution_history
            if r.error_diagnosis.category == diagnosis.category
            and step.id in str(r.fix_applied)
        )

        if previous_attempts >= self.max_fix_attempts:
            return None, f"Already tried {previous_attempts} fixes for this error type"

        # Generate a fix step if possible
        if diagnosis.fix_command and diagnosis.is_retryable:
            fix_step = self._create_fix_step(step, diagnosis)
            explanation = f"Trying fix: {diagnosis.suggested_fix}"
            return fix_step, explanation

        if diagnosis.requires_user:
            return None, f"This needs your input: {diagnosis.suggested_fix}"

        return None, diagnosis.explanation

    def _create_fix_step(self, original_step: TaskStep, diagnosis: ErrorDiagnosis) -> TaskStep:
        """Create a step to fix an error."""
        return TaskStep(
            id=f"{original_step.id}_fix_{diagnosis.category.value}",
            title=f"Fix: {diagnosis.suggested_fix}",
            description=f"Attempting to fix: {diagnosis.explanation}",
            step_type=StepType.COMMAND,
            action={"command": diagnosis.fix_command},
            explanation=f"This should fix the error: {diagnosis.explanation}",
        )

    def inject_dependency_step(
        self,
        plan: TaskPlan,
        before_step: TaskStep,
        dependency: str,
    ) -> TaskStep:
        """Inject a step to install a missing dependency.

        Args:
            plan: The plan to modify
            before_step: Insert the new step before this one
            dependency: The package to install

        Returns:
            The new step that was injected
        """
        install_cmd = self.classifier._get_install_command(dependency)
        if not install_cmd:
            install_cmd = f"# Install {dependency} manually"

        new_step = TaskStep(
            id=f"install_{dependency}_{datetime.now().strftime('%H%M%S')}",
            title=f"Install {dependency}",
            description=f"Installing missing dependency: {dependency}",
            step_type=StepType.COMMAND,
            action={"command": install_cmd},
            explanation=f"The previous step needs {dependency} to be installed first",
        )

        # Find insertion point
        try:
            idx = plan.steps.index(before_step)
            plan.steps.insert(idx, new_step)
        except ValueError:
            plan.steps.append(new_step)

        return new_step

    def record_resolution(
        self,
        diagnosis: ErrorDiagnosis,
        fix: str,
        success: bool,
        message: str,
    ) -> None:
        """Record a resolution attempt for learning."""
        attempt = ResolutionAttempt(
            error_diagnosis=diagnosis,
            fix_applied=fix,
            success=success,
            result_message=message,
        )
        self.memory.resolution_history.append(attempt)

        # Update patterns
        pattern_key = f"{diagnosis.category.value}:{fix[:50]}"
        if success:
            if pattern_key not in self.memory.successful_patterns:
                self.memory.successful_patterns[pattern_key] = []
            self.memory.successful_patterns[pattern_key].append(message[:100])
        else:
            if pattern_key not in self.memory.failed_patterns:
                self.memory.failed_patterns[pattern_key] = []
            self.memory.failed_patterns[pattern_key].append(message[:100])

    def suggest_alternatives(
        self,
        step: TaskStep,
        diagnosis: ErrorDiagnosis,
    ) -> list[dict[str, Any]]:
        """Suggest alternative approaches for a failed step.

        Returns list of alternative actions to try.
        """
        alternatives = []

        if diagnosis.category == ErrorCategory.PERMISSION_DENIED:
            command = step.action.get("command", "")
            if command and not command.startswith("sudo"):
                alternatives.append({
                    "description": "Run with sudo",
                    "command": f"sudo {command}",
                })

        elif diagnosis.category == ErrorCategory.MISSING_DEPENDENCY:
            package = self.classifier._extract_package_name(diagnosis.original_error)
            if package:
                install_cmd = self.classifier._get_install_command(package)
                if install_cmd:
                    alternatives.append({
                        "description": f"Install {package} first",
                        "command": install_cmd,
                        "then_retry": True,
                    })

        elif diagnosis.category == ErrorCategory.TRANSIENT:
            alternatives.append({
                "description": "Wait and retry",
                "command": step.action.get("command", ""),
                "delay": 10,
            })

        return alternatives


class ExecutionLearner:
    """Learns from execution to improve future performance.

    SAFETY: Enforces limits on stored patterns to prevent unbounded memory growth.
    Old patterns are pruned automatically.
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        limits: SafetyLimits | None = None,
    ) -> None:
        if storage_path is None:
            storage_path = Path.home() / ".config" / "reos" / "knowledge.db"
        self.storage_path = storage_path
        self.limits = limits or SafetyLimits()
        self.memory = ExecutionMemory()
        self._load()

    def _load(self) -> None:
        """Load learned patterns from disk."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            self.memory.successful_patterns = data.get("successful_patterns", {})
            self.memory.failed_patterns = data.get("failed_patterns", {})
            self.memory.system_quirks = data.get("system_quirks", {})
            logger.debug("Loaded %d learned patterns", len(self.memory.successful_patterns))

            # Prune on load if over limits
            self._prune_patterns()
        except Exception as e:
            logger.warning("Failed to load learning data: %s", e)

    def save(self) -> None:
        """Save learned patterns to disk (with limits enforced)."""
        # Prune before saving
        self._prune_patterns()

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "successful_patterns": self.memory.successful_patterns,
            "failed_patterns": self.memory.failed_patterns,
            "system_quirks": self.memory.system_quirks,
            "updated": datetime.now().isoformat(),
            "pattern_count": len(self.memory.successful_patterns) + len(self.memory.failed_patterns),
            "limit": self.limits.max_learned_patterns,
        }
        try:
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save learning data: %s", e)

    def _prune_patterns(self) -> None:
        """Prune patterns to stay within limits.

        SAFETY: This enforces the max_learned_patterns limit.
        Oldest patterns are removed first.
        """
        total = len(self.memory.successful_patterns) + len(self.memory.failed_patterns)
        if total <= self.limits.max_learned_patterns:
            return

        logger.info("Pruning learned patterns: %d -> %d", total, self.limits.max_learned_patterns)

        # Sort by most recent timestamp and keep only the most recent
        all_patterns = []
        for key, values in self.memory.successful_patterns.items():
            for v in values:
                ts = v.get("timestamp", "1970-01-01")
                all_patterns.append(("success", key, ts))
        for key, values in self.memory.failed_patterns.items():
            for v in values:
                ts = v.get("timestamp", "1970-01-01")
                all_patterns.append(("fail", key, ts))

        # Sort by timestamp descending (newest first)
        all_patterns.sort(key=lambda x: x[2], reverse=True)

        # Keep only the limit
        to_keep_success = set()
        to_keep_fail = set()
        for pattern_type, key, _ in all_patterns[:self.limits.max_learned_patterns]:
            if pattern_type == "success":
                to_keep_success.add(key)
            else:
                to_keep_fail.add(key)

        # Prune
        self.memory.successful_patterns = {
            k: v for k, v in self.memory.successful_patterns.items()
            if k in to_keep_success
        }
        self.memory.failed_patterns = {
            k: v for k, v in self.memory.failed_patterns.items()
            if k in to_keep_fail
        }

    def record_success(self, step: TaskStep, result: StepResult) -> None:
        """Record a successful step execution."""
        key = self._step_signature(step)
        if key not in self.memory.successful_patterns:
            self.memory.successful_patterns[key] = []
        self.memory.successful_patterns[key].append({
            "timestamp": datetime.now().isoformat(),
            "duration": result.duration_seconds,
        })
        # Keep only last 10 successes per pattern
        self.memory.successful_patterns[key] = self.memory.successful_patterns[key][-10:]

    def record_failure(self, step: TaskStep, result: StepResult, diagnosis: ErrorDiagnosis) -> None:
        """Record a failed step execution."""
        key = self._step_signature(step)
        if key not in self.memory.failed_patterns:
            self.memory.failed_patterns[key] = []
        self.memory.failed_patterns[key].append({
            "timestamp": datetime.now().isoformat(),
            "error_category": diagnosis.category.value,
            "error": result.error[:200] if result.error else "",
        })

    def record_system_quirk(self, quirk_id: str, description: str) -> None:
        """Record a system-specific behavior."""
        self.memory.system_quirks[quirk_id] = description

    def get_success_rate(self, step: TaskStep) -> float:
        """Get historical success rate for a step type."""
        key = self._step_signature(step)
        successes = len(self.memory.successful_patterns.get(key, []))
        failures = len(self.memory.failed_patterns.get(key, []))
        total = successes + failures
        return successes / total if total > 0 else 0.5

    def should_skip_step(self, step: TaskStep) -> tuple[bool, str]:
        """Check if a step should be skipped based on history.

        Returns (should_skip, reason).
        """
        key = self._step_signature(step)

        # Check for consistent failures
        failures = self.memory.failed_patterns.get(key, [])
        if len(failures) >= 3:
            # Check if all recent failures are the same type
            recent = failures[-3:]
            categories = [f.get("error_category") for f in recent]
            if len(set(categories)) == 1:
                return True, f"This step has failed 3+ times with: {categories[0]}"

        return False, ""

    def _step_signature(self, step: TaskStep) -> str:
        """Create a signature for a step type (for pattern matching)."""
        action = step.action
        if "command" in action:
            # Normalize command - remove specific paths/values
            cmd = action["command"]
            # Replace specific values with placeholders
            cmd = re.sub(r"/[^\s]+", "/PATH", cmd)
            cmd = re.sub(r"\d+", "N", cmd)
            return f"cmd:{cmd[:100]}"
        elif "tool" in action:
            return f"tool:{action['tool']}"
        return f"type:{step.step_type.value}"


class AdaptiveExecutor:
    """Enhanced executor with adaptive failure handling.

    SAFETY: Enforces hard limits via ExecutionBudget to prevent runaway execution.
    These limits cannot be overridden by the AI during execution.
    """

    def __init__(
        self,
        base_executor: Any,  # The original ExecutionEngine
        learner: ExecutionLearner | None = None,
        safety_limits: SafetyLimits | None = None,
    ) -> None:
        self.base = base_executor
        self.classifier = ErrorClassifier()
        self.learner = learner or ExecutionLearner()
        self.replanner = AdaptiveReplanner(self.classifier, self.learner.memory)
        self.safety_limits = safety_limits or SafetyLimits()

        # Current execution budget (created per-execution)
        self._current_budget: ExecutionBudget | None = None

    def execute_with_recovery(
        self,
        context: Any,  # ExecutionContext
        on_recovery_attempt: Callable[[str], None] | None = None,
        on_budget_exhausted: Callable[[str, dict], None] | None = None,
    ) -> bool:
        """Execute plan with automatic error recovery and circuit breakers.

        Args:
            context: The execution context
            on_recovery_attempt: Callback when attempting recovery
            on_budget_exhausted: Callback when safety limits are hit

        Returns:
            True if plan completed successfully

        SAFETY: This method enforces hard limits. If any limit is reached,
        execution STOPS and control returns to the human.
        """
        from .executor import ExecutionState

        # Create fresh budget for this execution
        budget = ExecutionBudget(limits=self.safety_limits)
        self._current_budget = budget

        max_recovery_attempts = 3
        recovery_count = 0
        original_request = context.plan.original_request

        while context.state == ExecutionState.RUNNING:
            # === CIRCUIT BREAKER: Time limit ===
            if not budget.check_time_limit():
                self._handle_budget_exhaustion(context, budget, on_budget_exhausted)
                break

            result = self.base.execute_next_step(context)

            if result is None:
                break

            # === CIRCUIT BREAKER: Operation count ===
            if not budget.record_operation():
                self._handle_budget_exhaustion(context, budget, on_budget_exhausted)
                break

            if result.success:
                # Record success for learning
                if context.current_step:
                    self.learner.record_success(context.current_step, result)
                continue

            # Handle failure with recovery
            step = context.current_step
            if not step:
                continue

            # Diagnose the error
            diagnosis = self.classifier.classify(
                result.error or result.output,
                step.action.get("command", ""),
            )

            # Record failure for learning
            self.learner.record_failure(step, result, diagnosis)

            if recovery_count >= max_recovery_attempts:
                logger.warning("Max recovery attempts reached")
                break

            # Try to create a fix
            fix_step, explanation = self.replanner.handle_step_failure(
                context.plan, step, result
            )

            if on_recovery_attempt:
                on_recovery_attempt(explanation)

            if fix_step:
                # === CIRCUIT BREAKER: Check scope drift ===
                fix_cmd = fix_step.action.get("command", "")
                is_safe, scope_reason = check_scope_drift(original_request, fix_cmd)
                if not is_safe:
                    logger.warning("Blocking fix due to scope drift: %s", scope_reason)
                    if on_recovery_attempt:
                        on_recovery_attempt(f"Blocked: {scope_reason}")
                    context.state = ExecutionState.PAUSED
                    break

                # === CIRCUIT BREAKER: Privilege escalation ===
                if "sudo" in fix_cmd:
                    if not budget.record_privilege_escalation():
                        self._handle_budget_exhaustion(context, budget, on_budget_exhausted)
                        break

                # === CIRCUIT BREAKER: Injected step limit ===
                if not budget.record_injected_step():
                    self._handle_budget_exhaustion(context, budget, on_budget_exhausted)
                    break

                recovery_count += 1

                # === CIRCUIT BREAKER: Human checkpoint ===
                if not budget.record_recovery():
                    logger.info("Human checkpoint required after %d recoveries",
                                budget.automated_recoveries)
                    if on_recovery_attempt:
                        on_recovery_attempt(
                            f"Pausing for human review after {budget.automated_recoveries} "
                            "automated recoveries. Status: " +
                            str(budget.get_status())
                        )
                    context.state = ExecutionState.PAUSED
                    break

                logger.info("Attempting recovery: %s", fix_step.title)

                # Execute the fix
                fix_result = self.base._execute_step(fix_step, context)

                # Count this as an operation too
                if not budget.record_operation():
                    self._handle_budget_exhaustion(context, budget, on_budget_exhausted)
                    break

                if fix_result.success:
                    self.replanner.record_resolution(
                        diagnosis, fix_step.action.get("command", ""), True, "Fix succeeded"
                    )

                    # Reset the failed step to try again
                    step.status = StepStatus.PENDING
                    context.plan.failed_steps.discard(step.id)
                    logger.info("Fix applied, retrying original step")
                else:
                    self.replanner.record_resolution(
                        diagnosis, fix_step.action.get("command", ""), False, fix_result.error or "Fix failed"
                    )

            elif diagnosis.requires_user:
                # Need user intervention
                context.state = ExecutionState.PAUSED
                break

        # Save learning at the end (with limits enforced)
        self.learner.save()
        self._current_budget = None

        return context.plan.is_complete() and not context.plan.has_failed()

    def _handle_budget_exhaustion(
        self,
        context: Any,
        budget: ExecutionBudget,
        callback: Callable[[str, dict], None] | None,
    ) -> None:
        """Handle when safety limits are reached."""
        from .executor import ExecutionState

        context.state = ExecutionState.PAUSED
        status = budget.get_status()

        logger.warning(
            "Execution paused due to safety limits: %s. Status: %s",
            budget.exhaustion_reason,
            status,
        )

        if callback:
            callback(budget.exhaustion_reason, status)

    def get_current_budget_status(self) -> dict[str, Any] | None:
        """Get the current execution budget status, if executing."""
        if self._current_budget:
            return self._current_budget.get_status()
        return None
