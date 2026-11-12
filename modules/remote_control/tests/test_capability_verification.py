"""Targeted tests for Section 3: Critical capability verification.

Invariants:
1. Query exact registered capability 'resource_coordinator.request_guarded_recovery'.
2. Require enabled=False.
3. Verify bound handler is DisabledRecoveryAdapter.
4. Never infer safe state from an absent capability (missing capability must block).
5. Check all registered capabilities against allowlist (unexpected actions or mutating capabilities must block).
6. Enforce public_action_policy == 'conservative'.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from remote_control.actions.adapters.coordinator import DisabledRecoveryAdapter
from remote_control.actions.models import (
    ActionDefinition,
    ActionEffect,
    EmptyParameters,
    PostconditionPolicy,
)
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import SimulatedTailscaleClient
from remote_control.external.doctor import ExternalDoctor


def _create_doctor(tmp_path: Path, registry: ActionRegistry, policy: str = "conservative") -> ExternalDoctor:
    db = tmp_path / "test.db"
    auth_store = AuthStorage(db)
    auth_store.create_operator("op1", "admin", "hash", "TOTP")
    action_store = ActionStorage(db)
    cfg = RemoteControlConfig(
        auth_db_path=db,
        public_origin="https://node.tailnet.ts.net:8443",
        allowed_public_hosts=["node.tailnet.ts.net"],
        cookie_security_mode="strict",
        external_exposure_enabled=True,
        public_action_policy=policy,
    )
    client = SimulatedTailscaleClient(state_file=tmp_path / ".ts.json")
    return ExternalDoctor(config=cfg, storage=action_store, client=client, registry=registry)


def test_standard_disabled_recovery_passes(tmp_path: Path) -> None:
    """Standard registry with disabled RC recovery and DisabledRecoveryAdapter passes."""
    registry = ActionRegistry()
    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    assert all(c.severity == "pass" for c in checks)
    coord_check = next(c for c in checks if c.name == "coordinator_recovery_disabled")
    assert coord_check.severity == "pass"
    assert "DisabledRecoveryAdapter" in coord_check.message


def test_enabled_recovery_blocks(tmp_path: Path) -> None:
    """Enabling resource_coordinator.request_guarded_recovery must strictly fail preflight."""
    registry = ActionRegistry()
    registry._frozen = False
    defn = registry.get("resource_coordinator.request_guarded_recovery")
    assert defn is not None
    # Re-register with enabled=True
    registry._actions["resource_coordinator.request_guarded_recovery"] = ActionDefinition(
        action_id=defn.action_id,
        version=defn.version,
        label=defn.label,
        description=defn.description,
        module=defn.module,
        effect=defn.effect,
        required_permission=defn.required_permission,
        parameter_model=defn.parameter_model,
        concurrency_key=defn.concurrency_key,
        enabled=True,  # VIOLATION
    )
    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    coord_check = next(c for c in checks if c.name == "coordinator_recovery_disabled")
    assert coord_check.severity == "blocker"
    assert "must remain disabled" in coord_check.message


def test_missing_recovery_definition_blocks(tmp_path: Path) -> None:
    """Never infer safe state from an absent capability: missing definition must block."""
    registry = ActionRegistry()
    registry._frozen = False
    del registry._actions["resource_coordinator.request_guarded_recovery"]

    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    coord_check = next(c for c in checks if c.name == "coordinator_recovery_disabled")
    assert coord_check.severity == "blocker"
    assert "not registered" in coord_check.message


def test_non_disabled_recovery_adapter_blocks(tmp_path: Path) -> None:
    """Binding any handler other than DisabledRecoveryAdapter must block."""
    registry = ActionRegistry()
    registry._frozen = False
    # Bind an arbitrary dummy handler
    class MockCustomAdapter:
        pass

    registry._handlers["resource_coordinator.request_guarded_recovery"] = MockCustomAdapter()

    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    coord_check = next(c for c in checks if c.name == "coordinator_recovery_disabled")
    assert coord_check.severity == "blocker"
    assert "expected DisabledRecoveryAdapter" in coord_check.message


def test_missing_handler_blocks(tmp_path: Path) -> None:
    """A None handler for recovery capability must block."""
    registry = ActionRegistry()
    registry._frozen = False
    registry._handlers["resource_coordinator.request_guarded_recovery"] = None

    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    coord_check = next(c for c in checks if c.name == "coordinator_recovery_disabled")
    assert coord_check.severity == "blocker"
    assert "expected DisabledRecoveryAdapter" in coord_check.message


def test_unexpected_action_id_blocks(tmp_path: Path) -> None:
    """Any registered action outside the authorized allowlist must block."""
    registry = ActionRegistry()
    registry._frozen = False
    registry._actions["system.arbitrary_command"] = ActionDefinition(
        action_id="system.arbitrary_command",
        label="Arbitrary Command",
        description="Not on allowlist",
        module="system",
        effect=ActionEffect.READ,
        required_permission="operator.read",
        parameter_model=EmptyParameters,
        concurrency_key="system:cmd",
        enabled=True,
    )

    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    allowlist_check = next(c for c in checks if c.name == "capabilities_allowlist")
    assert allowlist_check.severity == "blocker"
    assert "Unknown/unauthorized capabilities" in allowlist_check.message


def test_unexpected_mutating_capability_blocks(tmp_path: Path) -> None:
    """Any enabled mutating action other than notifications.acknowledge_incident must block."""
    registry = ActionRegistry()
    registry._frozen = False
    # Suppose a new action is in allowlist, but is an enabled mutation
    # We test with another mutating action
    registry._actions["unauthorized.mutation"] = ActionDefinition(
        action_id="unauthorized.mutation",
        label="Unauthorized Mutation",
        description="Mutating capability not allowed to be enabled",
        module="custom",
        effect=ActionEffect.MUTATION,
        required_permission="operator.action",
        parameter_model=EmptyParameters,
        concurrency_key="custom:mutation",
        enabled=True,
    )

    doctor = _create_doctor(tmp_path, registry)
    checks = doctor.check_capabilities_and_policy()
    allowlist_check = next(c for c in checks if c.name == "capabilities_allowlist")
    assert allowlist_check.severity == "blocker"


def test_permissive_public_action_policy_blocks(tmp_path: Path) -> None:
    """Public action policy other than 'conservative' must block."""
    registry = ActionRegistry()
    doctor = _create_doctor(tmp_path, registry, policy="permissive")
    checks = doctor.check_capabilities_and_policy()
    policy_check = next(c for c in checks if c.name == "public_action_policy")
    assert policy_check.severity == "blocker"
    assert "Only 'conservative' is authorized" in policy_check.message
