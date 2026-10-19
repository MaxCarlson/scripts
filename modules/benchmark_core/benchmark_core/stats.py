"""
Descriptive statistics, capability rate calculations, and benchmark aggregations.

Implements standard statistics via Python's statistics module:
- All-scored duration vs successful-only duration
- Micro and macro capability success rates
- Strict denominator filtering: passed / (passed + failed + timed_out)
- Infrastructure errors and unscored trials excluded from capability denominator
- Preservation of metric provenance and distinction of estimated vs measured values
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import math
import statistics
from typing import Any, Optional

from .models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
    VALID_QUALITIES,
    format_utc_timestamp,
)

PRIMARY_DURATION_METRIC = "duration.wall_ms"


@dataclass(frozen=True, slots=True)
class ScoreConfidenceInterval:
    """Wilson score confidence interval for a success rate / proportion."""

    lower: float
    upper: float
    confidence: float
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoreConfidenceInterval:
        return cls(
            lower=data["lower"],
            upper=data["upper"],
            confidence=data.get("confidence", 0.95),
            sample_size=data["sample_size"],
        )


def compute_wilson_score_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> Optional[ScoreConfidenceInterval]:
    """
    Calculate the Wilson score confidence interval for a proportion.

    Formula:
      center = (p + z^2/(2n)) / (1 + z^2/n)
      margin = (z / (1 + z^2/n)) * sqrt(p(1-p)/n + z^2/(4n^2))
    where p = successes / total, n = total, and z is the normal critical value.
    Returns None if total <= 0.
    """
    if total <= 0:
        return None
    if successes < 0 or successes > total:
        raise ValueError(f"successes ({successes}) must be between 0 and total ({total})")

    if abs(confidence - 0.95) < 1e-4:
        z = 1.959963984540054
    elif abs(confidence - 0.90) < 1e-4:
        z = 1.6448536269514722
    elif abs(confidence - 0.99) < 1e-4:
        z = 2.5758293035489004
    else:
        z = 1.959963984540054

    n = float(total)
    p = float(successes) / n
    z2 = z * z

    denom = 1.0 + (z2 / n)
    center = (p + (z2 / (2.0 * n))) / denom
    margin = (z / denom) * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))

    lower = max(0.0, round(center - margin, 4))
    upper = min(1.0, round(center + margin, 4))

    return ScoreConfidenceInterval(
        lower=lower,
        upper=upper,
        confidence=confidence,
        sample_size=total,
    )


@dataclass(frozen=True, slots=True)
class MetricStats:
    """Descriptive statistics for a numeric metric."""

    name: str
    unit: str
    observation_count: int
    available_count: int
    missing_count: int
    mean: Optional[float]
    median: Optional[float]
    min: Optional[float]
    max: Optional[float]
    stdev: Optional[float]
    measured_mean: Optional[float] = None
    estimated_mean: Optional[float] = None
    quality_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "observation_count": self.observation_count,
            "available_count": self.available_count,
            "missing_count": self.missing_count,
            "mean": self.mean,
            "median": self.median,
            "min": self.min,
            "max": self.max,
            "stdev": self.stdev,
            "measured_mean": self.measured_mean,
            "estimated_mean": self.estimated_mean,
            "quality_counts": copy.deepcopy(self.quality_counts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricStats:
        return cls(
            name=data["name"],
            unit=data["unit"],
            observation_count=data["observation_count"],
            available_count=data["available_count"],
            missing_count=data["missing_count"],
            mean=data.get("mean"),
            median=data.get("median"),
            min=data.get("min"),
            max=data.get("max"),
            stdev=data.get("stdev"),
            measured_mean=data.get("measured_mean"),
            estimated_mean=data.get("estimated_mean"),
            quality_counts=data.get("quality_counts", {}),
        )


@dataclass(frozen=True, slots=True)
class DurationStats:
    """Durations split into all-scored trials vs successful-only trials."""

    all_scored: Optional[MetricStats]
    successful_only: Optional[MetricStats]

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_scored": self.all_scored.to_dict() if self.all_scored else None,
            "successful_only": self.successful_only.to_dict() if self.successful_only else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DurationStats:
        return cls(
            all_scored=MetricStats.from_dict(data["all_scored"]) if data.get("all_scored") else None,
            successful_only=MetricStats.from_dict(data["successful_only"]) if data.get("successful_only") else None,
        )


@dataclass(frozen=True, slots=True)
class TaskSummary:
    """Summary of execution and measurements for a specific task under a variant."""

    task_id: str
    total_trials: int
    passed: int
    failed: int
    timed_out: int
    infrastructure_error: int
    unscored: int
    eligible_count: int
    success_rate: Optional[float]
    metrics: dict[str, MetricStats]
    duration: DurationStats
    confidence_interval: Optional[ScoreConfidenceInterval] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "total_trials": self.total_trials,
            "passed": self.passed,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
            "unscored": self.unscored,
            "eligible_count": self.eligible_count,
            "success_rate": self.success_rate,
            "confidence_interval": self.confidence_interval.to_dict() if self.confidence_interval else None,
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
            "duration": self.duration.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSummary:
        ci_data = data.get("confidence_interval")
        ci = ScoreConfidenceInterval.from_dict(ci_data) if ci_data else None
        return cls(
            task_id=data["task_id"],
            total_trials=data["total_trials"],
            passed=data["passed"],
            failed=data["failed"],
            timed_out=data["timed_out"],
            infrastructure_error=data["infrastructure_error"],
            unscored=data["unscored"],
            eligible_count=data["eligible_count"],
            success_rate=data.get("success_rate"),
            metrics={k: MetricStats.from_dict(v) for k, v in data.get("metrics", {}).items()},
            duration=DurationStats.from_dict(data["duration"]),
            confidence_interval=ci,
        )


@dataclass(frozen=True, slots=True)
class VariantSummary:
    """Summary of execution, capability rates, and measurements for a benchmark variant."""

    variant_id: str
    configuration: dict[str, Any]
    total_trials: int
    passed: int
    failed: int
    timed_out: int
    infrastructure_error: int
    unscored: int
    eligible_count: int
    micro_success_rate: Optional[float]
    macro_success_rate: Optional[float]
    insufficiently_sampled_tasks: list[str]
    metrics: dict[str, MetricStats]
    duration: DurationStats
    tasks: dict[str, TaskSummary]
    confidence_interval: Optional[ScoreConfidenceInterval] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "configuration": copy.deepcopy(self.configuration),
            "total_trials": self.total_trials,
            "passed": self.passed,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
            "unscored": self.unscored,
            "eligible_count": self.eligible_count,
            "micro_success_rate": self.micro_success_rate,
            "macro_success_rate": self.macro_success_rate,
            "confidence_interval": self.confidence_interval.to_dict() if self.confidence_interval else None,
            "insufficiently_sampled_tasks": list(self.insufficiently_sampled_tasks),
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
            "duration": self.duration.to_dict(),
            "tasks": {k: v.to_dict() for k, v in sorted(self.tasks.items())},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariantSummary:
        ci_data = data.get("confidence_interval")
        ci = ScoreConfidenceInterval.from_dict(ci_data) if ci_data else None
        return cls(
            variant_id=data["variant_id"],
            configuration=data.get("configuration", {}),
            total_trials=data["total_trials"],
            passed=data["passed"],
            failed=data["failed"],
            timed_out=data["timed_out"],
            infrastructure_error=data["infrastructure_error"],
            unscored=data["unscored"],
            eligible_count=data["eligible_count"],
            micro_success_rate=data.get("micro_success_rate"),
            macro_success_rate=data.get("macro_success_rate"),
            confidence_interval=ci,
            insufficiently_sampled_tasks=data.get("insufficiently_sampled_tasks", []),
            metrics={k: MetricStats.from_dict(v) for k, v in data.get("metrics", {}).items()},
            duration=DurationStats.from_dict(data["duration"]),
            tasks={k: TaskSummary.from_dict(v) for k, v in data.get("tasks", {}).items()},
        )


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    """Complete summary of a benchmark run and its variant evaluations."""

    run_info: RunInfo
    variants: dict[str, VariantSummary]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_info": self.run_info.to_dict(),
            "variants": {k: v.to_dict() for k, v in sorted(self.variants.items())},
            "generated_at": self.generated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkSummary:
        return cls(
            run_info=RunInfo.from_dict(data["run_info"]),
            variants={k: VariantSummary.from_dict(v) for k, v in data.get("variants", {}).items()},
            generated_at=data.get("generated_at", format_utc_timestamp()),
        )

    @classmethod
    def from_json(cls, json_str: str) -> BenchmarkSummary:
        return cls.from_dict(json.loads(json_str))


def compute_metric_stats(
    name: str,
    metric_values: list[MetricValue],
    expected_total: Optional[int] = None,
) -> MetricStats:
    """
    Calculate descriptive statistics for a collection of MetricValues.

    Distinguishes available vs missing/unavailable, counts qualities,
    and calculates mean, median, min, max, stdev, measured_mean, and estimated_mean.
    Rejects incompatible units within the same metric name.
    """
    observation_count = len(metric_values)
    if expected_total is not None and expected_total > observation_count:
        observation_count = expected_total

    if len(metric_values) == 0:
        return MetricStats(
            name=name,
            unit="",
            observation_count=observation_count,
            available_count=0,
            missing_count=observation_count,
            mean=None,
            median=None,
            min=None,
            max=None,
            stdev=None,
            measured_mean=None,
            estimated_mean=None,
            quality_counts={q: 0 for q in sorted(VALID_QUALITIES)},
        )

    # Unit validation
    units = {mv.unit for mv in metric_values if mv.unit}
    if len(units) > 1:
        raise ValueError(f"Incompatible units found for metric '{name}': {sorted(units)}")

    unit = metric_values[0].unit

    quality_counts = {q: 0 for q in sorted(VALID_QUALITIES)}
    for mv in metric_values:
        q_str = str(mv.quality)
        quality_counts[q_str] = quality_counts.get(q_str, 0) + 1

    available_floats: list[float] = [
        float(mv.value)
        for mv in metric_values
        if mv.value is not None and str(mv.quality) != MetricQuality.UNAVAILABLE
    ]
    available_count = len(available_floats)
    missing_count = observation_count - available_count

    measured_floats: list[float] = [
        float(mv.value)
        for mv in metric_values
        if mv.value is not None and str(mv.quality) == MetricQuality.MEASURED
    ]
    measured_mean = round(statistics.mean(measured_floats), 4) if measured_floats else None

    estimated_floats: list[float] = [
        float(mv.value)
        for mv in metric_values
        if mv.value is not None and str(mv.quality) == MetricQuality.ESTIMATED
    ]
    estimated_mean = round(statistics.mean(estimated_floats), 4) if estimated_floats else None

    if available_count == 0:
        return MetricStats(
            name=name,
            unit=unit,
            observation_count=observation_count,
            available_count=0,
            missing_count=missing_count,
            mean=None,
            median=None,
            min=None,
            max=None,
            stdev=None,
            measured_mean=None,
            estimated_mean=None,
            quality_counts=quality_counts,
        )

    mean_val = round(statistics.mean(available_floats), 4)
    median_val = round(statistics.median(available_floats), 4)
    min_val = round(min(available_floats), 4)
    max_val = round(max(available_floats), 4)
    stdev_val = round(statistics.stdev(available_floats), 4) if available_count >= 2 else None

    return MetricStats(
        name=name,
        unit=unit,
        observation_count=observation_count,
        available_count=available_count,
        missing_count=missing_count,
        mean=mean_val,
        median=median_val,
        min=min_val,
        max=max_val,
        stdev=stdev_val,
        measured_mean=measured_mean,
        estimated_mean=estimated_mean,
        quality_counts=quality_counts,
    )


def compute_duration_stats(trials: list[TrialResult]) -> DurationStats:
    """
    Extract duration metrics for:
    - all-scored trials: passed, failed, timed_out
    - successful-only trials: passed
    """
    all_scored_mvs: list[MetricValue] = []
    successful_mvs: list[MetricValue] = []

    for t in trials:
        mv = t.metrics.get(PRIMARY_DURATION_METRIC)
        if not mv:
            # Fallback: find any metric ending in duration.wall_ms or with duration
            for k, val in t.metrics.items():
                if k == "duration" or k.endswith(".duration") or k.endswith(".duration_ms"):
                    mv = val
                    break

        if mv:
            if t.status in (TrialStatus.PASSED, TrialStatus.FAILED, TrialStatus.TIMED_OUT):
                all_scored_mvs.append(mv)
            if t.status == TrialStatus.PASSED:
                successful_mvs.append(mv)

    all_scored_stats = (
        compute_metric_stats(PRIMARY_DURATION_METRIC, all_scored_mvs)
        if all_scored_mvs
        else None
    )
    successful_stats = (
        compute_metric_stats(PRIMARY_DURATION_METRIC, successful_mvs)
        if successful_mvs
        else None
    )

    return DurationStats(all_scored=all_scored_stats, successful_only=successful_stats)


_compute_duration_stats = compute_duration_stats


def summarize_task(task_id: str, trials: list[TrialResult]) -> TaskSummary:
    """Summarize trials for a single task."""
    total_trials = len(trials)
    status_counts: dict[str, int] = {s.value: 0 for s in TrialStatus}
    for t in trials:
        status_key = str(t.status)
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

    passed = status_counts[TrialStatus.PASSED.value]
    failed = status_counts[TrialStatus.FAILED.value]
    timed_out = status_counts[TrialStatus.TIMED_OUT.value]
    infrastructure_error = status_counts[TrialStatus.INFRASTRUCTURE_ERROR.value]
    unscored = status_counts[TrialStatus.UNSCORED.value]

    eligible_count = passed + failed + timed_out
    success_rate: Optional[float] = (
        round(passed / eligible_count, 4) if eligible_count > 0 else None
    )

    # Metrics aggregation
    metrics_by_name: dict[str, list[MetricValue]] = {}
    for t in trials:
        for m_name, mv in t.metrics.items():
            metrics_by_name.setdefault(m_name, []).append(mv)

    metric_stats = {
        name: compute_metric_stats(name, mvs, expected_total=total_trials)
        for name, mvs in sorted(metrics_by_name.items())
    }

    duration = _compute_duration_stats(trials)

    ci = (
        compute_wilson_score_interval(passed, eligible_count)
        if eligible_count > 0
        else None
    )

    return TaskSummary(
        task_id=task_id,
        total_trials=total_trials,
        passed=passed,
        failed=failed,
        timed_out=timed_out,
        infrastructure_error=infrastructure_error,
        unscored=unscored,
        eligible_count=eligible_count,
        success_rate=success_rate,
        metrics=metric_stats,
        duration=duration,
        confidence_interval=ci,
    )


_summarize_task = summarize_task


def summarize(
    run_info: RunInfo,
    trials: list[TrialResult],
    generated_at: Optional[str] = None,
) -> BenchmarkSummary:
    """
    Aggregate trials into a full BenchmarkSummary across all variants and tasks.

    Calculates:
    - Micro capability success rate: pooled passed / pooled eligible
    - Macro capability success rate: average of per-task rates for tasks with eligible denominator > 0
    - Insufficiently sampled tasks: tasks with eligible denominator == 0
    - All-scored vs successful-only duration
    """
    if generated_at is None:
        generated_at = format_utc_timestamp()

    # Verify trials belong to this run
    for t in trials:
        if t.run_id != run_info.run_id:
            raise ValueError(
                f"Trial '{t.trial_id}' belongs to run '{t.run_id}', but RunInfo has run_id '{run_info.run_id}'"
            )

    # Group trials by variant_id
    trials_by_variant: dict[str, list[TrialResult]] = {vid: [] for vid in run_info.variants.keys()}
    for t in trials:
        trials_by_variant.setdefault(t.variant_id, []).append(t)

    variant_summaries: dict[str, VariantSummary] = {}

    # Include all declared variants plus any undeclared variants found in trials
    all_variant_ids = list(run_info.variants.keys())
    for vid in sorted(trials_by_variant.keys()):
        if vid not in run_info.variants:
            all_variant_ids.append(vid)

    for vid in all_variant_ids:
        v_config = run_info.variants.get(vid, {"undeclared": True})
        v_trials = trials_by_variant.get(vid, [])

        # Group variant trials by task_id
        # Preserve all declared task_ids from run_info, plus any extra found in trials
        declared_tasks = list(run_info.task_ids)
        seen_tasks = set(declared_tasks)
        for t in v_trials:
            if t.task_id not in seen_tasks:
                declared_tasks.append(t.task_id)
                seen_tasks.add(t.task_id)

        trials_by_task: dict[str, list[TrialResult]] = {tid: [] for tid in declared_tasks}
        for t in v_trials:
            trials_by_task.setdefault(t.task_id, []).append(t)

        task_summaries: dict[str, TaskSummary] = {}
        macro_rates: list[float] = []
        insufficiently_sampled: list[str] = []

        total_trials = len(v_trials)
        v_status_counts: dict[str, int] = {s.value: 0 for s in TrialStatus}
        for t in v_trials:
            status_key = str(t.status)
            v_status_counts[status_key] = v_status_counts.get(status_key, 0) + 1

        for tid in declared_tasks:
            t_trials = trials_by_task[tid]
            ts = _summarize_task(tid, t_trials)
            task_summaries[tid] = ts

            if ts.eligible_count == 0:
                # Excluded from macro calculation per Amendment 2
                insufficiently_sampled.append(tid)
            else:
                # Included even if success_rate == 0.0 (e.g. 3 failed trials)
                assert ts.success_rate is not None
                macro_rates.append(ts.success_rate)

        v_passed = v_status_counts[TrialStatus.PASSED.value]
        v_failed = v_status_counts[TrialStatus.FAILED.value]
        v_timed_out = v_status_counts[TrialStatus.TIMED_OUT.value]
        v_infra = v_status_counts[TrialStatus.INFRASTRUCTURE_ERROR.value]
        v_unscored = v_status_counts[TrialStatus.UNSCORED.value]
        v_eligible = v_passed + v_failed + v_timed_out

        micro_success_rate = (
            round(v_passed / v_eligible, 4) if v_eligible > 0 else None
        )
        macro_success_rate = (
            round(statistics.mean(macro_rates), 4) if macro_rates else None
        )

        # Variant-wide metrics
        v_metrics_by_name: dict[str, list[MetricValue]] = {}
        for t in v_trials:
            for m_name, mv in t.metrics.items():
                v_metrics_by_name.setdefault(m_name, []).append(mv)

        v_metric_stats = {
            name: compute_metric_stats(name, mvs, expected_total=total_trials)
            for name, mvs in sorted(v_metrics_by_name.items())
        }

        v_duration = _compute_duration_stats(v_trials)

        v_ci = (
            compute_wilson_score_interval(v_passed, v_eligible)
            if v_eligible > 0
            else None
        )

        variant_summaries[vid] = VariantSummary(
            variant_id=vid,
            configuration=v_config,
            total_trials=total_trials,
            passed=v_passed,
            failed=v_failed,
            timed_out=v_timed_out,
            infrastructure_error=v_infra,
            unscored=v_unscored,
            eligible_count=v_eligible,
            micro_success_rate=micro_success_rate,
            macro_success_rate=macro_success_rate,
            insufficiently_sampled_tasks=insufficiently_sampled,
            metrics=v_metric_stats,
            duration=v_duration,
            tasks=task_summaries,
            confidence_interval=v_ci,
        )

    return BenchmarkSummary(
        run_info=run_info,
        variants=variant_summaries,
        generated_at=generated_at,
    )
