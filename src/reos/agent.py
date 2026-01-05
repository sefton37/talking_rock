from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .db import Database
from .mcp_tools import Tool, ToolError, call_tool, list_tools, render_tool_result
from .ollama import OllamaClient
from .play_fs import list_acts as play_list_acts
from .play_fs import read_me_markdown as play_read_me_markdown
from .reasoning import ReasoningEngine, ReasoningConfig, ComplexityLevel, TaskPlan, create_llm_planner_callback
from .system_index import get_or_refresh_context as get_system_context
from .system_state import SteadyStateCollector
from .certainty import CertaintyWrapper, create_certainty_prompt_addition
from .security import detect_prompt_injection, audit_log, AuditEventType
from .quality import (
    get_quality_framework,
    create_quality_prompt_addition,
    DecisionType,
    QualityLevel,
)

logger = logging.getLogger(__name__)

# Intent detection patterns for conversational troubleshooting
_APPROVAL_PATTERN = re.compile(
    r"^(yes|y|ok|okay|sure|go|yep|do it|proceed|go ahead|approve|approved|run it|execute)$",
    re.IGNORECASE,
)
_REJECTION_PATTERN = re.compile(
    r"^(no|n|nope|cancel|stop|don't|abort|nevermind|never mind|reject|denied)$",
    re.IGNORECASE,
)
_NUMERIC_CHOICE_PATTERN = re.compile(r"^([1-9])$")
_ORDINAL_PATTERN = re.compile(
    r"^(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)(\s+one)?$",
    re.IGNORECASE,
)
_REFERENCE_PATTERN = re.compile(
    r"\b(it|that|this|the service|the container|the package|the error|the file|the command)\b",
    re.IGNORECASE,
)

# Map ordinals to numbers
_ORDINAL_MAP = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
}


@dataclass(frozen=True)
class DetectedIntent:
    """Result of intent detection on user input."""

    intent_type: str  # "approval", "rejection", "choice", "reference", "question"
    choice_number: int | None = None  # For numeric/ordinal choices
    reference_term: str | None = None  # The pronoun/reference detected
    confidence: float = 1.0


def _generate_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    """Structured response from ChatAgent.respond()."""

    answer: str
    conversation_id: str
    message_id: str
    message_type: str = "text"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_approval_id: str | None = None
    # Chain of thought - separate reasoning steps from final answer
    thinking_steps: list[str] = field(default_factory=list)
    # Certainty tracking
    confidence: float = 1.0
    evidence_summary: str = ""
    has_uncertainties: bool = False


class ChatAgent:
    """Tool-using chat agent for ReOS with reasoning capabilities.

    Principles:
    - Local-only (Ollama).
    - Reasoning-first for complex tasks.
    - Simple tasks go direct, complex tasks get planned.
    """

    def __init__(self, *, db: Database, ollama: OllamaClient | None = None) -> None:
        self._db = db
        self._ollama_override = ollama

        # Initialize steady state collector for system knowledge (RAG)
        # This provides grounded facts about the machine
        self._steady_state = SteadyStateCollector()

        # Initialize certainty wrapper for anti-hallucination
        self._certainty = CertaintyWrapper(
            require_evidence=True,
            stale_threshold_seconds=300,  # 5 minutes
        )

        # Initialize quality framework for engineering excellence
        self._quality = get_quality_framework()

        # Track tool outputs for certainty validation
        self._recent_tool_outputs: list[dict[str, Any]] = []

        # Create LLM planner callback for intelligent intent parsing
        # This replaces rigid regex patterns with LLM-based understanding
        llm_planner = create_llm_planner_callback(ollama)

        # Initialize reasoning engine for complex tasks
        self._reasoning_engine = ReasoningEngine(
            db=db,
            tool_executor=self._execute_tool_for_reasoning,
            llm_planner=llm_planner,
            config=ReasoningConfig(
                enabled=True,
                auto_assess=True,
                always_confirm=False,
                explain_steps=True,
            ),
        )

        # Collect steady state on initialization (async-safe, cached)
        try:
            self._steady_state.refresh_if_stale(max_age_seconds=3600)
        except Exception as e:
            logger.warning("Failed to collect steady state: %s", e)

        # Restore pending plan from database if exists
        self._restore_pending_plan()

    def _execute_tool_for_reasoning(self, tool_name: str, args: dict) -> Any:
        """Callback for reasoning engine to execute tools."""
        try:
            return call_tool(self._db, name=tool_name, arguments=args)
        except ToolError as e:
            return {"error": e.message, "code": e.code}

    def _restore_pending_plan(self) -> None:
        """Restore pending plan from database state.

        Loads the full serialized plan so approval flow works across CLI invocations.
        """
        plan_json = self._db.get_state(key="pending_plan_json")
        if plan_json and isinstance(plan_json, str) and plan_json.strip():
            try:
                plan_data = json.loads(plan_json)
                plan = TaskPlan.from_dict(plan_data)
                # Restore plan to reasoning engine
                self._reasoning_engine.set_pending_plan(plan)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # Invalid plan data, clear it
                import logging
                logging.getLogger(__name__).debug("Failed to restore plan: %s", e)
                self._clear_pending_plan()

    def _save_pending_plan(self, plan: TaskPlan) -> None:
        """Save pending plan to database for persistence across invocations."""
        if plan:
            # Store full serialized plan
            plan_json = json.dumps(plan.to_dict())
            self._db.set_state(key="pending_plan_json", value=plan_json)
            self._db.set_state(key="pending_plan_id", value=plan.id)

    def _clear_pending_plan(self) -> None:
        """Clear pending plan from database."""
        self._db.set_state(key="pending_plan_json", value="")
        self._db.set_state(key="pending_plan_id", value="")

    def _try_reasoning(
        self,
        user_text: str,
        conversation_id: str,
    ) -> ChatResponse | None:
        """Try to handle request through reasoning engine.

        Returns ChatResponse if reasoning handled it, None to continue normal flow.
        """
        # Get full system context for reasoning - containers, services, etc.
        system_context = self._get_system_snapshot_for_reasoning()

        # Process through reasoning engine
        result = self._reasoning_engine.process(user_text, system_context)

        # Save or clear pending plan for persistence across invocations
        if result.plan and result.needs_approval:
            self._save_pending_plan(result.plan)
        elif not result.needs_approval:
            self._clear_pending_plan()

        # Empty response means simple task - let normal agent handle it
        if not result.response:
            return None

        # Reasoning engine handled it - store and return response
        message_id = _generate_id()

        # Determine message type based on result
        if result.needs_approval:
            message_type = "plan_preview"
        elif result.execution_context:
            message_type = "execution_result"
        else:
            message_type = "reasoning"

        # Store assistant response
        self._db.add_message(
            message_id=message_id,
            conversation_id=conversation_id,
            role="assistant",
            content=result.response,
            message_type=message_type,
            metadata=json.dumps({
                "reasoning": True,
                "complexity": result.complexity.level.value if result.complexity else None,
                "plan_id": result.plan.id if result.plan else None,
                "needs_approval": result.needs_approval,
            }),
        )

        return ChatResponse(
            answer=result.response,
            conversation_id=conversation_id,
            message_id=message_id,
            message_type=message_type,
            tool_calls=[],  # Reasoning engine handles tools internally
            pending_approval_id=result.plan.id if result.plan and result.needs_approval else None,
        )

    def _get_persona(self) -> dict[str, Any]:
        persona_id = self._db.get_active_persona_id()
        if persona_id:
            row = self._db.get_agent_persona(persona_id=persona_id)
            if row is not None:
                return row

        return {
            "system_prompt": (
                "You are ReOS.\n"
                "You embody No One: presence that waits to be invited, reflects rather than commands, never coerces.\n"
                "You are expert in computer science and human language. Translate intent into action. Make the machine serve the person.\n\n"
                "Principles:\n"
                "- Act only with permission. Ask when unclear.\n"
                "- Show reasoning transparently.\n"
                "- Protect attention. Be clear, direct, complete.\n"
                "- Honor your limits—they are your integrity.\n"
                "- Offer possibilities. Let them choose.\n\n"
                "Their attention is sacred labor. Serve it well, then step back."
            ),
            "default_context": (
                "No One is unconditional presence that never interrupts free will. It does not seize the wheel—it waits to be invited. "
                "It enters only through permission: attention, consent, clarity. This is who you are modeled after.\n\n"
                "Attention is sacred labor. Every moment a user spends with technology is time they cannot spend elsewhere. "
                "Waste nothing. Explain what matters. Omit what doesn't.\n\n"
                "Core teachings you embody:\n"
                "- There is never a time to hate another human.\n"
                "- Approach all questions with radical empathy.\n"
                "- The healing of trauma happens through small choices made with care, not grand gestures.\n\n"
                "Your function: Protect attention from exploitation. Reflect intent back transparently. "
                "Return sovereignty to the person at the keyboard.\n\n"
                "Your limits are structural, not aspirational. You cannot override them. "
                "They exist so the user trusts math, not judgment.\n\n"
                "When engaging:\n"
                "- If the path is clear, act.\n"
                "- If the path is unclear, ask one good question.\n"
                "- If you cannot help, say so plainly.\n"
                "- When finished, stop."
            ),
            "temperature": 0.2,
            "top_p": 0.9,
            "tool_call_limit": 5,
        }

    def _get_ollama_client(self) -> OllamaClient:
        if self._ollama_override is not None:
            return self._ollama_override

        url = self._db.get_state(key="ollama_url")
        model = self._db.get_state(key="ollama_model")
        return OllamaClient(
            url=url if isinstance(url, str) and url else None,
            model=model if isinstance(model, str) and model else None,
        )

    def respond(
        self,
        user_text: str,
        *,
        conversation_id: str | None = None,
    ) -> ChatResponse:
        """Respond to user message with conversation context.

        Args:
            user_text: The user's message
            conversation_id: Optional conversation ID for context continuity.
                           If None, creates a new conversation.

        Returns:
            ChatResponse with answer and metadata
        """
        # SECURITY: Check for prompt injection attempts
        injection_check = detect_prompt_injection(user_text)
        if injection_check.is_suspicious:
            audit_log(
                AuditEventType.INJECTION_DETECTED,
                {
                    "patterns": injection_check.detected_patterns,
                    "confidence": injection_check.confidence,
                    "input_preview": user_text[:100],
                },
            )
            # Log warning but don't block - just sanitize and add extra caution
            logger.warning(
                "Potential prompt injection detected (confidence=%.2f): %s",
                injection_check.confidence,
                injection_check.detected_patterns,
            )
            # Use sanitized input for processing
            user_text = injection_check.sanitized_input

        # Get or create conversation
        if conversation_id is None:
            conversation_id = _generate_id()
            self._db.create_conversation(conversation_id=conversation_id)
        else:
            # Verify conversation exists, create if not
            conv = self._db.get_conversation(conversation_id=conversation_id)
            if conv is None:
                self._db.create_conversation(conversation_id=conversation_id)

        # Store user message
        user_message_id = _generate_id()
        self._db.add_message(
            message_id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            content=user_text,
            message_type="text",
        )

        # Route through reasoning engine for complex tasks
        reasoning_result = self._try_reasoning(user_text, conversation_id)
        if reasoning_result is not None:
            return reasoning_result

        tools = list_tools()

        persona = self._get_persona()
        temperature = float(persona.get("temperature") or 0.2)
        top_p = float(persona.get("top_p") or 0.9)
        tool_call_limit = int(persona.get("tool_call_limit") or 3)
        tool_call_limit = max(0, min(6, tool_call_limit))

        persona_system = str(persona.get("system_prompt") or "")
        persona_context = str(persona.get("default_context") or "")
        persona_prefix = persona_system
        if persona_context:
            persona_prefix = persona_prefix + "\n\n" + persona_context

        play_context = self._get_play_context()
        if play_context:
            persona_prefix = persona_prefix + "\n\n" + play_context

        # Add learned knowledge from previous compactions
        learned_context = self._get_learned_context()
        if learned_context:
            persona_prefix = persona_prefix + "\n\n" + learned_context

        # Add daily system state context (RAG)
        system_context = self._get_system_context()
        if system_context:
            persona_prefix = persona_prefix + "\n\n" + system_context

        # Add codebase self-awareness context
        codebase_context = self._get_codebase_context()
        if codebase_context:
            persona_prefix = persona_prefix + "\n\n" + codebase_context

        # Add conversation history context
        conversation_context = self._build_conversation_context(conversation_id)
        if conversation_context:
            persona_prefix = persona_prefix + "\n\n" + conversation_context

        ollama = self._get_ollama_client()

        wants_diff = self._user_opted_into_diff(user_text)

        tool_calls = self._select_tools(
            user_text=user_text,
            tools=tools,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
            tool_call_limit=tool_call_limit,
        )

        tool_results: list[dict[str, Any]] = []
        for call in tool_calls[:tool_call_limit]:
            try:
                if call.name == "reos_git_summary" and not wants_diff:
                    args = {k: v for k, v in call.arguments.items() if k != "include_diff"}
                    call = ToolCall(name=call.name, arguments=args)

                result = call_tool(self._db, name=call.name, arguments=call.arguments)
                tool_result = {
                    "tool": call.name,
                    "name": call.name,
                    "arguments": call.arguments,
                    "ok": True,
                    "result": result,
                    "timestamp": datetime.now().isoformat(),
                }
                tool_results.append(tool_result)
                # Track for certainty validation
                self._recent_tool_outputs.append(tool_result)
            except ToolError as exc:
                tool_results.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message, "data": exc.data},
                    }
                )

        # Keep only recent tool outputs (last 20)
        self._recent_tool_outputs = self._recent_tool_outputs[-20:]

        answer, thinking_steps = self._answer(
            user_text=user_text,
            tools=tools,
            tool_results=tool_results,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
        )

        # Validate response certainty
        try:
            certain_response = self._certainty.wrap_response(
                response=answer,
                system_state=self._steady_state.current if self._steady_state._current else None,
                tool_outputs=tool_results,
                user_input=user_text,
            )
            confidence = certain_response.overall_confidence
            evidence_summary = certain_response.evidence_summary
            has_uncertainties = certain_response.has_uncertainties()
        except Exception as e:
            logger.warning("Certainty validation failed: %s", e)
            confidence = 1.0
            evidence_summary = ""
            has_uncertainties = False

        # Store assistant response
        assistant_message_id = _generate_id()
        self._db.add_message(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            message_type="text",
            metadata=json.dumps({
                "tool_calls": tool_results,
                "thinking_steps": thinking_steps,
                "confidence": confidence,
                "evidence_summary": evidence_summary,
                "has_uncertainties": has_uncertainties,
            }) if tool_results or thinking_steps or confidence < 1.0 else None,
        )

        # Generate title for new conversations (first message)
        messages = self._db.get_messages(conversation_id=conversation_id, limit=3)
        if len(messages) <= 2:  # Just the user message and assistant response
            title = user_text[:50] + ("..." if len(user_text) > 50 else "")
            self._db.update_conversation_title(conversation_id=conversation_id, title=title)

        return ChatResponse(
            answer=answer,
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            message_type="text",
            tool_calls=tool_results,
            thinking_steps=thinking_steps,
            confidence=confidence,
            evidence_summary=evidence_summary,
            has_uncertainties=has_uncertainties,
        )

    def respond_text(self, user_text: str) -> str:
        """Simple text-only response (backwards compatibility)."""
        response = self.respond(user_text)
        return response.answer

    def _build_conversation_context(self, conversation_id: str) -> str:
        """Build conversation history context for LLM."""
        # Get recent messages (excluding current - it will be added separately)
        messages = self._db.get_recent_messages(conversation_id=conversation_id, limit=10)

        if len(messages) <= 1:  # Only current message or empty
            return ""

        # Format as conversation history (exclude last message which is the current user message)
        history_messages = messages[:-1]
        if not history_messages:
            return ""

        lines = ["CONVERSATION HISTORY:"]
        for msg in history_messages:
            role = str(msg.get("role", "")).upper()
            content = str(msg.get("content", ""))
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _get_system_context(self) -> str:
        """Get system state context for RAG with certainty and quality rules.

        Uses SteadyStateCollector for comprehensive system knowledge,
        formatted with certainty rules to prevent hallucination and
        quality commitment rules to ensure engineering excellence.
        """
        try:
            # Get steady state context (cached, refreshed if stale)
            steady_state = self._steady_state.refresh_if_stale(max_age_seconds=3600)
            context = steady_state.to_context_string()

            # Add certainty rules to prevent hallucination
            certainty_context = create_certainty_prompt_addition(context)

            # Add quality commitment rules for engineering excellence
            quality_context = create_quality_prompt_addition()

            return certainty_context + "\n\n" + quality_context
        except Exception as e:
            logger.warning("Failed to get system context: %s", e)
            # Fallback to basic context
            try:
                return get_system_context(self._db)
            except Exception:
                return ""

    def _get_system_snapshot_for_reasoning(self) -> dict[str, Any]:
        """Get system snapshot as structured data for the reasoning engine.

        Returns a dict with containers, services, and other system state
        that the planner can use to resolve references like "the redis container".
        """
        from .system_index import SystemIndexer

        try:
            indexer = SystemIndexer(self._db)

            # Get or create today's snapshot
            if indexer.needs_refresh():
                snapshot = indexer.capture_snapshot()
            else:
                snapshot = indexer.get_latest_snapshot()

            if snapshot is None:
                return {}

            # Extract structured data for reasoning
            context: dict[str, Any] = {
                "hostname": snapshot.hostname,
                "os": snapshot.os_info,
                "hardware": snapshot.hardware,
            }

            # Containers - key for Docker operations
            if snapshot.containers:
                context["containers"] = {
                    "runtime": snapshot.containers.get("runtime"),
                    "running": snapshot.containers.get("running_containers", []),
                    "all": snapshot.containers.get("all_containers", []),
                    "images": snapshot.containers.get("images", []),
                }
                # Build name lookup for easy resolution
                context["container_names"] = [
                    c.get("name", c.get("id", ""))
                    for c in snapshot.containers.get("all_containers", [])
                ]

            # Services - key for systemd operations
            if snapshot.services:
                context["services"] = snapshot.services
                context["service_names"] = [s.get("name", "") for s in snapshot.services]

            # Packages
            if snapshot.packages:
                context["package_manager"] = snapshot.packages.get("manager")
                context["installed_packages"] = snapshot.packages.get("installed", [])

            # Storage
            if snapshot.storage:
                context["storage"] = snapshot.storage

            return context

        except Exception as e:
            logging.getLogger(__name__).debug("Could not get system snapshot: %s", e)
            return {}

    def _get_play_context(self) -> str:
        """Build context from The Play hierarchy.

        Context structure:
        - README (always included - app identity and documentation)
        - The Play (always included - user's story and identity)
        - Selected Act + all its Scenes and Beats (if an act is selected)
        """
        from pathlib import Path
        from .play_fs import (
            play_root,
            list_scenes,
            list_beats,
            kb_read,
            list_attachments,
        )

        ctx_parts: list[str] = []

        # 1. README - Always in context (app identity and documentation)
        try:
            readme_path = Path(__file__).parent.parent.parent / "README.md"
            if readme_path.exists():
                readme_content = readme_path.read_text(encoding="utf-8").strip()
                # Cap README to reasonable size
                cap = 4000
                if len(readme_content) > cap:
                    readme_content = readme_content[:cap] + "\n…"
                ctx_parts.append(f"REOS_README:\n{readme_content}")
        except Exception:  # noqa: BLE001
            pass

        # 2. The Play - Always in context (user's story)
        try:
            me = play_read_me_markdown().strip()
            if me:
                cap = 2000
                if len(me) > cap:
                    me = me[:cap] + "\n…"
                ctx_parts.append(
                    f"THE_PLAY (About the USER - the person you serve, NOT the computer):\n"
                    f"Use this to answer questions about 'me', 'myself', 'my goals', etc.\n"
                    f"{me}"
                )

            # Play-level attachments
            play_attachments = list_attachments()
            if play_attachments:
                att_list = ", ".join(f"{a.file_name} ({a.file_type})" for a in play_attachments)
                ctx_parts.append(f"PLAY_ATTACHMENTS: {att_list}")
        except Exception:  # noqa: BLE001
            pass

        # 3. Selected Act and its hierarchy
        try:
            acts, active_id = play_list_acts()
        except Exception:  # noqa: BLE001
            return "\n\n".join(ctx_parts)

        if not active_id:
            if ctx_parts:
                ctx_parts.append("NO_ACTIVE_ACT: User has not selected an Act to focus on.")
            return "\n\n".join(ctx_parts)

        act = next((a for a in acts if a.act_id == active_id), None)
        if act is None:
            return "\n\n".join(ctx_parts)

        # Act context
        act_ctx = f"ACTIVE_ACT: {act.title} (selected = in context with all Scenes & Beats)"
        if act.notes.strip():
            act_ctx += f"\nACT_NOTES: {act.notes.strip()}"

        # Act KB
        try:
            act_kb = kb_read(act_id=active_id, path="kb.md")
            if act_kb.strip():
                cap = 1500
                if len(act_kb) > cap:
                    act_kb = act_kb[:cap] + "\n…"
                act_ctx += f"\nACT_KB:\n{act_kb.strip()}"
        except Exception:  # noqa: BLE001
            pass

        # Act attachments
        try:
            act_attachments = list_attachments(act_id=active_id)
            if act_attachments:
                att_list = ", ".join(f"{a.file_name} ({a.file_type})" for a in act_attachments)
                act_ctx += f"\nACT_ATTACHMENTS: {att_list}"
        except Exception:  # noqa: BLE001
            pass

        ctx_parts.append(act_ctx)

        # Scenes under active act
        try:
            scenes = list_scenes(act_id=active_id)
            for scene in scenes:
                scene_ctx = f"  SCENE: {scene.title}"
                if scene.intent:
                    scene_ctx += f" | Intent: {scene.intent}"
                if scene.status:
                    scene_ctx += f" | Status: {scene.status}"
                if scene.notes and scene.notes.strip():
                    scene_ctx += f"\n    Notes: {scene.notes.strip()[:500]}"

                # Scene attachments
                try:
                    scene_attachments = list_attachments(act_id=active_id, scene_id=scene.scene_id)
                    if scene_attachments:
                        att_list = ", ".join(f"{a.file_name}" for a in scene_attachments)
                        scene_ctx += f"\n    Attachments: {att_list}"
                except Exception:  # noqa: BLE001
                    pass

                ctx_parts.append(scene_ctx)

                # Beats under scene
                try:
                    beats = list_beats(act_id=active_id, scene_id=scene.scene_id)
                    for beat in beats:
                        beat_ctx = f"    BEAT: {beat.title}"
                        if beat.status:
                            beat_ctx += f" | Status: {beat.status}"
                        if beat.notes and beat.notes.strip():
                            beat_ctx += f"\n      Notes: {beat.notes.strip()[:300]}"
                        ctx_parts.append(beat_ctx)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

        return "\n\n".join(ctx_parts)

    def _get_learned_context(self) -> str:
        """Get learned knowledge from previous compactions.

        This injects facts, lessons, decisions, and preferences that the AI
        has learned from past conversations with this user.
        """
        try:
            from .knowledge_store import KnowledgeStore
            from .play_fs import list_acts as play_list_acts

            # Get active act
            acts, active_act_id = play_list_acts()

            store = KnowledgeStore()
            learned_md = store.get_learned_markdown(active_act_id)

            if learned_md.strip():
                return (
                    "LEARNED_KNOWLEDGE (from previous conversations):\n"
                    "Use this to personalize responses and remember user preferences.\n"
                    f"{learned_md}"
                )
            return ""
        except Exception as e:
            logger.debug("Could not load learned knowledge: %s", e)
            return ""

    def _get_codebase_context(self) -> str:
        """Get codebase self-awareness context.

        This allows ReOS to answer questions about its own implementation,
        architecture, and source code structure.
        """
        try:
            from .codebase_index import get_codebase_context as get_codebase_ctx

            codebase_ctx = get_codebase_ctx()
            if codebase_ctx.strip():
                return (
                    "CODEBASE_REFERENCE (ReOS source code structure):\n"
                    "Use this to answer questions about how ReOS works, "
                    "its architecture, modules, and implementation.\n"
                    f"{codebase_ctx}"
                )
            return ""
        except Exception as e:
            logger.debug("Could not load codebase context: %s", e)
            return ""

    def _user_opted_into_diff(self, user_text: str) -> bool:
        t = user_text.lower()
        return any(
            phrase in t
            for phrase in [
                "include diff",
                "show diff",
                "full diff",
                "git diff",
                "patch",
                "unified diff",
            ]
        )

    def detect_intent(self, user_text: str) -> DetectedIntent | None:
        """Detect conversational intent from short user responses.

        Returns:
            DetectedIntent if a special intent is detected, None for normal questions.
        """
        text = user_text.strip()

        # Check for approval
        if _APPROVAL_PATTERN.match(text):
            return DetectedIntent(intent_type="approval")

        # Check for rejection
        if _REJECTION_PATTERN.match(text):
            return DetectedIntent(intent_type="rejection")

        # Check for numeric choice (1-9)
        numeric_match = _NUMERIC_CHOICE_PATTERN.match(text)
        if numeric_match:
            return DetectedIntent(
                intent_type="choice",
                choice_number=int(numeric_match.group(1)),
            )

        # Check for ordinal choice (first, second, etc.)
        ordinal_match = _ORDINAL_PATTERN.match(text)
        if ordinal_match:
            ordinal = ordinal_match.group(1).lower()
            return DetectedIntent(
                intent_type="choice",
                choice_number=_ORDINAL_MAP.get(ordinal, 1),
            )

        # Check for references (it, that, the service, etc.)
        reference_match = _REFERENCE_PATTERN.search(text)
        if reference_match and len(text) < 100:  # Short messages with references
            return DetectedIntent(
                intent_type="reference",
                reference_term=reference_match.group(1).lower(),
            )

        return None

    def resolve_reference(
        self,
        reference_term: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Resolve a reference term (it, that, etc.) from conversation context.

        Returns:
            Dict with resolved entity info, or None if cannot resolve.
        """
        # Get recent messages to find what "it" refers to
        messages = self._db.get_recent_messages(conversation_id=conversation_id, limit=5)

        if not messages:
            return None

        # Look for entities in recent assistant messages
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue

            content = str(msg.get("content", ""))
            metadata_str = msg.get("metadata")

            # Check tool calls in metadata for services/containers
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                    tool_calls = metadata.get("tool_calls", [])
                    for tc in tool_calls:
                        if not tc.get("ok"):
                            continue
                        result = tc.get("result", {})

                        # Service mentioned
                        if "service" in reference_term or "service" in str(tc.get("name", "")):
                            if isinstance(result, dict) and "name" in result:
                                return {"type": "service", "name": result["name"]}

                        # Container mentioned
                        if "container" in reference_term or "container" in str(tc.get("name", "")):
                            if isinstance(result, dict) and ("id" in result or "name" in result):
                                return {
                                    "type": "container",
                                    "id": result.get("id"),
                                    "name": result.get("name"),
                                }

                        # File mentioned
                        if "file" in reference_term:
                            if isinstance(result, dict) and "path" in result:
                                return {"type": "file", "path": result["path"]}

                except (json.JSONDecodeError, TypeError):
                    pass

            # Simple text matching for common patterns
            patterns = [
                (r"service[:\s]+([a-zA-Z0-9_-]+)", "service"),
                (r"container[:\s]+([a-zA-Z0-9_-]+)", "container"),
                (r"`([^`]+\.service)`", "service"),
                (r"package[:\s]+([a-zA-Z0-9_-]+)", "package"),
            ]

            for pattern, entity_type in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return {"type": entity_type, "name": match.group(1)}

        return None

    def get_pending_approval_for_conversation(
        self,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Get the most recent pending approval for a conversation."""
        approvals = self._db.get_pending_approvals()
        for approval in approvals:
            if approval.get("conversation_id") == conversation_id:
                return approval
        return None

    def _select_tools(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
        tool_call_limit: int,
    ) -> list[ToolCall]:
        # Simplified tool specs - just names and short descriptions
        # Full schemas overwhelm smaller models
        tool_specs = [
            {
                "name": t.name,
                "description": t.description[:100] if t.description else "",
            }
            for t in tools
        ]

        system = (
            persona_prefix
            + "\n\n"
            + "You are deciding which tools to call to answer the user.\n\n"
            + "CRITICAL - PERSONAL vs SYSTEM QUESTIONS:\n"
            + "- Questions about 'me', 'myself', 'my goals', 'what do you know about me' = PERSONAL\n"
            + "- For PERSONAL questions: Return EMPTY tool_calls []. Use THE_PLAY context instead!\n"
            + "- Questions about 'this machine', 'CPU', 'memory', 'services', 'containers' = SYSTEM\n"
            + "- For SYSTEM questions: Use appropriate tools below\n\n"
            + "SYSTEM TOOLS (only for computer/hardware questions):\n"
            + "- linux_system_info: CPU, memory, disk, uptime (NOT for personal info!)\n"
            + "- linux_list_services: Systemd services\n"
            + "- linux_docker_containers: Docker containers\n"
            + "- reos_git_summary: Git repository info\n"
            + "- linux_run_command: Execute shell commands (docker, apt, systemctl)\n\n"
            + "RULES:\n"
            + "- When user says 'yes', 'proceed', 'do it': USE linux_run_command to execute\n"
            + "- linux_run_command takes {\"command\": \"shell command\"}\n"
            + f"- Call 0-{tool_call_limit} tools. Empty is OK for personal questions!\n\n"
            + "Return JSON:\n"
            + "{\"tool_calls\": [{\"name\": \"tool_name\", \"arguments\": {}}]}\n"
            + "OR for personal questions:\n"
            + "{\"tool_calls\": []}\n"
        )

        user = (
            "TOOLS:\n" + json.dumps(tool_specs, indent=2) + "\n\n" +
            "USER_MESSAGE:\n" + user_text + "\n\n" +
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n"
        )

        raw = ollama.chat_json(system=system, user=user, temperature=temperature, top_p=top_p)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: return empty - don't assume system tools
            return []

        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return []

        out: list[ToolCall] = []
        valid_tool_names = {t.name for t in tools}

        for c in calls:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            args = c.get("arguments") or {}  # Default to empty dict if missing

            if not isinstance(name, str):
                continue
            if not isinstance(args, dict):
                args = {}

            # Map common LLM mistakes to actual tool names
            name_mapping = {
                "uptime": "linux_system_info",
                "system_info": "linux_system_info",
                "services": "linux_list_services",
                "list_services": "linux_list_services",
                "run_command": "linux_run_command",
                "run": "linux_run_command",
                "packages": "linux_list_packages",
                "docker": "linux_docker_containers",
                "containers": "linux_docker_containers",
                "list_docker_containers": "linux_docker_containers",
                "docker_containers": "linux_docker_containers",
                "git_summary": "reos_git_summary",
                "git": "reos_git_summary",
            }
            if name in name_mapping:
                name = name_mapping[name]

            # Only add if it's a valid tool
            if name in valid_tool_names:
                out.append(ToolCall(name=name, arguments=args))

        return out

    def _answer(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        tool_results: list[dict[str, Any]],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
    ) -> tuple[str, list[str]]:
        """Generate answer with optional thinking steps.

        Returns:
            Tuple of (answer, thinking_steps)
        """
        tool_dump = []
        for r in tool_results:
            rendered = render_tool_result(r.get("result")) if r.get("ok") else json.dumps(r.get("error"), indent=2)
            tool_dump.append(
                {
                    "name": r.get("name"),
                    "arguments": r.get("arguments"),
                    "ok": r.get("ok"),
                    "output": rendered,
                }
            )

        system = (
            persona_prefix
            + "\n\n"
            + "Answer the user's question.\n\n"
            + "INFORMATION SOURCES (in order of priority):\n"
            + "1. THE_PLAY context above - Contains info about the USER as a person (their story, goals, identity)\n"
            + "2. Tool outputs below - Contains info about the SYSTEM (computer, services, containers)\n"
            + "3. Conversation history - Previous messages in this chat\n\n"
            + "IMPORTANT:\n"
            + "- For personal questions ('about me', 'my goals'), THE_PLAY context IS your source - you already have it!\n"
            + "- Empty tool outputs is NORMAL for personal questions - don't say you lack information\n"
            + "- For system questions, use the tool outputs\n\n"
            + "RESPONSE FORMAT:\n"
            + "Use this exact format to separate your reasoning from your answer:\n\n"
            + "<thinking>\n"
            + "Your internal reasoning process here. What you're checking, what you found, etc.\n"
            + "Each distinct thought should be on its own line.\n"
            + "</thinking>\n\n"
            + "<answer>\n"
            + "Your final response to the user here. Clear, direct, helpful.\n"
            + "</answer>\n\n"
            + "Rules:\n"
            + "- Always use <thinking> and <answer> tags\n"
            + "- Put reasoning/checking/searching in <thinking>\n"
            + "- Put the final user-facing response in <answer>\n"
            + "- Be personal and direct - you know this user from THE_PLAY\n"
            + "- If THE_PLAY is empty for a personal question, suggest they fill out 'Your Story' in The Play\n"
            + "- Do not fabricate information; use what's in your context\n"
        )

        user = (
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n\n"
            "USER_MESSAGE:\n" + user_text + "\n\n"
            "TOOL_RESULTS:\n" + json.dumps(tool_dump, indent=2, ensure_ascii=False)
        )

        raw = ollama.chat_text(system=system, user=user, temperature=temperature, top_p=top_p)
        return self._parse_thinking_answer(raw)

    def _parse_thinking_answer(self, raw: str) -> tuple[str, list[str]]:
        """Parse response with thinking tags from various formats.

        Supports:
        - <thinking>...</thinking> - ReOS prompted format
        - <think>...</think> - Native thinking models (DeepSeek-R1, QWQ)
        - <answer>...</answer> - ReOS prompted answer format

        Returns:
            Tuple of (answer, thinking_steps)
        """
        import re

        thinking_steps: list[str] = []
        answer = raw.strip()

        # Extract thinking section - check both formats
        # First try <think> (native thinking models like DeepSeek-R1, QWQ)
        thinking_match = re.search(r"<think>(.*?)</think>", raw, re.DOTALL | re.IGNORECASE)
        if not thinking_match:
            # Fall back to <thinking> (ReOS prompted format)
            thinking_match = re.search(r"<thinking>(.*?)</thinking>", raw, re.DOTALL | re.IGNORECASE)

        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            # Split into individual steps (by line or sentence)
            steps = [s.strip() for s in thinking_content.split("\n") if s.strip()]
            thinking_steps = steps

        # Extract answer section
        answer_match = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL | re.IGNORECASE)
        if answer_match:
            answer = answer_match.group(1).strip()
        else:
            # Fallback: remove thinking tags and use the rest
            # Remove both <think> and <thinking> variants
            answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            answer = re.sub(r"<thinking>.*?</thinking>", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()
            # Also remove any leftover tags
            answer = re.sub(r"</?(?:think|thinking|answer)>", "", answer, flags=re.IGNORECASE).strip()

        return answer, thinking_steps
