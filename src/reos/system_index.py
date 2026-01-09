"""System State Indexer for ReOS.

This module collects and indexes system state information daily,
providing RAG (Retrieval-Augmented Generation) context for the LLM.

The indexer captures:
- Hardware info (CPU, RAM, disk, GPU)
- OS and kernel version
- Installed packages (key packages, not exhaustive)
- Running services
- Network configuration
- User environment
- Container status
- Recent system events

The snapshot is stored in SQLite and refreshed once per day (or on demand).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import linux_tools
from .db import Database

logger = logging.getLogger(__name__)


@dataclass
class SystemSnapshot:
    """A point-in-time snapshot of system state."""

    snapshot_id: str
    captured_at: str
    hostname: str = ""
    os_info: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    network: dict[str, Any] = field(default_factory=dict)
    services: list[dict[str, Any]] = field(default_factory=list)
    packages: dict[str, Any] = field(default_factory=dict)
    containers: dict[str, Any] = field(default_factory=dict)
    users: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    storage: list[dict[str, Any]] = field(default_factory=list)
    recent_logs: list[str] = field(default_factory=list)


class SystemIndexer:
    """Collects and stores daily system state snapshots."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the system_snapshots table if it doesn't exist."""
        conn = self._db.connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_snapshots (
                id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                date TEXT NOT NULL,
                hostname TEXT,
                data_json TEXT NOT NULL,
                summary TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON system_snapshots(date DESC)"
        )

        # FTS5 table for full-text package search
        # Enables queries like: "image editor" → finds "gimp"
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS packages_fts USING fts5(
                name,
                description,
                is_installed,
                category,
                tokenize='porter unicode61'
            )
            """
        )

        # Desktop applications table for GUI app metadata
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS desktop_apps (
                desktop_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                generic_name TEXT,
                comment TEXT,
                exec_cmd TEXT,
                icon TEXT,
                categories TEXT,
                keywords TEXT,
                indexed_at TEXT NOT NULL
            )
            """
        )

        # FTS5 for desktop apps
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS desktop_apps_fts USING fts5(
                desktop_id,
                name,
                generic_name,
                comment,
                keywords,
                tokenize='porter unicode61'
            )
            """
        )

        # Vector embeddings table for semantic search
        # Stores pre-computed embeddings for packages and apps
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_embeddings (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                embedding BLOB NOT NULL,
                indexed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_source ON semantic_embeddings(source_type)"
        )

        conn.commit()

    def needs_refresh(self) -> bool:
        """Check if we need a new snapshot today."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self._db._execute(
            "SELECT id FROM system_snapshots WHERE date = ? LIMIT 1",
            (today,),
        ).fetchone()
        return row is None

    def get_latest_snapshot(self) -> SystemSnapshot | None:
        """Get the most recent system snapshot."""
        row = self._db._execute(
            "SELECT * FROM system_snapshots ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()

        if row is None:
            return None

        data = json.loads(row["data_json"])
        return SystemSnapshot(
            snapshot_id=row["id"],
            captured_at=row["captured_at"],
            hostname=row["hostname"] or "",
            os_info=data.get("os_info", {}),
            hardware=data.get("hardware", {}),
            network=data.get("network", {}),
            services=data.get("services", []),
            packages=data.get("packages", {}),
            containers=data.get("containers", {}),
            users=data.get("users", []),
            environment=data.get("environment", {}),
            storage=data.get("storage", []),
            recent_logs=data.get("recent_logs", []),
        )

    def get_today_snapshot(self) -> SystemSnapshot | None:
        """Get today's snapshot if it exists."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self._db._execute(
            "SELECT * FROM system_snapshots WHERE date = ? LIMIT 1",
            (today,),
        ).fetchone()

        if row is None:
            return None

        data = json.loads(row["data_json"])
        return SystemSnapshot(
            snapshot_id=row["id"],
            captured_at=row["captured_at"],
            hostname=row["hostname"] or "",
            os_info=data.get("os_info", {}),
            hardware=data.get("hardware", {}),
            network=data.get("network", {}),
            services=data.get("services", []),
            packages=data.get("packages", {}),
            containers=data.get("containers", {}),
            users=data.get("users", []),
            environment=data.get("environment", {}),
            storage=data.get("storage", []),
            recent_logs=data.get("recent_logs", []),
        )

    def capture_snapshot(self) -> SystemSnapshot:
        """Capture a new system state snapshot."""
        import uuid

        now = datetime.now(UTC)
        snapshot_id = f"snap_{now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        logger.info("Capturing system state snapshot...")

        snapshot = SystemSnapshot(
            snapshot_id=snapshot_id,
            captured_at=now.isoformat(),
        )

        # Collect all information
        snapshot.hostname = self._get_hostname()
        snapshot.os_info = self._get_os_info()
        snapshot.hardware = self._get_hardware_info()
        snapshot.network = self._get_network_info()
        snapshot.services = self._get_services()
        snapshot.packages = self._get_packages()
        snapshot.containers = self._get_containers()
        snapshot.users = self._get_users()
        snapshot.environment = self._get_environment()
        snapshot.storage = self._get_storage()
        snapshot.recent_logs = self._get_recent_logs()

        # Store in database
        self._store_snapshot(snapshot)

        # Index for FTS5 search (packages + desktop apps)
        logger.info("Indexing packages and desktop apps for FTS5 search...")
        pkg_count = self.index_packages_fts(snapshot.packages)
        app_count = self.index_desktop_apps()
        logger.info("FTS5 indexed: %d packages, %d desktop apps", pkg_count, app_count)

        # Create vector embeddings for semantic search (if available)
        logger.info("Creating vector embeddings for semantic search...")
        pkg_embed_count = self.index_embeddings(snapshot.packages)
        app_embed_count = self.index_desktop_embeddings()
        if pkg_embed_count or app_embed_count:
            logger.info(
                "Embeddings created: %d packages, %d desktop apps",
                pkg_embed_count, app_embed_count
            )
        else:
            logger.info("Embeddings skipped (sentence-transformers not installed)")

        logger.info("System snapshot captured: %s", snapshot_id)
        return snapshot

    def _store_snapshot(self, snapshot: SystemSnapshot) -> None:
        """Store a snapshot in the database."""
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")

        data = {
            "os_info": snapshot.os_info,
            "hardware": snapshot.hardware,
            "network": snapshot.network,
            "services": snapshot.services,
            "packages": snapshot.packages,
            "containers": snapshot.containers,
            "users": snapshot.users,
            "environment": snapshot.environment,
            "storage": snapshot.storage,
            "recent_logs": snapshot.recent_logs,
        }

        summary = self._generate_summary(snapshot)

        self._db._execute(
            """
            INSERT INTO system_snapshots
            (id, captured_at, date, hostname, data_json, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.captured_at,
                today,
                snapshot.hostname,
                json.dumps(data, default=str),
                summary,
                now.isoformat(),
            ),
        )
        self._db.connect().commit()

    def _generate_summary(self, snapshot: SystemSnapshot) -> str:
        """Generate a human-readable summary of the snapshot."""
        lines = []

        # OS
        os_info = snapshot.os_info
        if os_info:
            lines.append(f"OS: {os_info.get('distro', 'Linux')} {os_info.get('version', '')}")
            if os_info.get("kernel"):
                lines.append(f"Kernel: {os_info['kernel']}")

        # Hardware
        hw = snapshot.hardware
        if hw:
            if hw.get("cpu_model"):
                lines.append(f"CPU: {hw['cpu_model']}")
            if hw.get("memory_total_gb"):
                lines.append(f"RAM: {hw['memory_total_gb']:.1f} GB")

        # Storage summary
        if snapshot.storage:
            total_gb = sum(s.get("total_gb", 0) for s in snapshot.storage)
            free_gb = sum(s.get("free_gb", 0) for s in snapshot.storage)
            lines.append(f"Storage: {free_gb:.0f} GB free of {total_gb:.0f} GB")

        # Services
        running = [s for s in snapshot.services if s.get("active")]
        if running:
            lines.append(f"Services: {len(running)} running")

        # Containers
        if snapshot.containers.get("containers"):
            lines.append(f"Containers: {len(snapshot.containers['containers'])} running")

        return "\n".join(lines)

    def _get_hostname(self) -> str:
        """Get the system hostname."""
        try:
            import socket
            return socket.gethostname()
        except Exception:
            return os.environ.get("HOSTNAME", "unknown")

    def _get_os_info(self) -> dict[str, Any]:
        """Get OS and kernel information."""
        info: dict[str, Any] = {}

        # Read /etc/os-release
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if "=" in line:
                        key, _, value = line.strip().partition("=")
                        value = value.strip('"')
                        if key == "NAME":
                            info["distro"] = value
                        elif key == "VERSION_ID":
                            info["version"] = value
                        elif key == "ID":
                            info["id"] = value
                        elif key == "ID_LIKE":
                            info["family"] = value
        except Exception as e:
            logger.debug("Could not read /etc/os-release: %s", e)

        # Kernel version
        try:
            result = subprocess.run(
                ["uname", "-r"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["kernel"] = result.stdout.strip()
        except Exception as e:
            logger.debug("Could not get kernel version: %s", e)

        # Architecture
        try:
            result = subprocess.run(
                ["uname", "-m"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["arch"] = result.stdout.strip()
        except Exception as e:
            logger.debug("Could not get architecture: %s", e)

        # Uptime
        try:
            sys_info = linux_tools.get_system_info()
            info["uptime"] = sys_info.uptime
        except Exception as e:
            logger.debug("Could not get uptime: %s", e)

        return info

    def _get_hardware_info(self) -> dict[str, Any]:
        """Get hardware information."""
        info: dict[str, Any] = {}

        try:
            sys_info = linux_tools.get_system_info()
            info["cpu_model"] = sys_info.cpu_model
            info["cpu_cores"] = sys_info.cpu_cores
            info["memory_total_gb"] = round(sys_info.memory_total_mb / 1024, 2)
            info["memory_used_gb"] = round(sys_info.memory_used_mb / 1024, 2)
            info["memory_percent"] = round(
                (sys_info.memory_used_mb / sys_info.memory_total_mb) * 100, 1
            ) if sys_info.memory_total_mb > 0 else 0
        except Exception as e:
            logger.debug("Could not get system info: %s", e)

        # GPU info (basic)
        try:
            result = subprocess.run(
                ["lspci"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                gpus = []
                for line in result.stdout.splitlines():
                    if "VGA" in line or "3D" in line or "Display" in line:
                        gpus.append(line.split(": ", 1)[-1] if ": " in line else line)
                if gpus:
                    info["gpus"] = gpus
        except Exception as e:
            logger.debug("Could not get GPU info: %s", e)

        return info

    def _get_network_info(self) -> dict[str, Any]:
        """Get network configuration."""
        try:
            return linux_tools.get_network_info()
        except Exception as e:
            logger.debug("Could not get network info: %s", e)
            return {}

    def _get_services(self) -> list[dict[str, Any]]:
        """Get list of ALL running services."""
        try:
            services = linux_tools.list_services(show_inactive=False)
            # Include ALL running services - no limit
            return [
                {
                    "name": s.name,
                    "description": s.description,
                    "active": s.active,
                    "enabled": s.enabled,
                }
                for s in services
            ]
        except Exception as e:
            logger.debug("Could not list services: %s", e)
            return []

    def _get_packages(self) -> dict[str, Any]:
        """Get ALL installed packages with descriptions for FTS5 indexing."""
        info: dict[str, Any] = {
            "manager": None,
            "installed": [],  # Full list of installed packages
            "with_descriptions": [],  # List of (name, description) tuples
            "total_count": 0,
        }

        try:
            pm = linux_tools.detect_package_manager()
            info["manager"] = pm

            if pm is None:
                return info

            # Get full package list with descriptions based on package manager
            if pm == "apt":
                # dpkg-query with description (first line only)
                try:
                    result = subprocess.run(
                        ["dpkg-query", "-W", "-f=${Package}\t${Description}\n"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode == 0:
                        packages = []
                        with_desc = []
                        for line in result.stdout.strip().splitlines():
                            if "\t" in line:
                                name, desc = line.split("\t", 1)
                                name = name.strip()
                                # Take only first line of description
                                desc = desc.split("\n")[0].strip()
                                if name:
                                    packages.append(name)
                                    with_desc.append((name, desc))
                            else:
                                name = line.strip()
                                if name:
                                    packages.append(name)
                                    with_desc.append((name, ""))
                        info["installed"] = sorted(packages)
                        info["with_descriptions"] = with_desc
                        info["total_count"] = len(packages)
                except Exception as e:
                    logger.debug("Could not list packages with descriptions: %s", e)

            else:
                # Other package managers: just get names (fallback)
                list_cmds = {
                    "dnf": ["rpm", "-qa", "--qf", "%{NAME}\n"],
                    "yum": ["rpm", "-qa", "--qf", "%{NAME}\n"],
                    "pacman": ["pacman", "-Qq"],
                    "zypper": ["rpm", "-qa", "--qf", "%{NAME}\n"],
                    "apk": ["apk", "list", "-I"],
                }

                if pm in list_cmds:
                    try:
                        result = subprocess.run(
                            list_cmds[pm],
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if result.returncode == 0:
                            packages = []
                            for line in result.stdout.strip().splitlines():
                                pkg = line.strip()
                                if pkg:
                                    # For apk, strip version info
                                    if pm == "apk" and " " in pkg:
                                        pkg = pkg.split()[0]
                                    packages.append(pkg)
                            info["installed"] = sorted(packages)
                            info["with_descriptions"] = [(p, "") for p in packages]
                            info["total_count"] = len(packages)
                    except Exception as e:
                        logger.debug("Could not list packages: %s", e)

        except Exception as e:
            logger.debug("Could not get package info: %s", e)

        return info

    def index_packages_fts(self, packages_info: dict[str, Any]) -> int:
        """Populate the FTS5 packages table with package descriptions.

        Args:
            packages_info: Output from _get_packages()

        Returns:
            Number of packages indexed
        """
        with_desc = packages_info.get("with_descriptions", [])
        if not with_desc:
            return 0

        conn = self._db.connect()
        try:
            # Clear existing entries
            conn.execute("DELETE FROM packages_fts")

            # Insert all packages
            for name, description in with_desc:
                conn.execute(
                    """INSERT INTO packages_fts
                    (name, description, is_installed, category) VALUES (?, ?, ?, ?)""",
                    (name, description, "yes", ""),
                )

            conn.commit()
            logger.info("Indexed %d packages in FTS5", len(with_desc))
            return len(with_desc)
        except Exception as e:
            logger.error("Failed to index packages in FTS5: %s", e)
            conn.rollback()
            return 0

    def search_packages(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Search packages using FTS5 full-text search.

        Args:
            query: Search query (e.g., "image editor", "web browser")
            limit: Maximum results to return

        Returns:
            List of matching packages with name and description
        """
        if not query or not query.strip():
            return []

        try:
            # Convert multi-word query to OR query for better matches
            # "image editor" -> "image OR editor"
            words = query.strip().split()
            if len(words) > 1:
                fts_query = " OR ".join(words)
            else:
                fts_query = query

            # FTS5 search with ranking
            rows = self._db._execute(
                """
                SELECT name, description, bm25(packages_fts) as rank
                FROM packages_fts
                WHERE packages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

            return [{"name": row["name"], "description": row["description"]} for row in rows]
        except Exception as e:
            logger.debug("FTS5 search failed: %s", e)
            return []

    def index_desktop_apps(self) -> int:
        """Index .desktop files for GUI application search.

        Scans standard locations for .desktop files and indexes their
        metadata (name, description, keywords) for FTS5 search.

        Returns:
            Number of desktop apps indexed
        """
        import configparser
        from pathlib import Path

        desktop_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            Path.home() / ".local/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications",
        ]

        apps: list[dict[str, str]] = []
        now = datetime.now(UTC).isoformat()

        for app_dir in desktop_dirs:
            if not app_dir.exists():
                continue

            for desktop_file in app_dir.glob("*.desktop"):
                try:
                    parser = configparser.ConfigParser(interpolation=None)
                    parser.read(str(desktop_file), encoding="utf-8")

                    if "Desktop Entry" not in parser:
                        continue

                    entry = parser["Desktop Entry"]

                    # Skip NoDisplay apps
                    if entry.get("NoDisplay", "").lower() == "true":
                        continue

                    # Skip non-Application types
                    if entry.get("Type", "Application") != "Application":
                        continue

                    app = {
                        "desktop_id": desktop_file.stem,
                        "name": entry.get("Name", desktop_file.stem),
                        "generic_name": entry.get("GenericName", ""),
                        "comment": entry.get("Comment", ""),
                        "exec_cmd": entry.get("Exec", ""),
                        "icon": entry.get("Icon", ""),
                        "categories": entry.get("Categories", ""),
                        "keywords": entry.get("Keywords", ""),
                        "indexed_at": now,
                    }
                    apps.append(app)
                except Exception as e:
                    logger.debug("Failed to parse %s: %s", desktop_file, e)

        if not apps:
            return 0

        conn = self._db.connect()
        try:
            # Clear existing entries
            conn.execute("DELETE FROM desktop_apps")
            conn.execute("DELETE FROM desktop_apps_fts")

            for app in apps:
                # Insert into regular table
                conn.execute(
                    """
                    INSERT OR REPLACE INTO desktop_apps
                    (desktop_id, name, generic_name, comment, exec_cmd,
                     icon, categories, keywords, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        app["desktop_id"],
                        app["name"],
                        app["generic_name"],
                        app["comment"],
                        app["exec_cmd"],
                        app["icon"],
                        app["categories"],
                        app["keywords"],
                        app["indexed_at"],
                    ),
                )

                # Insert into FTS5 table
                conn.execute(
                    """
                    INSERT INTO desktop_apps_fts
                    (desktop_id, name, generic_name, comment, keywords)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        app["desktop_id"],
                        app["name"],
                        app["generic_name"],
                        app["comment"],
                        app["keywords"],
                    ),
                )

            conn.commit()
            logger.info("Indexed %d desktop applications", len(apps))
            return len(apps)
        except Exception as e:
            logger.error("Failed to index desktop apps: %s", e)
            conn.rollback()
            return 0

    def search_desktop_apps(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Search desktop applications using FTS5.

        Args:
            query: Search query (e.g., "image editor", "web browser")
            limit: Maximum results to return

        Returns:
            List of matching apps with name, comment, and exec command
        """
        if not query or not query.strip():
            return []

        try:
            # Convert multi-word query to OR query for better matches
            words = query.strip().split()
            if len(words) > 1:
                fts_query = " OR ".join(words)
            else:
                fts_query = query

            rows = self._db._execute(
                """
                SELECT
                    da.desktop_id,
                    da.name,
                    da.generic_name,
                    da.comment,
                    da.exec_cmd,
                    bm25(desktop_apps_fts) as rank
                FROM desktop_apps_fts
                JOIN desktop_apps da ON da.desktop_id = desktop_apps_fts.desktop_id
                WHERE desktop_apps_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

            return [
                {
                    "desktop_id": row["desktop_id"],
                    "name": row["name"],
                    "generic_name": row["generic_name"],
                    "comment": row["comment"],
                    "exec_cmd": row["exec_cmd"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.debug("Desktop apps FTS5 search failed: %s", e)
            return []

    def search_all(self, query: str, limit: int = 5) -> dict[str, list[dict[str, str]]]:
        """Search both packages and desktop apps.

        Args:
            query: Search query
            limit: Maximum results per category

        Returns:
            Dict with "packages" and "desktop_apps" results
        """
        return {
            "packages": self.search_packages(query, limit),
            "desktop_apps": self.search_desktop_apps(query, limit),
        }

    # ═══════════════════════════════════════════════════════════════════════════════
    # Semantic Search with Vector Embeddings
    # ═══════════════════════════════════════════════════════════════════════════════

    _embedding_model = None  # Lazy-loaded singleton

    @classmethod
    def _get_embedding_model(cls):
        """Lazy-load the sentence transformer model.

        Uses all-MiniLM-L6-v2 (22MB) for fast, lightweight embeddings.
        Returns None if sentence-transformers not installed.
        """
        if cls._embedding_model is not None:
            return cls._embedding_model

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model (all-MiniLM-L6-v2)...")
            cls._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded")
            return cls._embedding_model
        except ImportError:
            logger.debug("sentence-transformers not installed, semantic search unavailable")
            return None
        except Exception as e:
            logger.warning("Failed to load embedding model: %s", e)
            return None

    def index_embeddings(self, packages_info: dict[str, Any], batch_size: int = 100) -> int:
        """Create vector embeddings for packages.

        Args:
            packages_info: Output from _get_packages() with descriptions
            batch_size: Number of items to embed at once

        Returns:
            Number of embeddings created
        """
        model = self._get_embedding_model()
        if model is None:
            logger.info("Skipping embeddings - model not available")
            return 0

        with_desc = packages_info.get("with_descriptions", [])
        if not with_desc:
            return 0

        # Filter to packages with meaningful descriptions
        items_to_embed = [
            (name, desc) for name, desc in with_desc
            if desc and len(desc) > 10  # Skip empty/trivial descriptions
        ]

        if not items_to_embed:
            return 0

        conn = self._db.connect()
        now = datetime.now(UTC).isoformat()
        count = 0

        try:
            # Clear existing package embeddings
            conn.execute("DELETE FROM semantic_embeddings WHERE source_type = 'package'")

            # Process in batches for memory efficiency
            for i in range(0, len(items_to_embed), batch_size):
                batch = items_to_embed[i:i + batch_size]
                texts = [f"{name}: {desc}" for name, desc in batch]

                # Generate embeddings for batch
                embeddings = model.encode(texts, show_progress_bar=False)

                # Store each embedding
                for j, (name, desc) in enumerate(batch):
                    embedding_bytes = embeddings[j].tobytes()
                    conn.execute(
                        """
                        INSERT INTO semantic_embeddings
                        (id, source_type, name, description, embedding, indexed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (f"pkg:{name}", "package", name, desc, embedding_bytes, now),
                    )
                    count += 1

                # Commit each batch
                conn.commit()
                logger.debug("Embedded batch %d-%d", i, min(i + batch_size, len(items_to_embed)))

            logger.info("Created %d package embeddings", count)
            return count

        except Exception as e:
            logger.error("Failed to create embeddings: %s", e)
            conn.rollback()
            return 0

    def index_desktop_embeddings(self) -> int:
        """Create vector embeddings for desktop applications.

        Returns:
            Number of embeddings created
        """
        model = self._get_embedding_model()
        if model is None:
            return 0

        conn = self._db.connect()
        now = datetime.now(UTC).isoformat()

        try:
            # Get all desktop apps
            rows = conn.execute(
                "SELECT desktop_id, name, generic_name, comment FROM desktop_apps"
            ).fetchall()

            if not rows:
                return 0

            # Clear existing desktop embeddings
            conn.execute("DELETE FROM semantic_embeddings WHERE source_type = 'desktop'")

            # Build texts for embedding
            items = []
            for row in rows:
                desc = row["comment"] or row["generic_name"] or ""
                if desc:
                    items.append((row["desktop_id"], row["name"], desc))

            if not items:
                return 0

            texts = [f"{name}: {desc}" for _, name, desc in items]
            embeddings = model.encode(texts, show_progress_bar=False)

            for i, (desktop_id, name, desc) in enumerate(items):
                embedding_bytes = embeddings[i].tobytes()
                conn.execute(
                    """
                    INSERT INTO semantic_embeddings
                    (id, source_type, name, description, embedding, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (f"desktop:{desktop_id}", "desktop", name, desc, embedding_bytes, now),
                )

            conn.commit()
            logger.info("Created %d desktop app embeddings", len(items))
            return len(items)

        except Exception as e:
            logger.error("Failed to create desktop embeddings: %s", e)
            conn.rollback()
            return 0

    def search_semantic(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search using vector similarity (cosine distance).

        This is the fallback when FTS5 returns no results.
        Handles synonyms and semantic matching.

        Args:
            query: Natural language query
            limit: Maximum results to return

        Returns:
            List of matching items with similarity scores
        """
        model = self._get_embedding_model()
        if model is None:
            return []

        try:
            import numpy as np

            # Embed the query
            query_embedding = model.encode(query, show_progress_bar=False)

            # Get all embeddings from database
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT id, source_type, name, description, embedding FROM semantic_embeddings"
            ).fetchall()

            if not rows:
                return []

            # Calculate cosine similarities
            results = []
            for row in rows:
                stored_embedding = np.frombuffer(row["embedding"], dtype=np.float32)

                # Cosine similarity
                similarity = np.dot(query_embedding, stored_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
                )

                results.append({
                    "id": row["id"],
                    "source_type": row["source_type"],
                    "name": row["name"],
                    "description": row["description"],
                    "similarity": float(similarity),
                })

            # Sort by similarity (highest first) and return top results
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:limit]

        except Exception as e:
            logger.debug("Semantic search failed: %s", e)
            return []

    def search_hybrid(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """Hybrid search: FTS5 first, semantic fallback.

        Uses fast FTS5 for keyword matches, falls back to
        vector similarity for semantic matching when FTS5 fails
        or returns weak results.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            Combined results from both search methods
        """
        combined = []

        # Try FTS5 first (fast)
        fts_results = self.search_all(query, limit)

        # Check if FTS5 results are high quality (name matches query words)
        query_words = set(query.lower().split())
        high_quality_fts = []

        for pkg in fts_results.get("packages", []):
            name_lower = pkg["name"].lower()
            # High quality if name contains any query word
            if any(word in name_lower for word in query_words):
                high_quality_fts.append({
                    "name": pkg["name"],
                    "description": pkg.get("description", ""),
                    "source": "package",
                    "match_type": "keyword",
                })

        for app in fts_results.get("desktop_apps", []):
            name_lower = app["name"].lower()
            if any(word in name_lower for word in query_words):
                high_quality_fts.append({
                    "name": app["name"],
                    "description": app.get("comment", app.get("generic_name", "")),
                    "source": "desktop",
                    "match_type": "keyword",
                })

        combined.extend(high_quality_fts)

        # Always try semantic search for synonym matching
        semantic_results = self.search_semantic(query, limit)

        # Add high-confidence semantic results (similarity > 0.5)
        for item in semantic_results:
            similarity = item.get("similarity", 0)
            if similarity > 0.5:  # Only high-confidence semantic matches
                # Avoid duplicates
                if not any(r["name"] == item["name"] for r in combined):
                    combined.append({
                        "name": item["name"],
                        "description": item.get("description", ""),
                        "source": item["source_type"],
                        "match_type": "semantic",
                        "similarity": similarity,
                    })

        # If still not enough results, add lower-quality FTS5 matches
        if len(combined) < limit:
            for pkg in fts_results.get("packages", []):
                if not any(r["name"] == pkg["name"] for r in combined):
                    combined.append({
                        "name": pkg["name"],
                        "description": pkg.get("description", ""),
                        "source": "package",
                        "match_type": "keyword",
                    })
                    if len(combined) >= limit:
                        break

            for app in fts_results.get("desktop_apps", []):
                if not any(r["name"] == app["name"] for r in combined):
                    combined.append({
                        "name": app["name"],
                        "description": app.get("comment", app.get("generic_name", "")),
                        "source": "desktop",
                        "match_type": "keyword",
                    })
                    if len(combined) >= limit:
                        break

        return combined[:limit]

    def _get_containers(self) -> dict[str, Any]:
        """Get container runtime, ALL containers, and ALL images."""
        info: dict[str, Any] = {
            "runtime": None,
            "running_containers": [],
            "all_containers": [],
            "images": [],
        }

        try:
            runtime = linux_tools.detect_container_runtime()
            info["runtime"] = runtime

            if runtime:
                # Get ALL containers (running and stopped)
                all_containers = linux_tools.list_containers(all_containers=True)
                info["all_containers"] = all_containers

                # Also track just running ones for quick reference
                info["running_containers"] = [
                    c for c in all_containers
                    if c.get("status", "").lower().startswith("up")
                ]

                # Get ALL images
                images = linux_tools.list_container_images()
                info["images"] = images

        except Exception as e:
            logger.debug("Could not get container info: %s", e)

        return info

    def _get_users(self) -> list[dict[str, Any]]:
        """Get list of users."""
        try:
            users = linux_tools.list_users(system_users=False)
            return users[:20]  # Limit to 20 users
        except Exception as e:
            logger.debug("Could not list users: %s", e)
            return []

    def _get_environment(self) -> dict[str, Any]:
        """Get environment information."""
        try:
            return linux_tools.get_environment_info()
        except Exception as e:
            logger.debug("Could not get environment info: %s", e)
            return {}

    def _get_storage(self) -> list[dict[str, Any]]:
        """Get storage/disk information."""
        storage = []

        # Common mount points to check
        mount_points = ["/", "/home", "/var", "/tmp", "/opt"]

        for path in mount_points:
            if os.path.exists(path):
                try:
                    info = linux_tools.get_disk_usage(path)
                    storage.append({
                        "path": path,
                        "total_gb": info.total_gb,
                        "used_gb": info.used_gb,
                        "free_gb": info.free_gb,
                        "percent_used": info.percent_used,
                    })
                except Exception as e:
                    logger.debug("Could not get disk usage for %s: %s", path, e)

        return storage

    def _get_recent_logs(self) -> list[str]:
        """Get recent important log entries."""
        logs = []

        try:
            # Get recent boot messages
            entries = linux_tools.get_boot_logs(current_boot=True, lines=20)
            for entry in entries[:10]:
                if isinstance(entry, dict):
                    logs.append(f"[boot] {entry.get('message', '')}")
                else:
                    logs.append(f"[boot] {entry}")
        except Exception as e:
            logger.debug("Could not get boot logs: %s", e)

        try:
            # Get failed services
            failed = linux_tools.get_failed_services()
            for svc in failed[:5]:
                if isinstance(svc, dict):
                    name = svc.get('name', 'unknown')
                    desc = svc.get('description', '')
                    logs.append(f"[failed] {name}: {desc}")
        except Exception as e:
            logger.debug("Could not get failed services: %s", e)

        return logs

    def cleanup_old_snapshots(self, keep_days: int = 30) -> int:
        """Remove snapshots older than keep_days."""
        cutoff = (datetime.now(UTC) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        cursor = self._db._execute(
            "DELETE FROM system_snapshots WHERE date < ?",
            (cutoff,),
        )
        self._db.connect().commit()
        return cursor.rowcount


def build_rag_context(snapshot: SystemSnapshot) -> str:
    """Build RAG context string from a system snapshot.

    This creates a comprehensive system state summary for the LLM,
    including ALL services, packages, and containers.
    """
    lines = []
    lines.append("=== SYSTEM STATE (as of {}) ===".format(
        snapshot.captured_at[:10] if snapshot.captured_at else "unknown"
    ))
    lines.append("")

    # Hostname and OS
    if snapshot.hostname:
        lines.append(f"Hostname: {snapshot.hostname}")

    os_info = snapshot.os_info
    if os_info:
        distro = os_info.get("distro", "Linux")
        version = os_info.get("version", "")
        kernel = os_info.get("kernel", "")
        arch = os_info.get("arch", "")
        lines.append(f"OS: {distro} {version} ({arch})")
        if kernel:
            lines.append(f"Kernel: {kernel}")
        if os_info.get("uptime"):
            lines.append(f"Uptime: {os_info['uptime']}")

    lines.append("")

    # Hardware
    hw = snapshot.hardware
    if hw:
        if hw.get("cpu_model"):
            cores = hw.get("cpu_cores", "")
            cores_str = f" ({cores} cores)" if cores else ""
            lines.append(f"CPU: {hw['cpu_model']}{cores_str}")
        if hw.get("memory_total_gb"):
            used = hw.get("memory_used_gb", 0)
            total = hw["memory_total_gb"]
            pct = hw.get("memory_percent", 0)
            lines.append(f"Memory: {used:.1f} GB / {total:.1f} GB ({pct:.0f}% used)")
        if hw.get("gpus"):
            for gpu in hw["gpus"]:
                lines.append(f"GPU: {gpu}")

    lines.append("")

    # Storage
    if snapshot.storage:
        lines.append("STORAGE:")
        for disk in snapshot.storage:
            path = disk.get("path", "/")
            free = disk.get("free_gb", 0)
            total = disk.get("total_gb", 0)
            pct = disk.get("percent_used", 0)
            lines.append(f"  {path}: {free:.0f} GB free / {total:.0f} GB ({pct:.0f}% used)")

    lines.append("")

    # Network
    net = snapshot.network
    if net:
        interfaces = net.get("interfaces", [])
        if interfaces:
            lines.append("NETWORK INTERFACES:")
            for iface in interfaces:
                name = iface.get("name", "")
                addrs = iface.get("addresses", [])
                addr_str = ", ".join(addrs) if addrs else "no IP"
                lines.append(f"  {name}: {addr_str}")

    lines.append("")

    # ALL Services
    if snapshot.services:
        running = [s for s in snapshot.services if s.get("active")]
        lines.append(f"RUNNING SERVICES ({len(running)} total):")
        for svc in running:
            name = svc.get("name", "")
            desc = svc.get("description", "")
            enabled = "enabled" if svc.get("enabled") else "disabled"
            if desc:
                lines.append(f"  {name}: {desc} [{enabled}]")
            else:
                lines.append(f"  {name} [{enabled}]")

    lines.append("")

    # ALL Packages
    pkgs = snapshot.packages
    if pkgs:
        pm = pkgs.get("manager", "unknown")
        installed = pkgs.get("installed", [])
        total = pkgs.get("total_count", len(installed))
        lines.append(f"INSTALLED PACKAGES ({pm}, {total} total):")
        if installed:
            # Group into lines of ~10 packages each for readability
            chunk_size = 10
            for i in range(0, len(installed), chunk_size):
                chunk = installed[i:i + chunk_size]
                lines.append(f"  {', '.join(chunk)}")

    lines.append("")

    # ALL Containers
    containers = snapshot.containers
    if containers.get("runtime"):
        runtime = containers["runtime"]
        running_containers = containers.get("running_containers", [])
        all_containers = containers.get("all_containers", [])
        images = containers.get("images", [])

        lines.append(f"CONTAINER RUNTIME: {runtime}")
        lines.append("")

        if running_containers:
            lines.append(f"RUNNING CONTAINERS ({len(running_containers)}):")
            for c in running_containers:
                name = c.get("name", c.get("id", "unknown"))
                image = c.get("image", "")
                status = c.get("status", "")
                lines.append(f"  {name}: {image} [{status}]")
        else:
            lines.append("RUNNING CONTAINERS: none")

        # Show stopped containers separately
        stopped = [c for c in all_containers if c not in running_containers]
        if stopped:
            lines.append("")
            lines.append(f"STOPPED CONTAINERS ({len(stopped)}):")
            for c in stopped:
                name = c.get("name", c.get("id", "unknown"))
                image = c.get("image", "")
                status = c.get("status", "")
                lines.append(f"  {name}: {image} [{status}]")

        if images:
            lines.append("")
            lines.append(f"CONTAINER IMAGES ({len(images)}):")
            for img in images:
                if isinstance(img, dict):
                    repo = img.get("repository", img.get("name", "unknown"))
                    tag = img.get("tag", "latest")
                    size = img.get("size", "")
                    size_str = f" ({size})" if size else ""
                    lines.append(f"  {repo}:{tag}{size_str}")
                else:
                    lines.append(f"  {img}")

    lines.append("")

    # Users
    if snapshot.users:
        lines.append("USERS:")
        for user in snapshot.users:
            username = user.get("username", "")
            uid = user.get("uid", "")
            groups = user.get("groups", [])
            groups_str = f" (groups: {', '.join(groups)})" if groups else ""
            if uid:
                lines.append(f"  {username} (uid={uid}){groups_str}")
            else:
                lines.append(f"  {username}{groups_str}")

    # Recent issues
    if snapshot.recent_logs:
        failed = [log for log in snapshot.recent_logs if "[failed]" in log]
        if failed:
            lines.append("")
            lines.append("RECENT ISSUES:")
            for log in failed:
                lines.append(f"  {log}")

    lines.append("")
    lines.append("=== END SYSTEM STATE ===")

    return "\n".join(lines)


def get_or_refresh_context(db: Database) -> str:
    """Get today's system context, refreshing if needed.

    This is the main entry point for the agent to get system context.
    It automatically captures a new snapshot if one doesn't exist for today.
    """
    indexer = SystemIndexer(db)

    # Check if we need a fresh snapshot
    if indexer.needs_refresh():
        logger.info("Daily system snapshot needed, capturing...")
        snapshot = indexer.capture_snapshot()
    else:
        snapshot = indexer.get_today_snapshot()

    if snapshot is None:
        return ""

    return build_rag_context(snapshot)
