"""Targeted tests for Section 4: Production configuration enforcement before activation.

Invariants:
1. Strict cookie security mode and cookie_secure=True required.
2. external_exposure_enabled=True required.
3. Missing or non-HTTPS public_origin blocks.
4. Port mismatch between public_origin and Funnel public_port blocks.
5. Local listener reachability and identity probe via unauthenticated /api/health endpoint.
6. Offline listener blocks activation.
7. Unrelated server listening on loopback (wrong app identity) blocks activation.
8. CLI disallows --skip-listener-check with -a / --apply (0 Tailscale mutations).
9. Strict valid production config passes preflight.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from remote_control.actions.registry import ActionRegistry
from remote_control.actions.storage import ActionStorage
from remote_control.app import create_app
from remote_control.auth.storage import AuthStorage
from remote_control.cli import main
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.doctor import ExternalDoctor
from remote_control.external.service import ExternalExposureService


def _seed_valid_auth(db_path: Path) -> None:
    auth_store = AuthStorage(db_path)
    auth_store.create_operator("op_admin", "admin", "$argon2id$v=19$dummy", "JBSWY3DPEHPK3PXP")


def test_health_endpoints_unauthenticated_and_read_only(tmp_path: Path) -> None:
    """Verify /api/health and /api/v1/health return expected schema without authentication."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://myhost.ts.net:8443",
        allowed_public_hosts=["myhost.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
    )
    app = create_app(cfg)
    client = TestClient(app, base_url="http://127.0.0.1:8443")

    for path in ("/api/health", "/api/v1/health"):
        resp = client.get(path)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["app"] == "remote_control"
        assert data["service"] == "remote_control"
        assert data["status"] == "healthy"
        assert data["external_exposure_enabled"] is True
        assert data["cookie_security_mode"] == "strict"
        assert data["cookie_secure"] is True
        assert data["public_origin"] == "https://myhost.ts.net:8443"
        assert data["coordinator_recovery_enabled"] is False


def test_exposure_disabled_blocks_preflight(tmp_path: Path) -> None:
    """external_exposure_enabled=False must block preflight."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://myhost.ts.net:8443",
        cookie_security_mode="strict",
        external_exposure_enabled=False,  # BLOCKS
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    checks = doctor.check_cookie_and_proxy_policy()
    exp_check = next(c for c in checks if c.name == "external_exposure_enabled")
    assert exp_check.severity == "blocker"
    assert "external_exposure_enabled is False" in exp_check.message


def test_auto_cookie_mode_blocks_preflight(tmp_path: Path) -> None:
    """cookie_security_mode='auto' without external_exposure_enabled must block preflight."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://myhost.ts.net:8443",
        cookie_security_mode="auto",
        external_exposure_enabled=False,
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    checks = doctor.check_cookie_and_proxy_policy()
    cookie_check = next(c for c in checks if c.name == "cookie_security_strict")
    assert cookie_check.severity == "blocker"


def test_missing_public_origin_blocks_preflight(tmp_path: Path) -> None:
    """Missing public_origin must block preflight."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin=None,
        cookie_security_mode="strict",
        external_exposure_enabled=True,
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    checks = doctor.check_origin_and_hosts()
    origin_check = next(c for c in checks if c.name == "public_origin_configured")
    assert origin_check.severity == "blocker"


def test_public_origin_port_mismatch_blocks(tmp_path: Path) -> None:
    """Port in public_origin (443) must match Funnel public port (8443)."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://myhost.ts.net:443",  # Mismatch with 8443
        allowed_public_hosts=["myhost.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    checks = doctor.check_origin_and_hosts(public_port=8443)
    port_check = next(c for c in checks if c.name == "public_origin_port_match")
    assert port_check.severity == "blocker"
    assert "does not match configured Funnel public port" in port_check.message


def test_listener_offline_blocks(tmp_path: Path) -> None:
    """Offline target listener blocks preflight fail closed."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(auth_db_path=auth_db, port=59999)  # Port not listened on
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    check = doctor.check_local_listener(host="127.0.0.1", port=59999, verify_listener=True)
    assert check.severity == "blocker"
    assert "No active process listening" in check.message or "offline" in check.details.get("status", "")


def test_unrelated_server_on_target_port_blocks(tmp_path: Path) -> None:
    """An unrelated server running on target port returning non-remote_control app blocks."""
    # Spin up a dummy HTTP server on a dynamic port
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"app": "unrelated_service", "status": "ok"}).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DummyHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        auth_db = tmp_path / "auth.db"
        _seed_valid_auth(auth_db)
        cfg = RemoteControlConfig(auth_db_path=auth_db, port=port)
        store = ActionStorage(auth_db)
        client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
        doctor = ExternalDoctor(config=cfg, storage=store, client=client)
        check = doctor.check_local_listener(host="127.0.0.1", port=port, verify_listener=True)
        assert check.severity == "blocker"
        assert "not the Remote Control application" in check.message
    finally:
        server.shutdown()
        server.server_close()


def test_cli_disallows_skip_listener_check_with_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Disallow --skip-listener-check with -a / --apply, ensuring 0 Tailscale mutations occur."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    state_file = tmp_path / ".ts.json"
    monkeypatch.setenv("REMOTE_CONTROL_AUTH_DB_PATH", str(auth_db))
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATE_TAILSCALE", "1")
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATED_STATE_PATH", str(state_file))
    monkeypatch.setenv("REMOTE_CONTROL_PUBLIC_ORIGIN", "https://workstation.tailnet.ts.net:8443")
    monkeypatch.setenv("REMOTE_CONTROL_EXTERNAL_EXPOSURE", "1")
    monkeypatch.setenv("REMOTE_CONTROL_COOKIE_SECURITY_MODE", "strict")

    # Call CLI with -a and --skip-listener-check
    code = main(["external", "enable", "-a", "--skip-listener-check", "--json"])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["applied"] is False
    assert out["error"] == "listener_check_required"

    # Verify zero Tailscale mutations occurred (funnel is not active)
    client = SimulatedTailscaleClient(state_file=state_file)
    assert client.get_status().funnel_active is False


def test_strict_valid_production_config_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict valid production configuration satisfies all preflight requirements."""
    auth_db = tmp_path / "auth.db"
    _seed_valid_auth(auth_db)
    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://workstation.tailnet.ts.net:8443",
        allowed_public_hosts=["workstation.tailnet.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
        trusted_proxy_peers=["127.0.0.1"],
        public_action_policy="conservative",
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(
        node_name="workstation",
        tailnet_name="tailnet.ts.net",
        version="1.56.0-simulated",
        state_file=tmp_path / ".ts.json",
    )
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # In dry-run without live listener
    res = service.enable(apply=False, port=8443, public_port=8443, verify_listener=False)
    assert res["ok"] is True
    assert res["applied"] is False
    assert res["ready_for_public_enable"] is True
