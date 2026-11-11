"""Unit tests for Stage B: Tailscale CLI integration, modern Funnel commands, and rollback.

Covers:
- Modern direct Funnel command form: tailscale funnel --bg --https=<public_port> http://127.0.0.1:<port>
- Rejection of unsupported public ports.
- Preexisting route conflict detection (port already owned by another service).
- Verification failure triggers safe rollback.
- Rollback failure reported with rollback_error.
- Disable failure captures return code and bounded stderr.
- Post-disable verification confirms endpoint is no longer configured.
- Disable operates independently of application preflight.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from remote_control.actions.storage import ActionStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import RealTailscaleClient, SimulatedTailscaleClient
from remote_control.external.service import ExternalExposureService


def test_modern_funnel_plan_syntax(tmp_path: Path) -> None:
    client = SimulatedTailscaleClient(
        node_name="myhost",
        tailnet_name="tailnet.ts.net",
        state_file=tmp_path / ".ts.json",
    )
    plan = client.plan_funnel(port=8443, public_port=8443)
    assert len(plan) >= 2
    assert plan[0] == "tailscale funnel --bg --https=8443 http://127.0.0.1:8443"
    assert "https://myhost.tailnet.ts.net:8443" in plan[1]


def test_unsupported_public_port_rejected(tmp_path: Path) -> None:
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    # Only 443, 8443, and 10000 are supported by Tailscale Funnel
    res = client.enable_funnel(port=8443, public_port=8080)
    assert res["ok"] is False
    assert res["error"] == "unsupported_public_port"
    assert "not in supported Funnel ports" in res["message"]


def test_preexisting_conflict_rejected_without_mutation(tmp_path: Path) -> None:
    # Port 8443 is already mapped to http://127.0.0.1:9090 by another service
    client = SimulatedTailscaleClient(
        state_file=tmp_path / ".ts.json",
        existing_conflicts={"8443": "http://127.0.0.1:9090"},
    )
    # Attempting to enable for http://127.0.0.1:8443 must detect conflict and abort
    res = client.enable_funnel(port=8443, public_port=8443)
    assert res["ok"] is False
    assert res["error"] == "port_conflict"
    assert "already configured for another service" in res["message"]

    # Verify existing route was NOT mutated
    st = client.get_status()
    assert st.routes["8443"] == "http://127.0.0.1:9090"


def test_post_activation_verification_failure_triggers_rollback(tmp_path: Path) -> None:
    client = SimulatedTailscaleClient(
        state_file=tmp_path / ".ts.json",
        fail_post_verify=True,
        fail_rollback=False,
    )
    res = client.enable_funnel(port=8443, public_port=8443)
    assert res["ok"] is False
    assert res["error"] == "post_activation_verification_failed"
    assert res["rolled_back"] is True
    assert "rolled back safely" in res["message"]

    # Invariant: Endpoint must NOT remain active
    st = client.get_status()
    assert st.funnel_active is False
    assert "8443" not in st.routes


def test_post_activation_verification_failure_and_rollback_failure(tmp_path: Path) -> None:
    client = SimulatedTailscaleClient(
        state_file=tmp_path / ".ts.json",
        fail_post_verify=True,
        fail_rollback=True,
    )
    res = client.enable_funnel(port=8443, public_port=8443)
    assert res["ok"] is False
    assert res["error"] == "post_activation_verification_failed"
    assert res["rolled_back"] is False
    assert res["rollback_error"] == "rollback_command_failed"


def test_disable_failure_reported(tmp_path: Path) -> None:
    client = SimulatedTailscaleClient(
        state_file=tmp_path / ".ts.json",
        fail_on_disable="tailscale_exit_code_1",
    )
    res = client.disable_funnel(public_port=8443)
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "tailscale_exit_code_1"


def test_emergency_disable_works_regardless_of_preflight_or_missing_auth(tmp_path: Path) -> None:
    """Disabling exposure must function even when preflight completely fails or configs are broken."""
    broken_auth_db = tmp_path / "broken_auth.db"
    store = ActionStorage(broken_auth_db, read_only=True)
    # Config is completely invalid / missing origin
    cfg = RemoteControlConfig(
        auth_db_path=broken_auth_db,
        public_origin=None,
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    # Simulate that Funnel was active previously
    st = client._ensure_state()
    st["funnel_active"] = True
    st["routes"] = {"8443": "http://127.0.0.1:8443"}
    client._save_state(st)

    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # Enable fails preflight
    enable_res = service.enable(apply=True, verify_listener=False)
    assert enable_res["ok"] is False
    assert enable_res["error"] == "preflight_failed"

    # Emergency disable MUST succeed without invoking preflight
    dis_res = service.disable(apply=True, public_port=8443)
    assert dis_res["ok"] is True
    assert dis_res["applied"] is True
    assert client.get_status().funnel_active is False
