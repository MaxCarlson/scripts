"""Tests for Stage A: Typed, static capability registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from remote_control.actions.models import (
    AcknowledgeIncidentParameters,
    ActionDefinition,
    ActionEffect,
    ConfirmationPolicy,
    EmptyParameters,
    GuardedRecoveryParameters,
    StepUpPolicy,
)
from remote_control.actions.permissions import has_permission
from remote_control.actions.registry import ActionRegistry


def test_registry_initial_capabilities() -> None:
    """Registry initializes with all expected capabilities and exact effects."""
    registry = ActionRegistry()
    actions = {a.action_id: a for a in registry.list_actions()}

    expected_ids = {
        "resource_coordinator.status",
        "resource_coordinator.inspect_recovery",
        "notifications.health",
        "notifications.incident_detail",
        "notifications.acknowledge_incident",
        "resource_coordinator.request_guarded_recovery",
    }
    assert set(actions.keys()) == expected_ids

    # Read capabilities
    assert actions["resource_coordinator.status"].effect == ActionEffect.READ
    assert actions["resource_coordinator.status"].enabled is True

    assert actions["resource_coordinator.inspect_recovery"].effect == ActionEffect.READ
    assert actions["resource_coordinator.inspect_recovery"].enabled is True

    assert actions["notifications.health"].effect == ActionEffect.READ
    assert actions["notifications.health"].enabled is True

    assert actions["notifications.incident_detail"].effect == ActionEffect.READ
    assert actions["notifications.incident_detail"].enabled is True

    # Mutation capabilities
    assert actions["notifications.acknowledge_incident"].effect == ActionEffect.MUTATION
    assert actions["notifications.acknowledge_incident"].enabled is True
    assert actions["notifications.acknowledge_incident"].confirmation_policy == ConfirmationPolicy.EXPLICIT_CHALLENGE
    assert actions["notifications.acknowledge_incident"].step_up_policy == StepUpPolicy.TOTP

    # Production disabled recovery capability
    rec = actions["resource_coordinator.request_guarded_recovery"]
    assert rec.effect == ActionEffect.MUTATION
    assert rec.enabled is False  # Enforced disabled in production!
    assert "separately approved safety contract" in rec.disabled_reason


def test_registry_rejection_of_unknown_and_disabled() -> None:
    """Registry returns None for unknown capabilities; public dict exposes disabled reason."""
    registry = ActionRegistry()

    assert registry.get("unknown.action") is None
    assert registry.get("runmux.terminal") is None
    assert registry.get("shell.exec") is None

    rec = registry.get("resource_coordinator.request_guarded_recovery")
    assert rec is not None
    assert rec.enabled is False

    pub = rec.to_public_dict()
    assert pub["enabled"] is False
    assert pub["disabled_reason"] is not None


def test_registry_freeze_immutability() -> None:
    """Registry cannot be extended or bound with handlers after freezing."""
    registry = ActionRegistry()
    registry.freeze()

    new_act = ActionDefinition(
        action_id="custom.action",
        label="Custom",
        description="Custom action",
        module="custom",
        effect=ActionEffect.READ,
        concurrency_key="custom:read",
    )

    with pytest.raises(RuntimeError, match="ActionRegistry is frozen"):
        registry.register(new_act)

    with pytest.raises(RuntimeError, match="ActionRegistry is frozen"):
        registry.bind_handler("resource_coordinator.status", lambda: None)


def test_parameter_schema_rejects_extra_fields() -> None:
    """Parameter schemas strictly reject extra or unexpected fields."""
    # EmptyParameters
    with pytest.raises(ValidationError):
        EmptyParameters(extra_field="malicious")

    # AcknowledgeIncidentParameters
    valid_ack = AcknowledgeIncidentParameters(incident_id="inc-123", reason="Reviewed")
    assert valid_ack.incident_id == "inc-123"

    with pytest.raises(ValidationError):
        AcknowledgeIncidentParameters(incident_id="inc-123", extra_field="forbidden")

    # GuardedRecoveryParameters
    valid_rec = GuardedRecoveryParameters(resource="gpu.inference", reason="Clear hold")
    assert valid_rec.resource == "gpu.inference"

    with pytest.raises(ValidationError):
        GuardedRecoveryParameters(resource="gpu.inference", reason="Clear hold", force=True)  # force is forbidden!


def test_permissions_enforcement() -> None:
    """Permissions are checked against user roles."""
    assert has_permission("operator", "operator.read") is True
    assert has_permission("operator", "operator.action") is True
    assert has_permission("operator", "operator.admin") is False

    assert has_permission("admin", "operator.read") is True
    assert has_permission("admin", "operator.action") is True
    assert has_permission("admin", "operator.admin") is True

    assert has_permission("guest", "operator.read") is False
    assert has_permission("guest", "operator.action") is False
