"""Harbor integration for deterministic external benchmark evaluation."""

from .datasets import (
    AIDER_POLYGLOT_TASKS,
    DATASETS,
    TERMINAL_BENCH_CPU_TASKS,
    DatasetDescriptor,
    resolve_dataset,
    select_tasks,
)
from .importer import HarborImporter, HarborImportError
from .models import (
    FailureCause,
    HarborJobLock,
    HarborJobResult,
    HarborTrialResult,
    StatusEvaluation,
    evaluate_trial_status,
)
from .planner import (
    BenchmarkPlan,
    ReadinessCheck,
    SUPPORTED_HARBOR_AGENTS,
    check_docker_readiness,
    check_harbor_readiness,
    plan_benchmark,
    verify_agent_readiness,
)
from .reporting import collect_run_summaries, render_leaderboard_table
from .runner import (
    ExecutionAuthorizationError,
    PreflightCheckError,
    build_harbor_command,
    execute_harbor_run,
)

__all__ = [
    "AIDER_POLYGLOT_TASKS",
    "DATASETS",
    "TERMINAL_BENCH_CPU_TASKS",
    "DatasetDescriptor",
    "resolve_dataset",
    "select_tasks",
    "HarborImporter",
    "HarborImportError",
    "FailureCause",
    "HarborJobLock",
    "HarborJobResult",
    "HarborTrialResult",
    "StatusEvaluation",
    "evaluate_trial_status",
    "BenchmarkPlan",
    "ReadinessCheck",
    "SUPPORTED_HARBOR_AGENTS",
    "check_docker_readiness",
    "check_harbor_readiness",
    "plan_benchmark",
    "verify_agent_readiness",
    "collect_run_summaries",
    "render_leaderboard_table",
    "ExecutionAuthorizationError",
    "PreflightCheckError",
    "build_harbor_command",
    "execute_harbor_run",
]
