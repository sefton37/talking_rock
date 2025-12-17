from __future__ import annotations

import hashlib
import json
import logging
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import Database
from .models import Event

logger = logging.getLogger(__name__)

_RECENT_SIGNATURES: dict[str, datetime] = {}


def _error_signature(*, operation: str, exc: BaseException) -> str:
    material = f"{operation}|{type(exc).__name__}|{str(exc)}".encode("utf-8", errors="replace")
    return hashlib.sha256(material).hexdigest()


def record_error(
    *,
    source: str,
    operation: str,
    exc: BaseException,
    context: dict[str, Any] | None = None,
    db: Database | None = None,
    dedupe_window_seconds: int = 60,
    include_traceback: bool = True,
) -> str | None:
    """Record an error as a local event.

    - Stores a metadata-only error summary in SQLite (or JSONL fallback via append_event).
    - Optionally deduplicates repeated identical errors for a short window.

    Returns the stored event id when known (SQLite path), else None.
    """

    signature = _error_signature(operation=operation, exc=exc)
    now = datetime.now(UTC)

    if dedupe_window_seconds > 0:
        cutoff = now - timedelta(seconds=dedupe_window_seconds)
        last_seen = _RECENT_SIGNATURES.get(signature)
        if last_seen is not None and last_seen >= cutoff:
            return None
        _RECENT_SIGNATURES[signature] = now

    tb_text: str | None = None
    if include_traceback:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # Keep the payload bounded.
        if len(tb_text) > 10_000:
            tb_text = tb_text[-10_000:]

    payload: dict[str, Any] = {
        "kind": "error",
        "signature": signature,
        "operation": operation,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "context": context or {},
        "traceback": tb_text,
        "ts": now.isoformat(),
    }

    try:
        if db is not None:
            import uuid

            event_id = str(uuid.uuid4())
            db.insert_event(
                event_id=event_id,
                source=source,
                kind="error",
                ts=now.isoformat(),
                payload_metadata=json.dumps(payload),
                note=f"{operation}: {type(exc).__name__}",
            )
            return event_id

        # Imported lazily to avoid circular imports (storage -> alignment -> errors).
        from .storage import append_event

        append_event(Event(source=source, ts=now, payload_metadata=payload))
        return None
    except Exception as write_exc:  # noqa: BLE001
        logger.debug("Failed to record error event: %s", write_exc)
        return None
