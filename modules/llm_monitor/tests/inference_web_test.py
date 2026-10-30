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
