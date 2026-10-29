"""Local, privacy-preserving SQLite persistence for normalized observations."""

from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit

from .events import NormalizedEvent


SCHEMA_VERSION = 2
DEFAULT_RETENTION_POLICY = "manual_prune_only"
BASE_REQUIRED_TABLES = {
    "schema_metadata", "provider_instances", "sessions", "jobs", "events", "inferences",
    "compactions", "tools", "model_configurations", "hardware_samples", "collection_checkpoints",
    "collection_gaps",
}
ALERT_TABLES = {"alert_states"}
REQUIRED_TABLES = BASE_REQUIRED_TABLES | ALERT_TABLES


class TelemetryStoreError(RuntimeError):
    """The telemetry database could not be safely opened or updated."""


class UnsupportedSchemaError(TelemetryStoreError):
    """The database schema is newer than this monitor understands."""


class AmbiguousSessionError(TelemetryStoreError):
    """A session identifier exists under multiple provider instances."""


def default_database_path(
    *, platform: str | None = None, environ: dict[str, str] | None = None
) -> Path:
    environment = os.environ if environ is None else environ
    current_platform = sys.platform if platform is None else platform
    if current_platform.startswith("win"):
        root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    elif current_platform == "darwin":
        base = Path(environment.get("HOME", str(Path.home()))) / "Library" / "Application Support"
    else:
        base = Path(environment.get("XDG_DATA_HOME", str(
            Path(environment.get("HOME", str(Path.home()))) / ".local" / "share"
        )))
    return base / "llm-monitor" / "telemetry.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_stamp(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return _utc_now()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _safe_endpoint(endpoint: str) -> str:
    """Keep server identity but discard credentials, paths, queries, and fragments."""
    try:
        parts = urlsplit(endpoint)
        if not parts.scheme or not parts.hostname:
            return "unknown"
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme.lower()}://{host.lower()}{port}"
    except ValueError:
        return "unknown"


def _safe_event(event: NormalizedEvent) -> dict[str, Any]:
    # Keep nullable dataclass keys for faithful rehydration when provider timestamps are absent.
    data = dict(event.__dict__)
    target = data.get("tool_target")
    if isinstance(target, str) and target:
        if not target.startswith("sha256:"):
            data["tool_target"] = "sha256:" + hashlib.sha256(target.encode("utf-8")).hexdigest()
    return data


def _safe_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    status = coverage.get("status")
    safe_status = status if status in {"complete", "partial", "unavailable", "unknown"} else "unknown"
    source = coverage.get("source")
    safe_source = source if source in {"cursor", "legacy", "unknown"} else "unknown"
    raw_reason = coverage.get("reason")
    if not isinstance(raw_reason, str):
        reason_code = None
    elif "page limit" in raw_reason.casefold():
        reason_code = "page_limit_reached"
    elif "bounded" in raw_reason.casefold() or "limit" in raw_reason.casefold():
        reason_code = "bounded_history_window"
    elif raw_reason:
        reason_code = "provider_reported_reason"
    else:
        reason_code = None
    result: dict[str, Any] = {
        "status": safe_status,
        "source": safe_source,
        "pages": coverage.get("pages") if isinstance(coverage.get("pages"), int) else None,
        "limit": coverage.get("limit") if isinstance(coverage.get("limit"), int) else None,
        "suspected_gap": bool(coverage.get("suspected_gap")),
        "reason_code": reason_code,
    }
    for name in ("window_start", "window_end"):
        stamp = coverage.get(name)
        if isinstance(stamp, str):
            try:
                result[name] = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
    return result


def _event_uid(instance_key: str, session_id: str, event: NormalizedEvent) -> tuple[str, str]:
    stable_ids = [event.provider_id, event.part_id, event.tool_call_id]
    if any(stable_ids):
        identity = [event.category, event.event_id, *stable_ids]
        quality = "provider_id"
    else:
        # No provider identifier exists. Metadata helps keep a reorder from changing
        # the key; identical anonymous records can still collide by design.
        identity = [event.category, event.timestamp, event.subtype, event.agent, event.model,
                    event.tool_name, event.tool_target, event.outcome, event.finish_reason, event.tokens]
        quality = "derived_metadata_collision_possible"
    return _digest([instance_key, session_id, identity]), quality


class TelemetryStore:
    """A multi-process-safe SQLite store using WAL and transactional batch writes."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        readonly: bool = False,
        timeout: float = 15.0,
        initialize: bool = True,
    ):
        self.path = Path(path) if path is not None else default_database_path()
        self.readonly = readonly
        self.timeout = max(0.1, timeout)
        if readonly:
            if not self.path.is_file():
                raise TelemetryStoreError(f"telemetry database does not exist: {self.path}")
            self._check_schema()
        elif initialize:
            try:
                parent_existed = self.path.parent.exists()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                existed = self.path.exists()
                self._initialize()
                if not existed and os.name != "nt":
                    self.path.chmod(0o600)
                    if not parent_existed:
                        self.path.parent.chmod(0o700)
            except (OSError, sqlite3.DatabaseError) as exc:
                if isinstance(exc, UnsupportedSchemaError):
                    raise
                raise TelemetryStoreError(f"cannot initialize telemetry database: {type(exc).__name__}: {exc}") from exc

    def __enter__(self) -> "TelemetryStore":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def _connect(self, *, readonly: bool | None = None) -> sqlite3.Connection:
        use_readonly = self.readonly if readonly is None else readonly
        try:
            if use_readonly:
                uri = self.path.resolve().as_uri() + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=self.timeout, isolation_level=None)
            else:
                connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite3.DatabaseError as exc:
            raise TelemetryStoreError(f"cannot open telemetry database: {type(exc).__name__}: {exc}") from exc

    def _initialize(self) -> None:
        with closing(self._connect(readonly=False)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if version > SCHEMA_VERSION:
                raise UnsupportedSchemaError(
                    f"database schema {version} is newer than supported schema {SCHEMA_VERSION}; database left untouched"
                )
            if version == 0 and tables:
                raise TelemetryStoreError("database contains tables but no supported schema version; database left untouched")
            if version == 0:
                connection.execute("PRAGMA journal_mode=WAL")
                self._create_schema(connection)
                version = SCHEMA_VERSION
            elif version == 1:
                self._migrate_v1_to_v2(connection)
                version = SCHEMA_VERSION
            elif version != SCHEMA_VERSION:
                raise UnsupportedSchemaError(f"unsupported telemetry schema version {version}")
            self._verify_schema_tables(connection, version)

    def _check_schema(self) -> None:
        with closing(self._connect(readonly=True)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise UnsupportedSchemaError(
                    f"database schema {version} is newer than supported schema {SCHEMA_VERSION}"
                )
            if version not in {1, SCHEMA_VERSION}:
                raise TelemetryStoreError(f"unsupported telemetry schema version {version}")
            self._verify_schema_tables(connection, version)

    @staticmethod
    def _verify_schema_tables(connection: sqlite3.Connection, version: int | None = None) -> None:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        required = BASE_REQUIRED_TABLES | (ALERT_TABLES if version == SCHEMA_VERSION else set())
        missing = sorted(required - tables)
        if missing:
            raise TelemetryStoreError("telemetry schema is incomplete; missing tables: " + ", ".join(missing))

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            statements = (
                "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE provider_instances (instance_key TEXT PRIMARY KEY, provider_type TEXT NOT NULL, endpoint TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, UNIQUE(provider_type, endpoint))",
                "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, instance_key TEXT NOT NULL REFERENCES provider_instances(instance_key), session_id TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, state TEXT, agent TEXT, model TEXT, coverage_json TEXT NOT NULL, UNIQUE(instance_key, session_id))",
                "CREATE TABLE jobs (job_key TEXT PRIMARY KEY, instance_key TEXT NOT NULL REFERENCES provider_instances(instance_key), session_key TEXT REFERENCES sessions(session_key), job_id TEXT NOT NULL, session_id TEXT, message_id TEXT, status TEXT, started_at TEXT, updated_at TEXT, completed_at TEXT, agent TEXT, model TEXT, correlation TEXT NOT NULL, UNIQUE(instance_key, job_id))",
                "CREATE TABLE events (event_uid TEXT PRIMARY KEY, session_key TEXT NOT NULL REFERENCES sessions(session_key) ON DELETE CASCADE, timestamp TEXT, observed_at TEXT NOT NULL, source TEXT NOT NULL, category TEXT NOT NULL, subtype TEXT, provider_event_id TEXT, identity_quality TEXT NOT NULL, payload_json TEXT NOT NULL)",
                "CREATE TABLE inferences (event_uid TEXT PRIMARY KEY REFERENCES events(event_uid) ON DELETE CASCADE, input_tokens REAL, output_tokens REAL, reasoning_tokens REAL, cache_read_tokens REAL, cache_write_tokens REAL, finish_reason TEXT, duration_seconds REAL)",
                "CREATE TABLE compactions (event_uid TEXT PRIMARY KEY REFERENCES events(event_uid) ON DELETE CASCADE, operation_id TEXT, outcome TEXT, duration_seconds REAL)",
                "CREATE TABLE tools (event_uid TEXT PRIMARY KEY REFERENCES events(event_uid) ON DELETE CASCADE, tool_name TEXT, outcome TEXT, target_hash TEXT, duration_seconds REAL, is_edit INTEGER NOT NULL)",
                "CREATE TABLE model_configurations (config_key TEXT PRIMARY KEY, session_key TEXT NOT NULL REFERENCES sessions(session_key) ON DELETE CASCADE, observed_at TEXT NOT NULL, model_id TEXT, provider_id TEXT, configured_context INTEGER, configured_output INTEGER, loaded_context INTEGER, loaded_state TEXT, source_json TEXT NOT NULL)",
                "CREATE TABLE hardware_samples (sample_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL, device_id TEXT, values_json TEXT NOT NULL)",
                "CREATE TABLE collection_checkpoints (session_key TEXT PRIMARY KEY REFERENCES sessions(session_key) ON DELETE CASCADE, last_polled_at TEXT NOT NULL, last_event_at TEXT, coverage_json TEXT NOT NULL, last_error_sources_json TEXT NOT NULL)",
                "CREATE TABLE collection_gaps (gap_id TEXT PRIMARY KEY, session_key TEXT NOT NULL REFERENCES sessions(session_key) ON DELETE CASCADE, category TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL, reason_code TEXT NOT NULL, detail_json TEXT NOT NULL)",
                "CREATE TABLE alert_states (alert_id TEXT PRIMARY KEY, provider_instance_id TEXT NOT NULL, session_id TEXT NOT NULL, rule_id TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL, classification TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL, evidence_json TEXT NOT NULL, threshold REAL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_notified_at TEXT, acknowledged_at TEXT, resolved_at TEXT, last_updated TEXT NOT NULL)",
                "CREATE INDEX ix_alert_states_status_updated ON alert_states(status, last_updated)",
                "CREATE INDEX ix_events_session_time ON events(session_key, timestamp, event_uid)",
                "CREATE INDEX ix_events_category_time ON events(category, timestamp)",
                "CREATE INDEX ix_events_provider_id ON events(session_key, provider_event_id)",
                "CREATE INDEX ix_inferences_session_event ON inferences(event_uid)",
                "CREATE INDEX ix_compactions_operation ON compactions(operation_id)",
                "CREATE INDEX ix_tools_outcome ON tools(outcome, tool_name)",
                "CREATE INDEX ix_hardware_observed ON hardware_samples(observed_at)",
                "CREATE INDEX ix_gaps_session_time ON collection_gaps(session_key, started_at)",
            )
            for statement in statements:
                connection.execute(statement)
            connection.executemany(
                "INSERT INTO schema_metadata(key, value) VALUES(?, ?)",
                [("schema_version", str(SCHEMA_VERSION)), ("retention_policy", DEFAULT_RETENTION_POLICY)],
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        """Atomically add alert-state storage without changing existing telemetry rows."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE alert_states (alert_id TEXT PRIMARY KEY, provider_instance_id TEXT NOT NULL, "
                "session_id TEXT NOT NULL, rule_id TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL, "
                "classification TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL, evidence_json TEXT NOT NULL, "
                "threshold REAL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_notified_at TEXT, "
                "acknowledged_at TEXT, resolved_at TEXT, last_updated TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX ix_alert_states_status_updated ON alert_states(status, last_updated)")
            connection.execute(
                "INSERT INTO schema_metadata(key, value) VALUES('schema_version', '2') "
                "ON CONFLICT(key) DO UPDATE SET value='2'"
            )
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise TelemetryStoreError("database is open read-only")
        with closing(self._connect(readonly=False)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def ingest_poll(
        self,
        provider_type: str,
        endpoint: str,
        session_id: str,
        snapshot: dict[str, Any],
        events: Iterable[NormalizedEvent],
    ) -> dict[str, int]:
        observed_at = _normalize_stamp(snapshot.get("polled_at"))
        safe_endpoint = _safe_endpoint(endpoint)
        instance_key = _digest([provider_type, safe_endpoint])
        session_key = _digest([instance_key, session_id])
        event_list = list(events)
        inserted = updated = duplicates = 0
        session_info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
        model = session_info.get("model") if isinstance(session_info.get("model"), str) else None
        agent = session_info.get("agent") if isinstance(session_info.get("agent"), str) else None
        state = snapshot.get("normalized_state") if isinstance(snapshot.get("normalized_state"), str) else None
        coverage = snapshot.get("history_coverage") if isinstance(snapshot.get("history_coverage"), dict) else {}
        coverage = _safe_coverage(coverage)
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), dict) else {}
        latest_event_at = max((event.timestamp for event in event_list if event.timestamp), default=None)

        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO provider_instances(instance_key, provider_type, endpoint, first_seen, last_seen) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(instance_key) DO UPDATE SET last_seen=MAX(provider_instances.last_seen, excluded.last_seen)",
                (instance_key, provider_type, safe_endpoint, observed_at, observed_at),
            )
            prior = connection.execute(
                "SELECT state, last_seen FROM sessions WHERE session_key=?", (session_key,)
            ).fetchone()
            previous_state = prior["state"] if prior else None
            is_latest_observation = not prior or observed_at >= prior["last_seen"]
            connection.execute(
                "INSERT INTO sessions(session_key, instance_key, session_id, first_seen, last_seen, state, agent, model, coverage_json) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_key) DO UPDATE SET "
                "last_seen=MAX(sessions.last_seen, excluded.last_seen), "
                "state=CASE WHEN excluded.last_seen >= sessions.last_seen THEN COALESCE(excluded.state, sessions.state) ELSE sessions.state END, "
                "agent=CASE WHEN excluded.last_seen >= sessions.last_seen THEN COALESCE(excluded.agent, sessions.agent) ELSE sessions.agent END, "
                "model=CASE WHEN excluded.last_seen >= sessions.last_seen THEN COALESCE(excluded.model, sessions.model) ELSE sessions.model END, "
                "coverage_json=CASE WHEN excluded.last_seen >= sessions.last_seen THEN excluded.coverage_json ELSE sessions.coverage_json END",
                (session_key, instance_key, session_id, observed_at, observed_at, state, agent, model, _json(coverage)),
            )
            if is_latest_observation and state and state != previous_state:
                self._insert_lifecycle(connection, session_key, session_id, observed_at, previous_state, state)
                inserted += 1
            inserted += self._insert_state_observation(
                connection, session_key, session_id, observed_at, state, snapshot, coverage, errors
            )
            for event in event_list:
                uid, identity_quality = _event_uid(instance_key, session_id, event)
                payload = _safe_event(event)
                payload["identity_quality"] = identity_quality
                was_present = connection.execute("SELECT 1 FROM events WHERE event_uid=?", (uid,)).fetchone()
                connection.execute(
                    "INSERT INTO events(event_uid, session_key, timestamp, observed_at, source, category, subtype, "
                    "provider_event_id, identity_quality, payload_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(event_uid) DO UPDATE SET timestamp=excluded.timestamp, observed_at=excluded.observed_at, "
                    "subtype=excluded.subtype, payload_json=excluded.payload_json",
                    (uid, session_key, event.timestamp, event.observed_at or observed_at, event.source, event.category,
                     event.subtype, event.provider_id, identity_quality, _json(payload)),
                )
                self._upsert_detail(connection, uid, event, payload)
                if was_present:
                    duplicates += 1
                    updated += 1
                else:
                    inserted += 1
            last_event_at = max(filter(None, [latest_event_at,
                (connection.execute("SELECT last_event_at FROM collection_checkpoints WHERE session_key=?",
                                    (session_key,)).fetchone() or {"last_event_at": None})["last_event_at"]]),
                default=None)
            connection.execute(
                "INSERT INTO collection_checkpoints(session_key, last_polled_at, last_event_at, coverage_json, last_error_sources_json) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(session_key) DO UPDATE SET "
                "last_polled_at=MAX(collection_checkpoints.last_polled_at, excluded.last_polled_at), "
                "last_event_at=CASE WHEN collection_checkpoints.last_event_at IS NULL THEN excluded.last_event_at "
                "WHEN excluded.last_event_at IS NULL THEN collection_checkpoints.last_event_at "
                "ELSE MAX(collection_checkpoints.last_event_at, excluded.last_event_at) END, "
                "coverage_json=CASE WHEN excluded.last_polled_at >= collection_checkpoints.last_polled_at "
                "THEN excluded.coverage_json ELSE collection_checkpoints.coverage_json END, "
                "last_error_sources_json=CASE WHEN excluded.last_polled_at >= collection_checkpoints.last_polled_at "
                "THEN excluded.last_error_sources_json ELSE collection_checkpoints.last_error_sources_json END",
                (session_key, observed_at, last_event_at, _json(coverage), _json(sorted(errors.keys()))),
            )
            self._update_gaps(
                connection, session_key, observed_at, coverage, errors,
                snapshot.get("restart_gap") if isinstance(snapshot.get("restart_gap"), dict) else None,
            )
        return {"inserted": inserted, "updated": updated, "duplicates": duplicates}

    @staticmethod
    def _insert_lifecycle(
        connection: sqlite3.Connection, session_key: str, session_id: str,
        observed_at: str, old_state: str | None, new_state: str,
    ) -> None:
        payload = {"timestamp": observed_at, "observed_at": observed_at, "source": "monitor",
                   "category": "lifecycle", "subtype": "state_change", "session_id": session_id,
                   "from": old_state, "to": new_state, "provenance": "observed_opencode_status"}
        uid = _digest([session_key, "state", old_state, new_state, observed_at])
        connection.execute(
            "INSERT OR IGNORE INTO events(event_uid, session_key, timestamp, observed_at, source, category, subtype, "
            "provider_event_id, identity_quality, payload_json) VALUES(?, ?, ?, ?, 'monitor', 'lifecycle', 'state_change', NULL, 'observed_state_transition', ?)",
            (uid, session_key, observed_at, observed_at, _json(payload)),
        )

    @staticmethod
    def _insert_state_observation(
        connection: sqlite3.Connection, session_key: str, session_id: str, observed_at: str,
        state: str | None, snapshot: dict[str, Any], coverage: dict[str, Any], errors: dict[str, Any],
    ) -> int:
        permissions = snapshot.get("pending_permissions")
        questions = snapshot.get("pending_questions")
        payload = {
            "timestamp": observed_at,
            "observed_at": observed_at,
            "source": "monitor",
            "category": "lifecycle",
            "subtype": "state_observation",
            "session_id": session_id,
            "state": state,
            "pending_permissions": permissions if isinstance(permissions, int) and permissions >= 0 else None,
            "pending_questions": questions if isinstance(questions, int) and questions >= 0 else None,
            "coverage_status": coverage.get("status"),
            "error_sources": sorted(errors.keys()),
            "provenance": "opencode_poll_observation",
        }
        uid = _digest([session_key, "state_observation", observed_at, state,
                       payload["pending_permissions"], payload["pending_questions"]])
        cursor = connection.execute(
            "INSERT OR IGNORE INTO events(event_uid, session_key, timestamp, observed_at, source, category, subtype, "
            "provider_event_id, identity_quality, payload_json) "
            "VALUES(?, ?, ?, ?, 'monitor', 'lifecycle', 'state_observation', NULL, 'poll_observation', ?)",
            (uid, session_key, observed_at, observed_at, _json(payload)),
        )
        return max(0, cursor.rowcount)

    @staticmethod
    def _upsert_detail(
        connection: sqlite3.Connection, uid: str, event: NormalizedEvent, payload: dict[str, Any]
    ) -> None:
        tokens = event.tokens or {}
        if event.category == "inference":
            connection.execute(
                "INSERT INTO inferences(event_uid, input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, "
                "cache_write_tokens, finish_reason, duration_seconds) VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(event_uid) DO UPDATE SET input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens, "
                "reasoning_tokens=excluded.reasoning_tokens, cache_read_tokens=excluded.cache_read_tokens, "
                "cache_write_tokens=excluded.cache_write_tokens, finish_reason=excluded.finish_reason, duration_seconds=excluded.duration_seconds",
                (uid, tokens.get("input"), tokens.get("output"), tokens.get("reasoning"), tokens.get("cache_read"),
                 tokens.get("cache_write"), event.finish_reason, event.duration_seconds),
            )
        elif event.category == "compaction":
            connection.execute(
                "INSERT INTO compactions(event_uid, operation_id, outcome, duration_seconds) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(event_uid) DO UPDATE SET operation_id=excluded.operation_id, outcome=excluded.outcome, duration_seconds=excluded.duration_seconds",
                (uid, event.provider_id or event.event_id, event.outcome, event.duration_seconds),
            )
        elif event.category == "tool":
            target = payload.get("tool_target")
            connection.execute(
                "INSERT INTO tools(event_uid, tool_name, outcome, target_hash, duration_seconds, is_edit) VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(event_uid) DO UPDATE SET tool_name=excluded.tool_name, outcome=excluded.outcome, "
                "target_hash=excluded.target_hash, duration_seconds=excluded.duration_seconds, is_edit=excluded.is_edit",
                (uid, event.tool_name, event.outcome, target, event.duration_seconds,
                 int(bool(event.tool_name and event.tool_name.lower() in {"edit", "write", "patch", "multiedit"}))),
            )

    @staticmethod
    def _update_gaps(
        connection: sqlite3.Connection, session_key: str, observed_at: str,
        coverage: dict[str, Any], errors: dict[str, Any], restart_gap: dict[str, Any] | None = None,
    ) -> None:
        active: set[str] = set()
        if errors:
            for source in errors:
                active.add(f"provider_error:{source}")
        coverage_status = coverage.get("status")
        if coverage_status in {"partial", "unavailable"}:
            active.add(f"coverage:{coverage_status}:{coverage.get('source', 'unknown')}")
        for key in active:
            category, reason = key.split(":", 1)[0], key
            gap_id = _digest([session_key, key])
            connection.execute(
                "INSERT INTO collection_gaps(gap_id, session_key, category, started_at, ended_at, status, reason_code, detail_json) "
                "VALUES(?, ?, ?, ?, NULL, 'open', ?, ?) ON CONFLICT(gap_id) DO UPDATE SET ended_at=NULL, status='open', "
                "detail_json=excluded.detail_json",
                (gap_id, session_key, category, observed_at, reason,
                 _json({"coverage_status": coverage_status, "suspected_gap": bool(coverage.get("suspected_gap"))})),
            )
        if restart_gap and isinstance(restart_gap.get("started_at"), str):
            started_at = restart_gap["started_at"]
            gap_id = _digest([session_key, "monitor_offline", started_at, observed_at])
            connection.execute(
                "INSERT OR IGNORE INTO collection_gaps(gap_id, session_key, category, started_at, ended_at, status, reason_code, detail_json) "
                "VALUES(?, ?, 'monitor_offline', ?, ?, 'closed', 'monitor_restart', ?)",
                (gap_id, session_key, started_at, observed_at, _json({"collector_gap": True})),
            )
        close_categories = []
        if not errors:
            close_categories.append("provider_error")
        if coverage_status == "complete":
            close_categories.append("coverage")
        for category in close_categories:
            connection.execute(
                "UPDATE collection_gaps SET status='closed', ended_at=? WHERE session_key=? AND category=? AND status='open'",
                (observed_at, session_key, category),
            )

    def save_job_snapshot(
        self, provider_type: str, endpoint: str, session_id: str,
        correlation: dict[str, Any], observed_at: str | None = None,
    ) -> int:
        job = correlation.get("job") if isinstance(correlation.get("job"), dict) else None
        if not job or not isinstance(job.get("jobId"), str):
            return 0
        now = observed_at or _utc_now()
        instance_key = _digest([provider_type, _safe_endpoint(endpoint)])
        with self._transaction() as connection:
            session = connection.execute("SELECT session_key FROM sessions WHERE instance_key=? AND session_id=?",
                                         (instance_key, session_id)).fetchone()
            session_key = session["session_key"] if session else None
            job_id = job["jobId"]
            job_key = _digest([instance_key, job_id])
            connection.execute(
                "INSERT INTO jobs(job_key, instance_key, session_key, job_id, session_id, message_id, status, started_at, "
                "updated_at, completed_at, agent, model, correlation) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_key) DO UPDATE SET session_key=COALESCE(excluded.session_key, jobs.session_key), "
                "status=excluded.status, updated_at=excluded.updated_at, completed_at=excluded.completed_at, "
                "correlation=excluded.correlation",
                (job_key, instance_key, session_key, job_id, job.get("sessionId"), job.get("messageId"),
                 job.get("status"), job.get("startedAt"), job.get("updatedAt") or now, job.get("completedAt"),
                 job.get("agent"), job.get("model"), correlation.get("classification", "unknown")),
            )
        return 1

    def ingest_model_configuration(
        self, provider_type: str, endpoint: str, session_id: str, observed_at: str,
        limits: dict[str, Any] | None, loaded_model: dict[str, Any] | None,
    ) -> bool:
        instance_key = _digest([provider_type, _safe_endpoint(endpoint)])
        limits = limits or {}
        loaded_model = loaded_model or {}
        model_id = loaded_model.get("id") or limits.get("model_id")
        safe = {"limits_source": limits.get("source"), "context_source": loaded_model.get("context_source"),
                "api_version": loaded_model.get("api_version")}
        config_key = _digest([instance_key, session_id, observed_at, model_id, limits.get("context"),
                              limits.get("output"), loaded_model.get("context_length")])
        with self._transaction() as connection:
            session = connection.execute("SELECT session_key FROM sessions WHERE instance_key=? AND session_id=?",
                                         (instance_key, session_id)).fetchone()
            if not session:
                return False
            connection.execute(
                "INSERT OR IGNORE INTO model_configurations(config_key, session_key, observed_at, model_id, provider_id, "
                "configured_context, configured_output, loaded_context, loaded_state, source_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (config_key, session["session_key"], observed_at, model_id, limits.get("provider_id"),
                 limits.get("context"), limits.get("output"), loaded_model.get("context_length"),
                 loaded_model.get("state"), _json(safe)),
            )
        return True

    def ingest_hardware_sample(
        self, values: dict[str, Any], *, source: str = "resource_metrics",
        scope: str = "point_in_time_device_measurement", observed_at: str | None = None,
    ) -> int:
        stamp = observed_at or _utc_now()
        devices = values.get("devices") if isinstance(values.get("devices"), list) else [values]
        inserted = 0
        with self._transaction() as connection:
            for index, device in enumerate(devices):
                if not isinstance(device, dict):
                    continue
                safe = {key: device.get(key) for key in (
                    "name", "id", "load", "memory_utilization", "mem_used", "mem_free", "mem_total", "temp", "power_w"
                ) if isinstance(device.get(key), (str, int, float, bool)) or device.get(key) is None}
                device_id = str(safe.get("id", index))
                sample_id = _digest([source, stamp, device_id, safe])
                connection.execute(
                    "INSERT OR IGNORE INTO hardware_samples(sample_id, observed_at, source, scope, device_id, values_json) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (sample_id, stamp, source, scope, device_id, _json(safe)),
                )
                inserted += connection.execute("SELECT changes()").fetchone()[0]
            processes = values.get("process_memory") if isinstance(values.get("process_memory"), list) else []
            for process in processes:
                if not isinstance(process, dict):
                    continue
                safe = {
                    "pid": process.get("pid") if isinstance(process.get("pid"), int) else None,
                    "memory_bytes": process.get("memory_bytes")
                    if isinstance(process.get("memory_bytes"), (int, float)) else None,
                    "process_name_hash": hashlib.sha256(process["name"].casefold().encode("utf-8")).hexdigest()
                    if isinstance(process.get("name"), str) and process["name"] else None,
                }
                process_id = str(safe.get("pid") or "unknown")
                sample_id = _digest([source, stamp, "process", process_id, safe])
                connection.execute(
                    "INSERT OR IGNORE INTO hardware_samples(sample_id, observed_at, source, scope, device_id, values_json) "
                    "VALUES(?, ?, ?, 'process_gpu_memory', ?, ?)",
                    (sample_id, stamp, source, process_id, _json(safe)),
                )
                inserted += connection.execute("SELECT changes()").fetchone()[0]
            if values.get("available") is False and not devices and not processes:
                reason = values.get("reason_code") if values.get("reason_code") == "not_installed" else "unavailable"
                sample_id = _digest([source, stamp, "unavailable", reason])
                connection.execute(
                    "INSERT OR IGNORE INTO hardware_samples(sample_id, observed_at, source, scope, device_id, values_json) "
                    "VALUES(?, ?, ?, 'device_unavailable', NULL, ?)",
                    (sample_id, stamp, source, _json({"available": False, "reason_code": reason})),
                )
                inserted += connection.execute("SELECT changes()").fetchone()[0]
        return inserted

    def list_sessions(
        self, *, provider_type: str | None = None, endpoint: str | None = None
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            query = "SELECT s.*, p.provider_type, p.endpoint FROM sessions s JOIN provider_instances p USING(instance_key)"
            clauses, values = [], []
            if provider_type:
                clauses.append("p.provider_type=?")
                values.append(provider_type)
            if endpoint:
                clauses.append("p.endpoint=?")
                values.append(_safe_endpoint(endpoint))
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY s.last_seen DESC, s.session_id"
            return [dict(row) for row in connection.execute(query, values)]

    def session_exists(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None
    ) -> bool:
        return self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint) is not None

    def checkpoint_for_session(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None
    ) -> dict[str, Any] | None:
        session = self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint)
        if not session:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM collection_checkpoints WHERE session_key=?",
                                     (session["session_key"],)).fetchone()
        return dict(row) if row else None

    def _resolve_session(
        self, session_id: str, *, provider_type: str | None = None, endpoint: str | None = None
    ) -> sqlite3.Row | None:
        clauses, values = ["s.session_id=?"], [session_id]
        if provider_type:
            clauses.append("p.provider_type=?")
            values.append(provider_type)
        if endpoint:
            clauses.append("p.endpoint=?")
            values.append(_safe_endpoint(endpoint))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT s.*, p.provider_type, p.endpoint FROM sessions s JOIN provider_instances p USING(instance_key) WHERE "
                + " AND ".join(clauses) + " ORDER BY s.last_seen DESC", values
            ).fetchall()
        if len(rows) > 1:
            raise AmbiguousSessionError(f"session {session_id!r} exists on multiple provider instances; specify an endpoint")
        return rows[0] if rows else None

    def events_for_session(self, session_key: str, *, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        page_size = min(max(1, limit), 10000)
        start = max(0, offset)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE session_key=? ORDER BY timestamp IS NULL, timestamp, event_uid LIMIT ? OFFSET ?",
                (session_key, page_size, start),
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def session_records_page(
        self,
        session_key: str,
        *,
        limit: int = 100,
        after_timestamp: str | None = None,
        after_event_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a keyset-paginated chronological page for stable concurrent reads."""
        page_size = min(max(1, limit), 1000)
        if after_event_uid is None and after_timestamp is not None:
            raise ValueError("after_event_uid is required when after_timestamp is supplied")
        query = (
            "SELECT event_uid, session_key, timestamp, observed_at, source, category, subtype, provider_event_id, "
            "identity_quality, payload_json FROM events WHERE session_key=?"
        )
        values: list[Any] = [session_key]
        if after_event_uid is not None:
            if after_timestamp is None:
                query += " AND timestamp IS NULL AND event_uid>?"
                values.append(after_event_uid)
            else:
                query += (
                    " AND (timestamp IS NULL OR (timestamp IS NOT NULL AND "
                    "(timestamp>? OR (timestamp=? AND event_uid>?))))"
                )
                values.extend((after_timestamp, after_timestamp, after_event_uid))
        query += " ORDER BY timestamp IS NULL, timestamp, event_uid LIMIT ?"
        values.append(page_size)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def session_context(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None,
    ) -> dict[str, Any] | None:
        session = self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint)
        if not session:
            return None
        with closing(self._connect()) as connection:
            checkpoint = connection.execute(
                "SELECT * FROM collection_checkpoints WHERE session_key=?", (session["session_key"],)
            ).fetchone()
            gaps = connection.execute(
                "SELECT category, started_at, ended_at, status, reason_code, detail_json FROM collection_gaps "
                "WHERE session_key=? ORDER BY started_at", (session["session_key"],)
            ).fetchall()
            model_configs = connection.execute(
                "SELECT observed_at, model_id, provider_id, configured_context, configured_output, loaded_context, "
                "loaded_state, source_json FROM model_configurations WHERE session_key=? ORDER BY observed_at",
                (session["session_key"],),
            ).fetchall()
            jobs = connection.execute(
                "SELECT job_id, message_id, status, started_at, updated_at, completed_at, agent, model, correlation "
                "FROM jobs WHERE session_key=? ORDER BY updated_at", (session["session_key"],)
            ).fetchall()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM events WHERE session_key=?", (session["session_key"],)
            ).fetchone()[0]
            hardware_count = connection.execute(
                "SELECT COUNT(*) FROM hardware_samples WHERE observed_at >= ? AND observed_at <= ?",
                (session["first_seen"], session["last_seen"]),
            ).fetchone()[0]
        return {
            "session": dict(session),
            "coverage": json.loads(checkpoint["coverage_json"]) if checkpoint else json.loads(session["coverage_json"]),
            "checkpoint": dict(checkpoint) if checkpoint else None,
            "gaps": [dict(row) | {"detail": json.loads(row["detail_json"])} for row in gaps],
            "jobs": [dict(row) for row in jobs],
            "model_configurations": [dict(row) | {"sources": json.loads(row["source_json"])} for row in model_configs],
            "hardware_samples": self.hardware_samples(
                start_at=session["first_seen"], end_at=session["last_seen"], limit=10000
            ),
            "hardware_sample_total": hardware_count,
            "hardware_samples_truncated": hardware_count > 10000,
            "event_count": event_count,
        }

    def iter_session_records(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None,
        batch_size: int = 512,
    ) -> Iterator[dict[str, Any]]:
        """Stream chronological persisted event rows for one unambiguous session."""
        session = self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint)
        if not session:
            return
        size = min(max(1, batch_size), 10000)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "SELECT event_uid, session_key, timestamp, observed_at, source, category, subtype, provider_event_id, "
                "identity_quality, payload_json FROM events WHERE session_key=? "
                "ORDER BY timestamp IS NULL, timestamp, event_uid", (session["session_key"],)
            )
            while rows := cursor.fetchmany(size):
                for row in rows:
                    yield dict(row) | {"payload": json.loads(row["payload_json"])}

    def recent_session_records(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the latest bounded event window in chronological order."""
        page_size = min(max(1, limit), 1000)
        session = self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint)
        if not session:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT event_uid, session_key, timestamp, observed_at, source, category, subtype, provider_event_id, "
                "identity_quality, payload_json FROM events WHERE session_key=? "
                "ORDER BY timestamp IS NULL, timestamp DESC, event_uid DESC LIMIT ?",
                (session["session_key"], page_size),
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in reversed(rows)]

    def hardware_samples(
        self, *, start_at: str | None = None, end_at: str | None = None,
        limit: int = 1000, offset: int = 0,
    ) -> list[dict[str, Any]]:
        page_size = min(max(1, limit), 10000)
        start = max(0, offset)
        clauses, values = [], []
        if start_at:
            clauses.append("observed_at >= ?")
            values.append(start_at)
        if end_at:
            clauses.append("observed_at <= ?")
            values.append(end_at)
        query = "SELECT sample_id, observed_at, source, scope, device_id, values_json FROM hardware_samples"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_at, sample_id LIMIT ? OFFSET ?"
        values.extend((page_size, start))
        with closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) | {"values": json.loads(row["values_json"])} for row in rows]

    def history_bundle(
        self, session_id: str, *, provider_type: str = "opencode", endpoint: str | None = None,
        limit: int = 10000, offset: int = 0,
    ) -> dict[str, Any] | None:
        session = self._resolve_session(session_id, provider_type=provider_type, endpoint=endpoint)
        if not session:
            return None
        with closing(self._connect()) as connection:
            total_events = connection.execute("SELECT COUNT(*) FROM events WHERE session_key=?",
                                              (session["session_key"],)).fetchone()[0]
            checkpoint = connection.execute("SELECT * FROM collection_checkpoints WHERE session_key=?",
                                            (session["session_key"],)).fetchone()
            gaps = connection.execute("SELECT category, started_at, ended_at, status, reason_code, detail_json "
                                      "FROM collection_gaps WHERE session_key=? ORDER BY started_at",
                                      (session["session_key"],)).fetchall()
            model_configs = connection.execute("SELECT observed_at, model_id, provider_id, configured_context, "
                                               "configured_output, loaded_context, loaded_state, source_json "
                                               "FROM model_configurations WHERE session_key=? ORDER BY observed_at",
                                               (session["session_key"],)).fetchall()
            jobs = connection.execute("SELECT job_id, message_id, status, started_at, updated_at, completed_at, "
                                      "agent, model, correlation FROM jobs WHERE session_key=? ORDER BY updated_at",
                                      (session["session_key"],)).fetchall()
        event_rows = self.events_for_session(session["session_key"], limit=limit, offset=offset)
        norm_events = []
        lifecycle = []
        for record in event_rows:
            payload = record["payload"]
            if record["category"] == "lifecycle":
                lifecycle.append(payload)
                continue
            if record["category"] in {"message", "inference", "compaction", "tool"}:
                payload.pop("identity_quality", None)
                norm_events.append(NormalizedEvent(**payload))
        return {
            "session": dict(session),
            "coverage": json.loads(checkpoint["coverage_json"]) if checkpoint else json.loads(session["coverage_json"]),
            "checkpoint": dict(checkpoint) if checkpoint else None,
            "gaps": [dict(row) | {"detail": json.loads(row["detail_json"])} for row in gaps],
            "jobs": [dict(row) for row in jobs],
            "model_configurations": [dict(row) | {"sources": json.loads(row["source_json"])} for row in model_configs],
            "hardware_samples": self.hardware_samples(
                start_at=session["first_seen"], end_at=session["last_seen"], limit=min(max(1, limit), 1000)
            ),
            "event_records": event_rows,
            "analysis_events": norm_events,
            "lifecycle": lifecycle,
            "page": {"limit": min(max(1, limit), 10000), "offset": max(0, offset),
                     "returned": len(event_rows), "total": total_events,
                     "has_more": max(0, offset) + len(event_rows) < total_events},
        }

    def database_info(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {}
            for table in ("provider_instances", "sessions", "events", "inferences", "compactions", "tools",
                          "hardware_samples", "collection_checkpoints", "collection_gaps", "jobs"):
                counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if "alert_states" in tables:
                counts["alert_states"] = connection.execute("SELECT COUNT(*) FROM alert_states").fetchone()[0]
            span = connection.execute("SELECT MIN(observed_at), MAX(observed_at) FROM events").fetchone()
        file_paths = (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"))
        size_bytes = sum(file.stat().st_size for file in file_paths if file.exists())
        return {"path": str(self.path), "schema_version": version,
                "size_bytes": size_bytes,
                "counts": counts, "oldest_observation": span[0], "latest_observation": span[1],
                "retention_policy": DEFAULT_RETENTION_POLICY, "automatic_pruning": False}

    @property
    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def check_integrity(self) -> dict[str, Any]:
        with closing(self._connect(readonly=True)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in {1, SCHEMA_VERSION}:
                return {"ok": False, "schema_version": version, "integrity": [],
                        "error": f"unsupported schema version {version}"}
            self._verify_schema_tables(connection, version)
            rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            foreign_key_rows = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        return {"ok": rows == ["ok"] and not foreign_key_rows, "schema_version": version,
                "integrity": rows, "foreign_key_violations": foreign_key_rows}

    def list_alert_states(self, *, status: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        size = min(max(1, limit), 10000)
        with closing(self._connect()) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "alert_states" not in tables:
                return []
            query = "SELECT * FROM alert_states"
            values: tuple[Any, ...] = ()
            if status:
                query += " WHERE status=?"
                values = (status,)
            query += " ORDER BY last_updated DESC, alert_id LIMIT ?"
            rows = connection.execute(query, (*values, size)).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence_json"])} for row in rows]

    def save_alert_state(self, state: dict[str, Any]) -> None:
        if self.readonly:
            raise TelemetryStoreError("database is open read-only")
        evidence = state.get("evidence")
        evidence_json = state.get("evidence_json")
        if not isinstance(evidence_json, str):
            evidence_json = _json(evidence if isinstance(evidence, list) else [])
        last_updated = state.get("last_updated") or state.get("last_seen") or _utc_now()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO alert_states(alert_id, provider_instance_id, session_id, rule_id, category, severity, "
                "classification, status, summary, evidence_json, threshold, first_seen, last_seen, last_notified_at, "
                "acknowledged_at, resolved_at, last_updated) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(alert_id) DO UPDATE SET status=excluded.status, severity=excluded.severity, "
                "classification=excluded.classification, summary=excluded.summary, evidence_json=excluded.evidence_json, "
                "threshold=excluded.threshold, last_seen=excluded.last_seen, "
                "last_notified_at=COALESCE(excluded.last_notified_at, alert_states.last_notified_at), "
                "acknowledged_at=excluded.acknowledged_at, resolved_at=excluded.resolved_at, "
                "last_updated=excluded.last_updated",
                (state["alert_id"], state["provider_instance_id"], state["session_id"], state["rule_id"],
                 state["category"], state["severity"], state["classification"], state["status"],
                 state["summary"], evidence_json, state.get("threshold"), state["first_seen"], state["last_seen"],
                 state.get("last_notified_at"), state.get("acknowledged_at"), state.get("resolved_at"), last_updated),
            )

    def acknowledge_alert(self, alert_id: str, *, at: str | None = None) -> dict[str, Any]:
        if self.readonly:
            raise TelemetryStoreError("database is open read-only")
        stamp = _normalize_stamp(at)
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE alert_states SET status='acknowledged', acknowledged_at=COALESCE(acknowledged_at, ?), "
                "last_updated=? WHERE alert_id=? AND status IN ('active', 'acknowledged')",
                (stamp, stamp, alert_id),
            )
            if not cursor.rowcount:
                raise TelemetryStoreError(f"active alert {alert_id!r} was not found")
            row = connection.execute("SELECT * FROM alert_states WHERE alert_id=?", (alert_id,)).fetchone()
        if row is None:
            raise TelemetryStoreError(f"active alert {alert_id!r} was not found")
        return dict(row) | {"evidence": json.loads(row["evidence_json"])}

    def prune_before(self, cutoff: str, *, write: bool = False) -> dict[str, Any]:
        with closing(self._connect(readonly=not write)) as connection:
            affected = connection.execute(
                "SELECT s.session_key, s.session_id, MIN(e.timestamp) AS first_at, MAX(e.timestamp) AS last_at, COUNT(*) AS count "
                "FROM events e JOIN sessions s USING(session_key) WHERE e.timestamp < ? GROUP BY s.session_key, s.session_id",
                (cutoff,),
            ).fetchall()
            hardware_count = connection.execute("SELECT COUNT(*) FROM hardware_samples WHERE observed_at < ?",
                                                (cutoff,)).fetchone()[0]
            event_count = sum(row["count"] for row in affected)
            if not write:
                return {"written": False, "cutoff": cutoff, "events": event_count,
                        "hardware_samples": hardware_count,
                        "sessions": [{"session_id": row["session_id"], "events": row["count"],
                                      "from": row["first_at"], "to": row["last_at"]} for row in affected]}
        with self._transaction() as connection:
            for row in affected:
                gap_id = _digest([row["session_key"], "retention_pruned", cutoff])
                connection.execute(
                    "INSERT OR IGNORE INTO collection_gaps(gap_id, session_key, category, started_at, ended_at, status, reason_code, detail_json) "
                    "VALUES(?, ?, 'retention_pruned', ?, ?, 'closed', 'retention_pruned', ?)",
                    (gap_id, row["session_key"], row["first_at"] or cutoff, row["last_at"] or cutoff,
                     _json({"deleted_event_count": row["count"], "cutoff": cutoff})),
                )
            connection.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            connection.execute("DELETE FROM hardware_samples WHERE observed_at < ?", (cutoff,))
        return {"written": True, "cutoff": cutoff, "events": event_count,
                "hardware_samples": hardware_count,
                "sessions": [{"session_id": row["session_id"], "events": row["count"],
                              "from": row["first_at"], "to": row["last_at"]} for row in affected]}
