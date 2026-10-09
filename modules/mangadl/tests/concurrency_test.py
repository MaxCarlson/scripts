from __future__ import annotations

import logging
from types import SimpleNamespace

from mangadl.concurrency import plan_manga18fx_concurrency
from mangadl.manager import DownloadManager
from mangadl.models import WorkerSnapshot


def test_concurrency_plan_defaults_to_safe_four_worker_ceiling() -> None:
    plan = plan_manga18fx_concurrency(6, 4, logical_cpus=24)

    assert plan.logical_cpus == 24
    assert plan.budget == 23
    assert plan.maximum_workers == 4
    assert plan.effective_workers == 4
    assert plan.effective_image_workers == 4
    assert plan.effective_total == 16
    assert plan.adjusted


def test_concurrency_plan_preserves_known_working_4_by_5_setting() -> None:
    plan = plan_manga18fx_concurrency(4, 5, logical_cpus=24)

    assert plan.effective_workers == 4
    assert plan.effective_image_workers == 5
    assert plan.effective_total == 20
    assert not plan.adjusted


def test_fast_storage_defaults_to_hard_outer_worker_limit() -> None:
    plan = plan_manga18fx_concurrency(8, 2, logical_cpus=24, fast_storage=True)

    assert plan.maximum_workers == 8
    assert plan.effective_workers == 8


def test_explicit_worker_override_still_obeys_cpu_budget() -> None:
    plan = plan_manga18fx_concurrency(
        6,
        4,
        logical_cpus=24,
        maximum_workers=8,
    )

    assert plan.maximum_workers == 8
    assert plan.effective_workers == 6
    assert plan.effective_image_workers == 3
    assert plan.effective_total == 18
    assert plan.effective_total < plan.logical_cpus


def test_concurrency_plan_caps_excess_outer_workers_at_hard_override() -> None:
    plan = plan_manga18fx_concurrency(
        30,
        8,
        logical_cpus=24,
        maximum_workers=8,
    )

    assert plan.effective_workers == 8
    assert plan.effective_image_workers == 2
    assert plan.effective_total == 16


def _manager_for_runtime_test(*, maximum_workers: int) -> DownloadManager:
    manager = DownloadManager.__new__(DownloadManager)
    manager.target_workers = 4
    manager.maximum_workers = maximum_workers
    manager.image_workers = 5
    manager.concurrency_budget = 23
    manager.processes = {}
    manager.worker_costs = {}
    manager.snapshots = {slot: WorkerSnapshot(slot) for slot in range(1, 5)}
    manager.runtime_notice = ""
    manager.logger = logging.getLogger(f"mangadl.tests.runtime.{maximum_workers}")
    manager.options = SimpleNamespace(worker_start_delay=2.0)
    manager.stop_requested = False
    return manager


def test_runtime_worker_increase_stops_at_safe_ceiling() -> None:
    manager = _manager_for_runtime_test(maximum_workers=4)

    manager._adjust_runtime("workers_up")

    assert manager.target_workers == 4
    assert "maximum of 4" in manager.runtime_notice


def test_runtime_override_still_obeys_aggregate_budget() -> None:
    manager = _manager_for_runtime_test(maximum_workers=8)

    manager._adjust_runtime("workers_up")
    assert manager.target_workers == 4
    assert "blocked" in manager.runtime_notice

    manager._adjust_runtime("images_down")
    manager._adjust_runtime("workers_up")
    assert manager.image_workers == 4
    assert manager.target_workers == 5
    assert 5 in manager.snapshots
    assert "staggered" in manager.runtime_notice

    manager._adjust_runtime("workers_up")
    assert manager.target_workers == 5
    assert "blocked" in manager.runtime_notice


def test_runtime_graceful_quit_stops_new_assignments() -> None:
    manager = _manager_for_runtime_test(maximum_workers=8)

    manager._adjust_runtime("quit_after_current")

    assert manager.stop_requested
    assert "no new downloads" in manager.runtime_notice


def test_retired_active_worker_remains_visible_until_it_finishes() -> None:
    manager = _manager_for_runtime_test(maximum_workers=8)

    class Process:
        returncode = None

        def __init__(self) -> None:
            self.running = True

        def poll(self):
            return None if self.running else 0

    process = Process()
    manager.processes[4] = process
    manager.target_workers = 3

    assert 4 in manager._visible_snapshots()
    process.running = False
    assert 4 not in manager._visible_snapshots()
