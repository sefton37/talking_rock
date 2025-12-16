from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Event(BaseModel):
    source: str = Field(..., description="Event origin (e.g., vscode, copilot, git)")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload_metadata: dict[str, Any] | None = Field(
        default=None, description="Metadata only; no content bodies."
    )
    note: str | None = Field(
        default=None, description="Optional human-readable note; avoid content dumps."
    )


class EventIngestResponse(BaseModel):
    stored: bool
    event_id: str


class Reflection(BaseModel):
    message: str
    switches_last_window: int
    window_minutes: int


class ReflectionsResponse(BaseModel):
    reflections: list[Reflection]
    events_seen: int


class OllamaHealthResponse(BaseModel):
    reachable: bool
    model_count: int | None = None
    error: str | None = None
