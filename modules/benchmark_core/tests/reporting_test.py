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
