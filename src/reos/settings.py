from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    """Static settings for the local service.

    Keep defaults local and auditable; no network endpoints beyond localhost.
    """

    root_dir: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = root_dir / ".reos-data"
    events_path: Path = data_dir / "events.jsonl"
    audit_path: Path = data_dir / "audit.log"
    log_path: Path = data_dir / "reos.log"
    log_level: str = os.environ.get("REOS_LOG_LEVEL", "INFO")
    log_max_bytes: int = int(os.environ.get("REOS_LOG_MAX_BYTES", str(1_000_000)))
    log_backup_count: int = int(os.environ.get("REOS_LOG_BACKUP_COUNT", "3"))
    host: str = os.environ.get("REOS_HOST", "127.0.0.1")
    port: int = int(os.environ.get("REOS_PORT", "8010"))
    ollama_url: str = os.environ.get("REOS_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str | None = os.environ.get("REOS_OLLAMA_MODEL")

    # Commit code review (opt-in).
    # When enabled, ReOS will read commit patches via `git show` and send them to the local LLM.
    auto_review_commits: bool = _env_bool("REOS_AUTO_REVIEW_COMMITS", False)
    auto_review_commits_include_diff: bool = _env_bool(
        "REOS_AUTO_REVIEW_COMMITS_INCLUDE_DIFF",
        False,
    )
    auto_review_commits_cooldown_seconds: int = int(
        os.environ.get("REOS_AUTO_REVIEW_COMMITS_COOLDOWN_SECONDS", "5")
    )

    # Git companion: which repo ReOS should observe.
    # If unset, ReOS will fall back to the workspace root if it's a git repo.
    repo_path: Path | None = (
        Path(os.environ["REOS_REPO_PATH"]) if os.environ.get("REOS_REPO_PATH") else None
    )

    # LLM context budgeting (heuristic, used for triggering reviews before overflow).
    llm_context_tokens: int = int(os.environ.get("REOS_LLM_CONTEXT_TOKENS", "8192"))
    review_trigger_ratio: float = float(os.environ.get("REOS_REVIEW_TRIGGER_RATIO", "0.8"))
    review_trigger_cooldown_minutes: int = int(
        os.environ.get("REOS_REVIEW_TRIGGER_COOLDOWN_MINUTES", "15")
    )

    # Estimation knobs (heuristics): how large changes feel in-context.
    review_overhead_tokens: int = int(os.environ.get("REOS_REVIEW_OVERHEAD_TOKENS", "800"))
    tokens_per_changed_line: int = int(os.environ.get("REOS_TOKENS_PER_CHANGED_LINE", "6"))
    tokens_per_changed_file: int = int(os.environ.get("REOS_TOKENS_PER_CHANGED_FILE", "40"))


settings = Settings()

# Ensure data directories exist at import time (local-only side effect).
settings.data_dir.mkdir(parents=True, exist_ok=True)
