from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .settings import settings


class Database:
    """Local SQLite database for ReOS events, sessions, and classifications."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.data_dir / "reos.db"
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open or return an existing connection."""
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _execute(self, query: str, params: tuple[object, ...] | None = None) -> sqlite3.Cursor:
        """Execute a query and return the cursor."""
        conn = self.connect()
        if params is None:
            return conn.execute(query)
        return conn.execute(query, params)

    def migrate(self) -> None:
        """Create tables if they don't exist."""
        conn = self.connect()

        # Events table: raw ingested metadata-only events (git snapshots, checkpoints, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                kind TEXT,
                ts TEXT NOT NULL,
                payload_metadata TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        # Sessions table: logical groupings of attention (by repo/folder + time window)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                workspace_folder TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                event_count INTEGER DEFAULT 0,
                switch_count INTEGER DEFAULT 0,
                coherence_score REAL,
                revolution_phase TEXT,
                evolution_phase TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        # Classifications table: explainable labels (fragmentation, frayed mind, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classifications (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                kind TEXT NOT NULL,
                severity TEXT,
                explanation TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )

        # Audit log: all mutations with context (for transparency + replay).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                before_state TEXT,
                after_state TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )

        conn.commit()

    def insert_event(
        self,
        event_id: str,
        source: str,
        kind: str | None,
        ts: str,
        payload_metadata: str | None,
        note: str | None,
    ) -> None:
        """Insert an event into the database."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO events
            (id, source, kind, ts, payload_metadata, note, created_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, source, kind, ts, payload_metadata, note, now, now),
        )
        self.connect().commit()

    def iter_events_recent(self, limit: int | None = None) -> list[dict[str, object]]:
        """Retrieve recent events from the database."""
        if limit is None:
            limit = 1000

        rows = self._execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]

    def insert_session(
        self,
        session_id: str,
        workspace_folder: str | None,
        started_at: str,
        event_count: int = 0,
        switch_count: int = 0,
    ) -> None:
        """Insert a session."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO sessions
            (id, workspace_folder, started_at, event_count, switch_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, workspace_folder, started_at, event_count, switch_count, now),
        )
        self.connect().commit()

    def insert_classification(
        self,
        classification_id: str,
        session_id: str | None,
        kind: str,
        severity: str | None,
        explanation: str | None,
    ) -> None:
        """Insert a classification label."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO classifications
            (id, session_id, kind, severity, explanation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (classification_id, session_id, kind, severity, explanation, now),
        )
        self.connect().commit()

    def iter_classifications_for_session(self, session_id: str) -> list[dict[str, object]]:
        """Get all classifications for a session."""
        rows = self._execute(
            "SELECT * FROM classifications WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


_db_instance: Database | None = None


def get_db() -> Database:
    """Get or create the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
        _db_instance.migrate()
    return _db_instance

