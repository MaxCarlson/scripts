"""Static, code-owned registry for remote control capabilities."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from remote_control.actions.models import (
    AcknowledgeIncidentParameters,
    ActionDefinition,
    ActionEffect,
    ConfirmationPolicy,
    EmptyParameters,
    GuardedRecoveryParameters,
    PostconditionPolicy,
    StepUpPolicy,
)

logger = logging.getLogger(__name__)


class ActionRegistry:
    """Immutable, code-owned registry of authorized capabilities.

    Invariants:
    - Capabilities must be declared in source code.
    - Registry is frozen once initialized; dynamic browser submission of action definitions is forbidden.
    - Unknown capabilities are rejected.
    - Production disabled capabilities fail closed.
    """

    def __init__(self) -> None:
        self._actions: Dict[str, ActionDefinition] = {}
        self._handlers: Dict[str, Any] = {}
        self._frozen: bool = False
        self._register_default_capabilities()

    def _register_default_capabilities(self) -> None:
        # 1. resource_coordinator.status (Read)
        self.register(
            ActionDefinition(
                action_id="resource_coordinator.status",
                version="1.0.0",
                label="Resource Coordinator Status",
                description="Fetch current operational status and observation of Resource Coordinator.",
                module="resource_coordinator",
                effect=ActionEffect.READ,
                required_permission="operator.read",
                parameter_model=EmptyParameters,
                timeout_seconds=5.0,
                concurrency_key="resource_coordinator:read",
                confirmation_policy=ConfirmationPolicy.NONE,
                step_up_policy=StepUpPolicy.NONE,
                enabled=True,
            )
        )

        # 2. resource_coordinator.inspect_recovery (Read)
        self.register(
            ActionDefinition(
                action_id="resource_coordinator.inspect_recovery",
                version="1.0.0",
                label="Inspect Recovery Condition",
                description="Inspect detailed safety hold, recovery contract, and inhibition status.",
                module="resource_coordinator",
                effect=ActionEffect.READ,
                required_permission="operator.read",
                parameter_model=EmptyParameters,
                timeout_seconds=5.0,
                concurrency_key="resource_coordinator:read",
                confirmation_policy=ConfirmationPolicy.NONE,
                step_up_policy=StepUpPolicy.NONE,
                enabled=True,
            )
        )

        # 3. notifications.health (Read)
        self.register(
            ActionDefinition(
                action_id="notifications.health",
                version="1.0.0",
                label="Notifications System Health",
                description="Inspect notifications broker, outbox queue, and storage health.",
                module="notifications",
                effect=ActionEffect.READ,
                required_permission="operator.read",
                parameter_model=EmptyParameters,
                timeout_seconds=5.0,
                concurrency_key="notifications:read",
                confirmation_policy=ConfirmationPolicy.NONE,
                step_up_policy=StepUpPolicy.NONE,
                enabled=True,
            )
        )

        # 4. notifications.incident_detail (Read)
        self.register(
            ActionDefinition(
                action_id="notifications.incident_detail",
                version="1.0.0",
                label="Incident Detail",
                description="Inspect full event history and lifecycle transitions for an incident.",
                module="notifications",
                effect=ActionEffect.READ,
                required_permission="operator.read",
                parameter_model=AcknowledgeIncidentParameters,
                timeout_seconds=5.0,
                concurrency_key="notifications:read",
                confirmation_policy=ConfirmationPolicy.NONE,
                step_up_policy=StepUpPolicy.NONE,
                enabled=True,
            )
        )

        # 5. notifications.acknowledge_incident (Mutation)
        self.register(
            ActionDefinition(
                action_id="notifications.acknowledge_incident",
                version="1.0.0",
                label="Acknowledge Incident",
                description="Acknowledge an active notification incident in the notification broker.",
                module="notifications",
                effect=ActionEffect.MUTATION,
                required_permission="operator.action",
                parameter_model=AcknowledgeIncidentParameters,
                timeout_seconds=10.0,
                concurrency_key="notifications:incident",
                idempotency_scope="incident:ack",
                confirmation_policy=ConfirmationPolicy.EXPLICIT_CHALLENGE,
                step_up_policy=StepUpPolicy.TOTP,
                postcondition_policy=PostconditionPolicy.VERIFY_SOURCE_STATE,
                enabled=True,
            )
        )

        # 6. resource_coordinator.request_guarded_recovery (Mutation - DISABLED IN PRODUCTION)
        self.register(
            ActionDefinition(
                action_id="resource_coordinator.request_guarded_recovery",
                version="1.0.0",
                label="Request Guarded Coordinator Recovery",
                description="Request guarded recovery of an inhibited Resource Coordinator GPU resource.",
                module="resource_coordinator",
                effect=ActionEffect.MUTATION,
                required_permission="operator.action",
                parameter_model=GuardedRecoveryParameters,
                timeout_seconds=15.0,
                concurrency_key="resource:gpu.inference",
                idempotency_scope="resource:recovery",
                confirmation_policy=ConfirmationPolicy.EXPLICIT_CHALLENGE,
                step_up_policy=StepUpPolicy.TOTP,
                postcondition_policy=PostconditionPolicy.VERIFY_SOURCE_STATE,
                enabled=False,  # Enforced server-side disabled state in production!
                disabled_reason="Coordinator recovery requires a separately approved safety contract.",
            )
        )

    def register(self, definition: ActionDefinition, handler: Optional[Any] = None) -> None:
        """Register a capability definition. Only permitted during setup before freezing."""
        if self._frozen:
            raise RuntimeError("ActionRegistry is frozen; dynamic capability registration is forbidden.")
        self._actions[definition.action_id] = definition
        if handler is not None:
            self._handlers[definition.action_id] = handler

    def bind_handler(self, action_id: str, handler: Any) -> None:
        """Bind an adapter handler to an action definition."""
        if self._frozen:
            raise RuntimeError("ActionRegistry is frozen; handler binding is forbidden during execution.")
        if action_id not in self._actions:
            raise KeyError(f"Cannot bind handler: unknown action '{action_id}'.")
        self._handlers[action_id] = handler

    def freeze(self) -> None:
        """Freeze the registry against further modification."""
        self._frozen = True

    def get(self, action_id: str) -> Optional[ActionDefinition]:
        """Look up an action definition by ID."""
        return self._actions.get(action_id)

    def get_handler(self, action_id: str) -> Optional[Any]:
        """Look up the adapter handler for an action ID."""
        return self._handlers.get(action_id)

    def list_actions(self) -> List[ActionDefinition]:
        """List all registered capabilities."""
        return list(self._actions.values())

    def list_public_capabilities(self) -> List[Dict[str, Any]]:
        """List public capability descriptions suitable for browser display."""
        return [action.to_public_dict() for action in self._actions.values()]
