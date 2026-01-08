"""Handoff system for Talking Rock.

Enables seamless agent-to-agent transfers with:
- Structured context passing (distilled, not full history)
- User confirmation gates (switching is always user-gated)
- Explicit, verbose transition messaging
- RIVA-style intent verification for multi-domain requests

The three agents:
- CAIRN: Attention minder (life, knowledge base, calendars)
- ReOS: System agent (Linux, terminal, services)
- RIVA: Code agent (development, git, testing)
"""

from __future__ import annotations

from reos.handoff.models import (
    AgentType,
    HandoffStatus,
    DomainConfidence,
    HandoffContext,
    HandoffDecision,
    HandoffRequest,
    AGENT_DESCRIPTIONS,
    generate_transition_message,
)

from reos.handoff.router import (
    detect_handoff_need,
    build_handoff_context,
    suggest_handoff_for_agent,
    analyze_domain,
    is_complex_request,
    is_simple_request,
)

from reos.handoff.tools import (
    SharedTool,
    SharedToolHandler,
    SHARED_TOOL_DEFINITIONS,
    get_shared_tool_schemas,
    get_shared_tool_names,
    is_shared_tool,
)

from reos.handoff.manifests import (
    CoreTool,
    MAX_TOOLS_PER_AGENT,
    CAIRN_CORE_TOOLS,
    REOS_CORE_TOOLS,
    RIVA_CORE_TOOLS,
    get_agent_manifest,
    get_tool_names_for_agent,
    validate_all_manifests,
)

__all__ = [
    # Models
    "AgentType",
    "HandoffStatus",
    "DomainConfidence",
    "HandoffContext",
    "HandoffDecision",
    "HandoffRequest",
    "AGENT_DESCRIPTIONS",
    "generate_transition_message",
    # Router
    "detect_handoff_need",
    "build_handoff_context",
    "suggest_handoff_for_agent",
    "analyze_domain",
    "is_complex_request",
    "is_simple_request",
    # Tools
    "SharedTool",
    "SharedToolHandler",
    "SHARED_TOOL_DEFINITIONS",
    "get_shared_tool_schemas",
    "get_shared_tool_names",
    "is_shared_tool",
    # Manifests
    "CoreTool",
    "MAX_TOOLS_PER_AGENT",
    "CAIRN_CORE_TOOLS",
    "REOS_CORE_TOOLS",
    "RIVA_CORE_TOOLS",
    "get_agent_manifest",
    "get_tool_names_for_agent",
    "validate_all_manifests",
]
