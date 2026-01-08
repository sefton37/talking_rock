"""Contract - explicit, testable definition of success.

A Contract is the system's commitment to what will be delivered.
It is:
- Explicit: No ambiguity about what success means
- Testable: Every criterion can be verified programmatically
- Decomposable: Can be broken into smaller contracts
- Grounded: Based on intent, not hallucination

The Contract is what prevents scope creep, hallucination, and
partial implementations. If it's not in the contract, it's not done.
If it's in the contract, it must be verified.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.intent import DiscoveredIntent
    from reos.code_mode.project_memory import ProjectMemoryStore
    from reos.code_mode.sandbox import CodeSandbox
    from reos.code_mode.session_logger import SessionLogger
    from reos.code_mode.streaming import ExecutionObserver
    from reos.code_mode.test_generator import TestGenerator
    from reos.providers import LLMProvider

logger = logging.getLogger(__name__)


class ContractStatus(Enum):
    """Status of a contract."""

    DRAFT = "draft"           # Not yet approved
    ACTIVE = "active"         # In progress
    FULFILLED = "fulfilled"   # All criteria met
    FAILED = "failed"         # Cannot be fulfilled
    SUPERSEDED = "superseded" # Replaced by new contract


class CriterionType(Enum):
    """Type of acceptance criterion."""

    FILE_EXISTS = "file_exists"           # A file must exist
    FILE_CONTAINS = "file_contains"       # A file must contain pattern
    FILE_NOT_CONTAINS = "file_not_contains"  # A file must NOT contain pattern
    TESTS_PASS = "tests_pass"             # Tests must pass
    CODE_COMPILES = "code_compiles"       # Code must compile/lint
    FUNCTION_EXISTS = "function_exists"   # A function must exist
    CLASS_EXISTS = "class_exists"         # A class must exist
    COMMAND_SUCCEEDS = "command_succeeds" # Arbitrary command returns 0
    GENERATED_TEST_PASSES = "generated_test_passes"  # Generated test must pass
    LAYER_APPROPRIATE = "layer_appropriate"  # Logic placed in correct layer
    CUSTOM = "custom"                     # Custom verification


@dataclass
class TestSpecification:
    """Generated test code for a criterion.

    This represents actual pytest test code that was generated from intent.
    The test code serves as the acceptance criterion - when the test passes,
    the feature is considered complete (test-first development).
    """

    test_code: str           # Full pytest test code including imports
    test_file: str           # Path to test file (e.g., "tests/test_feature.py")
    test_function: str       # Test function name (e.g., "test_add_user")
    imports: list[str] = field(default_factory=list)  # Required imports
    setup_code: str = ""     # Optional setup/fixtures
    rationale: str = ""      # Why this test proves the feature works

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "test_code": self.test_code,
            "test_file": self.test_file,
            "test_function": self.test_function,
            "imports": self.imports,
            "setup_code": self.setup_code,
            "rationale": self.rationale,
        }


@dataclass
class LayerConstraint:
    """Constraint for LAYER_APPROPRIATE criterion.

    Specifies what logic is being added and where it should/shouldn't go.
    """

    logic_type: str  # "business_logic", "routing", "parsing", etc.
    appropriate_layers: list[str]  # Layers where this logic belongs
    inappropriate_layers: list[str]  # Layers where this logic should NOT go
    reason: str  # Why this placement matters


@dataclass
class AcceptanceCriterion:
    """A single testable criterion for contract fulfillment."""

    id: str
    type: CriterionType
    description: str
    # Type-specific parameters
    target_file: str | None = None
    pattern: str | None = None
    command: str | None = None
    # Generated test specification (for GENERATED_TEST_PASSES)
    test_spec: TestSpecification | None = None
    # Layer constraint (for LAYER_APPROPRIATE)
    layer_constraint: LayerConstraint | None = None
    # Status
    verified: bool = False
    verification_output: str = ""
    verified_at: datetime | None = None

    def verify(self, sandbox: CodeSandbox) -> bool:
        """Verify this criterion against the sandbox."""
        result = False
        try:
            if self.type == CriterionType.FILE_EXISTS:
                result = self._verify_file_exists(sandbox)
            elif self.type == CriterionType.FILE_CONTAINS:
                result = self._verify_file_contains(sandbox)
            elif self.type == CriterionType.FILE_NOT_CONTAINS:
                result = self._verify_file_not_contains(sandbox)
            elif self.type == CriterionType.TESTS_PASS:
                result = self._verify_tests_pass(sandbox)
            elif self.type == CriterionType.CODE_COMPILES:
                result = self._verify_code_compiles(sandbox)
            elif self.type == CriterionType.FUNCTION_EXISTS:
                result = self._verify_function_exists(sandbox)
            elif self.type == CriterionType.CLASS_EXISTS:
                result = self._verify_class_exists(sandbox)
            elif self.type == CriterionType.COMMAND_SUCCEEDS:
                result = self._verify_command_succeeds(sandbox)
            elif self.type == CriterionType.GENERATED_TEST_PASSES:
                result = self._verify_generated_test_passes(sandbox)
            elif self.type == CriterionType.LAYER_APPROPRIATE:
                result = self._verify_layer_appropriate(sandbox)
            # else: Custom - cannot auto-verify, result stays False
        except Exception as e:
            logger.error("Criterion verification failed for '%s': %s", self.description[:50], e, exc_info=True)
            self.verification_output = f"Error: {e}"
            result = False

        self.verified = result
        if result:
            self.verified_at = datetime.now(timezone.utc)
        return result

    def _verify_file_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file:
            return False
        try:
            sandbox.read_file(self.target_file, start=1, end=1)
            self.verification_output = f"File exists: {self.target_file}"
            return True
        except Exception:
            self.verification_output = f"File not found: {self.target_file}"
            return False

    def _verify_file_contains(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file or not self.pattern:
            return False
        try:
            matches = sandbox.grep(
                pattern=self.pattern,
                glob_pattern=self.target_file,
                max_results=1,
            )
            if matches:
                self.verification_output = f"Pattern found in {self.target_file}"
                return True
            self.verification_output = f"Pattern not found in {self.target_file}"
            return False
        except Exception as e:
            logger.error("Error searching for pattern in %s: %s", self.target_file, e, exc_info=True)
            self.verification_output = f"Error searching: {e}"
            return False

    def _verify_file_not_contains(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file or not self.pattern:
            return False
        try:
            matches = sandbox.grep(
                pattern=self.pattern,
                glob_pattern=self.target_file,
                max_results=1,
            )
            if not matches:
                self.verification_output = f"Pattern correctly absent from {self.target_file}"
                return True
            self.verification_output = f"Pattern incorrectly found in {self.target_file}"
            return False
        except Exception as e:
            logger.error("Error checking pattern absence in %s: %s", self.target_file, e, exc_info=True)
            self.verification_output = f"Error searching: {e}"
            return False

    def _verify_tests_pass(self, sandbox: CodeSandbox) -> bool:
        command = self.command or "pytest"
        returncode, stdout, stderr = sandbox.run_command(command, timeout=120)
        self.verification_output = stdout[:500] if stdout else stderr[:500]
        return returncode == 0

    def _verify_code_compiles(self, sandbox: CodeSandbox) -> bool:
        # Try common lint/check commands
        commands = [
            ("python -m py_compile", "**/*.py"),
            ("ruff check", "."),
            ("mypy", "."),
        ]
        for cmd, target in commands:
            returncode, stdout, stderr = sandbox.run_command(
                f"{cmd} {target}", timeout=60
            )
            if returncode == 0:
                self.verification_output = "Code compiles successfully"
                return True
        self.verification_output = "Compilation/lint check failed"
        return False

    def _verify_function_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.pattern:  # pattern = function name
            return False
        matches = sandbox.grep(
            pattern=rf"def {self.pattern}\s*\(",
            glob_pattern=self.target_file or "**/*.py",
            max_results=1,
        )
        if matches:
            self.verification_output = f"Function '{self.pattern}' found"
            return True
        self.verification_output = f"Function '{self.pattern}' not found"
        return False

    def _verify_class_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.pattern:  # pattern = class name
            return False
        matches = sandbox.grep(
            pattern=rf"class {self.pattern}\b",
            glob_pattern=self.target_file or "**/*.py",
            max_results=1,
        )
        if matches:
            self.verification_output = f"Class '{self.pattern}' found"
            return True
        self.verification_output = f"Class '{self.pattern}' not found"
        return False

    def _verify_command_succeeds(self, sandbox: CodeSandbox) -> bool:
        """Verify an arbitrary command returns exit code 0."""
        if not self.command:
            self.verification_output = "No command specified"
            return False
        returncode, stdout, stderr = sandbox.run_command(self.command, timeout=120)
        # Capture full output for debugging
        output = stdout if stdout else stderr
        self.verification_output = output[:2000] if output else f"Exit code: {returncode}"
        return returncode == 0

    def _verify_generated_test_passes(self, sandbox: CodeSandbox) -> bool:
        """Verify the generated test passes.

        This method:
        1. Ensures the test file exists (writes it if not)
        2. Runs only the specific generated test function
        3. Reports pass/fail with output
        """
        if not self.test_spec:
            self.verification_output = "No test specification provided"
            return False

        test_file = self.test_spec.test_file
        test_function = self.test_spec.test_function

        # 1. Ensure test file exists - write it if not
        try:
            sandbox.read_file(test_file, start=1, end=1)
        except FileNotFoundError:
            # Write the generated test file
            sandbox.write_file(test_file, self.test_spec.test_code)
            self.verification_output = f"Created test file: {test_file}"

        # 2. Run only the specific generated test
        test_path = f"{test_file}::{test_function}"
        returncode, stdout, stderr = sandbox.run_command(
            f"pytest {test_path} -v --tb=short",
            timeout=60,
        )

        # 3. Capture output
        output = stdout if stdout else stderr
        self.verification_output = output[:2000] if output else f"Exit code: {returncode}"

        return returncode == 0

    def _verify_layer_appropriate(self, sandbox: CodeSandbox) -> bool:
        """Verify that logic is placed in the appropriate layer.

        This criterion checks that:
        1. The target file exists
        2. The pattern (new logic) is found in the file
        3. The file's layer type is in the appropriate_layers list
        4. The file's layer type is NOT in the inappropriate_layers list

        Uses file path patterns to infer layer type.
        """
        if not self.layer_constraint or not self.target_file:
            self.verification_output = "Missing layer constraint or target file"
            return False

        constraint = self.layer_constraint

        # Check file exists
        try:
            sandbox.read_file(self.target_file, start=1, end=1)
        except FileNotFoundError:
            self.verification_output = f"Target file not found: {self.target_file}"
            return False

        # If pattern specified, verify it's in the file
        if self.pattern:
            matches = sandbox.grep(
                pattern=self.pattern,
                glob_pattern=self.target_file,
                max_results=1,
            )
            if not matches:
                self.verification_output = f"Pattern not found in {self.target_file}"
                return False

        # Infer layer type from file path
        file_lower = self.target_file.lower()
        inferred_layer = self._infer_layer_from_path(file_lower)

        # Check if layer is appropriate
        if constraint.inappropriate_layers:
            if inferred_layer in constraint.inappropriate_layers:
                self.verification_output = (
                    f"VIOLATION: {constraint.logic_type} placed in {inferred_layer} layer "
                    f"({self.target_file}). {constraint.reason}"
                )
                return False

        if constraint.appropriate_layers:
            if inferred_layer not in constraint.appropriate_layers and inferred_layer != "unknown":
                self.verification_output = (
                    f"WARNING: {constraint.logic_type} placed in {inferred_layer} layer "
                    f"({self.target_file}), expected one of: {constraint.appropriate_layers}. "
                    f"{constraint.reason}"
                )
                # This is a warning, not a failure - we allow it but note it
                return True

        self.verification_output = (
            f"Layer placement OK: {constraint.logic_type} in {inferred_layer} layer"
        )
        return True

    def _infer_layer_from_path(self, file_path: str) -> str:
        """Infer layer type from file path."""
        layer_patterns = {
            "rpc": ["rpc", "server", "handler", "endpoint"],
            "agent": ["agent"],
            "executor": ["executor", "runner", "worker"],
            "storage": ["db", "database", "storage", "repository", "store"],
            "service": ["service", "services/"],
        }

        for layer, patterns in layer_patterns.items():
            for pattern in patterns:
                if pattern in file_path:
                    return layer

        return "unknown"


@dataclass
class ContractStep:
    """A discrete step to fulfill part of the contract."""

    id: str
    description: str
    target_criteria: list[str]  # IDs of criteria this step addresses
    # Implementation details
    action: str                  # "create_file", "edit_file", "run_command"
    target_file: str | None = None
    content: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    command: str | None = None
    # Status
    status: str = "pending"      # pending, in_progress, completed, failed
    result: str = ""
    completed_at: datetime | None = None


@dataclass
class Contract:
    """A contract defining what success means for a task.

    The contract is the system's commitment. It defines:
    - What must be true when complete (acceptance criteria)
    - How to get there (decomposed steps)
    - How to verify completion (testable assertions)
    """

    id: str
    intent_summary: str          # What this contract is for
    acceptance_criteria: list[AcceptanceCriterion]
    steps: list[ContractStep] = field(default_factory=list)
    status: ContractStatus = ContractStatus.DRAFT
    # Hierarchy
    parent_contract_id: str | None = None  # For sub-contracts
    child_contract_ids: list[str] = field(default_factory=list)
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fulfilled_at: datetime | None = None

    def is_fulfilled(self, sandbox: CodeSandbox) -> bool:
        """Check if all acceptance criteria are met."""
        for criterion in self.acceptance_criteria:
            criterion.verified = criterion.verify(sandbox)
            if criterion.verified:
                criterion.verified_at = datetime.now(timezone.utc)

        return all(c.verified for c in self.acceptance_criteria)

    def get_unfulfilled_criteria(self) -> list[AcceptanceCriterion]:
        """Get criteria that have not been verified."""
        return [c for c in self.acceptance_criteria if not c.verified]

    def get_pending_steps(self) -> list[ContractStep]:
        """Get steps that haven't been completed."""
        return [s for s in self.steps if s.status == "pending"]

    def get_next_step(self) -> ContractStep | None:
        """Get the next step to execute."""
        pending = self.get_pending_steps()
        return pending[0] if pending else None

    def summary(self) -> str:
        """Generate human-readable contract summary."""
        lines = [
            f"## Contract: {self.intent_summary}",
            f"**Status:** {self.status.value}",
            "",
            "### Acceptance Criteria:",
        ]

        for i, criterion in enumerate(self.acceptance_criteria, 1):
            status = "✅" if criterion.verified else "⏳"
            lines.append(f"{i}. {status} {criterion.description}")

        if self.steps:
            lines.append("")
            lines.append("### Steps:")
            for i, step in enumerate(self.steps, 1):
                status_icon = {
                    "pending": "⏳",
                    "in_progress": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }.get(step.status, "❓")
                lines.append(f"{i}. {status_icon} {step.description}")

        return "\n".join(lines)


def _generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class ContractBuilder:
    """Builds contracts from discovered intent.

    The builder translates intent into explicit, testable criteria
    and decomposes the work into discrete steps.

    With test_first=True (default), generates actual test code as
    acceptance criteria - implementing test-first development.

    With project_memory provided, injects project decisions into
    criteria generation to ensure contracts respect learned preferences.
    """

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
        test_generator: "TestGenerator | None" = None,
        test_first: bool = True,
        project_memory: "ProjectMemoryStore | None" = None,
        observer: "ExecutionObserver | None" = None,
        session_logger: "SessionLogger | None" = None,
    ) -> None:
        self.sandbox = sandbox
        self._llm = llm
        self._test_generator = test_generator
        self._test_first = test_first
        self._project_memory = project_memory
        self._observer = observer
        self._session_logger = session_logger

    def _notify(self, message: str) -> None:
        """Notify observer of activity."""
        if self._observer is not None:
            self._observer.on_activity(message, module="ContractBuilder")

    def _log(
        self,
        action: str,
        message: str,
        data: dict | None = None,
        level: str = "INFO",
    ) -> None:
        """Log to session logger if available."""
        if self._session_logger is not None:
            if level == "DEBUG":
                self._session_logger.log_debug("contract", action, message, data or {})
            elif level == "WARN":
                self._session_logger.log_warn("contract", action, message, data or {})
            elif level == "ERROR":
                self._session_logger.log_error("contract", action, message, data or {})
            else:
                self._session_logger.log_info("contract", action, message, data or {})

    def build_from_intent(self, intent: DiscoveredIntent) -> Contract:
        """Build a contract from discovered intent.

        Args:
            intent: The discovered intent to build a contract for.

        Returns:
            A Contract with acceptance criteria and steps.
        """
        # Log contract building start
        self._log("build_start", "Starting contract build from intent", {
            "intent_goal": intent.goal[:100],
            "has_llm": self._llm is not None,
            "test_first": self._test_first,
            "has_test_generator": self._test_generator is not None,
        })

        # Generate acceptance criteria from intent
        self._notify("Generating acceptance criteria...")
        criteria = self._generate_criteria(intent)
        self._notify(f"Generated {len(criteria)} acceptance criteria")

        # Log criteria generation
        self._log("criteria_generated", f"Generated {len(criteria)} acceptance criteria", {
            "num_criteria": len(criteria),
            "criteria_types": [c.type.value for c in criteria],
            "criteria_descriptions": [c.description[:50] for c in criteria],
        })

        # Decompose into steps
        self._notify("Decomposing into atomic steps...")
        steps = self._decompose_into_steps(intent, criteria)
        self._notify(f"Decomposed into {len(steps)} steps")

        # Log decomposition
        self._log("steps_decomposed", f"Decomposed into {len(steps)} steps", {
            "num_steps": len(steps),
            "step_actions": [s.action for s in steps],
            "step_descriptions": [s.description[:50] for s in steps],
        })

        contract = Contract(
            id=_generate_id("contract"),
            intent_summary=intent.goal,
            acceptance_criteria=criteria,
            steps=steps,
            status=ContractStatus.DRAFT,
        )
        self._notify(f"Contract built: {intent.goal[:50]}...")

        # Log contract completion
        self._log("build_complete", "Contract build complete", {
            "contract_id": contract.id,
            "intent_summary": contract.intent_summary[:100],
            "num_criteria": len(contract.acceptance_criteria),
            "num_steps": len(contract.steps),
        })

        return contract

    def build_gap_contract(
        self,
        original_contract: Contract,
        intent: DiscoveredIntent,
    ) -> Contract:
        """Build a contract for the remaining gap.

        When a contract is partially fulfilled, this creates a new
        contract for what remains.
        """
        # Get unfulfilled criteria
        unfulfilled = original_contract.get_unfulfilled_criteria()

        if not unfulfilled:
            # All done - return empty contract
            return Contract(
                id=_generate_id("contract"),
                intent_summary=f"Gap for: {original_contract.intent_summary}",
                acceptance_criteria=[],
                status=ContractStatus.FULFILLED,
                parent_contract_id=original_contract.id,
            )

        # Build new steps for unfulfilled criteria
        steps = self._decompose_for_criteria(unfulfilled, intent)

        contract = Contract(
            id=_generate_id("contract"),
            intent_summary=f"Remaining: {original_contract.intent_summary}",
            acceptance_criteria=unfulfilled,
            steps=steps,
            status=ContractStatus.DRAFT,
            parent_contract_id=original_contract.id,
        )

        # Link parent to child
        original_contract.child_contract_ids.append(contract.id)

        return contract

    def _generate_criteria(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate acceptance criteria from intent.

        When test_first is enabled, generates actual test code as
        the primary acceptance criterion.
        """
        criteria = []

        # 1. Generate test specification if test_first is enabled
        if self._test_first and self._test_generator is not None:
            self._notify("Generating test specification (test-first)...")
            try:
                test_spec = self._test_generator.generate(intent)
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.GENERATED_TEST_PASSES,
                        description=f"Generated test passes: {test_spec.test_function}",
                        target_file=test_spec.test_file,
                        test_spec=test_spec,
                    )
                )
                self._notify(f"Test spec created: {test_spec.test_function}")
                logger.info(
                    "Generated test specification: %s::%s",
                    test_spec.test_file,
                    test_spec.test_function,
                )
            except Exception as e:
                logger.error("Test generation failed: %s", e, exc_info=True)
                self._notify(f"Test generation skipped: {str(e)[:50]}")
                self._log("test_generation_failed",
                    f"Test-first generation failed, using standard criteria: {e}", {
                        "exception": str(e),
                        "exception_type": type(e).__name__,
                        "fallback": "standard_criteria",
                    }, level="WARN")

        # 2. Add other criteria using LLM or heuristics
        if self._llm is not None:
            self._notify("Using LLM to generate task-specific criteria...")
            criteria.extend(self._generate_criteria_with_llm(intent))
        else:
            self._notify("Generating criteria using heuristics...")
            criteria.extend(self._generate_criteria_heuristic(intent))

        return criteria

    def _generate_criteria_heuristic(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate meaningful criteria without LLM.

        Analyzes the intent to generate task-specific acceptance criteria
        rather than generic "code compiles" nonsense.
        """
        criteria = []
        prompt_lower = intent.prompt_intent.raw_prompt.lower()
        action = intent.prompt_intent.action_verb.lower()
        target = intent.prompt_intent.target.lower()

        # Detect project type from prompt keywords
        is_game = any(kw in prompt_lower for kw in [
            "game", "pygame", "arcade", "asteroids", "snake", "pong",
            "tetris", "breakout", "space invaders", "platformer"
        ])
        is_web = any(kw in prompt_lower for kw in [
            "flask", "django", "fastapi", "api", "endpoint", "web",
            "rest", "http", "server", "route"
        ])
        is_cli = any(kw in prompt_lower for kw in [
            "cli", "command line", "argparse", "click", "terminal"
        ])
        is_gui = any(kw in prompt_lower for kw in [
            "gui", "tkinter", "qt", "window", "ui", "interface"
        ])

        # Generate criteria based on detected project type
        if is_game:
            # Game-specific criteria - these are what actually matter
            criteria.extend([
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_EXISTS,
                    description="Main game file exists (main.py or game.py)",
                    target_file="main.py",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_CONTAINS,
                    description="Game loop implemented (pygame.display, while running)",
                    target_file="*.py",
                    pattern=r"pygame\.display|while.*running|game.*loop",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_CONTAINS,
                    description="Player/ship controls respond to keyboard input",
                    target_file="*.py",
                    pattern=r"pygame\.K_|KEYDOWN|key.*pressed|move|velocity",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.COMMAND_SUCCEEDS,
                    description="Game runs without crashing (syntax check)",
                    command="python -m py_compile main.py || python -m py_compile game.py",
                ),
            ])

            # Add asteroids-specific criteria
            if "asteroid" in prompt_lower:
                criteria.extend([
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.FILE_CONTAINS,
                        description="Asteroid class or spawning logic exists",
                        target_file="*.py",
                        pattern=r"class.*Asteroid|asteroid|spawn|enemy",
                    ),
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.FILE_CONTAINS,
                        description="Collision detection implemented",
                        target_file="*.py",
                        pattern=r"collide|collision|hit|intersect|rect",
                    ),
                ])

        elif is_web:
            criteria.extend([
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_EXISTS,
                    description="Main app file exists",
                    target_file="app.py",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_CONTAINS,
                    description="Route/endpoint defined",
                    target_file="*.py",
                    pattern=r"@app\.route|@router\.|def.*endpoint|FastAPI|Flask",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.COMMAND_SUCCEEDS,
                    description="App imports without errors",
                    command="python -c 'import app' || python -c 'import main'",
                ),
            ])

        elif is_cli:
            criteria.extend([
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_CONTAINS,
                    description="CLI argument parsing implemented",
                    target_file="*.py",
                    pattern=r"argparse|click|typer|sys\.argv",
                ),
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.COMMAND_SUCCEEDS,
                    description="CLI runs with --help",
                    command="python main.py --help",
                ),
            ])

        elif is_gui:
            criteria.extend([
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.FILE_CONTAINS,
                    description="GUI window/application created",
                    target_file="*.py",
                    pattern=r"Tk\(\)|QApplication|QMainWindow|tkinter|PyQt|PySide",
                ),
            ])

        else:
            # Generic but still meaningful criteria based on action/target
            if action in ("create", "add", "write", "implement", "make", "build"):
                if target in ("function", "method"):
                    criteria.append(
                        AcceptanceCriterion(
                            id=_generate_id("criterion"),
                            type=CriterionType.FUNCTION_EXISTS,
                            description=f"Function implemented and callable",
                            pattern=target,
                        )
                    )
                elif target in ("class",):
                    criteria.append(
                        AcceptanceCriterion(
                            id=_generate_id("criterion"),
                            type=CriterionType.CLASS_EXISTS,
                            description=f"Class implemented with required methods",
                            pattern=target,
                        )
                    )
                elif target in ("test",):
                    criteria.append(
                        AcceptanceCriterion(
                            id=_generate_id("criterion"),
                            type=CriterionType.TESTS_PASS,
                            description="Tests pass",
                            command="pytest",
                        )
                    )
                else:
                    # For unrecognized targets, at least require the file to exist
                    criteria.append(
                        AcceptanceCriterion(
                            id=_generate_id("criterion"),
                            type=CriterionType.FILE_EXISTS,
                            description=f"Implementation file created",
                            target_file="main.py",
                        )
                    )

        # Only add "code compiles" if we have no other criteria (last resort)
        if not criteria:
            criteria.append(
                AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=CriterionType.CODE_COMPILES,
                    description="Code compiles without errors",
                )
            )

        return criteria

    def _generate_criteria_with_llm(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate criteria using LLM."""
        system = """You define acceptance criteria for code changes.

Given an intent, output JSON with testable criteria:
{
    "criteria": [
        {
            "type": "file_exists|file_contains|tests_pass|function_exists|class_exists|layer_appropriate",
            "description": "Human-readable description",
            "target_file": "path/to/file.py",  // if applicable
            "pattern": "regex or name",  // if applicable
            "command": "test command",  // if applicable
            "layer_constraint": {  // REQUIRED for layer_appropriate type
                "logic_type": "business_logic|routing|parsing|etc",
                "appropriate_layers": ["agent", "service"],  // where it SHOULD go
                "inappropriate_layers": ["rpc", "storage"],  // where it should NOT go
                "reason": "Why this placement matters"
            }
        }
    ]
}

LAYER TYPES:
- rpc: Request parsing, routing, response formatting. NOT business logic.
- agent: Decision making, orchestration, state management.
- executor: Running plans, low-level execution.
- storage: Data persistence. NOT business logic.
- service: Business logic, domain operations.

Make criteria:
- Specific and testable
- Minimal but complete
- Focused on the actual change
- RESPECT any PROJECT DECISIONS listed (these are non-negotiable)
- Include layer_appropriate criterion when adding business logic to ensure correct placement"""

        # Build project decisions section if available
        decisions_section = ""
        if self._project_memory is not None:
            try:
                memory_context = self._project_memory.get_relevant_context(
                    repo_path=str(self.sandbox.repo_path),
                    prompt=intent.goal,
                    file_paths=intent.codebase_intent.related_files or None,
                )
                if memory_context.relevant_decisions:
                    decisions = "\n".join(
                        f"- {d.decision}" for d in memory_context.relevant_decisions
                    )
                    decisions_section = f"""
PROJECT DECISIONS (must respect):
{decisions}
"""
            except Exception as e:
                logger.warning("Failed to retrieve project decisions: %s", e, exc_info=True)
                self._log("project_decisions_retrieval_failed",
                    f"Could not load project decisions for criteria generation: {e}", {
                        "exception": str(e),
                    }, level="WARN")

        # Build layer responsibilities section
        layer_section = ""
        if intent.codebase_intent.layer_responsibilities:
            layer_lines = []
            for lr in intent.codebase_intent.layer_responsibilities[:5]:
                layer_lines.append(f"- {lr.file_path} ({lr.layer_name})")
                if lr.not_responsible_for:
                    layer_lines.append(f"  NOT: {', '.join(lr.not_responsible_for[:2])}")
            if layer_lines:
                layer_section = f"""
LAYER RESPONSIBILITIES:
{chr(10).join(layer_lines)}
"""

        context = f"""
GOAL: {intent.goal}
WHAT: {intent.what}
ACTION: {intent.prompt_intent.action_verb}
TARGET: {intent.prompt_intent.target}
LANGUAGE: {intent.codebase_intent.language}
RELATED FILES: {', '.join(intent.codebase_intent.related_files[:5])}
{decisions_section}{layer_section}"""

        # Log LLM call
        self._log("llm_call_start", "Starting criteria generation LLM call", {
            "purpose": "generate_criteria",
            "goal": intent.goal[:100],
            "context_length": len(context),
            "system_prompt_length": len(system),
        })

        try:
            self._notify("  Sending to LLM (criteria generation)...")
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            self._notify(f"  LLM response: {len(response)} chars")

            # Log raw response
            self._log("llm_response", "Received criteria generation response", {
                "response_length": len(response),
                "response": response,
            })

            data = json.loads(response)
            self._notify(f"  Parsed {len(data.get('criteria', []))} criteria from LLM")

            criteria = []
            for c in data.get("criteria", []):
                try:
                    ctype = CriterionType(c.get("type", "custom"))
                except ValueError:
                    ctype = CriterionType.CUSTOM

                # Parse layer constraint if present
                layer_constraint = None
                if c.get("layer_constraint"):
                    lc = c["layer_constraint"]
                    layer_constraint = LayerConstraint(
                        logic_type=lc.get("logic_type", "unknown"),
                        appropriate_layers=lc.get("appropriate_layers", []),
                        inappropriate_layers=lc.get("inappropriate_layers", []),
                        reason=lc.get("reason", ""),
                    )

                criterion = AcceptanceCriterion(
                    id=_generate_id("criterion"),
                    type=ctype,
                    description=c.get("description", ""),
                    target_file=c.get("target_file"),
                    pattern=c.get("pattern"),
                    command=c.get("command"),
                    layer_constraint=layer_constraint,
                )
                criteria.append(criterion)
                self._notify(f"    → {ctype.value}: {c.get('description', '')[:40]}...")

            # Always add code compiles if not present
            if not any(c.type == CriterionType.CODE_COMPILES for c in criteria):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.CODE_COMPILES,
                        description="Code compiles without errors",
                    )
                )

            # Log parsed criteria
            self._log("criteria_parsed", f"Parsed {len(criteria)} criteria from LLM", {
                "num_criteria": len(criteria),
                "criteria_types": [c.type.value for c in criteria],
                "criteria": [
                    {"type": c.type.value, "desc": c.description[:50], "file": c.target_file}
                    for c in criteria
                ],
            })

            return criteria

        except Exception as e:
            self._notify(f"LLM criteria failed: {str(e)[:50]}... using heuristics")
            self._log("llm_error", f"Criteria generation failed: {e}", {
                "error": str(e),
                "fallback": "heuristic",
            }, level="WARN")
            logger.warning("LLM criteria generation failed: %s", e)
            return self._generate_criteria_heuristic(intent)

    def _decompose_into_steps(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose the contract into discrete steps.

        When test_first is enabled, the first step creates the test file
        (red state), followed by implementation steps.
        """
        steps = []

        # 1. FIRST: Create test file for GENERATED_TEST_PASSES criteria
        for criterion in criteria:
            if (
                criterion.type == CriterionType.GENERATED_TEST_PASSES
                and criterion.test_spec is not None
            ):
                steps.append(
                    ContractStep(
                        id=_generate_id("step"),
                        description=f"Write test: {criterion.test_spec.test_function}",
                        target_criteria=[criterion.id],
                        action="create_file",
                        target_file=criterion.test_spec.test_file,
                        content=criterion.test_spec.test_code,
                    )
                )

        # 2. THEN: Implementation steps (from LLM or heuristics)
        if self._llm is not None:
            steps.extend(self._decompose_with_llm(intent, criteria))
        else:
            steps.extend(self._decompose_heuristic(intent, criteria))

        return steps

    def _decompose_heuristic(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose without LLM."""
        steps = []
        action = intent.prompt_intent.action_verb.lower()

        if action in ("create", "add", "write"):
            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Create {intent.prompt_intent.target}",
                    target_criteria=[c.id for c in criteria],
                    action="create_file",
                )
            )
        elif action in ("edit", "modify", "update", "fix"):
            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Modify {intent.prompt_intent.target}",
                    target_criteria=[c.id for c in criteria],
                    action="edit_file",
                )
            )

        # Add verification step
        steps.append(
            ContractStep(
                id=_generate_id("step"),
                description="Verify changes",
                target_criteria=[c.id for c in criteria],
                action="run_command",
                command="pytest" if intent.codebase_intent.test_patterns else "echo 'No tests'",
            )
        )

        return steps

    def _decompose_with_llm(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose using LLM."""
        self._notify("Using LLM to decompose task into steps...")
        system = """You decompose code tasks into discrete, atomic steps.

Each step should be the smallest complete unit of work.

Output JSON:
{
    "steps": [
        {
            "description": "What this step does",
            "action": "create_file|edit_file|run_command",
            "target_file": "path/to/file.py",  // if applicable
            "command": "command to run"  // if run_command
        }
    ]
}

Make steps:
- Atomic (one thing at a time)
- Ordered (dependencies first)
- Concrete (no ambiguity)"""

        criteria_desc = "\n".join(f"- {c.description}" for c in criteria)
        context = f"""
GOAL: {intent.goal}
WHAT: {intent.what}
LANGUAGE: {intent.codebase_intent.language}

MUST SATISFY:
{criteria_desc}
"""

        # Log LLM call
        self._log("llm_call_start", "Starting decomposition LLM call", {
            "purpose": "decompose_steps",
            "goal": intent.goal[:100],
            "num_criteria": len(criteria),
            "context_length": len(context),
        })

        try:
            self._notify("  Sending to LLM (decomposition)...")
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            self._notify(f"  LLM response: {len(response)} chars")

            # Log raw response
            self._log("llm_response", "Received decomposition response", {
                "response_length": len(response),
                "response": response,
            })

            data = json.loads(response)
            self._notify(f"  Parsed {len(data.get('steps', []))} steps from LLM")

            steps = []
            for s in data.get("steps", []):
                # Determine action - use LLM's choice or infer from file existence
                action = s.get("action")
                target_file = s.get("target_file")

                if not action:
                    # LLM didn't specify action - infer from file existence
                    if target_file:
                        full_path = self.sandbox.repo_path / target_file
                        action = "edit_file" if full_path.exists() else "create_file"
                    else:
                        action = "create_file"  # No target = likely new file

                step = ContractStep(
                    id=_generate_id("step"),
                    description=s.get("description", ""),
                    target_criteria=[c.id for c in criteria],
                    action=action,
                    target_file=target_file,
                    command=s.get("command"),
                )
                steps.append(step)
                self._notify(f"    → [{action}] {s.get('description', '')[:35]}...")
                if target_file:
                    self._notify(f"      file: {target_file}")

            # Log parsed steps
            self._log("steps_parsed", f"Parsed {len(steps)} steps from LLM", {
                "num_steps": len(steps),
                "steps": [
                    {"action": s.action, "desc": s.description[:50], "file": s.target_file}
                    for s in steps
                ],
            })

            return steps

        except Exception as e:
            self._notify(f"LLM decomposition failed: {str(e)[:50]}... using heuristics")
            self._log("llm_error", f"Decomposition failed: {e}", {
                "error": str(e),
                "fallback": "heuristic",
            }, level="WARN")
            logger.warning("LLM decomposition failed: %s", e)
            return self._decompose_heuristic(intent, criteria)

    def _decompose_for_criteria(
        self,
        criteria: list[AcceptanceCriterion],
        intent: DiscoveredIntent,
    ) -> list[ContractStep]:
        """Create steps specifically for unfulfilled criteria.

        Intelligently chooses create_file vs edit_file based on whether
        the target file already exists in the repository.
        """
        steps = []
        for criterion in criteria:
            # Determine action based on file existence
            action = "edit_file"  # Default
            target_file = criterion.target_file

            if target_file:
                # Check if file exists in repo
                full_path = self.sandbox.repo_path / target_file
                if not full_path.exists():
                    action = "create_file"
            else:
                # No target file specified - likely needs new file
                # Use create_file as safer default for new functionality
                action = "create_file"

            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Fulfill: {criterion.description}",
                    target_criteria=[criterion.id],
                    action=action,
                    target_file=target_file,
                )
            )
        return steps
