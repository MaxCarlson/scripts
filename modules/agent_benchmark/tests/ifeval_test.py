"""Tests for official IFEval benchmark adapter, dataset loader, and strict/loose scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from agent_benchmark.benchmarks.adapters.ifeval import (
    IFEvalScoringAdapter,
    IFEvalTask,
    load_ifeval_tasks,
    select_stratified_100_cohort,
)
from agent_benchmark.execution import (
    BackendAttempt,
    DirectChatBackend,
    ExecutionPlan,
    ResultNormalizer,
    TaskContext,
    get_scorer,
)
from agent_benchmark.suite import (
    RunStore,
    build_manifest,
    create_run,
    execute_pending,
)


def test_load_ifeval_tasks(tmp_path: Path) -> None:
    """Test loading and parsing IFEval JSONL records."""
    jsonl_p = tmp_path / "input_data.jsonl"
    jsonl_p.write_text(
        json.dumps({
            "key": 1001,
            "prompt": "Write a 300-word essay about cats.",
            "instruction_id_list": ["length_constraints:number_words"],
            "kwargs": [{"num_words": 300, "relation": "gte"}],
        })
        + "\n"
        + json.dumps({
            "key": 1002,
            "prompt": "Respond entirely in ALL CAPS.",
            "instruction_id_list": ["change_case:english_capital"],
            "kwargs": [{}],
        })
        + "\n",
        encoding="utf-8",
    )

    tasks = load_ifeval_tasks(jsonl_p)
    assert len(tasks) == 2
    assert "ifeval-1001" in tasks
    assert tasks["ifeval-1001"].instruction_id_list == ("length_constraints:number_words",)
    assert tasks["ifeval-1002"].instruction_id_list == ("change_case:english_capital",)


def test_select_stratified_100_cohort() -> None:
    """Stratification must deterministically cover instruction families."""
    tasks = []
    families = ["length_constraints", "change_case", "detectable_content", "startend"]
    for i in range(150):
        fam = families[i % len(families)]
        tasks.append(
            IFEvalTask(
                key=i,
                prompt=f"Task {i}",
                instruction_id_list=(f"{fam}:rule_{i}",),
                kwargs=({},),
                task_id=f"ifeval-{i}",
            )
        )

    cohort = select_stratified_100_cohort(tasks)
    assert len(cohort) == 100
    # Deterministic: repeated call gives identical cohort
    cohort2 = select_stratified_100_cohort(tasks)
    assert cohort == cohort2


def test_strict_and_loose_scoring_rules() -> None:
    """Verify strict vs loose rules on length, casing, and conversational framing."""
    adapter = IFEvalScoringAdapter()

    # 1. Capital casing: exact uppercase passes both
    ctx_cap = TaskContext(
        task_id="t-cap",
        prompt="Caps only",
        metadata={
            "instruction_id_list": ["change_case:english_capital"],
            "kwargs": [{}],
        },
    )
    att_pass = BackendAttempt(
        task_id="t-cap",
        model_id="m",
        endpoint="ep",
        response_text="THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG.",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc_pass = adapter.score_task("t-cap", att_pass, ctx_cap)
    assert sc_pass.status == "passed"
    assert sc_pass.metrics["ifeval.strict_prompt"] == 1.0
    assert sc_pass.metrics["ifeval.loose_prompt"] == 1.0

    # 2. Conversational prefix: fails strict, passes loose
    att_loose = BackendAttempt(
        task_id="t-cap",
        model_id="m",
        endpoint="ep",
        response_text="Sure, here is your text:\nTHE QUICK BROWN FOX JUMPS OVER THE LAZY DOG.",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc_loose = adapter.score_task("t-cap", att_loose, ctx_cap)
    assert sc_loose.status == "failed"  # strict prompt failed
    assert sc_loose.metrics["ifeval.strict_prompt"] == 0.0
    assert sc_loose.metrics["ifeval.loose_prompt"] == 1.0  # loose prompt passed!

    # 3. JSON format inside markdown block: fails strict, passes loose
    ctx_json = TaskContext(
        task_id="t-json",
        prompt="Output JSON",
        metadata={
            "instruction_id_list": ["detectable_format:json_format"],
            "kwargs": [{}],
        },
    )
    att_json = BackendAttempt(
        task_id="t-json",
        model_id="m",
        endpoint="ep",
        response_text='```json\n{"status": "ok", "value": 42}\n```',
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc_json = adapter.score_task("t-json", att_json, ctx_json)
    assert sc_json.metrics["ifeval.strict_prompt"] == 0.0
    assert sc_json.metrics["ifeval.loose_prompt"] == 1.0


def test_multi_instruction_conjunction() -> None:
    """Prompt passes strict only if ALL instructions pass."""
    adapter = get_scorer("ifeval_official")
    ctx_multi = TaskContext(
        task_id="t-multi",
        prompt="Output uppercase without comma",
        metadata={
            "instruction_id_list": ["change_case:english_capital", "punctuation:no_comma"],
            "kwargs": [{}, {}],
        },
    )

    # Passes capital, but fails comma
    att_partial = BackendAttempt(
        task_id="t-multi",
        model_id="m",
        endpoint="ep",
        response_text="HELLO, WORLD!",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    sc = adapter.score_task("t-multi", att_partial, ctx_multi)
    assert sc.status == "failed"
    assert sc.metrics["ifeval.strict_prompt"] == 0.0
    assert sc.metrics["ifeval.strict_instructions_passed"] == 1
    assert sc.metrics["ifeval.instructions_total"] == 2
    assert sc.metrics["ifeval.strict_instruction_acc"] == 0.5


def test_e2e_ifeval_suite_execution_with_mock_client(tmp_path: Path) -> None:
    """Execute end-to-end IFEval suite run using DirectChatBackend and mock HTTP transport."""
    # Build manifest for ifeval-smoke
    plan = build_manifest(
        cohort="ifeval-smoke",
        agent="direct",
        model="mock-qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert plan["backend"] == "direct_chat"
    assert plan["scoring_protocol"] == "ifeval_official"

    run_dir = create_run(
        tmp_path / "runs",
        cohort="ifeval-smoke",
        agent="direct",
        model="mock-qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )

    store = RunStore(run_dir)
    assert store.read()["state"] == "planned"

    # Mock HTTP responses: returns valid uppercase response
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-ifeval-mock",
                "model": "mock-qwen",
                "choices": [{"message": {"role": "assistant", "content": "THIS IS A PERFECT UPPERCASE RESPONSE."}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 8},
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    direct_backend = DirectChatBackend(client=mock_client)

    # Custom executor delegating to DirectChatBackend
    def custom_executor(s: RunStore, task: str) -> dict[str, Any]:
        scorer = IFEvalScoringAdapter()
        context = TaskContext(
            task_id=task,
            prompt="Write uppercase",
            metadata={"instruction_id_list": ["change_case:english_capital"], "kwargs": [{}]},
        )
        plan_obj = ExecutionPlan(
            backend_id="direct_chat",
            benchmark_id="ifeval",
            dataset_id="ifeval/google-2023",
            task_ids=(task,),
            model_id="mock-qwen",
            base_url="http://127.0.0.1:8000/v1",
        )
        attempt = direct_backend.execute_task(task, context, plan_obj)
        scored = scorer.score_task(task, attempt, context)
        return ResultNormalizer.to_store_task_record(scored, attempt)

    report = execute_pending(run_dir, execute=True, executor=custom_executor)
    assert report["state"] == "finished"
    assert report["planned"] == 5
    assert report["scored"] == 5
    assert report["passed"] == 5
    assert report["pass_rate_pct"] == 100.0
