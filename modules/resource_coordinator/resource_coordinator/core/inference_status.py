"""Read-only aggregation of Coordinator-known inference activity and evidence coverage."""

from __future__ import annotations

from typing import Any, Dict, Optional

from resource_coordinator.core.durable_state import RequestPhase, StateCodec


_UNRESOLVED = {
    RequestPhase.POSSIBLY_FORWARDED.value,
    RequestPhase.UNCERTAIN.value,
}
_DETAIL_FIELDS = {
    "request_id", "operation_type", "model", "resource", "lease_type", "lifecycle_state",
    "started_at", "elapsed_seconds", "configured_timeout_seconds", "connect_timeout_seconds",
    "timeout_phase", "failure_kind", "exception_class", "safe_exception_detail", "http_status",
    "terminal_evidence", "inhibition_holder", "inhibition_reason", "recovery_recommendation",
    "outcome", "upstream_elapsed_seconds", "upstream_timeout_seconds", "timeout_semantics",
    "lease_acquisition_timeout_seconds", "model_load_reported_seconds", "reconciliation_disposition",
    "resolved_by", "resolved_at",
}


def _safe_holders(raw: Optional[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    result = []
    queue = [raw]
    while queue:
        item = queue.pop(0)
        if not isinstance(item, dict):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        result.append({
            key: item[key] for key in ("resource", "reason", "holder_id", "inhibited_at")
            if isinstance(item.get(key), (str, int, float, bool)) or item.get(key) is None
        } | {"details": {key: value for key, value in details.items() if key in _DETAIL_FIELDS
                          and isinstance(value, (str, int, float, bool, type(None)))}})
        children = details.get("additional_uncertain_holders", [])
        if isinstance(children, list):
            queue.extend(child for child in children if isinstance(child, dict))
    return result


def build_inference_status(service: Any, *, lmstudio_observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Summarize managed activity; never claim physical GPU idleness from partial coverage."""
    if service is None:
        return {
            "schema_version": 1, "classification": "unavailable", "coverage": "unknown",
            "reason_codes": ["coordinator_service_unavailable"], "requests": [], "inhibition_holders": [],
            "physical_gpu_idle_proven": False,
        }
    leases = service.system.lease_mgr
    gpu_resources = {resource for resource in leases.tracked_resources() if resource.startswith("gpu.")}
    gpu_resources.update({"gpu.inference", "gpu.model_loading"})
    active = sum(leases.active_count(resource) for resource in gpu_resources)
    pending = sum(leases.pending_count(resource) for resource in gpu_resources)
    path = getattr(service.system.config.service, "state_persistence_path", "")
    durable = None
    journal_status = "not_configured"
    unresolved = []
    pending_requests = []
    all_requests = []
    gaming = {"state": "unavailable", "status": "unavailable"}
    if path:
        try:
            durable = StateCodec.load(path)
            journal_status = "available"
            gaming = dict(durable.gaming_mode)
            for request in durable.requests.values():
                safe_details = {key: value for key, value in request.details.items()
                                if key in _DETAIL_FIELDS and isinstance(value, (str, int, float, bool, type(None)))}
                item = {
                    "request_id": request.request_id, "resource": request.resource, "phase": request.phase,
                    "model": request.model, "started_at": request.created_at, "updated_at": request.updated_at,
                    "details": safe_details,
                }
                if request.phase in _UNRESOLVED:
                    unresolved.append(item)
                elif request.phase == RequestPhase.RESERVED.value:
                    pending_requests.append(item)
                all_requests.append(item)
        except (OSError, ValueError, RuntimeError):
            journal_status = "unavailable"
    inhibition_holders = []
    for resource in sorted(gpu_resources):
        inhibition = leases.get_inhibition(resource)
        inhibition_holders.extend(_safe_holders(inhibition.to_dict() if inhibition else None))
    maintenance = service.maintenance_manager.status()
    maintenance_state = maintenance.get("state", "unavailable")
    uncertain_holders = [item for item in inhibition_holders
                          if not str(item.get("holder_id", "")).startswith("maintenance:")]
    reasons = []
    if unresolved:
        reasons.append("unresolved_request_records")
    if pending_requests:
        reasons.append("pending_request_records")
    if uncertain_holders:
        reasons.append("restart_inhibition_active")
    if journal_status == "unavailable":
        reasons.append("durable_journal_unavailable")
    if journal_status == "not_configured":
        reasons.append("durable_journal_not_configured")
    if lmstudio_observation is None or lmstudio_observation.get("status") != "available":
        reasons.append("external_runtime_activity_unobserved")
    if unresolved or uncertain_holders:
        classification = "uncertain"
    elif active > 0 or maintenance_state in {"acquiring", "active", "releasing"} or gaming.get("state") not in {"inactive", "unavailable", None}:
        classification = "active"
    elif pending > 0 or pending_requests:
        classification = "pending"
    elif journal_status in {"unavailable", "not_configured"}:
        classification = "unavailable"
    else:
        classification = "quiescent"
    coverage = "unknown" if journal_status in {"unavailable", "not_configured"} else (
        "complete" if lmstudio_observation and lmstudio_observation.get("status") == "available"
        and lmstudio_observation.get("coverage") == "complete" else "partial"
    )
    return {
        "schema_version": 1, "classification": classification, "coverage": coverage,
        "provenance": {"coordinator": "authoritative_for_managed_admission", "journal": journal_status,
                       "lmstudio_observation": lmstudio_observation or {"status": "unavailable",
                                                                          "reason_code": "observer_not_qualified"}},
        "active_count": active, "pending_count": pending, "is_cooling_down": any(
            leases.is_cooling_down(resource) for resource in gpu_resources),
        "maintenance": {key: maintenance.get(key) for key in
                        ("state", "owner", "operation_id", "session_id", "expires_at", "registered_process_count",
                         "recovery_required_reason", "restoration") if key in maintenance},
        "gaming": {"state": gaming.get("state", "unavailable")},
        "runtime_identity": dict(getattr(service, "runtime_identity", {})),
        "requests": all_requests, "unresolved_requests": unresolved, "pending_requests": pending_requests,
        "inhibition_holders": inhibition_holders, "uncertain_inhibition_holders": uncertain_holders,
        "reason_codes": reasons,
        "physical_gpu_idle_proven": False,
    }
