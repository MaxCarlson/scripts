"""SQLite schema DDL for the agent_sync coordination database.

All tables use STRICT mode (requires SQLite 3.37+). The schema tracks agents,
tasks, runs, file-level claims, handoffs, events, and run artifacts.
"""
import sqlite3

SCHEMA_VERSION = 1

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER NOT NULL PRIMARY KEY,
    applied_at     TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS agents (
    agent_name        TEXT    NOT NULL PRIMARY KEY,
    provider          TEXT    NOT NULL,
    adapter_name      TEXT    NOT NULL,
    cli_command       TEXT    NOT NULL,
    default_profile   TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    capabilities_json TEXT    NOT NULL,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT    NOT NULL PRIMARY KEY,
    parent_task_id TEXT    REFERENCES tasks(task_id) ON DELETE SET NULL,
    title          TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    priority       INTEGER NOT NULL,
    status         TEXT    NOT NULL,
    target_branch  TEXT    NOT NULL,
    manifest_path  TEXT    NOT NULL,
    summary_md     TEXT    NOT NULL,
    acceptance_md  TEXT,
    routing_json   TEXT    NOT NULL,
    scoring_json   TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    started_at     TEXT,
    completed_at   TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id  TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id)
) STRICT;

CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT    NOT NULL PRIMARY KEY,
    task_id                 TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    parent_run_id           TEXT    REFERENCES runs(run_id) ON DELETE SET NULL,
    agent_name              TEXT    NOT NULL REFERENCES agents(agent_name),
    mode                    TEXT    NOT NULL,
    status                  TEXT    NOT NULL,
    repo_root               TEXT    NOT NULL,
    cwd                     TEXT    NOT NULL,
    branch_name             TEXT    NOT NULL,
    worktree_path           TEXT    NOT NULL,
    vendor_session_id       TEXT,
    vendor_transcript_path  TEXT,
    permission_mode         TEXT,
    model_name              TEXT,
    heartbeat_at            TEXT    NOT NULL,
    started_at              TEXT    NOT NULL,
    ended_at                TEXT,
    stop_reason             TEXT,
    summary_md              TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_runs_task_status
    ON runs(task_id, status);

CREATE TABLE IF NOT EXISTS claims (
    claim_id         TEXT    NOT NULL PRIMARY KEY,
    run_id           TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id          TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    repo_root        TEXT    NOT NULL,
    path             TEXT    NOT NULL,
    path_kind        TEXT    NOT NULL,
    access_mode      TEXT    NOT NULL,
    lease_expires_at TEXT    NOT NULL,
    released_at      TEXT,
    created_at       TEXT    NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_claims_lookup
    ON claims(repo_root, path, released_at, lease_expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_exact_write_claim
    ON claims(repo_root, path)
    WHERE access_mode = 'write' AND released_at IS NULL;

CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id      TEXT NOT NULL PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    from_run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    to_agent_name   TEXT NOT NULL REFERENCES agents(agent_name),
    handoff_md_path TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    accepted_at     TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS events (
    event_id     INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id      TEXT    REFERENCES tasks(task_id) ON DELETE CASCADE,
    level        TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_events_run_created
    ON events(run_id, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id    TEXT    NOT NULL PRIMARY KEY,
    run_id         TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id        TEXT    REFERENCES tasks(task_id) ON DELETE SET NULL,
    artifact_type  TEXT    NOT NULL,
    relative_path  TEXT    NOT NULL,
    sha256         TEXT    NOT NULL,
    byte_count     INTEGER NOT NULL,
    metadata_json  TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS memory_links (
    memory_link_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    run_id         TEXT    REFERENCES runs(run_id) ON DELETE SET NULL,
    backend        TEXT    NOT NULL,
    memory_ref     TEXT    NOT NULL,
    role           TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
) STRICT;
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes. Safe to call multiple times (idempotent).

    Args:
        conn: An open SQLite connection from get_connection().
    """
    conn.executescript(_DDL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta (schema_version, applied_at) VALUES (?, datetime('now'))",
        (SCHEMA_VERSION,),
    )
    conn.commit()
