"""Pure analysis of normalized session evidence."""

from __future__ import annotations

from typing import Any

from .events import NormalizedEvent
from .opencode import HistoryCoverage


def analyze_events(
    session_id: str,
    events: list[NormalizedEvent],
    *,
    coverage: HistoryCoverage,
    limits: dict[str, Any] | None = None,
    loaded_model: dict[str, Any] | None = None,
    cumulative_tokens: dict[str, Any] | None = None,
    session_state: Any = None,
) -> dict[str, Any]:
    limits = limits or {}
    loaded_model = loaded_model or {}
    inferences = [event for event in events if event.category == "inference"]
    completed = [event for event in inferences if event.outcome == "completed"]
    latest = completed[-1] if completed else None
    configured_context = _positive_number(limits.get("context"))
    output_limit = _positive_number(limits.get("output"))
    loaded_context = _positive_number(loaded_model.get("context_length"))
    current_model = next((event.model for event in reversed(inferences) if event.model), None)
    loaded_id = loaded_model.get("id") if isinstance(loaded_model.get("id"), str) else None
    model_match = bool(current_model and loaded_id and current_model == loaded_id)
    effective_capacity = min(configured_context, loaded_context) if configured_context and loaded_context and model_match else None
    usable_capacity = max(0, effective_capacity - (output_limit or 0)) if effective_capacity else None
    latest_input = _positive_or_zero(latest.tokens.get("input")) if latest and latest.tokens else None
    utilization = round(latest_input / usable_capacity * 100, 1) if latest_input is not None and usable_capacity else None
    per_request_utilization = [
        event.tokens["input"] / usable_capacity * 100
        for event in completed
        if event.tokens and "input" in event.tokens and usable_capacity
    ]
    compaction_events = [event for event in events if event.category == "compaction"]
    unique_compactions: dict[str, NormalizedEvent] = {}
    for event in compaction_events:
        key = event.provider_id or event.event_id
        existing = unique_compactions.get(key)
        if existing is None or (existing.duration_seconds is None and event.duration_seconds is not None):
            unique_compactions[key] = event
    compactions = list(unique_compactions.values())
    tools = [event for event in events if event.category == "tool"]
    read_tools = [event for event in tools if _is_read_event(event)]
    edits = [event for event in tools if event.tool_name and event.tool_name.lower() in
             {"edit", "write", "patch", "multiedit"}]
    model_identities = list(dict.fromkeys(event.model for event in inferences if event.model))
    agent_identities = list(dict.fromkeys(event.agent for event in inferences if event.agent))
    history_available = coverage.status != "unavailable"

    return {
        "schema_version": 1,
        "session_id": session_id,
        "coverage": coverage.__dict__,
        "session_state": session_state,
        "inference": {
            "count": len(inferences) if history_available else None,
            "completed_count": len(completed) if history_available else None,
            "latest_completed": _inference_record(latest, throughput=True) if latest else None,
            "total_output_tokens_observed": sum(
                event.tokens.get("output", 0) for event in completed if event.tokens
            ) if history_available and any(event.tokens and "output" in event.tokens for event in completed) else None,
            "throughput_scope": "observed_message_elapsed_not_decode_rate",
        },
        "context": {
            "configured_context_limit": configured_context,
            "configured_output_limit": output_limit,
            "loaded_context_length": loaded_context,
            "loaded_model_id": loaded_id,
            "current_model_id": current_model,
            "model_identity_match": model_match if current_model and loaded_id else None,
            "effective_capacity": effective_capacity,
            "usable_input_capacity": usable_capacity,
            "capacity_status": "observed_match" if effective_capacity else "unknown",
            "capacity_assumption": "min(matched loaded context, OpenCode context limit) minus output reservation",
            "latest_input_tokens": latest_input,
            "latest_cache_read_tokens": latest.tokens.get("cache_read") if latest and latest.tokens else None,
            "latest_cache_write_tokens": latest.tokens.get("cache_write") if latest and latest.tokens else None,
            "cache_tokens_combined_with_input": False,
            "utilization_percent": utilization,
            "estimated_remaining_tokens": max(0, usable_capacity - latest_input)
            if usable_capacity is not None and latest_input is not None else None,
            "maximum_observed_utilization_percent": round(max(per_request_utilization), 1)
            if per_request_utilization else None,
            "status": "observed" if utilization is not None else "unknown",
        },
        "compactions": {
            "unique_count": len(compactions) if history_available else None,
            "raw_parts": len(compaction_events) if history_available else None,
            "measured_duration_seconds": [event.duration_seconds for event in compactions
                                           if event.duration_seconds is not None] if history_available else None,
            "unmeasured_duration_count": sum(1 for event in compactions if event.duration_seconds is None)
            if history_available else None,
            "timeline": [
                {"event_id": event.event_id, "timestamp": event.timestamp,
                 "duration_seconds": event.duration_seconds, "outcome": event.outcome}
                for event in compactions
            ] if history_available else None,
        },
        "tools": {
            "count": len(tools) if history_available else None,
            "failed_count": sum(1 for event in tools if event.outcome == "failed") if history_available else None,
            "latest": tools[-1].to_dict() if tools else None,
            "read_count": len(read_tools) if history_available else None,
            "reads": [event.to_dict() for event in read_tools] if history_available else None,
            "edit_attempts": len(edits) if history_available else None,
            "edit_reported_success": sum(1 for event in edits if event.outcome == "succeeded"),
            "edit_failures": sum(1 for event in edits if event.outcome == "failed") if history_available else None,
            "edit_verification": "unverified" if history_available else "unknown",
        },
        "model_identities": model_identities if history_available else None,
        "agent_identities": agent_identities if history_available else None,
        "cumulative_tokens": cumulative_tokens,
        "completion": {
            "latest_inference_completed": bool(latest) if history_available else None,
            "session_job_completed": "unknown",
            "work_product_completed": "unverified",
            "task_accepted": "unverified",
        },
    }


def _inference_record(event: NormalizedEvent, *, throughput: bool) -> dict[str, Any]:
    tokens = event.tokens or {}
    output = _positive_or_zero(tokens.get("output"))
    tps = output / event.duration_seconds if throughput and output is not None and event.duration_seconds else None
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "completed_at": event.completed_at,
        "finish_reason": event.finish_reason,
        "duration_seconds": event.duration_seconds,
        "input_tokens": _positive_or_zero(tokens.get("input")),
        "output_tokens": output,
        "reasoning_tokens": _positive_or_zero(tokens.get("reasoning")),
        "cache_read_tokens": _positive_or_zero(tokens.get("cache_read")),
        "cache_write_tokens": _positive_or_zero(tokens.get("cache_write")),
        "observed_end_to_end_tokens_per_second": round(tps, 2) if tps is not None else None,
        "throughput_kind": "message_elapsed_approximation" if tps is not None else None,
        "agent": event.agent,
        "model": event.model,
    }


def _is_read_event(event: NormalizedEvent) -> bool:
    if not event.tool_name:
        return False
    name = event.tool_name.lower()
    return name in {"read", "read_file", "cat", "sed", "head", "tail", "get-content"} or (
        name == "shell" and event.tool_target is not None
    )


def _positive_number(value: Any) -> int | float | None:
    number = _positive_or_zero(value)
    return number if number and number > 0 else None


def _positive_or_zero(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None
