"""
Authoritative data models and serialization helpers for benchmark_core.

Defines the shared contracts: RunInfo, TrialResult, and MetricValue, along with
strict validation rules, safe relative path handling, and UTC timestamp utilities.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Optional, Union


class TrialStatus(StrEnum):
    """Allowed primary evaluation statuses for a benchmark trial."""

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    UNSCORED = "unscored"


VALID_STATUSES: frozenset[str] = frozenset(s.value for s in TrialStatus)


class MetricQuality(StrEnum):
    """Allowed provenance qualities for a numerical metric."""

    MEASURED = "measured"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


VALID_QUALITIES: frozenset[str] = frozenset(q.value for q in MetricQuality)


def format_utc_timestamp(dt: Optional[datetime] = None) -> str:
    """Format a datetime as a canonical ISO 8601 UTC string ending in 'Z'."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc_timestamp(ts: Union[str, datetime]) -> str:
    """Parse and normalize an ISO 8601 timestamp to a canonical UTC 'Z' string."""
    if isinstance(ts, datetime):
        return format_utc_timestamp(ts)
    if not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"Invalid timestamp: {ts!r}. Expected non-empty ISO 8601 string or datetime.")

    clean_ts = ts.strip()
    # Handle trailing Z
    if clean_ts.endswith("Z") or clean_ts.endswith("z"):
        iso_str = clean_ts[:-1] + "+00:00"
    else:
        iso_str = clean_ts

    try:
        parsed = datetime.fromisoformat(iso_str)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 timestamp {ts!r}: {exc}") from exc

    return format_utc_timestamp(parsed)


def is_safe_relative_path(path_str: str) -> bool:
    """
    Verify that a relative path does not escape its parent directory or point to an absolute location.

    Rejects:
    - Empty or whitespace paths
    - Embedded null bytes
    - Absolute POSIX (/path) or Windows (C:\\path, \\\\server\\share) paths
    - Traversal segments ('..')
    """
    if not isinstance(path_str, str) or not path_str.strip():
        return False
    if "\x00" in path_str:
        return False

    raw = path_str.strip()
    # Normalize forward/backward slashes for cross-platform checking
    norm = raw.replace("\\", "/")

    # Check absolute or UNC prefixes
    if norm.startswith("/") or norm.startswith("//"):
        return False

    # Check Windows drive letters
    posix_p = PurePosixPath(norm)
    win_p = PureWindowsPath(raw)
    if posix_p.is_absolute() or win_p.is_absolute():
        return False
    if win_p.drive:
        return False

    # Check for traversal components
    parts = norm.split("/")
    for part in parts:
        if part in ("..", ""):
            if part == "..":
                return False
            # consecutive slashes are redundant but we check for any escape
    return True


def validate_relative_path(path_str: str) -> str:
    """Validate and return normalized safe relative path, or raise ValueError."""
    if not is_safe_relative_path(path_str):
        raise ValueError(
            f"Unsafe or invalid relative path: {path_str!r}. "
            "Paths must be non-empty, relative, and must not escape the base directory."
        )
    return path_str.strip().replace("\\", "/")


def _assert_json_compatible(obj: Any, context: str) -> None:
    """Ensure an object is JSON serializable."""
    try:
        json.dumps(obj, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{context} must be JSON-serializable: {exc}") from exc


def _validate_evidence_references(details: dict[str, Any]) -> None:
    """Validate any evidence file references within details."""
    # Common keys for evidence files/paths
    for key in ("evidence", "evidence_files", "evidence_paths", "evidence_path"):
        if key in details:
            val = details[key]
            if isinstance(val, str):
                validate_relative_path(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        validate_relative_path(item)
                    elif isinstance(item, dict) and "path" in item and isinstance(item["path"], str):
                        validate_relative_path(item["path"])
            elif isinstance(val, dict):
                for item_k, item_v in val.items():
                    if isinstance(item_v, str):
                        validate_relative_path(item_v)


@dataclass(frozen=True, slots=True)
class MetricValue:
    """
    Represents a single numerical measurement or an explicit missing measurement.

    Attributes:
        value: Numerical value (int or float) or None if unavailable. NaN/Infinity are rejected.
        unit: Measurement unit string (e.g., 'ms', 'tokens', 'bytes', 'count').
        source: Provenance source string (e.g., 'timer', 'harness', 'api', 'derived').
        quality: Provenance quality ('measured', 'derived', 'estimated', 'unavailable').
        reason: Optional diagnostic string when value is missing or estimated.
    """

    value: Optional[Union[int, float]]
    unit: str
    source: str
    quality: Union[MetricQuality, str]
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        # Validate unit
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError(f"Metric unit must be a non-empty string, got {self.unit!r}")

        # Validate source
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(f"Metric source must be a non-empty string, got {self.source!r}")

        # Validate quality
        q_str = str(self.quality).lower().strip()
        if q_str not in VALID_QUALITIES:
            raise ValueError(
                f"Invalid metric quality {self.quality!r}. Allowed: {sorted(VALID_QUALITIES)}"
            )
        object.__setattr__(self, "quality", q_str)

        # Validate value
        if self.value is not None:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise TypeError(
                    f"Metric value must be an int or float, got {type(self.value).__name__} ({self.value!r})"
                )
            if math.isnan(self.value) or math.isinf(self.value):
                raise ValueError(f"Metric value cannot be NaN or Infinity, got {self.value}")
            if q_str == MetricQuality.UNAVAILABLE:
                raise ValueError(f"Unavailable metric cannot have numeric value {self.value!r}. Missing metrics must have value=None.")
        else:
            if q_str != MetricQuality.UNAVAILABLE:
                raise ValueError(
                    f"Missing metric with value=None must have quality='unavailable', got {self.quality!r}"
                )

        # Validate reason
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError(f"Metric reason must be a string or None, got {type(self.reason).__name__}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-compatible dictionary."""
        return {
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "quality": self.quality,
            "reason": self.reason,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricValue:
        """Deserialize from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for MetricValue, got {type(data).__name__}")
        required = {"value", "unit", "source", "quality"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for MetricValue: {sorted(missing)}")

        allowed_keys = {"value", "unit", "source", "quality", "reason"}
        extra = data.keys() - allowed_keys
        if extra:
            raise ValueError(f"Unexpected fields for MetricValue: {sorted(extra)}")

        return cls(
            value=data["value"],
            unit=data["unit"],
            source=data["source"],
            quality=data["quality"],
            reason=data.get("reason"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> MetricValue:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class TrialResult:
    """
    Represents one independent task/variant/repetition evaluation outcome.

    Attributes:
        run_id: Identifier of the parent benchmark batch.
        trial_id: Unique identifier for this trial.
        task_id: Benchmark task identifier.
        variant_id: Configuration variant identifier.
        repetition: 0-indexed or 1-indexed repetition counter (non-negative integer).
        status: Outcome status ('passed', 'failed', 'timed_out', 'infrastructure_error', 'unscored').
        metrics: Dotted or simple metric names mapped to MetricValue instances.
        details: Opaque consumer-specific dictionary (metadata, evidence paths, logs).
    """

    run_id: str
    trial_id: str
    task_id: str
    variant_id: str
    repetition: int
    status: Union[TrialStatus, str]
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for str_field, val in [
            ("run_id", self.run_id),
            ("trial_id", self.trial_id),
            ("task_id", self.task_id),
            ("variant_id", self.variant_id),
        ]:
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"TrialResult.{str_field} must be a non-empty string, got {val!r}")

        if isinstance(self.repetition, bool) or not isinstance(self.repetition, int) or self.repetition < 0:
            raise ValueError(f"TrialResult.repetition must be a non-negative int, got {self.repetition!r}")

        s_str = str(self.status).lower().strip()
        if s_str not in VALID_STATUSES:
            raise ValueError(f"Invalid trial status {self.status!r}. Allowed: {sorted(VALID_STATUSES)}")
        object.__setattr__(self, "status", s_str)

        # Validate metrics
        if not isinstance(self.metrics, dict):
            raise TypeError(f"TrialResult.metrics must be a dict, got {type(self.metrics).__name__}")
        normalized_metrics: dict[str, MetricValue] = {}
        for k, v in self.metrics.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"Metric key must be a non-empty string, got {k!r}")
            if isinstance(v, MetricValue):
                normalized_metrics[k] = v
            elif isinstance(v, dict):
                normalized_metrics[k] = MetricValue.from_dict(v)
            else:
                raise TypeError(
                    f"Metric value for {k!r} must be MetricValue or dict, got {type(v).__name__}"
                )
        object.__setattr__(self, "metrics", normalized_metrics)

        # Validate details
        if not isinstance(self.details, dict):
            raise TypeError(f"TrialResult.details must be a dict, got {type(self.details).__name__}")
        _assert_json_compatible(self.details, "TrialResult.details")
        _validate_evidence_references(self.details)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "trial_id": self.trial_id,
            "task_id": self.task_id,
            "variant_id": self.variant_id,
            "repetition": self.repetition,
            "status": self.status,
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
            "details": copy.deepcopy(self.details),
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialResult:
        """Deserialize from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for TrialResult, got {type(data).__name__}")
        required = {"run_id", "trial_id", "task_id", "variant_id", "repetition", "status", "metrics", "details"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for TrialResult: {sorted(missing)}")

        extra = data.keys() - required
        if extra:
            raise ValueError(f"Unexpected fields for TrialResult: {sorted(extra)}")

        metrics_raw = data["metrics"]
        if not isinstance(metrics_raw, dict):
            raise TypeError(f"metrics must be a dict, got {type(metrics_raw).__name__}")
        parsed_metrics = {
            k: v if isinstance(v, MetricValue) else MetricValue.from_dict(v)
            for k, v in metrics_raw.items()
        }

        return cls(
            run_id=data["run_id"],
            trial_id=data["trial_id"],
            task_id=data["task_id"],
            variant_id=data["variant_id"],
            repetition=data["repetition"],
            status=data["status"],
            metrics=parsed_metrics,
            details=data["details"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> TrialResult:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class RunInfo:
    """
    Represents a benchmark batch configuration and execution metadata.

    Attributes:
        run_id: Unique batch execution ID.
        created_at: ISO 8601 UTC timestamp string.
        suite_id: Identifier of the benchmark suite.
        suite_version: Version identifier of the suite.
        task_ids: List of evaluated task identifiers.
        variants: Mapping from variant IDs to opaque configuration dictionaries.
        repetitions: Number of planned repetitions per task/variant.
        scoring_basis: Specification of what success measures (e.g. 'worker_first_attempt_full_success').
        environment: Opaque system/environment metadata.
        metadata: Consumer-supplied metadata (must preserve suite fingerprint and randomization seed).
    """

    run_id: str
    created_at: str
    suite_id: str
    suite_version: str
    task_ids: list[str]
    variants: dict[str, dict[str, Any]]
    repetitions: int
    scoring_basis: str
    environment: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for str_field, val in [
            ("run_id", self.run_id),
            ("suite_id", self.suite_id),
            ("suite_version", self.suite_version),
            ("scoring_basis", self.scoring_basis),
        ]:
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"RunInfo.{str_field} must be a non-empty string, got {val!r}")

        # Normalize and validate created_at
        norm_created_at = parse_utc_timestamp(self.created_at)
        object.__setattr__(self, "created_at", norm_created_at)

        # Validate task_ids
        if not isinstance(self.task_ids, (list, tuple)):
            raise TypeError(f"RunInfo.task_ids must be a list of strings, got {type(self.task_ids).__name__}")
        task_id_list = [str(t) for t in self.task_ids]
        for t in task_id_list:
            if not t.strip():
                raise ValueError("RunInfo.task_ids contains empty or whitespace task ID")
        object.__setattr__(self, "task_ids", task_id_list)

        # Validate variants
        if not isinstance(self.variants, dict) or not self.variants:
            raise ValueError(f"RunInfo.variants must be a non-empty dict, got {self.variants!r}")
        for vk, vv in self.variants.items():
            if not isinstance(vk, str) or not vk.strip():
                raise ValueError(f"Variant ID must be a non-empty string, got {vk!r}")
            if not isinstance(vv, dict):
                raise TypeError(f"Configuration for variant {vk!r} must be a dict, got {type(vv).__name__}")
        _assert_json_compatible(self.variants, "RunInfo.variants")

        # Validate repetitions
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or self.repetitions < 1:
            raise ValueError(f"RunInfo.repetitions must be a positive int >= 1, got {self.repetitions!r}")

        # Validate environment
        if not isinstance(self.environment, dict):
            raise TypeError(f"RunInfo.environment must be a dict, got {type(self.environment).__name__}")
        _assert_json_compatible(self.environment, "RunInfo.environment")

        # Validate metadata
        if not isinstance(self.metadata, dict):
            raise TypeError(f"RunInfo.metadata must be a dict, got {type(self.metadata).__name__}")
        _assert_json_compatible(self.metadata, "RunInfo.metadata")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "task_ids": list(self.task_ids),
            "variants": copy.deepcopy(self.variants),
            "repetitions": self.repetitions,
            "scoring_basis": self.scoring_basis,
            "environment": copy.deepcopy(self.environment),
            "metadata": copy.deepcopy(self.metadata),
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunInfo:
        """Deserialize from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for RunInfo, got {type(data).__name__}")
        required = {
            "run_id",
            "created_at",
            "suite_id",
            "suite_version",
            "task_ids",
            "variants",
            "repetitions",
            "scoring_basis",
            "environment",
            "metadata",
        }
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for RunInfo: {sorted(missing)}")

        extra = data.keys() - required
        if extra:
            raise ValueError(f"Unexpected fields for RunInfo: {sorted(extra)}")

        return cls(
            run_id=data["run_id"],
            created_at=data["created_at"],
            suite_id=data["suite_id"],
            suite_version=data["suite_version"],
            task_ids=data["task_ids"],
            variants=data["variants"],
            repetitions=data["repetitions"],
            scoring_basis=data["scoring_basis"],
            environment=data["environment"],
            metadata=data["metadata"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> RunInfo:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """
    Configuration for a multi-run, multi-variant benchmark experiment.

    Attributes:
        experiment_id: Unique experiment identifier string.
        created_at: ISO 8601 UTC timestamp string.
        suite_id: Benchmark suite identifier.
        suite_version: Benchmark suite version string.
        task_ids: List of evaluated task identifiers.
        variant_ids: List of evaluated variant identifiers.
        repetitions: Planned repetitions per task/variant (>= 1).
        scoring_basis: Specification of what success measures.
        budget_profile: Budget profile name (e.g. 'canonical-60s').
        random_seed: Optional integer seed for reproducible scheduling.
        metadata: Consumer-supplied metadata dictionary.
    """

    experiment_id: str
    created_at: str
    suite_id: str
    suite_version: str
    task_ids: list[str]
    variant_ids: list[str]
    repetitions: int
    scoring_basis: str
    budget_profile: str
    random_seed: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for str_field, val in [
            ("experiment_id", self.experiment_id),
            ("suite_id", self.suite_id),
            ("suite_version", self.suite_version),
            ("scoring_basis", self.scoring_basis),
            ("budget_profile", self.budget_profile),
        ]:
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"ExperimentConfig.{str_field} must be a non-empty string, got {val!r}")

        norm_created_at = parse_utc_timestamp(self.created_at)
        object.__setattr__(self, "created_at", norm_created_at)

        if not isinstance(self.task_ids, (list, tuple)) or not self.task_ids:
            raise ValueError("ExperimentConfig.task_ids must be a non-empty list of strings")
        cleaned_tasks = [str(t) for t in self.task_ids]
        for t in cleaned_tasks:
            if not t.strip():
                raise ValueError("ExperimentConfig.task_ids contains empty or whitespace task ID")
        object.__setattr__(self, "task_ids", cleaned_tasks)

        if not isinstance(self.variant_ids, (list, tuple)) or not self.variant_ids:
            raise ValueError("ExperimentConfig.variant_ids must be a non-empty list of strings")
        cleaned_variants = [str(v) for v in self.variant_ids]
        for v in cleaned_variants:
            if not v.strip():
                raise ValueError("ExperimentConfig.variant_ids contains empty or whitespace variant ID")
        object.__setattr__(self, "variant_ids", cleaned_variants)

        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or self.repetitions < 1:
            raise ValueError(f"ExperimentConfig.repetitions must be a positive int >= 1, got {self.repetitions!r}")

        if self.random_seed is not None and (isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int)):
            raise TypeError(f"ExperimentConfig.random_seed must be an int or None, got {type(self.random_seed).__name__}")

        if not isinstance(self.metadata, dict):
            raise TypeError(f"ExperimentConfig.metadata must be a dict, got {type(self.metadata).__name__}")
        _assert_json_compatible(self.metadata, "ExperimentConfig.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "task_ids": list(self.task_ids),
            "variant_ids": list(self.variant_ids),
            "repetitions": self.repetitions,
            "scoring_basis": self.scoring_basis,
            "budget_profile": self.budget_profile,
            "random_seed": self.random_seed,
            "metadata": copy.deepcopy(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentConfig:
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for ExperimentConfig, got {type(data).__name__}")
        required = {
            "experiment_id",
            "created_at",
            "suite_id",
            "suite_version",
            "task_ids",
            "variant_ids",
            "repetitions",
            "scoring_basis",
            "budget_profile",
        }
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for ExperimentConfig: {sorted(missing)}")
        allowed = required | {"random_seed", "metadata"}
        extra = data.keys() - allowed
        if extra:
            raise ValueError(f"Unexpected fields for ExperimentConfig: {sorted(extra)}")

        return cls(
            experiment_id=data["experiment_id"],
            created_at=data["created_at"],
            suite_id=data["suite_id"],
            suite_version=data["suite_version"],
            task_ids=data["task_ids"],
            variant_ids=data["variant_ids"],
            repetitions=data["repetitions"],
            scoring_basis=data["scoring_basis"],
            budget_profile=data["budget_profile"],
            random_seed=data.get("random_seed"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> ExperimentConfig:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class ExperimentRunRef:
    """
    Immutable reference to a constituent run within an experiment.

    Attributes:
        run_id: Unique batch execution ID of the constituent run.
        run_dir: Directory or safe relative path where the run artifacts reside.
        variant_id: Configuration variant identifier evaluated by this run.
        suite_id: Identifier of the benchmark suite.
        suite_version: Version identifier of the suite.
        scoring_basis: Specification of what success measures.
        budget_profile: Budget profile name.
        comparison_eligible: Whether this run meets canonical comparison criteria.
        exclusion_reasons: Explicit list of reasons if comparison_eligible is False.
        metadata: Consumer-supplied metadata.
    """

    run_id: str
    run_dir: str
    variant_id: str
    suite_id: str
    suite_version: str
    scoring_basis: str
    budget_profile: str
    comparison_eligible: bool
    exclusion_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for str_field, val in [
            ("run_id", self.run_id),
            ("run_dir", self.run_dir),
            ("variant_id", self.variant_id),
            ("suite_id", self.suite_id),
            ("suite_version", self.suite_version),
            ("scoring_basis", self.scoring_basis),
            ("budget_profile", self.budget_profile),
        ]:
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"ExperimentRunRef.{str_field} must be a non-empty string, got {val!r}")

        if not isinstance(self.comparison_eligible, bool):
            raise TypeError(
                f"ExperimentRunRef.comparison_eligible must be a bool, got {type(self.comparison_eligible).__name__}"
            )

        if not isinstance(self.exclusion_reasons, (list, tuple)):
            raise TypeError(
                f"ExperimentRunRef.exclusion_reasons must be a list of strings, got {type(self.exclusion_reasons).__name__}"
            )
        clean_reasons = [str(r).strip() for r in self.exclusion_reasons if str(r).strip()]
        object.__setattr__(self, "exclusion_reasons", clean_reasons)

        if not isinstance(self.metadata, dict):
            raise TypeError(f"ExperimentRunRef.metadata must be a dict, got {type(self.metadata).__name__}")
        _assert_json_compatible(self.metadata, "ExperimentRunRef.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "variant_id": self.variant_id,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "scoring_basis": self.scoring_basis,
            "budget_profile": self.budget_profile,
            "comparison_eligible": self.comparison_eligible,
            "exclusion_reasons": list(self.exclusion_reasons),
            "metadata": copy.deepcopy(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRunRef:
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for ExperimentRunRef, got {type(data).__name__}")
        required = {
            "run_id",
            "run_dir",
            "variant_id",
            "suite_id",
            "suite_version",
            "scoring_basis",
            "budget_profile",
            "comparison_eligible",
        }
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for ExperimentRunRef: {sorted(missing)}")
        allowed = required | {"exclusion_reasons", "metadata"}
        extra = data.keys() - allowed
        if extra:
            raise ValueError(f"Unexpected fields for ExperimentRunRef: {sorted(extra)}")

        return cls(
            run_id=data["run_id"],
            run_dir=data["run_dir"],
            variant_id=data["variant_id"],
            suite_id=data["suite_id"],
            suite_version=data["suite_version"],
            scoring_basis=data["scoring_basis"],
            budget_profile=data["budget_profile"],
            comparison_eligible=data["comparison_eligible"],
            exclusion_reasons=data.get("exclusion_reasons", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> ExperimentRunRef:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class Experiment:
    """
    Top-level container for an experiment manifest and its constituent runs.

    Attributes:
        config: Experiment configuration and provenance.
        run_refs: List of immutable references to constituent runs.
        metadata: Consumer-supplied metadata.
    """

    config: ExperimentConfig
    run_refs: list[ExperimentRunRef]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.config, ExperimentConfig):
            raise TypeError(
                f"Experiment.config must be an ExperimentConfig instance, got {type(self.config).__name__}"
            )

        if not isinstance(self.run_refs, (list, tuple)):
            raise TypeError(
                f"Experiment.run_refs must be a list of ExperimentRunRef, got {type(self.run_refs).__name__}"
            )
        for ref in self.run_refs:
            if not isinstance(ref, ExperimentRunRef):
                raise TypeError(
                    f"Items in Experiment.run_refs must be ExperimentRunRef, got {type(ref).__name__}"
                )
        object.__setattr__(self, "run_refs", list(self.run_refs))

        if not isinstance(self.metadata, dict):
            raise TypeError(f"Experiment.metadata must be a dict, got {type(self.metadata).__name__}")
        _assert_json_compatible(self.metadata, "Experiment.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "run_refs": [ref.to_dict() for ref in self.run_refs],
            "metadata": copy.deepcopy(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Experiment:
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for Experiment, got {type(data).__name__}")
        required = {"config", "run_refs"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing required fields for Experiment: {sorted(missing)}")
        allowed = required | {"metadata"}
        extra = data.keys() - allowed
        if extra:
            raise ValueError(f"Unexpected fields for Experiment: {sorted(extra)}")

        config_data = data["config"]
        config = (
            config_data
            if isinstance(config_data, ExperimentConfig)
            else ExperimentConfig.from_dict(config_data)
        )

        raw_refs = data["run_refs"]
        if not isinstance(raw_refs, list):
            raise TypeError(f"run_refs must be a list, got {type(raw_refs).__name__}")
        parsed_refs = [
            r if isinstance(r, ExperimentRunRef) else ExperimentRunRef.from_dict(r)
            for r in raw_refs
        ]

        return cls(
            config=config,
            run_refs=parsed_refs,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Experiment:
        return cls.from_dict(json.loads(json_str))


# Top-level functional serialization helpers for module convenience
def metric_value_to_dict(mv: MetricValue) -> dict[str, Any]:
    return mv.to_dict()


def metric_value_from_dict(d: dict[str, Any]) -> MetricValue:
    return MetricValue.from_dict(d)


def metric_value_to_json(mv: MetricValue) -> str:
    return mv.to_json()


def metric_value_from_json(s: str) -> MetricValue:
    return MetricValue.from_json(s)


def trial_result_to_dict(tr: TrialResult) -> dict[str, Any]:
    return tr.to_dict()


def trial_result_from_dict(d: dict[str, Any]) -> TrialResult:
    return TrialResult.from_dict(d)


def trial_result_to_json(tr: TrialResult) -> str:
    return tr.to_json()


def trial_result_from_json(s: str) -> TrialResult:
    return TrialResult.from_json(s)


def run_info_to_dict(ri: RunInfo) -> dict[str, Any]:
    return ri.to_dict()


def run_info_from_dict(d: dict[str, Any]) -> RunInfo:
    return RunInfo.from_dict(d)


def run_info_to_json(ri: RunInfo) -> str:
    return ri.to_json()


def run_info_from_json(s: str) -> RunInfo:
    return RunInfo.from_json(s)


def experiment_config_to_dict(ec: ExperimentConfig) -> dict[str, Any]:
    return ec.to_dict()


def experiment_config_from_dict(d: dict[str, Any]) -> ExperimentConfig:
    return ExperimentConfig.from_dict(d)


def experiment_config_to_json(ec: ExperimentConfig) -> str:
    return ec.to_json()


def experiment_config_from_json(s: str) -> ExperimentConfig:
    return ExperimentConfig.from_json(s)


def experiment_run_ref_to_dict(ref: ExperimentRunRef) -> dict[str, Any]:
    return ref.to_dict()


def experiment_run_ref_from_dict(d: dict[str, Any]) -> ExperimentRunRef:
    return ExperimentRunRef.from_dict(d)


def experiment_run_ref_to_json(ref: ExperimentRunRef) -> str:
    return ref.to_json()


def experiment_run_ref_from_json(s: str) -> ExperimentRunRef:
    return ExperimentRunRef.from_json(s)


def experiment_to_dict(exp: Experiment) -> dict[str, Any]:
    return exp.to_dict()


def experiment_from_dict(d: dict[str, Any]) -> Experiment:
    return Experiment.from_dict(d)


def experiment_to_json(exp: Experiment) -> str:
    return exp.to_json()


def experiment_from_json(s: str) -> Experiment:
    return Experiment.from_json(s)
