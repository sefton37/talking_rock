-- Migration 001: Baseline
-- Establishes the baseline schema version for existing databases.
-- All tables are created by db.migrate() - this migration just marks the version.

-- This is a no-op migration that establishes version 1 as the baseline.
-- Future migrations (002+) will contain actual schema changes.

-- Verify schema_version table exists (created by runner before this runs)
SELECT 1;
