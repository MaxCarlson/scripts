"""
Comparison utilities for benchmark runs and variants.

Calculates absolute and percentage deltas, highlights improvements and regressions,
and provides explicit warnings when scoring bases, suite versions, or units mismatch.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
import json
from typing import Any, Optional, Sequence

from .conditions import contract_error, contract_key
from .models import ExperimentConfig, MetricValue, RunInfo, TrialResult, TrialStatus
from .stats import (
    BenchmarkSummary,
    DurationStats,
    MetricStats,
    ScoreConfidenceInterval,
    TaskSummary,
    VariantSummary,
    compute_duration_stats,
    compute_metric_stats,
    compute_wilson_score_interval,
    summarize_task,
)


@dataclass(frozen=True, slots=True)
class DeltaValue:
    """Calculated absolute and percentage change between baseline and candidate values."""

    baseline: Optional[float]
    candidate: Optional[float]
    absolute_change: Optional[float]
    percentage_change: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
        }


def compute_delta(
    baseline: Optional[float],
    candidate: Optional[float],
    precision: int = 4,
) -> DeltaValue:
    """Compute absolute and percentage delta between two numbers."""
    if baseline is None or candidate is None:
        return DeltaValue(baseline, candidate, None, None)

    diff = round(candidate - baseline, precision)
    pct: Optional[float] = None
    if baseline != 0.0:
        pct = round((diff / abs(baseline)) * 100.0, 2)

    return DeltaValue(baseline, candidate, diff, pct)


@dataclass(frozen=True, slots=True)
class VariantComparison:
    """Comparison between a candidate variant and a baseline variant."""

    variant_id: str
    baseline_variant_id: str
    micro_success_rate: DeltaValue
    macro_success_rate: DeltaValue
    duration_all_scored_mean: DeltaValue
    duration_successful_mean: DeltaValue
    metrics: dict[str, DeltaValue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "baseline_variant_id": self.baseline_variant_id,
            "micro_success_rate": self.micro_success_rate.to_dict(),
            "macro_success_rate": self.macro_success_rate.to_dict(),
            "duration_all_scored_mean": self.duration_all_scored_mean.to_dict(),
            "duration_successful_mean": self.duration_successful_mean.to_dict(),
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
        }


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Comparison results between two benchmark runs."""

    baseline_run_id: str
    candidate_run_id: str
    warnings: list[str]
    variant_comparisons: dict[str, VariantComparison]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "warnings": list(self.warnings),
            "variant_comparisons": {k: v.to_dict() for k, v in sorted(self.variant_comparisons.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def compare_variants(
    baseline_var: VariantSummary,
    candidate_var: VariantSummary,
    suppress_success_deltas: bool = False,
) -> VariantComparison:
    """Compare two VariantSummary instances."""
    if suppress_success_deltas:
        micro_delta = DeltaValue(baseline_var.micro_success_rate, candidate_var.micro_success_rate, None, None)
        macro_delta = DeltaValue(baseline_var.macro_success_rate, candidate_var.macro_success_rate, None, None)
    else:
        micro_delta = compute_delta(baseline_var.micro_success_rate, candidate_var.micro_success_rate)
        macro_delta = compute_delta(baseline_var.macro_success_rate, candidate_var.macro_success_rate)

    b_all_dur = baseline_var.duration.all_scored.mean if baseline_var.duration.all_scored else None
    c_all_dur = candidate_var.duration.all_scored.mean if candidate_var.duration.all_scored else None
    dur_all_delta = compute_delta(b_all_dur, c_all_dur)

    b_succ_dur = baseline_var.duration.successful_only.mean if baseline_var.duration.successful_only else None
    c_succ_dur = candidate_var.duration.successful_only.mean if candidate_var.duration.successful_only else None
    dur_succ_delta = compute_delta(b_succ_dur, c_succ_dur)

    shared_metrics = set(baseline_var.metrics.keys()).union(candidate_var.metrics.keys())
    metric_deltas: dict[str, DeltaValue] = {}
    for mk in sorted(shared_metrics):
        b_m = baseline_var.metrics.get(mk)
        c_m = candidate_var.metrics.get(mk)
        b_val = b_m.mean if b_m else None
        c_val = c_m.mean if c_m else None
        if b_m and c_m and b_m.unit != c_m.unit:
            metric_deltas[mk] = DeltaValue(b_val, c_val, None, None)
        else:
            metric_deltas[mk] = compute_delta(b_val, c_val)

    return VariantComparison(
        variant_id=candidate_var.variant_id,
        baseline_variant_id=baseline_var.variant_id,
        micro_success_rate=micro_delta,
        macro_success_rate=macro_delta,
        duration_all_scored_mean=dur_all_delta,
        duration_successful_mean=dur_succ_delta,
        metrics=metric_deltas,
    )


def compare_runs(
    baseline: BenchmarkSummary,
    candidate: BenchmarkSummary,
) -> RunComparison:
    """
    Compare two benchmark runs, validating scoring bases and suite configurations.

    Identifies:
    - Critical warning if scoring_basis differs
    - Notice if suite_version or suite_id differs
    - Variant-by-variant capability and metric differences
    """
    warnings: list[str] = []

    # Scoring basis verification
    scoring_basis_mismatch = (baseline.run_info.scoring_basis != candidate.run_info.scoring_basis)
    if scoring_basis_mismatch:
        warnings.append(
            f"CRITICAL: Scoring basis mismatch! Baseline uses '{baseline.run_info.scoring_basis}', "
            f"while candidate uses '{candidate.run_info.scoring_basis}'. Comparing success rates directly is invalid."
        )

    # Suite ID verification
    if baseline.run_info.suite_id != candidate.run_info.suite_id:
        warnings.append(
            f"WARNING: Suite ID mismatch! Baseline is '{baseline.run_info.suite_id}', "
            f"while candidate is '{candidate.run_info.suite_id}'."
        )

    # Suite fingerprint verification
    base_fp = baseline.run_info.metadata.get("suite_fingerprint")
    cand_fp = candidate.run_info.metadata.get("suite_fingerprint")
    if base_fp and cand_fp and base_fp != cand_fp:
        warnings.append(
            f"CRITICAL: Suite fingerprint mismatch! Baseline is '{base_fp}', while candidate is '{cand_fp}'. "
            "Benchmark tasks or suite contents may differ."
        )

    # Suite version verification
    if baseline.run_info.suite_version != candidate.run_info.suite_version:
        warnings.append(
            f"NOTICE: Suite version difference: v{baseline.run_info.suite_version} (baseline) "
            f"vs v{candidate.run_info.suite_version} (candidate)."
        )

    baseline_contract = baseline.run_info.metadata.get("comparison_contract")
    candidate_contract = candidate.run_info.metadata.get("comparison_contract")
    condition_mismatch = (contract_error(baseline_contract) is not None
                          or contract_error(candidate_contract) is not None
                          or baseline_contract != candidate_contract)
    if condition_mismatch:
        warnings.append("CRITICAL: Comparison conditions differ or are not established; numerical deltas suppressed.")
    # Match variants
    variant_comps: dict[str, VariantComparison] = {}
    for vid, cand_var in candidate.variants.items():
        base_var: Optional[VariantSummary] = None
        if vid in baseline.variants:
            base_var = baseline.variants[vid]
        elif len(baseline.variants) == 1:
            # Single variant baseline comparison
            base_var = next(iter(baseline.variants.values()))
        else:
            warnings.append(f"Notice: Candidate variant '{vid}' has no direct matching baseline variant.")

        if base_var:
            # Check unit mismatches on shared metrics
            for mk, b_m in base_var.metrics.items():
                c_m = cand_var.metrics.get(mk)
                if c_m and b_m.unit != c_m.unit:
                    warnings.append(
                        f"WARNING: Unit mismatch for metric '{mk}' on variant '{vid}': "
                        f"baseline uses '{b_m.unit}', candidate uses '{c_m.unit}'."
                    )
            variant_comps[vid] = compare_variants(
                base_var,
                cand_var,
                suppress_success_deltas=scoring_basis_mismatch or condition_mismatch,
            )

    if condition_mismatch:
        for key, value in list(variant_comps.items()):
            variant_comps[key] = replace(value,
                duration_all_scored_mean=DeltaValue(value.duration_all_scored_mean.baseline, value.duration_all_scored_mean.candidate, None, None),
                duration_successful_mean=DeltaValue(value.duration_successful_mean.baseline, value.duration_successful_mean.candidate, None, None),
                metrics={name: DeltaValue(delta.baseline, delta.candidate, None, None) for name, delta in value.metrics.items()})
    return RunComparison(
        baseline_run_id=baseline.run_info.run_id,
        candidate_run_id=candidate.run_info.run_id,
        warnings=warnings,
        variant_comparisons=variant_comps,
    )


def render_comparison_md(comparison: RunComparison) -> str:
    """Render comparison results as readable Markdown."""
    lines: list[str] = [
        f"# Benchmark Comparison: `{comparison.candidate_run_id}` vs `{comparison.baseline_run_id}`",
        "",
        f"- **Baseline Run:** `{comparison.baseline_run_id}`",
        f"- **Candidate Run:** `{comparison.candidate_run_id}`",
        "",
    ]

    if comparison.warnings:
        lines.append("## Warnings & Incompatibilities")
        lines.append("")
        for w in comparison.warnings:
            lines.append(f"> [!WARNING] {w}" if "CRITICAL" in w or "WARNING" in w else f"- {w}")
        lines.append("")

    lines.append("## Variant Comparison Summary")
    lines.append("")
    lines.append("| Variant | Micro Success Rate (Base -> Cand) | Delta (%) | Macro Success Rate (Base -> Cand) | Delta (%) | Mean Duration (Base -> Cand) | Delta (%) |")
    lines.append("|---|---|---|---|---|---|---|")

    def _fmt_delta(dv: DeltaValue, is_rate: bool = False, unit: str = "") -> tuple[str, str]:
        if dv.baseline is None and dv.candidate is None:
            return "N/A", "N/A"

        if is_rate:
            b_s = f"{dv.baseline * 100:.1f}%" if dv.baseline is not None else "N/A"
            c_s = f"{dv.candidate * 100:.1f}%" if dv.candidate is not None else "N/A"
        else:
            b_s = f"{dv.baseline:.1f} {unit}".strip() if dv.baseline is not None else "N/A"
            c_s = f"{dv.candidate:.1f} {unit}".strip() if dv.candidate is not None else "N/A"

        vals = f"{b_s} -> {c_s}"

        if dv.absolute_change is None:
            diff = "N/A"
        elif is_rate:
            diff = f"{dv.absolute_change * 100:+.1f}%"
        else:
            pct_s = f" ({dv.percentage_change:+.1f}%)" if dv.percentage_change is not None else ""
            diff = f"{dv.absolute_change:+.1f} {unit}{pct_s}".strip()

        return vals, diff

    for vid, vc in sorted(comparison.variant_comparisons.items()):
        micro_vals, micro_diff = _fmt_delta(vc.micro_success_rate, is_rate=True)
        macro_vals, macro_diff = _fmt_delta(vc.macro_success_rate, is_rate=True)
        dur_vals, dur_diff = _fmt_delta(vc.duration_successful_mean, is_rate=False, unit="ms")

        lines.append(f"| `{vid}` | {micro_vals} | {micro_diff} | {macro_vals} | {macro_diff} | {dur_vals} | {dur_diff} |")

    lines.append("")

    # Resource & Metric Differences (if custom metrics exist)
    all_custom_metric_keys: set[str] = set()
    for vc in comparison.variant_comparisons.values():
        for mk in vc.metrics.keys():
            if mk != "duration.wall_ms":
                all_custom_metric_keys.add(mk)

    if all_custom_metric_keys:
        lines.append("## Resource & Metric Differences")
        lines.append("")
        lines.append("| Variant | Metric | Mean (Base -> Cand) | Delta (%) |")
        lines.append("|---|---|---|---|")
        for vid, vc in sorted(comparison.variant_comparisons.items()):
            for mk in sorted(all_custom_metric_keys):
                if mk in vc.metrics:
                    m_delta = vc.metrics[mk]
                    m_vals, m_diff = _fmt_delta(m_delta, is_rate=False)
                    lines.append(f"| `{vid}` | `{mk}` | {m_vals} | {m_diff} |")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Multi-Run Experiment Aggregation & Eligibility Enforcement
# =============================================================================


@dataclass(frozen=True, slots=True)
class RunCompatibilityCheck:
    """Outcome of validating a constituent run against an experiment specification."""

    run_id: str
    is_compatible: bool
    is_eligible: bool
    rejection_reasons: list[str]
    ineligibility_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "is_compatible": self.is_compatible,
            "is_eligible": self.is_eligible,
            "rejection_reasons": list(self.rejection_reasons),
            "ineligibility_reasons": list(self.ineligibility_reasons),
        }


def check_run_compatibility(
    run_info: RunInfo,
    config: ExperimentConfig,
) -> RunCompatibilityCheck:
    """
    Validate a single RunInfo against target ExperimentConfig.

    Checks:
    - Compatibility (hard reject if false):
      * Suite ID must match
      * Suite version must match
      * Scoring basis must match
      * Evaluated tasks must overlap with experiment planned tasks
    - Eligibility (reference-only if false):
      * Run's metadata comparison_eligible flag (default True)
      * Budget profile match against config.budget_profile
    """
    rejections: list[str] = []
    ineligibilities: list[str] = []

    if run_info.suite_id != config.suite_id:
        rejections.append(
            f"Suite ID mismatch: run has '{run_info.suite_id}', expected '{config.suite_id}'"
        )

    if run_info.suite_version != config.suite_version:
        rejections.append(
            f"Suite version mismatch: run has '{run_info.suite_version}', expected '{config.suite_version}'"
        )

    if run_info.scoring_basis != config.scoring_basis:
        rejections.append(
            f"Scoring basis mismatch: run has '{run_info.scoring_basis}', expected '{config.scoring_basis}'"
        )

    common_tasks = set(run_info.task_ids).intersection(config.task_ids)
    if not common_tasks:
        rejections.append(
            f"No overlapping tasks: run tasks {sorted(run_info.task_ids)} do not intersect experiment tasks {sorted(config.task_ids)}"
        )

    expected_contract = config.metadata.get("comparison_contract")
    actual_contract = run_info.metadata.get("comparison_contract")
    errors = [error for error in (contract_error(expected_contract), contract_error(actual_contract)) if error]
    if errors:
        rejections.extend(sorted(set(errors)))
    elif expected_contract != actual_contract:
        differing = sorted(key for key in set(expected_contract) | set(actual_contract)
                           if expected_contract.get(key) != actual_contract.get(key))
        rejections.append("Comparison conditions mismatch: " + ", ".join(differing))
    if isinstance(actual_contract, dict) and not contract_error(actual_contract):
        if set(actual_contract["tasks"]) != set(run_info.task_ids):
            rejections.append("Run task set does not match its comparison contract")
        if actual_contract["budget"]["profile"] != run_info.metadata.get("budget_profile"):
            rejections.append("Run budget does not match its comparison contract")
    is_compatible = len(rejections) == 0

    run_meta = run_info.metadata or {}
    explicit_eligible = run_meta.get("comparison_eligible", True)
    if not explicit_eligible:
        reason = run_meta.get(
            "exclusion_reason", "Run metadata explicitly flagged comparison_eligible=False"
        )
        ineligibilities.append(str(reason))

    run_budget = run_meta.get("budget_profile") or run_info.environment.get("budget_profile")
    if run_budget and config.budget_profile and run_budget != config.budget_profile:
        ineligibilities.append(
            f"Budget profile mismatch: run used '{run_budget}', expected '{config.budget_profile}'"
        )

    is_eligible = is_compatible and len(ineligibilities) == 0

    return RunCompatibilityCheck(
        run_id=run_info.run_id,
        is_compatible=is_compatible,
        is_eligible=is_eligible,
        rejection_reasons=rejections,
        ineligibility_reasons=ineligibilities,
    )


@dataclass(frozen=True, slots=True)
class AggregatedVariantMetrics:
    """Aggregated results for one variant across constituent runs in an experiment."""

    variant_id: str
    is_eligible: bool
    exclusion_reasons: list[str]
    total_trials: int
    passed: int
    failed: int
    timed_out: int
    infrastructure_error: int
    unscored: int
    scored_denominator: int  # passed + failed + timed_out
    strict_acceptance_rate: Optional[float]  # passed / scored_denominator
    confidence_interval_95: Optional[ScoreConfidenceInterval]
    task_summaries: dict[str, TaskSummary]
    metrics: dict[str, MetricStats]
    duration: DurationStats
    constituent_run_ids: list[str]
    diagnostic_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "is_eligible": self.is_eligible,
            "exclusion_reasons": list(self.exclusion_reasons),
            "total_trials": self.total_trials,
            "passed": self.passed,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
            "unscored": self.unscored,
            "scored_denominator": self.scored_denominator,
            "strict_acceptance_rate": self.strict_acceptance_rate,
            "confidence_interval_95": (
                self.confidence_interval_95.to_dict() if self.confidence_interval_95 else None
            ),
            "task_summaries": {k: v.to_dict() for k, v in sorted(self.task_summaries.items())},
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
            "duration": self.duration.to_dict(),
            "constituent_run_ids": list(self.constituent_run_ids),
            "diagnostic_reasons": list(self.diagnostic_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AggregatedVariantMetrics:
        ci_data = data.get("confidence_interval_95")
        ci = ScoreConfidenceInterval.from_dict(ci_data) if ci_data else None
        return cls(
            variant_id=data["variant_id"],
            is_eligible=data["is_eligible"],
            exclusion_reasons=data.get("exclusion_reasons", []),
            total_trials=data["total_trials"],
            passed=data["passed"],
            failed=data["failed"],
            timed_out=data["timed_out"],
            infrastructure_error=data["infrastructure_error"],
            unscored=data["unscored"],
            scored_denominator=data["scored_denominator"],
            strict_acceptance_rate=data.get("strict_acceptance_rate"),
            confidence_interval_95=ci,
            task_summaries={
                k: TaskSummary.from_dict(v) for k, v in data.get("task_summaries", {}).items()
            },
            metrics={k: MetricStats.from_dict(v) for k, v in data.get("metrics", {}).items()},
            duration=DurationStats.from_dict(data["duration"]),
            constituent_run_ids=data.get("constituent_run_ids", []),
            diagnostic_reasons=data.get("diagnostic_reasons", []),
        )


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    """Comprehensive multi-run, multi-variant comparison outcome."""

    experiment_id: str
    config: ExperimentConfig
    eligible_variants: dict[str, AggregatedVariantMetrics]
    reference_variants: dict[str, AggregatedVariantMetrics]
    incompatible_runs: list[dict[str, Any]]
    canonical_rankings: list[str]  # Only eligible variants, sorted by strict acceptance descending
    warnings: list[str]
    condition_groups: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def unranked_variants(self) -> dict[str, AggregatedVariantMetrics]:
        return {k: v for k, v in self.eligible_variants.items()
                if v.scored_denominator == 0 or v.strict_acceptance_rate is None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "config": self.config.to_dict(),
            "eligible_variants": {k: v.to_dict() for k, v in sorted(self.eligible_variants.items())},
            "reference_variants": {k: v.to_dict() for k, v in sorted(self.reference_variants.items())},
            "incompatible_runs": copy.deepcopy(self.incompatible_runs),
            "canonical_rankings": list(self.canonical_rankings),
            "unranked_variants": {k: v.to_dict() for k, v in sorted(self.unranked_variants.items())},
            "condition_groups": copy.deepcopy(self.condition_groups),
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentComparison:
        return cls(
            experiment_id=data["experiment_id"],
            config=ExperimentConfig.from_dict(data["config"]),
            eligible_variants={
                k: AggregatedVariantMetrics.from_dict(v)
                for k, v in data.get("eligible_variants", {}).items()
            },
            reference_variants={
                k: AggregatedVariantMetrics.from_dict(v)
                for k, v in data.get("reference_variants", {}).items()
            },
            incompatible_runs=data.get("incompatible_runs", []),
            canonical_rankings=[k for k in data.get("canonical_rankings", [])
                                if data.get("eligible_variants", {}).get(k, {}).get("scored_denominator", 0) > 0
                                and data["eligible_variants"][k].get("strict_acceptance_rate") is not None],
            warnings=data.get("warnings", []),
            condition_groups=data.get("condition_groups", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> ExperimentComparison:
        return cls.from_dict(json.loads(json_str))


def aggregate_experiment(
    config: ExperimentConfig,
    runs: Sequence[tuple[RunInfo, Sequence[TrialResult]]],
    *, _separate_conditions: bool = True,
) -> ExperimentComparison:
    """
    Aggregate multiple benchmark runs into an ExperimentComparison.

    Enforces:
    1. Compatibility check: Mismatched suite_id, suite_version, or scoring_basis
       causes run rejection into `incompatible_runs`.
    2. Eligibility segregation: Runs flagged comparison_eligible=False or with mismatched
       budget_profile are segregated into `reference_variants`. They NEVER enter
       `eligible_variants` or `canonical_rankings`.
    3. Scored denominator: trials with status in (passed, failed, timed_out) form
       the denominator. Infrastructure errors and unscored trials do NOT increment
       scored_denominator and are isolated in diagnostic counts.
    4. Wilson 95% score confidence interval calculated on scored denominator.
    5. Canonical rankings: sorted strictly by (strict_acceptance_rate DESC, duration ASC)
       among eligible variants only.
    """
    eligible_variant_trials: dict[str, list[TrialResult]] = {}
    reference_variant_trials: dict[str, list[TrialResult]] = {}
    variant_exclusion_reasons: dict[str, list[str]] = {}
    variant_constituent_runs: dict[str, set[str]] = {}
    incompatible_runs: list[dict[str, Any]] = []
    warnings: list[str] = []

    for run_info, trials in runs:
        check = check_run_compatibility(run_info, config)
        if not check.is_compatible:
            incompatible_runs.append(
                {"run_id": run_info.run_id, "reasons": check.rejection_reasons,
                 "run_info": run_info.to_dict(), "trials": [t.to_dict() for t in trials],
                 "condition_key": contract_key(run_info.metadata.get("comparison_contract"))}
            )
            warnings.append(
                f"Incompatible run '{run_info.run_id}' rejected: {'; '.join(check.rejection_reasons)}"
            )
            continue

        for t in trials:
            vid = t.variant_id
            variant_constituent_runs.setdefault(vid, set()).add(run_info.run_id)
            if not check.is_eligible:
                variant_exclusion_reasons.setdefault(vid, []).extend(check.ineligibility_reasons)
                reference_variant_trials.setdefault(vid, []).append(t)
            else:
                eligible_variant_trials.setdefault(vid, []).append(t)

    # If any run for a variant was ineligible, treat the combined variant as ineligible
    demoted_vids = set(variant_exclusion_reasons.keys()).intersection(eligible_variant_trials.keys())
    for vid in demoted_vids:
        all_trials = eligible_variant_trials.pop(vid, []) + reference_variant_trials.pop(vid, [])
        reference_variant_trials[vid] = all_trials
        warnings.append(
            f"Variant '{vid}' demoted to reference comparisons due to ineligible constituent runs: "
            f"{'; '.join(sorted(set(variant_exclusion_reasons[vid])))}"
        )

    def _build_variant_metrics(
        vid: str,
        trials: list[TrialResult],
        is_eligible: bool,
    ) -> AggregatedVariantMetrics:
        total_trials = len(trials)
        passed = sum(1 for t in trials if t.status == TrialStatus.PASSED)
        failed = sum(1 for t in trials if t.status == TrialStatus.FAILED)
        timed_out = sum(1 for t in trials if t.status == TrialStatus.TIMED_OUT)
        infra = sum(1 for t in trials if t.status == TrialStatus.INFRASTRUCTURE_ERROR)
        unscored = sum(1 for t in trials if t.status == TrialStatus.UNSCORED)

        scored_denominator = passed + failed + timed_out
        strict_rate = (
            round(passed / scored_denominator, 4) if scored_denominator > 0 else None
        )
        ci = (
            compute_wilson_score_interval(passed, scored_denominator, 0.95)
            if scored_denominator > 0
            else None
        )

        # Task summaries
        task_summaries: dict[str, TaskSummary] = {}
        all_task_ids = sorted(set(config.task_ids).union({t.task_id for t in trials}))
        for tid in all_task_ids:
            t_trials = [t for t in trials if t.task_id == tid]
            task_summaries[tid] = summarize_task(tid, t_trials)

        duration = compute_duration_stats(trials)

        # Custom metrics
        metrics_by_name: dict[str, list[MetricValue]] = {}
        for t in trials:
            for m_name, mv in t.metrics.items():
                metrics_by_name.setdefault(m_name, []).append(mv)

        metric_stats = {
            m_name: compute_metric_stats(m_name, mvs, expected_total=total_trials)
            for m_name, mvs in sorted(metrics_by_name.items())
        }

        reasons = sorted(set(variant_exclusion_reasons.get(vid, [])))
        run_ids = sorted(variant_constituent_runs.get(vid, []))

        return AggregatedVariantMetrics(
            variant_id=vid,
            is_eligible=is_eligible,
            exclusion_reasons=reasons,
            total_trials=total_trials,
            passed=passed,
            failed=failed,
            timed_out=timed_out,
            infrastructure_error=infra,
            unscored=unscored,
            scored_denominator=scored_denominator,
            strict_acceptance_rate=strict_rate,
            confidence_interval_95=ci,
            task_summaries=task_summaries,
            metrics=metric_stats,
            duration=duration,
            constituent_run_ids=run_ids,
            diagnostic_reasons=sorted({str(reason)[:500] for trial in trials for reason in (
                trial.details.get("execution_diagnostic"), trial.details.get("execution_error"),
                "Execution scope unknown" if (trial.details.get("scope_audit") or {}).get("compliance") == "uncertain" else None,
            ) if reason}),
        )

    eligible_variants: dict[str, AggregatedVariantMetrics] = {}
    for vid, v_trials in sorted(eligible_variant_trials.items()):
        eligible_variants[vid] = _build_variant_metrics(vid, v_trials, is_eligible=True)

    reference_variants: dict[str, AggregatedVariantMetrics] = {}
    for vid, v_trials in sorted(reference_variant_trials.items()):
        reference_variants[vid] = _build_variant_metrics(vid, v_trials, is_eligible=False)

    # Canonical rankings: sorted strictly by (strict_rate DESC, duration ASC)
    # ONLY from eligible_variants
    def _rank_key(item: tuple[str, AggregatedVariantMetrics]) -> tuple[float, float]:
        _, m = item
        rate = m.strict_acceptance_rate if m.strict_acceptance_rate is not None else -1.0
        dur_mean = (
            m.duration.all_scored.mean
            if m.duration.all_scored and m.duration.all_scored.mean is not None
            else float("inf")
        )
        return (rate, -dur_mean)

    sorted_eligible = sorted(((k, v) for k, v in eligible_variants.items()
                              if v.scored_denominator > 0 and v.strict_acceptance_rate is not None),
                             key=_rank_key, reverse=True)
    canonical_rankings = [vid for vid, _ in sorted_eligible]

    condition_groups = {}
    if _separate_conditions:
        groups: dict[str, list] = {}
        expected_key = contract_key(config.metadata.get("comparison_contract"))
        for run, trials in runs:
            key = contract_key(run.metadata.get("comparison_contract"))
            if key and key != expected_key:
                groups.setdefault(key, []).append((run, trials))
        for key, group_runs in groups.items():
            first = group_runs[0][0]
            contract = first.metadata["comparison_contract"]
            group_config = replace(config, suite_id=first.suite_id, suite_version=first.suite_version,
                scoring_basis=first.scoring_basis, task_ids=list(first.task_ids),
                budget_profile=contract["budget"]["profile"],
                metadata={**config.metadata, "comparison_contract": contract})
            condition_groups[key] = aggregate_experiment(group_config, group_runs, _separate_conditions=False).to_dict()

    return ExperimentComparison(
        experiment_id=config.experiment_id,
        config=config,
        eligible_variants=eligible_variants,
        reference_variants=reference_variants,
        incompatible_runs=incompatible_runs,
        canonical_rankings=canonical_rankings,
        warnings=warnings, condition_groups=condition_groups,
    )


def render_experiment_comparison_md(comparison: ExperimentComparison) -> str:
    """Render an experiment comparison as readable Markdown."""
    lines: list[str] = [
        f"# Benchmark Experiment Comparison: `{comparison.experiment_id}`",
        "",
        f"- **Suite ID:** `{comparison.config.suite_id}` (v{comparison.config.suite_version})",
        f"- **Budget Profile:** `{comparison.config.budget_profile}`",
        f"- **Scoring Basis:** `{comparison.config.scoring_basis}`",
        f"- **Created At:** `{comparison.config.created_at}`",
        "",
    ]

    if comparison.warnings:
        lines.append("## Warnings & Incompatibilities")
        lines.append("")
        for w in comparison.warnings:
            lines.append(f"> [!WARNING] {w}")
        lines.append("")

    lines.append("## Canonical Model Leaderboard (Eligible Only)")
    lines.append("")
    if not comparison.canonical_rankings:
        lines.append("*No variants with a defined strict rate to rank.*")
        lines.append("")
    else:
        lines.append(
            "| Rank | Variant | Strict Acceptance Rate (Wilson 95% CI) | Scored Denom (Pass / Fail / Timeout) | Infra Errors | Unscored | Mean Duration |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for rank, vid in enumerate(comparison.canonical_rankings, start=1):
            vm = comparison.eligible_variants[vid]
            rate_str = f"{vm.strict_acceptance_rate * 100:.1f}%" if vm.strict_acceptance_rate is not None else "N/A"
            if vm.confidence_interval_95:
                ci = vm.confidence_interval_95
                ci_str = f" [{ci.lower * 100:.1f}% &ndash; {ci.upper * 100:.1f}%]"
            else:
                ci_str = ""
            rate_full = f"{rate_str}{ci_str}"
            denom_str = f"{vm.scored_denominator} ({vm.passed} / {vm.failed} / {vm.timed_out})"
            dur_str = (
                f"{vm.duration.all_scored.mean:.1f} ms"
                if vm.duration.all_scored and vm.duration.all_scored.mean is not None
                else "N/A"
            )
            lines.append(
                f"| {rank} | `{vid}` | **{rate_full}** | {denom_str} | {vm.infrastructure_error} | {vm.unscored} | {dur_str} |"
            )
        lines.append("")

    if comparison.unranked_variants:
        lines.extend(["## Unranked Diagnostics", "", "No numerical rank: strict scored denominator is zero.", "",
                      "| Variant | Trials | Infra / Unscored | Functional rate (available) | Observed mean ms | Reasons |",
                      "|---|---|---|---|---|---|"])
        for vid, vm in sorted(comparison.unranked_variants.items()):
            functional = vm.metrics.get("agent.functional_pass")
            duration = vm.metrics.get("duration.wall_ms")
            function_text = f"{functional.mean:.1%} ({functional.available_count})" if functional and functional.mean is not None else "unknown"
            duration_text = f"{duration.mean:.1f}" if duration and duration.mean is not None else "unknown"
            lines.append(f"| `{vid}` | {vm.total_trials} | {vm.infrastructure_error} / {vm.unscored} | {function_text} | {duration_text} | {'; '.join(vm.diagnostic_reasons)} |")
        lines.append("")

    if comparison.reference_variants:
        lines.append("## Reference & Comparison-Ineligible Variants")
        lines.append("")
        lines.append("> [!NOTE] These variants were evaluated under experimental budget profiles or flagged ineligible. They do not enter canonical rankings.")
        lines.append("")
        lines.append("| Variant | Exclusion Reason | Strict Acceptance Rate | Scored Denom | Infra Errors |")
        lines.append("|---|---|---|---|---|")
        for vid, vm in sorted(comparison.reference_variants.items()):
            reasons = "; ".join(vm.exclusion_reasons) if vm.exclusion_reasons else "Ineligible"
            rate_str = f"{vm.strict_acceptance_rate * 100:.1f}%" if vm.strict_acceptance_rate is not None else "N/A"
            denom_str = f"{vm.scored_denominator} ({vm.passed} / {vm.failed} / {vm.timed_out})"
            lines.append(f"| `{vid}` | {reasons} | {rate_str} | {denom_str} | {vm.infrastructure_error} |")
        lines.append("")

    if comparison.incompatible_runs:
        lines.extend(["## Incompatible / Unknown-condition Diagnostics", ""])
        for item in comparison.incompatible_runs:
            lines.append(f"- `{item['run_id']}`: {'; '.join(item['reasons'])}")
            for trial in item.get("trials", []):
                functional = trial.get("metrics", {}).get("agent.functional_pass", {}).get("value")
                duration = trial.get("metrics", {}).get("duration.wall_ms", {}).get("value")
                lines.append(f"  - `{trial['variant_id']}` / `{trial['trial_id']}`: {trial['status']}; functional={functional}; observed ms={duration}")
        lines.append("")
    for key, group in sorted(comparison.condition_groups.items()):
        lines.extend([f"## Separate comparison conditions `{key[:12]}`", "",
                      render_experiment_comparison_md(ExperimentComparison.from_dict(group)), ""])

    return "\n".join(lines)
