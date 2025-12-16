from __future__ import annotations

from dataclasses import dataclass

import httpx

from .settings import settings


@dataclass(frozen=True)
class OllamaHealth:
    reachable: bool
    model_count: int | None
    error: str | None


def check_ollama(timeout_seconds: float = 1.5) -> OllamaHealth:
    """Check local Ollama availability.

    Privacy: does not send any user content; only hits the local tags endpoint.
    """

    url = settings.ollama_url.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            res = client.get(url)
            res.raise_for_status()
            payload = res.json()
            models = payload.get("models") or []
            return OllamaHealth(reachable=True, model_count=len(models), error=None)
    except Exception as exc:  # noqa: BLE001
        return OllamaHealth(reachable=False, model_count=None, error=str(exc))
