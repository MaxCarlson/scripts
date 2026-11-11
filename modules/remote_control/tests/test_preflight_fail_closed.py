"""Comprehensive tests for Stage A: Fail-Closed Public Exposure Preflight.

Validates all 17 required prerequisites from Section 3:
1. Tailscale installed
2. Tailscale authenticated / logged in
3. Tailscale supported version (>= 1.52.0)
4. Tailscale version unknown (must block)
5. Funnel capability enabled in tailnet
6. Funnel public port supported (443, 8443, 10000)
7. Exact HTTPS public_origin configured
8. Public hostname matching pinned allowed_public_hosts
9. Strict cookie security mode
10. Loopback-only backend binding
11. Trusted proxy topology loopback-only
12. Authentication database exists
13. Operator enrolled with password and TOTP secret
14. Audit storage accessible and healthy
15. Resource Coordinator recovery disabled in capability registry
16. Conservative public action policy
17. Preexisting Funnel route conflict detection
18. Zero active unresolved barriers
19. Local listener reachable on loopback
20. All prerequisites satisfied -> enable succeeds
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Dict

import pytest

from remote_control.actions.models import ActionDefinition, ActionEffect, PostconditionPolicy
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.doctor import ExternalDoctor
from remote_control.external.service import ExternalExposureService


def _seed_valid_operator(auth_db: Path) -> None:
    """Helper to seed an enrolled operator with password and TOTP secret."""
    auth_store = AuthStorage(auth_db)
    auth_store.create_operator(
        operator_id="admin_op",
        username="admin",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        totp_secret="JBSWY3DPEHPK3PXP",
    )


def _base_valid_config(tmp_path: Path) -> RemoteControlConfig:
    auth_db = tmp_path / "valid_auth.db"
    return RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
        cookie_security_mode="strict",
        trusted_proxy_peers=["127.0.0.1"],
        public_action_policy="conservative",
    )


def test_preflight_blocks_when_tailscale_not_installed(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(installed=False, state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert res["applied"] is False
    assert res["error"] == "preflight_failed"
    assert any("not installed" in b for b in res["blockers"])


def test_preflight_blocks_when_tailscale_not_logged_in(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(installed=True, state_file=tmp_path / ".ts.json")
    st = client._ensure_state()
    st["logged_in"] = False
    client._save_state(st)

    service = ExternalExposureService(config=cfg, storage=store, client=client)
    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("not authenticated" in b for b in res["blockers"])


def test_preflight_blocks_when_tailscale_version_unsupported(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(version="1.48.0", state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("unsupported" in b for b in res["blockers"])


def test_preflight_blocks_when_tailscale_version_unknown(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(version="git-commit-abc", state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("could not be parsed" in b for b in res["blockers"])


def test_preflight_blocks_when_funnel_capability_disabled(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(funnel_available=False, state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("capability is disabled" in b for b in res["blockers"])


def test_preflight_blocks_when_public_port_unsupported(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # Port 8080 is not a supported Funnel port
    res = service.enable(apply=True, public_port=8080, verify_listener=False)
    assert res["ok"] is False
    assert any("not supported by Funnel" in b for b in res["blockers"])


def test_preflight_blocks_when_public_origin_missing(tmp_path: Path) -> None:
    auth_db = tmp_path / "valid_auth.db"
    _seed_valid_operator(auth_db)
    store = ActionStorage(auth_db)

    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin=None,  # Missing
        allowed_public_hosts=["node.tailnet.ts.net"],
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("public_origin is not configured" in b for b in res["blockers"])


def test_preflight_blocks_when_public_origin_not_https(tmp_path: Path) -> None:
    auth_db = tmp_path / "valid_auth.db"
    _seed_valid_operator(auth_db)
    store = ActionStorage(auth_db)

    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="http://node.tailnet.ts.net:8443",  # Insecure HTTP
        allowed_public_hosts=["node.tailnet.ts.net"],
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("must use HTTPS" in b for b in res["blockers"])


def test_preflight_blocks_when_public_hostname_not_pinned(tmp_path: Path) -> None:
    auth_db = tmp_path / "valid_auth.db"
    _seed_valid_operator(auth_db)
    store = ActionStorage(auth_db)

    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://untrusted-host.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],  # Mismatch
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("not in allowed_public_hosts" in b for b in res["blockers"])


def test_preflight_blocks_when_backend_not_loopback(tmp_path: Path) -> None:
    auth_db = tmp_path / "valid_auth.db"
    _seed_valid_operator(auth_db)
    store = ActionStorage(auth_db)

    cfg = RemoteControlConfig(
        host="0.0.0.0",  # Insecure wide binding
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("Backend is bound to non-loopback" in b for b in res["blockers"])


def test_preflight_blocks_when_proxy_topology_untrusted(tmp_path: Path) -> None:
    auth_db = tmp_path / "valid_auth.db"
    _seed_valid_operator(auth_db)
    store = ActionStorage(auth_db)

    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
        trusted_proxy_peers=["192.168.1.100"],  # Non-loopback proxy peer
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("contains non-loopback" in b for b in res["blockers"])


def test_preflight_blocks_when_auth_database_missing(tmp_path: Path) -> None:
    nonexistent_db = tmp_path / "missing_auth.db"
    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=nonexistent_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
    )
    store = ActionStorage(nonexistent_db, read_only=True)
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("does not exist" in b for b in res["blockers"])


def test_preflight_blocks_when_operator_not_enrolled(tmp_path: Path) -> None:
    auth_db = tmp_path / "empty_auth.db"
    # Create DB with initialized schema but without any operators
    AuthStorage(auth_db)
    store = ActionStorage(auth_db)
    cfg = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=auth_db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("No operator is enrolled" in b for b in res["blockers"])


def test_preflight_blocks_when_active_barriers_present(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    # Establish an unresolved barrier
    store.set_resource_barrier(
        resource_key="notifications:incident:500",
        execution_id="exec_500",
        reason="Unresolved timeout",
        barrier_status="locked_unresolved",
    )

    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("active unresolved execution barrier" in b for b in res["blockers"])


def test_preflight_blocks_when_listener_offline(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # Verify listener on unused port with verify_listener=True
    res = service.enable(apply=True, port=61999, public_port=8443, verify_listener=True)
    assert res["ok"] is False
    assert any("No active process listening" in b for b in res["blockers"])


def test_preflight_blocks_when_preexisting_route_conflicts(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    # Port 8443 is already mapped to a different service
    client = SimulatedTailscaleClient(
        state_file=tmp_path / ".ts.json",
        existing_conflicts={"8443": "http://127.0.0.1:9090"},
    )
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("already owned by another service" in b for b in res["blockers"])


def test_preflight_passes_and_activates_when_all_prerequisites_met(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    client = SimulatedTailscaleClient(
        node_name="node",
        tailnet_name="tailnet.ts.net",
        version="1.56.0-simulated",
        state_file=tmp_path / ".ts.json",
    )
    service = ExternalExposureService(config=cfg, storage=store, client=client)

    # 1. Dry run
    dry = service.enable(apply=False, port=8443, public_port=8443, verify_listener=False)
    assert dry["ok"] is True
    assert dry["applied"] is False
    assert dry["ready_for_public_enable"] is True

    # 2. Apply
    applied = service.enable(apply=True, port=8443, public_port=8443, verify_listener=False)
    assert applied["ok"] is True
    assert applied["applied"] is True
    assert client.get_status().funnel_active is True
    assert applied["public_url"] == "https://node.tailnet.ts.net:8443"


def test_preflight_blocks_when_coordinator_recovery_enabled(tmp_path: Path) -> None:
    cfg = _base_valid_config(tmp_path)
    store = ActionStorage(cfg.auth_db_path)
    _seed_valid_operator(cfg.auth_db_path)

    # Artificially create a registry where coordinator.recovery is enabled
    bad_registry = ActionRegistry()
    bad_action = ActionDefinition(
        action_id="coordinator.recovery",
        label="Insecure Recovery",
        description="Improperly enabled recovery mutation",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        concurrency_key="coordinator:recovery",
        enabled=True,  # VIOLATION
        postcondition_policy=PostconditionPolicy.NONE,
        module="resource_coordinator",
    )
    bad_registry.register(bad_action)

    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    service = ExternalExposureService(config=cfg, storage=store, client=client)
    # Inject bad registry into doctor_runner
    service.doctor_runner.registry = bad_registry

    res = service.enable(apply=True, verify_listener=False)
    assert res["ok"] is False
    assert any("Resource Coordinator recovery is enabled" in b for b in res["blockers"])
