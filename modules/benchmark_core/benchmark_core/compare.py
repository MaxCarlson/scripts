"""
Comparison utilities for benchmark runs and variants.

Calculates absolute and percentage deltas, highlights improvements and regressions,
and provides explicit warnings when scoring bases, suite versions, or units mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Optional

from .stats import BenchmarkSummary, VariantSummary


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
) -> VariantComparison:
    """Compare two VariantSummary instances."""
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
    if baseline.run_info.scoring_basis != candidate.run_info.scoring_basis:
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

    # Suite version verification
    if baseline.run_info.suite_version != candidate.run_info.suite_version:
        warnings.append(
            f"NOTICE: Suite version difference: v{baseline.run_info.suite_version} (baseline) "
            f"vs v{candidate.run_info.suite_version} (candidate)."
        )

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
            variant_comps[vid] = compare_variants(base_var, cand_var)

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
