"""External exposure lifecycle management service and barrier reconciliation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from remote_control.actions.storage import ActionStorage
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

    def enable(self, apply: bool = False, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        """Configure and enable Tailscale Funnel. Requires apply=True for execution."""
        if not apply:
            plan_res = self.plan(port=port, public_port=public_port)
            plan_res["message"] = "Dry-run only. Re-run with -a / --apply to execute."
            return plan_res

        # Check preflight doctor
        doc = self.doctor()
        if not doc["checks"]["tailscale"]["installed"]:
            return {
                "ok": False,
                "applied": False,
                "error": "tailscale_not_installed",
                "message": "Tailscale is not installed on this host. Run doctor for details.",
            }

        return self.client.enable_funnel(port=port, public_port=public_port)

    def disable(self, apply: bool = False, public_port: int = 8443) -> Dict[str, Any]:
        """Stop and disable Tailscale Funnel reachability. Requires apply=True for execution."""
        if not apply:
            return {
                "ok": True,
                "applied": False,
                "commands": [
                    f"tailscale funnel {public_port} off",
                    f"tailscale serve --https={public_port} off",
                ],
                "message": "Dry-run only. Re-run with -a / --apply to execute.",
            }

        return self.client.disable_funnel(public_port=public_port)

    def repair(self, apply: bool = False, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        """Re-align Funnel configuration and ensure fail-closed state."""
        if not apply:
            return {
                "ok": True,
                "applied": False,
                "message": "Dry-run repair plan. Re-run with -a / --apply to execute.",
            }

        self.client.disable_funnel(public_port=public_port)
        return self.client.enable_funnel(port=port, public_port=public_port)

    def reconcile_barrier(
        self,
        resource_key: str,
        evidence: str,
        apply: bool = False,
        operator_id: str = "operator",
    ) -> Dict[str, Any]:
        """Authoritatively reconcile an active unresolved barrier (Amendment 2).

        Must be an explicit, separate operation.
        Prohibits generic override of Resource Coordinator recovery.
        Requires -a/--apply and authoritative source evidence.
        """
        active = self.storage.get_active_barrier(resource_key)
        if not active:
            return {
                "ok": True,
                "applied": False,
                "resource_key": resource_key,
                "message": f"No active barrier found for resource key '{resource_key}'.",
            }

        # Check prohibited resources
        is_prohibited = (
            resource_key in PROTECTED_COORDINATOR_RESOURCES
            or resource_key.startswith("coordinator:recovery")
            or "gpu.inference" in resource_key
        )
        if is_prohibited:
            logger.warning("Attempted generic manual override of prohibited barrier: %s", resource_key)
            return {
                "ok": False,
                "applied": False,
                "error": "coordinator_recovery_prohibited",
                "message": (
                    "Generic manual override of Resource Coordinator recovery is prohibited "
                    "without an approved, verified recovery contract."
                ),
            }

        if not apply:
            return {
                "ok": True,
                "applied": False,
                "resource_key": resource_key,
                "active_barrier": active,
                "proposed_evidence": evidence,
                "message": "Dry-run only. Re-run with -a / --apply to clear barrier.",
            }

        cleared = self.storage.clear_resource_barrier(
            resource_key=resource_key,
            cleared_by=operator_id,
            evidence=evidence,
        )

        if cleared:
            self.storage.record_action_audit(
                actor_id=operator_id,
                action_id="barrier:reconcile",
                execution_id=active.get("execution_id", "unknown"),
                decision="cleared",
                details={"resource_key": resource_key, "evidence": evidence},
            )

        return {
            "ok": cleared,
            "applied": True,
            "resource_key": resource_key,
            "message": f"Barrier for '{resource_key}' authoritatively cleared with evidence.",
        }
