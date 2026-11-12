"""Harbor execution backend adapter for containerized agent evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .contract import BackendAttempt, ExecutionPlan, TaskContext


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HarborExecutionBackend:
    """Executes agentic benchmarks using the Harbor evaluation runner."""

    backend_id = "harbor"

    def execute_task(
        self,
        task_id: str,
        context: TaskContext,
        plan: ExecutionPlan,
    ) -> BackendAttempt:
        """Execute a single task through Harbor."""
        from ..harbor import execute_harbor_run, plan_benchmark

        started_at = _now_iso()
        t0 = time.monotonic()

        output_dir = Path(plan.metadata.get("output_dir", "results")).resolve()
        jobs_dir = Path(plan.metadata.get("jobs_dir", "harbor-jobs")).resolve()
        registry_path = plan.metadata.get("registry_path")

        harbor_plan = plan_benchmark(
            plan.dataset_id,
            agent=plan.metadata.get("agent", "opencode"),
            model=plan.model_id,
            base_url=plan.base_url,
            model_api_format=plan.api_format,
            task_ids=[task_id],
            repetitions=1,
            seed=plan.seed,
        )

        saved, summary = execute_harbor_run(
            harbor_plan,
            execute=True,
            output_dir=output_dir,
            jobs_dir=jobs_dir,
            n_concurrent=1,
            quiet=True,
            registry_path=Path(registry_path) if registry_path else None,
        )

        duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
        ended_at = _now_iso()

        status = "completed"
        error_code = None
        error_detail = None
        if summary.get("infrastructure_error", 0):
            status = "error"
            error_code = "HARBOR_INFRASTRUCTURE_ERROR"
            error_detail = "Harbor reported infrastructure failure during task execution"

        trials_file = saved / "trials.jsonl"
        response_text = ""
        trial_id = None
        if trials_file.is_file():
            for line in trials_file.read_text(encoding="utf-8").splitlines():
                trial = json.loads(line)
                if trial.get("task_id") == task_id:
                    trial_id = trial.get("trial_id")
                    response_text = trial.get("details", {}).get("solution_text", "")
                    break

        return BackendAttempt(
            task_id=task_id,
            model_id=plan.model_id or "unknown",
            endpoint=plan.base_url or "harbor",
            response_text=response_text,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status=status,
            scratch_dir=str(saved),
            raw_response={"trial_id": trial_id, "summary": summary},
            error_code=error_code,
            error_detail=error_detail,
        )
