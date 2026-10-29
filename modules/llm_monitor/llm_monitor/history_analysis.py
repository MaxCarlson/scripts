"""Streaming analytics and conservative timeline reconstruction for persisted sessions."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable

from .events import NormalizedEvent
from .storage import TelemetryStore


NORMALIZED_CATEGORIES = {"message", "inference", "compaction", "tool"}
ACTIVITY_CATEGORIES = ("inference", "tool", "compaction")
PERCENTILE_MIN_SAMPLES = 5


def analyze_stored_session(
    store: TelemetryStore,
    session_id: str,
    *,
    endpoint: str | None = None,
    batch_size: int = 512,
    max_sample_gap_seconds: float = 30.0,
    timeline_limit: int = 1000,
) -> dict[str, Any]:
    """Analyze every stored row without materializing the complete event history."""
    if max_sample_gap_seconds <= 0:
        raise ValueError("max_sample_gap_seconds must be greater than zero")
    context = store.session_context(session_id, endpoint=endpoint)
    if context is None:
        raise ValueError(f"session {session_id!r} was not found in the telemetry database")
    coverage = context["coverage"]
    session = context["session"]

    inference_count = completed_inferences = running_inferences = 0
    inference_durations: list[float] = []
    throughput_samples: list[float] = []
    token_values: dict[str, list[float]] = defaultdict(list)
    token_totals: dict[str, float] = defaultdict(float)
    token_seen: set[str] = set()
    context_utilization: list[float] = []
    context_capacities: list[int] = []
    usable_input_capacities: list[int] = []
    model_ids: set[str] = set()
    agent_ids: set[str] = set()
    inference_intervals: list[tuple[datetime, datetime]] = []
    tool_intervals: list[tuple[datetime, datetime]] = []
    compaction_intervals: list[tuple[datetime, datetime]] = []
    inference_event_refs: list[dict[str, Any]] = []
    tool_counts: Counter[str] = Counter()
    failed_tools: Counter[str] = Counter()
    read_count = edit_attempts = edit_successes = edit_failures = 0
    read_targets: Counter[str] = Counter()
    reads_after_compaction: Counter[str] = Counter()
    reads_after_compaction_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tool_failure_fingerprints: Counter[tuple[str, str | None]] = Counter()
    tool_durations: list[float] = []
    compactions: dict[str, dict[str, Any]] = {}
    raw_compaction_parts = 0
    length_terminations: list[dict[str, Any]] = []
    inferences_near_limit: list[dict[str, Any]] = []
    latest_compaction_time: datetime | None = None
    event_counts: Counter[str] = Counter()
    timeline_markers: list[dict[str, Any]] = []
    state_samples: list[tuple[datetime, str | None, dict[str, Any]]] = []
    lifecycle_transitions: list[dict[str, Any]] = []

    model_configurations = context["model_configurations"]
    config_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for configuration in model_configurations:
        if configuration.get("model_id"):
            config_by_model[configuration["model_id"]].append(configuration)

    for record in store.iter_session_records(session_id, endpoint=endpoint, batch_size=batch_size):
        category = record["category"]
        payload = record["payload"]
        event_counts[category] += 1
        if category == "lifecycle":
            if record.get("subtype") == "state_observation":
                stamp = _parse_time(payload.get("timestamp"))
                if stamp:
                    state_samples.append((stamp, payload.get("state"), payload))
            elif record.get("subtype") == "state_change":
                lifecycle_transitions.append(payload)
            timeline_markers.append(_marker(payload, record))
            continue
        if category not in NORMALIZED_CATEGORIES:
            continue
        event_data = dict(payload)
        event_data.pop("identity_quality", None)
        try:
            event = NormalizedEvent(**event_data)
        except TypeError:
            # Future/unknown payload shapes remain counted but are not silently coerced.
            event_counts["unparsed"] += 1
            continue
        timestamp = _parse_time(event.timestamp)
        end = _event_end(event, timestamp)
        if timestamp and end and end >= timestamp:
            interval = (timestamp, end)
            if category == "inference":
                inference_intervals.append(interval)
            elif category == "tool":
                tool_intervals.append(interval)
            elif category == "compaction":
                compaction_intervals.append(interval)
        timeline_markers.append(_marker(event.to_dict(), record))

        if event.agent:
            agent_ids.add(event.agent)
        if event.model:
            model_ids.add(event.model)

        if category == "inference":
            inference_count += 1
            if event.outcome == "completed":
                completed_inferences += 1
                for name, value in (event.tokens or {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                        token_seen.add(name)
                        token_values[name].append(float(value))
                        token_totals[name] += value
                output = (event.tokens or {}).get("output")
                if isinstance(output, (int, float)) and event.duration_seconds and event.duration_seconds > 0:
                    throughput_samples.append(float(output) / event.duration_seconds)
                if event.duration_seconds is not None and event.duration_seconds >= 0:
                    inference_durations.append(event.duration_seconds)
            elif event.outcome in {"running", "in_progress", "started"}:
                running_inferences += 1
            if event.finish_reason == "length":
                length_terminations.append(_evidence_ref(event))
            utilization, effective_capacity, usable_capacity = _event_context(event, timestamp, config_by_model)
            timeline_markers[-1]["context_utilization_percent"] = round(utilization, 2) if utilization is not None else None
            timeline_markers[-1]["usable_input_capacity_tokens"] = usable_capacity
            if effective_capacity is not None:
                context_capacities.append(effective_capacity)
            if usable_capacity is not None:
                usable_input_capacities.append(usable_capacity)
            if utilization is not None:
                context_utilization.append(utilization)
                if utilization >= 85:
                    inferences_near_limit.append(_evidence_ref(event) | {
                        "utilization_percent": round(utilization, 1), "usable_capacity": usable_capacity,
                        "threshold_percent": 85,
                    })
            inference_event_refs.append(_evidence_ref(event))
        elif category == "compaction":
            raw_compaction_parts += 1
            identity = event.provider_id or event.event_id
            current = compactions.get(identity)
            if current is None:
                current = {"operation_id": identity, "event_ids": [], "timestamps": [],
                           "durations_seconds": [], "outcomes": []}
                compactions[identity] = current
            current["event_ids"].append(event.event_id)
            if event.timestamp:
                current["timestamps"].append(event.timestamp)
            if event.duration_seconds is not None:
                current["durations_seconds"].append(event.duration_seconds)
            if event.outcome:
                current["outcomes"].append(event.outcome)
            if timestamp and (latest_compaction_time is None or timestamp > latest_compaction_time):
                latest_compaction_time = timestamp
        elif category == "tool":
            name = (event.tool_name or "unknown").casefold()
            tool_counts[name] += 1
            if event.duration_seconds is not None and event.duration_seconds >= 0:
                tool_durations.append(event.duration_seconds)
            if name in {"read", "read_file", "cat", "sed", "head", "tail", "get-content"} or (
                name == "shell" and event.tool_target is not None
            ):
                read_count += 1
                if event.tool_target:
                    read_targets[event.tool_target] += 1
                    if latest_compaction_time is not None and timestamp and timestamp >= latest_compaction_time:
                        reads_after_compaction[event.tool_target] += 1
                        reads_after_compaction_refs[event.tool_target].append(_evidence_ref(event))
            if name in {"edit", "write", "patch", "multiedit"}:
                edit_attempts += 1
                edit_successes += int(event.outcome == "succeeded")
                edit_failures += int(event.outcome == "failed")
            if event.outcome == "failed":
                failed_tools[name] += 1
                tool_failure_fingerprints[(name, event.tool_target)] += 1

    context["history_event_count"] = context["event_count"]
    compaction_records = []
    for item in compactions.values():
        times = sorted(item["timestamps"])
        durations = item["durations_seconds"]
        compaction_records.append({
            "operation_id": item["operation_id"],
            "event_ids": item["event_ids"],
            "started_at": times[0] if times else None,
            "duration_seconds": max(durations) if durations else None,
            "outcome": item["outcomes"][-1] if item["outcomes"] else None,
        })
    compaction_records.sort(key=lambda item: item["started_at"] or "")
    compaction_durations = [item["duration_seconds"] for item in compaction_records
                            if item["duration_seconds"] is not None]

    wall_start = _parse_time(session.get("first_seen"))
    wall_end = _parse_time(session.get("last_seen"))
    observed_wall_seconds = max(0.0, (wall_end - wall_start).total_seconds()) if wall_start and wall_end else None
    inference_union = _interval_union_seconds(inference_intervals)
    tool_union = _interval_union_seconds(tool_intervals)
    compaction_union = _interval_union_seconds(compaction_intervals)
    combined_union = _interval_union_seconds(inference_intervals + tool_intervals + compaction_intervals)
    category_sum = sum(value for value in (inference_union, tool_union, compaction_union) if value is not None)
    sampled_state = _sampled_state_metrics(state_samples, max_sample_gap_seconds)
    repeated_targets = {target: refs for target, refs in reads_after_compaction_refs.items() if len(refs) > 1}
    repeated_failures = [
        {"tool_name": name, "target_id": target, "failed_calls": count}
        for (name, target), count in tool_failure_fingerprints.items() if count >= 2
    ]

    metrics = {
        "execution": {
            "observed_wall_seconds": _metric(observed_wall_seconds, "first_to_last_monitor_observation",
                                               2 if observed_wall_seconds is not None else 0, coverage),
            "time_by_operation_seconds": {
                "inference": _metric(inference_union, "union_of_provider_timed_intervals", len(inference_intervals), coverage),
                "tool": _metric(tool_union, "union_of_provider_timed_intervals", len(tool_intervals), coverage),
                "compaction": _metric(compaction_union, "union_of_provider_timed_intervals", len(compaction_intervals), coverage),
                "combined_activity_union": _metric(combined_union, "union_across_known_activity_intervals",
                                                    len(inference_intervals) + len(tool_intervals) + len(compaction_intervals), coverage),
                "cross_category_overlap": _metric(max(0.0, category_sum - combined_union)
                                                    if combined_union is not None else None,
                                                    "sum_of_category_unions_minus_combined_union",
                                                    len(inference_intervals) + len(tool_intervals) + len(compaction_intervals), coverage),
                "unclassified_not_idle": _metric(max(0.0, observed_wall_seconds - combined_union)
                                                  if observed_wall_seconds is not None and combined_union is not None else None,
                                                  "wall_span_minus_known_activity_union; not an idle estimate",
                                                  2, coverage),
            },
            "sampled_state_seconds": sampled_state,
            "collection_gaps": context["gaps"],
        },
        "inference": {
            "count": inference_count,
            "completed_count": completed_inferences,
            "in_progress_count": running_inferences,
            "duration_seconds": _statistics(inference_durations, "provider_start_completion_boundary", coverage),
            "output_tokens_per_second": _statistics(throughput_samples, "approx_message_elapsed", coverage),
            "throughput_note": "Approximate end-to-end message rate; not measured decode throughput.",
        },
        "tokens": {
            "observed_completed_totals": {name: _metric(token_totals[name], "sum_of_completed_inference_records",
                                                          len(token_values[name]), coverage)
                                          for name in sorted(token_seen)},
            "per_inference": {name: _statistics(values, "provider_reported_per_inference", coverage)
                              for name, values in sorted(token_values.items())},
            "session_cumulative_provider_total": None,
        },
        "context": {
            "effective_capacity_tokens": _statistics(context_capacities, "matching_loaded_and_configured_capacity", coverage),
            "usable_input_capacity_tokens": _statistics(usable_input_capacities, "effective_capacity_minus_output_reservation", coverage),
            "utilization_percent": _statistics(context_utilization, "input_tokens_over_usable_capacity", coverage),
            "maximum_observed_utilization_percent": max(context_utilization) if context_utilization else None,
            "utilization_sample_count": len(context_utilization),
            "model_identities": sorted(model_ids),
        },
        "compactions": {
            "unique_cycles": len(compactions),
            "raw_parts": raw_compaction_parts,
            "duration_seconds": _statistics(compaction_durations, "provider_compaction_boundaries", coverage),
            "cycles_per_observed_hour": _rate(len(compactions), observed_wall_seconds),
            "cycles": compaction_records,
            "interval_seconds": _differences([_parse_time(item["started_at"]) for item in compaction_records]),
        },
        "tools": {
            "invocations": sum(tool_counts.values()),
            "by_operation": dict(sorted(tool_counts.items())),
            "failures_by_operation": dict(sorted(failed_tools.items())),
            "duration_seconds": _statistics(tool_durations, "provider_tool_boundaries", coverage),
            "read_calls": read_count,
            "distinct_read_targets": len(read_targets),
            "repeated_read_targets": sum(1 for count in read_targets.values() if count > 1),
            "reads_after_compaction": sum(reads_after_compaction.values()),
            "repeated_read_targets_after_compaction": len(repeated_targets),
            "repeated_read_evidence": [
                {"target_id": target, "read_count": len(refs), "events": refs}
                for target, refs in sorted(repeated_targets.items())
            ],
            "edit_attempts": edit_attempts,
            "reported_edit_successes": edit_successes,
            "reported_edit_failures": edit_failures,
            "edit_verification": "unverified",
            "repeated_failure_loops": repeated_failures,
        },
        "hardware": _hardware_metrics(context["hardware_samples"], coverage,
                                       context["hardware_sample_total"], context["hardware_samples_truncated"]),
        "coverage": {
            "status": coverage.get("status", "unknown"),
            "source": coverage.get("source", "unknown"),
            "event_rows": context["event_count"],
            "gaps": context["gaps"],
            "state_samples": len(state_samples),
            "state_sample_note": "Phase 3A records have transition-only state evidence; sampled occupancy is unavailable before state observations were added.",
        },
        "completion": {
            "inference_completion": {"completed": completed_inferences, "in_progress": running_inferences},
            "session_completion": session.get("state") if session.get("state") == "completed" else "unknown",
            "work_product_completion": "unverified",
            "task_acceptance": "unverified",
            "mcp_jobs": context["jobs"],
        },
        "timeline": {
            "event_counts": dict(sorted(event_counts.items())),
            "marker_count": len(timeline_markers),
            "markers": _downsample_markers(timeline_markers, timeline_limit),
            "downsampled": len(timeline_markers) > timeline_limit,
            "lifecycle_transitions": lifecycle_transitions,
        },
    }
    findings = _historical_findings(
        session_id, coverage, compaction_records, repeated_targets, repeated_failures,
        length_terminations, inferences_near_limit, context["gaps"],
    )
    return {
        "schema_version": 1,
        "source": "persisted_telemetry",
        "session": {
            "session_id": session_id,
            "provider_instance": session.get("endpoint"),
            "first_observed": session.get("first_seen"),
            "last_observed": session.get("last_seen"),
            "model": session.get("model"),
            "agent": session.get("agent"),
        },
        "coverage": metrics["coverage"],
        "metrics": metrics,
        "completion": metrics["completion"],
        "findings": findings,
        "provenance": {
            "event_source": "TelemetryStore.iter_session_records",
            "database_schema_version": store.schema_version,
            "streamed": True,
            "metric_coverage": coverage.get("status", "unknown"),
            "task_equivalence": "unknown",
        },
    }


def compare_stored_sessions(
    store: TelemetryStore,
    session_ids: list[str],
    *,
    endpoints: list[str | None] | None = None,
    batch_size: int = 512,
) -> dict[str, Any]:
    """Compare two or more runs against the first, preserving missing metrics."""
    if len(session_ids) < 2:
        raise ValueError("comparison requires at least two session identifiers")
    selected_endpoints = endpoints or [None] * len(session_ids)
    if len(selected_endpoints) == 1 and len(session_ids) > 1:
        selected_endpoints *= len(session_ids)
    if len(selected_endpoints) != len(session_ids):
        raise ValueError("provide either one endpoint or one endpoint per session")
    runs = [analyze_stored_session(store, sid, endpoint=endpoint, batch_size=batch_size)
            for sid, endpoint in zip(session_ids, selected_endpoints)]
    metric_values = [_comparison_metrics(run) for run in runs]
    metric_names = list(metric_values[0])
    differences: dict[str, list[dict[str, Any]]] = {}
    for name in metric_names:
        base_value = metric_values[0][name]
        differences[name] = []
        for index, value_set in enumerate(metric_values[1:], start=1):
            value = value_set.get(name)
            delta, percent, status = _difference(base_value, value)
            differences[name].append({
                "baseline_session_id": session_ids[0],
                "session_id": session_ids[index],
                "baseline": base_value,
                "value": value,
                "absolute": delta,
                "percent": percent,
                "status": status,
            })
    warnings = _comparison_warnings(runs)
    return {
        "schema_version": 1,
        "baseline_session_id": session_ids[0],
        "runs": runs,
        "differences": differences,
        "comparability": {"task_equivalence": "unknown", "task_acceptance_comparable": False,
                          "summary": "No task identifier or independently verified acceptance metadata is stored."},
        "warnings": warnings,
        "provenance": {"source": "persisted_telemetry", "offline": True,
                       "significance_claim": False, "causal_attribution": False},
    }


def reconstruct_timeline(records: Iterable[dict[str, Any]], *, gaps: list[dict[str, Any]] | None = None,
                         limit: int = 1000) -> dict[str, Any]:
    """Return bounded privacy-safe markers and unioned known activity intervals."""
    markers = []
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    total = 0
    for record in records:
        total += 1
        category = record.get("category") or "unknown"
        counts[category] += 1
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if category in NORMALIZED_CATEGORIES:
            data = dict(payload)
            data.pop("identity_quality", None)
            try:
                event = NormalizedEvent(**data)
            except TypeError:
                event = None
            if event:
                start = _parse_time(event.timestamp)
                end = _event_end(event, start)
                if start and end and end >= start and category in ACTIVITY_CATEGORIES:
                    intervals[category].append((start, end))
                markers.append(_marker(event.to_dict(), record))
                continue
        markers.append(_marker(payload, record))
    category_durations = {key: _interval_union_seconds(value) for key, value in intervals.items()}
    all_intervals = [span for spans in intervals.values() for span in spans]
    return {
        "event_count": total,
        "event_counts": dict(sorted(counts.items())),
        "markers": _downsample_markers(markers, limit),
        "downsampled": len(markers) > limit,
        "time_by_operation_seconds": category_durations,
        "combined_activity_union_seconds": _interval_union_seconds(all_intervals),
        "gaps": gaps or [],
    }


def _historical_findings(session_id, coverage, compactions, repeated_targets, repeated_failures,
                         length_events, near_limit, gaps):
    findings = []
    coverage_status = coverage.get("status", "unknown")
    if coverage_status != "complete" or gaps:
        findings.append(_finding(session_id, coverage_status, "coverage.incomplete", "info", "observed",
                                 "Persisted history contains partial coverage or collection gaps.",
                                 {"gaps": len(gaps), "coverage_status": coverage_status}))
    dated = [_parse_time(item["started_at"]) for item in compactions if item.get("started_at")]
    dated = sorted(value for value in dated if value)
    threshold_count, window = 3, 900.0
    crowded = []
    for start_index, start in enumerate(dated):
        end_index = start_index
        while end_index < len(dated) and (dated[end_index] - start).total_seconds() <= window:
            end_index += 1
        if end_index - start_index >= threshold_count:
            crowded = dated[start_index:end_index]
            break
    if crowded:
        findings.append(_finding(session_id, coverage_status, "compaction.frequent", "warning", "strong_inference",
                                 "Several unique compaction cycles occurred within the historical window.",
                                 {"cycle_count": len(crowded), "window_seconds": window,
                                  "timestamps": [item.isoformat() for item in crowded]},
                                 {"count_threshold": threshold_count, "window_seconds": window}))
    repeated = [{"target_id": target, "read_count": len(refs), "events": refs}
                for target, refs in repeated_targets.items() if len(refs) >= 2]
    if repeated:
        findings.append(_finding(session_id, coverage_status, "reads.repeated_after_compaction", "info", "hypothesis",
                                 "Repeated reads of the same privacy-safe target were observed after compaction; this may indicate context reconstruction.",
                                 {"targets": repeated}))
    if repeated_failures:
        findings.append(_finding(session_id, coverage_status, "tools.repeated_failures", "warning", "strong_inference",
                                 "The same tool operation and target reported multiple failures.",
                                 {"operations": repeated_failures}))
    if length_events:
        findings.append(_finding(session_id, coverage_status, "inference.length_termination", "warning", "observed",
                                 "One or more recorded inferences ended with finish reason 'length'.",
                                 {"events": length_events}))
    if near_limit:
        findings.append(_finding(session_id, coverage_status, "context.near_capacity", "warning", "observed",
                                 "Recorded inference input reached or exceeded 85% of matched usable capacity.",
                                 {"inferences": near_limit}, {"threshold_percent": 85}))
    return findings


def _finding(session_id, coverage, code, severity, classification, summary, evidence, parameters=None):
    return {"code": code, "severity": severity, "classification": classification, "summary": summary,
            "session_id": session_id, "evidence": evidence, "history_coverage": coverage,
            "rule_parameters": parameters or {}, "recommendation": None}


def _comparison_metrics(run):
    metrics = run["metrics"]
    totals = metrics["tokens"]["observed_completed_totals"]
    return {
        "observed_wall_seconds": metrics["execution"]["observed_wall_seconds"]["value"],
        "inference_union_seconds": _metric_value(metrics["execution"]["time_by_operation_seconds"]["inference"]),
        "tool_union_seconds": _metric_value(metrics["execution"]["time_by_operation_seconds"]["tool"]),
        "compaction_union_seconds": _metric_value(metrics["execution"]["time_by_operation_seconds"]["compaction"]),
        "context_capacity": metrics["context"]["effective_capacity_tokens"].get("maximum"),
        "inference_count": metrics["inference"]["completed_count"],
        "input_tokens": _metric_value(totals.get("input")),
        "output_tokens": _metric_value(totals.get("output")),
        "reasoning_tokens": _metric_value(totals.get("reasoning")),
        "output_tokens_per_second_p50": metrics["inference"]["output_tokens_per_second"].get("median"),
        "maximum_context_utilization_percent": metrics["context"]["maximum_observed_utilization_percent"],
        "compactions": metrics["compactions"]["unique_cycles"],
        "compactions_per_observed_hour": metrics["compactions"]["cycles_per_observed_hour"],
        "compaction_duration_total_seconds": metrics["compactions"]["duration_seconds"].get("mean") *
            metrics["compactions"]["duration_seconds"].get("count", 0)
            if metrics["compactions"]["duration_seconds"].get("mean") is not None else None,
        "tool_invocations": metrics["tools"]["invocations"],
        "tool_failures": sum(metrics["tools"]["failures_by_operation"].values()),
        "read_calls": metrics["tools"]["read_calls"],
        "reads_per_completed_inference": metrics["tools"]["read_calls"] / metrics["inference"]["completed_count"]
            if metrics["inference"]["completed_count"] else None,
        "repeated_read_targets": metrics["tools"]["repeated_read_targets"],
        "reads_after_compaction": metrics["tools"]["reads_after_compaction"],
        "edit_attempts": metrics["tools"]["edit_attempts"],
        "reported_edit_successes": metrics["tools"]["reported_edit_successes"],
        "reported_edit_failures": metrics["tools"]["reported_edit_failures"],
        "hardware_sample_count": metrics["hardware"]["sample_count"],
    }


def _comparison_warnings(runs):
    warnings = [{"code": "comparison.task_equivalence_unknown", "classification": "hypothesis",
                 "summary": "The database has no task/workload identifier; equal task difficulty cannot be assumed."},
                {"code": "comparison.acceptance_unverified", "classification": "observed",
                 "summary": "Independent task acceptance is unavailable for the compared runs."}]
    coverage = {run["coverage"].get("status") for run in runs}
    if len(coverage) > 1:
        warnings.append({"code": "comparison.coverage_differs", "classification": "observed",
                         "summary": "The runs have different history coverage classifications.",
                         "values": [run["coverage"].get("status") for run in runs]})
    models = sorted({tuple(run["metrics"]["context"]["model_identities"]) for run in runs})
    if len(models) > 1:
        warnings.append({"code": "comparison.model_differs", "classification": "observed",
                         "summary": "The runs recorded different model identities.",
                         "values": [list(value) for value in models]})
    capacities = [run["metrics"]["context"]["effective_capacity_tokens"].get("maximum") for run in runs]
    if len(set(capacities)) > 1:
        warnings.append({"code": "comparison.capacity_differs", "classification": "observed",
                         "summary": "The runs used different or unavailable effective context capacities.",
                         "values": capacities})
    hardware_counts = [run["metrics"]["hardware"]["sample_count"] for run in runs]
    if len(set(hardware_counts)) > 1:
        warnings.append({"code": "comparison.hardware_sampling_differs", "classification": "observed",
                         "summary": "Hardware sampling coverage differs; device activity is not attributed to sessions.",
                         "sample_counts": hardware_counts})
    return warnings


def _difference(baseline, value):
    if baseline is None or value is None:
        return None, None, "unavailable"
    delta = value - baseline
    percent = round(delta / baseline * 100, 2) if baseline else None
    return delta, percent, "zero_denominator" if baseline == 0 else "observed"


def _metric_value(metric):
    return metric.get("value") if isinstance(metric, dict) else None


def _statistics(values: list[float], method: str, coverage: dict[str, Any]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "minimum": None, "maximum": None, "mean": None, "median": None,
                "p50": None, "p90": None, "p95": None,
                "percentile_sample_threshold": PERCENTILE_MIN_SAMPLES,
                "percentile_status": "unavailable", "method": method, "status": "unavailable",
                "history_coverage": coverage.get("status", "unknown")}
    ordered = sorted(values)
    median = _percentile(ordered, 0.5)
    return {"count": len(ordered), "minimum": ordered[0], "maximum": ordered[-1],
            "mean": sum(ordered) / len(ordered), "median": median,
            "p50": median,
            "p90": _percentile(ordered, 0.9) if len(ordered) >= PERCENTILE_MIN_SAMPLES else None,
            "p95": _percentile(ordered, 0.95) if len(ordered) >= PERCENTILE_MIN_SAMPLES else None,
            "percentile_sample_threshold": PERCENTILE_MIN_SAMPLES,
            "percentile_status": "available" if len(ordered) >= PERCENTILE_MIN_SAMPLES else "insufficient_sample",
            "method": method, "status": "partial" if coverage.get("status") != "complete" else "observed",
            "history_coverage": coverage.get("status", "unknown")}


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _metric(value, method, sample_count, coverage):
    return {"value": value, "method": method, "sample_count": sample_count,
            "status": "unavailable" if value is None else "partial" if coverage.get("status") != "complete" else "observed",
            "history_coverage": coverage.get("status", "unknown")}


def _event_context(event, timestamp, configurations):
    if not timestamp or not event.model:
        return None, None, None
    candidates = []
    for configuration in configurations.get(event.model, []):
        observed = _parse_time(configuration.get("observed_at"))
        loaded = configuration.get("loaded_context")
        configured = configuration.get("configured_context")
        if (observed and observed <= timestamp and configuration.get("loaded_state") == "loaded"
                and isinstance(loaded, int) and isinstance(configured, int)):
            candidates.append((observed, configuration))
    if not candidates:
        return None, None, None
    _, config = max(candidates, key=lambda pair: pair[0])
    output = config.get("configured_output") if isinstance(config.get("configured_output"), int) else 0
    effective = min(config["loaded_context"], config["configured_context"])
    usable = max(0, effective - output)
    input_tokens = (event.tokens or {}).get("input")
    if not usable or not isinstance(input_tokens, (int, float)):
        return None, effective, usable
    return input_tokens / usable * 100, effective, usable


def _hardware_metrics(samples, coverage, total, truncated):
    fields = {"load": [], "memory_utilization": [], "mem_used": [], "mem_total": [], "power_w": [], "temp": []}
    scopes = Counter()
    for sample in samples:
        scopes[sample["scope"]] += 1
        values = sample["values"]
        for key in fields:
            value = values.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fields[key].append(float(value))
    return {"sample_count": total, "samples_analyzed": len(samples), "truncated": truncated,
            "sampling_scope_counts": dict(scopes),
            "attribution": "device/process observations; not attributed to this session",
            "measurements": {key: _statistics(values, "observed_samples_no_interpolation", coverage)
                             for key, values in fields.items()},
            "sampling_density": "time-bounded samples" if len(samples) > 1 else "sparse_or_unavailable"}


def _sampled_state_metrics(samples, max_gap):
    if len(samples) < 2:
        return {"values": None, "unknown_seconds": None, "sample_pairs": 0,
                "method": "bounded_poll_interval_interpolation", "status": "unavailable",
                "max_interpolation_gap_seconds": max_gap}
    totals: dict[str, float] = defaultdict(float)
    unknown = 0.0
    pairs = 0
    for (left, state, _), (right, _, _) in zip(samples, samples[1:]):
        duration = (right - left).total_seconds()
        if duration <= 0:
            continue
        pairs += 1
        if duration > max_gap:
            unknown += duration
        elif state and state not in {"unknown", "possibly_stalled"}:
            totals[state] += duration
        else:
            unknown += duration
    return {"values": dict(sorted(totals.items())), "unknown_seconds": unknown,
            "sample_pairs": pairs, "method": "bounded_poll_interval_interpolation",
            "status": "observed" if pairs else "unavailable", "max_interpolation_gap_seconds": max_gap,
            "note": "Estimate assigns each short sample interval to its earlier observed state; it is not provider-measured time."}


def _event_end(event: NormalizedEvent, start: datetime | None) -> datetime | None:
    if event.completed_at:
        return _parse_time(event.completed_at)
    if start and event.duration_seconds is not None and event.duration_seconds >= 0:
        return start + timedelta(seconds=event.duration_seconds)
    return None


def _interval_union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float | None:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return None
    total = 0.0
    left, right = ordered[0]
    for start, end in ordered[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += (right - left).total_seconds()
            left, right = start, end
    total += (right - left).total_seconds()
    return total


def _differences(values):
    dated = sorted(value for value in values if value)
    return [(right - left).total_seconds() for left, right in zip(dated, dated[1:])]


def _rate(count, seconds):
    return round(count / seconds * 3600, 3) if seconds and seconds > 0 else None


def _parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _marker(payload, record):
    return {"event_id": payload.get("event_id") or record.get("event_uid"),
            "timestamp": payload.get("timestamp") or record.get("timestamp"),
            "category": payload.get("category") or record.get("category"),
            "subtype": payload.get("subtype") or record.get("subtype"),
            "outcome": payload.get("outcome"), "duration_seconds": payload.get("duration_seconds"),
            "finish_reason": payload.get("finish_reason"), "tokens": payload.get("tokens")}


def _evidence_ref(event):
    return {"event_id": event.event_id, "timestamp": event.timestamp,
            "completed_at": event.completed_at, "outcome": event.outcome,
            "finish_reason": event.finish_reason}


def _downsample_markers(markers, limit):
    maximum = max(1, limit)
    if len(markers) <= maximum:
        return markers
    stride = math.ceil(len(markers) / maximum)
    return markers[::stride][:maximum]
