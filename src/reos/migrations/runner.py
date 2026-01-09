"""Migration runner for schema versioning.

Applies SQL migration files in order, tracking applied versions.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.db import Database

logger = logging.getLogger(__name__)

# Directory containing migration SQL files
MIGRATIONS_DIR = Path(__file__).parent / "versions"


class MigrationError(Exception):
    """Raised when a migration fails."""

    pass


class MigrationRunner:
    """Runs database migrations in order.

    Migration files must be named NNN_description.sql where NNN is a
    zero-padded version number (e.g., 001_initial.sql, 002_add_index.sql).
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Create the schema_version table if it doesn't exist."""
        conn = self.db.connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT,
                checksum TEXT
            )
            """
        )
        conn.commit()

    def get_current_version(self) -> int:
        """Get the current schema version (0 if no migrations applied)."""
        conn = self.db.connect()
        result = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return result[0] or 0

    def get_pending_migrations(self) -> list[tuple[int, str, Path]]:
        """Get list of migrations that haven't been applied yet.

        Returns:
            List of (version, description, path) tuples.
        """
        current = self.get_current_version()
        pending = []

        if not MIGRATIONS_DIR.exists():
            return pending

        pattern = re.compile(r"^(\d+)_(.+)\.sql$")

        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            match = pattern.match(sql_file.name)
            if not match:
                logger.warning(f"Skipping malformed migration file: {sql_file.name}")
                continue

            version = int(match.group(1))
            description = match.group(2).replace("_", " ")

            if version > current:
                pending.append((version, description, sql_file))

        return pending

    def apply_migration(self, version: int, description: str, path: Path) -> None:
        """Apply a single migration file.

        Args:
            version: Migration version number.
            description: Human-readable description.
            path: Path to the SQL file.

        Raises:
            MigrationError: If the migration fails.
        """
        logger.info(f"Applying migration {version:03d}: {description}")

        try:
            sql = path.read_text()

            # Calculate checksum for verification
            import hashlib

            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

            # Apply migration within transaction
            with self.db.transaction() as conn:
                # Execute the migration SQL
                conn.executescript(sql)

                # Record the migration
                conn.execute(
                    """
                    INSERT INTO schema_version (version, applied_at, description, checksum)
                    VALUES (?, ?, ?, ?)
                    """,
                    (version, datetime.now(UTC).isoformat(), description, checksum),
                )

            logger.info(f"Migration {version:03d} applied successfully")

        except sqlite3.Error as e:
            raise MigrationError(f"Migration {version:03d} failed: {e}") from e
        except Exception as e:
            raise MigrationError(f"Migration {version:03d} failed: {e}") from e

    def run_pending(self) -> int:
        """Apply all pending migrations in order.

        Returns:
            Number of migrations applied.

        Raises:
            MigrationError: If any migration fails.
        """
        pending = self.get_pending_migrations()

        if not pending:
            logger.debug("No pending migrations")
            return 0

        logger.info(f"Found {len(pending)} pending migration(s)")

        for version, description, path in pending:
            self.apply_migration(version, description, path)

        return len(pending)

    def verify_integrity(self) -> bool:
        """Verify that applied migrations match their checksums.

        Returns:
            True if all checksums match, False otherwise.
        """
        conn = self.db.connect()
        applied = conn.execute(
            "SELECT version, checksum FROM schema_version ORDER BY version"
        ).fetchall()

        pattern = re.compile(r"^(\d+)_(.+)\.sql$")

        for version, stored_checksum in applied:
            if stored_checksum is None:
                continue

            # Find the migration file
            for sql_file in MIGRATIONS_DIR.glob("*.sql"):
                match = pattern.match(sql_file.name)
                if match and int(match.group(1)) == version:
                    import hashlib

                    content = sql_file.read_text()
                    current_checksum = hashlib.sha256(content.encode()).hexdigest()[:16]

                    if current_checksum != stored_checksum:
                        logger.error(
                            f"Migration {version:03d} checksum mismatch! "
                            f"Expected {stored_checksum}, got {current_checksum}"
                        )
                        return False
                    break

        return True


def run_migrations(db: Database) -> int:
    """Convenience function to run all pending migrations.

    Args:
        db: Database instance.

    Returns:
        Number of migrations applied.
    """
    runner = MigrationRunner(db)
    return runner.run_pending()
