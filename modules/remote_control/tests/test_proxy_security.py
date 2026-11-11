"""Tests for Stage B & C: Public HTTPS, Reverse Proxy Boundary, and Policy Enforcement."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import pyotp
import pytest
from fastapi.testclient import TestClient

from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine
from remote_control.app import create_app
from remote_control.config import RemoteControlConfig


def _setup_app(tmp_path: Path, **config_overrides: Any) -> Tuple[TestClient, RemoteControlConfig, str, str]:
    auth_db = tmp_path / "auth.db"
    notif_db = tmp_path / "events.db"
    hc_json = tmp_path / "hc.json"
    hc_json.write_text('{"ping_url": "https://hc-ping.com/test", "enabled": true}', encoding="utf-8")

    notif_storage = StorageEngine(notif_db)
    notif_storage.migrate()
    lifecycle = IncidentLifecycleEngine(notif_storage)
    event = EventEnvelopeV1(
        schema_version=1,
        event_id=str(uuid.uuid4()),
        source="desktop_monitor",
        kind="heartbeat.loss",
        incident_key="desktop_monitor:heartbeat_loss",
        severity="critical",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        summary="Simulated host outage",
        lifecycle="open",
    )
    res = lifecycle.process_event(event)
    incident_id = res.incident_id

    cfg_kwargs = dict(
        auth_db_path=auth_db,
        notifications_db_path=notif_db,
        healthchecks_config_path=hc_json,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
        allowed_origins=["http://testserver", "https://testserver"],
    )
    cfg_kwargs.update(config_overrides)
    cfg = RemoteControlConfig(**cfg_kwargs)

    app = create_app(cfg)
    client = TestClient(app, base_url="https://testserver")

    # Bootstrap operator
    auth_svc = app.state.auth_service
    _, totp_secret, _ = auth_svc.bootstrap(
        username="admin",
        password="ValidPassword123!",
        totp_secret="JBSWY3DPEHPK3PXP",
        ip_address="127.0.0.1",
    )

    # Log in
    totp = pyotp.TOTP(totp_secret)
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ValidPassword123!", "totp_code": totp.now()},
    )
    assert login_res.status_code == 200
    csrf_token = login_res.json()["csrf_token"]

    return client, cfg, incident_id, csrf_token


def test_untrusted_proxy_peer_forwarded_headers_ignored(tmp_path: Path) -> None:
    """Spoofed X-Forwarded-* headers from untrusted proxy peer must be ignored."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        trusted_proxy_peers=["127.0.0.1"],
    )

    resp = client.get(
        "/api/summary",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "spoofed.com",
            "X-Forwarded-For": "8.8.8.8",
        },
    )
    assert resp.status_code == 200
    # Response must still have secure headers
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_host_header_validation_external(tmp_path: Path) -> None:
    """When external exposure is enabled, Host header must be in allowed list."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
    )

    # Invalid host
    res_bad = client.get("/api/summary", headers={"Host": "evil-attacker.com"})
    assert res_bad.status_code == 400
    assert res_bad.json()["error"] == "invalid_host_header"

    # Valid allowed public host
    res_good = client.get("/api/summary", headers={"Host": "dashboard.tailnet.ts.net"})
    assert res_good.status_code == 200


def test_origin_header_validation_external(tmp_path: Path) -> None:
    """State-changing requests must match pinned public_origin."""
    client, cfg, incident_id, csrf_token = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
    )

    # Disallowed origin
    res_bad = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "Origin": "https://evil.com",
            "X-CSRF-Token": csrf_token,
        },
        json={"parameters": {"incident_id": incident_id, "reason": "Test ack"}},
    )
    assert res_bad.status_code == 403
    assert res_bad.json()["error"] == "forbidden_origin"

    # Matching public origin
    res_good = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "Origin": "https://dashboard.tailnet.ts.net",
            "X-CSRF-Token": csrf_token,
        },
        json={"parameters": {"incident_id": incident_id, "reason": "Test ack"}},
    )
    assert res_good.status_code == 200


def test_security_headers_and_hsts(tmp_path: Path) -> None:
    """HSTS, CSP, and Cache-Control headers must be present."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
    )

    resp = client.get("/api/summary", headers={"Host": "dashboard.tailnet.ts.net"})
    assert resp.status_code == 200
    assert "Strict-Transport-Security" in resp.headers
    assert "max-age=" in resp.headers["Strict-Transport-Security"]
    assert "Content-Security-Policy" in resp.headers
    assert "no-store" in resp.headers["Cache-Control"]


def test_cookie_security_mode_strict(tmp_path: Path) -> None:
    """In external exposure / strict mode, cookies use __Host- prefix and Secure flag."""
    auth_db = tmp_path / "auth.db"
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        external_exposure_enabled=True,
        cookie_security_mode="strict",
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_hosts=["dashboard.tailnet.ts.net", "testserver"],
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
    )
    app = create_app(cfg)
    client = TestClient(app, base_url="https://dashboard.tailnet.ts.net")

    # Bootstrap operator
    auth_svc = app.state.auth_service
    _, totp_secret, _ = auth_svc.bootstrap(
        username="admin",
        password="ValidPassword123!",
        totp_secret="JBSWY3DPEHPK3PXP",
        ip_address="127.0.0.1",
    )

    totp = pyotp.TOTP(totp_secret)
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ValidPassword123!", "totp_code": totp.now()},
    )
    assert login_res.status_code == 200
    set_cookie = login_res.headers.get("set-cookie", "")
    assert "__Host-rc_session=" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


def test_conservative_public_action_policy(tmp_path: Path) -> None:
    """Conservative policy allows read actions and incident ack, blocks recovery mutations."""
    client, cfg, incident_id, csrf_token = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        public_action_policy="conservative",
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
    )

    # 1. Read action is allowed
    read_res = client.get("/api/v1/capabilities")
    assert read_res.status_code == 200

    # 2. Incident ack is allowed under conservative policy
    prep_res = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "Origin": "https://dashboard.tailnet.ts.net",
            "X-CSRF-Token": csrf_token,
        },
        json={"parameters": {"incident_id": incident_id, "reason": "Operator checked incident"}},
    )
    assert prep_res.status_code == 200

    # 3. Guarded recovery action is rejected
    recov_prep = client.post(
        "/api/v1/actions/resource_coordinator.request_guarded_recovery/prepare",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "Origin": "https://dashboard.tailnet.ts.net",
            "X-CSRF-Token": csrf_token,
        },
        json={"parameters": {"resource": "gpu.inference", "reason": "Attempting external recovery"}},
    )
    # Disabled or policy violation
    assert recov_prep.status_code in (403, 400)


def test_malformed_forwarded_proto_rejected(tmp_path: Path) -> None:
    """Malformed X-Forwarded-Proto from trusted peer must be rejected with 400."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        trusted_proxy_peers=["127.0.0.1", "testclient"],
    )

    resp = client.get(
        "/api/summary",
        headers={"X-Forwarded-Proto": "ftp"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_forwarded_proto"


def test_conflicting_forwarded_http_in_public_exposure_rejected(tmp_path: Path) -> None:
    """Insecure X-Forwarded-Proto: http under public exposure must be rejected with 400."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
        trusted_proxy_peers=["127.0.0.1", "testclient"],
    )

    resp = client.get(
        "/api/summary",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "X-Forwarded-Proto": "http",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "conflicting_forwarded_protocol"


def test_malformed_forwarded_port_rejected(tmp_path: Path) -> None:
    """Non-numeric X-Forwarded-Port must be rejected with 400."""
    client, cfg, _, _ = _setup_app(
        tmp_path,
        trusted_proxy_peers=["127.0.0.1", "testclient"],
    )

    resp = client.get(
        "/api/summary",
        headers={"X-Forwarded-Port": "invalid_port_999999"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_forwarded_port"


def test_broad_origin_cannot_bypass_pinned_public_origin(tmp_path: Path) -> None:
    """Under external exposure, a broad allowed_origins entry cannot bypass the pinned public_origin."""
    client, cfg, incident_id, csrf_token = _setup_app(
        tmp_path,
        external_exposure_enabled=True,
        public_origin="https://dashboard.tailnet.ts.net",
        allowed_public_hosts=["dashboard.tailnet.ts.net"],
        allowed_origins=["https://dashboard.tailnet.ts.net", "https://other-broad-domain.com"],
    )

    # State-changing POST from https://other-broad-domain.com MUST be rejected
    resp = client.post(
        "/api/v1/actions/notifications.acknowledge_incident/prepare",
        headers={
            "Host": "dashboard.tailnet.ts.net",
            "Origin": "https://other-broad-domain.com",
            "X-CSRF-Token": csrf_token,
        },
        json={"parameters": {"incident_id": incident_id, "reason": "Bypass attempt"}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden_origin"
