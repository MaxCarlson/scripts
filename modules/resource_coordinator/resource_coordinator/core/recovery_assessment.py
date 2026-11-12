"""Read-only, evidence-grounded recovery classification (mutation belongs to Part 3)."""

from __future__ import annotations

import json
from typing import Any, Dict

from resource_coordinator.core.inference_status import build_inference_status
from resource_coordinator.core.durable_state import RequestPhase


def read_upgrade_receipt_summary() -> Dict[str, Any]:
    """Read a bounded, secret-free summary of the local installation receipt."""
    try:
        from resource_coordinator.installation import InstallationPaths

        receipt_path = InstallationPaths.discover().upgrade_receipt
        if not receipt_path.is_file():
            return {"status": "absent"}
        if receipt_path.stat().st_size > 1024 * 1024:
            return {"status": "unavailable", "reason_code": "upgrade_receipt_oversized"}
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            return {"status": "unavailable", "reason_code": "upgrade_receipt_malformed"}
        phase = receipt.get("phase")
        operation_id = receipt.get("operation_id")
        if not isinstance(phase, str) or not phase or len(phase) > 64:
            return {"status": "unavailable", "reason_code": "upgrade_receipt_malformed"}
        terminal_phases = {"COMMITTED", "COMPLETE", "COMPLETED", "RECONCILED"}
        status = "recovery_required" if phase.upper() == "RECOVERY_REQUIRED" else (
            "pending" if phase.upper() not in terminal_phases else "completed")
        summary: Dict[str, Any] = {"status": status, "phase": phase}
        if isinstance(operation_id, str) and 0 < len(operation_id) <= 128:
            summary["operation_id"] = operation_id
        updated_at = receipt.get("updated_at")
        if isinstance(updated_at, (str, int, float)) and not isinstance(updated_at, bool):
            summary["updated_at"] = updated_at
        return summary
    except FileNotFoundError:
        return {"status": "absent"}
    except (OSError, ValueError, TypeError, RuntimeError):
        return {"status": "unavailable", "reason_code": "upgrade_receipt_unreadable"}


def assess_recovery(service: Any, *, inference_status: Dict[str, Any] | None = None) -> Dict[str, Any]:
    inference = inference_status or build_inference_status(service)
    result: Dict[str, Any] = {
        "schema_version": 1, "assessment_mode": "online_read_only", "service_reachable": service is not None,
        "classification": "blocked", "exit_code": 2, "reason_codes": [],
        "inference": inference, "recommended_actions": [], "automatic_recovery_available": False,
    }
    upgrade_receipt = read_upgrade_receipt_summary()
    result["upgrade_receipt"] = upgrade_receipt
    if upgrade_receipt.get("status") in {"pending", "recovery_required", "unavailable"}:
        result["classification"] = "blocked"
        result["reason_codes"].append("upgrade_recovery_required" if upgrade_receipt.get("status") != "unavailable"
                                      else "upgrade_receipt_unavailable")
        result["recommended_actions"].append("Inspect the interrupted upgrade with 'rc system recovery status'.")
    if service is None:
        result.update(assessment_mode="offline_diagnostic_only", service_reachable=False,
                      reason_codes=["coordinator_service_unreachable"])
        return result
    if upgrade_receipt.get("status") in {"pending", "recovery_required", "unavailable"}:
        result["exit_code"] = 2
        return result
    maintenance = service.maintenance_manager.status()
    if service.state.value in {"failed", "stopped", "reconciliation_required"}:
        result["reason_codes"].append("coordinator_not_ready")
    elif inference["coverage"] == "unknown":
        result["reason_codes"].append("durable_state_unavailable")
    elif maintenance.get("state") == "recovery_required":
        result["classification"] = "operator_required"
        result["exit_code"] = 2
        result["reason_codes"].append("safety_hold_requires_operator_evidence")
        result["recommended_actions"].append("Inspect holds; use rc maintenance reconcile only for a recovery-required maintenance session.")
    elif inference["active_count"] or inference["pending_count"] \
            or inference["is_cooling_down"] \
            or maintenance.get("state") in {"acquiring", "active", "releasing"}:
        result["classification"] = "wait"
        result["exit_code"] = 1
        result["reason_codes"].append("managed_work_or_cooldown_active")
    elif inference.get("unresolved_requests"):
        result["classification"] = "operator_required"
        result["exit_code"] = 2
        result["reason_codes"].append("upstream_execution_termination_unverified")
        result["recommended_actions"].append("Verify the complete upstream execution boundary before resolving these requests.")
    elif inference.get("pending_requests"):
        requests = inference["pending_requests"]
        request_ids = {item.get("request_id") for item in requests}
        live_holders = {
            holder.get("holder_id") for holder in inference.get("inhibition_holders", [])
            if holder.get("resource") == "gpu.inference"
        }
        safe_phases = all(
            item.get("phase") == RequestPhase.RESERVED.value
            and item.get("details", {}).get("forwarded") is not True
            for item in requests
        )
        if safe_phases and request_ids and live_holders == request_ids:
            result["classification"] = "auto_recoverable"
            result["exit_code"] = 0
            result["automatic_recovery_available"] = True
            result["reason_codes"].append("durably_not_forwarded")
            result["recommended_actions"].append("Run 'rc recover --apply' to reconcile the verified pre-dispatch requests.")
        else:
            result["classification"] = "operator_required"
            result["exit_code"] = 2
            result["reason_codes"].append("dispatch_boundary_or_holder_identity_unverified")
    elif inference.get("uncertain_inhibition_holders"):
        requests_by_id = {item.get("request_id"): item for item in inference.get("requests", [])}
        holders = [item for item in inference["uncertain_inhibition_holders"]
                   if item.get("resource") == "gpu.inference"]
        matched_request_ids: set[str] = set()
        matched_holder_ids: set[str] = set()
        terminal_only = bool(holders)
        for holder in holders:
            holder_id = holder.get("holder_id")
            request = next((requests_by_id.get(request_id) for request_id in requests_by_id
                            if holder_id in {request_id, f"coord-{request_id}", f"crash_recovery:{request_id}"}), None)
            if request is None or request.get("phase") != RequestPhase.TERMINAL_VERIFIED.value:
                terminal_only = False
                break
            request_id = request["request_id"]
            matched_request_ids.add(request_id)
            matched_holder_ids.add(holder_id)
        if terminal_only and matched_request_ids and len(matched_holder_ids) == len(holders):
            result["classification"] = "auto_recoverable"
            result["exit_code"] = 0
            result["automatic_recovery_available"] = True
            result["reason_codes"].append("protocol_terminal_verified")
            result["recommended_actions"].append(
                "Run 'rc recover --apply' to clear only the stale holders for terminally verified requests."
            )
        else:
            result["classification"] = "operator_required"
            result["exit_code"] = 2
            result["reason_codes"].append("safety_hold_requires_operator_evidence")
            result["recommended_actions"].append("Inspect the exact inhibition holders before resolving recovery.")
    elif not service.is_ready:
        result["reason_codes"].append("coordinator_not_ready")
    else:
        result["classification"] = "no_action_required"
        result["exit_code"] = 0
        result["reason_codes"] = []
    return result
