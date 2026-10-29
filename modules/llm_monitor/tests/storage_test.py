import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from time import perf_counter

import pytest

from llm_monitor.events import events_from_messages
from llm_monitor.events import NormalizedEvent
from llm_monitor.storage import (
    TelemetryStore,
    TelemetryStoreError,
    UnsupportedSchemaError,
    default_database_path,
)


def test_default_database_path_uses_platform_data_directories():
    assert str(default_database_path(platform="win32", environ={"LOCALAPPDATA": "C:/Local"})).replace("\\", "/") == \
        "C:/Local/llm-monitor/telemetry.sqlite3"
    assert str(default_database_path(platform="darwin", environ={"HOME": "/Users/example"})).replace("\\", "/") == \
        "/Users/example/Library/Application Support/llm-monitor/telemetry.sqlite3"
    assert str(default_database_path(platform="linux", environ={"XDG_DATA_HOME": "/tmp/data"})).replace("\\", "/") == \
        "/tmp/data/llm-monitor/telemetry.sqlite3"


def test_fresh_database_has_versioned_schema_and_integrity_check(tmp_path):
    path = tmp_path / "telemetry.sqlite3"

    with TelemetryStore(path) as store:
        info = store.database_info()
        check = store.check_integrity()

    assert info["schema_version"] == 2
    assert info["counts"]["sessions"] == 0
    assert check["ok"] is True
    assert check["foreign_key_violations"] == []
    assert path.exists()


def test_recent_session_records_returns_bounded_window_in_chronological_order(tmp_path):
    path = tmp_path / "recent.sqlite3"
    events = [NormalizedEvent(
        event_id=f"event-{index}", timestamp=f"2026-01-01T00:00:{index:02d}+00:00",
        observed_at="2026-01-01T00:01:00+00:00", source="synthetic", category="tool",
        subtype="completed", session_id="recent-session", provider_id=f"provider-{index}", outcome="success",
    ) for index in range(5)]
    snapshot = {"polled_at": "2026-01-01T00:01:00+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete"}}
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "recent-session", snapshot, events)
        recent = store.recent_session_records("recent-session", endpoint="http://localhost:4096", limit=7)
        bounded = store.recent_session_records("recent-session", endpoint="http://localhost:4096", limit=2)

    recent_tools = [row for row in recent if row["category"] == "tool"]
    assert [row["timestamp"] for row in recent_tools] == [
        f"2026-01-01T00:00:0{index}+00:00" for index in range(5)
    ]
    assert len(bounded) == 2
    assert all(row["timestamp"] == "2026-01-01T00:01:00+00:00" for row in bounded)


def test_future_schema_is_rejected_without_replacing_existing_data(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('keep')")
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(UnsupportedSchemaError):
        TelemetryStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "keep"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_incomplete_claimed_schema_is_rejected_without_replacement(tmp_path):
    path = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('keep')")
        connection.execute("PRAGMA user_version=1")

    with pytest.raises(TelemetryStoreError, match="schema is incomplete"):
        TelemetryStore(path, readonly=True)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "keep"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_interrupted_schema_creation_rolls_back_and_can_be_retried(tmp_path, monkeypatch):
    path = tmp_path / "interrupted.sqlite3"
    original = TelemetryStore._create_schema

    def interrupted(connection):
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE half_created(value TEXT)")
        raise sqlite3.OperationalError("simulated interruption")

    monkeypatch.setattr(TelemetryStore, "_create_schema", staticmethod(interrupted))
    with pytest.raises(Exception, match="simulated interruption"):
        TelemetryStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []

    monkeypatch.setattr(TelemetryStore, "_create_schema", staticmethod(original))
    with TelemetryStore(path) as store:
        assert store.check_integrity()["ok"] is True


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX permission semantics")
def test_new_database_does_not_change_existing_parent_permissions(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o755)
    with TelemetryStore(parent / "telemetry.sqlite3"):
        pass
    assert parent.stat().st_mode & 0o777 == 0o755


def test_ingest_is_idempotent_and_does_not_persist_raw_file_paths(tmp_path):
    path = tmp_path / "telemetry.sqlite3"
    messages = [{"info": {"id": "a1", "role": "assistant", "finish": "stop",
                           "time": {"created": 1000, "completed": 2000},
                           "tokens": {"input": 512, "output": 32}},
                 "parts": [{"id": "tool-1", "callID": "read-1", "type": "tool", "tool": "read",
                           "state": {"status": "completed", "input": {"filePath": "C:/secret/project/key.txt"}}}]}]
    events = events_from_messages("session-1", messages, observed_at="2026-01-01T00:00:03+00:00")
    snapshot = {
        "polled_at": "2026-01-01T00:00:03+00:00",
        "normalized_state": "idle",
        "session_info": {"model": "model-a", "agent": "worker", "directory": "C:/secret/project"},
        "history_coverage": {"status": "partial", "source": "legacy", "pages": 1, "limit": 100,
                             "suspected_gap": True, "reason": "private URL https://user:secret@example/path"},
        "errors": {},
    }

    with TelemetryStore(path) as store:
        first = store.ingest_poll("opencode", "http://user:secret@localhost:4096/path?token=x",
                                  "session-1", snapshot, events)
        second = store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, events)
        bundle = store.history_bundle("session-1", provider_type="opencode", endpoint="http://localhost:4096")

    assert first["inserted"] == len(events) + 2
    assert second["inserted"] == 0  # identical timestamp and contents deduplicate
    assert second["duplicates"] == len(events)
    encoded = json.dumps({**bundle, "analysis_events": [event.to_dict() for event in bundle["analysis_events"]]})
    assert "C:/secret/project" not in encoded
    assert "key.txt" not in encoded
    assert "secret" not in encoded
    assert "example/path" not in encoded
    assert bundle["analysis_events"][0].session_id == "session-1"
    assert bundle["session"]["model"] == "model-a"


def test_ingest_rolls_back_events_and_checkpoint_as_one_batch(tmp_path, monkeypatch):
    path = tmp_path / "rollback.sqlite3"
    events = events_from_messages("session-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop"},
                                                  "parts": []}])
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete", "source": "legacy", "pages": 1, "limit": 100}}

    def fail_after_event_insert(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated disk full")

    monkeypatch.setattr(TelemetryStore, "_upsert_detail", staticmethod(fail_after_event_insert))
    with TelemetryStore(path) as store, pytest.raises(sqlite3.OperationalError, match="disk full"):
        store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, events)

    with TelemetryStore(path, readonly=True) as store:
        assert store.list_sessions() == []
        assert store.database_info()["counts"]["events"] == 0


def test_two_writers_serialize_and_deduplicate_same_event(tmp_path):
    path = tmp_path / "writers.sqlite3"
    events = events_from_messages("session-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop"},
                                                  "parts": []}])
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete", "source": "legacy", "pages": 1, "limit": 100}}
    with TelemetryStore(path):
        pass

    def ingest():
        with TelemetryStore(path) as store:
            return store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, events)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: ingest(), range(2)))

    assert sum(result["inserted"] for result in results) == len(events) + 2
    assert sum(result["duplicates"] for result in results) == len(events)
    with TelemetryStore(path, readonly=True) as store:
        assert store.database_info()["counts"]["events"] == len(events) + 2


def test_out_of_order_poll_keeps_latest_state_and_checkpoint(tmp_path):
    path = tmp_path / "out-of-order.sqlite3"
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "session-1",
                          {"polled_at": "2026-01-01T00:00:10Z", "normalized_state": "inference_running",
                           "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 10}}, [])
        store.ingest_poll("opencode", "http://localhost:4096", "session-1",
                          {"polled_at": "2025-12-31T19:00:09-05:00", "normalized_state": "idle",
                           "history_coverage": {"status": "partial", "source": "legacy", "pages": 1, "limit": 10}}, [])
        row = store.list_sessions()[0]
        checkpoint = store.checkpoint_for_session("session-1", endpoint="http://localhost:4096")

    assert row["state"] == "inference_running"
    assert row["last_seen"] == "2026-01-01T00:00:10+00:00"
    assert checkpoint["last_polled_at"] == "2026-01-01T00:00:10+00:00"
    assert json.loads(checkpoint["coverage_json"])["status"] == "complete"


def test_unavailable_poll_does_not_erase_last_observed_state(tmp_path):
    path = tmp_path / "unavailable-state.sqlite3"
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "session-1",
                          {"polled_at": "2026-01-01T00:00:10Z", "normalized_state": "tool_running",
                           "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 10}}, [])
        store.ingest_poll("opencode", "http://localhost:4096", "session-1",
                          {"polled_at": "2026-01-01T00:00:12Z", "normalized_state": None,
                           "history_coverage": {"status": "unavailable", "source": "unknown", "pages": 0,
                                                "limit": 0, "reason": "poll failed"},
                           "errors": {"messages": "not persisted"}}, [])
        row = store.list_sessions()[0]

    assert row["state"] == "tool_running"
    assert "not persisted" not in json.dumps(row)


def test_job_model_configuration_and_device_samples_are_queryable(tmp_path):
    path = tmp_path / "related-telemetry.sqlite3"
    stamp = "2026-01-01T00:00:03+00:00"
    snapshot = {"polled_at": stamp, "normalized_state": "idle",
                "session_info": {"model": "model-a", "agent": "worker"},
                "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 100}}
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, [])
        store.save_job_snapshot("opencode", "http://localhost:4096", "session-1",
                                 {"job": {"jobId": "job-1", "sessionId": "session-1", "status": "running"},
                                  "classification": "exact"}, stamp)
        store.ingest_model_configuration("opencode", "http://localhost:4096", "session-1", stamp,
                                         {"model_id": "model-a", "context": 65536, "output": 8192},
                                         {"id": "model-a", "state": "loaded", "context_length": 65536})
        store.ingest_hardware_sample({"available": True, "devices": [{"id": "gpu0", "load": 50,
                                          "mem_used": 1000, "power_w": 29}], "process_memory": []},
                                     observed_at=stamp)
        bundle = store.history_bundle("session-1", endpoint="http://localhost:4096")

    assert bundle["jobs"][0]["job_id"] == "job-1"
    assert bundle["jobs"][0]["correlation"] == "exact"
    assert bundle["model_configurations"][0]["configured_context"] == 65536
    assert bundle["hardware_samples"][0]["values"]["power_w"] == 29
    assert "session_id" not in bundle["hardware_samples"][0]


def test_events_with_missing_provider_timestamps_remain_queryable(tmp_path):
    path = tmp_path / "missing-time.sqlite3"
    events = events_from_messages("session-1", [{"info": {"id": "m1", "role": "assistant"}, "parts": []}])
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "partial", "source": "legacy", "pages": 1, "limit": 100}}
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, events)
        bundle = store.history_bundle("session-1", endpoint="http://localhost:4096")

    assert bundle["analysis_events"]
    assert bundle["analysis_events"][0].timestamp is None
    assert bundle["analysis_events"][0].observed_at is None


def test_session_keys_are_scoped_to_provider_endpoint(tmp_path):
    path = tmp_path / "provider-scope.sqlite3"
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 100}}
    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "same-id", snapshot, [])
        store.ingest_poll("opencode", "http://localhost:5000", "same-id", snapshot, [])
        assert len(store.list_sessions(provider_type="opencode")) == 2
        assert len(store.list_sessions(provider_type="opencode", endpoint="http://localhost:4096")) == 1


def test_prune_previews_by_default_and_write_leaves_a_coverage_gap(tmp_path):
    path = tmp_path / "retention.sqlite3"
    events = events_from_messages("session-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop",
                           "time": {"created": 1000, "completed": 2000}}, "parts": []}])
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete", "source": "legacy", "pages": 1, "limit": 100}}

    with TelemetryStore(path) as store:
        store.ingest_poll("opencode", "http://localhost:4096", "session-1", snapshot, events)
        preview = store.prune_before("1971-01-01T00:00:00+00:00")
        assert preview["written"] is False
        assert preview["events"] == len(events)
        assert store.database_info()["counts"]["events"] == len(events) + 2
        applied = store.prune_before("1971-01-01T00:00:00+00:00", write=True)
        bundle = store.history_bundle("session-1", provider_type="opencode")

    assert applied["written"] is True
    assert bundle["analysis_events"] == []
    assert any(gap["category"] == "retention_pruned" for gap in bundle["gaps"])


def test_poll_state_observations_are_private_and_stream_in_order(tmp_path):
    path = tmp_path / "state-observations.sqlite3"
    with TelemetryStore(path) as store:
        store.ingest_poll(
            "opencode", "http://localhost:4096", "session-1",
            {"polled_at": "2026-01-01T00:00:02+00:00", "normalized_state": "waiting_question",
             "pending_permissions": 0, "pending_questions": 1,
             "history_coverage": {"status": "partial", "source": "legacy", "pages": 1, "limit": 100},
             "errors": {"messages": "private provider error detail"}}, [],
        )
        rows = list(store.iter_session_records("session-1", endpoint="http://localhost:4096", batch_size=1))
        context = store.session_context("session-1", endpoint="http://localhost:4096")

    sample = next(row["payload"] for row in rows if row["subtype"] == "state_observation")
    assert sample["state"] == "waiting_question"
    assert sample["pending_questions"] == 1
    assert sample["error_sources"] == ["messages"]
    assert "private provider error detail" not in json.dumps(rows)
    assert context["event_count"] == len(rows)


def test_large_event_batch_is_paginated_and_idempotent(tmp_path):
    path = tmp_path / "large.sqlite3"
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        NormalizedEvent(event_id=f"event-{index}", timestamp=(started_at + timedelta(seconds=index)).isoformat(),
                        observed_at="2026-01-01T01:00:00+00:00", source="fixture", category="inference",
                        subtype="completed", session_id="session-large", provider_id=f"message-{index}",
                        outcome="completed", tokens={"input": 1000 + index, "output": 32}, finish_reason="stop")
        for index in range(10000)
    ]
    snapshot = {"polled_at": "2026-01-01T01:00:00+00:00",
                "history_coverage": {"status": "complete", "source": "cursor", "pages": 100, "limit": 100}}

    started = perf_counter()
    with TelemetryStore(path) as store:
        outcome = store.ingest_poll("opencode", "http://localhost:4096", "session-large", snapshot, events)
        page = store.events_for_session(store.list_sessions()[0]["session_key"], limit=100, offset=5000)
        elapsed = perf_counter() - started

    assert outcome["inserted"] == 10001  # includes the persisted state observation
    assert len(page) == 100
    assert page[0]["provider_event_id"] == "message-4999"
    assert elapsed > 0
