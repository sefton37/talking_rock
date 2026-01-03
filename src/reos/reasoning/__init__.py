"""Extended Reasoning and Planning System for ReOS.

This module provides intelligent planning for complex Linux operations while
keeping simple requests fast and natural.

Components:
    - ComplexityAssessor: Determines if a request needs planning
    - TaskPlanner: Breaks complex requests into verifiable steps
    - ExecutionEngine: Runs steps with monitoring and rollback
    - AdaptiveExecutor: Enhanced executor with automatic error recovery
    - ConversationManager: Natural language interface
    - SafetyManager: Risk analysis and rollback capability

Adaptive Features:
    - ErrorClassifier: Diagnoses failures (missing deps, permissions, etc.)
    - AdaptiveReplanner: Dynamically revises plans on failure
    - ExecutionLearner: Learns what works on this specific system

Circuit Breakers (prevent runaway AI):
    - SafetyLimits: Hard limits on automated execution
    - ExecutionBudget: Runtime tracker for limits
    - check_scope_drift: Prevents actions outside original request

Example:
    from reos.reasoning import ReasoningEngine

    engine = ReasoningEngine(db)
    response = await engine.process("speed up my boot time")
"""

from .complexity import ComplexityAssessor, ComplexityLevel
from .planner import TaskPlanner, TaskPlan, TaskStep
from .executor import ExecutionEngine, StepResult, ExecutionState
from .conversation import ConversationManager
from .safety import SafetyManager, RiskLevel, RollbackAction
from .engine import ReasoningEngine
from .adaptive import (
    ErrorClassifier,
    ErrorCategory,
    ErrorDiagnosis,
    AdaptiveReplanner,
    AdaptiveExecutor,
    ExecutionLearner,
    ExecutionMemory,
    # Circuit breakers for safety
    SafetyLimits,
    ExecutionBudget,
    check_scope_drift,
)

__all__ = [
    # Main entry point
    "ReasoningEngine",
    # Complexity assessment
    "ComplexityAssessor",
    "ComplexityLevel",
    # Planning
    "TaskPlanner",
    "TaskPlan",
    "TaskStep",
    # Execution
    "ExecutionEngine",
    "StepResult",
    "ExecutionState",
    # Adaptive execution
    "ErrorClassifier",
    "ErrorCategory",
    "ErrorDiagnosis",
    "AdaptiveReplanner",
    "AdaptiveExecutor",
    "ExecutionLearner",
    "ExecutionMemory",
    # Circuit breakers
    "SafetyLimits",
    "ExecutionBudget",
    "check_scope_drift",
    # Conversation
    "ConversationManager",
    # Safety
    "SafetyManager",
    "RiskLevel",
    "RollbackAction",
]
