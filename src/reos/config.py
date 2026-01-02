"""TOML configuration file support for ReOS.

Loads configuration from:
1. System: /etc/reos/config.toml
2. User: ~/.config/reos/config.toml (XDG_CONFIG_HOME)
3. Local: ./.reos.toml (project-specific)
4. Environment variables (highest priority)

Configuration is merged in order, with later sources overriding earlier ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]

from reos.paths import paths


@dataclass
class GeneralConfig:
    """General configuration settings."""

    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 3


@dataclass
class KernelConfig:
    """Kernel server configuration."""

    host: str = "127.0.0.1"
    port: int = 8010
    workers: int = 1


@dataclass
class OllamaConfig:
    """Ollama LLM configuration."""

    url: str = "http://127.0.0.1:11434"
    model: str | None = None
    timeout: int = 120
    max_retries: int = 3


@dataclass
class ReviewConfig:
    """Commit review configuration."""

    auto_review: bool = False
    include_diff: bool = False
    cooldown_seconds: int = 5


@dataclass
class ContextConfig:
    """LLM context budget configuration."""

    max_tokens: int = 8192
    trigger_ratio: float = 0.8
    cooldown_minutes: int = 15
    overhead_tokens: int = 800
    tokens_per_line: int = 6
    tokens_per_file: int = 40


@dataclass
class NotificationsConfig:
    """Desktop notification configuration."""

    enabled: bool = True
    urgency: str = "normal"  # "low", "normal", "critical"
    timeout_ms: int = 5000


@dataclass
class Config:
    """Complete ReOS configuration."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    kernel: KernelConfig = field(default_factory=KernelConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)

    # Runtime overrides
    repo_path: Path | None = None

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from all sources."""
        config = cls()

        # Load from files (in order of priority)
        config_sources = [
            Path("/etc/reos/config.toml"),  # System
            paths.config_file,  # User (~/.config/reos/config.toml)
            Path.cwd() / ".reos.toml",  # Local project
        ]

        for source in config_sources:
            if source.exists():
                config = config._merge_from_file(source)

        # Apply environment variable overrides
        config = config._apply_env_overrides()

        return config

    def _merge_from_file(self, path: Path) -> "Config":
        """Merge configuration from a TOML file."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return self._merge_dict(data)
        except Exception as e:
            # Log but don't fail on config errors
            import sys

            print(f"Warning: Failed to load config from {path}: {e}", file=sys.stderr)
            return self

    def _merge_dict(self, data: dict[str, Any]) -> "Config":
        """Merge a dictionary into the configuration."""
        if "general" in data:
            self.general = _merge_dataclass(self.general, data["general"])
        if "kernel" in data:
            self.kernel = _merge_dataclass(self.kernel, data["kernel"])
        if "ollama" in data:
            self.ollama = _merge_dataclass(self.ollama, data["ollama"])
        if "review" in data:
            self.review = _merge_dataclass(self.review, data["review"])
        if "context" in data:
            self.context = _merge_dataclass(self.context, data["context"])
        if "notifications" in data:
            self.notifications = _merge_dataclass(self.notifications, data["notifications"])
        return self

    def _apply_env_overrides(self) -> "Config":
        """Apply environment variable overrides."""
        env_mappings = {
            "REOS_LOG_LEVEL": ("general", "log_level"),
            "REOS_LOG_FORMAT": ("general", "log_format"),
            "REOS_HOST": ("kernel", "host"),
            "REOS_PORT": ("kernel", "port", int),
            "REOS_OLLAMA_URL": ("ollama", "url"),
            "REOS_OLLAMA_MODEL": ("ollama", "model"),
            "REOS_AUTO_REVIEW_COMMITS": ("review", "auto_review", _parse_bool),
            "REOS_AUTO_REVIEW_COMMITS_INCLUDE_DIFF": ("review", "include_diff", _parse_bool),
            "REOS_AUTO_REVIEW_COMMITS_COOLDOWN_SECONDS": ("review", "cooldown_seconds", int),
            "REOS_LLM_CONTEXT_TOKENS": ("context", "max_tokens", int),
            "REOS_REVIEW_TRIGGER_RATIO": ("context", "trigger_ratio", float),
            "REOS_REVIEW_TRIGGER_COOLDOWN_MINUTES": ("context", "cooldown_minutes", int),
        }

        for env_var, mapping in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                section_name = mapping[0]
                field_name = mapping[1]
                converter = mapping[2] if len(mapping) > 2 else str

                section = getattr(self, section_name)
                try:
                    setattr(section, field_name, converter(value))  # type: ignore[operator]
                except (ValueError, TypeError):
                    pass  # Ignore invalid env values

        # Handle repo_path specially
        repo_path_env = os.environ.get("REOS_REPO_PATH")
        if repo_path_env:
            self.repo_path = Path(repo_path_env)

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary."""
        return {
            "general": {
                "log_level": self.general.log_level,
                "log_format": self.general.log_format,
                "log_max_bytes": self.general.log_max_bytes,
                "log_backup_count": self.general.log_backup_count,
            },
            "kernel": {
                "host": self.kernel.host,
                "port": self.kernel.port,
                "workers": self.kernel.workers,
            },
            "ollama": {
                "url": self.ollama.url,
                "model": self.ollama.model,
                "timeout": self.ollama.timeout,
                "max_retries": self.ollama.max_retries,
            },
            "review": {
                "auto_review": self.review.auto_review,
                "include_diff": self.review.include_diff,
                "cooldown_seconds": self.review.cooldown_seconds,
            },
            "context": {
                "max_tokens": self.context.max_tokens,
                "trigger_ratio": self.context.trigger_ratio,
                "cooldown_minutes": self.context.cooldown_minutes,
            },
            "notifications": {
                "enabled": self.notifications.enabled,
                "urgency": self.notifications.urgency,
                "timeout_ms": self.notifications.timeout_ms,
            },
        }


def _merge_dataclass(obj: Any, data: dict[str, Any]) -> Any:
    """Merge dictionary values into a dataclass instance."""
    for key, value in data.items():
        if hasattr(obj, key):
            # Handle type conversion for common cases
            current_value = getattr(obj, key)
            if isinstance(current_value, bool) and isinstance(value, str):
                value = _parse_bool(value)
            elif isinstance(current_value, int) and isinstance(value, str):
                value = int(value)
            elif isinstance(current_value, float) and isinstance(value, str):
                value = float(value)
            setattr(obj, key, value)
    return obj


def _parse_bool(value: str) -> bool:
    """Parse a boolean from string."""
    return value.lower() in ("1", "true", "yes", "y", "on")


# Default configuration template
DEFAULT_CONFIG_TEMPLATE = """\
# ReOS Configuration
# https://github.com/your-org/reos
#
# This file uses TOML format: https://toml.io/
# Environment variables override these settings.

[general]
# Log level: DEBUG, INFO, WARNING, ERROR
log_level = "INFO"

# Log format: "text" or "json"
log_format = "text"

# Log file rotation
log_max_bytes = 1000000
log_backup_count = 3

[kernel]
# Kernel bind address and port
host = "127.0.0.1"
port = 8010

[ollama]
# Local Ollama endpoint
url = "http://127.0.0.1:11434"

# Model to use (leave empty for auto-detect)
# model = "llama3.2"

# Request timeout in seconds
timeout = 120

[review]
# Automatic commit review (requires Ollama)
auto_review = false

# Include full diff in reviews (privacy: opt-in only)
include_diff = false

# Cooldown between reviews in seconds
cooldown_seconds = 5

[context]
# LLM context window settings
max_tokens = 8192

# Trigger review when context usage exceeds this ratio
trigger_ratio = 0.8

# Cooldown between triggers in minutes
cooldown_minutes = 15

[notifications]
# Enable desktop notifications
enabled = true

# Notification urgency: "low", "normal", "critical"
urgency = "normal"

# Notification timeout in milliseconds
timeout_ms = 5000
"""


def write_default_config(path: Path | None = None) -> Path:
    """Write the default configuration file.

    Args:
        path: Path to write to. Defaults to user config path.

    Returns:
        The path where the config was written.
    """
    if path is None:
        path = paths.config_file

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE)
    return path


# Global configuration instance - loaded on first access
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config() -> Config:
    """Reload configuration from disk."""
    global _config
    _config = Config.load()
    return _config
