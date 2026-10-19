"""
Targeted regression tests for the independent code review findings:
1. Incompatible metric unit rejection and measured vs estimated distinction
2. Consistent MetricValue value/quality combinations
3. Suppression of invalid cross-run comparison deltas on scoring basis/unit/fingerprint mismatches
4. Hyperfine re-import duplication prevention
5. Missing-metric accounting across trials and Hyperfine task grouping
6. Trial run_id validation matching declared RunInfo
"""

import json
from pathlib import Path
import pytest

from benchmark_core.compare import compare_runs
from benchmark_core.importers.hyperfine import import_hyperfine
from benchmark_core.models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.stats import compute_metric_stats, summarize
from benchmark_core.storage import append_result, save_run


class TestCorrectnessPass:
    """Test suite covering the 6 review findings."""

    def test_reject_incompatible_metric_units(self) -> None:
        """Issue 1: Reject metrics with incompatible units when computing stats."""
        values = [
            MetricValue(10.0, "ms", "timer", MetricQuality.MEASURED),
            MetricValue(0.02, "s", "timer", MetricQuality.MEASURED),  # Incompatible unit!
        ]
        with pytest.raises(ValueError, match="Incompatible units"):
            compute_metric_stats("duration", values)

    def test_distinguish_measured_vs_estimated_stats(self) -> None:
        """Issue 1: Distinguish measured from estimated statistics."""
        values = [
            MetricValue(10.0, "tokens", "api", MetricQuality.MEASURED),
            MetricValue(20.0, "tokens", "api", MetricQuality.MEASURED),
            MetricValue(90.0, "tokens", "heuristic", MetricQuality.ESTIMATED),
        ]
        stats = compute_metric_stats("tokens", values)
        assert stats.mean == 40.0
        assert stats.measured_mean == 15.0
        assert stats.estimated_mean == 90.0
        assert stats.quality_counts[MetricQuality.MEASURED] == 2
        assert stats.quality_counts[MetricQuality.ESTIMATED] == 1

    def test_enforce_consistent_value_quality_combinations(self) -> None:
        """Issue 2: Enforce consistent MetricValue value/quality combinations."""
        # Value is None, but quality is 'measured' -> must fail
        with pytest.raises(ValueError, match="Missing metric with value=None must have quality='unavailable'"):
            MetricValue(None, "tokens", "api", MetricQuality.MEASURED)

        # Value is numeric, but quality is 'unavailable' -> must fail
        with pytest.raises(ValueError, match="Unavailable metric cannot have numeric value"):
            MetricValue(100.0, "tokens", "api", MetricQuality.UNAVAILABLE)

        # Valid combinations
        mv_ok1 = MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE, reason="failed")
        assert mv_ok1.value is None and mv_ok1.quality == "unavailable"

        mv_ok2 = MetricValue(100.0, "tokens", "api", MetricQuality.MEASURED)
        assert mv_ok2.value == 100.0 and mv_ok2.quality == "measured"

    def test_suppress_invalid_deltas_on_incompatible_runs(self) -> None:
        """Issue 3: Prevent invalid success or performance deltas when runs are incompatible."""
        run_a = RunInfo(
            run_id="run-a",
            created_at="2026-10-19T02:00:00Z",
            suite_id="eval-suite",
            suite_version="1.0",
            task_ids=["t1"],
            variants={"var-1": {}},
            repetitions=1,
            scoring_basis="worker_first_attempt_full_success",
            metadata={"suite_fingerprint": "fp_AAA"},
        )
        trials_a = [
            TrialResult(
                "run-a", "a1", "t1", "var-1", 1, TrialStatus.PASSED,
                metrics={"mem": MetricValue(512.0, "MB", "os", MetricQuality.MEASURED)},
            ),
        ]

        # Candidate with DIFFERENT scoring basis, DIFFERENT fingerprint, and DIFFERENT metric unit
        run_b = RunInfo(
            run_id="run-b",
            created_at="2026-10-19T02:00:00Z",
            suite_id="eval-suite",
            suite_version="1.0",
            task_ids=["t1"],
            variants={"var-1": {}},
            repetitions=1,
            scoring_basis="workflow_final_success",  # Incompatible!
            metadata={"suite_fingerprint": "fp_BBB"},  # Incompatible!
        )
        trials_b = [
            TrialResult(
                "run-b", "b1", "t1", "var-1", 1, TrialStatus.FAILED,
                metrics={"mem": MetricValue(536870912.0, "bytes", "os", MetricQuality.MEASURED)},  # Incompatible unit!
            ),
        ]

        s_a = summarize(run_a, trials_a)
        s_b = summarize(run_b, trials_b)
        comp = compare_runs(s_a, s_b)

        # Warnings must be raised
        assert any("Scoring basis mismatch" in w for w in comp.warnings)
        assert any("Suite fingerprint mismatch" in w for w in comp.warnings)
        assert any("Unit mismatch for metric 'mem'" in w for w in comp.warnings)

        # Success rate deltas MUST NOT be computed when scoring basis differs!
        vc = comp.variant_comparisons["var-1"]
        assert vc.micro_success_rate.absolute_change is None
        assert vc.micro_success_rate.percentage_change is None
        assert vc.macro_success_rate.absolute_change is None

        # Metric deltas MUST NOT be computed when units differ!
        assert vc.metrics["mem"].absolute_change is None
        assert vc.metrics["mem"].percentage_change is None

    def test_hyperfine_reimport_duplicate_prevention(self, tmp_path: Path) -> None:
        """Issue 4: Prevent Hyperfine re-import from duplicating persisted trials and avoid unauthorized overwrite."""
        hf_data = {
            "results": [
                {
                    "command": "echo test",
                    "times": [0.01, 0.02],
                    "exit_codes": [0, 0],
                }
            ]
        }
        hf_file = tmp_path / "hf.json"
        hf_file.write_text(json.dumps(hf_data), encoding="utf-8")
        out_dir = tmp_path / "imported_hf"

        # Import first time
        import_hyperfine(hf_file, output_dir=out_dir, write=True)

        # Re-importing into existing directory without explicit overwrite authorization must fail safely
        with pytest.raises(FileExistsError, match="already contains authoritative benchmark records"):
            import_hyperfine(hf_file, output_dir=out_dir, write=True, overwrite=False)

        # Authorized overwrite replaces records cleanly without duplicating trials
        import_hyperfine(hf_file, output_dir=out_dir, write=True, overwrite=True)

        trials_lines = (out_dir / "trials.jsonl").read_text(encoding="utf-8").strip().splitlines()
        # Must be exactly 2 trials, NOT 4!
        assert len(trials_lines) == 2

    def test_missing_metric_accounting_across_trials(self) -> None:
        """Issue 5: Correct missing-metric accounting across trials in a variant."""
        run_info = RunInfo(
            run_id="run-missing-test",
            created_at="2026-10-19T02:00:00Z",
            suite_id="suite-eval",
            suite_version="1.0",
            task_ids=["t1"],
            variants={"v1": {}},
            repetitions=3,
            scoring_basis="worker_first_attempt_full_success",
        )
        trials = [
            # Trial 1 has tokens.worker.input
            TrialResult(
                "run-missing-test", "t1", "t1", "v1", 1, TrialStatus.PASSED,
                metrics={"tokens.worker.input": MetricValue(500, "tokens", "api", MetricQuality.MEASURED)},
            ),
            # Trial 2 omits tokens.worker.input completely (e.g. failed before token logging)
            TrialResult(
                "run-missing-test", "t2", "t1", "v1", 2, TrialStatus.FAILED,
                metrics={},
            ),
            # Trial 3 has tokens.worker.input as unavailable (value=None)
            TrialResult(
                "run-missing-test", "t3", "t1", "v1", 3, TrialStatus.TIMED_OUT,
                metrics={"tokens.worker.input": MetricValue(None, "tokens", "api", MetricQuality.UNAVAILABLE)},
            ),
        ]

        summary = summarize(run_info, trials)
        v_summary = summary.variants["v1"]
        token_stats = v_summary.metrics["tokens.worker.input"]

        # Across the 3 trials evaluated for this variant:
        # 1 available, 2 missing!
        assert token_stats.observation_count == 3
        assert token_stats.available_count == 1
        assert token_stats.missing_count == 2
        assert token_stats.mean == 500.0

    def test_hyperfine_groups_command_variants_under_common_task(self, tmp_path: Path) -> None:
        """Issue 5: Hyperfine commands are variants evaluated on a common benchmark task."""
        hf_data = {
            "results": [
                {"command": "app --fast", "times": [0.01, 0.02]},
                {"command": "app --slow", "times": [0.05, 0.06]},
            ]
        }
        hf_file = tmp_path / "hf_grouping.json"
        hf_file.write_text(json.dumps(hf_data), encoding="utf-8")

        run_info, trials = import_hyperfine(hf_file, suite_id="app-benchmark")

        # Both commands must share the same task_id so they are directly comparable
        task_ids = {t.task_id for t in trials}
        assert len(task_ids) == 1
        assert "app-benchmark" in next(iter(task_ids))

        # But have different variant_ids
        variant_ids = {t.variant_id for t in trials}
        assert len(variant_ids) == 2

    def test_validate_trial_run_id_matches_run_info(self, tmp_path: Path) -> None:
        """Issue 6: Ensure trials belong to declared run and validate before aggregation."""
        run_info = RunInfo(
            run_id="run-correct",
            created_at="2026-10-19T02:00:00Z",
            suite_id="suite-eval",
            suite_version="1.0",
            task_ids=["t1"],
            variants={"v1": {}},
            repetitions=1,
            scoring_basis="worker_first_attempt_full_success",
        )
        alien_trial = TrialResult(
            run_id="run-WRONG-ALIEN",
            trial_id="t-alien",
            task_id="t1",
            variant_id="v1",
            repetition=1,
            status=TrialStatus.PASSED,
        )

        # summarize must reject alien trial
        with pytest.raises(ValueError, match="belongs to run 'run-WRONG-ALIEN', but RunInfo has run_id 'run-correct'"):
            summarize(run_info, [alien_trial])

        # append_result must check run.json if present
        run_dir = tmp_path / "test_run_isolation"
        save_run(run_dir, run_info)
        with pytest.raises(ValueError, match="belongs to run 'run-WRONG-ALIEN', but run directory has run_id 'run-correct'"):
            append_result(run_dir, alien_trial)
