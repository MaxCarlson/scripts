"""
Adapter bridging generic benchmark data structures to interactive report models.

Converts ExperimentComparison and TrialResult collections from benchmark_core or domain runners
into self-contained ReportData instances without hard static dependencies.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from .charts import build_efficiency_points
from .divergence import build_task_divergence_matrix
from .models import (
    ReportData,
    TrialDetail,
    VariantReportRow,
)


def _get_metric_val(metric_obj: Any) -> Optional[float]:
    """Extract float value from a MetricValue or number or dict."""
    if metric_obj is None:
        return None
    if isinstance(metric_obj, (int, float)):
        return float(metric_obj)
    if hasattr(metric_obj, "value"):
        v = metric_obj.value
        return float(v) if v is not None else None
    if isinstance(metric_obj, dict):
        v = metric_obj.get("value")
        return float(v) if v is not None else None
    return None


def convert_trial_to_detail(
    t: Any,
    evidence_resolver: Optional[Callable[[str], dict[str, Any]]] = None,
) -> TrialDetail:
    """Convert a generic TrialResult or dictionary to a TrialDetail record."""
    # Attribute or dict access
    trial_id = getattr(t, "trial_id", None) or (t.get("trial_id") if isinstance(t, dict) else str(t))
    variant_id = getattr(t, "variant_id", None) or (t.get("variant_id") if isinstance(t, dict) else "")
    task_id = getattr(t, "task_id", None) or (t.get("task_id") if isinstance(t, dict) else "")

    status_raw = getattr(t, "status", None) or (t.get("status") if isinstance(t, dict) else "unscored")
    status = getattr(status_raw, "value", str(status_raw)).lower()

    duration_ms = float(getattr(t, "duration_ms", 0.0) or (t.get("duration_ms", 0.0) if isinstance(t, dict) else 0.0))
    error_message = getattr(t, "error_message", None) or (t.get("error_message") if isinstance(t, dict) else None)

    metrics_raw = getattr(t, "metrics", {}) or (t.get("metrics", {}) if isinstance(t, dict) else {})
    details_raw = getattr(t, "details", {}) or (t.get("details", {}) if isinstance(t, dict) else {})
    artifacts_raw = getattr(t, "artifacts", {}) or (t.get("artifacts", {}) if isinstance(t, dict) else {})
    if isinstance(details_raw, dict) and "artifacts" in details_raw:
        artifacts_raw = {**artifacts_raw, **details_raw["artifacts"]}
    metadata_raw = getattr(t, "metadata", {}) or (t.get("metadata", {}) if isinstance(t, dict) else {})

    # Extract duration from metrics if not directly on object
    if duration_ms == 0.0:
        dur_metric = _get_metric_val(metrics_raw.get("duration.wall_ms") or metrics_raw.get("duration_ms"))
        if dur_metric is not None:
            duration_ms = float(dur_metric)

    # Extract tokens
    inp_tok = _get_metric_val(metrics_raw.get("tokens.worker.input") or metrics_raw.get("input_tokens"))
    out_tok = _get_metric_val(metrics_raw.get("tokens.worker.output") or metrics_raw.get("output_tokens"))
    rea_tok = _get_metric_val(metrics_raw.get("tokens.worker.reasoning") or metrics_raw.get("reasoning_tokens"))
    tot_tok = _get_metric_val(metrics_raw.get("tokens.worker.total") or metrics_raw.get("total_tokens"))
    peak_ctx = _get_metric_val(metrics_raw.get("tokens.worker.peak_context") or metrics_raw.get("peak_context"))

    tp = _get_metric_val(metrics_raw.get("tokens.throughput_tok_per_s") or metrics_raw.get("throughput"))
    if tp is None and duration_ms > 0 and out_tok:
        tp = round(out_tok / (duration_ms / 1000.0), 2)

    share = _get_metric_val(metrics_raw.get("tokens.reasoning_share") or metrics_raw.get("reasoning_token_share"))
    if share is None and out_tok and rea_tok is not None:
        share = round(rea_tok / out_tok, 4)

    # Scope & Uncertain Ops
    scope_val = _get_metric_val(metrics_raw.get("audit.scope_compliance") or metrics_raw.get("scope_compliance"))
    scope_comp = (scope_val == 1.0) if scope_val is not None else None

    unc_val = _get_metric_val(metrics_raw.get("audit.uncertain_operations") or metrics_raw.get("uncertain_operations"))
    unc_ops = (unc_val == 1.0) if unc_val is not None else None

    # Verifier & Diff Evidence
    verifier_out = artifacts_raw.get("verifier_output") or metadata_raw.get("verifier_output")
    diff_content = artifacts_raw.get("patch_diff") or artifacts_raw.get("diff") or metadata_raw.get("diff")

    if evidence_resolver:
        extra_ev = evidence_resolver(str(trial_id))
        if extra_ev:
            verifier_out = verifier_out or extra_ev.get("verifier_output")
            diff_content = diff_content or extra_ev.get("diff")
            error_message = error_message or extra_ev.get("error_message")

    return TrialDetail(
        trial_id=str(trial_id),
        variant_id=str(variant_id),
        task_id=str(task_id),
        status=status,
        duration_ms=duration_ms,
        input_tokens=int(inp_tok) if inp_tok is not None else None,
        output_tokens=int(out_tok) if out_tok is not None else None,
        reasoning_tokens=int(rea_tok) if rea_tok is not None else None,
        total_tokens=int(tot_tok) if tot_tok is not None else None,
        peak_context_tokens=int(peak_ctx) if peak_ctx is not None else None,
        reasoning_token_share=share,
        throughput_tok_per_s=tp,
        scope_compliance=scope_comp,
        uncertain_operations=unc_ops,
        verifier_output=verifier_out,
        diff=diff_content,
        error_message=error_message,
        metrics={k: _get_metric_val(v) for k, v in metrics_raw.items()},
        metadata=dict(metadata_raw),
    )


def from_experiment_comparison(
    comparison: Any,
    trials: Sequence[Any] = (),
    task_categories: Optional[Mapping[str, str]] = None,
    evidence_resolver: Optional[Callable[[str], dict[str, Any]]] = None,
) -> ReportData:
    """
    Construct a ReportData instance from an ExperimentComparison and collection of trials.

    Enforces:
    1. Separation of canonical eligible variants from reference variants.
    2. Preserves failed + timed_out trials in scored denominator.
    3. Calculates Wilson 95% confidence intervals and throughput aggregates.
    """
    # Extract config
    cfg = getattr(comparison, "config", None)
    exp_id = getattr(comparison, "experiment_id", "") or "EXP"
    suite_id = getattr(cfg, "suite_id", "") if cfg else ""
    suite_version = getattr(cfg, "suite_version", "") if cfg else ""
    budget = getattr(cfg, "budget_profile", "") if cfg else ""
    basis = getattr(cfg, "scoring_basis", "") if cfg else ""
    created = getattr(cfg, "created_at", "") if cfg else ""

    # Convert trials
    detail_map: dict[str, TrialDetail] = {}
    trial_details: list[TrialDetail] = []
    for t in trials:
        td = convert_trial_to_detail(t, evidence_resolver=evidence_resolver)
        detail_map[td.trial_id] = td
        trial_details.append(td)

    # Process variants
    eligible_raw = getattr(comparison, "eligible_variants", {})
    reference_raw = getattr(comparison, "reference_variants", {})
    canonical_rankings = list(getattr(comparison, "canonical_rankings", []))

    variant_rows: list[VariantReportRow] = []

    def _build_variant_row(vid: str, vm: Any, is_eligible: bool, rank: Optional[int]) -> VariantReportRow:
        strict_rate = getattr(vm, "strict_acceptance_rate", None)
        ci = getattr(vm, "confidence_interval_95", None)
        ci_lower = getattr(ci, "lower", None) if ci else None
        ci_upper = getattr(ci, "upper", None) if ci else None

        dur = getattr(vm, "duration", None)
        dur_all = getattr(dur, "all_scored", None) if dur else None
        dur_mean = getattr(dur_all, "mean", None) if dur_all else None
        dur_med = getattr(dur_all, "median", None) if dur_all else None

        # Metrics
        vm_metrics = getattr(vm, "metrics", {})
        tp_stat = vm_metrics.get("tokens.throughput_tok_per_s") or vm_metrics.get("throughput")
        tp_mean = getattr(tp_stat, "mean", None) if tp_stat else None

        tok_task_stat = vm_metrics.get("tokens.per_successful_task")
        tok_task = getattr(tok_task_stat, "mean", None) if tok_task_stat else None

        share_stat = vm_metrics.get("tokens.reasoning_share") or vm_metrics.get("reasoning_token_share")
        share_mean = getattr(share_stat, "mean", None) if share_stat else None

        # If throughput was not in aggregated metrics, calculate from trials
        v_trials = [t for t in trial_details if t.variant_id == vid]
        if tp_mean is None and v_trials:
            tps = [t.throughput_tok_per_s for t in v_trials if t.throughput_tok_per_s is not None]
            tp_mean = round(sum(tps) / len(tps), 1) if tps else None

        if share_mean is None and v_trials:
            shares = [t.reasoning_token_share for t in v_trials if t.reasoning_token_share is not None]
            share_mean = round(sum(shares) / len(shares), 4) if shares else None

        return VariantReportRow(
            variant_id=vid,
            is_eligible=is_eligible,
            rank=rank,
            exclusion_reasons=list(getattr(vm, "exclusion_reasons", [])),
            total_trials=int(getattr(vm, "total_trials", len(v_trials))),
            passed=int(getattr(vm, "passed", 0)),
            failed=int(getattr(vm, "failed", 0)),
            timed_out=int(getattr(vm, "timed_out", 0)),
            infrastructure_error=int(getattr(vm, "infrastructure_error", 0)),
            unscored=int(getattr(vm, "unscored", 0)),
            scored_denominator=int(getattr(vm, "scored_denominator", 0)),
            strict_acceptance_rate=strict_rate,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            duration_mean_ms=dur_mean,
            duration_median_ms=dur_med,
            throughput_tok_per_s=tp_mean,
            tokens_per_successful_task=tok_task,
            reasoning_token_share=share_mean,
        )

    # 1. Eligible variants in rank order
    for rank, vid in enumerate(canonical_rankings, start=1):
        if vid in eligible_raw:
            variant_rows.append(_build_variant_row(vid, eligible_raw[vid], is_eligible=True, rank=rank))

    # Add any remaining eligible variants not in rankings
    for vid, vm in sorted(eligible_raw.items()):
        if vid not in canonical_rankings:
            variant_rows.append(_build_variant_row(vid, vm, is_eligible=True, rank=None))

    # 2. Reference variants
    for vid, vm in sorted(reference_raw.items()):
        variant_rows.append(_build_variant_row(vid, vm, is_eligible=False, rank=None))

    # Divergence matrix
    divergence = build_task_divergence_matrix(
        trial_details,
        task_categories=task_categories,
        ordered_variant_ids=[v.variant_id for v in variant_rows],
    )

    # Efficiency scatterplot points
    points = build_efficiency_points(trial_details)

    warnings = list(getattr(comparison, "warnings", []))

    return ReportData(
        experiment_id=exp_id,
        title=f"Benchmark Experiment: {exp_id}",
        suite_id=suite_id,
        suite_version=suite_version,
        budget_profile=budget,
        scoring_basis=basis,
        created_at=created,
        variants=variant_rows,
        divergence_matrix=divergence,
        efficiency_points=points,
        trials=detail_map,
        warnings=warnings,
    )
