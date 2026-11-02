from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_monitor.inference_models import CaptureCapabilities, InferenceRequest
from llm_monitor.inference_recording import InferenceRecorder
from llm_monitor.inference_web import create_inference_web_app
from llm_monitor.storage import TelemetryStore


class FakeService:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.value = {
            "schema_version": 1,
            "revision": 1,
            "refreshed_at": "2026-11-01T12:00:00Z",
            "server": {"connection_state": "connected", "endpoint": "http://127.0.0.1:1234"},
            "servers": [{"server_instance_id": "server-1", "connection_state": "connected"}],
            "capabilities": CaptureCapabilities.passive_inventory(available=True).to_dict(),
            "models": [{"provider_model_id": "qwen38-27b-q4km", "state": "loaded"}],
            "requests": [],
            "recording": {"status": "active", "mode": "metadata"},
        }

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return self.value


def test_recording_mode_mutation_api(tmp_path):
    service = FakeService()
    db_path = tmp_path / "test_inference.sqlite3"
    storage = TelemetryStore(db_path)
    recorder = InferenceRecorder(store=storage, mode="metadata")

    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    app = create_inference_web_app(
        service,
        login_code="test-code",
        static_dir=Path(tmp_path),
        recorder=recorder,
    )

    with TestClient(app, base_url="http://localhost") as client:
        # Must be authenticated
        res = client.post("/api/inference/v1/recording/mode", json={"mode": "content"}, headers={"Origin": "http://localhost"})
        assert res.status_code == 401

        login = client.post("/auth/login", json={"code": "test-code"}, headers={"Origin": "http://localhost"})
        assert login.status_code == 204

        # Mutate to content
        res = client.post("/api/inference/v1/recording/mode", json={"mode": "content"}, headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["recording"]["mode"] == "content"
        assert recorder.mode == "content"

        # Mutate back to metadata
        res = client.post("/api/inference/v1/recording/mode", json={"mode": "metadata"}, headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        assert res.json()["recording"]["mode"] == "metadata"
        assert recorder.mode == "metadata"

        # Invalid mode returns 400 Bad Request
        res = client.post("/api/inference/v1/recording/mode", json={"mode": "invalid_mode"}, headers={"Origin": "http://localhost"})
        assert res.status_code == 400


def test_history_server_filter(tmp_path):
    service = FakeService()
    db_path = tmp_path / "test_history.sqlite3"
    storage = TelemetryStore(db_path)

    # Insert two requests from different servers
    req1 = InferenceRequest(
        request_id="req-s1",
        server_instance_id="server-alpha",
        source="gateway_openai_chat_completions",
        model_instance_id="model-1",
        state="completed",
        started_at="2026-11-01T10:00:00Z",
    )
    req2 = InferenceRequest(
        request_id="req-s2",
        server_instance_id="server-beta",
        source="gateway_openai_chat_completions",
        model_instance_id="model-1",
        state="completed",
        started_at="2026-11-01T10:05:00Z",
    )
    storage.record_inference(req1, "metadata")
    storage.record_inference(req2, "metadata")

    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    app = create_inference_web_app(
        service,
        login_code="test-code",
        static_dir=Path(tmp_path),
        history_store=storage,
    )

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-code"}, headers={"Origin": "http://localhost"})

        # Query all
        res_all = client.get("/api/inference/v1/history", headers={"Origin": "http://localhost"})
        assert res_all.status_code == 200
        assert res_all.json()["total_count"] == 2

        # Query server-alpha
        res_alpha = client.get("/api/inference/v1/history?server_instance_id=server-alpha", headers={"Origin": "http://localhost"})
        assert res_alpha.status_code == 200
        assert res_alpha.json()["total_count"] == 1
        assert res_alpha.json()["requests"][0]["request_id"] == "req-s1"

        # Query server-beta
        res_beta = client.get("/api/inference/v1/history?server_instance_id=server-beta", headers={"Origin": "http://localhost"})
        assert res_beta.status_code == 200
        assert res_beta.json()["total_count"] == 1
        assert res_beta.json()["requests"][0]["request_id"] == "req-s2"


def test_request_list_scroll_trapping_removed():
    css_path = Path(__file__).resolve().parent.parent / "llm_monitor" / "web_static" / "assets" / "app.css"
    content = css_path.read_text(encoding="utf-8")
    assert "overscroll-behavior: auto" in content
    assert "overscroll-behavior: contain" not in content
