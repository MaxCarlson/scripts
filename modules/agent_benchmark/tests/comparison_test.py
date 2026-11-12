"""Tests for multi-model comparison, paired task matrix, Wilson CI, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark_core.conditions import declared_model_intervention_error
from agent_benchmark.cli import main
from agent_benchmark.comparison import (
    compare_suite_runs,
    compute_wilson_interval,
    format_comparison_markdown,
    format_comparison_table,
)


def _make_mock_run_dir(
    dir_path: Path,
    *,
    run_id: str,
    model: str,
    cohort: str = "mock-cohort",
    revision: str = "mock-rev-123",
    task_outcomes: dict[str, str],
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    tasks = []
    for tid, st in task_outcomes.items():
        tasks.append({
            "task_id": tid,
            "status": st,
            "duration_wall_ms": 150.0,
            "token_counts": {"input": 20, "output": 40},
        })

    cp = {
        "schema": "agent-benchmark-suite-checkpoint-v1",
        "run_id": run_id,
        "state": "finished",
        "cohort": cohort,
        "source_revision": revision,
        "model": model,
        "tasks": tasks,
    }
    (dir_path / "checkpoint.json").write_text(json.dumps(cp, indent=2), encoding="utf-8")
    (dir_path / "report.json").write_text(
        json.dumps({
            "run_id": run_id,
            "state": "finished",
            "planned": len(tasks),
            "scored": sum(t["status"] in ("passed", "failed") for t in tasks),
            "passed": sum(t["status"] == "passed" for t in tasks),
            "total_wall_time_ms": 150.0 * len(tasks),
        }, indent=2),
        encoding="utf-8",
    )
    return dir_path


def test_wilson_confidence_interval() -> None:
    """Wilson interval must calculate correct bounds and handle edge cases."""
    lo, hi = compute_wilson_interval(50, 100)
    assert 0.40 < lo < 0.50
    assert 0.50 < hi < 0.60

    # 100% successes
    lo_full, hi_full = compute_wilson_interval(10, 10)
    assert hi_full == 1.0
    assert lo_full > 0.6

    # 0 successes
    lo_zero, hi_zero = compute_wilson_interval(0, 10)
    assert lo_zero == 0.0
    assert hi_zero < 0.4

    # 0 total
    assert compute_wilson_interval(0, 0) == (0.0, 0.0)


def test_compare_suite_runs_paired_discordance(tmp_path: Path) -> None:
    """compare_suite_runs must compute paired task discordance matrix accurately."""
    # Model A: passes t1, t2; fails t3; t4 is invalid
    outcomes_a = {"t1": "passed", "t2": "passed", "t3": "failed", "t4": "infrastructure_invalid"}
    run_a = _make_mock_run_dir(tmp_path / "run_a", run_id="run-a", model="qwen-7b", task_outcomes=outcomes_a)

    # Model B: passes t2, t3; fails t1; passes t4
    outcomes_b = {"t1": "failed", "t2": "passed", "t3": "passed", "t4": "passed"}
    run_b = _make_mock_run_dir(tmp_path / "run_b", run_id="run-b", model="llama-8b", task_outcomes=outcomes_b)

    res = compare_suite_runs(run_a, run_b)
    assert res["is_comparable"] is True
    assert len(res["blockers"]) == 0

    pa = res["paired_analysis"]
    # Common valid tasks are t1, t2, t3 (t4 was invalid in A)
    assert pa["common_valid_tasks"] == 3
    assert pa["both_passed_count"] == 1  # t2
    assert pa["both_failed_count"] == 0
    assert pa["model_a_only_count"] == 1  # t1
    assert pa["model_b_only_count"] == 1  # t3
    assert pa["discordance_count"] == 2
    assert pa["paired_delta_pct"] == 0.0  # Equal passes on common valid tasks

    ma = res["model_a"]
    mb = res["model_b"]
    assert ma["coverage_pct"] == 75.0  # 3/4 scored
    assert mb["coverage_pct"] == 100.0  # 4/4 scored


def test_comparability_rejection_on_mismatched_cohorts(tmp_path: Path) -> None:
    """Runs with different cohorts or revisions must be flagged as non-comparable."""
    run_a = _make_mock_run_dir(
        tmp_path / "run_a",
        run_id="run-a",
        model="qwen-7b",
        cohort="cohort-1",
        revision="rev-AAA",
        task_outcomes={"t1": "passed"},
    )
    run_b = _make_mock_run_dir(
        tmp_path / "run_b",
        run_id="run-b",
        model="llama-8b",
        cohort="cohort-2",
        revision="rev-BBB",
        task_outcomes={"t1": "passed"},
    )

    res = compare_suite_runs(run_a, run_b)
    assert res["is_comparable"] is False
    assert any("Cohorts differ" in b for b in res["blockers"])
    assert any("Source revisions differ" in b for b in res["blockers"])


def test_comparison_formatters(tmp_path: Path) -> None:
    """Formatters must render clean table and markdown representations."""
    run_a = _make_mock_run_dir(tmp_path / "run_a", run_id="run-a", model="m_a", task_outcomes={"t1": "passed", "t2": "failed"})
    run_b = _make_mock_run_dir(tmp_path / "run_b", run_id="run-b", model="m_b", task_outcomes={"t1": "passed", "t2": "passed"})

    res = compare_suite_runs(run_a, run_b)
    tbl_text = format_comparison_table(res)
    assert "Benchmark Model Comparison" in tbl_text
    assert "Paired Discordance Matrix" in tbl_text

    md_text = format_comparison_markdown(res)
    assert "# Benchmark Model Comparison" in md_text
    assert "| **Pass Rate** |" in md_text


def test_cli_suite_compare(tmp_path: Path, capsys) -> None:
    """CLI 'suite compare -r RUN_A RUN_B' must execute and support table/json/markdown."""
    run_a = _make_mock_run_dir(tmp_path / "run_a", run_id="run-a", model="m_a", task_outcomes={"t1": "passed"})
    run_b = _make_mock_run_dir(tmp_path / "run_b", run_id="run-b", model="m_b", task_outcomes={"t1": "passed"})

    # 1. JSON format
    rc1 = main(["suite", "compare", "-r", str(run_a), str(run_b), "-f", "json"])
    assert rc1 == 0
    data = json.loads(capsys.readouterr().out)
    assert data["is_comparable"] is True
    assert data["paired_analysis"]["common_valid_tasks"] == 1

    # 2. Markdown format
    rc2 = main(["suite", "compare", "-r", str(run_a), str(run_b), "-f", "markdown"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "# Benchmark Model Comparison" in out2


def test_declared_model_intervention_error() -> None:
    """declared_model_intervention_error must allow explicitly declared model comparisons."""
    contract_base = {
        "schema": "comparison-conditions-v1",
        "tasks": {"t1": {"task_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "verifier_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}},
        "execution_profiles": {"t1": "prof-1"},
        "scope_policy": "strict",
        "isolation_policy": "process",
        "context_length": 8192,
        "budget": {"profile": "std", "task_seconds": 60.0, "verifier_seconds": 10.0, "grace_seconds": 5.0},
        "environment": {
            "python": "3.12",
            "platform": "windows",
            "machine": "x86_64",
            "harness_version": "1.0",
            "runtime": {"kind": "native", "version": "1.0"},
            "model_identity": {"model_id": "model-a"},
        },
    }
    contract_cand = json.loads(json.dumps(contract_base))
    contract_cand["environment"]["model_identity"] = {"model_id": "model-b"}

    meta_base = {
        "model_intervention": {
            "schema": "declared-model-intervention-v1",
            "design_id": "test-eval-v1",
            "factor": "model_identity",
            "assignment": "model-a",
        }
    }
    meta_cand = {
        "model_intervention": {
            "schema": "declared-model-intervention-v1",
            "design_id": "test-eval-v1",
            "factor": "model_identity",
            "assignment": "model-b",
        }
    }

    err, info = declared_model_intervention_error(contract_base, contract_cand, meta_base, meta_cand)
    assert err is None
    assert info is not None
    assert info["baseline_condition"] == "model-a"
    assert info["candidate_condition"] == "model-b"
