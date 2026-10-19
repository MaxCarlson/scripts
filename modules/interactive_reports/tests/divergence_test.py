"""Tests for Task Divergence Matrix construction and status classification."""

from interactive_reports.divergence import (
    build_task_divergence_matrix,
    compute_task_cell_status,
)
from interactive_reports.models import TrialDetail


def _make_trial(
    trial_id: str,
    variant_id: str,
    task_id: str,
    status: str,
    duration_ms: float = 1000.0,
) -> TrialDetail:
    return TrialDetail(
        trial_id=trial_id,
        variant_id=variant_id,
        task_id=task_id,
        status=status,
        duration_ms=duration_ms,
    )


def test_compute_task_cell_status_empty():
    assert compute_task_cell_status([]) == "unscored"


def test_compute_task_cell_status_uniform():
    t_pass = [_make_trial("t1", "m1", "task_a", "passed"), _make_trial("t2", "m1", "task_a", "passed")]
    assert compute_task_cell_status(t_pass) == "passed"

    t_fail = [_make_trial("t1", "m1", "task_a", "failed"), _make_trial("t2", "m1", "task_a", "failed")]
    assert compute_task_cell_status(t_fail) == "failed"

    t_time = [_make_trial("t1", "m1", "task_a", "timed_out")]
    assert compute_task_cell_status(t_time) == "timed_out"

    t_infra = [_make_trial("t1", "m1", "task_a", "infrastructure_error")]
    assert compute_task_cell_status(t_infra) == "infra_error"


def test_compute_task_cell_status_mixed():
    trials = [
        _make_trial("t1", "m1", "task_a", "passed"),
        _make_trial("t2", "m1", "task_a", "failed"),
    ]
    assert compute_task_cell_status(trials) == "mixed"


def test_build_task_divergence_matrix():
    trials = [
        _make_trial("t1", "m1", "task_a", "passed"),
        _make_trial("t2", "m1", "task_a", "passed"),
        _make_trial("t3", "m2", "task_a", "failed"),
        _make_trial("t4", "m1", "task_b", "timed_out"),
        _make_trial("t5", "m2", "task_b", "passed"),
    ]

    cat_map = {"task_a": "cli", "task_b": "refactor"}
    matrix = build_task_divergence_matrix(
        trials,
        task_categories=cat_map,
        ordered_variant_ids=["m1", "m2"],
        ordered_task_ids=["task_a", "task_b"],
    )

    assert len(matrix) == 2
    row_a = matrix[0]
    assert row_a.task_id == "task_a"
    assert row_a.category == "cli"
    assert row_a.results_by_variant["m1"].status == "passed"
    assert row_a.results_by_variant["m1"].pass_rate == 1.0
    assert row_a.results_by_variant["m1"].trial_ids == ["t1", "t2"]

    assert row_a.results_by_variant["m2"].status == "failed"
    assert row_a.results_by_variant["m2"].pass_rate == 0.0
    assert row_a.results_by_variant["m2"].trial_ids == ["t3"]

    row_b = matrix[1]
    assert row_b.task_id == "task_b"
    assert row_b.category == "refactor"
    assert row_b.results_by_variant["m1"].status == "timed_out"
    assert row_b.results_by_variant["m1"].pass_rate == 0.0

    assert row_b.results_by_variant["m2"].status == "passed"
    assert row_b.results_by_variant["m2"].pass_rate == 1.0


def test_build_task_divergence_matrix_unscored_handling():
    # Model m2 was not evaluated on task_c
    trials = [
        _make_trial("t1", "m1", "task_c", "passed"),
    ]
    matrix = build_task_divergence_matrix(
        trials,
        ordered_variant_ids=["m1", "m2"],
        ordered_task_ids=["task_c"],
    )
    assert len(matrix) == 1
    assert matrix[0].results_by_variant["m2"].status == "unscored"
    assert matrix[0].results_by_variant["m2"].pass_rate is None
    assert matrix[0].results_by_variant["m2"].trial_ids == []
