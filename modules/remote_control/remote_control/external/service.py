"""External exposure lifecycle management service and barrier reconciliation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from remote_control.actions.storage import ActionStorage
from remote_control.actions.verifiers import (
    BarrierVerificationResult,
    get_barrier_verifier,
)
from remote_control.config import RemoteControlConfig
from remote_control.external.client import TailscaleClientProtocol, get_tailscale_client
from remote_control.external.doctor import ExternalDoctor

logger = logging.getLogger(__name__)

# Resource keys protected from generic manual reconciliation override
PROTECTED_COORDINATOR_RESOURCES = {
    "coordinator:recovery",
    "resource:gpu.inference",
    "resource_coordinator:recovery",
}


class ExternalExposureService:
    """Manages Tailscale Funnel lifecycle, dry-run planning, and barrier reconciliation."""

    def __init__(
        self,
        config: RemoteControlConfig,
        storage: ActionStorage,
        client: Optional[TailscaleClientProtocol] = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.client = client or get_tailscale_client()
        self.doctor_runner = ExternalDoctor(self.config, self.storage, self.client)

    def status(self) -> Dict[str, Any]:
        """Read-only operational status of external exposure and tunnel reachability."""
        st = self.client.get_status()
        barriers = self.storage.list_active_barriers()
        return {
            "ok": True,
            "read_only": True,
            "tailscale": st.to_dict(),
            "exposure": {
                "enabled": self.config.external_exposure_enabled,
                "public_origin": self.config.public_origin,
                "allowed_public_hosts": self.config.allowed_public_hosts,
                "cookie_security_mode": self.config.cookie_security_mode,
                "public_action_policy": self.config.public_action_policy,
            },
            "barriers": {
                "active_count": len(barriers),
                "items": barriers,
            },
        }

    def doctor(self) -> Dict[str, Any]:
        """Run read-only preflight health checks."""
        return self.doctor_runner.check_all()

    def plan(self, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        """Display proposed Funnel and Serve commands without mutating state."""
        commands = self.client.plan_funnel(port=port, public_port=public_port)
        st = self.client.get_status()
        return {
            "ok": True,
            "applied": False,
            "local_port": port,
            "public_port": public_port,
            "commands": commands,
            "topology": {
                "ingress": f"Public Internet -> Tailscale Funnel (:{public_port})",
                "proxy_target": f"Loopback 127.0.0.1:{port}",
                "node": st.node_name,
                "tailnet": st.tailnet_name,
            },
            "warnings": [
                "Tailscale Funnel exposes port to public internet.",
                "Ensure strong password and TOTP two-factor authentication are enrolled.",
                "Never expose Runmux, Resource Coordinator port 1235, or Windows credentials.",
            ],
        }

    def enable(
        self,
        apply: bool = False,
        port: int = 8443,
        public_port: int = 8443,
        verify_listener: bool = True,
    ) -> Dict[str, Any]:
        """Configure and enable Tailscale Funnel with fail-closed preflight (Stage A)."""
        # Run complete preflight checks
        doc = self.doctor_runner.check_all(
            target_port=port,
            public_port=public_port,
            verify_listener=verify_listener,
        )

        if not doc.get("ready_for_public_enable", False):
            blockers = doc.get("blockers", [])
            unknowns = doc.get("security_unknowns", [])
            issues = [b["message"] for b in blockers] + [u["message"] for u in unknowns]
            return {
                "ok": False,
                "applied": False,
                "error": "preflight_failed",
                "ready_for_public_enable": False,
                "blockers": issues,
                "message": (
                    f"Public exposure preflight failed with {len(issues)} blocking security requirement(s). "
                    "Enablement aborted before executing any Tailscale mutation."
                ),
                "diagnostics": doc,
            }

        if not apply:
            plan_res = self.plan(port=port, public_port=public_port)
            plan_res["ready_for_public_enable"] = True
            plan_res["message"] = "Preflight passed. Dry-run only. Re-run with -a / --apply to execute."
            return plan_res

        return self.client.enable_funnel(port=port, public_port=public_port)

    def disable(self, apply: bool = False, public_port: int = 8443) -> Dict[str, Any]:
        """Stop and disable Tailscale Funnel reachability. Requires apply=True for execution.

        Invariant: Disabling operates independently of application preflight (emergency shutdown).
        """
        if not apply:
            return {
                "ok": True,
                "applied": False,
                "commands": [
                    f"tailscale funnel --https={public_port} off",
                ],
                "message": "Dry-run only. Re-run with -a / --apply to execute.",
            }

        return self.client.disable_funnel(public_port=public_port)

    def repair(
        self,
        apply: bool = False,
        port: int = 8443,
        public_port: int = 8443,
        verify_listener: bool = True,
    ) -> Dict[str, Any]:
        """Re-align Funnel configuration with preflight checks and rollback safeguards."""
        if not apply:
            return {
                "ok": True,
                "applied": False,
                "message": "Dry-run repair plan. Re-run with -a / --apply to execute.",
            }

        # Check preflight first before altering configuration
        doc = self.doctor_runner.check_all(target_port=port, public_port=public_port, verify_listener=verify_listener)
        if not doc.get("ready_for_public_enable", False):
            return {
                "ok": False,
                "applied": False,
                "error": "preflight_failed",
                "message": "Repair aborted because preflight checks failed.",
                "blockers": [b["message"] for b in doc.get("blockers", [])],
            }

        dis_res = self.client.disable_funnel(public_port=public_port)
        if not dis_res.get("ok", True):
            return {
                "ok": False,
                "applied": False,
                "error": "repair_disable_failed",
                "message": f"Repair failed while disabling old exposure: {dis_res.get('error')}",
            }
        return self.client.enable_funnel(port=port, public_port=public_port)

    def reconcile_barrier(
        self,
        resource_key: str,
        evidence: Optional[str] = None,
        apply: bool = False,
        operator_id: str = "operator",
        notifications_db_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Authoritatively reconcile an active unresolved barrier with typed source verification (Stage E).

        Requirements:
        - Fails closed if no active barrier exists.
        - Obtains the source-owned typed verifier for the resource key.
        - Rejects generic/free-text overrides without independent source state proof.
        - Fails closed with 'coordinator_recovery_prohibited' for Resource Coordinator recovery.
        - Requires -a/--apply to mutate state.
        - Atomically binds clearance to barrier execution_id.
        - Records comprehensive audit record with verifier ID and state fingerprint.
        """
        active = self.storage.get_active_barrier(resource_key)
        if not active:
            return {
                "ok": False,
                "applied": False,
                "error": "barrier_not_found",
                "resource_key": resource_key,
                "message": f"No active barrier found for resource key '{resource_key}'.",
            }

        # Obtain typed source verifier
        verifier = get_barrier_verifier(resource_key, notifications_db_path=notifications_db_path)
        verification: BarrierVerificationResult = verifier.verify(
            resource_key=resource_key,
            barrier_record=active,
            evidence_payload={"operator_evidence": evidence},
        )

        if not verification.verified:
            return {
                "ok": False,
                "applied": False,
                "error": verification.error or "verification_failed",
                "verifier_id": verification.verifier_id,
                "resource_key": resource_key,
                "message": verification.message,
                "details": verification.evidence_details,
            }

        # Verification succeeded!
        if not apply:
            return {
                "ok": True,
                "applied": False,
                "verified": True,
                "verifier_id": verification.verifier_id,
                "state_fingerprint": verification.state_fingerprint,
                "resource_key": resource_key,
                "active_barrier": active,
                "message": (
                    f"Dry-run only. Source state authoritatively verified by {verification.verifier_id} "
                    f"(fingerprint: {verification.state_fingerprint[:12] if verification.state_fingerprint else 'none'}). "
                    "Re-run with -a / --apply to clear barrier."
                ),
            }

        # Atomically clear barrier bound to current barrier execution_id
        cleared_evidence_str = json.dumps({
            "verifier_id": verification.verifier_id,
            "state_fingerprint": verification.state_fingerprint,
            "evidence_details": verification.evidence_details,
            "operator_note": evidence,
        })

        cleared = self.storage.clear_resource_barrier(
            resource_key=resource_key,
            cleared_by=operator_id,
            evidence=cleared_evidence_str,
            execution_id=active.get("execution_id"),
        )

        if cleared:
            self.storage.record_action_audit(
                actor_id=operator_id,
                action_id="barrier:reconcile",
                execution_id=active.get("execution_id", "unknown"),
                decision="cleared",
                details={
                    "resource_key": resource_key,
                    "verifier_id": verification.verifier_id,
                    "state_fingerprint": verification.state_fingerprint,
                },
            )

        return {
            "ok": cleared,
            "applied": True,
            "verified": True,
            "resource_key": resource_key,
            "verifier_id": verification.verifier_id,
            "state_fingerprint": verification.state_fingerprint,
            "message": f"Barrier for '{resource_key}' authoritatively cleared with verified source evidence.",
        }
