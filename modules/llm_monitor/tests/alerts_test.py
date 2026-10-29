from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace

from llm_monitor.alerts import AlertEngine
from llm_monitor.observability import Freshness, ProviderStatus, SessionSummary, SystemSnapshot, SystemSummary
from llm_monitor.storage import TelemetryStore


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def build_snapshot(*, findings=None, state="idle", stale=False, questions=0, utilization=None):
    summary = SessionSummary(
        "http://localhost:4096", "s1", None, "model", "agent", 4096, state, state,
        "observed", "test", BASE.isoformat(),
        Freshness("stale" if stale else "fresh", BASE.isoformat(), 5 if stale else 0, "test"),
        {"status": "complete"}, None, None, None, None,
        {"permissions": 0, "questions": questions}, {}, True, [],
        findings or [], utilization or [],
    )
    return SystemSnapshot(1, BASE.isoformat(), ProviderStatus("http://localhost:4096", "connected", BASE.isoformat()),
        SystemSummary(1, 0, 0, int(questions > 0), 0, ["model"], "not_started_by_dashboard"),
        [summary], None, None)


def test_finding_alerts_open_once_and_resolve_when_evidence_clears():
    engine = AlertEngine()
    finding = {"code": "context.length_finish", "severity": "warning", "classification": "observed",
               "summary": "length-limited inference", "evidence": [{"event_id": "event-1"}]}
    opened = engine.evaluate(build_snapshot(findings=[finding]), now=BASE)
    repeated = engine.evaluate(build_snapshot(findings=[finding]), previous=opened.states, now=BASE + timedelta(seconds=2))
    resolved = engine.evaluate(build_snapshot(), previous=repeated.states, now=BASE + timedelta(seconds=3))

    assert [alert.rule_id for alert in opened.active] == ["inference.length_finish"]
    assert opened.transitions[0].transition == "opened"
    assert repeated.transitions == []
    assert resolved.transitions[0].transition == "resolved"


def test_explicit_question_blocker_and_provider_staleness_are_observed_alerts():
    engine = AlertEngine()
    result = engine.evaluate(build_snapshot(state="waiting_question", questions=1, stale=True), now=BASE)

    assert {item.rule_id for item in result.active} == {"blocker.question", "monitor.provider_stale"}
    assert all(item.classification == "observed" for item in result.active)


def test_missing_context_capacity_does_not_create_context_alert():
    result = AlertEngine().evaluate(build_snapshot(utilization=[{"utilization_percent": None}]), now=BASE)

    assert not any(item.category == "context" for item in result.active)


def test_historical_analyzer_finding_codes_match_shared_alert_rules():
    length = {"code": "inference.length_termination", "severity": "warning", "classification": "observed",
              "summary": "generation ended at length", "evidence": [{"event_id": "inf-1"}]}
    repeated = {"code": "tools.repeated_failures", "severity": "warning", "classification": "strong_inference",
                "summary": "same operation failed repeatedly", "evidence": [{"tool_name": "edit"}]}
    result = AlertEngine().evaluate(build_snapshot(findings=[length, repeated]), now=BASE)

    assert {item.rule_id for item in result.active} == {"inference.length_finish", "tool.repeated_failure"}


def test_acknowledged_condition_remains_suppressed_until_resolved():
    engine = AlertEngine()
    finding = {"code": "tools.failed_edit", "severity": "warning", "classification": "observed",
               "summary": "edit failed", "evidence": [{"event_id": "edit-1"}]}
    first = engine.evaluate(build_snapshot(findings=[finding]), now=BASE)
    acknowledged = [{**first.states[0], "status": "acknowledged", "acknowledged_at": BASE.isoformat()}]
    next_evaluation = engine.evaluate(build_snapshot(findings=[finding]), previous=acknowledged,
                                      now=BASE + timedelta(seconds=30))

    assert next_evaluation.active[0].status == "acknowledged"
    assert not next_evaluation.transitions


def test_stale_observation_does_not_resolve_previous_diagnostic_alert():
    engine = AlertEngine()
    finding = {"code": "tools.failed_edit", "severity": "warning", "classification": "observed",
               "summary": "edit failed", "evidence": [{"event_id": "edit-1"}]}
    first = engine.evaluate(build_snapshot(findings=[finding]), now=BASE)
    stale = engine.evaluate(build_snapshot(stale=True), previous=first.states,
                            now=BASE + timedelta(seconds=60))

    assert any(item.rule_id == "tool.edit_failure" for item in stale.active)
    assert not any(item.transition == "resolved" and item.alert.rule_id == "tool.edit_failure"
                   for item in stale.transitions)


def test_alert_store_migrates_v1_and_persists_acknowledgment(tmp_path):
    database = tmp_path / "alerts.sqlite3"
    with TelemetryStore(database):
        pass
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS alert_states")
        connection.execute("UPDATE schema_metadata SET value='1' WHERE key='schema_version'")
        connection.execute("PRAGMA user_version=1")

    with TelemetryStore(database) as store:
        assert store.database_info()["schema_version"] == 2
        assert store.list_alert_states() == []
        alert = {"alert_id": "alert-1", "provider_instance_id": "http://localhost:4096", "session_id": "s1",
            "rule_id": "blocker.question", "category": "questions", "severity": "info",
            "classification": "observed", "status": "active", "summary": "waiting for a response",
            "evidence": [{"count": 1}], "threshold": None, "first_seen": BASE.isoformat(),
            "last_seen": BASE.isoformat(), "last_notified_at": BASE.isoformat(), "acknowledged_at": None}
        store.save_alert_state(alert)
        saved = store.acknowledge_alert("alert-1", at=(BASE + timedelta(seconds=1)).isoformat())

    assert saved["status"] == "acknowledged"
    with TelemetryStore(database, readonly=True) as store:
        rows = store.list_alert_states()
    assert rows[0]["alert_id"] == "alert-1"
    assert rows[0]["status"] == "acknowledged"


def test_readonly_telemetry_store_accepts_schema_v1(tmp_path):
    database = tmp_path / "old.sqlite3"
    with TelemetryStore(database):
        pass
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS alert_states")
        connection.execute("UPDATE schema_metadata SET value='1' WHERE key='schema_version'")
        connection.execute("PRAGMA user_version=1")

    with TelemetryStore(database, readonly=True) as store:
        result = store.check_integrity()
    assert result["ok"] is True
    assert result["schema_version"] == 1
