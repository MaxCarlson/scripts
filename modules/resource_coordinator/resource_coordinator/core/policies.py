"""
Declarative policy engine binding triggers, conditions, actions, resource leases, and release lifecycles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .actions import Action
from .conditions import Condition
from .events import Event, EventDispatcher, VetoOperation
from .leases import LeaseManager, LeaseType

logger = logging.getLogger(__name__)


@dataclass
class Policy:
    """A coordination policy binding a trigger, condition, actions, and post-release steps."""

    name: str
    trigger_event: str
    condition: Optional[Condition] = None
    actions: List[Action] = field(default_factory=list)
    on_failure: str = "reject_operation"  # reject_operation | continue | log
    resource: Optional[str] = None
    lease_type: LeaseType = LeaseType.SHARED
    cooldown_seconds: Optional[float] = None
    after_release_actions: List[Action] = field(default_factory=list)


class PolicyEngine:
    """
    Evaluates and enforces policies against events, leases, and managed processes.
    """

    def __init__(
        self,
        event_dispatcher: EventDispatcher,
        lease_manager: LeaseManager,
    ) -> None:
        self.dispatcher = event_dispatcher
        self.lease_mgr = lease_manager
        self._policies: Dict[str, Policy] = {}

        # Listen for resource idle events to trigger after_release_actions
        self.dispatcher.on("resource.idle", self._on_resource_idle)

    def register_policy(self, policy: Policy) -> None:
        """Register a policy and bind its trigger listener."""
        self._policies[policy.name] = policy

        if policy.resource and policy.cooldown_seconds is not None:
            self.lease_mgr.set_resource_cooldown(policy.resource, policy.cooldown_seconds)

        # Register trigger handler
        async def _trigger_handler(event: Event) -> None:
            await self._handle_trigger(policy, event)

        # If on_failure == "reject_operation", register as blocking hook
        is_blocking = policy.on_failure == "reject_operation"
        self.dispatcher.on(policy.trigger_event, _trigger_handler, is_blocking=is_blocking)
        logger.info(
            "Registered policy '%s' on trigger '%s' (blocking=%s)", policy.name, policy.trigger_event, is_blocking
        )

    async def _handle_trigger(self, policy: Policy, event: Event) -> None:
        """Evaluate conditions and execute actions for a triggered policy."""
        context = dict(event.data)
        context["event_id"] = event.event_id
        context["policy_name"] = policy.name

        if policy.condition is not None:
            matches = await policy.condition.evaluate(context)
            if not matches:
                logger.debug("Policy '%s' condition did not match event '%s'", policy.name, event.name)
                return

        logger.info("Executing actions for policy '%s' triggered by '%s'", policy.name, event.name)
        for action in policy.actions:
            result = await action.execute(context)
            if not result.is_ok:
                logger.error("Action in policy '%s' failed: %s", policy.name, result.message)
                if policy.on_failure == "reject_operation":
                    raise VetoOperation(
                        message=f"Policy '{policy.name}' action failed: {result.message}",
                        reason=result,
                    )

    async def _on_resource_idle(self, event: Event) -> None:
        """Trigger after_release_actions when a resource becomes idle."""
        resource = event.data.get("resource")
        if not resource:
            return

        for policy in self._policies.values():
            if policy.resource == resource and policy.after_release_actions:
                logger.info(
                    "Executing after-release actions for policy '%s' on idle resource '%s'", policy.name, resource
                )
                for action in policy.after_release_actions:
                    res = await action.execute(event.data)
                    if not res.is_ok:
                        logger.warning("After-release action in policy '%s' failed: %s", policy.name, res.message)
