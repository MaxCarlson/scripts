"""Tests for Phase 02 local control channel, capability tokens, and authentication bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from llm_monitor.local_control import (
    LocalCapabilityManager,
    LocalControlServer,
    LocalControlClient,
)
from llm_monitor.local_client import ManagedMonitorClient
from llm_monitor.server_lifecycle import ServerDescriptor


def test_capability_manager_issue_and_verify():
    manager = LocalCapabilityManager(instance_id="inst-test-123")
    token_record = manager.issue_read_capability(
        requested_scopes=["inference:models:read", "inference:status:read"],
        ttl_seconds=5.0,
    )
    assert token_record.token
    assert token_record.expires_in_seconds == 5.0
    assert "inference:models:read" in token_record.issued_scopes

    # Valid verification
    assert manager.verify_token(token_record.token, "inference:models:read", "inst-test-123") is True
    assert manager.verify_token(token_record.token, "inference:status:read", "inst-test-123") is True

    # Missing scope fails
    assert manager.verify_token(token_record.token, "history:verification:read", "inst-test-123") is False

    # Wrong instance fails
    assert manager.verify_token(token_record.token, "inference:models:read", "wrong-instance") is False

    # Revocation works
    assert manager.revoke_token(token_record.token) is True
    assert manager.verify_token(token_record.token, "inference:models:read", "inst-test-123") is False


def test_capability_manager_expiration():
    manager = LocalCapabilityManager(instance_id="inst-exp-1")
    token_record = manager.issue_read_capability(
        requested_scopes=["inference:models:read"],
        ttl_seconds=0.1,
    )
    assert manager.verify_token(token_record.token, "inference:models:read", "inst-exp-1") is True
    time.sleep(0.15)
    assert manager.verify_token(token_record.token, "inference:models:read", "inst-exp-1") is False


def test_local_control_ipc_round_trip(tmp_path: Path):
    instance_id = "inst-ipc-test"
    manager = LocalCapabilityManager(instance_id=instance_id)
    server = LocalControlServer(
        instance_id=instance_id,
        capability_manager=manager,
        state_dir=tmp_path,
    )
    server.start()
    try:
        client = LocalControlClient(
            endpoint=server.endpoint,
            instance_id=instance_id,
        )
        # 1. Hello
        hello = client.hello()
        assert hello["status"] == "ok"
        assert hello["instance_id"] == instance_id

        # 2. Issue capability
        cap = client.issue_read_capability(["inference:models:read"])
        assert cap["instance_id"] == instance_id
        token = cap["capability_token"]
        assert manager.verify_token(token, "inference:models:read", instance_id) is True

        # 3. Revoke
        rev = client.revoke_capability(token)
        assert rev["status"] == "revoked"
        assert manager.verify_token(token, "inference:models:read", instance_id) is False
    finally:
        server.stop()


def test_http_api_capability_token_authentication():
    from llm_monitor.inference_service import InferenceMonitoringService
    from llm_monitor.inference_web import create_inference_web_app

    class DummyProvider:
        def list_models(self):
            return [{"id": "model-1"}]
        def server_status(self):
            return {"status": "ok"}

    service = InferenceMonitoringService(DummyProvider(), endpoint="http://127.0.0.1:1234", refresh_interval_seconds=10.0)
    service.refresh()
    instance_id = "inst-http-auth"
    cap_manager = LocalCapabilityManager(instance_id=instance_id)

    app = create_inference_web_app(
        service,
        login_code="test-code-12345",
        capability_manager=cap_manager,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8788")

    headers_base = {
        "Host": "127.0.0.1:8788",
        "Origin": "http://127.0.0.1:8788",
    }

    # 1. Unauthenticated request -> 401
    resp_unauth = client.get("/api/inference/v1/models", headers=headers_base)
    assert resp_unauth.status_code == 401

    # 2. Authenticated with scoped read token -> 200
    token_record = cap_manager.issue_read_capability(["inference:models:read"])
    resp_auth = client.get(
        "/api/inference/v1/models",
        headers={**headers_base, "Authorization": f"Bearer {token_record.token}"},
    )
    assert resp_auth.status_code == 200
    data = resp_auth.json()
    assert data["schema_version"] == 1
    assert len(data["models"]) == 1
    assert data["models"][0]["provider_model_id"] == "model-1"

    # 3. Bearer token cannot perform POST mutations -> 401
    resp_post = client.post(
        "/api/inference/v1/recording/mode",
        headers={**headers_base, "Authorization": f"Bearer {token_record.token}"},
        json={"mode": "off"},
    )
    assert resp_post.status_code == 401

    # 4. Browser login with code still works -> sets session cookie
    resp_login = client.post(
        "/auth/login",
        headers=headers_base,
        json={"code": "test-code-12345"},
    )
    assert resp_login.status_code == 204
    assert "llm_monitor_session" in client.cookies

    # 5. Browser cookie can access API
    resp_cookie = client.get("/api/inference/v1/models", headers=headers_base)
    assert resp_cookie.status_code == 200


def test_managed_monitor_client_live(tmp_path: Path):
    instance_id = "inst-client-test"
    cap_manager = LocalCapabilityManager(instance_id=instance_id)
    control_server = LocalControlServer(instance_id=instance_id, capability_manager=cap_manager, state_dir=tmp_path)
    control_server.start()

    desc = ServerDescriptor(
        instance_id=instance_id,
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=8788,
        pid=os.getpid(),
        process_create_time=None,
        started_at="2026-11-02T12:00:00Z",
        control_token="secret",
        control_endpoint=control_server.endpoint,
    )

    try:
        client = ManagedMonitorClient(port=8788, host="127.0.0.1", state_dir=tmp_path, descriptor=desc)
        token = client.acquire_capability_token()
        assert token
        assert cap_manager.verify_token(token, "inference:models:read", instance_id) is True

        # Cached token returned
        token2 = client.acquire_capability_token()
        assert token2 == token

        # Force refresh yields new token
        token3 = client.acquire_capability_token(force_refresh=True)
        assert token3 != token
        assert cap_manager.verify_token(token3, "inference:models:read", instance_id) is True
    finally:
        control_server.stop()


