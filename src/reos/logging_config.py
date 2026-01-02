"""Structured logging configuration for ReOS.

Supports both text and JSON output formats. JSON format is suitable for
log aggregation systems like Loki, ELK, or Datadog.

Usage:
    from reos.logging_config import setup_logging

    setup_logging(level="INFO", format="json")

Log format can be configured via:
    - Environment variable: REOS_LOG_FORMAT=json
    - Config file: [general] log_format = "json"
    - Function argument: setup_logging(format="json")
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from reos.paths import paths

LogFormat = Literal["text", "json"]


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Produces log entries like:
    {"timestamp": "2024-01-15T10:30:45.123Z", "level": "INFO", "logger": "reos.agent", "message": "..."}
    """

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add location info
        if record.pathname:
            log_entry["location"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields from the record
        if self.include_extra:
            extra_fields = {
                key: value
                for key, value in record.__dict__.items()
                if key not in {
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "exc_info", "exc_text", "thread", "threadName",
                    "message", "asctime",
                }
                and not key.startswith("_")
            }
            if extra_fields:
                log_entry["extra"] = extra_fields

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """Colored text formatter for terminal output."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str | None = None, use_colors: bool = True):
        super().__init__(fmt or "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors:
            color = self.COLORS.get(record.levelname, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    level: str | None = None,
    format: LogFormat | None = None,
    log_file: Path | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> None:
    """Configure logging for ReOS.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to REOS_LOG_LEVEL or INFO.
        format: Output format ("text" or "json"). Defaults to REOS_LOG_FORMAT or "text".
        log_file: Path to log file. Defaults to ~/.cache/reos/reos.log.
        max_bytes: Max size before rotation. Defaults to 1MB.
        backup_count: Number of backup files. Defaults to 3.
    """
    # Resolve configuration
    level = level or os.environ.get("REOS_LOG_LEVEL", "INFO")
    format = format or os.environ.get("REOS_LOG_FORMAT", "text")  # type: ignore[assignment]
    log_file = log_file or paths.log_path
    max_bytes = max_bytes or int(os.environ.get("REOS_LOG_MAX_BYTES", "1000000"))
    backup_count = backup_count or int(os.environ.get("REOS_LOG_BACKUP_COUNT", "3"))

    # Ensure log directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatters
    if format == "json":
        console_formatter = JsonFormatter()
        file_formatter = JsonFormatter()
    else:
        console_formatter = ColoredFormatter()
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        root_logger.warning(f"Could not create log file at {log_file}: {e}")

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    This is a convenience function that returns a logger configured
    with the ReOS logging settings.

    Args:
        name: Logger name, typically __name__

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding extra fields to log records.

    Usage:
        with LogContext(request_id="abc123", user="john"):
            logger.info("Processing request")  # Includes request_id and user
    """

    def __init__(self, **kwargs: Any):
        self.extra = kwargs
        self.old_factory: Any = None

    def __enter__(self) -> "LogContext":
        self.old_factory = logging.getLogRecordFactory()

        extra = self.extra

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = self.old_factory(*args, **kwargs)
            for key, value in extra.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, *args: Any) -> None:
        logging.setLogRecordFactory(self.old_factory)


# Convenience loggers for common modules
def log_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    result: Any = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Log a tool call with structured data."""
    logger = get_logger("reos.tools")

    log_data = {
        "tool": tool_name,
        "arguments": arguments,
    }

    if result is not None:
        log_data["result_type"] = type(result).__name__

    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms

    if error:
        logger.error(f"Tool call failed: {tool_name}", extra=log_data)
    else:
        logger.debug(f"Tool call: {tool_name}", extra=log_data)


def log_rpc_request(
    method: str,
    params: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Log an RPC request with structured data."""
    logger = get_logger("reos.rpc")

    log_data = {
        "method": method,
    }

    if params:
        # Redact sensitive fields
        safe_params = {
            k: "***" if k in ("password", "token", "secret") else v
            for k, v in params.items()
        }
        log_data["params"] = safe_params

    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms

    if error:
        logger.error(f"RPC error: {method} - {error}", extra=log_data)
    else:
        logger.debug(f"RPC: {method}", extra=log_data)
