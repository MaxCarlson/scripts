from __future__ import annotations

import logging

from mangadl.concurrency import plan_manga18fx_concurrency
from mangadl.manager import DownloadManager
from mangadl.models import WorkerSnapshot


def test_concurrency_plan_reserves_one_of_24_logical_cpus() -> None:
    plan = plan_manga18fx_concurrency(6, 4, logical_cpus=24)

    assert plan.logical_cpus == 24
    assert plan.budget == 23
    assert plan.effective_workers == 6
    assert plan.effective_image_workers == 3
    assert plan.effective_total == 18
    assert plan.effective_total < plan.logical_cpus
    assert plan.adjusted


def test_concurrency_plan_preserves_known_working_4_by_5_setting() -> None:
    plan = plan_manga18fx_concurrency(4, 5, logical_cpus=24)

    assert plan.effective_workers == 4
    assert plan.effective_image_workers == 5
    assert plan.effective_total == 20
    assert not plan.adjusted


def test_concurrency_plan_caps_excess_outer_workers() -> None:
    plan = plan_manga18fx_concurrency(30, 8, logical_cpus=24)

    assert plan.effective_workers == 23
    assert plan.effective_image_workers == 1
    assert plan.effective_total == 23


def test_runtime_tuning_obeys_budget() -> None:
    manager = DownloadManager.__new__(DownloadManager)
    manager.target_workers = 4
    manager.image_workers = 5
    manager.concurrency_budget = 23
    manager.processes = {}
    manager.worker_costs = {}
    manager.snapshots = {slot: WorkerSnapshot(slot) for slot in range(1, 5)}
    manager.runtime_notice = ""
    manager.logger = logging.getLogger("mangadl.tests.runtime")

    manager._adjust_runtime("workers_up")
    assert manager.target_workers == 4
    assert "blocked" in manager.runtime_notice

    manager._adjust_runtime("images_up")
    assert manager.image_workers == 5
    assert "blocked" in manager.runtime_notice

    manager._adjust_runtime("images_down")
    manager._adjust_runtime("workers_up")
    assert manager.image_workers == 4
    assert manager.target_workers == 5
    assert 5 in manager.snapshots

    manager._adjust_runtime("workers_up")
    assert manager.target_workers == 5
    assert "blocked" in manager.runtime_notice
