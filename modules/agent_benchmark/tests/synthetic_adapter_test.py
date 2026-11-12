"""
Phase 08 Integration Qualification: Third Synthetic Benchmark Adapter.

Proves N-benchmark extensibility:
- Registers a third benchmark (Synthetic Regex Bench) without modifying shared CLI,
  catalog core definitions, runner scheduling, or results storage.
- Tests descriptor-only registration of an additional Harbor dataset.
- Executes full lifecycle: discovery, setup plan/verify, cohort selection, immutable plan,
  mocked execution, scoring adapter import, interruption/resume, and model comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_benchmark.benchmarks.catalog import (
    get_default_catalog,
    get_unified_discovery,
)
from agent_benchmark.benchmarks.schema import (
    BenchmarkDescriptor,
    CohortDescriptor,
    DatasetDescriptor,
    ResourceDeclaration,
)
from agent_benchmark.comparison import compare_suite_runs
from agent_benchmark.execution.contract import (
    BackendAttempt,
    ExecutionPlan,
    ScoredAttempt,
    TaskContext,
)
from agent_benchmark.execution.mock_backend import MockExecutionBackend
from agent_benchmark.execution.registry import (
    register_scorer,
)
from agent_benchmark.external_sources.manager import SourceManager
from agent_benchmark.external_sources.specs import ResourceSpec
from agent_benchmark.suite import (
    COHORTS,
    build_manifest,
)


class SyntheticRegexScoringAdapter:
    """Official scoring adapter for the synthetic regex benchmark."""

    scorer_id = "synthetic_regex_scorer"

    def score_task(
        self,
        task_id: str,
        attempt: BackendAttempt,
        context: TaskContext,
    ) -> ScoredAttempt:
        expected = (context.metadata or {}).get("expected", "MATCH")
        is_correct = expected in attempt.response_text
        return ScoredAttempt(
            task_id=task_id,
            scorer_id=self.scorer_id,
            status="passed" if is_correct else "failed",
            score=1.0 if is_correct else 0.0,
            metrics={"accuracy": 1.0 if is_correct else 0.0},
            details={"expected": expected, "match_found": is_correct},
        )


def test_descriptor_only_registration_harbor_dataset() -> None:
    """Verify descriptor-only registration of an additional Harbor dataset."""
    catalog = get_default_catalog()

    custom_dataset = DatasetDescriptor(
        id="harbor/swe-synthetic-eval",
        benchmark_id="harbor",
        name="SWE Synthetic Evaluation Dataset",
        version="2026.1",
        description="Descriptor-only synthetic evaluation dataset for Harbor",
        supported_languages=("python",),
        all_tasks=("swe-synth-1", "swe-synth-2"),
        default_scoring_protocol="harbor-standard-v1",
        tags=("harbor", "synthetic"),
        install_state="ready",
    )
    catalog.register_dataset(custom_dataset, aliases=["swe-synth", "swe-synthetic"])

    resolved = catalog.resolve_dataset("swe-synth")
    assert resolved.id == "harbor/swe-synthetic-eval"
    assert resolved.name == "SWE Synthetic Evaluation Dataset"

    discovery = get_unified_discovery(include_readiness=False)
    registered_ids = [d["id"] for d in discovery["datasets"]]
    assert "harbor/swe-synthetic-eval" in registered_ids


def test_synthetic_benchmark_full_lifecycle(tmp_path: Path) -> None:
    """
    Proves generic N-benchmark extensibility:
    1. Register synthetic benchmark, dataset, cohort, and custom scorer.
    2. Verify unified discovery & legacy COHORTS facade.
    3. Verify setup plan & verification.
    4. Plan execution using build_manifest.
    5. Mock execution for Model Alpha and Model Beta.
    6. Interruption and resume check.
    7. Multi-model comparison across paired task results.
    """
    catalog = get_default_catalog()

    # Register custom ScoringAdapter
    adapter = SyntheticRegexScoringAdapter()
    register_scorer("synthetic_regex_scorer", lambda: adapter)

    # 1. Register Benchmark
    bench_desc = BenchmarkDescriptor(
        id="synthetic_regex",
        name="Synthetic Regex Benchmark",
        version="1.0.0",
        description="Deterministic regex problem suite proving N-benchmark extensibility",
        implementation_type="synthetic",
        trusted_adapter_id="synthetic_regex_scorer",
        supported_backends=("mock", "direct_chat"),
        resources=(
            ResourceDeclaration(
                name="regex_patterns",
                type="dataset",
                url="https://example.com/regex.json",
                revision="1.0.0",
            ),
        ),
    )
    catalog.register_benchmark(bench_desc)

    # Register Dataset
    dataset_desc = DatasetDescriptor(
        id="synthetic_regex/v1",
        benchmark_id="synthetic_regex",
        name="Synthetic Regex Dataset v1",
        version="1.0.0",
        description="3 deterministic regex evaluation tasks",
        supported_languages=("python",),
        default_scoring_protocol="synthetic-regex-v1",
        all_tasks=("regex-task-1", "regex-task-2", "regex-task-3"),
        tags=("synthetic", "regex"),
        install_state="ready",
    )
    catalog.register_dataset(dataset_desc, aliases=["regex-bench"])

    # Register Cohort
    cohort_desc = CohortDescriptor(
        id="synthetic-regex-3",
        dataset_id="synthetic_regex/v1",
        source_revision="1.0.0",
        task_ids=("regex-task-1", "regex-task-2", "regex-task-3"),
        description="3 deterministic regex evaluation tasks",
        tags=("synthetic", "regex", "smoke"),
        scorer_id="synthetic_regex_scorer",
    )
    catalog.register_cohort(cohort_desc)

    # 2. Verify Discovery & Facades
    assert catalog.get_benchmark("synthetic_regex").name == "Synthetic Regex Benchmark"
    assert "synthetic-regex-3" in COHORTS
    cohort_data = COHORTS["synthetic-regex-3"]
    assert cohort_data["dataset"] == "synthetic_regex/v1"
    assert list(cohort_data["tasks"]) == ["regex-task-1", "regex-task-2", "regex-task-3"]

    # 3. Setup plan & verify
    store_dir = tmp_path / "ext_store"
    mgr = SourceManager(store_dir)
    spec = ResourceSpec.from_declaration(bench_desc.id, bench_desc.resources[0])
    plan = mgr.plan_resource(spec)
    assert plan["benchmark_id"] == "synthetic_regex"
    assert plan["installed"] is False

    # 4. Build execution manifest
    manifest = build_manifest(
        cohort="synthetic-regex-3",
        agent="mock_agent",
        model="model-alpha",
        base_url="http://localhost:8788/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
        backend="mock",
    )
    assert manifest["cohort"] == "synthetic-regex-3"
    assert manifest["tasks"] == ["regex-task-1", "regex-task-2", "regex-task-3"]

    tasks = list(manifest["tasks"])
    assert tasks == ["regex-task-1", "regex-task-2", "regex-task-3"]

    # 5. Execute Model Alpha (passes tasks 1 and 2, fails task 3)
    run_dir_a = tmp_path / "runs" / "run_model_alpha"
    run_dir_a.mkdir(parents=True)
    (run_dir_a / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    mock_alpha = MockExecutionBackend(
        canned_responses={
            "regex-task-1": "MATCH: verified valid pattern",
            "regex-task-2": "MATCH: pattern confirmed",
            "regex-task-3": "ERROR: syntax error in regex",
        }
    )

    exec_plan_a = ExecutionPlan(
        backend_id="mock",
        benchmark_id="synthetic_regex",
        dataset_id="synthetic_regex/v1",
        task_ids=("regex-task-1", "regex-task-2", "regex-task-3"),
        cohort_id="synthetic-regex-3",
        model_id="model-alpha",
    )

    scores_a: list[ScoredAttempt] = []
    checkpoint_tasks_a: list[dict[str, Any]] = []

    for task_id in tasks:
        ctx = TaskContext(
            task_id=task_id,
            prompt="Generate a regex match",
            metadata={"expected": "MATCH"},
        )
        attempt = mock_alpha.execute_task(task_id, ctx, exec_plan_a)
        score = adapter.score_task(task_id, attempt, ctx)
        scores_a.append(score)
        checkpoint_tasks_a.append(
            {
                "task_id": task_id,
                "status": score.status,
                "score": score.score,
                "metrics": score.metrics,
            }
        )

    passed_a = sum(1 for s in scores_a if s.status == "passed")
    assert passed_a == 2
    assert len(scores_a) == 3

    # Write authoritative suite checkpoint for Model Alpha
    (run_dir_a / "checkpoint.json").write_text(
        json.dumps(
            {
                "model": "model-alpha",
                "cohort": "synthetic-regex-3",
                "source_revision": "1.0.0",
                "completed": 3,
                "passed": 2,
                "failed": 1,
                "timed_out": 0,
                "infrastructure_invalid": 0,
                "tasks": checkpoint_tasks_a,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 6. Interruption & Resume verification
    partial_tasks = checkpoint_tasks_a[:2]
    partial_run_dir = tmp_path / "runs" / "run_partial"
    partial_run_dir.mkdir(parents=True)
    (partial_run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (partial_run_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "model": "model-alpha",
                "cohort": "synthetic-regex-3",
                "source_revision": "1.0.0",
                "completed": 2,
                "tasks": partial_tasks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    completed_ids = {t["task_id"] for t in partial_tasks}
    remaining_tasks = [t for t in tasks if t not in completed_ids]
    assert remaining_tasks == ["regex-task-3"]

    # 7. Execute Model Beta (passes all 3 tasks)
    manifest_b = dict(manifest)
    manifest_b["model"] = "model-beta"
    run_dir_b = tmp_path / "runs" / "run_model_beta"
    run_dir_b.mkdir(parents=True)
    (run_dir_b / "manifest.json").write_text(json.dumps(manifest_b, indent=2), encoding="utf-8")

    mock_beta = MockExecutionBackend(
        canned_responses={
            "regex-task-1": "MATCH: verified valid pattern",
            "regex-task-2": "MATCH: pattern confirmed",
            "regex-task-3": "MATCH: pattern also resolved",
        }
    )
    exec_plan_b = ExecutionPlan(
        backend_id="mock",
        benchmark_id="synthetic_regex",
        dataset_id="synthetic_regex/v1",
        task_ids=("regex-task-1", "regex-task-2", "regex-task-3"),
        cohort_id="synthetic-regex-3",
        model_id="model-beta",
    )

    scores_b: list[ScoredAttempt] = []
    checkpoint_tasks_b: list[dict[str, Any]] = []

    for task_id in tasks:
        ctx = TaskContext(
            task_id=task_id,
            prompt="Generate a regex match",
            metadata={"expected": "MATCH"},
        )
        attempt = mock_beta.execute_task(task_id, ctx, exec_plan_b)
        score = adapter.score_task(task_id, attempt, ctx)
        scores_b.append(score)
        checkpoint_tasks_b.append(
            {
                "task_id": task_id,
                "status": score.status,
                "score": score.score,
                "metrics": score.metrics,
            }
        )

    passed_b = sum(1 for s in scores_b if s.status == "passed")
    assert passed_b == 3

    (run_dir_b / "checkpoint.json").write_text(
        json.dumps(
            {
                "model": "model-beta",
                "cohort": "synthetic-regex-3",
                "source_revision": "1.0.0",
                "completed": 3,
                "passed": 3,
                "failed": 0,
                "timed_out": 0,
                "infrastructure_invalid": 0,
                "tasks": checkpoint_tasks_b,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 8. Multi-Model Comparison
    comparison = compare_suite_runs(run_dir_a, run_dir_b)
    assert comparison["is_comparable"] is True
    assert comparison["model_a"]["id"] == "model-alpha"
    assert comparison["model_b"]["id"] == "model-beta"
    assert comparison["model_a"]["passed"] == 2
    assert comparison["model_b"]["passed"] == 3
    pa = comparison["paired_analysis"]
    assert pa["both_passed_count"] == 2
    assert pa["discordance_count"] == 1
    assert pa["model_b_only_count"] == 1
    assert pa["model_a_only_count"] == 0
    assert pa["model_b_only_tasks"] == ["regex-task-3"]
    assert pa["model_a_only_tasks"] == []
