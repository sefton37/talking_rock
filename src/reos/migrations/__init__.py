"""Database migrations for Talking Rock.

Schema versioning with forward-only migrations. Each migration is a SQL file
in the versions/ directory, numbered sequentially (001_xxx.sql, 002_xxx.sql).

Usage:
    from reos.migrations import run_migrations
    run_migrations(db)  # Apply pending migrations
"""

from .runner import MigrationRunner, run_migrations

__all__ = ["MigrationRunner", "run_migrations"]
