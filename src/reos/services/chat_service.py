"""Chat Service - Unified chat functionality for CLI and RPC.

Provides a consistent interface for chat operations regardless of
the calling interface (CLI or Tauri RPC).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..agent import ChatAgent, ChatResponse
from ..db import Database
from ..ollama import OllamaClient

logger = logging.getLogger(__name__)


@dataclass
class ChatRequest:
    """Request to send a chat message."""

    message: str
    conversation_id: str | None = None
    model_id: str | None = None


@dataclass
class ChatResult:
    """Result from a chat operation."""

    answer: str
    conversation_id: str
    message_id: str
    message_type: str = "text"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    thinking_steps: list[str] = field(default_factory=list)
    pending_approval_id: str | None = None
    confidence: float = 1.0
    evidence_summary: str = ""
    has_uncertainties: bool = False
    intent_handled: str | None = None

    @classmethod
    def from_chat_response(cls, response: ChatResponse) -> ChatResult:
        """Convert ChatAgent response to ChatResult."""
        return cls(
            answer=response.answer,
            conversation_id=response.conversation_id,
            message_id=response.message_id,
            message_type=response.message_type,
            tool_calls=response.tool_calls,
            thinking_steps=response.thinking_steps,
            pending_approval_id=response.pending_approval_id,
            confidence=response.confidence,
            evidence_summary=response.evidence_summary,
            has_uncertainties=response.has_uncertainties,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for RPC responses."""
        return {
            "answer": self.answer,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "tool_calls": self.tool_calls,
            "thinking_steps": self.thinking_steps,
            "pending_approval_id": self.pending_approval_id,
            "confidence": self.confidence,
            "evidence_summary": self.evidence_summary,
            "has_uncertainties": self.has_uncertainties,
            "intent_handled": self.intent_handled,
        }


@dataclass
class ModelInfo:
    """Information about an available model."""

    id: str
    name: str
    size: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    is_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "capabilities": self.capabilities,
            "is_current": self.is_current,
        }


class ChatService:
    """Unified chat service for both CLI and RPC interfaces."""

    def __init__(self, db: Database):
        self._db = db
        self._agent: ChatAgent | None = None

    def _get_agent(self) -> ChatAgent:
        """Get or create the ChatAgent instance."""
        if self._agent is None:
            self._agent = ChatAgent(db=self._db)
        return self._agent

    def respond(
        self,
        request: ChatRequest,
        *,
        on_approval_needed: Callable[[dict[str, Any]], bool] | None = None,
    ) -> ChatResult:
        """Process a chat message and return the response.

        Args:
            request: The chat request containing message and optional conversation ID
            on_approval_needed: Optional callback for handling approval requests.
                               If None, approvals are handled asynchronously.

        Returns:
            ChatResult with the response and metadata
        """
        agent = self._get_agent()

        # Check for conversational intents (approval, rejection, references)
        if request.conversation_id:
            intent = agent.detect_intent(request.message)

            if intent:
                # Handle approval/rejection
                if intent.intent_type in ("approval", "rejection"):
                    pending = agent.get_pending_approval_for_conversation(
                        request.conversation_id
                    )
                    if pending:
                        # If we have a callback, let the caller handle it
                        if on_approval_needed and intent.intent_type == "approval":
                            approved = on_approval_needed(pending)
                            if not approved:
                                intent = intent._replace(intent_type="rejection")

                        # Return intent-handled result
                        return self._handle_approval_intent(
                            request.conversation_id,
                            pending,
                            intent.intent_type == "approval",
                        )

                # Handle reference resolution
                if intent.intent_type == "reference" and intent.reference_term:
                    resolved = agent.resolve_reference(
                        intent.reference_term, request.conversation_id
                    )
                    if resolved:
                        # Expand the text to include resolved entity
                        request = ChatRequest(
                            message=request.message.replace(
                                intent.reference_term,
                                f"{intent.reference_term} ({resolved.get('type', '')}: {resolved.get('name', resolved.get('id', ''))})",
                            ),
                            conversation_id=request.conversation_id,
                            model_id=request.model_id,
                        )

        # Normal chat response
        response = agent.respond(
            request.message,
            conversation_id=request.conversation_id,
        )

        return ChatResult.from_chat_response(response)

    def _handle_approval_intent(
        self,
        conversation_id: str,
        pending: dict[str, Any],
        approved: bool,
    ) -> ChatResult:
        """Handle approval/rejection intent for a pending command."""
        from ..linux_tools import execute_command
        import uuid

        message_id = uuid.uuid4().hex[:12]

        if approved:
            # Execute the command
            command = pending.get("command", "")
            try:
                result = execute_command(command)
                answer = f"Command executed. Return code: {result.get('return_code', 'unknown')}"
                if result.get("stdout"):
                    answer += f"\n\nOutput:\n{result['stdout'][:500]}"
                if result.get("stderr"):
                    answer += f"\n\nErrors:\n{result['stderr'][:500]}"
            except Exception as e:
                answer = f"Command execution failed: {e}"

            # Update approval status
            self._db.update_approval(
                approval_id=str(pending["id"]),
                status="approved",
            )
        else:
            answer = "Command rejected."
            self._db.update_approval(
                approval_id=str(pending["id"]),
                status="rejected",
            )

        # Store the response
        self._db.add_message(
            message_id=message_id,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            message_type="text",
        )

        return ChatResult(
            answer=answer,
            conversation_id=conversation_id,
            message_id=message_id,
            message_type="text",
            intent_handled="approval" if approved else "rejection",
        )

    def detect_intent(
        self,
        text: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect intent from user input.

        Returns:
            Dict with intent information or {"detected": False}
        """
        agent = self._get_agent()
        intent = agent.detect_intent(text)

        if not intent:
            return {"detected": False}

        result: dict[str, Any] = {
            "detected": True,
            "intent_type": intent.intent_type,
            "confidence": intent.confidence,
        }

        if intent.choice_number is not None:
            result["choice_number"] = intent.choice_number

        if intent.reference_term:
            result["reference_term"] = intent.reference_term
            if conversation_id:
                resolved = agent.resolve_reference(intent.reference_term, conversation_id)
                if resolved:
                    result["resolved_entity"] = resolved

        return result

    def list_models(self) -> list[ModelInfo]:
        """List available models from Ollama.

        Returns:
            List of ModelInfo with capabilities and current status
        """
        try:
            from ..ollama import list_ollama_models

            ollama_url = self._db.get_state(key="ollama_url")
            url = ollama_url if isinstance(ollama_url, str) and ollama_url else None

            model_names = list_ollama_models(url=url)
            current_model = self._db.get_state(key="ollama_model") or "qwen2.5:7b"
            models = []

            for name in model_names:
                # Parse model info
                info = ModelInfo(
                    id=name,
                    name=name.split(":")[0] if ":" in name else name,
                    size="unknown",
                    capabilities=self._infer_capabilities(name, {}),
                    is_current=(name == current_model),
                )
                models.append(info)

            return models

        except Exception as e:
            logger.warning("Failed to list models: %s", e)
            return []

    def set_model(self, model_id: str) -> bool:
        """Set the active model.

        Args:
            model_id: The model identifier (e.g., "qwen2.5:7b")

        Returns:
            True if model was set successfully
        """
        try:
            # Verify model exists
            models = self.list_models()
            if not any(m.id == model_id for m in models):
                logger.warning("Model not found: %s", model_id)
                return False

            self._db.set_state(key="ollama_model", value=model_id)

            # Reset agent to use new model
            self._agent = None

            logger.info("Model set to: %s", model_id)
            return True

        except Exception as e:
            logger.error("Failed to set model: %s", e)
            return False

    def get_current_model(self) -> str | None:
        """Get the currently active model ID."""
        model = self._db.get_state(key="ollama_model")
        return model if isinstance(model, str) else None

    def _get_ollama_client(self) -> OllamaClient:
        """Get configured Ollama client."""
        url = self._db.get_state(key="ollama_url")
        model = self._db.get_state(key="ollama_model")
        return OllamaClient(
            url=url if isinstance(url, str) and url else None,
            model=model if isinstance(model, str) and model else None,
        )

    def _infer_capabilities(
        self, name: str, model_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Infer model capabilities from name and metadata."""
        name_lower = name.lower()

        caps: dict[str, Any] = {
            "chat": True,
            "tools": False,
            "thinking": False,
            "vision": False,
            "code": False,
        }

        # Detect tool-capable models
        if any(x in name_lower for x in ["qwen", "llama3", "mistral", "codestral"]):
            caps["tools"] = True

        # Detect thinking models
        if any(x in name_lower for x in ["deepseek-r1", "qwq", "thinking"]):
            caps["thinking"] = True

        # Detect vision models
        if any(x in name_lower for x in ["llava", "vision", "bakllava"]):
            caps["vision"] = True

        # Detect code models
        if any(x in name_lower for x in ["code", "starcoder", "deepseek-coder", "codestral"]):
            caps["code"] = True

        return caps

    # --- Conversation Management ---

    def start_conversation(self, title: str | None = None) -> str:
        """Start a new conversation.

        Returns:
            The new conversation ID
        """
        import uuid

        conversation_id = uuid.uuid4().hex[:12]
        self._db.create_conversation(conversation_id=conversation_id, title=title)
        return conversation_id

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent conversations.

        Returns:
            List of conversation metadata dicts
        """
        conversations = self._db.iter_conversations(limit=limit)
        return [
            {
                "id": str(c.get("id")),
                "title": c.get("title"),
                "started_at": c.get("started_at"),
                "last_active_at": c.get("last_active_at"),
            }
            for c in conversations
        ]

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages from a conversation.

        Returns:
            List of message dicts
        """
        messages = self._db.get_messages(conversation_id=conversation_id, limit=limit)
        return [
            {
                "id": str(m.get("id")),
                "role": m.get("role"),
                "content": m.get("content"),
                "message_type": m.get("message_type"),
                "metadata": m.get("metadata"),
                "created_at": m.get("created_at"),
            }
            for m in messages
        ]

    def clear_conversation(self, conversation_id: str) -> bool:
        """Clear all messages from a conversation.

        Returns:
            True if successful
        """
        try:
            self._db.clear_messages(conversation_id=conversation_id)
            return True
        except Exception as e:
            logger.error("Failed to clear conversation: %s", e)
            return False
