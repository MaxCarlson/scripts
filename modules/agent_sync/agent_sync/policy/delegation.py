"""Delegation policy and routing heuristics."""

from agent_sync.config import AgentSyncConfig, WorkerSpec
from agent_sync.errors import ConfigError, PolicyError
from agent_sync.tasks import DelegationTask

TOKEN_HEAVY_TASKS = {"research", "summarize", "extract", "brainstorm", "log-triage"}
HIGH_STAKES_TASKS = {"review", "verify"}
LOCAL_FRIENDLY_TASKS = {"summarize", "extract", "classify", "log-triage", "brainstorm"}


def enforce_external_policy(*, allow_external: bool, worker: WorkerSpec) -> None:
    """Raise if policy forbids invoking the chosen worker."""
    if allow_external:
        return
    raise PolicyError(
        f"External worker invocation is disabled. Planned worker: {worker.name}. "
        "Re-run with -E/--allow-external after reviewing the prompt."
    )


def select_worker(config: AgentSyncConfig, task: DelegationTask, preferred: str | None = None) -> WorkerSpec:
    """Select a worker for a task using conservative local-first heuristics."""
    if preferred and preferred != "auto":
        worker = config.get_worker(preferred)
        if not worker.enabled:
            raise ConfigError(f"Worker '{preferred}' is configured but disabled.")
        return worker

    enabled = config.enabled_workers()
    if not enabled:
        raise ConfigError("No enabled workers are configured.")

    if task.high_stakes or task.task_type in HIGH_STAKES_TASKS:
        candidates = [worker for worker in enabled if worker.capability_score >= 0.85 and worker.name != "local-lmstudio"]
        if candidates:
            return sorted(candidates, key=lambda worker: (-worker.capability_score, worker.rate_limited, worker.name))[0]

    if task.task_type in LOCAL_FRIENDLY_TASKS:
        for worker in enabled:
            if worker.kind == "local":
                return worker

    if task.task_type in TOKEN_HEAVY_TASKS:
        low_cost = [worker for worker in enabled if not worker.rate_limited or worker.cost.startswith("local")]
        if low_cost:
            return sorted(low_cost, key=lambda worker: (-worker.capability_score, worker.name))[0]

    try:
        default_worker = config.get_worker(config.default_worker)
        if default_worker.enabled:
            return default_worker
    except ConfigError:
        pass

    return sorted(enabled, key=lambda worker: (-worker.capability_score, worker.name))[0]
