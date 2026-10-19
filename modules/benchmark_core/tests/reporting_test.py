"""
Tests for benchmark_core reporting generators (JSON, wide-form CSV, Markdown).

Strictly verifies Final Amendment 3 requirements for summary.csv:
- Wide-form schema with exactly one row per variant
- Union of aggregate metric keys across all variants
- Deterministic column ordering
- Preservation of dotted metric names
- Empty string ('') for unavailable or absent measurements, NEVER 0
"""

import csv
import io
import json
from pathlib import Path
import pytest

from benchmark_core.models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.reporting import (
    generate_reports,
    render_report_md,
    render_summary_csv,
    render_summary_json,
)
from benchmark_core.stats import summarize


@pytest.fixture
def multi_variant_summary() -> tuple[RunInfo, list[TrialResult]]:
    run_info = RunInfo(
        run_id="run-report-test",
        created_at="2026-10-19T02:30:00Z",
        suite_id="agent-coding-eval",
        suite_version="1.2.0",
        task_ids=["t1", "t2"],
        variants={
            "var_fast": {"model": "fast-7b", "temp": 0.0},
            "var_reasoning": {"model": "reasoning-32b", "temp": 0.6},
        },
        repetitions=2,
        scoring_basis="worker_first_attempt_full_success",
        environment={"os": "Windows 11", "python": "3.12.10"},
        metadata={"suite_fingerprint": "fp_12345", "random_seed": 99},
    )

    trials = [
        # var_fast: has tokens.worker.input, but lacks reasoning_tokens
        TrialResult(
            "run-report-test", "t-01", "t1", "var_fast", 1, TrialStatus.PASSED,
            metrics={
                "duration.wall_ms": MetricValue(500.0, "ms", "timer", MetricQuality.MEASURED),
                "tokens.worker.input": MetricValue(200, "tokens", "api", MetricQuality.MEASURED),
            },
        ),
        TrialResult(
            "run-report-test", "t-02", "t2", "var_fast", 1, TrialStatus.FAILED,
            metrics={
                "duration.wall_ms": MetricValue(400.0, "ms", "timer", MetricQuality.MEASURED),
                "tokens.worker.input": MetricValue(220, "tokens", "api", MetricQuality.MEASURED),
            },
        ),
        # var_reasoning: has reasoning_tokens, but duration on t2 is unavailable
        TrialResult(
            "run-report-test", "t-03", "t1", "var_reasoning", 1, TrialStatus.PASSED,
            metrics={
                "duration.wall_ms": MetricValue(1500.0, "ms", "timer", MetricQuality.MEASURED),
                "reasoning_tokens": MetricValue(450, "tokens", "api", MetricQuality.MEASURED),
            },
        ),
        TrialResult(
            "run-report-test", "t-04", "t2", "var_reasoning", 1, TrialStatus.PASSED,
            metrics={
                "duration.wall_ms": MetricValue(None, "ms", "timer", MetricQuality.UNAVAILABLE, reason="timer error"),
                "reasoning_tokens": MetricValue(500, "tokens", "api", MetricQuality.MEASURED),
            },
        ),
    ]

    return run_info, trials


def test_render_summary_json(multi_variant_summary: tuple[RunInfo, list[TrialResult]]) -> None:
    run_info, trials = multi_variant_summary
    summary = summarize(run_info, trials)
    json_str = render_summary_json(summary)

    # Valid JSON
    data = json.loads(json_str)
    assert data["run_info"]["run_id"] == "run-report-test"
    assert "var_fast" in data["variants"]
    assert "var_reasoning" in data["variants"]
    assert data["run_info"]["metadata"]["suite_fingerprint"] == "fp_12345"


def test_render_summary_csv_wide_form_contract(multi_variant_summary: tuple[RunInfo, list[TrialResult]]) -> None:
    """
    Verify Amendment 3 wide-form CSV contract:
    - Exactly 1 row per variant
    - Union of metric keys
    - Dotted metric names preserved
    - Missing/unavailable values represented as empty string (''), never 0
    """
    run_info, trials = multi_variant_summary
    summary = summarize(run_info, trials)
    csv_str = render_summary_csv(summary)

    reader = list(csv.DictReader(io.StringIO(csv_str)))

    # Exactly 2 variant rows
    assert len(reader) == 2
    variant_ids = {row["variant_id"] for row in reader}
    assert variant_ids == {"var_fast", "var_reasoning"}

    row_fast = next(r for r in reader if r["variant_id"] == "var_fast")
    row_reasoning = next(r for r in reader if r["variant_id"] == "var_reasoning")

    # Fast variant has tokens.worker.input but NOT reasoning_tokens
    assert row_fast["tokens.worker.input.mean"] != ""
    assert float(row_fast["tokens.worker.input.mean"]) == 210.0
    # Crucial: reasoning_tokens.mean must be empty string, NOT '0' or '0.0'
    assert row_fast["reasoning_tokens.mean"] == ""
    assert row_fast["reasoning_tokens.available_count"] == ""

    # Reasoning variant has reasoning_tokens, but lacks tokens.worker.input
    assert row_reasoning["reasoning_tokens.mean"] != ""
    assert float(row_reasoning["reasoning_tokens.mean"]) == 475.0
    assert row_reasoning["tokens.worker.input.mean"] == ""

    # Check stable columns
    assert int(row_fast["total_trials"]) == 2
    assert int(row_fast["passed"]) == 1
    assert int(row_fast["failed"]) == 1
    assert float(row_fast["micro_success_rate"]) == 0.5
    assert float(row_fast["macro_success_rate"]) == 0.5

    assert int(row_reasoning["total_trials"]) == 2
    assert int(row_reasoning["passed"]) == 2
    assert float(row_reasoning["micro_success_rate"]) == 1.0


def test_render_report_md_contents(multi_variant_summary: tuple[RunInfo, list[TrialResult]]) -> None:
    run_info, trials = multi_variant_summary
    summary = summarize(run_info, trials)
    md = render_report_md(summary)

    assert "# Benchmark Report: run-report-test" in md
    assert "fp_12345" in md
    assert "99" in md
    assert "worker_first_attempt_full_success" in md
    assert "var_fast" in md
    assert "var_reasoning" in md
    assert "50.0%" in md
    assert "100.0%" in md


def test_generate_reports_disk_write(tmp_path: Path, multi_variant_summary: tuple[RunInfo, list[TrialResult]]) -> None:
    run_info, trials = multi_variant_summary
    summary = summarize(run_info, trials)

    # In-memory only when write=False
    reports = generate_reports(summary, write=False)
    assert set(reports.keys()) == {"summary.json", "summary.csv", "report.md"}
    assert not (tmp_path / "summary.json").exists()

    # Disk write when write=True
    out_dir = tmp_path / "output_reports"
    generate_reports(summary, output_dir=out_dir, write=True)

    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "summary.csv").is_file()
    assert (out_dir / "report.md").is_file()


def test_render_report_md_displays_entirely_unavailable_metrics() -> None:
    run_info = RunInfo(
        run_id="run-unavailable-test",
        created_at="2026-10-19T05:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.0",
        task_ids=["t1"],
        variants={"worker": {"model": "test-model"}},
        repetitions=1,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials = [
        TrialResult(
            "run-unavailable-test", "t-01", "t1", "worker", 1, TrialStatus.TIMED_OUT,
            metrics={
                "duration.wall_ms": MetricValue(60000.0, "ms", "timer", MetricQuality.MEASURED),
                "agent.scope_violations": MetricValue(0, "count", "audit", MetricQuality.MEASURED),
                "tokens.worker.input": MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE, reason="unsupported"),
                "tokens.worker.output": MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE, reason="unsupported"),
            },
        ),
    ]
    summary = summarize(run_info, trials)
    md = render_report_md(summary)

    # Both measured and entirely unavailable metrics must appear in markdown report
    assert "| `worker` | `agent.scope_violations` | 0.0 count | 0.0 count | 1/1 |" in md
    assert "| `worker` | `tokens.worker.input` | N/A | N/A | 0/1 |" in md
    assert "| `worker` | `tokens.worker.output` | N/A | N/A | 0/1 |" in md


def test_render_report_md_mixed_and_estimated_quality() -> None:
    run_info = RunInfo(
        run_id="run-mixed-test",
        created_at="2026-10-19T05:00:00Z",
        suite_id="agent-smoke",
        suite_version="0.1.0",
        task_ids=["t1"],
        variants={"worker": {"model": "test-model"}},
        repetitions=3,
        scoring_basis="worker_first_attempt_full_success",
    )
    trials = [
        TrialResult(
            "run-mixed-test", "t-01", "t1", "worker", 1, TrialStatus.PASSED,
            metrics={"tokens.worker.input": MetricValue(100.0, "tokens", "api", MetricQuality.MEASURED)},
        ),
        TrialResult(
            "run-mixed-test", "t-02", "t1", "worker", 2, TrialStatus.PASSED,
            metrics={"tokens.worker.input": MetricValue(200.0, "tokens", "heuristic", MetricQuality.ESTIMATED)},
        ),
        TrialResult(
            "run-mixed-test", "t-03", "t1", "worker", 3, TrialStatus.PASSED,
            metrics={"tokens.worker.input": MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE)},
        ),
    ]
    summary = summarize(run_info, trials)
    md = render_report_md(summary)
    csv_str = render_summary_csv(summary)
    json_str = render_summary_json(summary)

    # Markdown displays available/total as 2/3 and mean/median from available samples
    assert "| `worker` | `tokens.worker.input` | 150.0 tokens | 150.0 tokens | 2/3 |" in md

    # CSV preserves empty fields for missing statistics and records available/missing counts
    reader = list(csv.DictReader(io.StringIO(csv_str)))
    assert reader[0]["tokens.worker.input.mean"] == "150.0"
    assert reader[0]["tokens.worker.input.available_count"] == "2"
    assert reader[0]["tokens.worker.input.missing_count"] == "1"

    # JSON preserves full quality breakdown
    data = json.loads(json_str)
    metric_data = data["variants"]["worker"]["metrics"]["tokens.worker.input"]
    assert metric_data["available_count"] == 2
    assert metric_data["missing_count"] == 1
    assert metric_data["measured_mean"] == 100.0
    assert metric_data["estimated_mean"] == 200.0
    assert metric_data["quality_counts"][MetricQuality.MEASURED] == 1
    assert metric_data["quality_counts"][MetricQuality.ESTIMATED] == 1
    assert metric_data["quality_counts"][MetricQuality.UNAVAILABLE] == 1


def test_regenerate_historical_report_offline_without_modifying_files() -> None:
    historical_dir = Path(__file__).resolve().parents[3] / "reports" / "20261019T114143Z-dfd3bbc9"
    if not (historical_dir / "run.json").exists():
        pytest.skip("Historical report directory not available")

    # Capture mtimes of all files in historical directory
    mtimes_before = {p: p.stat().st_mtime_ns for p in historical_dir.rglob("*") if p.is_file()}

    from benchmark_core.storage import load_run
    run_info, trials = load_run(historical_dir)
    summary = summarize(run_info, trials)
    reports = generate_reports(summary, write=False)

    md = reports["report.md"]
    # All unavailable metrics from historical run are now present in rendered report.md
    assert "| `worker` | `tokens.worker.input` | N/A | N/A | 0/1 |" in md
    assert "| `worker` | `tokens.worker.output` | N/A | N/A | 0/1 |" in md
    assert "| `worker` | `tokens.coordinator.input` | N/A | N/A | 0/1 |" in md
    assert "| `worker` | `tools.calls` | N/A | N/A | 0/1 |" in md
    assert "| `worker` | `tools.failures` | N/A | N/A | 0/1 |" in md

    # Ensure no files on disk were modified
    mtimes_after = {p: p.stat().st_mtime_ns for p in historical_dir.rglob("*") if p.is_file()}
    assert mtimes_before == mtimes_after


