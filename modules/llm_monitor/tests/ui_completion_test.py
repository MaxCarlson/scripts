from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_monitor.inference_models import CaptureCapabilities, ContentSegment, InferenceRequest
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


def test_runtime_recording_mode_transition_privacy_invariant(tmp_path: Path):
    """Switching from metadata to content while a request is active MUST NOT

    retroactively persist prompt, reasoning, or output generated before content
    recording was authorized.
    """
    db_path = tmp_path / "privacy_test.sqlite3"
    storage = TelemetryStore(db_path)
    recorder = InferenceRecorder(store=storage, mode="metadata")
    recorder.start()

    # 1. Request starts under metadata mode
    req_inflight = InferenceRequest(
        request_id="req-in-flight",
        server_instance_id="s1",
        source="gateway_openai_chat_completions",
        model_instance_id="m1",
        state="running",
        started_at="2026-11-01T12:00:00Z",
    )
    recorder.record_request_start(req_inflight)

    secret_content = [
        ContentSegment(sequence=1, kind="user", role="user", text="SENSITIVE PROMPT BEFORE CONTENT RECORDING"),
        ContentSegment(sequence=2, kind="reasoning", role="assistant", text="THOUGHTS BEFORE CONTENT RECORDING"),
    ]

    # 2. User switches to content recording while req-in-flight is still active
    recorder.set_mode("content")
    assert recorder.mode == "content"

    # 3. In-flight request completes
    req_inflight_final = InferenceRequest(
        **{
            **req_inflight.__dict__,
            "state": "completed",
            "ended_at": "2026-11-01T12:00:05Z",
            "elapsed_seconds": 5.0,
        }
    )
    recorder.record_request_final(req_inflight_final, contents=secret_content)

    # 4. A new request begins AFTER content recording was authorized
    req_authorized = InferenceRequest(
        request_id="req-authorized",
        server_instance_id="s1",
        source="gateway_openai_chat_completions",
        model_instance_id="m1",
        state="running",
        started_at="2026-11-01T12:00:10Z",
    )
    recorder.record_request_start(req_authorized)

    authorized_content = [
        ContentSegment(sequence=1, kind="user", role="user", text="AUTHORIZED PROMPT"),
        ContentSegment(sequence=2, kind="assistant", role="assistant", text="AUTHORIZED OUTPUT"),
    ]
    req_authorized_final = InferenceRequest(
        **{
            **req_authorized.__dict__,
            "state": "completed",
            "ended_at": "2026-11-01T12:00:12Z",
            "elapsed_seconds": 2.0,
        }
    )
    recorder.record_request_final(req_authorized_final, contents=authorized_content)

    # 5. Revocation test: switch back to metadata while a third request is active
    req_revoked = InferenceRequest(
        request_id="req-revoked",
        server_instance_id="s1",
        source="gateway_openai_chat_completions",
        model_instance_id="m1",
        state="running",
        started_at="2026-11-01T12:00:15Z",
    )
    recorder.record_request_start(req_revoked)
    recorder.set_mode("metadata")

    revoked_content = [
        ContentSegment(sequence=1, kind="user", role="user", text="REVOKED PROMPT"),
    ]
    req_revoked_final = InferenceRequest(
        **{
            **req_revoked.__dict__,
            "state": "completed",
            "ended_at": "2026-11-01T12:00:18Z",
            "elapsed_seconds": 3.0,
        }
    )
    recorder.record_request_final(req_revoked_final, contents=revoked_content)

    recorder.flush()
    recorder.stop()

    # Invariant Verification in SQLite:
    # 1. req-in-flight MUST NOT have stored contents
    in_flight_db = storage.get_inference_request("req-in-flight", include_content=True)
    assert in_flight_db is not None
    assert in_flight_db["recording_mode"] == "metadata"
    assert in_flight_db["content"] == []

    # 2. req-authorized MUST have stored contents
    auth_db = storage.get_inference_request("req-authorized", include_content=True)
    assert auth_db is not None
    assert auth_db["recording_mode"] == "content"
    assert len(auth_db["content"]) == 2
    assert auth_db["content"][0]["text"] == "AUTHORIZED PROMPT"

    # 3. req-revoked MUST NOT have stored contents
    revoked_db = storage.get_inference_request("req-revoked", include_content=True)
    assert revoked_db is not None
    assert revoked_db["recording_mode"] == "metadata"
    assert revoked_db["content"] == []


def test_recording_disabled_explains_requirement(tmp_path: Path):
    service = FakeService()
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    app = create_inference_web_app(
        service,
        login_code="test-code",
        static_dir=Path(tmp_path),
        recorder=None,
    )

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-code"}, headers={"Origin": "http://localhost"})

        # Status explains disabled state
        status_res = client.get("/api/inference/v1/recording/status", headers={"Origin": "http://localhost"})
        assert status_res.status_code == 200
        rec_data = status_res.json()["recording"]
        assert rec_data["status"] == "disabled"
        assert rec_data["mode"] == "disabled"
        assert rec_data["metadata"] is False

        # Attempting mutation returns 400 explaining -R requirement
        mode_res = client.post("/api/inference/v1/recording/mode", json={"mode": "metadata"}, headers={"Origin": "http://localhost"})
        assert mode_res.status_code == 400
        detail = mode_res.json()["detail"]
        assert "-R" in detail or "--record-inferences" in detail

