"""Recursive Intention-Verification Architecture (RIVA).

Core Principle: If you can't verify it, decompose it.

Levels (project, component, function, line) are not prescribed.
They emerge from recursive application of this single constraint.
The agent navigates by asking one question: Can I verify this intention right now?
If yes, act and verify. If no, decompose until you can.

This module implements:
- Intention: The atomic unit with what/acceptance/trace
- Cycle: A single attempt (thought → action → result → judgment)
- Action: Concrete action taken (command, edit, create, delete, query)
- work(): The recursive navigation algorithm
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, TypeVar

if TYPE_CHECKING:
    from reos.code_mode.sandbox import CodeSandbox
    from reos.code_mode.session_logger import SessionLogger
    from reos.code_mode.quality import QualityTracker
    from reos.code_mode.tools import ToolProvider
    from reos.providers import LLMProvider

logger = logging.getLogger(__name__)


class IntentionStatus(Enum):
    """Status of an intention in the tree."""
    PENDING = "pending"      # Not yet started
    ACTIVE = "active"        # Currently being worked on
    VERIFIED = "verified"    # Successfully completed
    FAILED = "failed"        # Could not be satisfied


class ActionType(Enum):
    """Type of action taken."""
    COMMAND = "command"      # Shell command
    EDIT = "edit"            # Edit existing file
    CREATE = "create"        # Create new file
    DELETE = "delete"        # Delete file
    QUERY = "query"          # Read/search/explore


class Judgment(Enum):
    """Human judgment on an action's outcome."""
    SUCCESS = "success"      # Action achieved what we wanted
    FAILURE = "failure"      # Action clearly failed
    PARTIAL = "partial"      # Partially worked, more needed
    UNCLEAR = "unclear"      # Can't tell if it worked


@dataclass
class Action:
    """A concrete action taken to satisfy an intention.

    Attributes:
        type: The type of action (command, edit, create, delete, query)
        content: The actual command/code/query
        target: File path or system target if applicable
    """
    type: ActionType
    content: str
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "content": self.content,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        return cls(
            type=ActionType(data["type"]),
            content=data["content"],
            target=data.get("target"),
        )


@dataclass
class Cycle:
    """A single attempt to satisfy an intention.

    Each cycle represents: thought → action → result → judgment → reflection

    Attributes:
        thought: What I'm about to try and why
        action: The concrete action taken
        result: What happened (output, error, etc.)
        judgment: Human/auto judgment on outcome
        reflection: If not success, why and what changes
    """
    thought: str
    action: Action
    result: str
    judgment: Judgment
    reflection: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought": self.thought,
            "action": self.action.to_dict(),
            "result": self.result,
            "judgment": self.judgment.value,
            "reflection": self.reflection,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cycle:
        return cls(
            thought=data["thought"],
            action=Action.from_dict(data["action"]),
            result=data["result"],
            judgment=Judgment(data["judgment"]),
            reflection=data.get("reflection"),
        )


@dataclass
class Intention:
    """The atomic unit of the recursive architecture.

    Every node in the system is an Intention with:
    - what: natural language description of the goal
    - acceptance: how we know it's done (verifiable criteria)
    - trace: all action cycles attempted at THIS level
    - children: sub-intentions if decomposed

    Attributes:
        id: Unique identifier
        what: What are we trying to do (natural language)
        acceptance: How do we know it's done (verifiable)
        parent_id: Parent intention ID (None for root)
        children: List of child intention IDs (empty until decomposed)
        status: Current status (pending, active, verified, failed)
        trace: All cycles attempted at this level
        created_at: When this intention was created
        verified_at: When this intention was verified (if applicable)
    """
    id: str
    what: str
    acceptance: str
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    status: IntentionStatus = IntentionStatus.PENDING
    trace: list[Cycle] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: datetime | None = None

    # Runtime fields (not serialized)
    _child_intentions: list["Intention"] = field(default_factory=list, repr=False)

    @staticmethod
    def create(what: str, acceptance: str, parent_id: str | None = None) -> Intention:
        """Create a new intention with a unique ID."""
        return Intention(
            id=f"int-{uuid.uuid4().hex[:8]}",
            what=what,
            acceptance=acceptance,
            parent_id=parent_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (includes full tree via children)."""
        return {
            "id": self.id,
            "what": self.what,
            "acceptance": self.acceptance,
            "parent_id": self.parent_id,
            "children": self.children,
            "status": self.status.value,
            "trace": [c.to_dict() for c in self.trace],
            "created_at": self.created_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "_child_intentions": [c.to_dict() for c in self._child_intentions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Intention:
        """Deserialize from dictionary."""
        intention = cls(
            id=data["id"],
            what=data["what"],
            acceptance=data["acceptance"],
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            status=IntentionStatus(data.get("status", "pending")),
            trace=[Cycle.from_dict(c) for c in data.get("trace", [])],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            verified_at=datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else None,
        )
        # Recursively load children
        for child_data in data.get("_child_intentions", []):
            intention._child_intentions.append(cls.from_dict(child_data))
        return intention

    def add_cycle(self, cycle: Cycle) -> None:
        """Add a cycle to the trace."""
        self.trace.append(cycle)

    def add_child(self, child: "Intention") -> None:
        """Add a child intention."""
        self.children.append(child.id)
        self._child_intentions.append(child)
        child.parent_id = self.id

    def get_depth(self) -> int:
        """Get the depth of this intention in the tree."""
        if not self._child_intentions:
            return 0
        return 1 + max(c.get_depth() for c in self._child_intentions)

    def get_total_cycles(self) -> int:
        """Get total cycles in this intention and all descendants."""
        total = len(self.trace)
        for child in self._child_intentions:
            total += child.get_total_cycles()
        return total


class HumanCheckpoint(Protocol):
    """Protocol for human-in-the-loop checkpoints.

    The agent proposes, the human confirms. This is where alignment lives.
    """

    def judge_action(self, intention: Intention, cycle: Cycle) -> Judgment:
        """After each action: did it work?"""
        ...

    def approve_decomposition(self, intention: Intention, proposed_children: list[Intention]) -> bool:
        """Before splitting: are these the right sub-parts?"""
        ...

    def verify_integration(self, intention: Intention) -> bool:
        """After children complete: does the whole work?"""
        ...

    def review_reflection(self, intention: Intention, cycle: Cycle) -> bool:
        """On failure: does this analysis make sense?"""
        ...


class AutoCheckpoint:
    """Automatic checkpoint implementation for autonomous operation.

    Uses heuristics and test results instead of human input.
    Can be replaced with HumanCheckpoint for human-in-the-loop mode.
    """

    def __init__(self, sandbox: "CodeSandbox", llm: "LLMProvider | None" = None):
        self.sandbox = sandbox
        self.llm = llm

    def judge_action(self, intention: Intention, cycle: Cycle) -> Judgment:
        """Judge action based on result content."""
        result_lower = cycle.result.lower()

        # Check for clear failures
        if any(err in result_lower for err in ["error", "failed", "exception", "traceback"]):
            return Judgment.FAILURE

        # Check for clear success indicators
        if any(ok in result_lower for ok in ["success", "passed", "ok", "created", "completed"]):
            return Judgment.SUCCESS

        # Check exit codes for commands
        if cycle.action.type == ActionType.COMMAND:
            if "exit code: 0" in result_lower or "exit code 0" in result_lower:
                return Judgment.SUCCESS
            if "exit code:" in result_lower:
                return Judgment.FAILURE

        # Default to partial if we can't tell
        return Judgment.PARTIAL

    def approve_decomposition(self, intention: Intention, proposed_children: list[Intention]) -> bool:
        """Auto-approve decompositions that look reasonable."""
        # Approve if each child is more specific than parent
        if not proposed_children:
            return False

        # Basic heuristics
        parent_words = set(intention.what.lower().split())
        for child in proposed_children:
            child_words = set(child.what.lower().split())
            # Child should be related but more specific
            if not parent_words & child_words:
                logger.warning("Child '%s' seems unrelated to parent '%s'",
                             child.what[:30], intention.what[:30])

        return True

    def verify_integration(self, intention: Intention) -> bool:
        """Verify all children are complete."""
        if not intention._child_intentions:
            return True
        return all(c.status == IntentionStatus.VERIFIED for c in intention._child_intentions)

    def review_reflection(self, intention: Intention, cycle: Cycle) -> bool:
        """Auto-approve reflections."""
        return True


class UICheckpoint:
    """Human-in-the-loop checkpoint using UI callbacks.

    This checkpoint implementation surfaces decisions to the user through
    callback functions. Use this when you want explicit human approval
    for RIVA decisions.

    The callbacks follow a pattern:
    - They receive context about the decision
    - They return the human's decision (or a default if callback not provided)

    Example:
        def ask_judgment(intention, cycle, auto_judgment):
            # Show UI, get user input
            return user_selected_judgment or auto_judgment

        checkpoint = UICheckpoint(
            sandbox=sandbox,
            on_judge_action=ask_judgment,
        )
    """

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
        on_judge_action: "Callable[[Intention, Cycle, Judgment], Judgment] | None" = None,
        on_approve_decomposition: "Callable[[Intention, list[Intention]], bool] | None" = None,
        on_verify_integration: "Callable[[Intention], bool] | None" = None,
        on_review_reflection: "Callable[[Intention, Cycle], bool] | None" = None,
    ):
        """Initialize UICheckpoint.

        Args:
            sandbox: Code sandbox for file operations
            llm: Optional LLM provider for generating suggestions
            on_judge_action: Callback for action judgment.
                            Receives (intention, cycle, auto_judgment) and returns final Judgment.
            on_approve_decomposition: Callback for decomposition approval.
                            Receives (intention, proposed_children) and returns bool.
            on_verify_integration: Callback for integration verification.
                            Receives (intention) and returns bool.
            on_review_reflection: Callback for reflection review.
                            Receives (intention, cycle) and returns bool.
        """
        self._auto = AutoCheckpoint(sandbox, llm)
        self._on_judge_action = on_judge_action
        self._on_approve_decomposition = on_approve_decomposition
        self._on_verify_integration = on_verify_integration
        self._on_review_reflection = on_review_reflection

    def judge_action(self, intention: Intention, cycle: Cycle) -> Judgment:
        """Judge action with human input.

        First computes auto judgment, then optionally asks human for override.
        """
        auto_judgment = self._auto.judge_action(intention, cycle)

        if self._on_judge_action:
            return self._on_judge_action(intention, cycle, auto_judgment)
        return auto_judgment

    def approve_decomposition(self, intention: Intention, proposed_children: list[Intention]) -> bool:
        """Approve decomposition with human input."""
        if self._on_approve_decomposition:
            return self._on_approve_decomposition(intention, proposed_children)
        return self._auto.approve_decomposition(intention, proposed_children)

    def verify_integration(self, intention: Intention) -> bool:
        """Verify integration with human input."""
        if self._on_verify_integration:
            return self._on_verify_integration(intention)
        return self._auto.verify_integration(intention)

    def review_reflection(self, intention: Intention, cycle: Cycle) -> bool:
        """Review reflection with human input."""
        if self._on_review_reflection:
            return self._on_review_reflection(intention, cycle)
        return self._auto.review_reflection(intention, cycle)


@dataclass
class WorkContext:
    """Context for the recursive work algorithm.

    Carries dependencies through the recursion without global state.
    """
    sandbox: "CodeSandbox"
    llm: "LLMProvider | None"
    checkpoint: HumanCheckpoint | AutoCheckpoint
    session_logger: "SessionLogger | None" = None
    quality_tracker: "QualityTracker | None" = None  # Track quality tiers
    tool_provider: "ToolProvider | None" = None  # Tools for gathering context
    max_cycles_per_intention: int = 5
    max_depth: int = 10

    # Callbacks for UI integration
    on_intention_start: Callable[[Intention], None] | None = None
    on_intention_complete: Callable[[Intention], None] | None = None
    on_cycle_complete: Callable[[Intention, Cycle], None] | None = None
    on_decomposition: Callable[[Intention, list[Intention]], None] | None = None


def can_verify_directly(intention: Intention, ctx: WorkContext) -> bool:
    """Can we verify this intention directly without decomposition?

    Ask: "Can I write a test, run a command, or observe an outcome
    that tells me this intention is satisfied?"

    Heuristics:
    - Single observable behavior mentioned
    - "Done" can be described in one sentence
    - There's a command that would prove it works
    - No compound actions (and, then, also)
    """
    what_lower = intention.what.lower()
    acceptance_lower = intention.acceptance.lower()

    # Compound indicators suggest need for decomposition
    compound_words = ["and", "then", "also", "additionally", "plus", "as well as"]
    compound_count = sum(1 for w in compound_words if f" {w} " in what_lower)
    if compound_count >= 2:
        logger.debug("Intention has compound structure, needs decomposition")
        return False

    # Very long descriptions usually need decomposition
    if len(intention.what) > 200:
        logger.debug("Intention description too long, needs decomposition")
        return False

    # Check if acceptance criteria is testable
    testable_indicators = [
        "file exists", "returns", "outputs", "displays", "shows",
        "test passes", "compiles", "runs", "works", "responds",
        "contains", "matches", "equals", "creates", "produces"
    ]
    has_testable = any(ind in acceptance_lower for ind in testable_indicators)

    # Check for vague acceptance criteria
    vague_indicators = [
        "feels good", "looks nice", "works well", "is complete",
        "everything", "all features", "fully functional"
    ]
    is_vague = any(ind in acceptance_lower for ind in vague_indicators)

    if is_vague and not has_testable:
        logger.debug("Acceptance criteria too vague, needs decomposition")
        return False

    # If we have clear, testable criteria, we can verify directly
    return has_testable or len(intention.what.split()) < 15


def should_decompose(intention: Intention, cycle: Cycle | None, ctx: WorkContext) -> bool:
    """Should we decompose this intention instead of retrying?

    Decompose when:
    - Action attempted but outcome unclear
    - Multiple distinct sub-tasks detected in reflection
    - Repeated failures suggest missing foundations
    - Max cycles reached without success
    """
    # Already at max cycles
    if len(intention.trace) >= ctx.max_cycles_per_intention:
        logger.info("Max cycles reached, decomposing")
        return True

    # No cycle means initial check found it unverifiable
    if cycle is None:
        return True

    # Repeated failures
    failure_count = sum(1 for c in intention.trace if c.judgment == Judgment.FAILURE)
    if failure_count >= 2:
        logger.info("Repeated failures, decomposing")
        return True

    # Unclear outcomes suggest scope is wrong
    unclear_count = sum(1 for c in intention.trace if c.judgment == Judgment.UNCLEAR)
    if unclear_count >= 2:
        logger.info("Unclear outcomes, decomposing")
        return True

    # Reflection suggests decomposition
    if cycle.reflection:
        decompose_hints = ["need to first", "requires", "depends on", "multiple steps", "break down"]
        if any(hint in cycle.reflection.lower() for hint in decompose_hints):
            logger.info("Reflection suggests decomposition")
            return True

    return False


def gather_context(intention: Intention, ctx: WorkContext) -> str:
    """Gather relevant context using tools before taking action.

    When RIVA is uncertain or needs more information, this function uses
    the tool provider to search the codebase and web for relevant context.

    Returns a context string to include in LLM prompts.
    """
    if ctx.tool_provider is None:
        return ""

    if ctx.session_logger:
        ctx.session_logger.log_info("riva", "gather_context",
            f"Gathering context for: {intention.what[:50]}...")

    context_parts = []
    what_lower = intention.what.lower()

    # Extract potential keywords from intention
    keywords = _extract_keywords(intention.what)

    # 1. Search codebase for relevant patterns
    if ctx.tool_provider.has_tool("grep"):
        for keyword in keywords[:3]:  # Limit to top 3 keywords
            try:
                result = ctx.tool_provider.call_tool("grep", {
                    "pattern": keyword,
                    "max_results": 5,
                })
                if result.success and result.output and "No matches" not in result.output:
                    context_parts.append(f"[Codebase search for '{keyword}']\n{result.output[:500]}")
            except Exception as e:
                logger.debug("Grep search failed for '%s': %s", keyword, e)

    # 2. Look at file structure if we need to understand project layout
    if any(w in what_lower for w in ["create", "add", "implement", "structure"]):
        if ctx.tool_provider.has_tool("get_structure"):
            try:
                result = ctx.tool_provider.call_tool("get_structure", {"max_depth": 2})
                if result.success:
                    context_parts.append(f"[Project structure]\n{result.output[:800]}")
            except Exception as e:
                logger.debug("Get structure failed: %s", e)

    # 3. Web search for documentation if working with external libraries
    library_hints = _detect_library_hints(intention.what)
    if library_hints and ctx.tool_provider.has_tool("fetch_docs"):
        for lib in library_hints[:2]:  # Limit to 2 libraries
            try:
                result = ctx.tool_provider.call_tool("fetch_docs", {"library": lib})
                if result.success:
                    context_parts.append(f"[Documentation for '{lib}']\n{result.output[:600]}")
            except Exception as e:
                logger.debug("Fetch docs failed for '%s': %s", lib, e)

    # 4. If there are errors mentioned, search for solutions
    if any(w in what_lower for w in ["error", "fix", "debug", "exception", "failed"]):
        if ctx.tool_provider.has_tool("web_search"):
            # Extract error patterns from intention
            error_context = intention.what
            if intention.trace:
                last_result = intention.trace[-1].result
                if "error" in last_result.lower() or "exception" in last_result.lower():
                    error_context = last_result[:200]

            try:
                result = ctx.tool_provider.call_tool("web_search", {
                    "query": f"python {error_context[:100]} solution",
                    "num_results": 2,
                })
                if result.success:
                    context_parts.append(f"[Web search for solution]\n{result.output[:500]}")
            except Exception as e:
                logger.debug("Web search failed: %s", e)

    context = "\n\n".join(context_parts)

    if ctx.session_logger and context:
        ctx.session_logger.log_debug("riva", "context_gathered",
            f"Gathered {len(context_parts)} context sections ({len(context)} chars)")

    return context


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from intention text."""
    import re

    # Remove common words
    stopwords = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "can", "this", "that",
        "these", "those", "it", "its", "i", "we", "you", "they", "he", "she",
        "create", "add", "implement", "make", "build", "write", "function",
        "file", "code", "new", "using", "use", "need", "want", "please",
    }

    # Extract words
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text.lower())

    # Filter and dedupe
    keywords = []
    seen = set()
    for word in words:
        if word not in stopwords and word not in seen and len(word) > 2:
            keywords.append(word)
            seen.add(word)

    return keywords[:10]  # Limit to 10 keywords


def _detect_library_hints(text: str) -> list[str]:
    """Detect mentions of known libraries in text."""
    text_lower = text.lower()

    # Common libraries we might want docs for
    known_libs = [
        "python", "requests", "flask", "django", "fastapi", "pytest",
        "numpy", "pandas", "pygame", "sqlalchemy", "pydantic",
        "react", "nextjs", "typescript", "node",
        "rust", "tokio", "serde",
    ]

    detected = []
    for lib in known_libs:
        if lib in text_lower:
            detected.append(lib)

    return detected


def decompose(intention: Intention, ctx: WorkContext) -> list[Intention]:
    """Break intention into sub-intentions.

    Each child should be:
    - Closer to verifiable than the parent
    - As independent as possible
    - Together sufficient to satisfy parent

    Uses LLM to generate decomposition, then human confirms.
    """
    if ctx.session_logger:
        ctx.session_logger.log_info("riva", "decompose_start",
            f"Decomposing: {intention.what[:50]}...")

    if ctx.llm is None:
        # Fallback: simple heuristic decomposition
        return _heuristic_decompose(intention, ctx)

    # Gather context to help with decomposition
    tool_context = gather_context(intention, ctx)
    context_section = ""
    if tool_context:
        context_section = f"\n\n[Codebase Context]\n{tool_context[:1500]}"

    # Use LLM to decompose
    system_prompt = """You are decomposing a software task into smaller, verifiable sub-tasks.

Rules:
1. Each sub-task must be independently verifiable
2. Sub-tasks should be as independent as possible
3. Together, completing all sub-tasks should satisfy the parent
4. Each sub-task should be simpler than the parent
5. Include acceptance criteria for each sub-task
6. IMPORTANT: If multiple functions belong in the same file, mention the filename in each sub-task
7. First sub-task should create the file, subsequent tasks should ADD to that same file
8. Use the codebase context to understand existing patterns and structure

Respond with ONLY a JSON array of objects with "what" and "acceptance" fields.

Example - creating multiple functions in one module:
[
  {"what": "Create math_utils.py with factorial function", "acceptance": "math_utils.py exists with working factorial()"},
  {"what": "Add fibonacci function to math_utils.py", "acceptance": "fibonacci() added to math_utils.py and works"},
  {"what": "Add is_prime function to math_utils.py", "acceptance": "is_prime() added to math_utils.py and works"}
]"""

    user_prompt = f"""Decompose this intention into 2-5 smaller, verifiable sub-intentions:

INTENTION: {intention.what}
ACCEPTANCE: {intention.acceptance}
{context_section}

Provide sub-intentions that are concrete and testable.
If creating multiple functions for one module, reference the SAME filename in each sub-task."""

    try:
        response = ctx.llm.chat_json(
            system=system_prompt,
            user=user_prompt,
            timeout_seconds=30.0,
        )

        # Log LLM call
        if ctx.session_logger:
            ctx.session_logger.log_llm_call(
                module="riva",
                purpose="decompose",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
            )

        data = json.loads(response)
        children = []
        for item in data:
            # Handle both dict format and string format
            if isinstance(item, dict):
                what = item.get("what", "")
                acceptance = item.get("acceptance", "")
            elif isinstance(item, str):
                # Some models return simple strings instead of objects
                what = item
                acceptance = f"Complete: {item[:30]}..."
            else:
                continue  # Skip invalid items

            if what:  # Only add if we have a description
                child = Intention.create(
                    what=what,
                    acceptance=acceptance,
                    parent_id=intention.id,
                )
                children.append(child)

        # Track quality: LLM success
        if ctx.quality_tracker:
            from reos.code_mode.quality import QualityTier
            ctx.quality_tracker.record_event(
                operation="decomposition",
                tier=QualityTier.LLM_SUCCESS,
                reason=f"LLM generated {len(children)} sub-intentions",
                context={"intention": intention.what[:50], "children_count": len(children)},
            )

        # Human/auto confirmation
        if ctx.checkpoint.approve_decomposition(intention, children):
            if ctx.on_decomposition:
                ctx.on_decomposition(intention, children)
            return children
        else:
            logger.warning("Decomposition rejected, using heuristic")
            if ctx.quality_tracker:
                from reos.code_mode.quality import QualityTier
                ctx.quality_tracker.record_event(
                    operation="decomposition",
                    tier=QualityTier.HEURISTIC_FALLBACK,
                    reason="LLM decomposition rejected by checkpoint",
                    context={"intention": intention.what[:50]},
                )
            return _heuristic_decompose(intention, ctx)

    except Exception as e:
        logger.error("LLM decomposition failed: %s, using heuristic fallback", e, exc_info=True)
        if ctx.session_logger:
            ctx.session_logger.log_error("riva", "decompose_fallback",
                f"LLM decomposition failed: {e}. Using heuristic fallback.", {
                    "exception_type": type(e).__name__,
                    "exception": str(e),
                    "intention_what": intention.what[:100],
                    "fallback": "heuristic_decompose",
                })
        # Track quality: fallback to heuristic
        if ctx.quality_tracker:
            from reos.code_mode.quality import QualityTier
            ctx.quality_tracker.record_event(
                operation="decomposition",
                tier=QualityTier.HEURISTIC_FALLBACK,
                reason=f"LLM decomposition failed: {type(e).__name__}",
                exception=e,
                context={"intention": intention.what[:50]},
            )
        return _heuristic_decompose(intention, ctx)


def _heuristic_decompose(intention: Intention, ctx: WorkContext) -> list[Intention]:
    """Fallback heuristic decomposition when LLM unavailable."""
    children = []

    # Split on common conjunctions
    what = intention.what
    for sep in [" and ", " then ", ". ", "; "]:
        if sep in what.lower():
            parts = what.split(sep)
            for i, part in enumerate(parts):
                part = part.strip()
                if part:
                    child = Intention.create(
                        what=part,
                        acceptance=f"Part {i+1} complete: {part[:30]}...",
                        parent_id=intention.id,
                    )
                    children.append(child)
            if children:
                return children

    # Default: create setup and implementation phases
    children = [
        Intention.create(
            what=f"Set up prerequisites for: {intention.what[:50]}",
            acceptance="All dependencies and setup complete",
            parent_id=intention.id,
        ),
        Intention.create(
            what=f"Implement core logic: {intention.what[:50]}",
            acceptance=intention.acceptance,
            parent_id=intention.id,
        ),
    ]
    return children


def determine_next_action(intention: Intention, ctx: WorkContext) -> tuple[str, Action]:
    """Determine the next action to try for this intention.

    Returns:
        Tuple of (thought, action) - what we're about to try and why.
    """
    if ctx.llm is None:
        # Fallback: basic action based on keywords
        return _heuristic_action(intention, ctx)

    # Build context from previous cycles
    history = ""
    if intention.trace:
        history = "\n\nPrevious attempts:"
        for i, cycle in enumerate(intention.trace[-3:], 1):
            history += f"\n{i}. Tried: {cycle.action.content[:100]}"
            history += f"\n   Result: {cycle.result[:100]}"
            history += f"\n   Judgment: {cycle.judgment.value}"
            if cycle.reflection:
                history += f"\n   Reflection: {cycle.reflection[:100]}"

    # Check what files already exist in the repo
    existing_files = []
    try:
        py_files = ctx.sandbox.glob("**/*.py", max_results=20)
        existing_files = [str(f) for f in py_files]
    except Exception:
        pass

    existing_context = ""
    if existing_files:
        existing_context = f"\n\nExisting files in repo: {', '.join(existing_files[:10])}"
        existing_context += "\nIMPORTANT: If adding to an existing file, use 'edit' not 'create'."

    # Gather additional context using tools when available
    tool_context = gather_context(intention, ctx)
    if tool_context:
        existing_context += f"\n\n[Additional Context from Tools]\n{tool_context[:2000]}"

    system_prompt = """You are determining the next action to satisfy an intention.

CRITICAL RULES:
1. Write COMPLETE, WORKING code - never use 'pass', 'TODO', or placeholders
2. If a file already exists and you need to add to it, use "edit" not "create"
3. Include full function implementations with actual logic
4. For algorithms (factorial, fibonacci, etc.), write the actual algorithm

Respond with ONLY a JSON object:
{
  "thought": "What I'm about to try and why",
  "action_type": "one of: command, edit, create, delete, query",
  "content": "The actual command/code - MUST be complete working code",
  "target": "file path if applicable, or null"
}

Valid action_type values:
- "command": Run a shell command
- "edit": Modify/append to an existing file (USE THIS if file exists!)
- "create": Create a new file (only if file doesn't exist)
- "delete": Delete a file
- "query": Search the codebase

Example - creating a factorial function:
{"thought": "Implementing factorial with recursion", "action_type": "create", "content": "def factorial(n):\\n    if n < 0:\\n        raise ValueError('n must be non-negative')\\n    if n <= 1:\\n        return 1\\n    return n * factorial(n - 1)", "target": "math_utils.py"}

Be specific and concrete. Write REAL implementations, not stubs."""

    user_prompt = f"""Determine the next action for this intention:

INTENTION: {intention.what}
ACCEPTANCE: {intention.acceptance}
{history}{existing_context}

What should we try next? Remember: write COMPLETE working code, not placeholders."""

    try:
        response = ctx.llm.chat_json(
            system=system_prompt,
            user=user_prompt,
            timeout_seconds=30.0,
        )

        if ctx.session_logger:
            ctx.session_logger.log_llm_call(
                module="riva",
                purpose="determine_action",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
            )

        data = json.loads(response)
        thought = data.get("thought", "Attempting action")
        action = Action(
            type=ActionType(data.get("action_type", "query")),
            content=data.get("content", ""),
            target=data.get("target"),
        )

        # Track quality: LLM success
        if ctx.quality_tracker:
            from reos.code_mode.quality import QualityTier
            ctx.quality_tracker.record_event(
                operation="action_determination",
                tier=QualityTier.LLM_SUCCESS,
                reason=f"LLM generated {action.type.value} action",
                context={"intention": intention.what[:50], "action_type": action.type.value},
            )

        return thought, action

    except Exception as e:
        logger.error("LLM action determination failed: %s, using heuristic", e, exc_info=True)
        if ctx.session_logger:
            ctx.session_logger.log_error("riva", "action_determination_fallback",
                f"LLM action determination failed: {e}. Using heuristic.", {
                    "exception_type": type(e).__name__,
                    "exception": str(e),
                    "intention_what": intention.what[:100],
                    "fallback": "heuristic_action",
                })
        # Track quality: fallback to heuristic
        if ctx.quality_tracker:
            from reos.code_mode.quality import QualityTier
            ctx.quality_tracker.record_event(
                operation="action_determination",
                tier=QualityTier.HEURISTIC_FALLBACK,
                reason=f"LLM action determination failed: {type(e).__name__}",
                exception=e,
                context={"intention": intention.what[:50]},
            )
        return _heuristic_action(intention, ctx)


def _heuristic_action(intention: Intention, ctx: WorkContext) -> tuple[str, Action]:
    """Fallback heuristic action when LLM unavailable."""
    what_lower = intention.what.lower()

    # Check for existing files to determine create vs edit
    existing_files = set()
    existing_basenames = set()
    try:
        py_files = ctx.sandbox.glob("**/*.py", max_results=20)
        existing_files = {str(f) for f in py_files}
        # Also track just the basenames for easier matching
        import os
        existing_basenames = {os.path.basename(str(f)) for f in py_files}
    except Exception:
        pass

    # Try to extract filename from intention
    target_file = None
    words = intention.what.split()
    for w in words:
        if "." in w and len(w) < 50:  # Looks like a filename
            target_file = w.strip("'\"(),")
            break

    # Generate actual code based on common patterns
    content = _generate_heuristic_code(intention.what)

    # File creation or edit
    if any(w in what_lower for w in ["create", "write", "add", "implement"]):
        if target_file:
            # Check if file exists - use edit instead of create
            # Compare both full path and basename
            file_exists = (
                target_file in existing_files or
                target_file in existing_basenames or
                any(target_file in f for f in existing_files)
            )
            if file_exists:
                return (
                    f"Adding to existing file {target_file}",
                    Action(ActionType.EDIT, content, target_file)
                )
            return (
                f"Creating file {target_file}",
                Action(ActionType.CREATE, content, target_file)
            )
        return (
            "Creating new file",
            Action(ActionType.CREATE, content, "new_file.py")
        )

    # Running tests
    if any(w in what_lower for w in ["test", "verify", "check"]):
        return (
            "Running tests to verify",
            Action(ActionType.COMMAND, "python -m pytest -v", None)
        )

    # Default: query/explore
    return (
        "Exploring codebase for context",
        Action(ActionType.QUERY, f"Search for: {intention.what[:50]}", None)
    )


def _generate_heuristic_code(intention_what: str) -> str:
    """Generate actual code based on common patterns in the intention."""
    what_lower = intention_what.lower()

    # Check for multiple functions mentioned and combine them
    functions = []

    if "factorial" in what_lower:
        functions.append('''def factorial(n):
    """Calculate the factorial of n."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return 1
    return n * factorial(n - 1)''')

    if "fibonacci" in what_lower:
        functions.append('''def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b''')

    if "prime" in what_lower or "is_prime" in what_lower:
        functions.append('''def is_prime(n):
    """Return True if n is a prime number."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True''')

    # If we found multiple functions, combine them
    if functions:
        return '\n\n\n'.join(functions)

    if "add" in what_lower and "subtract" in what_lower:
        # Calculator-like module
        return '''def add(a, b):
    """Return the sum of a and b."""
    return a + b

def subtract(a, b):
    """Return a minus b."""
    return a - b

def multiply(a, b):
    """Return the product of a and b."""
    return a * b

def divide(a, b):
    """Return a divided by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b'''

    # Try to extract a function name and generate a stub with docstring
    import re
    func_match = re.search(r'(?:function|def|implement)\s+(\w+)', what_lower)
    if func_match:
        func_name = func_match.group(1)
        return f'''def {func_name}(*args, **kwargs):
    """Implementation of {func_name}."""
    # TODO: Implement {func_name}
    raise NotImplementedError("{func_name} not yet implemented")'''

    # Default: minimal module structure
    return '''# Module implementation
# TODO: Add implementation based on requirements'''


def _strip_markdown_code_block(content: str) -> str:
    """Strip markdown code block formatting from content.

    LLMs often wrap code in ```language ... ``` blocks.
    This extracts the inner content.
    """
    import re
    content = content.strip()

    # Match ```language\n...\n``` or ```\n...\n```
    match = re.match(r'^```(?:\w+)?\s*\n(.*)\n```$', content, re.DOTALL)
    if match:
        return match.group(1)

    # Match just ```...``` (no newlines)
    match = re.match(r'^```(?:\w+)?\s*(.*?)\s*```$', content, re.DOTALL)
    if match:
        return match.group(1)

    return content


def _merge_python_content(existing: str, new_content: str) -> str:
    """Intelligently merge new Python code into existing content.

    Appends new functions/classes without duplicating existing ones.
    """
    import re

    # Extract function and class names from existing content
    existing_defs = set(re.findall(r'^(?:def|class)\s+(\w+)', existing, re.MULTILINE))

    # Extract function and class names from new content
    new_defs = re.findall(r'^(?:def|class)\s+(\w+)', new_content, re.MULTILINE)

    # If new content defines something already in existing, it's a replacement
    # If it's entirely new, append it
    has_overlap = any(name in existing_defs for name in new_defs)

    if has_overlap:
        # New content redefines existing functions - could be an update
        # For now, append anyway (user might want both versions during development)
        # A smarter version could replace the specific functions
        pass

    # Check if new content has any new definitions
    new_unique_defs = [name for name in new_defs if name not in existing_defs]

    if not new_unique_defs and not new_content.strip():
        # Nothing new to add
        return existing

    # Append new content, handling imports specially
    new_lines = new_content.strip().split('\n')
    existing_lines = existing.strip().split('\n')

    # Extract imports from new content
    new_imports = []
    new_code = []
    for line in new_lines:
        if line.startswith(('import ', 'from ')):
            if line not in existing:
                new_imports.append(line)
        else:
            new_code.append(line)

    # Build merged content
    result_lines = []

    # First, existing imports
    for line in existing_lines:
        result_lines.append(line)
        # After the last import, add new imports
        if line.startswith(('import ', 'from ')):
            continue

    # Find where to insert new imports (after existing imports)
    insert_pos = 0
    for i, line in enumerate(result_lines):
        if line.startswith(('import ', 'from ')):
            insert_pos = i + 1
        elif line.strip() and not line.startswith('#'):
            break

    # Insert new imports
    for imp in new_imports:
        result_lines.insert(insert_pos, imp)
        insert_pos += 1

    # Append new code at the end
    if new_code:
        # Add blank lines before new code
        if result_lines and result_lines[-1].strip():
            result_lines.append('')
            result_lines.append('')
        result_lines.extend(new_code)

    return '\n'.join(result_lines)


def execute_action(action: Action, ctx: WorkContext) -> str:
    """Execute an action and return the result."""
    if ctx.session_logger:
        ctx.session_logger.log_debug("riva", "execute_start",
            f"Executing {action.type.value}: {action.content[:50]}...", {
                "action_type": action.type.value,
                "target": action.target,
            })

    try:
        if action.type == ActionType.COMMAND:
            # run_command returns (returncode, stdout, stderr) tuple
            returncode, stdout, stderr = ctx.sandbox.run_command(action.content, timeout=60)
            result = f"Exit code: {returncode}\nOutput: {stdout or ''}\nStderr: {stderr or ''}"

            if ctx.session_logger:
                ctx.session_logger.log_info("riva", "command_result",
                    f"Command completed with exit code {returncode}", {
                        "exit_code": returncode,
                        "stdout_preview": (stdout or "")[:200],
                        "stderr_preview": (stderr or "")[:200],
                    })
            return result

        elif action.type == ActionType.CREATE:
            if action.target:
                # Strip markdown code blocks from LLM output
                clean_content = _strip_markdown_code_block(action.content)
                ctx.sandbox.write_file(action.target, clean_content)
                if ctx.session_logger:
                    ctx.session_logger.log_info("riva", "file_created",
                        f"Created file: {action.target}", {
                            "target": action.target,
                            "content_length": len(clean_content),
                        })
                return f"Created file: {action.target}"
            return "Error: No target specified for create action"

        elif action.type == ActionType.EDIT:
            if action.target:
                # Strip markdown code blocks
                clean_content = _strip_markdown_code_block(action.content)

                # Try to read existing content and append intelligently
                existing_content = ""
                try:
                    existing_content = ctx.sandbox.read_file(action.target)
                except Exception:
                    pass  # File might not exist yet

                if existing_content:
                    # Append new content if it contains new functions/classes
                    merged = _merge_python_content(existing_content, clean_content)
                    ctx.sandbox.write_file(action.target, merged)
                    if ctx.session_logger:
                        ctx.session_logger.log_info("riva", "file_edited",
                            f"Merged content into {action.target}", {
                                "target": action.target,
                                "original_length": len(existing_content),
                                "new_length": len(merged),
                            })
                    return f"Edited file: {action.target} (merged)"
                else:
                    ctx.sandbox.write_file(action.target, clean_content)
                    if ctx.session_logger:
                        ctx.session_logger.log_info("riva", "file_edited",
                            f"Created file: {action.target}", {
                                "target": action.target,
                                "content_length": len(clean_content),
                            })
                    return f"Edited file: {action.target}"
            return "Error: No target specified for edit action"

        elif action.type == ActionType.DELETE:
            if action.target:
                ctx.sandbox.delete_file(action.target)
                if ctx.session_logger:
                    ctx.session_logger.log_info("riva", "file_deleted",
                        f"Deleted file: {action.target}")
                return f"Deleted file: {action.target}"
            return "Error: No target specified for delete action"

        elif action.type == ActionType.QUERY:
            # Search/explore
            matches = ctx.sandbox.grep(action.content, glob_pattern="**/*.py", max_results=10)
            if matches:
                result = f"Found {len(matches)} matches:\n" + "\n".join(
                    f"  {m.path}:{m.line_number}: {m.line_content[:60]}" for m in matches[:5]
                )
                if ctx.session_logger:
                    ctx.session_logger.log_info("riva", "query_result",
                        f"Found {len(matches)} matches", {
                            "match_count": len(matches),
                            "query": action.content[:50],
                        })
                return result
            return "No matches found"

        return "Unknown action type"

    except Exception as e:
        error_msg = f"Error executing action: {e}"
        if ctx.session_logger:
            ctx.session_logger.log_error("riva", "execute_error", error_msg, {
                "action_type": action.type.value,
                "error_type": type(e).__name__,
                "error": str(e),
            })
        logger.error("Action execution failed: %s", e)
        return error_msg


def reflect(intention: Intention, cycle: Cycle, ctx: WorkContext) -> str:
    """Reflect on a failed cycle to determine next steps."""
    if ctx.llm is None:
        return f"Action failed with judgment: {cycle.judgment.value}. Will retry with different approach."

    system_prompt = """You are reflecting on a failed action to determine what went wrong and what to try next.

Provide a brief analysis:
1. Why did it fail?
2. What's missing or wrong?
3. Should we decompose this into smaller tasks?
4. What should we try next?

Keep response under 100 words."""

    user_prompt = f"""Reflect on this failed attempt:

INTENTION: {intention.what}
ACCEPTANCE: {intention.acceptance}

ACTION: {cycle.action.type.value} - {cycle.action.content[:200]}
RESULT: {cycle.result[:500]}
JUDGMENT: {cycle.judgment.value}

Why did this fail and what should we do?"""

    try:
        response = ctx.llm.chat_text(
            system=system_prompt,
            user=user_prompt,
            timeout_seconds=20.0,
        )

        if ctx.session_logger:
            ctx.session_logger.log_llm_call(
                module="riva",
                purpose="reflect",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
            )

        return response.strip()

    except Exception as e:
        logger.error("LLM reflection failed: %s", e, exc_info=True)
        if ctx.session_logger:
            ctx.session_logger.log_error("riva", "reflection_failed",
                f"LLM reflection failed: {e}", {
                    "exception_type": type(e).__name__,
                    "exception": str(e),
                    "cycle_judgment": cycle.judgment.value if cycle else "unknown",
                })
        return f"Unable to analyze failure (error: {type(e).__name__}). Retrying with different approach."


def integrate(intention: Intention, ctx: WorkContext) -> bool:
    """Integrate child intentions and verify at parent level.

    After all children are verified, test that they work together
    and verify at the parent's acceptance criteria level.
    """
    if ctx.session_logger:
        ctx.session_logger.log_info("riva", "integrate",
            f"Integrating children for: {intention.what[:50]}...")

    # Check all children are verified
    for child in intention._child_intentions:
        if child.status != IntentionStatus.VERIFIED:
            logger.warning("Child '%s' not verified, cannot integrate", child.what[:30])
            return False

    # Human/auto verification at parent level
    if ctx.checkpoint.verify_integration(intention):
        intention.status = IntentionStatus.VERIFIED
        intention.verified_at = datetime.now(timezone.utc)

        if ctx.session_logger:
            ctx.session_logger.log_info("riva", "integrate_success",
                f"Integration verified: {intention.what[:50]}...")
        return True
    else:
        logger.warning("Integration verification failed for '%s'", intention.what[:30])
        return False


def work(intention: Intention, ctx: WorkContext, depth: int = 0) -> None:
    """The recursive navigation algorithm.

    Core principle: If you can't verify it, decompose it.

    1. Can we verify this intention directly?
    2. If yes, try to satisfy it with action cycles
    3. If no (or cycles fail), decompose into sub-intentions
    4. Work each child recursively
    5. Integrate and verify at parent level
    6. Bubble up success/failure
    """
    # Guard against infinite recursion
    if depth > ctx.max_depth:
        logger.error("Max depth exceeded, failing intention")
        intention.status = IntentionStatus.FAILED
        return

    # Log start
    if ctx.session_logger:
        ctx.session_logger.log_info("riva", "work_start",
            f"[depth={depth}] Working on: {intention.what[:60]}...", {
                "intention_id": intention.id,
                "depth": depth,
                "acceptance": intention.acceptance[:100],
            })

    if ctx.on_intention_start:
        ctx.on_intention_start(intention)

    intention.status = IntentionStatus.ACTIVE

    # 1. Can we verify this intention directly?
    verifiable = can_verify_directly(intention, ctx)

    if ctx.session_logger:
        ctx.session_logger.log_decision("riva", "verifiable",
            "yes" if verifiable else "no",
            f"Intention {'can' if verifiable else 'cannot'} be verified directly")

    if verifiable:
        # 2. Try to satisfy it with action cycles
        while intention.status == IntentionStatus.ACTIVE:
            # Determine next action
            thought, action = determine_next_action(intention, ctx)

            if ctx.session_logger:
                ctx.session_logger.log_debug("riva", "cycle_start",
                    f"Thought: {thought[:50]}...", {
                        "action_type": action.type.value,
                        "action_content": action.content[:100],
                    })

            # Execute action
            result = execute_action(action, ctx)

            # Create cycle
            cycle = Cycle(
                thought=thought,
                action=action,
                result=result,
                judgment=Judgment.UNCLEAR,  # Will be set by checkpoint
            )

            # Human/auto judgment
            cycle.judgment = ctx.checkpoint.judge_action(intention, cycle)

            if ctx.session_logger:
                ctx.session_logger.log_info("riva", "cycle_complete",
                    f"Judgment: {cycle.judgment.value}", {
                        "result_preview": result[:200],
                    })

            if cycle.judgment == Judgment.SUCCESS:
                intention.status = IntentionStatus.VERIFIED
                intention.verified_at = datetime.now(timezone.utc)
            else:
                # Reflect on failure
                cycle.reflection = reflect(intention, cycle, ctx)

                if ctx.session_logger:
                    ctx.session_logger.log_debug("riva", "reflection",
                        f"Reflection: {cycle.reflection[:100]}...")

                # Check if we should decompose instead of retry
                if should_decompose(intention, cycle, ctx):
                    break  # Exit to decomposition path

            intention.add_cycle(cycle)

            if ctx.on_cycle_complete:
                ctx.on_cycle_complete(intention, cycle)

    # 3. If not verifiable or should decompose, break it down
    if intention.status != IntentionStatus.VERIFIED:
        if not verifiable or should_decompose(intention, intention.trace[-1] if intention.trace else None, ctx):

            if ctx.session_logger:
                ctx.session_logger.log_info("riva", "decomposing",
                    f"Decomposing: {intention.what[:50]}...")

            # Decompose into sub-intentions
            children = decompose(intention, ctx)

            for child in children:
                intention.add_child(child)

            # 4. Work each child recursively
            for child in intention._child_intentions:
                work(child, ctx, depth + 1)

                # If child failed, propagate up
                if child.status == IntentionStatus.FAILED:
                    intention.status = IntentionStatus.FAILED

                    if ctx.session_logger:
                        ctx.session_logger.log_error("riva", "child_failed",
                            f"Child failed: {child.what[:50]}...")

                    if ctx.on_intention_complete:
                        ctx.on_intention_complete(intention)
                    return

            # 5. All children verified - integrate
            if not integrate(intention, ctx):
                intention.status = IntentionStatus.FAILED

    # 6. Complete
    if ctx.session_logger:
        ctx.session_logger.log_info("riva", "work_complete",
            f"[depth={depth}] {intention.status.value}: {intention.what[:50]}...", {
                "status": intention.status.value,
                "cycles": len(intention.trace),
                "children": len(intention._child_intentions),
            })

    if ctx.on_intention_complete:
        ctx.on_intention_complete(intention)


@dataclass
class Session:
    """Complete session capture for training data.

    Every session produces a tree of intentions with full traces.
    This structure captures:
    - Intent at every scale (the what and acceptance fields)
    - Actions taken (the action in each cycle)
    - Human judgment (the judgment field)
    - Reasoning through failure (the reflection field)
    - How big problems become small problems (the tree structure)
    """
    id: str
    timestamp: str
    root: Intention
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(root: Intention) -> Session:
        """Create a new session from a root intention."""
        return Session(
            id=f"session-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            root=root,
            metadata={
                "duration": 0,
                "total_cycles": root.get_total_cycles(),
                "max_depth": root.get_depth(),
                "outcome": root.status.value,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "root": self.root.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            root=Intention.from_dict(data["root"]),
            metadata=data.get("metadata", {}),
        )

    def save(self, path: Path) -> None:
        """Save session to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Session:
        """Load session from JSON file."""
        with open(path) as f:
            return cls.from_dict(json.load(f))
