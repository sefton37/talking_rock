from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .settings import settings


class Database:
    """Local SQLite database for ReOS events, sessions, and classifications."""

    db_path: Path | str  # Can be Path or ":memory:" string

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path == ":memory:":
            self.db_path = ":memory:"
        elif db_path is None:
            self.db_path = settings.data_dir / "reos.db"
        elif isinstance(db_path, str):
            self.db_path = Path(db_path)
        else:
            self.db_path = db_path
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        """Open or return an existing connection."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        # Handle :memory: databases specially
        if isinstance(self.db_path, Path):
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

        # App state: small key/value store for local UI + tool coordination.
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

        # Conversations: chat sessions with context continuity.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                started_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                context_summary TEXT
            )
            """
        )

        # Messages: individual chat messages within conversations.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)"
        )

        # Pending approvals: commands awaiting user confirmation.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                plan_id TEXT,
                step_id TEXT,
                command TEXT NOT NULL,
                explanation TEXT,
                risk_level TEXT NOT NULL,
                affected_paths TEXT,
                undo_command TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )

        # -------------------------------------------------------------------------
        # Repository Map tables (Code Mode - semantic code understanding)
        # -------------------------------------------------------------------------

        # File index with hash for cache invalidation
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_map_files (
                id INTEGER PRIMARY KEY,
                repo_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                UNIQUE(repo_path, file_path)
            )
            """
        )

        # Symbol table (functions, classes, methods, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_symbols (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                column_start INTEGER DEFAULT 0,
                column_end INTEGER DEFAULT 0,
                parent TEXT,
                signature TEXT,
                docstring TEXT,
                decorators TEXT,
                FOREIGN KEY (file_id) REFERENCES repo_map_files(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_symbols_name ON repo_symbols(name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_symbols_kind ON repo_symbols(kind)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_symbols_file ON repo_symbols(file_id)"
        )

        # Dependency edges (import relationships)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_dependencies (
                id INTEGER PRIMARY KEY,
                from_file_id INTEGER NOT NULL,
                to_file_id INTEGER NOT NULL,
                import_type TEXT NOT NULL,
                symbols TEXT,
                FOREIGN KEY (from_file_id) REFERENCES repo_map_files(id) ON DELETE CASCADE,
                FOREIGN KEY (to_file_id) REFERENCES repo_map_files(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_deps_from ON repo_dependencies(from_file_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_deps_to ON repo_dependencies(to_file_id)"
        )

        # Embeddings for semantic search
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_embeddings (
                id INTEGER PRIMARY KEY,
                symbol_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                model TEXT NOT NULL DEFAULT 'nomic-embed-text',
                FOREIGN KEY (symbol_id) REFERENCES repo_symbols(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repo_embeddings_symbol ON repo_embeddings(symbol_id)"
        )

        # -------------------------------------------------------------------------
        # Project Memory tables (Code Mode - long-term learning)
        # -------------------------------------------------------------------------

        # Project decisions: preferences and choices that guide future work
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_decisions (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT,
                scope TEXT NOT NULL,
                keywords TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                superseded_by TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_repo ON project_decisions(repo_path)"
        )

        # Project patterns: recurring code patterns to follow
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_patterns (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                description TEXT NOT NULL,
                applies_to TEXT NOT NULL,
                example_code TEXT,
                source TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_patterns_repo ON project_patterns(repo_path)"
        )

        # User corrections: modifications user made to AI-generated code
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_corrections (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                session_id TEXT NOT NULL,
                original_code TEXT NOT NULL,
                corrected_code TEXT NOT NULL,
                file_path TEXT NOT NULL,
                correction_type TEXT NOT NULL,
                inferred_rule TEXT NOT NULL,
                promoted_to_decision TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_corrections_repo ON user_corrections(repo_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_corrections_session ON user_corrections(session_id)"
        )

        # Coding sessions: history of Code Mode sessions
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS coding_sessions (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                prompt_summary TEXT NOT NULL,
                outcome TEXT,
                files_changed TEXT,
                intent_summary TEXT,
                lessons_learned TEXT,
                contract_fulfilled INTEGER DEFAULT 0,
                iteration_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_coding_sessions_repo ON coding_sessions(repo_path)"
        )

        # Code changes: record of file modifications
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS code_changes (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                session_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                change_type TEXT NOT NULL,
                diff_summary TEXT,
                old_content_hash TEXT,
                new_content_hash TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                contract_step_id TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_changes_repo ON code_changes(repo_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_changes_session ON code_changes(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_changes_file ON code_changes(file_path)"
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
            value = row["value"]
            return str(value) if value is not None else None
        return str(row[0]) if row[0] is not None else None

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

    # -------------------------------------------------------------------------
    # Conversation methods
    # -------------------------------------------------------------------------

    def create_conversation(self, *, conversation_id: str, title: str | None = None) -> str:
        """Create a new conversation and return its ID."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO conversations (id, title, started_at, last_active_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )
        self.connect().commit()
        return conversation_id

    def get_conversation(self, *, conversation_id: str) -> dict[str, object] | None:
        """Get a conversation by ID."""
        row = self._execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def update_conversation_activity(self, *, conversation_id: str) -> None:
        """Update the last_active_at timestamp for a conversation."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            "UPDATE conversations SET last_active_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        self.connect().commit()

    def update_conversation_title(self, *, conversation_id: str, title: str) -> None:
        """Update the title of a conversation."""
        self._execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        self.connect().commit()

    def iter_conversations(self, limit: int = 50) -> list[dict[str, object]]:
        """List recent conversations (most recent first)."""
        rows = self._execute(
            "SELECT * FROM conversations ORDER BY last_active_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Message methods
    # -------------------------------------------------------------------------

    def add_message(
        self,
        *,
        message_id: str,
        conversation_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        metadata: str | None = None,
    ) -> str:
        """Add a message to a conversation."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, message_type, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content, message_type, metadata, now),
        )
        # Update conversation activity
        self._execute(
            "UPDATE conversations SET last_active_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        self.connect().commit()
        return message_id

    def get_messages(
        self,
        *,
        conversation_id: str,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Get messages for a conversation (oldest first for context building)."""
        if before_id:
            rows = self._execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND created_at < (
                    SELECT created_at FROM messages WHERE id = ?
                )
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (conversation_id, before_id, limit),
            ).fetchall()
        else:
            rows = self._execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_messages(
        self,
        *,
        conversation_id: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Get the most recent messages for LLM context (returns in chronological order)."""
        rows = self._execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) ORDER BY created_at ASC
            """,
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def clear_messages(self, *, conversation_id: str) -> int:
        """Clear all messages from a conversation.

        Returns:
            Number of messages deleted
        """
        cursor = self._execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.connect().commit()
        return cursor.rowcount

    # -------------------------------------------------------------------------
    # Approval methods
    # -------------------------------------------------------------------------

    def create_approval(
        self,
        *,
        approval_id: str,
        conversation_id: str,
        command: str,
        explanation: str | None = None,
        risk_level: str = "medium",
        affected_paths: str | None = None,
        undo_command: str | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> str:
        """Create a pending approval request."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO pending_approvals
            (id, conversation_id, plan_id, step_id, command, explanation,
             risk_level, affected_paths, undo_command, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                approval_id,
                conversation_id,
                plan_id,
                step_id,
                command,
                explanation,
                risk_level,
                affected_paths,
                undo_command,
                now,
            ),
        )
        self.connect().commit()
        return approval_id

    def get_approval(self, *, approval_id: str) -> dict[str, object] | None:
        """Get an approval by ID."""
        row = self._execute(
            "SELECT * FROM pending_approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_pending_approvals(
        self,
        *,
        conversation_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Get all pending approvals, optionally filtered by conversation."""
        if conversation_id:
            rows = self._execute(
                """
                SELECT * FROM pending_approvals
                WHERE status = 'pending' AND conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()
        else:
            rows = self._execute(
                """
                SELECT * FROM pending_approvals
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_approval(
        self,
        *,
        approval_id: str,
        status: str,  # 'approved', 'rejected', 'expired'
    ) -> None:
        """Resolve an approval request."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            UPDATE pending_approvals
            SET status = ?, resolved_at = ?
            WHERE id = ?
            """,
            (status, now, approval_id),
        )
        self.connect().commit()


_db_instance: Database | None = None


def get_db() -> Database:
    """Get or create the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
        _db_instance.migrate()
    return _db_instance

