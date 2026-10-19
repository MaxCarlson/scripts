"""
Pytest configuration and shared fixtures for benchmark_core tests.
"""

from pathlib import Path
import sys

# Ensure benchmark_core is importable without requiring editable install
MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import pytest

from benchmark_core.models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def canonical_run_file(fixtures_dir: Path) -> Path:
    return fixtures_dir / "canonical_run.json"


@pytest.fixture
def canonical_trials_file(fixtures_dir: Path) -> Path:
    return fixtures_dir / "canonical_trials.jsonl"


@pytest.fixture
def sample_metric_value() -> MetricValue:
    return MetricValue(
        value=150.5,
        unit="ms",
        source="timer",
        quality=MetricQuality.MEASURED,
        reason=None,
    )


@pytest.fixture
def sample_trial_result(sample_metric_value: MetricValue) -> TrialResult:
    return TrialResult(
        run_id="run-test-01",
        trial_id="trial-001",
        task_id="task_sort",
        variant_id="var-a",
        repetition=1,
        status=TrialStatus.PASSED,
        metrics={"duration.wall_ms": sample_metric_value},
        details={"evidence": ["evidence/trace.log"]},
    )


@pytest.fixture
def sample_run_info() -> RunInfo:
    return RunInfo(
        run_id="run-test-01",
        created_at="2026-10-19T02:30:00Z",
        suite_id="suite-sort-eval",
        suite_version="1.0.0",
        task_ids=["task_sort", "task_search"],
        variants={"var-a": {"opt": True}, "var-b": {"opt": False}},
        repetitions=3,
        scoring_basis="worker_first_attempt_full_success",
        environment={"os": "Windows 11"},
        metadata={"suite_fingerprint": "abc12345", "random_seed": 1234},
    )
