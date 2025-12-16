from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from .models import (
    Event,
    EventIngestResponse,
    HealthResponse,
    OllamaHealthResponse,
    Reflection,
    ReflectionsResponse,
)
from .ollama import check_ollama
from .storage import append_event, iter_events
from .tools import list_tools

app = FastAPI(
    title="ReOS Local Kernel",
    version="0.0.0a0",
    description=(
        "Local-only attention kernel scaffold. No cloud calls. "
        "Mirrors events to local storage and produces reflective summaries."
    ),
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "ReOS Local Kernel",
        "privacy": "local-only; metadata-only by default",
        "health": "/health",
        "ingest": "/events",
        "reflections": "/reflections",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/events", response_model=EventIngestResponse)
def ingest_event(event: Event) -> EventIngestResponse:
    event_id = append_event(event)
    return EventIngestResponse(stored=True, event_id=event_id)


@app.get("/reflections", response_model=ReflectionsResponse)
def reflections(window_minutes: int = 30) -> ReflectionsResponse:
    # Simple heuristic placeholder: count recent events as switches.
    recent = list(iter_events())
    switches = len(recent)
    message = (
        f"Recent activity shows {switches} context switches in the last window. "
        "No content was captured; metadata only."
    )
    reflection = Reflection(
        message=message,
        switches_last_window=switches,
        window_minutes=window_minutes,
    )
    return ReflectionsResponse(reflections=[reflection], events_seen=len(recent))


@app.get("/time", response_model=HealthResponse)
def time_now() -> HealthResponse:
    # Minimal endpoint to check clock skew from VS Code extension if needed.
    return HealthResponse(timestamp=datetime.now(UTC))


@app.get("/ollama/health", response_model=OllamaHealthResponse)
def ollama_health() -> OllamaHealthResponse:
    health = check_ollama()
    return OllamaHealthResponse(
        reachable=health.reachable,
        model_count=health.model_count,
        error=health.error,
    )


@app.get("/tools")
def tools() -> list[dict[str, str]]:
    # MCP-ready: stable, explicit tool catalog for a future MCP server.
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "method": spec.method,
            "path": spec.path,
            "privacy": spec.privacy,
        }
        for spec in list_tools()
    ]
