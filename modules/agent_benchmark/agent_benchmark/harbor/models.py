"""Pydantic data models and status evaluation for Harbor evaluation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FailureCause(StrEnum):
    """Categorization of failure causes matching Harbor's ErrorPolicy."""

    SANDBOX_FAILED = "sandbox_failed"
    MODEL_PROVIDER_FAILED = "model_provider_failed"
    HARBOR_FAILED = "harbor_failed"
    UNCLASSIFIED = "unclassified"
    AGENT_EXHAUSTED_BUDGET = "agent_exhausted_budget"
    AGENT_REFUSED_TASK = "agent_refused_task"
    VERIFIER_FAILED = "verifier_failed"
    CANCELLED = "cancelled"


# Error policies mapping exception type name to FailureCause and validity
ERROR_TYPE_TO_CAUSE: dict[str, FailureCause] = {
    # Sandbox / container infrastructure
    "EnvironmentStartTimeoutError": FailureCause.SANDBOX_FAILED,
    "SandboxBuildFailedError": FailureCause.SANDBOX_FAILED,
    "AgentSetupTimeoutError": FailureCause.SANDBOX_FAILED,
    "HealthcheckError": FailureCause.SANDBOX_FAILED,
    "SandboxLikelyOutOfMemoryError": FailureCause.SANDBOX_FAILED,
    "MemoryLimitExceededError": FailureCause.SANDBOX_FAILED,
    "SSHAccessError": FailureCause.SANDBOX_FAILED,
    "GKEExecStreamClosedError": FailureCause.SANDBOX_FAILED,
    "GKEPodNotFoundError": FailureCause.SANDBOX_FAILED,
    "RuntimeRequestError": FailureCause.SANDBOX_FAILED,
    "AddTestsDirError": FailureCause.SANDBOX_FAILED,
    "DownloadVerifierDirError": FailureCause.SANDBOX_FAILED,
    "DockerError": FailureCause.SANDBOX_FAILED,
    "ContainerError": FailureCause.SANDBOX_FAILED,
    # Model provider / API infrastructure
    "ApiError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiRateLimitError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiInternalServerError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiOverloadedError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiConnectionClosedError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiResponseStalledError": FailureCause.MODEL_PROVIDER_FAILED,
    "UnknownApiError": FailureCause.MODEL_PROVIDER_FAILED,
    "NetworkConnectionError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiConnectionError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiUsageLimitError": FailureCause.MODEL_PROVIDER_FAILED,
    "RateLimitError": FailureCause.MODEL_PROVIDER_FAILED,
    "InternalServerError": FailureCause.MODEL_PROVIDER_FAILED,
    "ServiceUnavailableError": FailureCause.MODEL_PROVIDER_FAILED,
    "APIConnectionError": FailureCause.MODEL_PROVIDER_FAILED,
    "APIError": FailureCause.MODEL_PROVIDER_FAILED,
    "Timeout": FailureCause.MODEL_PROVIDER_FAILED,
    "BadRequestError": FailureCause.MODEL_PROVIDER_FAILED,
    "UnprocessableEntityError": FailureCause.MODEL_PROVIDER_FAILED,
    "UnsupportedParamsError": FailureCause.MODEL_PROVIDER_FAILED,
    "APIResponseValidationError": FailureCause.MODEL_PROVIDER_FAILED,
    "BudgetExceededError": FailureCause.MODEL_PROVIDER_FAILED,
    "AgentAuthenticationError": FailureCause.MODEL_PROVIDER_FAILED,
    "ModelNotFoundError": FailureCause.MODEL_PROVIDER_FAILED,
    "ApiProviderResourceNotFoundError": FailureCause.MODEL_PROVIDER_FAILED,
    "AuthenticationError": FailureCause.MODEL_PROVIDER_FAILED,
    "PermissionDeniedError": FailureCause.MODEL_PROVIDER_FAILED,
    "NotFoundError": FailureCause.MODEL_PROVIDER_FAILED,
    # Harbor framework
    "ServiceOperationsUnsupportedError": FailureCause.HARBOR_FAILED,
    "VercelScopeError": FailureCause.HARBOR_FAILED,
    "DspyImportError": FailureCause.HARBOR_FAILED,
    "MissingExtraError": FailureCause.HARBOR_FAILED,
    "RegradeError": FailureCause.HARBOR_FAILED,
    # Agent budget / exhaustion
    "AgentTimeoutError": FailureCause.AGENT_EXHAUSTED_BUDGET,
    "ContextWindowExceededError": FailureCause.AGENT_EXHAUSTED_BUDGET,
    "OutputTokenExceededError": FailureCause.AGENT_EXHAUSTED_BUDGET,
    "ContextLengthExceededError": FailureCause.AGENT_EXHAUSTED_BUDGET,
    "OutputLengthExceededError": FailureCause.AGENT_EXHAUSTED_BUDGET,
    # Agent refusal
    "AgentSafetyRefusalError": FailureCause.AGENT_REFUSED_TASK,
    "ContentPolicyViolationError": FailureCause.AGENT_REFUSED_TASK,
    # Verifier failure
    "VerifierTimeoutError": FailureCause.VERIFIER_FAILED,
    "RewardFileNotFoundError": FailureCause.VERIFIER_FAILED,
    "RewardFileEmptyError": FailureCause.VERIFIER_FAILED,
    "VerifierOutputParseError": FailureCause.VERIFIER_FAILED,
    # Cancellation
    "CancelledError": FailureCause.CANCELLED,
}


def classify_exception_type(exc_type: str | None) -> FailureCause:
    if not exc_type:
        return FailureCause.UNCLASSIFIED
    return ERROR_TYPE_TO_CAUSE.get(exc_type, FailureCause.UNCLASSIFIED)


class TimingInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExceptionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exception_type: str
    exception_message: str
    exception_traceback: str | None = None
    occurred_at: datetime | None = None

    @property
    def failure_cause(self) -> FailureCause:
        return classify_exception_type(self.exception_type)


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    provider: str | None = None


class AgentInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    version: str | None = None
    model_info: ModelInfo | None = None


class VerifierResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rewards: dict[str, float | int] | None = None


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n_input_tokens: int | None = None
    n_cache_tokens: int | None = None
    n_output_tokens: int | None = None
    cost_usd: float | None = None


class StepResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_name: str | None = None
    agent_result: AgentContext | None = None
    verifier_result: VerifierResult | None = None
    exception_info: ExceptionInfo | None = None
    agent_execution: TimingInfo | None = None
    verifier: TimingInfo | None = None


class HarborTrialResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    task_name: str
    trial_name: str
    trial_uri: str | None = None
    task_id: Any = None
    source: str | None = None
    task_checksum: str | None = None
    config: dict[str, Any] | None = None
    agent_info: AgentInfo
    agent_result: AgentContext | None = None
    verifier_result: VerifierResult | None = None
    verifier_environment_mode: str | None = None
    exception_info: ExceptionInfo | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    environment_setup: TimingInfo | None = None
    agent_setup: TimingInfo | None = None
    agent_execution: TimingInfo | None = None
    verifier: TimingInfo | None = None
    step_results: list[StepResult] | None = None

    def compute_token_cost_totals(
        self,
    ) -> tuple[int | None, int | None, int | None, float | None]:
        contexts: list[AgentContext] = []
        if self.agent_result is not None:
            contexts.append(self.agent_result)
        elif self.step_results:
            contexts.extend([s.agent_result for s in self.step_results if s.agent_result is not None])

        if not contexts:
            return None, None, None, None

        n_input: int | None = None
        n_cache: int | None = None
        n_output: int | None = None
        cost: float | None = None
        for ctx in contexts:
            if ctx.n_input_tokens is not None:
                n_input = (n_input or 0) + ctx.n_input_tokens
            if ctx.n_cache_tokens is not None:
                n_cache = (n_cache or 0) + ctx.n_cache_tokens
            if ctx.n_output_tokens is not None:
                n_output = (n_output or 0) + ctx.n_output_tokens
            if ctx.cost_usd is not None:
                cost = (cost or 0.0) + ctx.cost_usd
        return n_input, n_cache, n_output, cost


class AgentDatasetStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n_trials: int = 0
    n_errors: int = 0
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class JobStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n_completed_trials: int = 0
    n_errored_trials: int = 0
    n_running_trials: int = 0
    n_pending_trials: int = 0
    n_cancelled_trials: int = 0
    n_retries: int = 0
    evals: dict[str, Any] = Field(default_factory=dict)
    n_input_tokens: int | None = None
    n_cache_tokens: int | None = None
    n_output_tokens: int | None = None
    cost_usd: float | None = None


class HarborJobResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    started_at: datetime
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    n_total_trials: int = 0
    stats: JobStats | dict[str, Any] = Field(default_factory=JobStats)
    trial_results: list[HarborTrialResult] = Field(default_factory=list)


# --- Lock files ---


class HarborLockInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str | None = None
    git_commit_hash: str | None = None
    is_editable: bool | None = None


class TaskLock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    version: str | None = None
    type: str = "local"
    digest: str | None = None
    source: str | None = None
    git_url: str | None = None
    git_commit_id: str | None = None


class TrialLock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = 2
    task: TaskLock | None = None
    agent: dict[str, Any] | None = None
    verifier: dict[str, Any] | None = None


class HarborJobLock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = 3
    created_at: datetime | None = None
    harbor: HarborLockInfo = Field(default_factory=HarborLockInfo)
    n_concurrent_trials: int | None = None
    retry: dict[str, Any] | None = None
    trials: list[TrialLock] | dict[str, TrialLock] = Field(default_factory=list)

    def task_digests(self) -> dict[str, str]:
        """Map task name to its content digest if recorded."""
        result: dict[str, str] = {}
        trial_list: list[TrialLock] = []
        if isinstance(self.trials, list):
            trial_list = self.trials
        elif isinstance(self.trials, dict):
            trial_list = list(self.trials.values())

        for trial in trial_list:
            if trial.task and trial.task.name and trial.task.digest:
                result[trial.task.name] = trial.task.digest
        return result


# --- Status Evaluation ---


@dataclass(frozen=True)
class StatusEvaluation:
    """Normalized evaluation status and awarded points for benchmark_core."""

    canonical_status: str  # "passed", "failed", "timed_out", "infrastructure_error", "unscored"
    points_awarded: float | None  # 1.0, 0.0, or None (unavailable)
    primary_reward: float | None
    scoring_basis: str
    diagnostics: str
    failure_cause: str | None


def evaluate_trial_status(trial: HarborTrialResult) -> StatusEvaluation:
    """Evaluate authoritative outcome according to Section 7.1 and 8 of the specification."""
    scoring_basis = "external_verifier_pass_v1"

    # 1. Check for trial-level or step-level exceptions
    exc = trial.exception_info
    if exc is None and trial.step_results:
        for s in trial.step_results:
            if s.exception_info is not None:
                exc = s.exception_info
                break

    if exc is not None:
        cause = exc.failure_cause
        if cause == FailureCause.AGENT_EXHAUSTED_BUDGET:
            return StatusEvaluation(
                canonical_status="timed_out",
                points_awarded=0.0,
                primary_reward=0.0,
                scoring_basis=scoring_basis,
                diagnostics=f"Agent exhausted budget: {exc.exception_type} - {exc.exception_message}",
                failure_cause=cause.value,
            )
        elif cause == FailureCause.AGENT_REFUSED_TASK:
            return StatusEvaluation(
                canonical_status="failed",
                points_awarded=0.0,
                primary_reward=0.0,
                scoring_basis=scoring_basis,
                diagnostics=f"Agent refused task: {exc.exception_type} - {exc.exception_message}",
                failure_cause=cause.value,
            )
        elif cause == FailureCause.CANCELLED:
            return StatusEvaluation(
                canonical_status="unscored",
                points_awarded=None,
                primary_reward=None,
                scoring_basis=scoring_basis,
                diagnostics=f"Trial cancelled: {exc.exception_type}",
                failure_cause=cause.value,
            )
        else:
            # SANDBOX_FAILED, MODEL_PROVIDER_FAILED, HARBOR_FAILED, VERIFIER_FAILED, UNCLASSIFIED
            return StatusEvaluation(
                canonical_status="infrastructure_error",
                points_awarded=None,
                primary_reward=None,
                scoring_basis=scoring_basis,
                diagnostics=f"Infrastructure failure ({cause.value}): {exc.exception_type} - {exc.exception_message}",
                failure_cause=cause.value,
            )

    # 2. Check verifier output
    v_res = trial.verifier_result
    if v_res is None or v_res.rewards is None or not v_res.rewards:
        return StatusEvaluation(
            canonical_status="infrastructure_error",
            points_awarded=None,
            primary_reward=None,
            scoring_basis=scoring_basis,
            diagnostics="Verifier result or rewards missing",
            failure_cause=FailureCause.VERIFIER_FAILED.value,
        )

    # Determine primary reward from authoritative keys
    rewards = v_res.rewards
    reward_val: float | None = None
    authoritative_keys = ("reward", "score", "acc", "accuracy")
    for key in authoritative_keys:
        if key in rewards:
            reward_val = float(rewards[key])
            break

    if reward_val is None:
        if len(rewards) == 1:
            reward_val = float(next(iter(rewards.values())))
        else:
            return StatusEvaluation(
                canonical_status="infrastructure_error",
                points_awarded=None,
                primary_reward=None,
                scoring_basis=scoring_basis,
                diagnostics=f"Multi-dimensional rewards {list(rewards.keys())} without recognized authoritative key ('reward', 'score', 'acc')",
                failure_cause=FailureCause.VERIFIER_FAILED.value,
            )

    # Check for non-finite values (NaN or Inf)
    if math.isnan(reward_val) or math.isinf(reward_val):
        return StatusEvaluation(
            canonical_status="infrastructure_error",
            points_awarded=None,
            primary_reward=None,
            scoring_basis=scoring_basis,
            diagnostics=f"Verifier returned non-finite reward ({reward_val})",
            failure_cause=FailureCause.VERIFIER_FAILED.value,
        )

    # Authoritative binary scoring rule: 1.0 is verified success, anything less is failure
    if reward_val >= 1.0:
        return StatusEvaluation(
            canonical_status="passed",
            points_awarded=1.0,
            primary_reward=reward_val,
            scoring_basis=scoring_basis,
            diagnostics="Verifier confirmed success",
            failure_cause=None,
        )
    elif reward_val <= 0.0:
        return StatusEvaluation(
            canonical_status="failed",
            points_awarded=0.0,
            primary_reward=reward_val,
            scoring_basis=scoring_basis,
            diagnostics="Verifier confirmed failure",
            failure_cause=None,
        )
    else:
        # Fractional reward: In binary-scored coding benchmarks, partial solutions do not earn a pass
        return StatusEvaluation(
            canonical_status="failed",
            points_awarded=0.0,
            primary_reward=reward_val,
            scoring_basis=scoring_basis,
            diagnostics=f"Verifier fractional reward: {reward_val} (binary scoring awards 0.0)",
            failure_cause=None,
        )
