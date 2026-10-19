"""
Report generators for benchmark_core: JSON, wide-form CSV, and Markdown.

Follows Final Amendment 3 requirements:
- summary.json: complete machine-readable aggregates and provenance
- summary.csv: deterministic wide-form schema with exactly one row per variant,
  union of aggregate metric keys, deterministically sorted columns, empty fields for missing values (never 0)
- report.md: human-readable Markdown report with configuration, results, durations, and warnings
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, Union

from .stats import BenchmarkSummary

if TYPE_CHECKING:
    from .compare import ExperimentComparison
    from .models import TrialResult


def render_summary_json(summary: BenchmarkSummary) -> str:
    """Render complete machine-readable summary as formatted JSON."""
    return summary.to_json()


def render_summary_csv(summary: BenchmarkSummary) -> str:
    """
    Render tabular variant comparison as a deterministic wide-form CSV.

    Adheres strictly to Final Amendment 3:
    1. Exactly one row per benchmark variant.
    2. Collect union of aggregate metric keys across all variants.
    3. Sort dynamic metric columns deterministically.
    4. Preserve unambiguous metric names (e.g. 'tokens.worker.input.mean').
    5. Represent unavailable or absent measurements with empty CSV fields (''), never zero.
    6. Stable identification and primary result columns.
    """
    variants = list(summary.variants.values())
    if not variants:
        return ""

    # 1. Collect union of metric keys across all variants
    all_metric_keys: set[str] = set()
    for v in variants:
        all_metric_keys.update(v.metrics.keys())
    sorted_metric_keys = sorted(all_metric_keys)

    # 2. Define stable identification and result columns
    headers = [
        "variant_id",
        "total_trials",
        "eligible_count",
        "passed",
        "failed",
        "timed_out",
        "infrastructure_error",
        "unscored",
        "micro_success_rate",
        "macro_success_rate",
        "duration_all_scored_mean_ms",
        "duration_all_scored_median_ms",
        "duration_successful_mean_ms",
        "duration_successful_median_ms",
    ]

    # Dynamic metric sub-fields
    metric_subfields = ["mean", "median", "min", "max", "stdev", "available_count", "missing_count"]
    for m_key in sorted_metric_keys:
        for sf in metric_subfields:
            headers.append(f"{m_key}.{sf}")

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)

    for v in sorted(variants, key=lambda x: x.variant_id):
        # Stable columns
        row: list[Any] = [
            v.variant_id,
            v.total_trials,
            v.eligible_count,
            v.passed,
            v.failed,
            v.timed_out,
            v.infrastructure_error,
            v.unscored,
            v.micro_success_rate if v.micro_success_rate is not None else "",
            v.macro_success_rate if v.macro_success_rate is not None else "",
        ]

        # Duration columns
        all_scored_dur = v.duration.all_scored
        row.append(all_scored_dur.mean if (all_scored_dur and all_scored_dur.mean is not None) else "")
        row.append(all_scored_dur.median if (all_scored_dur and all_scored_dur.median is not None) else "")

        succ_dur = v.duration.successful_only
        row.append(succ_dur.mean if (succ_dur and succ_dur.mean is not None) else "")
        row.append(succ_dur.median if (succ_dur and succ_dur.median is not None) else "")

        # Dynamic metric columns (empty string for absent/unavailable measurements)
        for m_key in sorted_metric_keys:
            m_stat = v.metrics.get(m_key)
            if m_stat is None:
                row.extend([""] * len(metric_subfields))
            else:
                row.append(m_stat.mean if m_stat.mean is not None else "")
                row.append(m_stat.median if m_stat.median is not None else "")
                row.append(m_stat.min if m_stat.min is not None else "")
                row.append(m_stat.max if m_stat.max is not None else "")
                row.append(m_stat.stdev if m_stat.stdev is not None else "")
                row.append(m_stat.available_count)
                row.append(m_stat.missing_count)

        writer.writerow(row)

    return output.getvalue()


def render_report_md(summary: BenchmarkSummary) -> str:
    """Render human-readable Markdown report."""
    run_info = summary.run_info
    variants = list(summary.variants.values())

    lines: list[str] = [
        f"# Benchmark Report: {run_info.run_id}",
        "",
        "## Overview",
        "",
        f"- **Suite ID:** `{run_info.suite_id}` (version `{run_info.suite_version}`)",
        f"- **Created At:** {run_info.created_at}",
        f"- **Scoring Basis:** `{run_info.scoring_basis}`",
        f"- **Planned Repetitions:** {run_info.repetitions}",
        f"- **Evaluated Tasks:** {len(run_info.task_ids)} tasks",
        "",
    ]

    # Reproducibility Metadata
    lines.append("## Reproducibility & Environment")
    lines.append("")
    fingerprint = run_info.metadata.get("suite_fingerprint", "N/A")
    seed = run_info.metadata.get("random_seed", "N/A")
    lines.append(f"- **Suite Fingerprint:** `{fingerprint}`")
    lines.append(f"- **Random Seed:** `{seed}`")

    if run_info.environment:
        lines.append("- **Environment:**")
        for env_k, env_v in sorted(run_info.environment.items()):
            lines.append(f"  - `{env_k}`: {env_v}")
    if run_info.metadata:
        other_meta = {k: v for k, v in run_info.metadata.items() if k not in ("suite_fingerprint", "random_seed")}
        if other_meta:
            lines.append("- **Additional Metadata:**")
            for mk, mv in sorted(other_meta.items()):
                lines.append(f"  - `{mk}`: {mv}")
    lines.append("")

    # Variant Configurations
    lines.append("## Variant Configurations")
    lines.append("")
    lines.append("| Variant ID | Configuration Details |")
    lines.append("|---|---|")
    for v in sorted(variants, key=lambda x: x.variant_id):
        cfg_str = ", ".join(f"`{k}={val}`" for k, val in sorted(v.configuration.items())) or "*(default)*"
        lines.append(f"| `{v.variant_id}` | {cfg_str} |")
    lines.append("")

    # Primary Results Table
    lines.append("## Primary Results")
    lines.append("")
    lines.append("| Variant | Total Trials | Eligible | Passed | Failed | Timed Out | Infra Error | Unscored | Micro Success | Macro Success |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v in sorted(variants, key=lambda x: x.variant_id):
        micro_str = f"{v.micro_success_rate * 100:.1f}%" if v.micro_success_rate is not None else "N/A"
        macro_str = f"{v.macro_success_rate * 100:.1f}%" if v.macro_success_rate is not None else "N/A"
        lines.append(
            f"| `{v.variant_id}` | {v.total_trials} | {v.eligible_count} | {v.passed} | {v.failed} | "
            f"{v.timed_out} | {v.infrastructure_error} | {v.unscored} | {micro_str} | {macro_str} |"
        )
    lines.append("")

    # Timing Table
    lines.append("## Duration & Latency")
    lines.append("")
    lines.append("| Variant | All-Scored (Mean ± Stdev) | All-Scored (Median [Min, Max]) | Successful-Only (Mean ± Stdev) | Successful (Median) |")
    lines.append("|---|---|---|---|---|")
    for v in sorted(variants, key=lambda x: x.variant_id):
        all_dur = v.duration.all_scored
        if all_dur and all_dur.available_count > 0:
            stdev_s = f" ± {all_dur.stdev:.1f}" if all_dur.stdev is not None else ""
            all_mean = f"{all_dur.mean:.1f}{stdev_s} {all_dur.unit} (n={all_dur.available_count})"
            all_med = f"{all_dur.median:.1f} [{all_dur.min:.1f}, {all_dur.max:.1f}] {all_dur.unit}"
        else:
            all_mean = "N/A"
            all_med = "N/A"

        succ_dur = v.duration.successful_only
        if succ_dur and succ_dur.available_count > 0:
            stdev_s = f" ± {succ_dur.stdev:.1f}" if succ_dur.stdev is not None else ""
            succ_mean = f"{succ_dur.mean:.1f}{stdev_s} {succ_dur.unit} (n={succ_dur.available_count})"
            succ_med = f"{succ_dur.median:.1f} {succ_dur.unit}"
        else:
            succ_mean = "N/A"
            succ_med = "N/A"

        lines.append(f"| `{v.variant_id}` | {all_mean} | {all_med} | {succ_mean} | {succ_med} |")
    lines.append("")

    # Metrics Summary
    all_metric_keys = sorted({k for v in variants for k in v.metrics.keys() if k != "duration.wall_ms"})
    if all_metric_keys:
        lines.append("## Resource & Token Metrics")
        lines.append("")
        lines.append("| Variant | Metric | Mean | Median | Available / Total |")
        lines.append("|---|---|---:|---:|---:|")
        for v in sorted(variants, key=lambda x: x.variant_id):
            for mk in all_metric_keys:
                m_stat = v.metrics.get(mk)
                if m_stat is not None:
                    if m_stat.available_count > 0:
                        mean_s = f"{m_stat.mean:.1f} {m_stat.unit}" if m_stat.mean is not None else "N/A"
                        med_s = f"{m_stat.median:.1f} {m_stat.unit}" if m_stat.median is not None else "N/A"
                        obs_s = f"{m_stat.available_count}/{m_stat.observation_count}"
                    else:
                        mean_s = "N/A"
                        med_s = "N/A"
                        obs_s = f"0/{m_stat.observation_count}"
                    lines.append(f"| `{v.variant_id}` | `{mk}` | {mean_s} | {med_s} | {obs_s} |")
        lines.append("")

    # Incompatibility & Sampling Warnings
    warnings: list[str] = []
    for v in variants:
        if v.insufficiently_sampled_tasks:
            warnings.append(
                f"- Variant `{v.variant_id}` has insufficiently sampled tasks with 0 eligible scored trials: "
                f"`{', '.join(v.insufficiently_sampled_tasks)}` (excluded from macro-average calculation)."
            )
        if v.eligible_count == 0:
            warnings.append(
                f"- Variant `{v.variant_id}` has 0 eligible scored trials (all trials failed infrastructure checks or were unscored)."
            )

    if warnings:
        lines.append("## Notable Observations & Warnings")
        lines.append("")
        lines.extend(warnings)
        lines.append("")

    return "\n".join(lines)


def generate_reports(
    summary: BenchmarkSummary,
    output_dir: Optional[Union[Path, str]] = None,
    write: bool = False,
) -> dict[str, str]:
    """
    Generate all derived report artifacts (summary.json, summary.csv, report.md).

    Args:
        summary: The BenchmarkSummary to render.
        output_dir: Destination folder if write=True.
        write: If True, writes files to disk. If False, returns string content map.

    Returns:
        Dict mapping filenames to generated string content.
    """
    reports = {
        "summary.json": render_summary_json(summary),
        "summary.csv": render_summary_csv(summary),
        "report.md": render_report_md(summary),
    }

    if write:
        if output_dir is None:
            raise ValueError("output_dir must be specified when write=True")
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for filename, content in reports.items():
            (out_path / filename).write_text(content, encoding="utf-8")

    return reports


def render_experiment_comparison_csv(comparison: ExperimentComparison) -> str:
    """
    Render tabular model/variant comparison as a deterministic wide-form CSV.
    Eligible variants are listed first in canonical ranking order, followed by reference variants.
    """
    all_variants = list(comparison.eligible_variants.values()) + list(comparison.reference_variants.values())
    if not all_variants:
        return ""

    all_metric_keys: set[str] = set()
    for v in all_variants:
        all_metric_keys.update(v.metrics.keys())
    sorted_metric_keys = sorted(all_metric_keys)

    headers = [
        "rank",
        "variant_id",
        "is_eligible",
        "exclusion_reasons",
        "strict_acceptance_rate",
        "ci_95_lower",
        "ci_95_upper",
        "total_trials",
        "scored_denominator",
        "passed",
        "failed",
        "timed_out",
        "infrastructure_error",
        "unscored",
        "duration_all_scored_mean_ms",
        "duration_all_scored_median_ms",
    ]

    metric_subfields = ["mean", "median", "min", "max", "stdev", "available_count", "missing_count"]
    for m_key in sorted_metric_keys:
        for sf in metric_subfields:
            headers.append(f"{m_key}.{sf}")

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)

    def _variant_row(rank_val: Any, vm: Any) -> list[Any]:
        ci = vm.confidence_interval_95
        row: list[Any] = [
            rank_val,
            vm.variant_id,
            "true" if vm.is_eligible else "false",
            "; ".join(vm.exclusion_reasons),
            vm.strict_acceptance_rate if vm.strict_acceptance_rate is not None else "",
            ci.lower if ci else "",
            ci.upper if ci else "",
            vm.total_trials,
            vm.scored_denominator,
            vm.passed,
            vm.failed,
            vm.timed_out,
            vm.infrastructure_error,
            vm.unscored,
        ]
        all_dur = vm.duration.all_scored
        row.append(all_dur.mean if (all_dur and all_dur.mean is not None) else "")
        row.append(all_dur.median if (all_dur and all_dur.median is not None) else "")

        for m_key in sorted_metric_keys:
            m_stat = vm.metrics.get(m_key)
            if m_stat is None:
                row.extend([""] * len(metric_subfields))
            else:
                row.append(m_stat.mean if m_stat.mean is not None else "")
                row.append(m_stat.median if m_stat.median is not None else "")
                row.append(m_stat.min if m_stat.min is not None else "")
                row.append(m_stat.max if m_stat.max is not None else "")
                row.append(m_stat.stdev if m_stat.stdev is not None else "")
                row.append(m_stat.available_count)
                row.append(m_stat.missing_count)
        return row

    for rank, vid in enumerate(comparison.canonical_rankings, start=1):
        if vid in comparison.eligible_variants:
            writer.writerow(_variant_row(rank, comparison.eligible_variants[vid]))

    for vid, vm in sorted(comparison.reference_variants.items()):
        writer.writerow(_variant_row("", vm))

    return output.getvalue()


def generate_experiment_reports(
    comparison: ExperimentComparison,
    trials: Sequence[TrialResult] = (),
    output_dir: Optional[Union[Path, str]] = None,
    write: bool = False,
    task_categories: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """
    Generate all experiment report artifacts (comparison.json, comparison.csv, report.md, index.html).
    """
    from .compare import render_experiment_comparison_md

    reports = {
        "comparison.json": comparison.to_json(),
        "comparison.csv": render_experiment_comparison_csv(comparison),
        "report.md": render_experiment_comparison_md(comparison),
    }

    try:
        from interactive_reports import from_experiment_comparison, generate_html_report

        report_data = from_experiment_comparison(
            comparison,
            trials,
            task_categories=task_categories,
        )
        reports["index.html"] = generate_html_report(report_data)
    except ImportError:
        pass

    if write:
        if output_dir is None:
            raise ValueError("output_dir must be specified when write=True")
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for filename, content in reports.items():
            (out_path / filename).write_text(content, encoding="utf-8")

    return reports
