from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    method: str
    path: str
    privacy: str


def list_tools() -> list[ToolSpec]:
    """Local tool registry.

    This is *not* MCP yet; it’s a stable internal catalog that we can later expose
    through an MCP server implementation.
    """

    return [
        ToolSpec(
            name="health",
            description="Check local service health.",
            method="GET",
            path="/health",
            privacy="local-only",
        ),
        ToolSpec(
            name="ingest_event",
            description="Ingest a metadata-only event (e.g., from VS Code).",
            method="POST",
            path="/events",
            privacy="metadata-only by default",
        ),
        ToolSpec(
            name="reflections",
            description="Get reflective summaries derived from stored events.",
            method="GET",
            path="/reflections",
            privacy="local-only",
        ),
        ToolSpec(
            name="ollama_health",
            description="Verify local Ollama connectivity without sending content.",
            method="GET",
            path="/ollama/health",
            privacy="local-only; no prompt content",
        ),
    ]
