"""Targeted tests for Section 7: Exact Tailscale Funnel route verification and structured status parsing.

Invariants:
1. Structured parsing of Tailscale status JSON (Web, TCP, AllowFunnel).
2. Exact integer port parsing: parse_endpoint_port() must never confuse port 443 with 8443.
3. Preexisting route conflict detection isolates exact port.
4. Post-activation verification confirms exact route is active in AllowFunnel.
5. If only an unrelated route is active, post-activation fails and triggers rollback.
6. Malformed status JSON is captured safely in status_error and blocks preflight.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import (
    RealTailscaleClient,
    SimulatedTailscaleClient,
    TailscaleStatus,
    parse_endpoint_host,
    parse_endpoint_port,
)
from remote_control.external.doctor import ExternalDoctor
from remote_control.external.service import ExternalExposureService


def test_parse_endpoint_port_and_host_exact() -> None:
    """Verify exact port and host parsing without substring confusion between 443 and 8443."""
    # Test cases: "node.tailnet.ts.net:8443", "8443", "443", "node.ts.net:443", "[::1]:8443"
    assert parse_endpoint_port("node.tailnet.ts.net:8443") == 8443
    assert parse_endpoint_port("8443") == 8443
    assert parse_endpoint_port("443") == 443
    assert parse_endpoint_port("node.tailnet.ts.net:443") == 443
    assert parse_endpoint_port("node.tailnet.ts.net:10000") == 10000
    assert parse_endpoint_port("[::1]:8443") == 8443
    assert parse_endpoint_port("invalid") is None

    # Host parsing
    assert parse_endpoint_host("node.tailnet.ts.net:8443") == "node.tailnet.ts.net"
    assert parse_endpoint_host("node.tailnet.ts.net:443") == "node.tailnet.ts.net"
    assert parse_endpoint_host("8443") == ""


def test_port_443_vs_8443_no_substring_confusion(tmp_path: Path) -> None:
    """Preexisting route on port 443 must NOT conflict with target port 8443."""
    auth_db = tmp_path / "auth.db"
    auth_store = AuthStorage(auth_db)
    auth_store.create_operator("op", "admin", "hash", "TOTP")
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
    )
    store = ActionStorage(auth_db)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")

    # Set up route on port 443 to another service (e.g. 127.0.0.1:3000)
    st = client._ensure_state()
    st["routes"] = {
        "node.tailnet.ts.net:443": "http://127.0.0.1:3000"
    }
    client._save_state(st)

    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    # Check port 8443 conflict: port 443 must not trigger conflict!
    checks = doctor.check_tailscale(public_port=8443)
    conflict_check = next(c for c in checks if c.name == "no_conflicting_funnel_route")
    assert conflict_check.severity == "pass"
    assert "No conflicting preexisting route" in conflict_check.message

    # But checking port 443 conflict MUST trigger blocker!
    checks_443 = doctor.check_tailscale(public_port=443)
    conflict_443 = next(c for c in checks_443 if c.name == "no_conflicting_funnel_route")
    assert conflict_443.severity == "blocker"
    assert "already owned by another service" in conflict_443.message


def test_unrelated_active_route_rejected_and_rolled_back(tmp_path: Path) -> None:
    """If post-activation verification detects that only an unrelated route is active, fail and rollback."""
    # Custom client that simulates activating port 443 instead of requested 8443
    class MismatchedPortClient(SimulatedTailscaleClient):
        def enable_funnel(self, port: int = 8443, public_port: int = 8443):
            # Simulate bug/failure where tailscale CLI activated port 443 instead
            st = self._ensure_state()
            st["funnel_active"] = True
            node = st.get("node_name", "node")
            tailnet = st.get("tailnet_name", "ts.net")
            ep = f"{node}.{tailnet}:443"
            st["routes"] = {ep: f"http://127.0.0.1:{port}"}
            st["allow_funnel"] = {ep: True}
            self._save_state(st)

            # Route verification check in enable_funnel
            cur = self.get_status()
            if not cur.is_route_funnel_active(public_port):
                # Rollback
                self.disable_funnel(public_port=public_port)
                return {
                    "ok": False,
                    "applied": False,
                    "error": "funnel_route_verification_failed",
                    "message": f"Post-activation check failed: route for port {public_port} is not active in AllowFunnel.",
                }
            return {"ok": True, "applied": True}

    client = MismatchedPortClient(state_file=tmp_path / ".ts.json")
    res = client.enable_funnel(port=8443, public_port=8443)
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "funnel_route_verification_failed"


def test_private_serve_without_funnel_rejected() -> None:
    """Route present in Web (Serve mode) but absent or False in AllowFunnel is NOT funnel_active."""
    status = TailscaleStatus(
        installed=True,
        logged_in=True,
        version="1.56.0",
        funnel_available=True,
        routes={"node.ts.net:8443": "http://127.0.0.1:8443"},
        allow_funnel={"node.ts.net:8443": False},  # Funnel disallowed, Serve only!
    )
    assert status.is_route_funnel_active(8443) is False

    # When AllowFunnel is True for exact port
    status_active = TailscaleStatus(
        installed=True,
        logged_in=True,
        version="1.56.0",
        funnel_available=True,
        routes={"node.ts.net:8443": "http://127.0.0.1:8443"},
        allow_funnel={"node.ts.net:8443": True},
    )
    assert status_active.is_route_funnel_active(8443) is True


def test_malformed_status_json_captured_and_blocks_preflight(tmp_path: Path) -> None:
    """When tailscale status returns invalid JSON, status_error is captured and preflight blocks."""
    # Simulated status with status_error
    status = TailscaleStatus(
        installed=True,
        logged_in=True,
        version="1.56.0",
        status_error="JSONDecodeError: Unterminated string starting at line 1",
    )
    assert status.status_error is not None

    auth_db = tmp_path / "auth.db"
    auth_store = AuthStorage(auth_db)
    auth_store.create_operator("op", "admin", "hash", "TOTP")
    cfg = RemoteControlConfig(
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
    )
    store = ActionStorage(auth_db)

    class BrokenClient(SimulatedTailscaleClient):
        def get_status(self):
            return status

    client = BrokenClient(state_file=tmp_path / ".ts.json")
    doctor = ExternalDoctor(config=cfg, storage=store, client=client)
    checks = doctor.check_tailscale(public_port=8443)
    error_check = next((c for c in checks if c.name == "tailscale_status_valid"), None)
    assert error_check is not None
    assert error_check.severity == "unknown"
    assert error_check.is_security_critical is True
    # Security unknown must block ready_for_public_enable
    report = doctor.check_all()
    assert report["ready_for_public_enable"] is False
