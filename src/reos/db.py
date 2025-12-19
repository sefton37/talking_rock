from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .settings import settings


class Database:
    """Local SQLite database for ReOS events, sessions, and classifications."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.data_dir / "reos.db"
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        """Open or return an existing connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close the database connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

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

        # Discovered git repositories (metadata-only).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repos (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                remote_summary TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        # Projects are user-declared meaning containers (1 project -> 1 repo).
        # NOTE: `projects` was an earlier minimal version. Keep it for backwards
        # compatibility with existing local DB files; new code should use
        # `project_charter`.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                charter_text TEXT NOT NULL,
                repo_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES repos(id)
            )
            """
        )

        # Project charter: authoritative, human-authored, slow-changing.
        # One row per project.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_charter (
                project_id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                project_owner TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_reaffirmed_at TEXT NOT NULL,

                core_intent TEXT NOT NULL,
                problem_statement TEXT NOT NULL,
                non_goals TEXT NOT NULL,

                definition_of_done TEXT NOT NULL,
                success_signals TEXT NOT NULL,
                failure_conditions TEXT NOT NULL,
                sunset_criteria TEXT NOT NULL,

                time_horizon TEXT NOT NULL,
                energy_profile TEXT NOT NULL,
                allowed_scope TEXT NOT NULL,
                forbidden_scope TEXT NOT NULL,

                primary_values TEXT NOT NULL,
                acceptable_tradeoffs TEXT NOT NULL,
                unacceptable_tradeoffs TEXT NOT NULL,

                attention_budget TEXT NOT NULL,
                distraction_tolerance TEXT NOT NULL,
                intervention_style TEXT NOT NULL,

                origin_story TEXT,
                current_state_summary TEXT,

                updated_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES repos(id)
            )
            """
        )

        # App state: small key/value store for local UI + tool coordination.
        # Example: active_project_id.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Agent personas: saved system prompt/context + a few knobs.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_personas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                system_prompt TEXT NOT NULL,
                default_context TEXT NOT NULL,
                temperature REAL NOT NULL,
                top_p REAL NOT NULL,
                tool_call_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        conn.commit()

    def set_active_persona_id(self, *, persona_id: str | None) -> None:
        """Set the active agent persona id."""
        self.set_state(key="active_persona_id", value=persona_id)

    def get_active_persona_id(self) -> str | None:
        """Get the active agent persona id."""
        return self.get_state(key="active_persona_id")

    def upsert_agent_persona(
        self,
        *,
        persona_id: str,
        name: str,
        system_prompt: str,
        default_context: str,
        temperature: float,
        top_p: float,
        tool_call_limit: int,
    ) -> None:
        """Insert or update an agent persona by id.

        Name is unique; if a different persona already uses the name, SQLite will raise.
        """

        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO agent_personas
            (id, name, system_prompt, default_context, temperature, top_p, tool_call_limit,
             created_at, updated_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                system_prompt = excluded.system_prompt,
                default_context = excluded.default_context,
                temperature = excluded.temperature,
                top_p = excluded.top_p,
                tool_call_limit = excluded.tool_call_limit,
                updated_at = excluded.updated_at,
                ingested_at = excluded.ingested_at
            """,
            (
                persona_id,
                name,
                system_prompt,
                default_context,
                float(temperature),
                float(top_p),
                int(tool_call_limit),
                now,
                now,
                now,
            ),
        )
        self.connect().commit()

    def get_agent_persona(self, *, persona_id: str) -> dict[str, object] | None:
        row = self._execute(
            "SELECT * FROM agent_personas WHERE id = ?",
            (persona_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def iter_agent_personas(self) -> list[dict[str, object]]:
        rows = self._execute(
            "SELECT * FROM agent_personas ORDER BY name ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def set_state(self, *, key: str, value: str | None) -> None:
        """Set a small piece of app state."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self.connect().commit()

    def get_state(self, *, key: str) -> str | None:
        """Get a small piece of app state."""
        row = self._execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return row["value"]
        return str(row[0]) if row[0] is not None else None

    def set_active_project_id(self, *, project_id: str | None) -> None:
        """Set the active project id (used to scope tools and reflections)."""
        self.set_state(key="active_project_id", value=project_id)

    def get_active_project_id(self) -> str | None:
        """Get the active project id."""
        return self.get_state(key="active_project_id")

    def get_active_project_charter(self) -> dict[str, object] | None:
        """Get the active project's charter, if any."""
        project_id = self.get_active_project_id()
        if not project_id:
            return None
        return self.get_project_charter(project_id=project_id)

    def get_active_project_repo_path(self) -> str | None:
        """Resolve the active project's linked repo path."""
        project = self.get_active_project_charter()
        if project is None:
            return None

        repo_id = project.get("repo_id")
        if not isinstance(repo_id, str) or not repo_id:
            return None

        row = self._execute("SELECT path FROM repos WHERE id = ?", (repo_id,)).fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return str(row["path"])
        return str(row[0])

    def upsert_repo(self, *, repo_id: str, path: str, remote_summary: str | None = None) -> None:
        """Insert or update a discovered repo by path."""
        now = datetime.now(UTC).isoformat()

        row = self._execute("SELECT id, first_seen_at FROM repos WHERE path = ?", (path,)).fetchone()
        if row is None:
            self._execute(
                """
                INSERT INTO repos
                (id, path, remote_summary, first_seen_at, last_seen_at, created_at, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (repo_id, path, remote_summary, now, now, now, now),
            )
        else:
            existing_id = str(row["id"]) if isinstance(row, sqlite3.Row) else str(row[0])
            self._execute(
                """
                UPDATE repos
                SET remote_summary = COALESCE(?, remote_summary),
                    last_seen_at = ?,
                    ingested_at = ?
                WHERE id = ?
                """,
                (remote_summary, now, now, existing_id),
            )

        self.connect().commit()

    def iter_repos(self) -> list[dict[str, object]]:
        """Return discovered repos (most recently seen first)."""
        rows = self._execute(
            "SELECT * FROM repos ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_repo_path(self, *, repo_id: str) -> str | None:
        """Resolve a discovered repo's path by id."""

        row = self._execute("SELECT path FROM repos WHERE id = ?", (repo_id,)).fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            val = row["path"]
            return str(val) if val is not None else None
        return str(row[0]) if row[0] is not None else None

    def insert_project_charter(self, *, record: dict[str, str]) -> None:
        """Insert a project charter.

        The caller is responsible for providing all required fields.
        """
        now = datetime.now(UTC).isoformat()
        payload = {
            **record,
            "updated_at": record.get("updated_at") or now,
            "ingested_at": record.get("ingested_at") or now,
        }

        columns = sorted(payload.keys())
        values = [payload[c] for c in columns]
        placeholders = ", ".join(["?"] * len(columns))
        col_sql = ", ".join(columns)

        self._execute(
            f"INSERT INTO project_charter ({col_sql}) VALUES ({placeholders})",
            tuple(values),
        )
        self.connect().commit()

    def update_project_charter(self, *, project_id: str, updates: dict[str, str]) -> None:
        """Update a project charter.

        Note: this does not update `last_reaffirmed_at`; reaffirmation is explicit.
        """
        if not updates:
            return

        now = datetime.now(UTC).isoformat()
        updates = {**updates, "updated_at": now, "ingested_at": now}

        assignments = ", ".join([f"{k} = ?" for k in sorted(updates.keys())])
        values = [updates[k] for k in sorted(updates.keys())]
        values.append(project_id)

        self._execute(
            f"UPDATE project_charter SET {assignments} WHERE project_id = ?",
            tuple(values),
        )
        self.connect().commit()

    def reaffirm_project_charter(self, *, project_id: str) -> None:
        """Explicitly reaffirm a charter (human-confirmed action)."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            UPDATE project_charter
            SET last_reaffirmed_at = ?, updated_at = ?, ingested_at = ?
            WHERE project_id = ?
            """,
            (now, now, now, project_id),
        )
        self.connect().commit()

    def get_project_charter(self, *, project_id: str) -> dict[str, object] | None:
        """Return a single project charter."""
        row = self._execute(
            "SELECT * FROM project_charter WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def iter_project_charters(self) -> list[dict[str, object]]:
        """Return project charters (newest updated first)."""
        rows = self._execute(
            "SELECT * FROM project_charter ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

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

