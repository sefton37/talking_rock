"""Integration tests for database integrity.

Tests SQLite safety features: foreign keys, transactions, schema versioning.
"""

import sqlite3
import threading
from pathlib import Path

import pytest

from reos.db import Database
from reos.migrations import MigrationRunner


class TestForeignKeyEnforcement:
    """Test that foreign key constraints are enforced."""

    def test_fk_violation_raises_integrity_error(self, tmp_path: Path) -> None:
        """Inserting a record with invalid FK should fail."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        # Try to insert a message with non-existent conversation_id
        conn = db.connect()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, message_type, created_at)
                VALUES ('msg-1', 'nonexistent-conv', 'user', 'hello', 'text', '2024-01-01')
                """
            )

    def test_fk_valid_insert_succeeds(self, tmp_path: Path) -> None:
        """Inserting a record with valid FK should succeed."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        conn = db.connect()

        # First create a conversation
        conn.execute(
            """
            INSERT INTO conversations (id, started_at, last_active_at)
            VALUES ('conv-1', '2024-01-01', '2024-01-01')
            """
        )

        # Then insert a message with valid FK
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, message_type, created_at)
            VALUES ('msg-1', 'conv-1', 'user', 'hello', 'text', '2024-01-01')
            """
        )
        conn.commit()

        # Verify it was inserted
        result = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        assert result[0] == 1

    def test_cascade_delete_works(self, tmp_path: Path) -> None:
        """Deleting parent with ON DELETE CASCADE should delete children."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        conn = db.connect()

        # Create a file entry
        conn.execute(
            """
            INSERT INTO repo_map_files (repo_path, file_path, language, sha256, indexed_at)
            VALUES ('/repo', 'file.py', 'python', 'abc123', '2024-01-01')
            """
        )

        # Get the file id
        file_id = conn.execute(
            "SELECT id FROM repo_map_files WHERE file_path = 'file.py'"
        ).fetchone()[0]

        # Create a symbol referencing it
        conn.execute(
            """
            INSERT INTO repo_symbols (file_id, name, kind, line_start, line_end)
            VALUES (?, 'my_function', 'function', 1, 10)
            """,
            (file_id,),
        )
        conn.commit()

        # Verify symbol exists
        assert conn.execute("SELECT COUNT(*) FROM repo_symbols").fetchone()[0] == 1

        # Delete the file
        conn.execute("DELETE FROM repo_map_files WHERE id = ?", (file_id,))
        conn.commit()

        # Symbol should be cascade-deleted
        assert conn.execute("SELECT COUNT(*) FROM repo_symbols").fetchone()[0] == 0


class TestTransactions:
    """Test transaction rollback on error."""

    def test_transaction_commits_on_success(self, tmp_path: Path) -> None:
        """Successful transaction should commit changes."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, started_at, last_active_at)
                VALUES ('conv-1', '2024-01-01', '2024-01-01')
                """
            )

        # Verify committed
        conn = db.connect()
        result = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        assert result[0] == 1

    def test_transaction_rollbacks_on_error(self, tmp_path: Path) -> None:
        """Failed transaction should rollback all changes."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        try:
            with db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO conversations (id, started_at, last_active_at)
                    VALUES ('conv-1', '2024-01-01', '2024-01-01')
                    """
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Verify rolled back
        conn = db.connect()
        result = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        assert result[0] == 0

    def test_nested_operations_atomic(self, tmp_path: Path) -> None:
        """Multiple operations in transaction should be atomic."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        try:
            with db.transaction() as conn:
                # First operation
                conn.execute(
                    """
                    INSERT INTO conversations (id, started_at, last_active_at)
                    VALUES ('conv-1', '2024-01-01', '2024-01-01')
                    """
                )
                # Second operation
                conn.execute(
                    """
                    INSERT INTO conversations (id, started_at, last_active_at)
                    VALUES ('conv-2', '2024-01-01', '2024-01-01')
                    """
                )
                # Third operation fails
                raise RuntimeError("Failure after partial work")
        except RuntimeError:
            pass

        # Neither should exist
        conn = db.connect()
        result = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        assert result[0] == 0


class TestWALMode:
    """Test WAL journal mode for concurrency."""

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """WAL mode should be enabled on connection."""
        db = Database(tmp_path / "test.db")
        conn = db.connect()

        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

    def test_concurrent_reads_allowed(self, tmp_path: Path) -> None:
        """Multiple readers should work concurrently with WAL."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.migrate()

        # Insert some data
        conn = db.connect()
        conn.execute(
            """
            INSERT INTO conversations (id, started_at, last_active_at)
            VALUES ('conv-1', '2024-01-01', '2024-01-01')
            """
        )
        conn.commit()

        results = []

        def read_data():
            # Create new database instance for this thread
            thread_db = Database(db_path)
            thread_conn = thread_db.connect()
            result = thread_conn.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()
            results.append(result[0])

        # Start multiple reader threads
        threads = [threading.Thread(target=read_data) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should have read the same value
        assert all(r == 1 for r in results)


class TestSchemaVersioning:
    """Test migration system."""

    def test_migration_runner_creates_version_table(self, tmp_path: Path) -> None:
        """MigrationRunner should create schema_version table."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        conn = db.connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchall()

        assert len(tables) == 1

    def test_get_current_version_zero_initially(self, tmp_path: Path) -> None:
        """Current version should be 0 before any migrations."""
        db = Database(tmp_path / "test.db")
        # Don't call migrate() - just create version table
        runner = MigrationRunner(db)

        assert runner.get_current_version() == 0

    def test_baseline_migration_applied(self, tmp_path: Path) -> None:
        """Baseline migration should be applied on migrate()."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        runner = MigrationRunner(db)
        assert runner.get_current_version() == 1

    def test_pending_migrations_empty_after_migrate(self, tmp_path: Path) -> None:
        """No pending migrations after full migrate()."""
        db = Database(tmp_path / "test.db")
        db.migrate()

        runner = MigrationRunner(db)
        pending = runner.get_pending_migrations()

        # Should have no pending (only 001 exists and it's applied)
        assert len(pending) == 0


class TestBusyTimeout:
    """Test busy timeout for lock contention."""

    def test_busy_timeout_set(self, tmp_path: Path) -> None:
        """Busy timeout should be configured."""
        db = Database(tmp_path / "test.db")
        conn = db.connect()

        result = conn.execute("PRAGMA busy_timeout").fetchone()
        assert result[0] == 5000  # 5 seconds
