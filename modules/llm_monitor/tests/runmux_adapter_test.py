from datetime import datetime, timedelta, timezone

import pytest
from concurrent.futures import ThreadPoolExecutor

from llm_monitor.events import NormalizedEvent
from llm_monitor.observability import ObservabilityService
from llm_monitor.opencode import ApiResult
from llm_monitor.runmux_adapter import RunmuxMonitoringAdapter
from llm_monitor.storage import TelemetryStore


def stamp(seconds=0):
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class Client:
    base_url = "http://user:secret@localhost:4096/private?key=secret"

    def __init__(self):
        self.poll_calls = []

    def sessions(self, _directory=None):
        return ApiResult(data=[{"id": "s1"}])

    def poll(self, session_id, _directory=None):
        self.poll_calls.append(session_id)
        return {"session_id": session_id, "polled_at": stamp(10), "normalized_state": "idle",
                "session_info": {"id": session_id}, "history_coverage": {"status": "complete"},
                "pending_permissions": 0, "pending_questions": 0, "errors": {}}

    def events_for_session(self, session_id):
        return []


def make_event(index):
    return NormalizedEvent(
        event_id=f"event-{index}", timestamp=stamp(index), observed_at=stamp(index), source="synthetic",
        category="tool", subtype="invocation", session_id="s1", provider_id=f"message-{index}",
        tool_name="read", tool_target=f"C:/private/source-{index}.py", outcome="succeeded",
    )


def test_snapshot_is_versioned_and_does_not_expose_database_or_credentials():
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client(), database_path="C:/private/telemetry.sqlite3"))

    result = adapter.snapshot()

    assert result["schema_version"] == 1
    assert result["provider"]["provider_instance_id"] == "http://localhost:4096"
    assert "database_path" not in result
    assert "secret" not in str(result)


def test_snapshot_redacts_sensitive_provider_error_details():
    class FailingClient(Client):
        def sessions(self, _directory=None):
            return ApiResult(error="URLError: http://user:secret@localhost:4096/private?key=private-token")

    adapter = RunmuxMonitoringAdapter(ObservabilityService(FailingClient()))

    result = adapter.snapshot()

    assert result["provider"]["status"] == "unavailable"
    assert result["provider"]["error"] == "provider_error"
    assert "secret" not in str(result)
    assert "private-token" not in str(result)
    assert "/private" not in str(result)


def test_snapshot_cache_shares_refresh_between_consumers():
    client = Client()
    adapter = RunmuxMonitoringAdapter(ObservabilityService(client), refresh_interval_seconds=10)

    first = adapter.snapshot()
    second = adapter.snapshot()

    assert first == second
    assert first["system"]["discovered_sessions"] == 1
    assert client.poll_calls == ["s1"]


def test_timeline_supports_concurrent_readers_without_writes(tmp_path):
    db = tmp_path / "concurrent.sqlite3"
    with TelemetryStore(db) as store:
        for index in range(20):
            store.ingest_poll("opencode", "http://localhost:4096", "s1",
                              {"polled_at": stamp(index), "normalized_state": "idle",
                               "history_coverage": {"status": "complete"}}, [make_event(index)])
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client(), database_path=db), database_path=db)
    before = TelemetryStore(db, readonly=True).database_info()["counts"]["events"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(lambda _: adapter.timeline("http://localhost:4096", "s1", limit=5), range(8)))

    after = TelemetryStore(db, readonly=True).database_info()["counts"]["events"]
    assert all(len(page["events"]) == 5 for page in pages)
    assert before == after


def test_timeline_pages_are_bounded_and_hash_file_targets(tmp_path):
    db = tmp_path / "telemetry.sqlite3"
    with TelemetryStore(db) as store:
        for index in range(5):
            store.ingest_poll("opencode", "http://localhost:4096", "s1",
                              {"polled_at": stamp(index), "normalized_state": "idle",
                               "history_coverage": {"status": "complete", "source": "legacy"}},
                              [make_event(index)])
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client(), database_path=db), database_path=db)

    first = adapter.timeline("http://localhost:4096", "s1", limit=2)
    second = adapter.timeline("http://localhost:4096", "s1", limit=2, cursor=first["next_cursor"])

    assert len(first["events"]) == 2
    assert len(second["events"]) == 2
    targets = [event.get("tool_target") for event in first["events"] if event.get("tool_target")]
    assert targets and all(target.startswith("sha256:") for target in targets)
    assert "private/source" not in str(first)
    assert first["next_cursor"] != second["next_cursor"]


def test_timeline_rejects_cursor_bound_to_another_session(tmp_path):
    db = tmp_path / "telemetry.sqlite3"
    with TelemetryStore(db) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "s1",
                          {"polled_at": stamp(), "normalized_state": "idle",
                           "history_coverage": {"status": "complete"}}, [])
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client(), database_path=db), database_path=db)
    cursor = adapter.timeline("http://localhost:4096", "s1", limit=1)["next_cursor"]

    with pytest.raises(ValueError, match="cursor"):
        adapter.timeline("http://localhost:4096", "s2", limit=1, cursor=cursor)


def test_unavailable_history_and_alerts_return_empty_versioned_envelopes(tmp_path):
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client()), database_path=tmp_path / "absent.sqlite3")

    timeline = adapter.timeline("http://localhost:4096", "s1")
    alerts = adapter.alerts()

    assert timeline["availability"] == "unavailable"
    assert timeline["events"] == []
    assert alerts["availability"] == "unavailable"
    assert alerts["alerts"] == []


def test_alert_evidence_json_is_decoded_and_path_fields_are_removed(tmp_path):
    db = tmp_path / "alerts.sqlite3"
    with TelemetryStore(db) as store:
        store.save_alert_state({"alert_id": "alert-1", "provider_instance_id": "http://localhost:4096",
                                "session_id": "s1", "rule_id": "read-loop", "category": "reads",
                                "severity": "warning", "classification": "hypothesis", "status": "active",
                                "summary": "Repeated reads observed", "evidence": [{"path": "C:/private/file.py",
                                "count": 3}], "first_seen": stamp(), "last_seen": stamp()})
    adapter = RunmuxMonitoringAdapter(ObservabilityService(Client(), database_path=db), database_path=db)

    result = adapter.alerts()

    assert "evidence_json" not in result["alerts"][0]
    assert "path" not in result["alerts"][0]["evidence"][0]
    assert "private/file.py" not in str(result)
