"""
Tests for benchmark_core command-line interface.

Verifies:
- Short and long flags for every CLI argument
- Read-only default behavior (-w / --write required to write)
- Subcommands: report, compare, import
"""

from pathlib import Path
import pytest

from benchmark_core.cli import build_parser, main
from benchmark_core.models import RunInfo, TrialResult, TrialStatus
from benchmark_core.storage import append_result, save_run


import argparse


def test_cli_flags_have_short_and_long_forms() -> None:
    parser = build_parser()
    # Check that each subparser action has both short and long options
    subparsers_action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    assert subparsers_action is not None
    for sub_name, sub_p in subparsers_action.choices.items():
        for action in sub_p._actions:
            if action.option_strings:
                shorts = [opt for opt in action.option_strings if opt.startswith("-") and not opt.startswith("--")]
                longs = [opt for opt in action.option_strings if opt.startswith("--")]
                assert len(shorts) >= 1, f"Missing short flag for {action.option_strings} in '{sub_name}'"
                assert len(longs) >= 1, f"Missing long flag for {action.option_strings} in '{sub_name}'"


def test_cli_report_read_only_by_default(tmp_path: Path, sample_run_info: RunInfo, sample_trial_result: TrialResult, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "run_cli_test"
    save_run(run_dir, sample_run_info)
    append_result(run_dir, sample_trial_result)

    # Run without -w
    exit_code = main(["report", "-i", str(run_dir)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "# Benchmark Report: run-test-01" in captured.out

    # Files must NOT be written to disk in read-only mode
    assert not (run_dir / "summary.json").exists()
    assert not (run_dir / "summary.csv").exists()
    assert not (run_dir / "report.md").exists()


def test_cli_report_with_write_flag(tmp_path: Path, sample_run_info: RunInfo, sample_trial_result: TrialResult) -> None:
    run_dir = tmp_path / "run_cli_write"
    save_run(run_dir, sample_run_info)
    append_result(run_dir, sample_trial_result)

    exit_code = main(["report", "--input-dir", str(run_dir), "--write", "--quiet"])
    assert exit_code == 0

    # Files must be written
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "summary.csv").is_file()
    assert (run_dir / "report.md").is_file()


def test_cli_compare(tmp_path: Path, sample_run_info: RunInfo, sample_trial_result: TrialResult, capsys: pytest.CaptureFixture[str]) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    save_run(run_a, sample_run_info)
    append_result(run_a, sample_trial_result)

    run_info_b = RunInfo(
        run_id="run-test-02",
        created_at="2026-10-19T03:00:00Z",
        suite_id="suite-sort-eval",
        suite_version="1.0.0",
        task_ids=["task_sort", "task_search"],
        variants={"var-a": {"opt": True}, "var-b": {"opt": False}},
        repetitions=3,
        scoring_basis="worker_first_attempt_full_success",
    )
    trial_b = TrialResult(
        run_id="run-test-02",
        trial_id="trial-002",
        task_id="task_sort",
        variant_id="var-a",
        repetition=1,
        status=TrialStatus.PASSED,
    )
    save_run(run_b, run_info_b)
    append_result(run_b, trial_b)

    exit_code = main(["compare", "-b", str(run_a), "-c", str(run_b), "-w"])
    assert exit_code == 0

    assert (run_b / "comparison.md").is_file()
    assert (run_b / "comparison.json").is_file()


def test_cli_error_on_missing_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nonexistent_dir"
    exit_code = main(["report", "-i", str(missing)])
    assert exit_code != 0
    captured = capsys.readouterr()
    assert "does not exist" in captured.err
