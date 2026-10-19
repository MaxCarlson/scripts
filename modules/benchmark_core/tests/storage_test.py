"""
Tests for benchmark_core filesystem persistence and storage handling.
"""

from pathlib import Path
import pytest

from benchmark_core.models import (
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
)
from benchmark_core.storage import (
    CorruptedDataError,
    DuplicateTrialError,
    append_result,
    append_results,
    load_run,
    load_run_info,
    load_trials,
    save_run,
)


def test_save_and_load_run_info(tmp_path: Path, sample_run_info: RunInfo) -> None:
    run_dir = tmp_path / "test_run_dir"
    run_file = save_run(run_dir, sample_run_info)

    assert run_file.is_file()
    assert run_file.name == "run.json"

    # Reject overwrite by default
    with pytest.raises(FileExistsError):
        save_run(run_dir, sample_run_info, overwrite=False)

    # Allow overwrite
    save_run(run_dir, sample_run_info, overwrite=True)

    loaded = load_run_info(run_dir)
    assert loaded == sample_run_info


def test_append_single_and_batch_trials(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_trials"
    t1 = TrialResult(
        run_id="r1",
        trial_id="t-001",
        task_id="task_a",
        variant_id="v1",
        repetition=1,
        status=TrialStatus.PASSED,
        metrics={"duration.wall_ms": MetricValue(100.0, "ms", "timer", "measured")},
    )
    t2 = TrialResult(
        run_id="r1",
        trial_id="t-002",
        task_id="task_a",
        variant_id="v1",
        repetition=2,
        status=TrialStatus.FAILED,
        metrics={"duration.wall_ms": MetricValue(120.0, "ms", "timer", "measured")},
    )

    trials_file = append_result(run_dir, t1)
    assert trials_file.is_file()
    assert trials_file.name == "trials.jsonl"

    append_result(run_dir, t2)

    loaded = load_trials(run_dir)
    assert len(loaded) == 2
    assert loaded[0] == t1
    assert loaded[1] == t2


def test_duplicate_trial_id_rejection(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_dup"
    t1 = TrialResult(
        run_id="r1",
        trial_id="duplicate-id",
        task_id="task_a",
        variant_id="v1",
        repetition=1,
        status=TrialStatus.PASSED,
    )
    append_result(run_dir, t1)

    # Appending the same trial_id should raise DuplicateTrialError
    with pytest.raises(DuplicateTrialError, match="already exists"):
        append_result(run_dir, t1)

    # In batch append
    t_dup_in_batch = [
        TrialResult("r1", "t-new", "t1", "v1", 1, TrialStatus.PASSED),
        TrialResult("r1", "t-new", "t1", "v1", 2, TrialStatus.PASSED),
    ]
    with pytest.raises(DuplicateTrialError, match="same append batch"):
        append_results(run_dir, t_dup_in_batch)


def test_corrupted_jsonl_handling(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_corrupt"
    run_dir.mkdir(parents=True)
    trials_file = run_dir / "trials.jsonl"

    # Write one valid line, one corrupted line, one valid line
    t1 = TrialResult("r1", "t-1", "task_a", "v1", 1, TrialStatus.PASSED)
    t2 = TrialResult("r1", "t-2", "task_a", "v1", 2, TrialStatus.PASSED)

    trials_file.write_text(
        t1.to_json() + "\n" + "{malformed json line\n" + t2.to_json() + "\n",
        encoding="utf-8",
    )

    # Default should raise CorruptedDataError
    with pytest.raises(CorruptedDataError, match="Failed to load TrialResult"):
        load_trials(run_dir, ignore_corrupted=False)

    # With ignore_corrupted=True, it should return the valid records
    recovered = load_trials(run_dir, ignore_corrupted=True)
    assert len(recovered) == 2
    assert recovered[0].trial_id == "t-1"
    assert recovered[1].trial_id == "t-2"


def test_load_full_run(tmp_path: Path, sample_run_info: RunInfo, sample_trial_result: TrialResult) -> None:
    run_dir = tmp_path / "full_run"
    save_run(run_dir, sample_run_info)
    append_result(run_dir, sample_trial_result)

    ri, trials = load_run(run_dir)
    assert ri == sample_run_info
    assert len(trials) == 1
    assert trials[0] == sample_trial_result
