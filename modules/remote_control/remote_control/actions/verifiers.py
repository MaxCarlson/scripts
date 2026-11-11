"""Authoritative typed barrier verifiers for Stage E.

Reconciliation requires an independent, source-owned typed verifier to establish
the real subsystem postcondition before permitting barrier clearance.
Generic clearance via free-text explanations or unverified -a/--apply is rejected.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

PROTECTED_COORDINATOR_RESOURCES = {
    "coordinator:recovery",
    "coordinator:inhibition",
    "coordinator:reboot",
}


@dataclass
class BarrierVerificationResult:
    """Structured result of an authoritative source verification."""
    verified: bool
    verifier_id: str
    verified_at: str
    error: Optional[str] = None
    message: str = ""
    state_fingerprint: Optional[str] = None
    evidence_details: Dict[str, Any] = field(default_factory=dict)


class BarrierVerifierProtocol(Protocol):
    """Protocol for authoritative source barrier verifiers."""

    def verify(
        self,
        resource_key: str,
        barrier_record: Dict[str, Any],
        evidence_payload: Optional[Dict[str, Any]] = None,
    ) -> BarrierVerificationResult:
        ...


class CoordinatorRecoveryVerifier:
    """Verifier for Resource Coordinator recovery resources.

    Strict invariant: Production Resource Coordinator recovery barriers cannot be cleared
    through the remote control manual override interface. They require approved coordinator contracts.
    """

    def verify(
        self,
        resource_key: str,
        barrier_record: Dict[str, Any],
        evidence_payload: Optional[Dict[str, Any]] = None,
    ) -> BarrierVerificationResult:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return BarrierVerificationResult(
            verified=False,
            verifier_id="coordinator_recovery_verifier",
            verified_at=now_iso,
            error="coordinator_recovery_prohibited",
            message=(
                "Generic manual override of Resource Coordinator recovery is prohibited "
                "without an approved, verified recovery contract."
            ),
        )


class IncidentAcknowledgementVerifier:
    """Authoritative verifier for notification incident acknowledgement barriers.

    Directly queries the notifications SQLite storage engine in read-only mode to
    verify that the target incident actually reached status='acknowledged'.
    """

    def __init__(self, notifications_db_path: Optional[Path] = None) -> None:
        self.db_path = notifications_db_path

    def _get_engine(self) -> Any:
        try:
            from notifications.config import default_db_path
            from notifications.storage import StorageEngine
            db_p = self.db_path or default_db_path()
            return StorageEngine(db_p)
        except Exception as e:
            logger.debug("Failed to initialize notifications StorageEngine: %s", e)
            return None

    def verify(
        self,
        resource_key: str,
        barrier_record: Dict[str, Any],
        evidence_payload: Optional[Dict[str, Any]] = None,
    ) -> BarrierVerificationResult:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Extract incident_id from resource key e.g. "notifications:incident:inc_123"
        parts = resource_key.split(":")
        incident_id = parts[-1] if len(parts) >= 3 else None
        if not incident_id:
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="invalid_resource_key",
                message=f"Cannot extract incident_id from resource key '{resource_key}'.",
            )

        engine = self._get_engine()
        if not engine:
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="source_inaccessible",
                message="Notifications storage engine is unavailable or unconfigured.",
            )

        try:
            incident = engine.get_incident(incident_id)
        except Exception as exc:
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="source_query_failed",
                message=f"Failed to query notifications source: {exc}",
            )

        if not incident:
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="incident_not_found",
                message=f"Incident '{incident_id}' does not exist in notifications database.",
            )

        # Source verification: status must be acknowledged or resolved
        if incident.status not in ("acknowledged", "resolved"):
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="state_mismatch",
                message=f"Incident '{incident_id}' is in state '{incident.status}', not 'acknowledged'.",
                evidence_details={"incident_id": incident.incident_id, "current_status": incident.status},
            )

        # Authoritatively proven: compute deterministic fingerprint
        raw_fingerprint = f"{incident.incident_id}:{incident.status}:{incident.acknowledged_at}:{incident.occurrence_count}"
        fingerprint = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()

        return BarrierVerificationResult(
            verified=True,
            verifier_id="notifications_incident_verifier",
            verified_at=now_iso,
            error=None,
            message=f"Incident '{incident_id}' authoritatively verified as '{incident.status}'.",
            state_fingerprint=fingerprint,
            evidence_details={
                "incident_id": incident.incident_id,
                "status": incident.status,
                "acknowledged_at": incident.acknowledged_at,
                "occurrence_count": incident.occurrence_count,
            },
        )


class DefaultUnsupportedVerifier:
    """Fails closed for any resource without a specialized authoritative verifier."""

    def verify(
        self,
        resource_key: str,
        barrier_record: Dict[str, Any],
        evidence_payload: Optional[Dict[str, Any]] = None,
    ) -> BarrierVerificationResult:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return BarrierVerificationResult(
            verified=False,
            verifier_id="unsupported_resource_verifier",
            verified_at=now_iso,
            error="verification_unavailable",
            message=(
                f"No authoritative source verifier is registered for resource key '{resource_key}'. "
                "Generic barrier clearance is rejected to prevent unverified mutations."
            ),
        )


def get_barrier_verifier(resource_key: str, notifications_db_path: Optional[Path] = None) -> BarrierVerifierProtocol:
    """Return the authoritative typed verifier for a resource key."""
    if (
        resource_key in PROTECTED_COORDINATOR_RESOURCES
        or resource_key.startswith("coordinator:")
        or "gpu.inference" in resource_key
    ):
        return CoordinatorRecoveryVerifier()

    if resource_key.startswith("notifications:incident:"):
        return IncidentAcknowledgementVerifier(notifications_db_path=notifications_db_path)

    return DefaultUnsupportedVerifier()
