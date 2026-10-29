"""Shared read-only application API for live and historical session observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .analysis import analyze_events
from .diagnostics import diagnose_events
from .events import NormalizedEvent
from .history_analysis import analyze_stored_session
from .opencode import ApiResult, HistoryCoverage, OpenCodeClient
from .storage import TelemetryStore, default_database_path


OBSERVABILITY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Freshness:
    status: str
    observed_at: str | None
    age_seconds: float | None
    source: str


@dataclass(frozen=True)
class SessionSummary:
    provider_instance_id: str
    session_id: str
    job_id: str | None
    model: str | None
    agent: str | None
    context_capacity: int | None
    state: str
    last_observed_state: str
    state_confidence: str
    state_source: str
    last_activity_at: str | None
    freshness: Freshness
    coverage: dict[str, Any]
    latest_inference: dict[str, Any] | None
    cumulative_tokens: dict[str, int | float] | None
    compaction_count: int | None
    current_tool: dict[str, Any] | None
    blockers: dict[str, int | None]
    diagnostic_severity: dict[str, int]
    is_live: bool
    last_error_sources: list[str] = field(default_factory=list)
    diagnostic_findings: list[dict[str, Any]] = field(default_factory=list)
    recent_context_utilization: list[dict[str, Any]] = field(default_factory=list)
    cumulative_token_scope: str = "unknown"

    @property
    def key(self) -> str:
        return f"{self.provider_instance_id}\0{self.session_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderStatus:
    provider_instance_id: str
    status: str
    checked_at: str
    error: str | None = None


@dataclass(frozen=True)
class SystemSummary:
    discovered_sessions: int
    active_inferences: int
    active_tools: int
    blocked_sessions: int
    potentially_stalled_sessions: int
    loaded_models: list[str]
    recording_status: str


@dataclass(frozen=True)
class SystemSnapshot:
    schema_version: int
    refreshed_at: str
    provider: ProviderStatus
    system: SystemSummary
    sessions: list[SessionSummary]
    hardware: dict[str, Any] | None
    database_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "refreshed_at": self.refreshed_at,
            "provider": asdict(self.provider),
            "system": asdict(self.system),
            "sessions": [session.to_dict() for session in self.sessions],
            "hardware": self.hardware,
            "database_path": self.database_path,
        }


@dataclass(frozen=True)
class SessionDetail:
    schema_version: int
    summary: SessionSummary
    recent_events: list[dict[str, Any]]
    context_utilization: list[dict[str, Any]]
    compactions: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    hardware_samples: list[dict[str, Any]]
    mcp_correlations: list[dict[str, Any]]
    completion: dict[str, Any]
    coverage: dict[str, Any]
    historical_analysis: dict[str, Any] | None
    monitoring_gaps: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ObservabilityService:
    """Collect once per refresh and expose shared versioned snapshots to UI clients.

    This service never records telemetry. Supplying ``database_path`` enables read-only
    historical queries only; persistent recording remains the ``record`` command's job.
    """

    def __init__(
        self,
        client: OpenCodeClient,
        *,
        directory: str | None = None,
        database_path: str | Path | None = None,
        stale_after_seconds: float = 15.0,
        max_sessions: int = 200,
        clock: Callable[[], datetime] | None = None,
        hardware_provider: Callable[[], dict[str, Any]] | None = None,
        model_metadata_provider: Callable[[str, dict[str, Any]], tuple[dict[str, Any] | None,
                                                                        dict[str, Any] | None]] | None = None,
        session_filter: str | None = None,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least one")
        self.client = client
        self.directory = directory
        self.database_path = Path(database_path) if database_path is not None else default_database_path()
        self.stale_after_seconds = stale_after_seconds
        self.max_sessions = max_sessions
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.hardware_provider = hardware_provider
        self.model_metadata_provider = model_metadata_provider
        self.session_filter = session_filter
        self._current: dict[str, tuple[SessionSummary, dict[str, Any], list[NormalizedEvent]]] = {}
        self._last_snapshot: SystemSnapshot | None = None

    def refresh(self) -> SystemSnapshot:
        now = self.clock().astimezone(timezone.utc)
        checked_at = now.isoformat()
        endpoint = str(getattr(self.client, "base_url", getattr(self.client, "endpoint", "unknown"))).rstrip("/")
        previous_current = self._current
        if self.session_filter:
            session_result = ApiResult(data=[{"id": self.session_filter}])
        else:
            try:
                session_result = self.client.sessions(self.directory)
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                session_result = ApiResult(data=None, error=type(exc).__name__)
        provider_error = getattr(session_result, "error", None)
        live_rows = getattr(session_result, "data", None)
        summaries: dict[str, SessionSummary] = {}
        self._current = {}

        if not provider_error and isinstance(live_rows, list):
            selected = [row for row in live_rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
            selected = selected[: self.max_sessions]
            for row in selected:
                session_id = row["id"]
                try:
                    snapshot = self.client.poll(session_id, self.directory)
                except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                    snapshot = {"session_id": session_id, "polled_at": checked_at, "normalized_state": "unknown",
                                "errors": {"poll": type(exc).__name__}, "history_coverage": {"status": "unavailable"}}
                events = self._events(session_id)
                key = f"{endpoint}\0{session_id}"
                previous = previous_current.get(key)
                errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), dict) else {}
                if previous and errors:
                    summary = _stale_summary(previous[0], checked_at, sorted(errors))
                    if not events:
                        events = previous[2]
                else:
                    summary = self._live_summary(endpoint, session_id, snapshot, events, now)
                summaries[summary.key] = summary
                self._current[summary.key] = (summary, snapshot, events)
        elif not provider_error:
            provider_error = "OpenCode returned an unsupported session-list response"
        if provider_error:
            for key, (previous_summary, previous_snapshot, previous_events) in previous_current.items():
                summary = _stale_summary(previous_summary, checked_at, ["sessions"])
                summaries[key] = summary
                self._current[key] = (summary, previous_snapshot, previous_events)

        database_available = self.database_path.is_file()
        if database_available:
            try:
                with TelemetryStore(self.database_path, readonly=True) as store:
                    for row in store.list_sessions(provider_type="opencode"):
                        key = f"{row.get('endpoint') or 'unknown'}\0{row['session_id']}"
                        if key not in summaries:
                            summary = self._historical_summary(row, now)
                            summaries[key] = summary
                            self._current[key] = (summary, {}, [])
            except (OSError, ValueError, RuntimeError) as exc:
                database_available = False
                database_error = type(exc).__name__
            else:
                database_error = None
        else:
            database_error = None

        session_values = sorted(summaries.values(), key=lambda item: (not item.is_live, item.session_id.casefold()))
        counts = {
            "discovered_sessions": len(session_values),
            "active_inferences": sum(item.is_live and item.state == "inference_running" for item in session_values),
            "active_tools": sum(item.is_live and item.state == "tool_running" for item in session_values),
            "blocked_sessions": sum(item.state in {"waiting_permission", "waiting_question"} for item in session_values),
            "potentially_stalled_sessions": sum(item.state == "possibly_stalled" for item in session_values),
            "loaded_models": sorted({item.model for item in session_values if item.model}),
            "recording_status": "not_started_by_dashboard",
        }
        if provider_error:
            provider_status = "unavailable" if not live_rows else "degraded"
        elif any(value[1].get("errors") for value in self._current.values() if value[0].is_live):
            provider_status = "degraded"
        else:
            provider_status = "connected"
        error = provider_error or (f"telemetry database unavailable: {database_error}" if database_error else None)
        hardware = None
        if self.hardware_provider:
            try:
                hardware = self.hardware_provider()
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                hardware = {"available": False, "error": type(exc).__name__}
        self._last_snapshot = SystemSnapshot(
            schema_version=OBSERVABILITY_SCHEMA_VERSION,
            refreshed_at=checked_at,
            provider=ProviderStatus(endpoint, provider_status, checked_at, error),
            system=SystemSummary(**counts),
            sessions=session_values,
            hardware=hardware,
            database_path=str(self.database_path) if database_available else None,
        )
        return self._last_snapshot

    def get_detail(self, provider_instance_id: str, session_id: str) -> SessionDetail | None:
        key = f"{provider_instance_id.rstrip('/')}\0{session_id}"
        record = self._current.get(key)
        if record is None:
            return None
        summary, snapshot, events = record
        coverage_data = snapshot.get("history_coverage") or summary.coverage
        try:
            coverage = HistoryCoverage(**coverage_data)
        except (TypeError, ValueError):
            coverage = HistoryCoverage("unknown", "unknown", 0, 0)
        analysis = analyze_events(session_id, events, coverage=coverage, session_state=summary.state)
        findings = summary.diagnostic_findings if summary.is_live else diagnose_events(
            session_id, events, analysis, coverage=coverage
        )
        recent = [event.to_dict() for event in events[-100:]]
        compactions = [event.to_dict() for event in events if event.category == "compaction"]
        utilization = summary.recent_context_utilization
        history_analysis = None
        completion = None
        gaps: list[dict[str, Any]] = []
        hardware: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        if not summary.is_live and self.database_path.is_file():
            try:
                with TelemetryStore(self.database_path, readonly=True) as store:
                    history_analysis = analyze_stored_session(store, session_id, endpoint=provider_instance_id)
                    context = store.session_context(session_id, endpoint=provider_instance_id)
                    if context:
                        gaps = context["gaps"]
                        hardware = context["hardware_samples"]
                        jobs = context["jobs"]
                        findings = history_analysis["findings"]
                        compactions = history_analysis["metrics"]["compactions"]["cycles"]
                        coverage_data = history_analysis["coverage"]
                        recent = [record["payload"] for record in store.recent_session_records(
                            session_id, endpoint=provider_instance_id, limit=100
                        )]
                        utilization = [{"event_id": item.get("event_id"), "timestamp": item.get("timestamp"),
                                        "tokens": item.get("tokens"),
                                        "utilization_percent": item.get("context_utilization_percent"),
                                        "status": "observed" if item.get("context_utilization_percent") is not None else "unknown"}
                                       for item in history_analysis["metrics"]["timeline"]["markers"]
                                       if item.get("category") == "inference"]
                        completion = history_analysis["completion"]
            except (OSError, ValueError, RuntimeError):
                pass
        completion = completion or {"inference_completion": "completed" if any(
            event.category == "inference" and event.outcome == "completed" for event in events
        ) else "unknown", "session_completion": "unknown", "work_product_completion": "unverified",
            "task_acceptance": "unverified"}
        return SessionDetail(OBSERVABILITY_SCHEMA_VERSION, summary, recent, utilization, compactions,
                             findings, hardware, jobs, completion, coverage_data, history_analysis, gaps)

    def _events(self, session_id: str) -> list[NormalizedEvent]:
        try:
            return self.client.events_for_session(session_id)
        except (AttributeError, KeyError, RuntimeError, TypeError):
            return []

    def _live_summary(self, endpoint: str, session_id: str, snapshot: dict[str, Any],
                      events: list[NormalizedEvent], now: datetime) -> SessionSummary:
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), dict) else {}
        polled_at = _parse_time(snapshot.get("polled_at"))
        age = max(0.0, (now - polled_at).total_seconds()) if polled_at else None
        stale = bool(errors) or age is None or age > self.stale_after_seconds
        observed_state = snapshot.get("normalized_state") or "unknown"
        state = "unknown" if stale else observed_state
        latest = snapshot.get("latest_completed_inference")
        if latest is None:
            latest = next((event.to_dict() for event in reversed(events)
                           if event.category == "inference" and event.outcome == "completed"), None)
        totals: dict[str, int | float] = {}
        token_available = False
        for event in events:
            if event.category == "inference" and event.outcome == "completed" and event.tokens:
                for category, value in event.tokens.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[category] = totals.get(category, 0) + value
                        token_available = True
        limits, loaded_model = (None, None)
        if self.model_metadata_provider:
            try:
                limits, loaded_model = self.model_metadata_provider(session_id, snapshot)
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
        inferred = analyze_events(session_id, events, coverage=_coverage(snapshot.get("history_coverage")),
                                  limits=limits, loaded_model=loaded_model)
        findings = diagnose_events(session_id, events, inferred, coverage=_coverage(snapshot.get("history_coverage")))
        severities: dict[str, int] = {}
        for item in findings:
            severity = item.get("severity", "info")
            severities[severity] = severities.get(severity, 0) + 1
        info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
        last_event = next((event.timestamp for event in reversed(events) if event.timestamp), None)
        return SessionSummary(
            endpoint, session_id, None, info.get("model"), info.get("agent"),
            inferred.get("context", {}).get("effective_capacity"), state, observed_state,
            "stale" if stale else "observed", "opencode_poll", last_event,
            Freshness("stale" if stale else "fresh", polled_at.isoformat() if polled_at else None, age, "opencode_poll"),
            snapshot.get("history_coverage") or {"status": "unknown"}, latest,
            totals if token_available else None,
            inferred.get("compactions", {}).get("unique_count"), snapshot.get("latest_tool"),
            {"permissions": snapshot.get("pending_permissions"), "questions": snapshot.get("pending_questions")},
            severities, True, sorted(errors.keys()), findings,
            [{"event_id": event.event_id, "timestamp": event.timestamp,
              "utilization_percent": round(event.tokens["input"] / inferred["context"]["usable_input_capacity"] * 100, 1)
              if (event.tokens and isinstance(event.tokens.get("input"), (int, float))
                  and inferred["context"].get("usable_input_capacity")) else None,
              "capacity_tokens": inferred["context"].get("usable_input_capacity"),
              "status": "observed" if inferred["context"].get("usable_input_capacity") else "unknown"}
             for event in events if event.category == "inference" and event.outcome == "completed"],
            cumulative_token_scope="bounded_in_memory_event_window",
        )

    def _historical_summary(self, row: dict[str, Any], now: datetime) -> SessionSummary:
        seen = _parse_time(row.get("last_seen"))
        age = max(0.0, (now - seen).total_seconds()) if seen else None
        return SessionSummary(
            row.get("endpoint") or "unknown", row["session_id"], None, row.get("model"), row.get("agent"), None,
            "unknown", row.get("state") or "unknown", "historical", "telemetry_store",
            row.get("last_seen"), Freshness("historical", row.get("last_seen"), age, "telemetry_store"),
            _coverage_json(row.get("coverage_json")), None, None, None, None,
            {"permissions": None, "questions": None}, {}, False, cumulative_token_scope="unavailable",
        )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _stale_summary(summary: SessionSummary, checked_at: str, errors: list[str]) -> SessionSummary:
    now = _parse_time(checked_at)
    observed = _parse_time(summary.freshness.observed_at)
    age = max(0.0, (now - observed).total_seconds()) if now and observed else None
    return replace(summary, state="unknown", state_confidence="stale",
                   freshness=Freshness("stale", summary.freshness.observed_at, age, summary.state_source),
                   last_error_sources=sorted(set(summary.last_error_sources + errors)))


def _coverage(value: Any) -> HistoryCoverage:
    if isinstance(value, dict):
        try:
            return HistoryCoverage(**value)
        except (TypeError, ValueError):
            pass
    return HistoryCoverage("unknown", "unknown", 0, 0)


def _coverage_json(value: Any) -> dict[str, Any]:
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = None
    return value if isinstance(value, dict) else {"status": "unknown"}
