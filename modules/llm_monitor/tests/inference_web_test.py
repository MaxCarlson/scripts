from pathlib import Path

from fastapi.testclient import TestClient

from llm_monitor.inference_models import CaptureCapabilities
from llm_monitor.inference_web import create_inference_web_app


class FakeService:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.value = {
            "schema_version": 1,
            "revision": 4,
            "refreshed_at": "2026-10-29T12:00:00Z",
            "server": {"connection_state": "connected", "endpoint": "http://127.0.0.1:1234"},
            "capabilities": CaptureCapabilities.passive_inventory(available=True).to_dict(),
            "models": [{"provider_model_id": "fixture/model", "state": "loaded"}],
            "requests": [],
            "recording": {"status": "disabled", "metadata": False, "content": False},
        }

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.value


def test_application_starts_and_stops_recording_worker(tmp_path):
    from llm_monitor.inference_models import InferenceRequest
    from llm_monitor.inference_recording import InferenceRecorder
    from llm_monitor.storage import TelemetryStore

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    store = TelemetryStore(tmp_path / "recorder.sqlite3")
    recorder = InferenceRecorder(store, mode="content")
    app = create_inference_web_app(FakeService(), login_code="fixture", static_dir=tmp_path, recorder=recorder)
    assert recorder.status()["healthy"] is False
    for callback in app.router.on_startup:
        callback()
    assert recorder.status()["healthy"] is True
    recorder.record_request_final(InferenceRequest(request_id="fixture", server_instance_id="s1",
                                                   source="gateway", state="completed"))
    recorder.stop()
    assert store.get_inference_request("fixture") is not None


def test_inference_routes_are_authenticated_versioned_and_read_only(tmp_path):
    service = FakeService()
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_inference_web_app(service, login_code="local-code", static_dir=Path(tmp_path))

    with TestClient(app, base_url="http://localhost") as client:
        assert service.started is True
        assert client.get("/api/inference/v1/status", headers={"Origin": "http://localhost"}).status_code == 401
        login = client.post("/auth/login", json={"code": "local-code"}, headers={"Origin": "http://localhost"})
        assert login.status_code == 204

        status = client.get("/api/inference/v1/status", headers={"Origin": "http://localhost"})
        models = client.get("/api/inference/v1/models", headers={"Origin": "http://localhost"})
        requests = client.get("/api/inference/v1/requests", headers={"Origin": "http://localhost"})

        assert status.json()["schema_version"] == 1
        assert status.headers["cache-control"] == "no-store"
        assert models.json()["models"][0]["provider_model_id"] == "fixture/model"
        assert requests.json()["requests"] == []

        hw = client.get("/api/inference/v1/hardware", headers={"Origin": "http://localhost"})
        assert hw.status_code == 200
        assert hw.json()["schema_version"] == 1
        assert "samples" in hw.json()
        assert hw.headers["cache-control"] == "no-store"

        analytics = client.get("/api/inference/v1/analytics", headers={"Origin": "http://localhost"})
        assert analytics.status_code == 200
        assert analytics.json()["schema_version"] == 1
        assert "request_counts" in analytics.json()["analytics"]
        assert analytics.headers["cache-control"] == "no-store"

        telem_404 = client.get("/api/inference/v1/requests/nonexistent/telemetry", headers={"Origin": "http://localhost"})
        assert telem_404.status_code == 404

    assert service.stopped is True
    assert list(tmp_path.glob("*.sqlite*")) == []


def test_web_app_requires_static_assets(tmp_path):
    service = FakeService()

    try:
        create_inference_web_app(service, login_code="local-code", static_dir=tmp_path)
    except ValueError as error:
        assert "index" in str(error).lower()
    else:
        raise AssertionError("the application must reject a missing static index")


def test_request_telemetry_endpoint_returns_timing_and_hardware(tmp_path):
    from llm_monitor.live_store import LiveInferenceStore
    from llm_monitor.inference_models import InferenceRequest

    store = LiveInferenceStore()
    req = InferenceRequest(
        request_id="req-123",
        server_instance_id="srv-1",
        source="gateway",
        state="completed",
        started_at="2026-11-01T20:00:00Z",
        ended_at="2026-11-01T20:00:02Z",
        elapsed_seconds=2.0,
        input_tokens=15,
        output_tokens=25,
        generated_tokens=25,
        gpu_average_percent=68.5,
        gpu_peak_vram_bytes=1024 * 1024 * 1024,
        gpu_scope="Device measurement · n=2",
        time_to_first_text_seconds=0.35,
        generation_tokens_per_second=12.5,
    )
    store.add_request(req)

    class ServiceWithStore(FakeService):
        def __init__(self):
            super().__init__()
            self.store = store

        def snapshot(self):
            snap = super().snapshot()
            snap["requests"] = [r.to_dict() for r in store.requests()]
            return snap

    service = ServiceWithStore()
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_inference_web_app(service, login_code="local-code", static_dir=Path(tmp_path))

    with TestClient(app, base_url="http://localhost") as client:
        # Unauthenticated request returns 401
        assert client.get("/api/inference/v1/requests/req-123/telemetry", headers={"Origin": "http://localhost"}).status_code == 401
        client.post("/auth/login", json={"code": "local-code"}, headers={"Origin": "http://localhost"})

        res = client.get("/api/inference/v1/requests/req-123/telemetry", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"] == 1
        assert data["request_id"] == "req-123"
        assert data["timing"]["elapsed_seconds"] == 2.0
        assert data["timing"]["time_to_first_text_seconds"] == 0.35
        assert data["timing"]["generation_tokens_per_second"] == 12.5
        assert data["tokens"]["input_tokens"] == 15
        assert data["tokens"]["generated_tokens"] == 25
        assert data["hardware"]["gpu_average_percent"] == 68.5
        assert data["hardware"]["gpu_peak_vram_bytes"] == 1024 * 1024 * 1024


def test_recording_status_and_disabled_history(tmp_path):
    service = FakeService()
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_inference_web_app(service, login_code="local-code", static_dir=Path(tmp_path))

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "local-code"}, headers={"Origin": "http://localhost"})

        rec = client.get("/api/inference/v1/recording/status", headers={"Origin": "http://localhost"})
        assert rec.status_code == 200
        assert rec.json()["schema_version"] == 1
        assert rec.json()["recording"]["status"] == "disabled"

        hist = client.get("/api/inference/v1/history", headers={"Origin": "http://localhost"})
        assert hist.status_code == 200
        assert hist.json()["availability"] == "disabled"
        assert hist.json()["requests"] == []

        an = client.get("/api/inference/v1/history/analytics", headers={"Origin": "http://localhost"})
        assert an.status_code == 200
        assert an.json()["availability"] == "disabled"

        detail_404 = client.get("/api/inference/v1/history/req-xyz", headers={"Origin": "http://localhost"})
        assert detail_404.status_code == 404


def test_history_endpoints_with_recorded_database(tmp_path):
    from llm_monitor.storage import TelemetryStore
    from llm_monitor.inference_models import InferenceRequest, ContentSegment, HardwareSample

    db_path = tmp_path / "history_test.db"
    store = TelemetryStore(db_path)
    req = InferenceRequest(
        request_id="hist-123",
        server_instance_id="srv-hist",
        source="gateway",
        state="completed",
        started_at="2026-11-01T20:00:00Z",
        ended_at="2026-11-01T20:00:02Z",
        elapsed_seconds=2.0,
        model_name="qwen-2.5",
        input_tokens=10,
        output_tokens=20,
    )
    seg = ContentSegment(kind="user", text="hello historical", role="user", source="client")
    hw = HardwareSample(
        sample_id=1,
        device_id="gpu-0",
        device_name="RTX 5090",
        timestamp="2026-11-01T20:00:01Z",
        timestamp_monotonic=100.0,
        gpu_utilization_percent=55.0,
        vram_used_bytes=2 * 1024 * 1024 * 1024,
        source="nvidia_smi",
    )
    store.record_inference(req, recording_mode="content", contents=[seg], hardware_samples=[hw])

    service = FakeService()
    static_dir = tmp_path / "web_ui"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_inference_web_app(service, login_code="local-code", static_dir=static_dir, history_store=store)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "local-code"}, headers={"Origin": "http://localhost"})

        hist = client.get("/api/inference/v1/history", headers={"Origin": "http://localhost"})
        assert hist.status_code == 200
        assert hist.json()["availability"] == "available"
        assert hist.json()["total_count"] == 1
        assert hist.json()["requests"][0]["request_id"] == "hist-123"

        detail = client.get("/api/inference/v1/history/hist-123", headers={"Origin": "http://localhost"})
        assert detail.status_code == 200
        assert detail.json()["schema_version"] == 1
        assert detail.json()["request"]["request_id"] == "hist-123"
        assert len(detail.json()["request"]["content"]) == 1
        assert detail.json()["request"]["content"][0]["text"] == "hello historical"
        assert len(detail.json()["request"]["hardware_samples"]) == 1
        assert detail.json()["request"]["hardware_samples"][0]["gpu_utilization_percent"] == 55.0

        an = client.get("/api/inference/v1/history/analytics", headers={"Origin": "http://localhost"})
        assert an.status_code == 200
        assert an.json()["availability"] == "available"
        assert an.json()["analytics"]["request_counts"]["observed_requests"] == 1
