"""Extended Reasoning and Planning System for ReOS.

This module provides intelligent planning for complex Linux operations while
keeping simple requests fast and natural.

Components:
    - ComplexityAssessor: Determines if a request needs planning
    - TaskPlanner: Breaks complex requests into verifiable steps
    - ExecutionEngine: Runs steps with monitoring and rollback
    - ConversationManager: Natural language interface
    - SafetyManager: Risk analysis and rollback capability

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
    # Conversation
    "ConversationManager",
    # Safety
    "SafetyManager",
    "RiskLevel",
    "RollbackAction",
]
