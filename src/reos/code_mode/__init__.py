"""Code Mode - Agentic coding capabilities for ReOS.

Simplified execution loop:
1. INTENT - Understand what the user wants
2. CONTRACT - Define testable success criteria
3. PLAN - Break into steps
4. BUILD - Execute steps
5. VERIFY - Check results
6. Loop until complete or max iterations
"""

from __future__ import annotations

# Core - Sandbox for file operations
from reos.code_mode.sandbox import CodeSandbox, CodeSandboxError

# Core - Router for request classification
from reos.code_mode.router import CodeModeRouter, RoutingDecision, RequestType

# Core - Planning
from reos.code_mode.planner import (
    CodePlanner,
    CodeTaskPlan,
    CodeStep,
    CodeStepType,
    ImpactLevel,
)

# Core - Intent Discovery
from reos.code_mode.intent import (
    IntentDiscoverer,
    DiscoveredIntent,
    PromptIntent,
    PlayIntent,
    CodebaseIntent,
    LayerResponsibility,
)

# Core - Contract (acceptance criteria)
from reos.code_mode.contract import (
    Contract,
    ContractBuilder,
    ContractStatus,
    ContractStep,
    AcceptanceCriterion,
    CriterionType,
    TestSpecification,
    LayerConstraint,
)

# Core - Executor (main loop)
from reos.code_mode.executor import (
    CodeExecutor,
    ExecutionState,
    ExecutionResult,
    LoopStatus,
    LoopIteration,
    StepResult,
    DebugDiagnosis,
)

# Core - Streaming (UI state updates)
from reos.code_mode.streaming import (
    ExecutionStateSnapshot,
    CodeExecutionContext,
    ExecutionObserver,
    ExecutionCancelledError,
    create_execution_context,
    PHASE_INFO,
)

# Supporting - Diff Preview
from reos.code_mode.diff_utils import (
    DiffPreviewManager,
    DiffPreview,
    FileChange,
    ChangeType,
    Hunk,
    generate_diff,
    generate_edit_diff,
)

# Supporting - Perspectives (may be removed)
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

# Supporting - Test Generator
from reos.code_mode.test_generator import TestGenerator

# Supporting - Session Logger (verbose debugging)
from reos.code_mode.session_logger import SessionLogger, list_sessions, get_session_log

# Core - Recursive Intention-Verification Architecture (RIVA)
from reos.code_mode.intention import (
    Intention,
    IntentionStatus,
    Cycle,
    Action,
    ActionType,
    Judgment,
    WorkContext,
    AutoCheckpoint,
    UICheckpoint,
    Session as RIVASession,
    work as riva_work,
    can_verify_directly,
    should_decompose,
    decompose,
    gather_context,
)

# Supporting - Multi-path Exploration
from reos.code_mode.explorer import (
    StepExplorer,
    StepAlternative,
    ExplorationState,
)

# Quality Tier Tracking - Transparency over hidden failures
from reos.code_mode.quality import (
    QualityTier,
    QualityTracker,
    QualityEvent,
    OperationTracker,
    track_quality,
    quality_context,
    get_current_tracker,
    set_current_tracker,
    format_quality_for_log,
    TIER_DISPLAY,
)

# Repository Map - REMOVED for simplification
# To re-enable, restore repo_map.py, symbol_extractor.py, dependency_graph.py

# Optional - Project Memory (can be disabled)
from reos.code_mode.project_memory import (
    ProjectMemoryStore,
    ProjectDecision,
    ProjectPattern,
    UserCorrection,
    CodingSession,
    CodeChange,
    ProjectMemoryContext,
)

# Tool Providers - Unified tool interface for RIVA
from reos.code_mode.tools import (
    ToolProvider,
    ToolInfo,
    ToolResult,
    ToolCategory,
    SandboxToolProvider,
    CompositeToolProvider,
    NullToolProvider,
    create_tool_provider,
)

# Web Tools - Search, fetch, documentation
from reos.code_mode.web_tools import (
    WebToolProvider,
    SearchResult,
    FetchedContent,
    KNOWN_DOCS,
)

__all__ = [
    # Core
    "CodeSandbox",
    "CodeSandboxError",
    "CodeModeRouter",
    "RoutingDecision",
    "RequestType",
    "CodePlanner",
    "CodeTaskPlan",
    "CodeStep",
    "CodeStepType",
    "ImpactLevel",
    "IntentDiscoverer",
    "DiscoveredIntent",
    "PromptIntent",
    "PlayIntent",
    "CodebaseIntent",
    "LayerResponsibility",
    "Contract",
    "ContractBuilder",
    "ContractStatus",
    "ContractStep",
    "AcceptanceCriterion",
    "CriterionType",
    "TestSpecification",
    "LayerConstraint",
    "CodeExecutor",
    "ExecutionState",
    "ExecutionResult",
    "LoopStatus",
    "LoopIteration",
    "StepResult",
    "DebugDiagnosis",
    "ExecutionStateSnapshot",
    "CodeExecutionContext",
    "ExecutionObserver",
    "ExecutionCancelledError",
    "create_execution_context",
    "PHASE_INFO",
    # Supporting
    "DiffPreviewManager",
    "DiffPreview",
    "FileChange",
    "ChangeType",
    "Hunk",
    "generate_diff",
    "generate_edit_diff",
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
    "TestGenerator",
    "SessionLogger",
    "list_sessions",
    "get_session_log",
    # RIVA
    "Intention",
    "IntentionStatus",
    "Cycle",
    "Action",
    "ActionType",
    "Judgment",
    "WorkContext",
    "AutoCheckpoint",
    "UICheckpoint",
    "RIVASession",
    "riva_work",
    "can_verify_directly",
    "should_decompose",
    "decompose",
    "gather_context",
    "StepExplorer",
    "StepAlternative",
    "ExplorationState",
    # Quality Tracking
    "QualityTier",
    "QualityTracker",
    "QualityEvent",
    "OperationTracker",
    "track_quality",
    "quality_context",
    "get_current_tracker",
    "set_current_tracker",
    "format_quality_for_log",
    "TIER_DISPLAY",
    # Optional
    "ProjectMemoryStore",
    "ProjectDecision",
    "ProjectPattern",
    "UserCorrection",
    "CodingSession",
    "CodeChange",
    "ProjectMemoryContext",
    # Tool Providers
    "ToolProvider",
    "ToolInfo",
    "ToolResult",
    "ToolCategory",
    "SandboxToolProvider",
    "CompositeToolProvider",
    "NullToolProvider",
    "create_tool_provider",
    # Web Tools
    "WebToolProvider",
    "SearchResult",
    "FetchedContent",
    "KNOWN_DOCS",
]
