from pathlib import Path
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
