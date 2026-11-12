"""Tests for official LiveCodeBench adapter, code extraction, and sandboxed verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_benchmark.benchmarks.adapters.livecodebench import (
    LCBProblem,
    LCBScoringAdapter,
    extract_python_code,
    select_stratified_lcb_100,
)
from agent_benchmark.execution import (
    BackendAttempt,
    ContainerVerifier,
    SandboxConfig,
    SandboxExecutionResult,
    SandboxUnavailableError,
    TaskContext,
)
from agent_benchmark.suite import (
    RunStore,
    build_manifest,
    create_run,
    execute_pending,
)


def test_extract_python_code() -> None:
    """extract_python_code must handle markdown code fences, fallback, and syntax errors."""
    # 1. Standard markdown code fence
    resp1 = "Here is the solution:\n```python\ndef add(a: int, b: int) -> int:\n    return a + b\n```\nHope it works!"
    code1, valid1 = extract_python_code(resp1)
    assert valid1 is True
    assert "def add(a: int, b: int) -> int:" in code1
    assert "Here is the solution" not in code1

    # 2. Syntax error in code block
    resp2 = "```python\ndef broken(:\n    pass\n```"
    code2, valid2 = extract_python_code(resp2)
    assert valid2 is False

    # 3. Code without markdown fences
    resp3 = "def multiply(x, y):\n    return x * y\n"
    code3, valid3 = extract_python_code(resp3)
    assert valid3 is True
    assert "def multiply" in code3


def test_container_verifier_fails_closed_when_docker_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """ContainerVerifier MUST fail closed without executing untrusted code on host."""
    verifier = ContainerVerifier(SandboxConfig())
    # Force sandbox check to return False
    monkeypatch.setattr(verifier, "is_sandbox_available", lambda: False)

    with pytest.raises(SandboxUnavailableError, match="strictly prohibited"):
        verifier.run_candidate("print('evil')", "1\n")


def test_container_verifier_security_config() -> None:
    """SandboxConfig must enforce strict security defaults."""
    cfg = SandboxConfig()
    assert cfg.network_disabled is True
    assert cfg.read_only_rootfs is True
    assert cfg.cap_drop_all is True
    assert cfg.no_new_privileges is True
    assert cfg.memory_limit == "512m"


def test_lcb_scoring_adapter_syntax_error_rejected_early() -> None:
    """Syntax error must be rejected immediately without container invocation."""
    adapter = LCBScoringAdapter()
    ctx = TaskContext(task_id="lcb-01", prompt="Solve problem")
    attempt = BackendAttempt(
        task_id="lcb-01",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef bad(\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=50.0,
        status="completed",
    )
    scored = adapter.score_task("lcb-01", attempt, ctx)
    assert scored.status == "failed"
    assert scored.score == 0.0
    assert scored.error_code == "SYNTAX_ERROR"


def test_lcb_scoring_adapter_sandbox_unavailable_classified_as_infrastructure_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When container sandbox is unavailable, outcome is infrastructure_invalid, not model failure."""
    verifier = ContainerVerifier()
    monkeypatch.setattr(verifier, "is_sandbox_available", lambda: False)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-01",
        prompt="Solve problem",
        metadata={"input_output": {"inputs": ["1"], "outputs": ["42"]}},
    )
    attempt = BackendAttempt(
        task_id="lcb-01",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve(): return 42\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=50.0,
        status="completed",
    )
    scored = adapter.score_task("lcb-01", attempt, ctx)
    assert scored.status == "infrastructure_invalid"
    assert scored.error_code == "CONTAINER_SANDBOX_UNAVAILABLE"


def test_lcb_scoring_adapter_mock_verifier_pass_and_fail() -> None:
    """Test pass and fail with a mock container verifier."""
    def mock_runner(code: str, stdin_text: str, fn_name: str | None) -> SandboxExecutionResult:
        if "return 42" in code:
            return SandboxExecutionResult(
                success=True, status="passed", exit_code=0, stdout="42\n", stderr="", duration_ms=120.0,
            )
        return SandboxExecutionResult(
            success=True, status="passed", exit_code=0, stdout="0\n", stderr="", duration_ms=80.0,
        )
    verifier = ContainerVerifier(mock_runner=mock_runner)
    adapter = LCBScoringAdapter(verifier=verifier)
    ctx = TaskContext(
        task_id="lcb-01",
        prompt="Return 42",
        metadata={"input_output": {"inputs": ["1"], "outputs": ["42"]}},
    )

    # 1. Passing code
    att_pass = BackendAttempt(
        task_id="lcb-01",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve(): return 42\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc_pass = adapter.score_task("lcb-01", att_pass, ctx)
    assert sc_pass.status == "passed"
    assert sc_pass.score == 1.0
    assert sc_pass.metrics["pass@1"] == 1.0

    # 2. Failing code
    att_fail = BackendAttempt(
        task_id="lcb-01",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve(): return 0\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc_fail = adapter.score_task("lcb-01", att_fail, ctx)
    assert sc_fail.status == "failed"
    assert sc_fail.score == 0.0
    assert sc_fail.metrics["pass@1"] == 0.0


def test_select_stratified_lcb_100() -> None:
    """Stratification must cover easy, medium, and hard difficulty groups."""
    problems = []
    difficulties = ["easy", "medium", "hard"]
    for i in range(120):
        diff = difficulties[i % 3]
        problems.append(
            LCBProblem(
                question_id=str(i),
                question_title=f"Problem {i}",
                difficulty=diff,
                contest_date="2024-01-01",
                prompt="Prompt",
                starter_code="",
                input_output={},
                task_id=f"lcb-{i}",
            )
        )

    cohort = select_stratified_lcb_100(problems)
    assert len(cohort) == 100
    assert len(set(cohort)) == 100


def test_e2e_lcb_suite_execution(tmp_path: Path) -> None:
    """Execute end-to-end LiveCodeBench suite run with direct backend and mock verifier."""
    plan = build_manifest(
        cohort="lcb-v6-smoke",
        agent="direct",
        model="mock-coder",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert plan["backend"] == "direct_chat"
    assert plan["scoring_protocol"] == "lcb_official"
    assert len(plan["tasks"]) == 5

    run_dir = create_run(
        tmp_path / "runs",
        cohort="lcb-v6-smoke",
        agent="direct",
        model="mock-coder",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert RunStore(run_dir).read()["state"] == "planned"

    # Custom executor using mock verifier
    def mock_runner(code: str, stdin_text: str, fn_name: str | None) -> SandboxExecutionResult:
        return SandboxExecutionResult(
            success=True, status="passed", exit_code=0, stdout="1\n", stderr="", duration_ms=50.0,
        )
    verifier = ContainerVerifier(mock_runner=mock_runner)
    adapter = LCBScoringAdapter(verifier=verifier)

    def lcb_executor(s: RunStore, task: str) -> dict[str, Any]:
        from agent_benchmark.execution import ResultNormalizer

        attempt = BackendAttempt(
            task_id=task,
            model_id="mock-coder",
            endpoint="http://127.0.0.1:8000/v1",
            response_text="```python\ndef solve(): return 1\n```",
            started_at="2026-11-11T00:00:00Z",
            ended_at="2026-11-11T00:00:01Z",
            duration_ms=60.0,
            status="completed",
        )
        ctx = TaskContext(
            task_id=task,
            prompt="solve",
            metadata={"input_output": {"inputs": ["1"], "outputs": ["1"]}},
        )
        scored = adapter.score_task(task, attempt, ctx)
        return ResultNormalizer.to_store_task_record(scored, attempt)

    report = execute_pending(run_dir, execute=True, executor=lcb_executor)
    assert report["state"] == "finished"
    assert report["planned"] == 5
    assert report["passed"] == 5
    assert report["pass_rate_pct"] == 100.0
