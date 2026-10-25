"""Coordinate existing collectors and persist one transactional observation cycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .events import NormalizedEvent
from .opencode import HistoryResult, OpenCodeClient
from .storage import TelemetryStore


class Recorder:
    def __init__(
        self,
        client: OpenCodeClient,
        store: TelemetryStore,
        *,
        endpoint: str,
        interval: float = 2.0,
        directory: str | None = None,
        model_metadata_provider: Callable[[str, dict[str, Any]], tuple[dict[str, Any] | None,
                                                                     dict[str, Any] | None]] | None = None,
        mcp_snapshot_provider: Callable[[], dict[str, Any] | None] | None = None,
        hardware_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.client = client
        self.store = store
        self.endpoint = endpoint
        self.interval = max(0.1, interval)
        self.directory = directory
        self.model_metadata_provider = model_metadata_provider
        self.mcp_snapshot_provider = mcp_snapshot_provider
        self.hardware_provider = hardware_provider
        self._seen_this_process: set[str] = set()
        self._model_refresh: dict[str, tuple[str | None, datetime]] = {}

    def collect_cycle(self, session_ids: Iterable[str]) -> dict[str, Any]:
        counts = {"sessions": 0, "inserted": 0, "updated": 0, "duplicates": 0,
                  "unavailable": 0, "errors": 0, "hardware_samples": 0, "jobs": 0}
        for session_id in dict.fromkeys(item for item in session_ids if isinstance(item, str) and item):
            counts["sessions"] += 1
            outcome = self._collect_session(session_id)
            for key in ("inserted", "updated", "duplicates", "hardware_samples", "jobs"):
                counts[key] += outcome.get(key, 0)
            counts["unavailable"] += int(outcome.get("unavailable", False))
            counts["errors"] += int(outcome.get("collector_error", False))
        return counts

    def _collect_session(self, session_id: str) -> dict[str, Any]:
        existed = self.store.session_exists(session_id, endpoint=self.endpoint)
        checkpoint = self.store.checkpoint_for_session(session_id, endpoint=self.endpoint) if existed else None
        history: HistoryResult | None = None
        try:
            if not existed:
                history = self.client.collect_history(session_id, self.directory)
            snapshot = self.client.poll(session_id, self.directory)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            self._record_collection_error(session_id)
            return {"unavailable": True, "collector_error": True}
        observed_at = snapshot.get("polled_at") if isinstance(snapshot.get("polled_at"), str) else _utc_now()
        event_cache = self.client.events_for_session(session_id)
        events_by_id: dict[str, NormalizedEvent] = {event.event_id: event for event in event_cache}
        if history and history.coverage.status != "unavailable":
            history_events = {event.event_id: event for event in history.events}
            history_events.update(events_by_id)
            events_by_id = history_events
            snapshot["history_coverage"] = history.coverage.__dict__

        if session_id not in self._seen_this_process and checkpoint and checkpoint.get("last_polled_at"):
            previous_poll = checkpoint["last_polled_at"]
            if previous_poll < observed_at:
                snapshot["restart_gap"] = {"started_at": previous_poll}
        self._seen_this_process.add(session_id)

        result = self.store.ingest_poll(
            "opencode", self.endpoint, session_id, snapshot, events_by_id.values()
        )
        result["unavailable"] = bool(snapshot.get("errors"))
        if self.model_metadata_provider and self._should_refresh_model(session_id, snapshot):
            try:
                limits, loaded = self.model_metadata_provider(session_id, snapshot)
            except (OSError, RuntimeError, ValueError, TypeError):
                limits, loaded = None, None
            self.store.ingest_model_configuration(
                "opencode", self.endpoint, session_id, observed_at, limits, loaded
            )
        if self.mcp_snapshot_provider:
            try:
                from .mcp import correlate_job
                raw_jobs = self.mcp_snapshot_provider()
                session_info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
                correlation = correlate_job(session_id, session_info.get("directory"), raw_jobs)
            except (OSError, ValueError, TypeError):
                result["jobs"] = 0
            else:
                result["jobs"] = self.store.save_job_snapshot(
                    "opencode", self.endpoint, session_id, correlation, observed_at
                )
        return result

    def _should_refresh_model(self, session_id: str, snapshot: dict[str, Any]) -> bool:
        info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
        model = info.get("model") if isinstance(info.get("model"), str) else None
        previous = self._model_refresh.get(session_id)
        now = datetime.now(timezone.utc)
        if previous is None or previous[0] != model or (now - previous[1]).total_seconds() >= 300:
            self._model_refresh[session_id] = (model, now)
            return True
        return False

    def sample_hardware(self, observed_at: str | None = None) -> int:
        if not self.hardware_provider:
            return 0
        try:
            values = self.hardware_provider()
        except (OSError, RuntimeError, ValueError):
            return 0
        if not isinstance(values, dict):
            return 0
        return self.store.ingest_hardware_sample(values, observed_at=observed_at)

    def _record_collection_error(self, session_id: str) -> None:
        observed_at = _utc_now()
        snapshot = {
            "polled_at": observed_at,
            "normalized_state": None,
            "history_coverage": {"status": "unavailable", "source": "unknown", "pages": 0,
                                 "limit": 0, "reason": "collector_exception"},
            "errors": {"collector": "exception"},
        }
        self.store.ingest_poll("opencode", self.endpoint, session_id, snapshot, [])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
