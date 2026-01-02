"""XDG Base Directory compliant paths for ReOS.

This module provides platform-aware paths following the XDG Base Directory
Specification (https://specifications.freedesktop.org/basedir-spec/latest/).

On Linux:
  - Data:   ~/.local/share/reos (XDG_DATA_HOME)
  - Config: ~/.config/reos (XDG_CONFIG_HOME)
  - Cache:  ~/.cache/reos (XDG_CACHE_HOME)
  - Runtime: $XDG_RUNTIME_DIR/reos (if available)

On other platforms, falls back to ~/.reos-data for compatibility.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Application identifier
APP_NAME: Final[str] = "reos"


def _is_linux() -> bool:
    """Check if running on Linux."""
    return sys.platform.startswith("linux")


def _get_xdg_path(env_var: str, default_subdir: str) -> Path:
    """Get XDG directory path with fallback to default."""
    if env_var in os.environ:
        return Path(os.environ[env_var]) / APP_NAME
    return Path.home() / default_subdir / APP_NAME


@dataclass(frozen=True)
class XDGPaths:
    """XDG Base Directory compliant paths.

    Provides separate directories for:
    - data: Persistent application data (database, events)
    - config: User configuration files
    - cache: Cached data that can be regenerated
    - runtime: Runtime files (sockets, locks) - session-specific
    """

    data_home: Path
    config_home: Path
    cache_home: Path
    runtime_dir: Path | None

    @classmethod
    def detect(cls) -> "XDGPaths":
        """Detect and create XDG-compliant paths for current platform."""
        if _is_linux():
            data_home = _get_xdg_path("XDG_DATA_HOME", ".local/share")
            config_home = _get_xdg_path("XDG_CONFIG_HOME", ".config")
            cache_home = _get_xdg_path("XDG_CACHE_HOME", ".cache")

            # Runtime dir is special - may not exist
            runtime_base = os.environ.get("XDG_RUNTIME_DIR")
            runtime_dir = Path(runtime_base) / APP_NAME if runtime_base else None
        else:
            # Fallback for non-Linux platforms
            fallback = Path.home() / f".{APP_NAME}"
            data_home = fallback / "data"
            config_home = fallback / "config"
            cache_home = fallback / "cache"
            runtime_dir = None

        return cls(
            data_home=data_home,
            config_home=config_home,
            cache_home=cache_home,
            runtime_dir=runtime_dir,
        )

    def ensure_dirs(self) -> None:
        """Create all directories if they don't exist."""
        self.data_home.mkdir(parents=True, exist_ok=True)
        self.config_home.mkdir(parents=True, exist_ok=True)
        self.cache_home.mkdir(parents=True, exist_ok=True)
        if self.runtime_dir:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)

    # Convenience properties for common paths

    @property
    def db_path(self) -> Path:
        """SQLite database path."""
        return self.data_home / "reos.db"

    @property
    def events_path(self) -> Path:
        """JSONL events fallback path."""
        return self.data_home / "events.jsonl"

    @property
    def audit_path(self) -> Path:
        """Audit log path."""
        return self.data_home / "audit.log"

    @property
    def log_path(self) -> Path:
        """Application log path."""
        return self.cache_home / "reos.log"

    @property
    def config_file(self) -> Path:
        """Main configuration file."""
        return self.config_home / "config.toml"

    @property
    def play_dir(self) -> Path:
        """Play (Acts/Scenes/Beats) data directory."""
        return self.data_home / "play"

    @property
    def personas_dir(self) -> Path:
        """Agent personas directory."""
        return self.config_home / "personas"

    @property
    def hooks_dir(self) -> Path:
        """User hooks directory."""
        return self.config_home / "hooks"

    @property
    def socket_path(self) -> Path | None:
        """Unix socket path for IPC (if runtime dir available)."""
        return self.runtime_dir / "reos.sock" if self.runtime_dir else None

    @property
    def pid_file(self) -> Path | None:
        """PID file path (if runtime dir available)."""
        return self.runtime_dir / "reos.pid" if self.runtime_dir else None


# Global paths instance - initialized on import
paths = XDGPaths.detect()


def get_legacy_data_dir() -> Path | None:
    """Get legacy .reos-data directory if it exists (for migration).

    Returns the path if it exists, None otherwise.
    """
    # Check in current working directory
    cwd_legacy = Path.cwd() / ".reos-data"
    if cwd_legacy.is_dir():
        return cwd_legacy

    # Check in home directory
    home_legacy = Path.home() / ".reos-data"
    if home_legacy.is_dir():
        return home_legacy

    return None


def migrate_legacy_data() -> bool:
    """Migrate data from legacy .reos-data to XDG directories.

    Returns True if migration was performed, False otherwise.
    """
    legacy_dir = get_legacy_data_dir()
    if not legacy_dir:
        return False

    paths.ensure_dirs()

    # Files to migrate to data_home
    data_files = ["reos.db", "events.jsonl", "audit.log"]
    for filename in data_files:
        legacy_file = legacy_dir / filename
        if legacy_file.exists():
            target = paths.data_home / filename
            if not target.exists():
                import shutil

                shutil.copy2(legacy_file, target)

    # Migrate play directory
    legacy_play = legacy_dir / "play"
    if legacy_play.is_dir() and not paths.play_dir.exists():
        import shutil

        shutil.copytree(legacy_play, paths.play_dir)

    return True
