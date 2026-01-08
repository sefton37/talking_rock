"""Handoff system models for Talking Rock.

Defines the data structures for agent-to-agent handoffs with:
- Structured context passing (distilled, not full history)
- User confirmation gates
- Explicit, verbose transition messaging
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AgentType(Enum):
    """The three Talking Rock agents."""

    CAIRN = "cairn"   # Attention minder - life, knowledge base, default entry
    REOS = "reos"     # System agent - Linux, terminal, services
    RIVA = "riva"     # Code agent - development, git, testing


class HandoffStatus(Enum):
    """Status of a handoff request."""

    PROPOSED = "proposed"       # Agent proposed handoff, awaiting user confirmation
    CONFIRMED = "confirmed"     # User confirmed, handoff proceeding
    REJECTED = "rejected"       # User rejected, staying with current agent
    COMPLETED = "completed"     # Handoff completed, target agent active
    FAILED = "failed"           # Handoff failed (target unavailable, etc.)


class DomainConfidence(Enum):
    """How confident we are about domain classification."""

    HIGH = "high"       # Clear domain match (e.g., "install nginx")
    MEDIUM = "medium"   # Likely match (e.g., "help with the server")
    LOW = "low"         # Ambiguous (e.g., "fix this")
    MIXED = "mixed"     # Multiple domains detected


@dataclass
class HandoffContext:
    """Structured context passed to the receiving agent.

    This is the distilled, focused context - not full conversation history.
    Designed to give the receiving agent exactly what it needs to continue.
    """

    # What the user is trying to accomplish
    user_goal: str

    # Why this handoff is happening
    handoff_reason: str

    # Key information from the conversation
    relevant_details: list[str] = field(default_factory=list)

    # Any files, paths, or resources mentioned
    relevant_paths: list[str] = field(default_factory=list)

    # Any entities (contacts, projects, services) involved
    relevant_entities: list[str] = field(default_factory=list)

    # The last few user messages for immediate context
    recent_messages: list[str] = field(default_factory=list)

    # Any decisions or preferences expressed
    user_preferences: dict[str, Any] = field(default_factory=dict)

    # Timestamp for context freshness
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "user_goal": self.user_goal,
            "handoff_reason": self.handoff_reason,
            "relevant_details": self.relevant_details,
            "relevant_paths": self.relevant_paths,
            "relevant_entities": self.relevant_entities,
            "recent_messages": self.recent_messages,
            "user_preferences": self.user_preferences,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffContext:
        """Create from dictionary."""
        return cls(
            user_goal=data["user_goal"],
            handoff_reason=data["handoff_reason"],
            relevant_details=data.get("relevant_details", []),
            relevant_paths=data.get("relevant_paths", []),
            relevant_entities=data.get("relevant_entities", []),
            recent_messages=data.get("recent_messages", []),
            user_preferences=data.get("user_preferences", {}),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(),
        )

    def to_prompt(self) -> str:
        """Format context as a prompt for the receiving agent."""
        lines = [
            f"## Handoff Context",
            f"",
            f"**User Goal:** {self.user_goal}",
            f"",
            f"**Why This Handoff:** {self.handoff_reason}",
        ]

        if self.relevant_details:
            lines.append("")
            lines.append("**Key Details:**")
            for detail in self.relevant_details:
                lines.append(f"- {detail}")

        if self.relevant_paths:
            lines.append("")
            lines.append("**Relevant Paths:**")
            for path in self.relevant_paths:
                lines.append(f"- `{path}`")

        if self.relevant_entities:
            lines.append("")
            lines.append("**Related Entities:**")
            for entity in self.relevant_entities:
                lines.append(f"- {entity}")

        if self.recent_messages:
            lines.append("")
            lines.append("**Recent Context:**")
            for msg in self.recent_messages[-3:]:  # Last 3 messages max
                lines.append(f"> {msg}")

        return "\n".join(lines)


@dataclass
class HandoffDecision:
    """The result of analyzing whether a handoff is needed.

    Uses RIVA-style intent verification to determine the primary domain
    when requests span multiple domains.
    """

    # Should we handoff?
    should_handoff: bool

    # If yes, to which agent?
    target_agent: AgentType | None = None

    # How confident are we?
    confidence: DomainConfidence = DomainConfidence.MEDIUM

    # Why are we recommending this?
    reason: str = ""

    # What domains were detected?
    detected_domains: list[AgentType] = field(default_factory=list)

    # For multi-domain requests, what's the primary intent?
    primary_intent: str | None = None

    # What secondary tasks might need attention later?
    deferred_intents: list[str] = field(default_factory=list)

    # Can the current agent handle this simply?
    can_handle_simply: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "should_handoff": self.should_handoff,
            "target_agent": self.target_agent.value if self.target_agent else None,
            "confidence": self.confidence.value,
            "reason": self.reason,
            "detected_domains": [d.value for d in self.detected_domains],
            "primary_intent": self.primary_intent,
            "deferred_intents": self.deferred_intents,
            "can_handle_simply": self.can_handle_simply,
        }


@dataclass
class HandoffRequest:
    """A request to hand off to another agent.

    This is the full handoff record including user confirmation status.
    """

    # Unique ID for this handoff
    handoff_id: str

    # Source and target
    source_agent: AgentType
    target_agent: AgentType

    # The structured context to pass
    context: HandoffContext

    # Current status
    status: HandoffStatus = HandoffStatus.PROPOSED

    # The verbose message shown to user
    transition_message: str = ""

    # Whether to open the target agent's specialized UI
    open_ui: bool = True

    # Timestamps
    proposed_at: datetime = field(default_factory=datetime.now)
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None

    # If rejected, why?
    rejection_reason: str | None = None

    # If failed, what went wrong?
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "handoff_id": self.handoff_id,
            "source_agent": self.source_agent.value,
            "target_agent": self.target_agent.value,
            "context": self.context.to_dict(),
            "status": self.status.value,
            "transition_message": self.transition_message,
            "open_ui": self.open_ui,
            "proposed_at": self.proposed_at.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "rejection_reason": self.rejection_reason,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffRequest:
        """Create from dictionary."""
        return cls(
            handoff_id=data["handoff_id"],
            source_agent=AgentType(data["source_agent"]),
            target_agent=AgentType(data["target_agent"]),
            context=HandoffContext.from_dict(data["context"]),
            status=HandoffStatus(data["status"]),
            transition_message=data.get("transition_message", ""),
            open_ui=data.get("open_ui", True),
            proposed_at=datetime.fromisoformat(data["proposed_at"]),
            confirmed_at=datetime.fromisoformat(data["confirmed_at"])
            if data.get("confirmed_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            rejection_reason=data.get("rejection_reason"),
            failure_reason=data.get("failure_reason"),
        )


# Agent descriptions for transition messages
AGENT_DESCRIPTIONS: dict[AgentType, dict[str, str]] = {
    AgentType.CAIRN: {
        "name": "CAIRN",
        "role": "Attention Minder",
        "domain": "life organization, knowledge base, calendars, reminders, and priorities",
        "personality": "calm, non-coercive, makes room rather than demands",
        "ui": "focus view with today's priorities and knowledge base",
    },
    AgentType.REOS: {
        "name": "ReOS",
        "role": "System Agent",
        "domain": "Linux system administration, services, packages, processes, and terminal operations",
        "personality": "precise, safety-conscious, explains before acting",
        "ui": "terminal view with command output and system status",
    },
    AgentType.RIVA: {
        "name": "RIVA",
        "role": "Code Agent",
        "domain": "software development, code editing, debugging, testing, and git operations",
        "personality": "methodical, verifies intent before making changes",
        "ui": "code editor view with file tree and diff preview",
    },
}


def generate_transition_message(
    source: AgentType,
    target: AgentType,
    context: HandoffContext,
) -> str:
    """Generate a verbose, transparent transition message.

    The message explains:
    - Who is handing off to whom
    - Why this handoff makes sense
    - What the target agent specializes in
    - What will happen next
    """
    source_info = AGENT_DESCRIPTIONS[source]
    target_info = AGENT_DESCRIPTIONS[target]

    message = f"""## Handoff Proposed: {source_info['name']} → {target_info['name']}

**Why I'm suggesting this handoff:**
{context.handoff_reason}

**About {target_info['name']}:**
{target_info['name']} is the {target_info['role']}, specializing in {target_info['domain']}.
Its approach is {target_info['personality']}.

**What will happen:**
- The conversation will continue with {target_info['name']}
- {target_info['name']} will receive context about your goal: "{context.user_goal}"
- The UI will switch to {target_info['ui']}

**Your choice:**
You can confirm this handoff, or stay with {source_info['name']} if you prefer.
"""
    return message
