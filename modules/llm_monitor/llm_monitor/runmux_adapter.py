"""Framework-neutral, read-only data adapter for an authenticated Runmux host.

This module does not define HTTP routes or authentication. A host should mount these
methods behind its existing protected API boundary and share one service instance.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .observability import ObservabilityService
from .storage import TelemetryStore


RUNMUX_API_SCHEMA_VERSION = 1
DEFAULT_TIMELINE_LIMIT = 100
MAX_TIMELINE_LIMIT = 500
MAX_ALERT_LIMIT = 500
_OMIT_KEYS = {
    "api_token", "authorization", "command", "database_path", "directory", "environment", "evidence_json",
    "environment_variables", "input_text", "output_text", "path", "prompt", "raw",
    "response_text", "tool_arguments", "tool_output", "working_directory",
}


class RunmuxMonitoringAdapter:
    """Expose bounded snapshots and persisted evidence without collecting or writing.

    The adapter intentionally has no Runmux dependency. It consumes the same
    ``ObservabilityService`` and ``TelemetryStore`` as the CLI and terminal UI.
    """

    def __init__(self, service: ObservabilityService, *, database_path: str | Path | None = None,
                 refresh_interval_seconds: float = 1.0):
        if refresh_interval_seconds < 0:
            raise ValueError("refresh_interval_seconds must be non-negative")
        self.service = service
        self.database_path = Path(database_path) if database_path is not None else service.database_path
        self.refresh_interval_seconds = refresh_interval_seconds
        self._refresh_lock = threading.RLock()
        self._snapshot_cache: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._provider_lookup: dict[tuple[str, str], str] = {}

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return a short-lived shared snapshot; the first caller triggers collection."""
        now = time.monotonic()
        with self._refresh_lock:
            if (not force_refresh and self._snapshot_cache is not None
                    and now - self._snapshot_at < self.refresh_interval_seconds):
                return json.loads(json.dumps(self._snapshot_cache))
            raw = self.service.refresh().to_dict()
            self._provider_lookup = {
                (_safe_endpoint(row["provider_instance_id"]), row["session_id"]): row["provider_instance_id"]
                for row in raw.get("sessions", [])
                if isinstance(row, dict) and isinstance(row.get("provider_instance_id"), str)
                and isinstance(row.get("session_id"), str)
            }
            current = _sanitize(raw)
            self._snapshot_cache = current
            self._snapshot_at = time.monotonic()
            return json.loads(json.dumps(current))

    def session_detail(self, provider_instance_id: str, session_id: str) -> dict[str, Any] | None:
        """Return one provider-scoped detail snapshot, or ``None`` when unknown."""
        _validate_identity(provider_instance_id, session_id)
        with self._refresh_lock:
            provider_key = self._provider_lookup.get((_safe_endpoint(provider_instance_id), session_id),
                                                     provider_instance_id)
            detail = self.service.get_detail(provider_key, session_id)
        return _sanitize(detail.to_dict()) if detail is not None else None

    def timeline(
        self,
        provider_instance_id: str,
        session_id: str,
        *,
        limit: int = DEFAULT_TIMELINE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return a chronological page of stored session events.

        Cursors are opaque, provider/session-bound offsets. Rows and page sizes are
        bounded; callers should retain cursors only for one traversal of a snapshot.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        _validate_identity(provider_instance_id, session_id)
        page_size = min(limit, MAX_TIMELINE_LIMIT)
        after_timestamp, after_uid = _decode_cursor(cursor, provider_instance_id, session_id) if cursor else (None, None)
        base = {"schema_version": RUNMUX_API_SCHEMA_VERSION, "provider_instance_id": _safe_endpoint(provider_instance_id),
                "session_id": session_id, "limit": page_size}
        if not self.database_path.is_file():
            return base | {"availability": "unavailable", "reason": "telemetry_store_unavailable",
                           "events": [], "next_cursor": None, "coverage": {"status": "unknown"}}
        try:
            with TelemetryStore(self.database_path, readonly=True) as store:
                context = store.session_context(session_id, endpoint=provider_instance_id)
                if context is None:
                    return base | {"availability": "unavailable", "reason": "session_not_found",
                                   "events": [], "next_cursor": None, "coverage": {"status": "unknown"}}
                total = context["event_count"]
                records = store.session_records_page(context["session"]["session_key"], limit=page_size + 1,
                                                     after_timestamp=after_timestamp, after_event_uid=after_uid)
                has_more = len(records) > page_size
                visible = records[:page_size]
                events = [_sanitize(row["payload"]) for row in visible]
                last = visible[-1] if visible else None
                next_cursor = (_encode_cursor(provider_instance_id, session_id, last["timestamp"], last["event_uid"])
                               if has_more and last else None)
                return base | {"availability": "available", "events": events, "next_cursor": next_cursor,
                               "coverage": _sanitize(context["coverage"]), "total_events": total}
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            return base | {"availability": "unavailable", "reason": type(exc).__name__,
                           "events": [], "next_cursor": None, "coverage": {"status": "unknown"}}

    def alerts(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        provider_instance_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Return persisted local alert states; this method does not evaluate or write alerts."""
        if status not in {None, "active", "acknowledged", "resolved"}:
            raise ValueError("status must be active, acknowledged, resolved, or None")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if (provider_instance_id is None) != (session_id is None):
            raise ValueError("provider_instance_id and session_id must be provided together")
        if provider_instance_id is not None:
            _validate_identity(provider_instance_id, session_id or "")
        page_size = min(limit, MAX_ALERT_LIMIT)
        if not self.database_path.is_file():
            return {"schema_version": RUNMUX_API_SCHEMA_VERSION, "availability": "unavailable", "alerts": [],
                    "reason": "telemetry_store_unavailable"}
        try:
            with TelemetryStore(self.database_path, readonly=True) as store:
                records = store.list_alert_states(
                    status=status,
                    limit=MAX_ALERT_LIMIT if session_id is not None else page_size,
                    session_id=session_id,
                )
            if provider_instance_id is not None:
                safe_provider = _safe_endpoint(provider_instance_id)
                records = [row for row in records if _safe_endpoint(row.get("provider_instance_id", "")) == safe_provider]
                records = records[:page_size]
            return {"schema_version": RUNMUX_API_SCHEMA_VERSION, "availability": "available",
                    "alerts": [_sanitize(record) for record in records], "limit": page_size}
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            return {"schema_version": RUNMUX_API_SCHEMA_VERSION, "availability": "unavailable", "alerts": [],
                    "reason": type(exc).__name__}


def _encode_cursor(provider: str, session: str, timestamp: str | None, event_uid: str) -> str:
    payload = json.dumps([_safe_endpoint(provider), session, timestamp, event_uid], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, provider: str, session: str) -> tuple[str | None, str]:
    if not isinstance(cursor, str) or len(cursor) > 1024:
        raise ValueError("invalid timeline cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid timeline cursor") from exc
    if (not isinstance(payload, list) or len(payload) != 4
            or payload[0] != _safe_endpoint(provider) or payload[1] != session
            or (payload[2] is not None and not isinstance(payload[2], str))
            or not isinstance(payload[3], str) or not payload[3]):
        raise ValueError("timeline cursor does not match this provider and session")
    return payload[2], payload[3]


def _safe_endpoint(value: str) -> str:
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.hostname:
            return "unknown"
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme.lower()}://{host.lower()}{port}"
    except ValueError:
        return "unknown"


def _validate_identity(provider: str, session: str) -> None:
    if not isinstance(provider, str) or not provider or len(provider) > 2048:
        raise ValueError("provider_instance_id must be a non-empty endpoint identity")
    if not isinstance(session, str) or not session or len(session) > 512:
        raise ValueError("session_id must be a non-empty bounded identifier")


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    if key == "provider_instance_id" and isinstance(value, str):
        return _safe_endpoint(value)
    if isinstance(key, str) and key.casefold() == "error" and value:
        # Transport exception text may include credential-bearing provider URLs.
        return "provider_error"
    if key == "tool_target" and isinstance(value, str) and value:
        if value.startswith("sha256:"):
            return value
        return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    if isinstance(value, dict):
        result = {}
        for child_key, child_value in value.items():
            normalized = child_key.casefold() if isinstance(child_key, str) else ""
            if normalized in _OMIT_KEYS:
                continue
            result[child_key] = _sanitize(child_value, key=child_key if isinstance(child_key, str) else None)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value
