import sqlite3
from pathlib import Path

from llm_monitor.inference_models import HardwareSample, ContentSegment, InferenceRequest
from llm_monitor.storage import TelemetryStore


def test_schema_v3_fresh_database_has_inference_tables(tmp_path: Path):
    db_path = tmp_path / "test_v3.sqlite3"
    with TelemetryStore(db_path) as store:
        info = store.database_info()
        assert info["schema_version"] == 3
        assert "inference_requests" in info["counts"]
        assert "inference_contents" in info["counts"]
        assert "inference_hardware_samples" in info["counts"]

        integrity = store.check_integrity()
        assert integrity["ok"] is True


def test_migration_v2_to_v3_preserves_existing_data(tmp_path: Path):
    db_path = tmp_path / "migrate_v2.sqlite3"
    # Create a real v2 database
    with TelemetryStore(db_path) as store:
        pass
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE inference_contents")
        conn.execute("DROP TABLE inference_hardware_samples")
        conn.execute("DROP TABLE inference_requests")
        conn.execute("UPDATE schema_metadata SET value='2' WHERE key='schema_version'")
        conn.execute("PRAGMA user_version=2")
        conn.execute("INSERT INTO alert_states(alert_id, provider_instance_id, session_id, rule_id, category, severity, classification, status, summary, evidence_json, threshold, first_seen, last_seen, last_notified_at, acknowledged_at, resolved_at, last_updated) VALUES('a1', 'http://127.0.0.1', 's1', 'r1', 'c1', 'info', 'observed', 'active', 'summary', '[]', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, NULL, NULL, '2026-01-01T00:00:00Z')")

    # Now open with TelemetryStore which triggers v2 -> v3 migration
    with TelemetryStore(db_path) as store:
        info = store.database_info()
        assert info["schema_version"] == 3
        alerts = store.list_alert_states()
        assert len(alerts) == 1
        assert alerts[0]["alert_id"] == "a1"
        assert store.check_integrity()["ok"] is True


def test_record_inference_metadata_mode_never_persists_content(tmp_path: Path):
    db_path = tmp_path / "metadata_mode.sqlite3"
    with TelemetryStore(db_path) as store:
        req = InferenceRequest(
            request_id="req-123",
            server_instance_id="srv-1",
            provider_model_id="qwen",
            model_name="qwen",
            source="gateway_openai_chat_completions",
            state="completed",
            started_at="2026-11-01T12:00:00Z",
            ended_at="2026-11-01T12:00:02Z",
            elapsed_seconds=2.0,
            input_tokens=10,
            output_tokens=20,
            generated_tokens=20,
            gpu_average_percent=55.0,
            gpu_peak_vram_bytes=8000000.0,
        )
        content_secret = [
            ContentSegment(sequence=1, kind="user", role="user", text="TOP SECRET PROMPT"),
            ContentSegment(sequence=2, kind="reasoning", role="assistant", text="SECRET REASONING"),
            ContentSegment(sequence=3, kind="assistant", role="assistant", text="SECRET ANSWER"),
        ]
        hw_sample = [
            HardwareSample(
                sample_id=1,
                timestamp="2026-11-01T12:00:01Z",
                timestamp_monotonic=100.0,
                device_id="gpu-0",
                device_name="RTX 5090",
                source="nvidia-smi",
                gpu_utilization_percent=55.0,
            )
        ]

        # Record in metadata mode
        store.record_inference(req, "metadata", contents=content_secret, hardware_samples=hw_sample)

        # Inspect database directly: zero content rows must exist
        with sqlite3.connect(db_path) as conn:
            c_count = conn.execute("SELECT COUNT(*) FROM inference_contents").fetchone()[0]
            assert c_count == 0, "Privacy violation: inference_contents contains rows in metadata mode!"

        # Inspect via get_inference_request
        retrieved = store.get_inference_request("req-123", include_content=True)
        assert retrieved is not None
        assert retrieved["request_id"] == "req-123"
        assert retrieved["recording_mode"] == "metadata"
        assert retrieved["content"] == []
        assert retrieved["input_tokens"] == 10
        assert retrieved["output_tokens"] == 20
        assert len(retrieved["hardware_samples"]) == 1


def test_record_inference_content_mode_persists_content(tmp_path: Path):
    db_path = tmp_path / "content_mode.sqlite3"
    with TelemetryStore(db_path) as store:
        req = InferenceRequest(
            request_id="req-456",
            server_instance_id="srv-1",
            provider_model_id="qwen",
            model_name="qwen",
            source="gateway_openai_chat_completions",
            state="completed",
            started_at="2026-11-01T12:00:00Z",
            ended_at="2026-11-01T12:00:01Z",
            elapsed_seconds=1.0,
        )
        contents = [
            ContentSegment(sequence=1, kind="user", role="user", text="Hello world"),
            ContentSegment(sequence=2, kind="assistant", role="assistant", text="Hi there!"),
        ]

        store.record_inference(req, "content", contents=contents)

        retrieved = store.get_inference_request("req-456", include_content=True)
        assert retrieved is not None
        assert retrieved["recording_mode"] == "content"
        assert len(retrieved["content"]) == 2
        assert retrieved["content"][0]["text"] == "Hello world"
        assert retrieved["content"][1]["text"] == "Hi there!"

        # When include_content=False, content should be omitted
        retrieved_no_c = store.get_inference_request("req-456", include_content=False)
        assert retrieved_no_c["content"] == []


def test_list_inference_requests_filtering_and_pagination(tmp_path: Path):
    db_path = tmp_path / "list_mode.sqlite3"
    with TelemetryStore(db_path) as store:
        for i in range(10):
            req = InferenceRequest(
                request_id=f"r-{i:02d}",
                server_instance_id="srv-A" if i % 2 == 0 else "srv-B",
                provider_model_id="m-1" if i < 5 else "m-2",
                model_name="model",
                source="gateway",
                state="completed" if i < 8 else "failed",
                started_at=f"2026-11-01T12:0{i:02d}:00Z",
                elapsed_seconds=1.0,
            )
            store.record_inference(req, "metadata")

        # All requests
        items, total = store.list_inference_requests(limit=5, offset=0)
        assert total == 10
        assert len(items) == 5
        # Ordered by started_at DESC
        assert items[0]["request_id"] == "r-09"

        # Offset
        items_page2, total2 = store.list_inference_requests(limit=5, offset=5)
        assert total2 == 10
        assert len(items_page2) == 5
        assert items_page2[0]["request_id"] == "r-04"

        # Filter by server
        srv_a_items, srv_a_total = store.list_inference_requests(server_instance_id="srv-A")
        assert srv_a_total == 5

        # Filter by model
        m1_items, m1_total = store.list_inference_requests(model_id="m-1")
        assert m1_total == 5

        # Filter by state
        failed_items, failed_total = store.list_inference_requests(state="failed")
        assert failed_total == 2


def test_prune_before_cascades_to_contents_and_hardware(tmp_path: Path):
    db_path = tmp_path / "prune_cascade.sqlite3"
    with TelemetryStore(db_path) as store:
        req_old = InferenceRequest(
            request_id="old-req",
            server_instance_id="s1",
            source="gateway",
            started_at="2026-10-01T00:00:00Z",
            state="completed",
        )
        req_new = InferenceRequest(
            request_id="new-req",
            server_instance_id="s1",
            source="gateway",
            started_at="2026-11-01T00:00:00Z",
            state="completed",
        )
        contents = [ContentSegment(sequence=1, kind="user", role="user", text="old message")]
        hw = [HardwareSample(sample_id=1, timestamp="2026-10-01T00:00:00Z", timestamp_monotonic=10.0, device_id="gpu-0", device_name="GPU", source="nvidia-smi")]

        store.record_inference(req_old, "content", contents=contents, hardware_samples=hw)
        store.record_inference(req_new, "metadata")

        # Preview prune
        cutoff = "2026-10-15T00:00:00Z"
        preview = store.prune_before(cutoff, write=False)
        assert preview["written"] is False
        assert preview["inference_requests"] == 1

        # Apply prune
        applied = store.prune_before(cutoff, write=True)
        assert applied["written"] is True
        assert applied["inference_requests"] == 1

        # Verify old-req and its contents are gone
        assert store.get_inference_request("old-req") is None
        with sqlite3.connect(db_path) as conn:
            c_count = conn.execute("SELECT COUNT(*) FROM inference_contents WHERE request_id='old-req'").fetchone()[0]
            assert c_count == 0
            h_count = conn.execute("SELECT COUNT(*) FROM inference_hardware_samples WHERE request_id='old-req'").fetchone()[0]
            assert h_count == 0

        # Verify new-req remains
        assert store.get_inference_request("new-req") is not None
