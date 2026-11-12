"""Tests for backend-neutral execution contracts, direct chat client, and suite runner."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_benchmark.execution import (
    BackendAttempt,
    DirectChatBackend,
    ExecutionPlan,
    MockExecutionBackend,
    MockScoringAdapter,
    ResultNormalizer,
    ScoredAttempt,
    TaskContext,
    validate_endpoint_url,
)
from agent_benchmark.suite import (
    RunStore,
    build_manifest,
    create_run,
    execute_pending,
    status_run,
)


def test_execution_plan_digest_and_contracts() -> None:
    """ExecutionPlan must produce deterministic digest and serializable dict."""
    plan1 = ExecutionPlan(
        backend_id="direct_chat",
        benchmark_id="ifeval",
        dataset_id="ifeval/google-2023",
        task_ids=("task-1", "task-2"),
        model_id="qwen-2.5-7b",
        base_url="http://127.0.0.1:1234/v1",
    )
    plan2 = ExecutionPlan(
        backend_id="direct_chat",
        benchmark_id="ifeval",
        dataset_id="ifeval/google-2023",
        task_ids=("task-1", "task-2"),
        model_id="qwen-2.5-7b",
        base_url="http://127.0.0.1:1234/v1",
    )
    assert plan1.digest() == plan2.digest()
    data = plan1.to_dict()
    assert data["backend_id"] == "direct_chat"
    assert data["task_ids"] == ["task-1", "task-2"]


def test_result_normalizer_mapping() -> None:
    """ResultNormalizer must map scored attempt into RunStore record."""
    attempt = BackendAttempt(
        task_id="task-01",
        model_id="model-a",
        endpoint="http://127.0.0.1:8000/v1",
        response_text="output text",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=1000.0,
        status="completed",
        input_tokens=15,
        output_tokens=30,
        request_ids=("req-123",),
    )
    scored = ScoredAttempt(
        task_id="task-01",
        scorer_id="mock_scorer",
        status="passed",
        score=1.0,
        metrics={"acc": 1.0},
    )
    record = ResultNormalizer.to_store_task_record(scored, attempt)
    assert record["status"] == "passed"
    assert record["score"] == 1.0
    assert record["duration_wall_ms"] == 1000.0
    assert record["monitor_request_ids"] == ["req-123"]
    assert record["token_counts"] == {"input": 15, "output": 30}


def test_validate_endpoint_url() -> None:
    """Endpoint validator must accept local loopback and reject invalid/empty values."""
    assert validate_endpoint_url("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080/v1"
    assert validate_endpoint_url("http://localhost:1234") == "http://localhost:1234"
    assert validate_endpoint_url("http://host.docker.internal:8788/v1") == "http://host.docker.internal:8788/v1"

    with pytest.raises(ValueError, match="requires explicit base_url"):
        validate_endpoint_url("")

    with pytest.raises(ValueError, match="Invalid base_url format"):
        validate_endpoint_url("not-a-valid-url")


def test_direct_chat_backend_success() -> None:
    """DirectChatBackend must parse OpenAI-compatible responses, tokens, and request IDs."""
    fake_response = {
        "id": "chatcmpl-test-01",
        "model": "local-model",
        "choices": [{"message": {"role": "assistant", "content": "Hello World!"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-request-id") is not None
        body = json.loads(request.read())
        assert body["model"] == "local-model"
        assert len(body["messages"]) == 1
        return httpx.Response(200, json=fake_response)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    backend = DirectChatBackend(client=client)

    plan = ExecutionPlan(
        backend_id="direct_chat",
        benchmark_id="ifeval",
        dataset_id="ifeval/google-2023",
        task_ids=("t1",),
        model_id="local-model",
        base_url="http://127.0.0.1:8000/v1",
    )
    context = TaskContext(task_id="t1", prompt="Say hello")
    attempt = backend.execute_task("t1", context, plan)

    assert attempt.status == "completed"
    assert attempt.response_text == "Hello World!"
    assert attempt.input_tokens == 12
    assert attempt.output_tokens == 4
    assert attempt.error_code is None


def test_direct_chat_backend_errors_and_timeouts() -> None:
    """DirectChatBackend must properly classify HTTP errors and timeouts without crash."""
    # 1. HTTP 500 error
    def err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client_err = httpx.Client(transport=httpx.MockTransport(err_handler))
    backend_err = DirectChatBackend(client=client_err)
    plan = ExecutionPlan(
        backend_id="direct_chat",
        benchmark_id="ifeval",
        dataset_id="ifeval/google-2023",
        task_ids=("t1",),
        model_id="local-model",
        base_url="http://127.0.0.1:8000/v1",
    )
    attempt_err = backend_err.execute_task("t1", TaskContext(task_id="t1", prompt="test"), plan)
    assert attempt_err.status == "error"
    assert attempt_err.error_code == "INFERENCE_HTTP_ERROR"

    # 2. Timeout
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout reached")

    client_to = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    backend_to = DirectChatBackend(client=client_to)
    attempt_to = backend_to.execute_task("t1", TaskContext(task_id="t1", prompt="test"), plan)
    assert attempt_to.status == "timed_out"
    assert attempt_to.error_code == "INFERENCE_TIMEOUT"


def test_mock_backend_and_scorer() -> None:
    """MockExecutionBackend and MockScoringAdapter must support deterministic flows."""
    backend = MockExecutionBackend(
        canned_responses={"t1": "this is a pass", "t2": "failure"},
        simulate_timeout={"t3"},
        simulate_error={"t4"},
    )
    scorer = MockScoringAdapter(pass_pattern="pass", simulate_infra_error={"t5"})

    plan = ExecutionPlan(
        backend_id="mock",
        benchmark_id="test",
        dataset_id="test-ds",
        task_ids=("t1", "t2", "t3", "t4", "t5"),
        model_id="mock-model",
    )

    # t1: passes
    att1 = backend.execute_task("t1", TaskContext("t1", "prompt 1"), plan)
    sc1 = scorer.score_task("t1", att1, TaskContext("t1", "prompt 1"))
    assert sc1.status == "passed"
    assert sc1.score == 1.0

    # t2: fails
    att2 = backend.execute_task("t2", TaskContext("t2", "prompt 2"), plan)
    sc2 = scorer.score_task("t2", att2, TaskContext("t2", "prompt 2"))
    assert sc2.status == "failed"
    assert sc2.score == 0.0

    # t3: timeout
    att3 = backend.execute_task("t3", TaskContext("t3", "prompt 3"), plan)
    sc3 = scorer.score_task("t3", att3, TaskContext("t3", "prompt 3"))
    assert sc3.status == "timed_out"

    # t4: inference error -> infrastructure_invalid
    att4 = backend.execute_task("t4", TaskContext("t4", "prompt 4"), plan)
    sc4 = scorer.score_task("t4", att4, TaskContext("t4", "prompt 4"))
    assert sc4.status == "infrastructure_invalid"

    # t5: scorer infra failure -> infrastructure_invalid
    att5 = backend.execute_task("t5", TaskContext("t5", "prompt 5"), plan)
    sc5 = scorer.score_task("t5", att5, TaskContext("t5", "prompt 5"))
    assert sc5.status == "infrastructure_invalid"
    assert sc5.error_code == "SCORER_INFRASTRUCTURE_FAILURE"


def test_suite_build_manifest_direct_chat(tmp_path: Path) -> None:
    """Direct-chat manifest must not require Docker or Harbor and declare backend properly."""
    manifest_p = tmp_path / "custom_direct.json"
    manifest_p.write_text(
        json.dumps({
            "id": "direct-cohort",
            "dataset": "ifeval/google-2023",
            "source_revision": "c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
            "tasks": ["ifeval-task-1", "ifeval-task-2"],
        }),
        encoding="utf-8",
    )
    plan = build_manifest(
        cohort=None,
        manifest=manifest_p,
        agent="direct",
        model="test-model",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert plan["backend"] == "direct_chat"
    assert plan["cohort"] == "direct-cohort"
    assert plan["readiness"]["is_runnable"] is True
    assert len(plan["tasks"]) == 2
    assert "docker_available" not in plan["readiness"]  # Docker not required!


def test_suite_create_run_and_execute_pending_with_mock_backend(tmp_path: Path) -> None:
    """E2E suite execution using mock backend without Docker or external network."""
    manifest_p = tmp_path / "custom_manifest.json"
    manifest_p.write_text(
        json.dumps({
            "id": "mock-cohort-3",
            "dataset": "mock-benchmark/test-ds",
            "source_revision": "mock-rev-1",
            "tasks": ["mock-task-1", "mock-task-2", "mock-task-3"],
        }),
        encoding="utf-8",
    )

    run_dir = create_run(
        tmp_path / "runs",
        cohort=None,
        manifest=manifest_p,
        agent="mock-agent",
        model="mock-model",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
        backend="mock",
    )

    store = RunStore(run_dir)
    cp = store.read()
    assert cp["state"] == "planned"
    assert cp["backend"] == "mock"
    assert len(cp["tasks"]) == 3

    # Require -x/--execute
    with pytest.raises(PermissionError, match="-x/--execute"):
        execute_pending(run_dir, execute=False)

    # Execute with mock backend
    report = execute_pending(run_dir, execute=True)
    assert report["state"] == "finished"
    assert report["planned"] == 3
    assert report["scored"] == 3
    assert report["coverage_pct"] == 100.0

    # Status check
    st = status_run(run_dir)
    assert st["state"] == "finished"
    assert st["planned"] == 3
