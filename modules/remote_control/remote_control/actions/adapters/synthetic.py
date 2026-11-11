"""Deterministic synthetic Resource Coordinator recovery adapter for negative and safety testing."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SyntheticCoordinatorRecoveryAdapter:
    """Configurable fake Resource Coordinator recovery backend.

    Used exclusively in automated tests to exercise the complete prepare/confirm/execute
    guarded workflow, timeout handling, and safety refusals without calling the live
    Resource Coordinator or executing external processes.
    """

    def __init__(
        self,
        *,
        service_ready: bool = True,
        source_available: bool = True,
        recovery_required: bool = True,
        active_claims: int = 0,
        pending_claims: int = 0,
        inhibition_active: bool = True,
        inhibition_holder: str = "gpu.inference",
        request_id: str = "req-synth-1",
        simulate_timeout: bool = False,
        simulate_safety_refusal: bool = False,
        simulate_postcondition_failure: bool = False,
        transition_on_success: bool = True,
    ) -> None:
        self.service_ready = service_ready
        self.source_available = source_available
        self.recovery_required = recovery_required
        self.active_claims = active_claims
        self.pending_claims = pending_claims
        self.inhibition_active = inhibition_active
        self.inhibition_holder = inhibition_holder
        self.request_id = request_id
        self.simulate_timeout = simulate_timeout
        self.simulate_safety_refusal = simulate_safety_refusal
        self.simulate_postcondition_failure = simulate_postcondition_failure
        self.transition_on_success = transition_on_success

        self.execution_count = 0
        self.last_params: Optional[Dict[str, Any]] = None

    def get_source_state(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return the current simulated Resource Coordinator observation."""
        if not self.source_available:
            return {
                "status": "unavailable",
                "contract_version": "v1",
                "recovery_required": None,
                "inhibition_active": None,
                "error_message": "Synthetic service offline",
            }

        return {
            "status": "ready" if self.service_ready else "degraded",
            "contract_version": "v1",
            "recovery_required": self.recovery_required,
            "inhibition_active": self.inhibition_active,
            "inhibition_reason": f"Synthetic holder {self.inhibition_holder}",
            "active_claims": self.active_claims,
            "pending_claims": self.pending_claims,
            "active_request_id": self.request_id,
            "journal_status": "synced",
            "observed_at": "2026-11-11T12:00:00Z",
        }

    async def execute(self, params: Dict[str, Any], actor_id: str = "operator", **kwargs: Any) -> Dict[str, Any]:
        """Simulate guarded recovery execution."""
        self.execution_count += 1
        self.last_params = params

        # 1. Source availability check
        if not self.source_available:
            return {
                "ok": False,
                "error": "source_unavailable",
                "message": "Resource Coordinator is currently offline.",
                "simulated": True,
            }

        # 2. Service readiness check
        if not self.service_ready:
            return {
                "ok": False,
                "error": "service_not_ready",
                "message": "Resource Coordinator is not in a ready state.",
                "simulated": True,
            }

        # 3. Active claims / unsafe arbitration
        if self.active_claims > 0 or self.pending_claims > 0:
            return {
                "ok": False,
                "error": "safety_refusal",
                "message": f"Cannot recover: {self.active_claims} active claims and {self.pending_claims} pending claims.",
                "simulated": True,
            }

        # 4. Simulated safety refusal
        if self.simulate_safety_refusal:
            return {
                "ok": False,
                "error": "safety_refusal",
                "message": "Resource Coordinator refused recovery: upstream inference active.",
                "simulated": True,
            }

        # 5. Simulated timeout
        if self.simulate_timeout:
            await asyncio.sleep(0.5)
            raise asyncio.TimeoutError("Synthetic execution timed out waiting for Coordinator response.")

        # 6. Success path
        if self.transition_on_success:
            if not self.simulate_postcondition_failure:
                self.recovery_required = False
                self.inhibition_active = False
                self.request_id = "req-synth-cleared"

        return {
            "ok": True,
            "resource": params.get("resource", "gpu.inference"),
            "recovered": True,
            "simulated": True,
            "new_state": self.get_source_state(),
        }

    def verify_postcondition(self, params: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """Verify postcondition for synthetic recovery."""
        if not result.get("ok"):
            return False
        if self.simulate_postcondition_failure:
            return False
        return (not self.recovery_required) and (not self.inhibition_active)
