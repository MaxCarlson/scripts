"""Resource Coordinator action adapters (read-only and disabled production recovery)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RCStatusAdapter:
    """Read adapter for resource_coordinator.status."""

    def __init__(self, coordinator_adapter: Any) -> None:
        self.coordinator_adapter = coordinator_adapter

    def get_source_state(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        status = self.coordinator_adapter.get_coordinator_status()
        return status.get("observation") or {}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch sanitized observation of Resource Coordinator."""
        status = self.coordinator_adapter.get_coordinator_status()
        return {
            "ok": True,
            "coordinator": status,
        }


class RCInspectRecoveryAdapter:
    """Read adapter for resource_coordinator.inspect_recovery."""

    def __init__(self, coordinator_adapter: Any) -> None:
        self.coordinator_adapter = coordinator_adapter

    def get_source_state(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        status = self.coordinator_adapter.get_coordinator_status()
        return status.get("observation") or {}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect detailed recovery conditions and inhibition state."""
        status = self.coordinator_adapter.get_coordinator_status()
        obs = status.get("observation") or {}

        return {
            "ok": True,
            "monitored": status.get("monitored", False),
            "service_status": status.get("status", "unknown"),
            "contract_version": obs.get("contract_version", "unknown"),
            "recovery_required": obs.get("recovery_required"),
            "inhibition_active": obs.get("inhibition_active"),
            "inhibition_reason": obs.get("inhibition_reason"),
            "journal_status": obs.get("journal_status"),
            "observed_at": obs.get("observed_at"),
            "authoritative_recovery_contract_present": False,
            "missing_contract_reason": "Coordinator lacks authoritative upstream idle verification; recovery requires interactive operator override.",
        }


class DisabledRecoveryAdapter:
    """Production recovery adapter that strictly fails closed.

    Enforces that production Resource Coordinator recovery is disabled until
    the RC planning owner approves an appropriate recovery contract.
    """

    def get_source_state(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"status": "disabled", "recovery_required": None, "inhibition_active": None}

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.warning("Rejected attempt to execute production Resource Coordinator recovery: capability disabled.")
        return {
            "ok": False,
            "error": "capability_disabled",
            "reason": "Coordinator recovery requires a separately approved safety contract",
            "contract_gap": "Live POST /_coordinator/recover requires 'override: true' without upstream verification.",
        }
