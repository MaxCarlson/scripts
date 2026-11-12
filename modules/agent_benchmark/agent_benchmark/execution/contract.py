"""Execution contracts, attempt representations, and normalization interfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable, hashable configuration for benchmark suite execution."""

    backend_id: str  # "harbor" | "direct_chat" | "mock"
    benchmark_id: str
    dataset_id: str
    task_ids: tuple[str, ...]
    cohort_id: str | None = None
    source_revision: str | None = None
    scorer_id: str = "mock_scorer"
    model_id: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_format: str | None = None
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int | None = None
    seed: int | None = None
    timeout_seconds: float = 120.0
    sandbox_policy: str = "isolated"
    metadata: dict[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_ids"] = list(self.task_ids)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPlan:
        d = dict(data)
        d["task_ids"] = tuple(d.get("task_ids", ()))
        return cls(**d)


@dataclass(frozen=True)
class TaskContext:
    """Frozen input context and budget for executing a single benchmark task."""

    task_id: str
    prompt: str
    system_prompt: str | None = None
    input_files: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    expected_output_type: str = "text"  # "text" | "code"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackendAttempt:
    """Raw model generation artifact, telemetry, and execution metadata."""

    task_id: str
    model_id: str
    endpoint: str
    response_text: str
    started_at: str
    ended_at: str
    duration_ms: float
    status: str  # "completed" | "timed_out" | "error"
    input_tokens: int = 0
    output_tokens: int = 0
    request_ids: tuple[str, ...] = ()
    raw_response: dict[str, Any] = field(default_factory=dict)
    scratch_dir: str | None = None
    error_code: str | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["request_ids"] = list(self.request_ids)
        return data


@dataclass(frozen=True)
class ScoredAttempt:
    """Authoritative scorer-native outcome and metrics."""

    task_id: str
    scorer_id: str
    status: str  # "passed" | "failed" | "timed_out" | "infrastructure_invalid"
    score: float  # 0.0 to 1.0
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionBackend(Protocol):
    """Protocol for executing task attempts against a model or harness."""

    backend_id: str

    def execute_task(
        self,
        task_id: str,
        context: TaskContext,
        plan: ExecutionPlan,
    ) -> BackendAttempt: ...


class ScoringAdapter(Protocol):
    """Protocol for scoring a task attempt using an authoritative evaluation method."""

    scorer_id: str

    def score_task(
        self,
        task_id: str,
        attempt: BackendAttempt,
        context: TaskContext,
    ) -> ScoredAttempt: ...


class ResultNormalizer:
    """Normalizes scored attempts into stable persistence formats."""

    @staticmethod
    def to_store_task_record(
        scored: ScoredAttempt,
        attempt: BackendAttempt | None = None,
    ) -> dict[str, Any]:
        """Convert a ScoredAttempt and optional BackendAttempt into a RunStore task update dict."""
        record: dict[str, Any] = {
            "status": scored.status,
            "score": scored.score,
            "metrics": scored.metrics,
            "details": scored.details,
            "ended_at": _now_iso(),
        }
        if scored.error_code:
            record["error_code"] = scored.error_code
            record["error_detail"] = scored.error_detail

        if attempt is not None:
            record["duration_wall_ms"] = attempt.duration_ms
            record["started_at"] = attempt.started_at
            if attempt.request_ids:
                record["monitor_request_ids"] = list(attempt.request_ids)
            if attempt.input_tokens or attempt.output_tokens:
                record["token_counts"] = {
                    "input": attempt.input_tokens,
                    "output": attempt.output_tokens,
                }
            if attempt.error_code and not scored.error_code:
                record["error_code"] = attempt.error_code
                record["error_detail"] = attempt.error_detail

        return record
