from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from pathlib import Path

from .models import Event
from .settings import settings


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def append_event(event: Event) -> str:
    """Append an event to local JSONL storage and return its id."""
    _ensure_file(settings.events_path)
    event_id = str(uuid.uuid4())
    record = {
        "id": event_id,
        "source": event.source,
        "ts": event.ts.isoformat(),
        "payload_metadata": event.payload_metadata,
        "note": event.note,
    }
    with settings.events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")
    return event_id


def iter_events(limit: int | None = None) -> Iterable[tuple[str, Event]]:
    """Yield events from storage (newest first if limit is set)."""
    _ensure_file(settings.events_path)
    lines = settings.events_path.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    for line in lines:
        try:
            raw = json.loads(line)
            evt = Event(
                source=raw.get("source", "unknown"),
                ts=raw.get("ts"),
                payload_metadata=raw.get("payload_metadata"),
                note=raw.get("note"),
            )
            yield raw.get("id", ""), evt
        except json.JSONDecodeError:
            continue
