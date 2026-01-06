"""Code Mode - Agentic coding capabilities for ReOS.

When an Act has a repository assigned, ReOS enters "Code Mode" providing
Claude Code-like capabilities: read, write, edit files, run tests, and
iterate on errors - all sandboxed to the assigned repository.

The execution loop follows a principled cycle:
1. INTENT - Discover what the user truly wants from multiple sources
2. CONTRACT - Define explicit, testable success criteria
3. DECOMPOSE - Break into atomic steps
4. BUILD - Execute the most concrete step
5. VERIFY - Test that step fulfills its part
6. INTEGRATE - Merge verified code
7. GAP - Check what remains, loop until complete
"""

from __future__ import annotations

# Sandbox
from reos.code_mode.sandbox import CodeSandbox, CodeSandboxError

# Router
from reos.code_mode.router import CodeModeRouter, RoutingDecision, RequestType

# Planner (Sprint 2)
from reos.code_mode.planner import (
    CodePlanner,
    CodeTaskPlan,
    CodeStep,
    CodeStepType,
    ImpactLevel,
)

# Intent Discovery (Sprint 3)
from reos.code_mode.intent import (
    IntentDiscoverer,
    DiscoveredIntent,
    PromptIntent,
    PlayIntent,
    CodebaseIntent,
)

# Contract (Sprint 3)
from reos.code_mode.contract import (
    Contract,
    ContractBuilder,
    ContractStatus,
    ContractStep,
    AcceptanceCriterion,
    CriterionType,
)

# Perspectives (Sprint 3)
from reos.code_mode.perspectives import (
    PerspectiveManager,
    Perspective,
    Phase,
    ANALYST,
    ARCHITECT,
    ENGINEER,
    CRITIC,
    DEBUGGER,
    INTEGRATOR,
    GAP_ANALYZER,
)

# Executor (Sprint 3)
from reos.code_mode.executor import (
    CodeExecutor,
    ExecutionState,
    ExecutionResult,
    LoopStatus,
    LoopIteration,
    StepResult,
    DebugDiagnosis,
)

# Diff Preview
from reos.code_mode.diff_utils import (
    DiffPreviewManager,
    DiffPreview,
    FileChange,
    ChangeType,
    Hunk,
    generate_diff,
    generate_edit_diff,
)

__all__ = [
    # Sandbox
    "CodeSandbox",
    "CodeSandboxError",
    # Router
    "CodeModeRouter",
    "RoutingDecision",
    "RequestType",
    # Planner
    "CodePlanner",
    "CodeTaskPlan",
    "CodeStep",
    "CodeStepType",
    "ImpactLevel",
    # Intent
    "IntentDiscoverer",
    "DiscoveredIntent",
    "PromptIntent",
    "PlayIntent",
    "CodebaseIntent",
    # Contract
    "Contract",
    "ContractBuilder",
    "ContractStatus",
    "ContractStep",
    "AcceptanceCriterion",
    "CriterionType",
    # Perspectives
    "PerspectiveManager",
    "Perspective",
    "Phase",
    "ANALYST",
    "ARCHITECT",
    "ENGINEER",
    "CRITIC",
    "DEBUGGER",
    "INTEGRATOR",
    "GAP_ANALYZER",
    # Executor
    "CodeExecutor",
    "ExecutionState",
    "ExecutionResult",
    "LoopStatus",
    "LoopIteration",
    "StepResult",
    "DebugDiagnosis",
    # Diff Preview
    "DiffPreviewManager",
    "DiffPreview",
    "FileChange",
    "ChangeType",
    "Hunk",
    "generate_diff",
    "generate_edit_diff",
]
