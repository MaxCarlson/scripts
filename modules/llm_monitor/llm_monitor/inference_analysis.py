"""Pure, testable inference analytics and request-window hardware correlation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .inference_models import HardwareSample, InferenceRequest


def parse_iso_timestamp(timestamp_str: str | None) -> float | None:
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def correlate_request_hardware(
    request: InferenceRequest,
    samples: Sequence[HardwareSample],
    *,
    max_gap_seconds: float = 5.0,
) -> dict[str, Any]:
    """Correlate hardware observations during a request's active lifetime.

    Prefers monotonic timestamps when available, falling back to UTC timestamps.
    Scope: Device-level measurement; concurrent requests may contribute.
    Never manufactures an artificial average for requests with insufficient samples.
    """
    if not samples:
        return {
            "gpu_average_percent": None,
            "gpu_peak_percent": None,
            "gpu_average_vram_bytes": None,
            "gpu_peak_vram_bytes": None,
            "gpu_average_memory_controller_percent": None,
            "gpu_average_power_watts": None,
            "sample_count": 0,
            "covered_duration_seconds": 0.0,
            "coverage_fraction": 0.0,
            "device_id": None,
            "attribution_scope": "device_during_request",
            "is_sparse": True,
        }

    # Determine start and end reference times
    use_monotonic = request.started_monotonic is not None
    if use_monotonic:
        t_start = request.started_monotonic or 0.0
        t_end = request.ended_monotonic if request.ended_monotonic is not None else t_start + (request.elapsed_seconds or 0.0)
    else:
        t_start = parse_iso_timestamp(request.started_at) or 0.0
        t_end = parse_iso_timestamp(request.ended_at) if request.ended_at else (t_start + (request.elapsed_seconds or 0.0))

    duration = max(0.001, t_end - t_start)

    # Filter and extract timestamps per sample
    usable: list[tuple[float, HardwareSample]] = []
    for s in samples:
        t_s = s.timestamp_monotonic if use_monotonic else (parse_iso_timestamp(s.timestamp) or 0.0)
        # Include sample if within window (with 0.5s boundary tolerance)
        if (t_start - 0.5) <= t_s <= (t_end + 0.5):
            usable.append((t_s, s))

    usable.sort(key=lambda item: item[0])

    if not usable:
        return {
            "gpu_average_percent": None,
            "gpu_peak_percent": None,
            "gpu_average_vram_bytes": None,
            "gpu_peak_vram_bytes": None,
            "gpu_average_memory_controller_percent": None,
            "gpu_average_power_watts": None,
            "sample_count": 0,
            "covered_duration_seconds": 0.0,
            "coverage_fraction": 0.0,
            "device_id": samples[-1].device_id if samples else None,
            "attribution_scope": "device_during_request",
            "is_sparse": True,
        }

    primary_device_id = usable[0][1].device_id

    # If only 1 sample is present, it's a point-in-time observation
    if len(usable) == 1:
        s = usable[0][1]
        covered_sec = min(duration, 1.0)
        cov_fraction = min(1.0, covered_sec / duration)
        return {
            "gpu_average_percent": s.gpu_utilization_percent,
            "gpu_peak_percent": s.gpu_utilization_percent,
            "gpu_average_vram_bytes": s.vram_used_bytes,
            "gpu_peak_vram_bytes": s.vram_used_bytes,
            "gpu_average_memory_controller_percent": s.memory_controller_utilization_percent,
            "gpu_average_power_watts": s.power_watts,
            "sample_count": 1,
            "covered_duration_seconds": round(covered_sec, 3),
            "coverage_fraction": round(cov_fraction, 3),
            "device_id": s.device_id,
            "attribution_scope": "device_point_sample",
            "is_sparse": True,
        }

    # Multiple samples: compute time-weighted averages over intervals
    total_weight = 0.0
    weighted_util = 0.0
    weighted_vram = 0.0
    weighted_mem_ctrl = 0.0
    mem_ctrl_weight = 0.0
    weighted_power = 0.0
    power_weight = 0.0

    peak_util: float | None = None
    peak_vram: float | None = None

    for i in range(len(usable)):
        t_i, s_i = usable[i]
        # Update peaks
        if s_i.gpu_utilization_percent is not None:
            peak_util = s_i.gpu_utilization_percent if peak_util is None else max(peak_util, s_i.gpu_utilization_percent)
        if s_i.vram_used_bytes is not None:
            peak_vram = s_i.vram_used_bytes if peak_vram is None else max(peak_vram, s_i.vram_used_bytes)

        # Interval to next sample
        if i < len(usable) - 1:
            t_next = usable[i + 1][0]
            dt = t_next - t_i
            if 0 < dt <= max_gap_seconds:
                # Overlap of [t_i, t_next] with [t_start, t_end]
                overlap_start = max(t_i, t_start)
                overlap_end = min(t_next, t_end)
                weight = max(0.0, overlap_end - overlap_start)
            else:
                weight = 0.0
        else:
            weight = 0.0

        if weight > 0:
            total_weight += weight
            if s_i.gpu_utilization_percent is not None:
                weighted_util += s_i.gpu_utilization_percent * weight
            if s_i.vram_used_bytes is not None:
                weighted_vram += s_i.vram_used_bytes * weight
            if s_i.memory_controller_utilization_percent is not None:
                weighted_mem_ctrl += s_i.memory_controller_utilization_percent * weight
                mem_ctrl_weight += weight
            if s_i.power_watts is not None:
                weighted_power += s_i.power_watts * weight
                power_weight += weight

    # If intervals yielded valid weights, calculate weighted averages
    if total_weight > 0:
        avg_util = weighted_util / total_weight
        avg_vram = weighted_vram / total_weight
        avg_mem_ctrl = (weighted_mem_ctrl / mem_ctrl_weight) if mem_ctrl_weight > 0 else None
        avg_power = (weighted_power / power_weight) if power_weight > 0 else None
        covered_sec = min(duration, total_weight)
        cov_fraction = min(1.0, covered_sec / duration)
    else:
        # Fallback to arithmetic mean of valid samples in window
        valid_utils = [s.gpu_utilization_percent for _, s in usable if s.gpu_utilization_percent is not None]
        avg_util = sum(valid_utils) / len(valid_utils) if valid_utils else None
        valid_vram = [s.vram_used_bytes for _, s in usable if s.vram_used_bytes is not None]
        avg_vram = sum(valid_vram) / len(valid_vram) if valid_vram else None
        valid_ctrl = [s.memory_controller_utilization_percent for _, s in usable if s.memory_controller_utilization_percent is not None]
        avg_mem_ctrl = sum(valid_ctrl) / len(valid_ctrl) if valid_ctrl else None
        valid_pwr = [s.power_watts for _, s in usable if s.power_watts is not None]
        avg_power = sum(valid_pwr) / len(valid_pwr) if valid_pwr else None
        covered_sec = min(duration, len(usable) * 0.8)
        cov_fraction = min(1.0, covered_sec / duration)

    is_sparse = len(usable) < 2 or cov_fraction < 0.5

    return {
        "gpu_average_percent": round(avg_util, 2) if avg_util is not None else None,
        "gpu_peak_percent": round(peak_util, 2) if peak_util is not None else None,
        "gpu_average_vram_bytes": round(avg_vram, 2) if avg_vram is not None else None,
        "gpu_peak_vram_bytes": round(peak_vram, 2) if peak_vram is not None else None,
        "gpu_average_memory_controller_percent": round(avg_mem_ctrl, 2) if avg_mem_ctrl is not None else None,
        "gpu_average_power_watts": round(avg_power, 2) if avg_power is not None else None,
        "sample_count": len(usable),
        "covered_duration_seconds": round(covered_sec, 3),
        "coverage_fraction": round(cov_fraction, 3),
        "device_id": primary_device_id,
        "attribution_scope": "device_during_request",
        "is_sparse": is_sparse,
    }


def compute_model_analytics(
    requests: Sequence[InferenceRequest],
    hardware_samples: Sequence[HardwareSample] = (),
    *,
    server_instance_id: str | None = None,
    model_id: str | None = None,
    time_window_seconds: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute pure statistical aggregates for requests and model performance.

    Does not fabricate zeros for missing metrics.
    denominators and sample counts are explicitly recorded for every aggregate.
    """
    current_time = now if now is not None else datetime.now(timezone.utc).timestamp()

    # Filter candidate requests
    candidates: list[InferenceRequest] = []
    for r in requests:
        if server_instance_id is not None and server_instance_id != "all":
            if r.server_instance_id != server_instance_id:
                continue
        if model_id is not None and model_id != "all":
            match_model = r.provider_model_id == model_id or r.model_instance_id == model_id or r.model_name == model_id
            if not match_model:
                continue
        if time_window_seconds is not None and time_window_seconds > 0:
            started_ts = parse_iso_timestamp(r.started_at)
            if started_ts is not None and (current_time - started_ts) > time_window_seconds:
                continue
        candidates.append(r)

    total_candidates = len(candidates)
    active_count = sum(1 for r in candidates if r.state in {"active", "generating", "running", "queued"})
    completed_requests = [r for r in candidates if r.state in {"completed", "complete"}]
    completed_count = len(completed_requests)
    failed_count = sum(1 for r in candidates if r.state == "failed")
    cancelled_count = sum(1 for r in candidates if r.state in {"cancelled", "canceled"})

    # Token accounting over completed requests with provider-reported counts
    input_tokens_vals = [r.input_tokens for r in completed_requests if r.input_tokens is not None]
    reasoning_tokens_vals = [r.reasoning_tokens for r in completed_requests if r.reasoning_tokens is not None]
    output_tokens_vals = [r.output_tokens for r in completed_requests if r.output_tokens is not None]
    generated_tokens_vals = [r.generated_tokens for r in completed_requests if r.generated_tokens is not None]

    tokens_measured_count = sum(1 for r in completed_requests if r.input_tokens is not None or r.generated_tokens is not None)

    # Durations over completed requests
    durations = [r.elapsed_seconds for r in completed_requests if r.elapsed_seconds is not None and r.elapsed_seconds >= 0]
    ttft_vals = [r.time_to_first_text_seconds for r in completed_requests if r.time_to_first_text_seconds is not None and r.time_to_first_text_seconds >= 0]
    tps_vals = [r.generation_tokens_per_second for r in completed_requests if r.generation_tokens_per_second is not None and r.generation_tokens_per_second >= 0]

    # Hardware over completed requests
    gpu_utils = [r.gpu_average_percent for r in completed_requests if r.gpu_average_percent is not None]
    gpu_peaks = [r.gpu_peak_vram_bytes for r in completed_requests if r.gpu_peak_vram_bytes is not None]
    hw_cov_count = len(gpu_utils)

    return {
        "request_counts": {
            "observed_requests": total_candidates,
            "active_requests": active_count,
            "completed_requests": completed_count,
            "failed_requests": failed_count,
            "cancelled_requests": cancelled_count,
            "token_measured_requests": tokens_measured_count,
            "hardware_covered_requests": hw_cov_count,
        },
        "tokens": {
            "input_tokens": _metric_summary(input_tokens_vals, unit="tokens", source="provider_reported"),
            "reasoning_tokens": _metric_summary(reasoning_tokens_vals, unit="tokens", source="provider_reported"),
            "output_tokens": _metric_summary(output_tokens_vals, unit="tokens", source="provider_reported"),
            "generated_tokens": _metric_summary(generated_tokens_vals, unit="tokens", source="provider_reported"),
        },
        "timing": {
            "duration_seconds": _timing_summary(durations, unit="seconds", source="observed_lifecycle"),
            "time_to_first_text_seconds": _metric_summary(ttft_vals, unit="seconds", source="gateway_observed"),
            "generation_tokens_per_second": _metric_summary(tps_vals, unit="tok/s", source="end_to_end_approx"),
        },
        "hardware": {
            "gpu_average_percent": _metric_summary(gpu_utils, unit="%", source="device_during_request"),
            "gpu_peak_vram_bytes": {
                "max": max(gpu_peaks) if gpu_peaks else None,
                "sample_count": len(gpu_peaks),
                "unit": "bytes",
                "source": "device_during_request",
            },
        },
    }


def _metric_summary(values: list[float | int], *, unit: str, source: str) -> dict[str, Any]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "total": None,
            "sample_count": 0,
            "unit": unit,
            "source": source,
        }
    val_float = [float(v) for v in values]
    val_float.sort()
    mean_val = sum(val_float) / len(val_float)
    n = len(val_float)
    if n % 2 == 1:
        median_val = val_float[n // 2]
    else:
        median_val = (val_float[n // 2 - 1] + val_float[n // 2]) / 2.0

    total_val = sum(values) if unit == "tokens" else None

    return {
        "mean": round(mean_val, 2),
        "median": round(median_val, 2),
        "total": total_val,
        "sample_count": n,
        "unit": unit,
        "source": source,
    }


def _timing_summary(values: list[float], *, unit: str, source: str) -> dict[str, Any]:
    summary = _metric_summary(values, unit=unit, source=source)
    if not values:
        summary["p90"] = None
        summary["p95"] = None
        return summary

    vals = sorted(values)
    n = len(vals)
    # p90 requires at least 5 samples, p95 at least 10 samples
    if n >= 5:
        summary["p90"] = round(_percentile(vals, 90), 2)
    else:
        summary["p90"] = None

    if n >= 10:
        summary["p95"] = round(_percentile(vals, 95), 2)
    else:
        summary["p95"] = None

    return summary


def _percentile(sorted_vals: list[float], percent: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    rank = (percent / 100.0) * (n - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_vals[low]
    weight = rank - low
    return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight
