"""Deterministic mock execution backend and scoring adapter for offline verification."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from .contract import BackendAttempt, ExecutionPlan, ScoredAttempt, TaskContext


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockExecutionBackend:
    """Deterministic mock backend that simulates model responses without network or inference."""

    backend_id = "mock"

    def __init__(
        self,
        canned_responses: dict[str, str] | None = None,
        simulate_timeout: set[str] | None = None,
        simulate_error: set[str] | None = None,
    ) -> None:
        self.canned_responses = canned_responses or {}
        self.simulate_timeout = simulate_timeout or set()
        self.simulate_error = simulate_error or set()
        self.call_history: list[dict[str, Any]] = []

    def execute_task(
        self,
        task_id: str,
        context: TaskContext,
        plan: ExecutionPlan,
    ) -> BackendAttempt:
        started_at = _now_iso()
        t0 = time.monotonic()
        self.call_history.append({
            "task_id": task_id,
            "prompt": context.prompt,
            "model_id": plan.model_id,
            "endpoint": plan.base_url or "http://127.0.0.1:8000/v1",
        })

        if task_id in self.simulate_timeout:
            return BackendAttempt(
                task_id=task_id,
                model_id=plan.model_id or "mock-model",
                endpoint=plan.base_url or "http://127.0.0.1:8000/v1",
                response_text="",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=50.0,
                status="timed_out",
                request_ids=(f"mock-req-{task_id}",),
                error_code="INFERENCE_TIMEOUT",
                error_detail="Simulated task timeout",
            )

        if task_id in self.simulate_error:
            return BackendAttempt(
                task_id=task_id,
                model_id=plan.model_id or "mock-model",
                endpoint=plan.base_url or "http://127.0.0.1:8000/v1",
                response_text="",
                started_at=started_at,
                ended_at=_now_iso(),
                duration_ms=20.0,
                status="error",
                request_ids=(f"mock-req-{task_id}",),
                error_code="INFERENCE_HTTP_ERROR",
                error_detail="Simulated server error 500",
            )

        response_text = self.canned_responses.get(
            task_id,
            f"Mock response for task {task_id} with prompt {context.prompt[:40]!r}",
        )
        duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
        in_tokens = len(context.prompt.split())
        out_tokens = len(response_text.split())

        return BackendAttempt(
            task_id=task_id,
            model_id=plan.model_id or "mock-model",
            endpoint=plan.base_url or "http://127.0.0.1:8000/v1",
            response_text=response_text,
            started_at=started_at,
            ended_at=_now_iso(),
            duration_ms=max(duration_ms, 5.0),
            status="completed",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            request_ids=(f"mock-req-{task_id}",),
            raw_response={"mock": True},
        )


class MockScoringAdapter:
    """Deterministic scoring adapter that classifies attempts for testing."""

    scorer_id = "mock_scorer"

    def __init__(
        self,
        pass_pattern: str = "pass",
        force_outcomes: dict[str, str] | None = None,
        simulate_infra_error: set[str] | None = None,
    ) -> None:
        self.pass_pattern = pass_pattern
        self.force_outcomes = force_outcomes or {}
        self.simulate_infra_error = simulate_infra_error or set()

    def score_task(
        self,
        task_id: str,
        attempt: BackendAttempt,
        context: TaskContext,
    ) -> ScoredAttempt:
        if task_id in self.simulate_infra_error:
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code="SCORER_INFRASTRUCTURE_FAILURE",
                error_detail="Simulated evaluator exception",
            )

        if attempt.status == "timed_out":
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="timed_out",
                score=0.0,
                error_code=attempt.error_code,
                error_detail=attempt.error_detail,
            )

        if attempt.status == "error":
            return ScoredAttempt(
                task_id=task_id,
                scorer_id=self.scorer_id,
                status="infrastructure_invalid",
                score=0.0,
                error_code=attempt.error_code or "INFERENCE_ERROR",
                error_detail=attempt.error_detail or "Inference failed before scoring",
            )

        forced = self.force_outcomes.get(task_id)
        if forced:
            passed = forced == "passed"
        else:
            passed = self.pass_pattern.lower() in attempt.response_text.lower()

        status = "passed" if passed else "failed"
        score = 1.0 if passed else 0.0

        return ScoredAttempt(
            task_id=task_id,
            scorer_id=self.scorer_id,
            status=status,
            score=score,
            metrics={"accuracy": score, "duration_ms": attempt.duration_ms},
            details={"matched_pattern": self.pass_pattern if passed else None},
            evidence={"response_excerpt": attempt.response_text[:100]},
        )
