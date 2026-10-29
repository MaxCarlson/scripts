"""Evidence-classified diagnostic rules over normalized observations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import os
from typing import Any

from .events import NormalizedEvent
from .opencode import HistoryCoverage


def diagnose_events(
    session_id: str,
    events: list[NormalizedEvent],
    analysis: dict[str, Any],
    *,
    coverage: HistoryCoverage,
    compaction_count_threshold: int = 3,
    compaction_window_seconds: float = 900.0,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    context = analysis.get("context", {})
    raw_compactions = [event for event in events if event.category == "compaction"]
    compactions_by_id: dict[str, NormalizedEvent] = {}
    for event in raw_compactions:
        key = event.provider_id or event.event_id
        existing = compactions_by_id.get(key)
        if existing is None or (existing.duration_seconds is None and event.duration_seconds is not None):
            compactions_by_id[key] = event
    compactions = list(compactions_by_id.values())
    reads = [event for event in events if _is_read(event)]
    edits = [event for event in events if _is_edit(event)]
    inferences = [event for event in events if event.category == "inference"]

    if coverage.status != "complete":
        findings.append(_finding(
            session_id, coverage, "coverage.partial_history", "info", "observed",
            "Available history is incomplete or its continuity is uncertain.",
            [{"status": coverage.status, "source": coverage.source, "pages": coverage.pages,
              "limit": coverage.limit, "reason": coverage.reason, "suspected_gap": coverage.suspected_gap}],
            recommendation="Treat event counts and absence of activity as scoped to the observed window.",
        ))

    length_events = [event for event in inferences if event.finish_reason == "length"]
    if length_events:
        findings.append(_finding(
            session_id, coverage, "context.length_finish", "warning", "observed",
            "An inference ended with finish reason 'length'.",
            [_event_evidence(event) for event in length_events],
            recommendation="Review the request's output limit and available context evidence.",
        ))

    overflow_events = [event for event in events if event.error_name and any(
        marker in event.error_name.casefold() for marker in ("context", "overflow", "tokenlimit", "token_limit")
    )]
    if overflow_events:
        findings.append(_finding(
            session_id, coverage, "context.overflow", "error", "observed",
            "Provider error metadata indicates a context or token limit failure.",
            [_event_evidence(event) | {"error_name": event.error_name} for event in overflow_events],
            recommendation="Compare the request's measured input with the effective loaded context and output reservation.",
        ))

    if context.get("utilization_percent") is not None and context["utilization_percent"] >= 85:
        findings.append(_finding(
            session_id, coverage, "context.near_limit", "warning", "observed",
            "The latest completed inference used at least 85% of the estimated usable input capacity.",
            [{"input_tokens": context.get("latest_input_tokens"),
              "usable_input_capacity": context.get("usable_input_capacity"),
              "utilization_percent": context.get("utilization_percent"),
              "threshold_percent": 85}],
            recommendation="Check whether the effective loaded context and OpenCode limits match.",
            rule_parameters={"threshold_percent": 85},
        ))

    configured = context.get("configured_context_limit")
    loaded = context.get("loaded_context_length")
    if configured is not None and loaded is not None and configured != loaded:
        findings.append(_finding(
            session_id, coverage, "model.context_capacity_mismatch", "warning", "observed",
            "OpenCode's configured context limit differs from LM Studio's reported loaded context.",
            [{"opencode_context_limit": configured, "lmstudio_loaded_context": loaded,
              "model_identity_match": context.get("model_identity_match")}],
            recommendation="Confirm both values refer to the same loaded model instance.",
        ))

    dated_compactions = [(event, _parse_time(event.timestamp)) for event in compactions]
    dated_compactions = [(event, stamp) for event, stamp in dated_compactions if stamp is not None]
    if len(dated_compactions) >= compaction_count_threshold:
        close_window: list[tuple[NormalizedEvent, datetime]] | None = None
        for index, (_, start) in enumerate(dated_compactions):
            candidates = [(event, stamp) for event, stamp in dated_compactions[index:]
                          if (stamp - start).total_seconds() <= compaction_window_seconds]
            if len(candidates) >= compaction_count_threshold:
                close_window = candidates
                break
        if close_window:
            findings.append(_finding(
                session_id, coverage, "compaction.frequent", "warning", "strong_inference",
                "Several distinct compaction cycles occurred within the configured observation window.",
                [{"event_id": event.event_id, "timestamp": event.timestamp,
                  "duration_seconds": event.duration_seconds} for event, _ in close_window],
                recommendation="Inspect the associated request sizes and work repeated after each cycle.",
                rule_parameters={"count_threshold": compaction_count_threshold,
                                 "window_seconds": compaction_window_seconds},
            ))

    reads_after_compaction: list[tuple[NormalizedEvent, NormalizedEvent]] = []
    compactions_by_time = sorted(dated_compactions, key=lambda item: item[1])
    for read in reads:
        read_time = _parse_time(read.timestamp)
        if read_time is None or not read.tool_target:
            continue
        prior = [(event, stamp) for event, stamp in compactions_by_time if stamp <= read_time]
        if prior:
            reads_after_compaction.append((prior[-1][0], read))
    grouped: dict[tuple[str, str], list[tuple[NormalizedEvent, NormalizedEvent]]] = defaultdict(list)
    for compaction, read in reads_after_compaction:
        grouped[(compaction.event_id, _normalize_path(read.tool_target or ""))].append((compaction, read))
    for (compaction_id, target), group in grouped.items():
        if len(group) < 2:
            continue
        findings.append(_finding(
            session_id, coverage, "reads.repeated_after_compaction", "info", "hypothesis",
            "The same path was read multiple times after an observed compaction; this may indicate context reconstruction.",
            [{"compaction_event_id": compaction_id, "path": group[0][1].tool_target,
              "read_count": len(group), "read_timestamps": [read.timestamp for _, read in group]}],
            recommendation="Review whether later reads were needed to continue the task.",
        ))

    failed_edits = [event for event in edits if event.outcome == "failed"]
    if failed_edits:
        findings.append(_finding(
            session_id, coverage, "tools.failed_edit", "warning", "observed",
            "An edit or write tool reported failure.", [_event_evidence(event) for event in failed_edits],
            recommendation="Inspect the tool error evidence and subsequent attempts.",
        ))

    for identity_type, key in (("model", "model_identities"), ("agent", "agent_identities")):
        identities = analysis.get(key, [])
        if len(identities) > 1:
            findings.append(_finding(
                session_id, coverage, f"lifecycle.{identity_type}_identity_changed", "info", "observed",
                f"The observed {identity_type} identity changed during the session.",
                [{"identities": identities}],
            ))

    return _deduplicate(findings)


def _finding(
    session_id: str,
    coverage: HistoryCoverage,
    code: str,
    severity: str,
    classification: str,
    summary: str,
    evidence: list[dict[str, Any]],
    *,
    recommendation: str | None = None,
    rule_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "classification": classification,
        "summary": summary,
        "evidence": evidence,
        "session_id": session_id,
        "job_id": None,
        "history_coverage": coverage.status,
        "recommendation": recommendation,
        "rule_parameters": rule_parameters or {},
    }


def _event_evidence(event: NormalizedEvent) -> dict[str, Any]:
    return {"event_id": event.event_id, "timestamp": event.timestamp,
            "finish_reason": event.finish_reason, "tool_target": event.tool_target,
            "outcome": event.outcome}


def _is_read(event: NormalizedEvent) -> bool:
    if not event.tool_name:
        return False
    name = event.tool_name.lower()
    return name in {"read", "read_file", "cat", "sed", "head", "tail", "get-content"} or (
        name == "shell" and event.tool_target is not None
    )


def _is_edit(event: NormalizedEvent) -> bool:
    return bool(event.tool_name and event.tool_name.lower() in {"edit", "write", "patch", "multiedit"})


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    normalized = os.path.normpath(normalized).replace("\\", "/")
    return normalized.casefold() if os.name == "nt" else normalized


def _deduplicate(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    output = []
    for finding in findings:
        evidence_key = str(finding["evidence"])
        key = (finding["code"], evidence_key)
        if key not in seen:
            seen.add(key)
            output.append(finding)
    return output
