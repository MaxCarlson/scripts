from pathlib import Path
from dataclasses import replace
import pytest

from llm_monitor.inference_models import ContentSegment, InferenceRequest
from llm_monitor.inference_recording import InferenceRecorder
from llm_monitor.storage import TelemetryStore


def test_inference_recorder_rejects_invalid_mode(tmp_path: Path):
    store = TelemetryStore(tmp_path / "test.sqlite3")
    with pytest.raises(ValueError, match="invalid recording mode"):
        InferenceRecorder(store, mode="invalid_mode")


def test_inference_recorder_metadata_mode_lifecycle(tmp_path: Path):
    db_path = tmp_path / "rec_meta.sqlite3"
    store = TelemetryStore(db_path)
    recorder = InferenceRecorder(store, mode="metadata")
    recorder.start()

    req = InferenceRequest(
        request_id="r-start-finish",
        server_instance_id="s1",
        source="gateway",
        state="running",
        started_at="2026-11-01T12:00:00Z",
    )
    recorder.record_request_start(req)

    # Now finalize with updated record
    req_final = InferenceRequest(
        **{
            **req.__dict__,
            "state": "completed",
            "ended_at": "2026-11-01T12:00:01Z",
            "elapsed_seconds": 1.0,
            "generated_tokens": 50,
        }
    )
    secret_content = [ContentSegment(sequence=1, kind="user", role="user", text="TOP SECRET PROMPT")]

    recorder.record_request_final(req_final, contents=secret_content)
    recorder.flush()
    recorder.stop()

    status = recorder.status()
    assert status["recording_enabled"] is True
    assert status["mode"] == "metadata"
    assert status["persisted_requests_count"] >= 1
    assert status["is_healthy"] is False
    assert status["worker_running"] is False

    # Verify database directly: contents MUST be empty
    record = store.get_inference_request("r-start-finish", include_content=True)
    assert record is not None
    assert record["state"] == "completed"
    assert record["content"] == []
    assert record["generated_tokens"] == 50


def test_inference_recorder_content_mode_lifecycle(tmp_path: Path):
    db_path = tmp_path / "rec_content.sqlite3"
    store = TelemetryStore(db_path)
    recorder = InferenceRecorder(store, mode="content")
    recorder.start()

    req = InferenceRequest(
        request_id="r-content",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_at="2026-11-01T12:00:00Z",
        ended_at="2026-11-01T12:00:02Z",
        elapsed_seconds=2.0,
    )
    contents = [
        ContentSegment(sequence=1, kind="user", role="user", text="User Question"),
        ContentSegment(sequence=2, kind="assistant", role="assistant", text="Assistant Response"),
    ]
    recorder.record_request_final(req, contents=contents)
    recorder.flush()
    recorder.stop()

    record = store.get_inference_request("r-content", include_content=True)
    assert record is not None
    assert record["recording_mode"] == "content"
    assert len(record["content"]) == 2
    assert record["content"][0]["text"] == "User Question"
    assert record["content"][1]["text"] == "Assistant Response"


def test_inference_recorder_queue_overflow_marks_unhealthy(tmp_path: Path):
    db_path = tmp_path / "rec_overflow.sqlite3"
    store = TelemetryStore(db_path)
    # Queue size 2
    recorder = InferenceRecorder(store, mode="metadata", queue_size=2)
    # Don't start worker thread, so queue fills up immediately

    for i in range(5):
        req = InferenceRequest(
            request_id=f"r-{i}",
            server_instance_id="s1",
            source="gateway",
            state="completed",
        )
        recorder.record_request_start(req)

    status = recorder.status()
    assert status["dropped_count"] == 3
    assert status["is_healthy"] is False
    assert "Recorder queue capacity exceeded" in status["last_error"]


def test_incremental_content_exceeds_live_store_budget_and_survives_restart(tmp_path: Path):
    store = TelemetryStore(tmp_path / "incremental.sqlite3")
    recorder = InferenceRecorder(store, mode="content")
    recorder.start()
    req = InferenceRequest(request_id="large", server_instance_id="s1", source="gateway", state="active")
    recorder.record_request_start(req)
    for sequence in range(3):
        recorder.record_content("large", ContentSegment(
            sequence=sequence, kind="assistant", role="assistant", text="x" * 1_000_000,
            source="gateway_sse",
        ))
    assert recorder.flush(timeout=10) is True
    assert recorder.stop(timeout=10) is True
    record = store.get_inference_request("large", include_content=True)
    assert record is not None
    assert sum(len(part["text"]) for part in record["content"]) == 3_000_000

    recovered = InferenceRecorder(store, mode="metadata")
    recovered.start()
    assert recovered.flush(timeout=10)
    assert recovered.stop(timeout=10)
    record = store.get_inference_request("large", include_content=True)
    assert record is not None
    assert record["state"] == "interrupted"
    assert sum(len(part["text"]) for part in record["content"]) == 3_000_000


def test_mode_transitions_preserve_start_authorization_and_capture_boundary(tmp_path: Path):
    store = TelemetryStore(tmp_path / "modes.sqlite3")
    recorder = InferenceRecorder(store, mode="content")
    recorder.start()
    req = InferenceRequest(request_id="revoke", server_instance_id="s1", source="gateway", state="active")
    recorder.record_request_start(req)
    recorder.record_content("revoke", ContentSegment(sequence=1, kind="assistant", role="assistant", text="allowed"))
    recorder.set_mode("metadata")
    recorder.record_content("revoke", ContentSegment(sequence=2, kind="assistant", role="assistant", text="blocked"))
    recorder.set_mode("content")
    recorder.record_content("revoke", ContentSegment(sequence=3, kind="assistant", role="assistant", text="still blocked"))
    recorder.record_request_final(replace(req, state="completed"))

    recorder.set_mode("metadata")
    req2 = InferenceRequest(request_id="grant", server_instance_id="s1", source="gateway", state="active")
    recorder.record_request_start(req2)
    recorder.set_mode("content")
    recorder.record_content("grant", ContentSegment(sequence=1, kind="assistant", role="assistant", text="not authorized"))
    recorder.record_request_final(replace(req2, state="completed"))
    assert recorder.flush(timeout=5)
    recorder.stop()

    revoked = store.get_inference_request("revoke", include_content=True)
    granted = store.get_inference_request("grant", include_content=True)
    assert revoked["recording_mode"] == "content"
    assert [item["text"] for item in revoked["content"]] == ["allowed"]
    assert granted["recording_mode"] == "metadata"
    assert granted["content"] == []


def test_repeat_start_does_not_interrupt_active_request(tmp_path: Path):
    store = TelemetryStore(tmp_path / "repeat-start.sqlite3")
    recorder = InferenceRecorder(store, mode="metadata")
    recorder.start()
    req = InferenceRequest(request_id="live", server_instance_id="s1", source="gateway", state="active")
    recorder.record_request_start(req)
    assert recorder.flush(timeout=5)
    recorder.start()
    record = store.get_inference_request("live", include_content=False)
    assert record is not None and record["state"] == "active"
    recorder.stop()


def test_flush_reports_preceding_write_failure_and_byte_saturation(tmp_path: Path):
    class FailingStore(TelemetryStore):
        def append_inference_content(self, request_id, segment):
            raise OSError("synthetic sqlite failure")

    store = FailingStore(tmp_path / "failed-write.sqlite3")
    recorder = InferenceRecorder(store, mode="content")
    recorder.start()
    req = InferenceRequest(request_id="failure", server_instance_id="s1", source="gateway", state="active")
    recorder.record_request_start(req)
    recorder.record_content("failure", ContentSegment(sequence=1, kind="assistant", role="assistant", text="x"))
    assert recorder.flush(timeout=5) is False
    assert recorder.status()["is_healthy"] is False
    recorder.stop()

    saturated = InferenceRecorder(TelemetryStore(tmp_path / "saturated.sqlite3"), mode="content", queue_bytes=100)
    saturated.record_request_start(req)
    saturated.record_content("failure", ContentSegment(sequence=1, kind="assistant", role="assistant", text="x" * 1000))
    assert saturated.status()["dropped_count"] >= 1
    assert saturated.status()["is_healthy"] is False
