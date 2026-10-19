"""
Contract tests for benchmark_core data models and serialization helpers.

Validates Gate 1 requirements:
- RunInfo, TrialResult, and MetricValue dataclasses
- Strict status and quality validation
- Rejection of NaN, Infinity, and non-numeric metric values
- UTC timestamp normalization
- Safe relative path validation for evidence references
- Canonical fixtures loading and round-trip serialization
"""

from pathlib import Path
import pytest

from benchmark_core.models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
    VALID_QUALITIES,
    VALID_STATUSES,
    is_safe_relative_path,
    metric_value_from_dict,
    metric_value_to_dict,
    run_info_from_dict,
    run_info_to_dict,
    trial_result_from_dict,
    trial_result_to_dict,
    validate_relative_path,
)


class TestMetricValue:
    """Tests for MetricValue model and validation."""

    def test_valid_metric_int_and_float(self) -> None:
        mv_float = MetricValue(value=12.34, unit="ms", source="timer", quality=MetricQuality.MEASURED)
        assert mv_float.value == 12.34
        assert mv_float.unit == "ms"
        assert mv_float.quality == "measured"

        mv_int = MetricValue(value=42, unit="tokens", source="api", quality="derived")
        assert mv_int.value == 42
        assert mv_int.quality == "derived"

    def test_missing_metric_null_value(self) -> None:
        mv_null = MetricValue(
            value=None,
            unit="tokens",
            source="api",
            quality=MetricQuality.UNAVAILABLE,
            reason="stream interrupted",
        )
        assert mv_null.value is None
        assert mv_null.quality == "unavailable"
        assert mv_null.reason == "stream interrupted"

    def test_all_metric_qualities(self) -> None:
        for q in VALID_QUALITIES:
            mv = MetricValue(value=1.0, unit="x", source="src", quality=q)
            assert mv.quality == q

    def test_invalid_quality_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid metric quality"):
            MetricValue(value=1.0, unit="ms", source="src", quality="super_measured")

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot be NaN"):
            MetricValue(value=float("nan"), unit="ms", source="timer", quality="measured")

    def test_inf_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot be NaN or Infinity"):
            MetricValue(value=float("inf"), unit="ms", source="timer", quality="measured")
        with pytest.raises(ValueError, match="cannot be NaN or Infinity"):
            MetricValue(value=float("-inf"), unit="ms", source="timer", quality="measured")

    def test_bool_rejected_as_numeric(self) -> None:
        with pytest.raises(TypeError, match="must be an int or float"):
            MetricValue(value=True, unit="count", source="harness", quality="measured")  # type: ignore

    def test_non_numeric_type_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be an int or float"):
            MetricValue(value="100", unit="count", source="harness", quality="measured")  # type: ignore

    def test_empty_unit_or_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="Metric unit must be a non-empty string"):
            MetricValue(value=1.0, unit="", source="timer", quality="measured")
        with pytest.raises(ValueError, match="Metric source must be a non-empty string"):
            MetricValue(value=1.0, unit="ms", source="   ", quality="measured")

    def test_metric_value_round_trip(self) -> None:
        mv = MetricValue(value=100.5, unit="ms", source="timer", quality="measured", reason=None)
        d = metric_value_to_dict(mv)
        mv2 = metric_value_from_dict(d)
        assert mv == mv2

        json_str = mv.to_json()
        mv3 = MetricValue.from_json(json_str)
        assert mv == mv3

    def test_metric_value_from_dict_validation(self) -> None:
        with pytest.raises(ValueError, match="Missing required fields"):
            metric_value_from_dict({"value": 1.0, "unit": "ms"})
        with pytest.raises(ValueError, match="Unexpected fields"):
            metric_value_from_dict({
                "value": 1.0,
                "unit": "ms",
                "source": "timer",
                "quality": "measured",
                "extra_key": 123,
            })


class TestTrialResult:
    """Tests for TrialResult model and validation."""

    def test_all_valid_statuses(self) -> None:
        for status in VALID_STATUSES:
            tr = TrialResult(
                run_id="run-1",
                trial_id=f"trial-{status}",
                task_id="task-1",
                variant_id="var-1",
                repetition=1,
                status=status,
                metrics={},
                details={},
            )
            assert tr.status == status

    def test_invalid_status_rejected(self) -> None:
        for invalid_status in ["success", "error", "skipped", "timeout", ""]:
            with pytest.raises(ValueError, match="Invalid trial status"):
                TrialResult(
                    run_id="run-1",
                    trial_id="trial-err",
                    task_id="task-1",
                    variant_id="var-1",
                    repetition=1,
                    status=invalid_status,
                )

    def test_namespaced_metric_keys(self) -> None:
        metrics = {
            "duration.wall_ms": MetricValue(120.0, "ms", "timer", "measured"),
            "tokens.worker.input": MetricValue(500, "tokens", "api", "measured"),
            "tokens.coordinator.output": MetricValue(150, "tokens", "api", "measured"),
            "agent.scope_violations": MetricValue(0, "count", "harness", "derived"),
        }
        tr = TrialResult(
            run_id="run-1",
            trial_id="trial-metrics",
            task_id="task-1",
            variant_id="var-1",
            repetition=1,
            status=TrialStatus.PASSED,
            metrics=metrics,
        )
        assert set(tr.metrics.keys()) == {
            "duration.wall_ms",
            "tokens.worker.input",
            "tokens.coordinator.output",
            "agent.scope_violations",
        }

    def test_details_preservation(self) -> None:
        custom_details = {
            "prompt_hash": "abcdef123",
            "retry_history": [{"attempt": 1, "error": "rate_limit"}],
            "evidence": ["evidence/run1.log", "evidence/patch.diff"],
        }
        tr = TrialResult(
            run_id="run-1",
            trial_id="trial-det",
            task_id="task-1",
            variant_id="var-1",
            repetition=1,
            status=TrialStatus.PASSED,
            metrics={},
            details=custom_details,
        )
        assert tr.details == custom_details

    def test_unsafe_evidence_path_in_details_rejected(self) -> None:
        unsafe_details = {"evidence": ["/etc/shadow"]}
        with pytest.raises(ValueError, match="Unsafe or invalid relative path"):
            TrialResult(
                run_id="run-1",
                trial_id="trial-unsafe",
                task_id="task-1",
                variant_id="var-1",
                repetition=1,
                status=TrialStatus.PASSED,
                details=unsafe_details,
            )

        traversal_details = {"evidence": ["evidence/../../escape.log"]}
        with pytest.raises(ValueError, match="Unsafe or invalid relative path"):
            TrialResult(
                run_id="run-1",
                trial_id="trial-traversal",
                task_id="task-1",
                variant_id="var-1",
                repetition=1,
                status=TrialStatus.PASSED,
                details=traversal_details,
            )

    def test_trial_result_round_trip(self, sample_trial_result: TrialResult) -> None:
        d = trial_result_to_dict(sample_trial_result)
        tr2 = trial_result_from_dict(d)
        assert sample_trial_result == tr2

        json_str = sample_trial_result.to_json()
        tr3 = TrialResult.from_json(json_str)
        assert sample_trial_result == tr3


class TestRunInfo:
    """Tests for RunInfo model, metadata preservation, and validation."""

    def test_run_info_creation_and_reproducibility_metadata(self, sample_run_info: RunInfo) -> None:
        assert sample_run_info.run_id == "run-test-01"
        assert sample_run_info.created_at == "2026-10-19T02:30:00Z"
        assert sample_run_info.repetitions == 3
        # Reproducibility metadata check per Amendment 1
        assert sample_run_info.metadata["suite_fingerprint"] == "abc12345"
        assert sample_run_info.metadata["random_seed"] == 1234

    def test_utc_timestamp_normalization(self) -> None:
        ri = RunInfo(
            run_id="run-ts",
            created_at="2026-10-19 02:30:00+00:00",
            suite_id="s1",
            suite_version="1.0",
            task_ids=["t1"],
            variants={"v1": {}},
            repetitions=1,
            scoring_basis="basis",
        )
        assert ri.created_at == "2026-10-19T02:30:00Z"

    def test_invalid_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid ISO 8601 timestamp"):
            RunInfo(
                run_id="run-bad-ts",
                created_at="invalid-date-string",
                suite_id="s1",
                suite_version="1.0",
                task_ids=["t1"],
                variants={"v1": {}},
                repetitions=1,
                scoring_basis="basis",
            )

    def test_zero_or_negative_repetitions_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive int >= 1"):
            RunInfo(
                run_id="run-rep",
                created_at="2026-10-19T02:30:00Z",
                suite_id="s1",
                suite_version="1.0",
                task_ids=["t1"],
                variants={"v1": {}},
                repetitions=0,
                scoring_basis="basis",
            )

    def test_empty_variants_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty dict"):
            RunInfo(
                run_id="run-var",
                created_at="2026-10-19T02:30:00Z",
                suite_id="s1",
                suite_version="1.0",
                task_ids=["t1"],
                variants={},
                repetitions=1,
                scoring_basis="basis",
            )

    def test_run_info_round_trip(self, sample_run_info: RunInfo) -> None:
        d = run_info_to_dict(sample_run_info)
        ri2 = run_info_from_dict(d)
        assert sample_run_info == ri2

        json_str = sample_run_info.to_json()
        ri3 = RunInfo.from_json(json_str)
        assert sample_run_info == ri3


class TestRelativePathValidation:
    """Tests for relative path security."""

    @pytest.mark.parametrize(
        "safe_path",
        [
            "evidence/run1.log",
            "evidence/worker_diff.patch",
            "logs/stdout.txt",
            "trace.json",
            "sub/dir/nested/file.txt",
        ],
    )
    def test_safe_paths(self, safe_path: str) -> None:
        assert is_safe_relative_path(safe_path) is True
        assert validate_relative_path(safe_path) == safe_path.replace("\\", "/")

    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "",
            "   ",
            "/absolute/posix/path",
            "//network/share",
            "\\absolute\\windows\\path",
            "C:/Windows/system32",
            "D:\\data\\file.txt",
            "../parent_escape.txt",
            "evidence/../../escape.txt",
            "evidence/subdir/../../../root.txt",
            "file\x00with_null_byte",
        ],
    )
    def test_unsafe_paths(self, unsafe_path: str) -> None:
        assert is_safe_relative_path(unsafe_path) is False
        with pytest.raises(ValueError, match="Unsafe or invalid relative path"):
            validate_relative_path(unsafe_path)


class TestCanonicalFixtures:
    """Validates that repository canonical fixtures load and pass all contracts."""

    def test_load_canonical_run_fixture(self, canonical_run_file: Path) -> None:
        assert canonical_run_file.is_file()
        content = canonical_run_file.read_text(encoding="utf-8")
        run_info = RunInfo.from_json(content)

        assert run_info.run_id == "run-20261019-0230-llm-eval"
        assert run_info.suite_id == "agent-coding-eval"
        assert len(run_info.task_ids) == 3
        assert len(run_info.variants) == 2
        assert run_info.repetitions == 2
        assert "suite_fingerprint" in run_info.metadata
        assert "random_seed" in run_info.metadata

        # Round trip
        d = run_info.to_dict()
        assert RunInfo.from_dict(d) == run_info

    def test_load_canonical_trials_fixture(self, canonical_trials_file: Path) -> None:
        assert canonical_trials_file.is_file()
        lines = [line.strip() for line in canonical_trials_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 8

        statuses_found: set[str] = set()
        for line in lines:
            trial = TrialResult.from_json(line)
            assert trial.run_id == "run-20261019-0230-llm-eval"
            statuses_found.add(trial.status)

            # Round trip
            d = trial.to_dict()
            assert TrialResult.from_dict(d) == trial

        # Verify all 5 statuses are represented in the canonical fixture
        assert statuses_found == VALID_STATUSES
