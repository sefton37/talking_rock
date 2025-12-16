from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Static settings for the local service.

    Keep defaults local and auditable; no network endpoints beyond localhost.
    """

    root_dir: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = root_dir / ".reos-data"
    events_path: Path = data_dir / "events.jsonl"
    audit_path: Path = data_dir / "audit.log"
    host: str = os.environ.get("REOS_HOST", "127.0.0.1")
    port: int = int(os.environ.get("REOS_PORT", "8010"))
    ollama_url: str = os.environ.get("REOS_OLLAMA_URL", "http://127.0.0.1:11434")


settings = Settings()

# Ensure data directories exist at import time (local-only side effect).
settings.data_dir.mkdir(parents=True, exist_ok=True)
