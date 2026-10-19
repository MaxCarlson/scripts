"""
Data models for standalone interactive HTML reporting.

Domain-agnostic contracts for experiment summaries, variant rankings, task divergence,
execution efficiency, and portable trial inspection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Optional


@dataclass(slots=True)
class TrialDetail:
    """Detailed record of a single benchmark trial for offline inspection."""

    trial_id: str
    variant_id: str
    task_id: str
    status: str
    duration_ms: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    peak_context_tokens: Optional[int] = None
    reasoning_token_share: Optional[float] = None
    throughput_tok_per_s: Optional[float] = None
    scope_compliance: Optional[bool] = None
    uncertain_operations: Optional[bool] = None
    verifier_output: Optional[str] = None
    diff: Optional[str] = None
    error_message: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialDetail:
        return cls(
            trial_id=str(data["trial_id"]),
            variant_id=str(data["variant_id"]),
            task_id=str(data["task_id"]),
            status=str(data["status"]),
            duration_ms=float(data.get("duration_ms", 0.0)),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            reasoning_tokens=data.get("reasoning_tokens"),
            total_tokens=data.get("total_tokens"),
            peak_context_tokens=data.get("peak_context_tokens"),
            reasoning_token_share=data.get("reasoning_token_share"),
            throughput_tok_per_s=data.get("throughput_tok_per_s"),
            scope_compliance=data.get("scope_compliance"),
            uncertain_operations=data.get("uncertain_operations"),
            verifier_output=data.get("verifier_output"),
            diff=data.get("diff"),
            error_message=data.get("error_message"),
            metrics=dict(data.get("metrics", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class VariantReportRow:
    """Row representing a benchmark variant (model/configuration) in the leaderboard."""

    variant_id: str
    is_eligible: bool = True
    rank: Optional[int] = None
    exclusion_reasons: list[str] = field(default_factory=list)
    total_trials: int = 0
    passed: int = 0
    failed: int = 0
    timed_out: int = 0
    infrastructure_error: int = 0
    unscored: int = 0
    scored_denominator: int = 0
    strict_acceptance_rate: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    duration_mean_ms: Optional[float] = None
    duration_median_ms: Optional[float] = None
    throughput_tok_per_s: Optional[float] = None
    tokens_per_successful_task: Optional[float] = None
    reasoning_token_share: Optional[float] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariantReportRow:
        return cls(
            variant_id=str(data["variant_id"]),
            is_eligible=bool(data.get("is_eligible", True)),
            rank=data.get("rank"),
            exclusion_reasons=list(data.get("exclusion_reasons", [])),
            total_trials=int(data.get("total_trials", 0)),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            timed_out=int(data.get("timed_out", 0)),
            infrastructure_error=int(data.get("infrastructure_error", 0)),
            unscored=int(data.get("unscored", 0)),
            scored_denominator=int(data.get("scored_denominator", 0)),
            strict_acceptance_rate=data.get("strict_acceptance_rate"),
            ci_lower=data.get("ci_lower"),
            ci_upper=data.get("ci_upper"),
            duration_mean_ms=data.get("duration_mean_ms"),
            duration_median_ms=data.get("duration_median_ms"),
            throughput_tok_per_s=data.get("throughput_tok_per_s"),
            tokens_per_successful_task=data.get("tokens_per_successful_task"),
            reasoning_token_share=data.get("reasoning_token_share"),
            metrics=dict(data.get("metrics", {})),
            configuration=dict(data.get("configuration", {})),
        )


@dataclass(slots=True)
class TaskVariantResult:
    """Cell outcome for a specific variant on a specific task."""

    status: str
    pass_rate: Optional[float] = None
    passed: int = 0
    total: int = 0
    trial_ids: list[str] = field(default_factory=list)
    mean_duration_ms: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskVariantResult:
        return cls(
            status=str(data["status"]),
            pass_rate=data.get("pass_rate"),
            passed=int(data.get("passed", 0)),
            total=int(data.get("total", 0)),
            trial_ids=list(data.get("trial_ids", [])),
            mean_duration_ms=data.get("mean_duration_ms"),
        )


@dataclass(slots=True)
class TaskDivergenceRow:
    """Row in the Task Divergence Matrix."""

    task_id: str
    category: str = "general"
    results_by_variant: dict[str, TaskVariantResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "results_by_variant": {
                k: v.to_dict() for k, v in self.results_by_variant.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskDivergenceRow:
        results = {
            k: TaskVariantResult.from_dict(v)
            for k, v in data.get("results_by_variant", {}).items()
        }
        return cls(
            task_id=str(data["task_id"]),
            category=str(data.get("category", "general")),
            results_by_variant=results,
        )


@dataclass(slots=True)
class EfficiencyPoint:
    """Individual data point for execution efficiency scatterplots."""

    trial_id: str
    variant_id: str
    task_id: str
    status: str
    strict_pass: bool
    duration_ms: float
    total_tokens: int
    throughput_tok_per_s: Optional[float] = None
    reasoning_token_share: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EfficiencyPoint:
        return cls(
            trial_id=str(data["trial_id"]),
            variant_id=str(data["variant_id"]),
            task_id=str(data["task_id"]),
            status=str(data["status"]),
            strict_pass=bool(data.get("strict_pass", False)),
            duration_ms=float(data.get("duration_ms", 0.0)),
            total_tokens=int(data.get("total_tokens", 0)),
            throughput_tok_per_s=data.get("throughput_tok_per_s"),
            reasoning_token_share=data.get("reasoning_token_share"),
        )


@dataclass(slots=True)
class ReportData:
    """Complete structured dataset for generating interactive benchmark reports."""

    experiment_id: str
    title: str = "Benchmark Experiment Report"
    suite_id: str = ""
    suite_version: str = ""
    budget_profile: str = ""
    scoring_basis: str = ""
    created_at: str = ""
    variants: list[VariantReportRow] = field(default_factory=list)
    divergence_matrix: list[TaskDivergenceRow] = field(default_factory=list)
    efficiency_points: list[EfficiencyPoint] = field(default_factory=list)
    trials: dict[str, TrialDetail] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "title": self.title,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "budget_profile": self.budget_profile,
            "scoring_basis": self.scoring_basis,
            "created_at": self.created_at,
            "variants": [v.to_dict() for v in self.variants],
            "divergence_matrix": [d.to_dict() for d in self.divergence_matrix],
            "efficiency_points": [e.to_dict() for e in self.efficiency_points],
            "trials": {k: v.to_dict() for k, v in self.trials.items()},
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportData:
        return cls(
            experiment_id=str(data["experiment_id"]),
            title=str(data.get("title", "Benchmark Experiment Report")),
            suite_id=str(data.get("suite_id", "")),
            suite_version=str(data.get("suite_version", "")),
            budget_profile=str(data.get("budget_profile", "")),
            scoring_basis=str(data.get("scoring_basis", "")),
            created_at=str(data.get("created_at", "")),
            variants=[VariantReportRow.from_dict(v) for v in data.get("variants", [])],
            divergence_matrix=[
                TaskDivergenceRow.from_dict(d)
                for d in data.get("divergence_matrix", [])
            ],
            efficiency_points=[
                EfficiencyPoint.from_dict(e) for e in data.get("efficiency_points", [])
            ],
            trials={
                k: TrialDetail.from_dict(v)
                for k, v in data.get("trials", {}).items()
            },
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> ReportData:
        return cls.from_dict(json.loads(json_str))
