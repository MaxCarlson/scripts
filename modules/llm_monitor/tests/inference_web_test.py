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
