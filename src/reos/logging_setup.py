from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .settings import settings

_CONFIGURED = False


def configure_logging(*, log_path: Path | None = None) -> None:
    """Configure ReOS logging.

    Local-first:
    - Logs to stderr for developer visibility.
    - Logs to a rotating file under `.reos-data/` for later inspection.

    Safe to call multiple times; it will not duplicate handlers.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = settings.log_level.upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Avoid adding duplicate handlers if something else already configured logging.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    resolved_log_path = log_path or settings.log_path
    try:
        resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not any(
            isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", None) == str(resolved_log_path)
            for h in root.handlers
        ):
            file_handler = RotatingFileHandler(
                filename=str(resolved_log_path),
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
    except Exception:
        # Best-effort: logging must never crash the app.
        pass

    _CONFIGURED = True
