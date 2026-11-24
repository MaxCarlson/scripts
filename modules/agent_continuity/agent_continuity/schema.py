"""SQLite schema definition and migrations for the materialized continuity index."""

from __future__ import annotations

import sqlite3

from .errors import ContinuityError, ErrorCode
from .identifiers import now_utc_iso

SCHEMA_VERSION = 2

_DDL_V1 = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingested_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    observed_timestamp TEXT NOT NULL,
    spool_file TEXT,
    checksum TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    repo_paths_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gui_conversations (
    gui_ref_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT,
    relationship TEXT NOT NULL DEFAULT 'primary',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS environments (
    environment_id TEXT PRIMARY KEY,
    runtime_kind TEXT NOT NULL,
    distro TEXT,
    hostname TEXT,
    label TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_root_id TEXT,
    parent_session_id TEXT,
    surface TEXT,
    native_version TEXT,
    cwd_native TEXT,
    cwd_canonical TEXT,
    repository_identity TEXT,
    native_title TEXT,
    transcript_reference TEXT,
    created_at TEXT,
    first_observed_at TEXT NOT NULL,
    last_seen_at TEXT,
    last_turn_at TEXT,
    last_completed_turn_at TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    metadata_source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, environment_id, native_session_id)
);

CREATE TABLE IF NOT EXISTS associations (
    association_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    association_method TEXT NOT NULL,
    evidence_summary TEXT,
    evidence_reference TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    first_turn_id TEXT,
    last_turn_id TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (provider, environment_id, native_session_id)
        REFERENCES sessions(provider, environment_id, native_session_id)
);

CREATE TABLE IF NOT EXISTS association_evidence (
    evidence_id TEXT PRIMARY KEY,
    association_id TEXT NOT NULL REFERENCES associations(association_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    provider TEXT,
    environment_id TEXT,
    native_session_id TEXT,
    workflow_id TEXT,
    source_timestamp TEXT NOT NULL,
    observed_timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    workflow_id TEXT,
    evidence_level TEXT NOT NULL DEFAULT 'unknown',
    marker_text TEXT,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (provider, environment_id, native_session_id)
        REFERENCES sessions(provider, environment_id, native_session_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    workflow_id TEXT,
    provider TEXT,
    environment_id TEXT,
    native_session_id TEXT,
    repository_identity TEXT,
    commit_sha TEXT,
    branch_name TEXT,
    validation_command TEXT,
    exit_code INTEGER,
    evidence_source TEXT NOT NULL,
    user_accepted INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_state (
    scanner_id TEXT PRIMARY KEY,
    cursor_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_capabilities (
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    version TEXT,
    capabilities_json TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (provider, environment_id)
);

CREATE TABLE IF NOT EXISTS dispatcher_gui_conversations (
    gui_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    alias_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_activity_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_slots (
    slot_id TEXT PRIMARY KEY,
    gui_id TEXT NOT NULL REFERENCES dispatcher_gui_conversations(gui_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_activity_at TEXT,
    UNIQUE(gui_id, name_key)
);

CREATE TABLE IF NOT EXISTS agent_slot_activations (
    activation_id TEXT PRIMARY KEY,
    slot_id TEXT NOT NULL REFERENCES agent_slots(slot_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    provenance TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    UNIQUE(slot_id, sequence)
);

CREATE TABLE IF NOT EXISTS dispatcher_pending_launches (
    launch_id TEXT PRIMARY KEY,
    slot_id TEXT NOT NULL REFERENCES agent_slots(slot_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    cwd TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_session_id TEXT,
    failure_detail TEXT
);

CREATE TABLE IF NOT EXISTS dispatcher_review_cycles (
    cycle_id TEXT PRIMARY KEY,
    original_slot_id TEXT NOT NULL REFERENCES agent_slots(slot_id),
    reviewer_slot_id TEXT NOT NULL REFERENCES agent_slots(slot_id),
    original_provider TEXT NOT NULL,
    original_environment_id TEXT NOT NULL,
    original_session_id TEXT NOT NULL,
    original_state TEXT NOT NULL,
    reviewer_provider TEXT,
    reviewer_environment_id TEXT,
    reviewer_session_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dispatcher_review_cycle_slots
    ON dispatcher_review_cycles(original_slot_id, reviewer_slot_id, status);

CREATE INDEX IF NOT EXISTS idx_workflows_slug ON workflows(slug);
CREATE INDEX IF NOT EXISTS idx_gui_workflow ON gui_conversations(workflow_id);
CREATE INDEX IF NOT EXISTS idx_gui_canonical_url ON gui_conversations(canonical_url);
CREATE INDEX IF NOT EXISTS idx_sessions_repo ON sessions(repository_identity);
CREATE INDEX IF NOT EXISTS idx_associations_workflow ON associations(workflow_id, status);
CREATE INDEX IF NOT EXISTS idx_associations_session ON associations(provider, environment_id, native_session_id, status);
CREATE INDEX IF NOT EXISTS idx_activity_observed ON activity_events(observed_timestamp);
CREATE INDEX IF NOT EXISTS idx_dispatcher_gui_activity ON dispatcher_gui_conversations(status, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_agent_slots_gui_state ON agent_slots(gui_id, state, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_agent_slot_activations_slot ON agent_slot_activations(slot_id, sequence);
"""


def configure_connection(conn: sqlite3.Connection, *, read_only: bool = False) -> None:
    """Apply consistent SQLite pragmas and row factory."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL;")


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the stored schema version or None if uninitialized."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_metadata'"
    ).fetchone()
    if row is None:
        return None
    ver_row = conn.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if ver_row is None:
        return None
    try:
        return int(ver_row["value"])
    except (TypeError, ValueError):
        return None


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Initialize or migrate the SQLite schema to SCHEMA_VERSION."""
    configure_connection(conn, read_only=False)
    current = get_schema_version(conn)
    if current is None:
        conn.executescript(_DDL_V1)
        now = now_utc_iso()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('initialized_at', ?)",
                (now,),
            )
        return SCHEMA_VERSION
    if current == 1:
        conn.executescript(_DDL_V1)
        now = now_utc_iso()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('migrated_at', ?)",
                (now,),
            )
        return SCHEMA_VERSION
    if current > SCHEMA_VERSION:
        raise ContinuityError(
            ErrorCode.REGISTRY_REBUILD_REQUIRED,
            f"Database schema version {current} is newer than supported version {SCHEMA_VERSION}.",
            {"db_version": current, "supported_version": SCHEMA_VERSION},
        )
    return current
