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

    Strict Invariants:
    - Verifies postcondition for the EXACT execution and occurrence.
    - An incident in status='resolved' without explicit acknowledgement for this occurrence is rejected.
    - A subsequent/reopened occurrence cannot clear an unresolved barrier from an earlier occurrence.
    """

    def __init__(self, notifications_db_path: Optional[Path] = None, action_storage: Optional[Any] = None) -> None:
        self.db_path = notifications_db_path
        self.action_storage = action_storage

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
        if not incident_id or resource_key == "notifications:incident":
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="invalid_resource_key",
                message=f"Cannot extract incident_id from resource key '{resource_key}'. Exact per-incident serialization is required.",
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

        # Source verification: status must be explicitly 'acknowledged'.
        # Do not clear a barrier simply because the current incident status happens to be 'resolved'.
        if incident.status != "acknowledged":
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="state_mismatch",
                message=(
                    f"Incident '{incident_id}' is in state '{incident.status}', not 'acknowledged'. "
                    "Barriers cannot be cleared simply because status is resolved or firing."
                ),
                evidence_details={"incident_id": incident.incident_id, "current_status": incident.status},
            )

        # Retrieve original execution journal record if available
        exec_id = barrier_record.get("execution_id")
        exec_record = None
        if self.action_storage and exec_id:
            try:
                exec_record = self.action_storage.get_execution(exec_id)
            except Exception:
                pass

        # Check for occurrence mismatch or reopening
        evidence_dict = evidence_payload or {}
        expected_occ = evidence_dict.get("expected_occurrence")
        if expected_occ is not None and incident.occurrence_count != int(expected_occ):
            return BarrierVerificationResult(
                verified=False,
                verifier_id="notifications_incident_verifier",
                verified_at=now_iso,
                error="occurrence_mismatch",
                message=(
                    f"Incident reopened: current occurrence count is {incident.occurrence_count}, "
                    f"expected {expected_occ}. An acknowledgement of a different occurrence cannot clear this barrier."
                ),
                evidence_details={"incident_id": incident.incident_id, "current_occurrence": incident.occurrence_count, "expected_occurrence": expected_occ},
            )

        if exec_record and exec_record.started_at and incident.acknowledged_at:
            if incident.acknowledged_at < exec_record.started_at:
                return BarrierVerificationResult(
                    verified=False,
                    verifier_id="notifications_incident_verifier",
                    verified_at=now_iso,
                    error="state_mismatch",
                    message=(
                        f"Incident acknowledgement timestamp ({incident.acknowledged_at}) predates execution dispatch ({exec_record.started_at}). "
                        "A prior acknowledgement cannot clear this barrier."
                    ),
                    evidence_details={"acknowledged_at": incident.acknowledged_at, "dispatch_started_at": exec_record.started_at},
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


def get_barrier_verifier(
    resource_key: str,
    notifications_db_path: Optional[Path] = None,
    action_storage: Optional[Any] = None,
) -> BarrierVerifierProtocol:
    """Return the authoritative typed verifier for a resource key."""
    if (
        resource_key in PROTECTED_COORDINATOR_RESOURCES
        or resource_key.startswith("coordinator:")
        or resource_key.startswith("resource_coordinator:")
        or "gpu.inference" in resource_key
        or "coordinator" in resource_key
    ):
        return CoordinatorRecoveryVerifier()

    if resource_key.startswith("notifications:incident:"):
        return IncidentAcknowledgementVerifier(notifications_db_path=notifications_db_path, action_storage=action_storage)

    return DefaultUnsupportedVerifier()
