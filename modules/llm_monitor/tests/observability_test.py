from datetime import datetime, timedelta, timezone

from llm_monitor.events import NormalizedEvent
from llm_monitor.observability import ObservabilityService
from llm_monitor.opencode import ApiResult
from llm_monitor.storage import TelemetryStore


def stamp(seconds=0):
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class FakeClient:
    endpoint = "http://localhost:4096"

    def __init__(self, sessions, snapshots, events=None, session_error=None):
        self._sessions = sessions
        self._snapshots = snapshots
        self._events = events or {}
        self.session_error = session_error
        self.poll_calls = []

    def sessions(self, _directory=None):
        return ApiResult(data=self._sessions, error=self.session_error)

    def poll(self, session_id, _directory=None):
        self.poll_calls.append(session_id)
        return self._snapshots[session_id]

    def events_for_session(self, session_id):
        return list(self._events.get(session_id, []))


def snapshot(session_id, *, state="idle", errors=None, polled_at=None):
    return {"session_id": session_id, "polled_at": polled_at or stamp(), "normalized_state": state,
            "session_state": {"type": "idle"}, "session_info": {"id": session_id, "model": "model-x"},
            "history_coverage": {"status": "complete", "source": "legacy", "pages": 1, "limit": 100},
            "pending_permissions": 0, "pending_questions": 1 if state == "waiting_question" else 0,
            "latest_tool": None, "latest_completed_inference": None, "errors": errors or {}}


def test_refresh_aggregates_sessions_and_marks_poll_errors_stale():
    sessions = [{"id": "s1"}, {"id": "s2"}]
    client = FakeClient(sessions, {
        "s1": snapshot("s1", state="inference_running", polled_at=stamp(10)),
        "s2": snapshot("s2", state="tool_running", errors={"messages": "offline"}),
    })
    service = ObservabilityService(client, stale_after_seconds=5, clock=lambda: datetime.fromisoformat(stamp(10)))

    result = service.refresh()

    assert [item.session_id for item in result.sessions] == ["s1", "s2"]
    assert result.system.active_inferences == 1
    assert result.system.active_tools == 0
    assert result.sessions[1].state == "unknown"
    assert result.sessions[1].last_observed_state == "tool_running"
    assert result.sessions[1].freshness.status == "stale"
    assert result.provider.status == "degraded"
    assert client.poll_calls == ["s1", "s2"]


def test_provider_disconnect_preserves_last_live_observation_as_stale():
    client = FakeClient([{"id": "s1"}], {"s1": snapshot("s1", state="inference_running")})
    service = ObservabilityService(client, clock=lambda: datetime.fromisoformat(stamp(5)))
    first = service.refresh()
    client.session_error = "connection reset"

    disconnected = service.refresh()

    assert first.sessions[0].state == "inference_running"
    assert len(disconnected.sessions) == 1
    assert disconnected.sessions[0].state == "unknown"
    assert disconnected.sessions[0].last_observed_state == "inference_running"
    assert disconnected.sessions[0].freshness.status == "stale"
    assert disconnected.provider.status == "degraded"


def test_detail_reuses_current_events_and_does_not_claim_acceptance():
    event = NormalizedEvent(event_id="e1", timestamp=stamp(), observed_at=stamp(), source="synthetic",
        category="inference", subtype="completed", session_id="s1", provider_id="m1", model="model-x",
        outcome="completed", finish_reason="stop", tokens={"input": 100, "output": 20})
    client = FakeClient([{"id": "s1"}], {"s1": snapshot("s1")}, {"s1": [event]})
    service = ObservabilityService(client)
    service.refresh()

    detail = service.get_detail("http://localhost:4096", "s1")

    assert detail is not None
    assert detail.recent_events[0]["event_id"] == "e1"
    assert detail.completion["inference_completion"] == "completed"
    assert detail.completion["task_acceptance"] == "unverified"
    assert detail.context_utilization[0]["utilization_percent"] is None


def test_service_provides_historical_sessions_offline(tmp_path):
    database = tmp_path / "telemetry.sqlite3"
    with TelemetryStore(database) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "old-session",
            {"polled_at": stamp(), "normalized_state": "idle",
             "history_coverage": {"status": "partial", "source": "legacy"}, "errors": {}}, [])
    client = FakeClient([], {}, session_error="provider offline")
    service = ObservabilityService(client, database_path=database)

    result = service.refresh()

    assert result.to_dict()["schema_version"] == 1
    assert len(result.sessions) == 1
    assert result.sessions[0].session_id == "old-session"
    assert result.sessions[0].is_live is False
    assert result.sessions[0].freshness.status == "historical"
    assert result.provider.status == "unavailable"


def test_historical_detail_includes_bounded_recent_events_and_unknown_acceptance(tmp_path):
    database = tmp_path / "historical-detail.sqlite3"
    events = [NormalizedEvent(
        event_id=f"history-{index}", timestamp=stamp(index), observed_at=stamp(index), source="synthetic",
        category="tool", subtype="completed", session_id="old-session", provider_id=f"tool-{index}",
        tool_name="read", outcome="success",
    ) for index in range(3)]
    with TelemetryStore(database) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "old-session",
            {"polled_at": stamp(3), "normalized_state": "idle",
             "history_coverage": {"status": "partial", "source": "legacy"}, "errors": {}}, events)
    service = ObservabilityService(FakeClient([], {}, session_error="offline"), database_path=database)
    service.refresh()

    detail = service.get_detail("http://localhost:4096", "old-session")

    assert detail is not None
    assert [event["event_id"] for event in detail.recent_events if event.get("category") == "tool"] == [
        "history-0", "history-1", "history-2"
    ]
    assert detail.completion["task_acceptance"] == "unverified"
    assert detail.coverage["status"] == "partial"
