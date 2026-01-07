"""Anthropic Provider - Claude API integration.

Implements LLMProvider protocol for Anthropic's Claude models.
Requires an API key stored in the system keyring.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .base import LLMError, LLMProvider, ModelInfo, ProviderHealth

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = logging.getLogger(__name__)


# =============================================================================
# Available Claude Models
# =============================================================================

CLAUDE_MODELS: list[ModelInfo] = [
    ModelInfo(
        name="claude-sonnet-4-20250514",
        context_length=200000,
        capabilities=["tools", "vision"],
        description="Fast, cost-effective model for most tasks",
    ),
    ModelInfo(
        name="claude-opus-4-5-20251101",
        context_length=200000,
        capabilities=["tools", "vision"],
        description="Most capable model for complex tasks",
    ),
    ModelInfo(
        name="claude-haiku-3-5-20241022",
        context_length=200000,
        capabilities=["tools", "vision"],
        description="Fastest, most economical model",
    ),
]

DEFAULT_MODEL = "claude-sonnet-4-20250514"


# =============================================================================
# Anthropic Provider
# =============================================================================


class AnthropicProvider:
    """LLM Provider implementation for Anthropic Claude.

    Uses the Anthropic Python SDK for API access.
    API key should be stored in system keyring via secrets module.

    Example:
        from reos.providers.secrets import get_api_key
        api_key = get_api_key("anthropic")
        provider = AnthropicProvider(api_key=api_key)
        response = provider.chat_text(
            system="You are helpful.",
            user="Hello!",
        )
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key. If None, will attempt to get from keyring.
            model: Model to use. Defaults to claude-sonnet-4-20250514.

        Raises:
            LLMError: If anthropic library not installed or no API key provided.
        """
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._client: Anthropic | None = None

    @property
    def provider_type(self) -> str:
        """Provider identifier."""
        return "anthropic"

    def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate plain text response."""
        client = self._get_client()

        try:
            # Build request kwargs
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 4096,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }

            if temperature is not None:
                kwargs["temperature"] = temperature
            if top_p is not None:
                kwargs["top_p"] = top_p

            # Make request with timeout
            with client.messages.with_options(timeout=timeout_seconds) as messages:
                response = messages.create(**kwargs)

            # Extract text content
            content = response.content
            if content and len(content) > 0:
                text_block = content[0]
                if hasattr(text_block, "text"):
                    return text_block.text.strip()

            raise LLMError("Unexpected Anthropic response: no text content")

        except Exception as e:
            if "anthropic" in str(type(e).__module__).lower():
                raise LLMError(f"Anthropic API error: {e}") from e
            raise LLMError(f"Request failed: {e}") from e

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate JSON-formatted response.

        Note: Claude doesn't have a native JSON mode like Ollama.
        We instruct the model to respond in JSON format via the prompt.
        """
        # Enhance system prompt to request JSON
        json_system = f"{system}\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, just the JSON object."

        response = self.chat_text(
            system=json_system,
            user=user,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
        )

        # Strip any markdown code blocks if present
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        # Validate JSON
        try:
            json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning("Anthropic returned invalid JSON: %s", e)
            # Return as-is, let caller handle

        return response.strip()

    def list_models(self) -> list[ModelInfo]:
        """List available Claude models."""
        return CLAUDE_MODELS.copy()

    def check_health(self) -> ProviderHealth:
        """Check Anthropic API connectivity."""
        if not self._api_key:
            return ProviderHealth(
                reachable=False,
                error="No API key configured",
            )

        try:
            # Try to create client and make a minimal request
            client = self._get_client()

            # Use a minimal request to verify connectivity
            # The models.list() endpoint is lightweight
            with client.messages.with_options(timeout=5.0) as messages:
                response = messages.create(
                    model=self._model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "hi"}],
                )
                _ = response  # Just checking it succeeds

            return ProviderHealth(
                reachable=True,
                model_count=len(CLAUDE_MODELS),
                current_model=self._model,
            )

        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                error_msg = "Invalid API key"
            elif "rate" in error_msg.lower():
                error_msg = "Rate limited - try again later"

            return ProviderHealth(
                reachable=False,
                error=error_msg,
            )

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    def _get_client(self) -> "Anthropic":
        """Get or create the Anthropic client."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            # Try to get from keyring
            try:
                from .secrets import get_api_key

                self._api_key = get_api_key("anthropic")
            except Exception as e:
                logger.debug("Failed to get Anthropic API key from keyring: %s", e)

        if not self._api_key:
            raise LLMError(
                "No Anthropic API key configured. "
                "Add your key in Settings > LLM Provider."
            )

        try:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key)
            return self._client
        except ImportError as e:
            raise LLMError(
                "anthropic library not installed. "
                "Run: pip install anthropic"
            ) from e


def check_anthropic_available() -> bool:
    """Check if the anthropic library is installed."""
    try:
        import anthropic  # noqa: F401

        return True
    except ImportError:
        return False


# Type assertion to verify protocol compliance
def _check_protocol() -> None:
    """Verify AnthropicProvider implements LLMProvider protocol."""
    provider: LLMProvider = AnthropicProvider(api_key="test")
    _ = provider  # noqa: F841
