"""
Task Divergence Matrix builder and utilities.

Calculates cross-variant per-task outcome matrices, identifying agreement, divergence,
and failure patterns across models.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from .models import TaskDivergenceRow, TaskVariantResult, TrialDetail


def compute_task_cell_status(trials: Sequence[TrialDetail]) -> str:
    """
    Determine aggregate status for a task x variant cell:
    - 'passed': all trials passed
    - 'failed': all trials failed
    - 'timed_out': all trials timed out
    - 'infra_error': all trials had infrastructure errors
    - 'unscored': all trials were unscored
    - 'mixed': trials had mixed outcomes (e.g. 1 pass, 1 fail)
    """
    if not trials:
        return "unscored"

    statuses = {t.status for t in trials}
    if len(statuses) == 1:
        single = next(iter(statuses))
        if single == "infrastructure_error":
            return "infra_error"
        return single

    # Mixed statuses: check if there are multiple outcome types
    return "mixed"


def build_task_divergence_matrix(
    trials: Sequence[TrialDetail],
    task_categories: Optional[Mapping[str, str]] = None,
    ordered_task_ids: Optional[Sequence[str]] = None,
    ordered_variant_ids: Optional[Sequence[str]] = None,
) -> list[TaskDivergenceRow]:
    """
    Construct a structured Task Divergence Matrix from a collection of TrialDetail items.

    Args:
        trials: Sequence of TrialDetail items.
        task_categories: Optional mapping of task_id to category name.
        ordered_task_ids: Optional explicit order for task rows.
        ordered_variant_ids: Optional explicit order for variant columns.

    Returns:
        List of TaskDivergenceRow instances.
    """
    cat_map = dict(task_categories or {})

    # Group trials by (task_id, variant_id)
    grouped: dict[tuple[str, str], list[TrialDetail]] = {}
    all_tasks: set[str] = set()
    all_variants: set[str] = set()

    for t in trials:
        all_tasks.add(t.task_id)
        all_variants.add(t.variant_id)
        grouped.setdefault((t.task_id, t.variant_id), []).append(t)

    sorted_tasks = list(ordered_task_ids) if ordered_task_ids else sorted(all_tasks)
    sorted_variants = list(ordered_variant_ids) if ordered_variant_ids else sorted(all_variants)

    matrix: list[TaskDivergenceRow] = []

    for task_id in sorted_tasks:
        category = cat_map.get(task_id, "general")
        variant_results: dict[str, TaskVariantResult] = {}

        for var_id in sorted_variants:
            cell_trials = grouped.get((task_id, var_id), [])
            if not cell_trials:
                variant_results[var_id] = TaskVariantResult(
                    status="unscored",
                    pass_rate=None,
                    passed=0,
                    total=0,
                    trial_ids=[],
                    mean_duration_ms=None,
                )
                continue

            status = compute_task_cell_status(cell_trials)
            total = len(cell_trials)
            passed = sum(1 for t in cell_trials if t.status == "passed")
            scored_denom = sum(
                1 for t in cell_trials if t.status in ("passed", "failed", "timed_out")
            )
            pass_rate = round(passed / scored_denom, 4) if scored_denom > 0 else None

            durations = [t.duration_ms for t in cell_trials if t.duration_ms > 0]
            mean_dur = round(sum(durations) / len(durations), 1) if durations else None

            variant_results[var_id] = TaskVariantResult(
                status=status,
                pass_rate=pass_rate,
                passed=passed,
                total=total,
                trial_ids=[t.trial_id for t in cell_trials],
                mean_duration_ms=mean_dur,
            )

        matrix.append(
            TaskDivergenceRow(
                task_id=task_id,
                category=category,
                results_by_variant=variant_results,
            )
        )

    return matrix
