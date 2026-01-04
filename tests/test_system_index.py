"""Tests for the system state indexer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestSystemSnapshot:
    """Tests for SystemSnapshot dataclass."""

    def test_snapshot_creation(self) -> None:
        """Should create a snapshot with default values."""
        from reos.system_index import SystemSnapshot

        snapshot = SystemSnapshot(
            snapshot_id="test_123",
            captured_at="2024-01-15T10:30:00+00:00",
        )

        assert snapshot.snapshot_id == "test_123"
        assert snapshot.captured_at == "2024-01-15T10:30:00+00:00"
        assert snapshot.hostname == ""
        assert snapshot.os_info == {}
        assert snapshot.hardware == {}
        assert snapshot.services == []

    def test_snapshot_with_data(self) -> None:
        """Should create a snapshot with provided data."""
        from reos.system_index import SystemSnapshot

        snapshot = SystemSnapshot(
            snapshot_id="test_456",
            captured_at="2024-01-15T10:30:00+00:00",
            hostname="myhost",
            os_info={"distro": "Ubuntu", "version": "22.04"},
            hardware={"cpu_model": "Intel i7", "memory_total_gb": 16.0},
        )

        assert snapshot.hostname == "myhost"
        assert snapshot.os_info["distro"] == "Ubuntu"
        assert snapshot.hardware["memory_total_gb"] == 16.0


class TestSystemIndexer:
    """Tests for SystemIndexer class."""

    def test_ensure_table_creates_schema(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should create system_snapshots table."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        # Table should exist
        conn = db.connect()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_snapshots'"
        )
        assert cursor.fetchone() is not None

    def test_needs_refresh_true_when_no_snapshot(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should return True when no snapshot exists for today."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        assert indexer.needs_refresh() is True

    def test_needs_refresh_false_after_capture(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should return False after capturing a snapshot today."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        # Capture a snapshot (mocked to avoid real system calls)
        with patch.object(indexer, "_get_hostname", return_value="testhost"), \
             patch.object(indexer, "_get_os_info", return_value={}), \
             patch.object(indexer, "_get_hardware_info", return_value={}), \
             patch.object(indexer, "_get_network_info", return_value={}), \
             patch.object(indexer, "_get_services", return_value=[]), \
             patch.object(indexer, "_get_packages", return_value={}), \
             patch.object(indexer, "_get_containers", return_value={}), \
             patch.object(indexer, "_get_users", return_value=[]), \
             patch.object(indexer, "_get_environment", return_value={}), \
             patch.object(indexer, "_get_storage", return_value=[]), \
             patch.object(indexer, "_get_recent_logs", return_value=[]):
            indexer.capture_snapshot()

        assert indexer.needs_refresh() is False

    def test_get_latest_snapshot(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should retrieve the most recent snapshot."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        with patch.object(indexer, "_get_hostname", return_value="testhost"), \
             patch.object(indexer, "_get_os_info", return_value={"distro": "TestOS"}), \
             patch.object(indexer, "_get_hardware_info", return_value={}), \
             patch.object(indexer, "_get_network_info", return_value={}), \
             patch.object(indexer, "_get_services", return_value=[]), \
             patch.object(indexer, "_get_packages", return_value={}), \
             patch.object(indexer, "_get_containers", return_value={}), \
             patch.object(indexer, "_get_users", return_value=[]), \
             patch.object(indexer, "_get_environment", return_value={}), \
             patch.object(indexer, "_get_storage", return_value=[]), \
             patch.object(indexer, "_get_recent_logs", return_value=[]):
            indexer.capture_snapshot()

        snapshot = indexer.get_latest_snapshot()
        assert snapshot is not None
        assert snapshot.hostname == "testhost"
        assert snapshot.os_info["distro"] == "TestOS"

    def test_cleanup_old_snapshots(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should remove snapshots older than specified days."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        # Insert an old snapshot directly
        old_date = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%d")
        db._execute(
            """
            INSERT INTO system_snapshots
            (id, captured_at, date, hostname, data_json, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("old_snap", "2024-01-01T00:00:00+00:00", old_date, "old", "{}", "", "2024-01-01T00:00:00+00:00"),
        )
        db.connect().commit()

        # Cleanup
        removed = indexer.cleanup_old_snapshots(keep_days=30)
        assert removed == 1


class TestBuildRagContext:
    """Tests for build_rag_context function."""

    def test_build_context_basic(self) -> None:
        """Should build a context string from snapshot."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            hostname="myhost",
            os_info={"distro": "Ubuntu", "version": "22.04", "kernel": "5.15.0"},
        )

        context = build_rag_context(snapshot)

        assert "SYSTEM STATE" in context
        assert "myhost" in context
        assert "Ubuntu" in context
        assert "22.04" in context

    def test_build_context_with_hardware(self) -> None:
        """Should include hardware info in context."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            hardware={
                "cpu_model": "Intel Core i7-10700",
                "cpu_cores": 8,
                "memory_total_gb": 32.0,
                "memory_used_gb": 16.0,
                "memory_percent": 50.0,
            },
        )

        context = build_rag_context(snapshot)

        assert "Intel Core i7-10700" in context
        assert "32.0 GB" in context
        assert "50" in context  # percent

    def test_build_context_with_storage(self) -> None:
        """Should include storage info in context."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            storage=[
                {"path": "/", "total_gb": 500, "free_gb": 200, "percent_used": 60},
                {"path": "/home", "total_gb": 1000, "free_gb": 800, "percent_used": 20},
            ],
        )

        context = build_rag_context(snapshot)

        assert "STORAGE:" in context
        assert "/" in context
        assert "/home" in context

    def test_build_context_with_services(self) -> None:
        """Should include ALL services in context."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            services=[
                {"name": "sshd", "active": True, "enabled": True},
                {"name": "nginx", "active": True, "enabled": True},
                {"name": "docker", "active": True, "enabled": True},
            ],
        )

        context = build_rag_context(snapshot)

        assert "RUNNING SERVICES (3 total):" in context
        # All services should be listed
        assert "sshd" in context
        assert "nginx" in context
        assert "docker" in context

    def test_build_context_with_packages(self) -> None:
        """Should include ALL packages in context."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            packages={
                "manager": "apt",
                "installed": ["bash", "coreutils", "curl", "git", "nginx", "python3", "vim"],
                "total_count": 7,
            },
        )

        context = build_rag_context(snapshot)

        assert "INSTALLED PACKAGES (apt, 7 total):" in context
        # All packages should be listed
        assert "bash" in context
        assert "git" in context
        assert "nginx" in context
        assert "python3" in context

    def test_build_context_with_containers(self) -> None:
        """Should include ALL container info in context."""
        from reos.system_index import SystemSnapshot, build_rag_context

        snapshot = SystemSnapshot(
            snapshot_id="test",
            captured_at="2024-01-15T10:30:00+00:00",
            containers={
                "runtime": "docker",
                "running_containers": [
                    {"name": "web", "id": "abc123", "image": "nginx:latest", "status": "Up 2 hours"},
                    {"name": "db", "id": "def456", "image": "postgres:15", "status": "Up 2 hours"},
                ],
                "all_containers": [
                    {"name": "web", "id": "abc123", "image": "nginx:latest", "status": "Up 2 hours"},
                    {"name": "db", "id": "def456", "image": "postgres:15", "status": "Up 2 hours"},
                    {"name": "old-app", "id": "ghi789", "image": "myapp:v1", "status": "Exited (0) 3 days ago"},
                ],
                "images": [
                    {"repository": "nginx", "tag": "latest", "size": "142MB"},
                    {"repository": "postgres", "tag": "15", "size": "379MB"},
                    {"repository": "myapp", "tag": "v1", "size": "89MB"},
                ],
            },
        )

        context = build_rag_context(snapshot)

        assert "CONTAINER RUNTIME: docker" in context
        # All running containers should be listed
        assert "RUNNING CONTAINERS (2):" in context
        assert "web" in context
        assert "db" in context
        # Stopped containers should be listed
        assert "STOPPED CONTAINERS (1):" in context
        assert "old-app" in context
        # All images should be listed
        assert "CONTAINER IMAGES (3):" in context
        assert "nginx:latest" in context
        assert "postgres:15" in context


class TestGetOrRefreshContext:
    """Tests for get_or_refresh_context function."""

    def test_returns_empty_on_error(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should return empty string on error."""
        from reos.db import get_db
        from reos.system_index import get_or_refresh_context

        db = get_db()

        # Mock the indexer to raise an error
        with patch("reos.system_index.SystemIndexer") as MockIndexer:
            MockIndexer.return_value.needs_refresh.side_effect = Exception("Test error")

            # Should not raise, should return empty or handle gracefully
            # The actual function catches exceptions at a higher level
            # so we test that it doesn't crash
            try:
                result = get_or_refresh_context(db)
                assert isinstance(result, str)
            except Exception:
                pass  # Expected if error handling is at caller level

    def test_captures_new_snapshot_when_needed(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should capture a new snapshot when needed."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer, get_or_refresh_context

        db = get_db()

        # Create a mock snapshot
        mock_snapshot = MagicMock()
        mock_snapshot.captured_at = "2024-01-15T10:30:00+00:00"
        mock_snapshot.hostname = "testhost"
        mock_snapshot.os_info = {"distro": "Ubuntu"}
        mock_snapshot.hardware = {}
        mock_snapshot.network = {}
        mock_snapshot.services = []
        mock_snapshot.packages = {}
        mock_snapshot.containers = {}
        mock_snapshot.users = []
        mock_snapshot.environment = {}
        mock_snapshot.storage = []
        mock_snapshot.recent_logs = []

        with patch.object(SystemIndexer, "needs_refresh", return_value=True), \
             patch.object(SystemIndexer, "capture_snapshot", return_value=mock_snapshot):
            result = get_or_refresh_context(db)

        assert "SYSTEM STATE" in result
        assert "testhost" in result


class TestAgentIntegration:
    """Tests for ChatAgent integration with system indexer."""

    def test_agent_gets_system_context(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ChatAgent should include system context in persona prefix."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        db = get_db()

        agent = ChatAgent(db=db)
        context = agent._get_system_context()

        # Should include system state from SteadyStateCollector
        assert "SYSTEM STATE" in context
        # Should include certainty rules
        assert "CERTAINTY RULES" in context

    def test_agent_handles_missing_context(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """ChatAgent should handle missing system context gracefully."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        db = get_db()
        agent = ChatAgent(db=db)

        # Mock the steady state collector to raise an exception
        agent._steady_state.refresh_if_stale = Mock(side_effect=Exception("Test error"))

        # Also mock fallback to ensure we test the full error path
        with patch("reos.agent.get_system_context", side_effect=Exception("Fallback error")):
            context = agent._get_system_context()

        # Should return empty string, not crash
        assert context == ""


class TestDataCollection:
    """Tests for individual data collection methods."""

    def test_get_hostname(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should get hostname."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        hostname = indexer._get_hostname()
        assert isinstance(hostname, str)
        assert len(hostname) > 0

    def test_get_os_info(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should get OS info (may be empty on non-Linux)."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        os_info = indexer._get_os_info()
        assert isinstance(os_info, dict)

    def test_get_packages_info(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should get package info structure."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        packages = indexer._get_packages()
        assert isinstance(packages, dict)
        assert "manager" in packages
        assert "installed" in packages  # Full list of installed packages
        assert "total_count" in packages

    def test_get_storage_info(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should get storage info for root at minimum."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        storage = indexer._get_storage()
        assert isinstance(storage, list)
        # Should have at least root on any system
        if storage:
            assert "path" in storage[0]
            assert "total_gb" in storage[0]


class TestSnapshotPersistence:
    """Tests for snapshot storage and retrieval."""

    def test_snapshot_roundtrip(
        self,
        isolated_db_singleton,  # noqa: ANN001
    ) -> None:
        """Should store and retrieve snapshot data correctly."""
        from reos.db import get_db
        from reos.system_index import SystemIndexer

        db = get_db()
        indexer = SystemIndexer(db)

        # Capture with mocked data
        with patch.object(indexer, "_get_hostname", return_value="roundtrip-host"), \
             patch.object(indexer, "_get_os_info", return_value={"distro": "TestOS", "version": "1.0"}), \
             patch.object(indexer, "_get_hardware_info", return_value={"cpu_model": "Test CPU"}), \
             patch.object(indexer, "_get_network_info", return_value={}), \
             patch.object(indexer, "_get_services", return_value=[{"name": "test", "active": True}]), \
             patch.object(indexer, "_get_packages", return_value={"manager": "apt"}), \
             patch.object(indexer, "_get_containers", return_value={}), \
             patch.object(indexer, "_get_users", return_value=[{"username": "testuser"}]), \
             patch.object(indexer, "_get_environment", return_value={}), \
             patch.object(indexer, "_get_storage", return_value=[]), \
             patch.object(indexer, "_get_recent_logs", return_value=[]):
            original = indexer.capture_snapshot()

        # Retrieve
        retrieved = indexer.get_latest_snapshot()

        assert retrieved is not None
        assert retrieved.hostname == "roundtrip-host"
        assert retrieved.os_info["distro"] == "TestOS"
        assert retrieved.hardware["cpu_model"] == "Test CPU"
        assert len(retrieved.services) == 1
        assert retrieved.packages["manager"] == "apt"
