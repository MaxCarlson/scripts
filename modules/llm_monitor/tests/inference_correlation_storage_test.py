from llm_monitor.inference_models import InferenceRequest
from llm_monitor.storage import TelemetryStore
import sqlite3


def test_execution_correlation_survives_history_round_trip(tmp_path):
    request = InferenceRequest(
        request_id="request-1",
        server_instance_id="monitor-1",
        source="gateway_openai_chat_completions",
        state="completed",
        started_at="2026-11-05T00:00:00Z",
        ended_at="2026-11-05T00:00:01Z",
        benchmark_correlation={
            "schema_version": 1,
            "run_id": "run-1",
            "task_id": "task-1",
            "execution_id": "exec-1",
            "trial_id": "trial-1",
            "verification_status": "verified",
            "provenance_source": "llm_monitor_gateway_credential",
        },
    )
    with TelemetryStore(tmp_path / "history.sqlite3") as store:
        store.record_inference(request, "metadata")
        reconciled = {**request.benchmark_correlation, "trial_id": "trial-after-run"}
        assert store.update_execution_correlation("exec-1", reconciled) == 1
        retrieved = store.get_inference_request("request-1", include_content=False)
    assert retrieved["benchmark_correlation"] == reconciled


def test_old_inference_rows_have_unavailable_correlation(tmp_path):
    request = InferenceRequest(
        request_id="legacy-request",
        server_instance_id="monitor-1",
        source="gateway",
        state="completed",
    )
    with TelemetryStore(tmp_path / "legacy.sqlite3") as store:
        store.record_inference(request, "metadata")
        retrieved = store.get_inference_request("legacy-request", include_content=False)
    assert retrieved["benchmark_correlation"] is None


def test_schema_v3_migrates_additively_to_v4(tmp_path):
    path = tmp_path / "v3.sqlite3"
    with TelemetryStore(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE inference_requests DROP COLUMN correlation_json"
        )
        connection.execute("PRAGMA user_version=3")
        connection.execute(
            "UPDATE schema_metadata SET value='3' WHERE key='schema_version'"
        )
    with TelemetryStore(path) as store:
        request = InferenceRequest("migrated", "monitor", "gateway", "completed")
        store.record_inference(request, "metadata")
        saved = store.get_inference_request("migrated", include_content=False)
    assert saved["benchmark_correlation"] is None
