"""
Unit tests for scheduler persistent JSON storage.
"""
import json

import pytest
from scheduler.models import Schedule, ScheduleTiming, Task
from scheduler.storage import StorageManager


@pytest.fixture
def storage_instance(tmp_path):
    json_file = tmp_path / "scheduler_data.json"
    return StorageManager(data_file=json_file)


def test_storage_initialization(storage_instance):
    assert storage_instance.data_file.exists()
    cfg = storage_instance.get_config()
    assert cfg.log_retention_runs == 10
    assert storage_instance.list_schedules() == []
    assert storage_instance.list_tasks() == []


def test_schedule_crud(storage_instance):
    timing = ScheduleTiming(timing_type="daily", at_time="03:00")
    sched = Schedule(name="NightlySync", timing=timing, catch_up=True)
    storage_instance.save_schedule(sched)

    recovered = storage_instance.get_schedule("NightlySync")
    assert recovered is not None
    assert recovered.name == "NightlySync"
    assert recovered.timing.at_time == "03:00"

    # List
    all_s = storage_instance.list_schedules()
    assert len(all_s) == 1
    assert all_s[0].name == "NightlySync"

    # Delete
    success, orphaned = storage_instance.delete_schedule("NightlySync")
    assert success is True
    assert storage_instance.get_schedule("NightlySync") is None


def test_task_crud_and_orphan_handling(storage_instance):
    sched = Schedule(name="MainSchedule")
    storage_instance.save_schedule(sched)

    t1 = Task(name="Task1", schedule_name="MainSchedule", environment="terminal", code="echo 1")
    t2 = Task(name="Task2", schedule_name="MainSchedule", environment="terminal", code="echo 2")
    storage_instance.save_task(t1)
    storage_instance.save_task(t2)

    attached = storage_instance.get_attached_tasks("MainSchedule")
    assert len(attached) == 2
    assert {t.name for t in attached} == {"Task1", "Task2"}

    # Delete schedule and verify orphaned tasks
    success, orphaned = storage_instance.delete_schedule("MainSchedule", orphan_tasks=True)
    assert success is True
    assert set(orphaned) == {"Task1", "Task2"}

    t1_after = storage_instance.get_task("Task1")
    t2_after = storage_instance.get_task("Task2")
    assert t1_after is not None
    assert t1_after.schedule_name is None  # Orphaned, detached cleanly
    assert t2_after is not None
    assert t2_after.schedule_name is None

    # Delete task
    del_ok = storage_instance.delete_task("Task1")
    assert del_ok is True
    assert storage_instance.get_task("Task1") is None


def test_attached_tasks_follow_assignment_order_and_reattach_appends(storage_instance):
    storage_instance.save_schedule(Schedule(name="FirstSchedule"))
    storage_instance.save_schedule(Schedule(name="SecondSchedule"))
    storage_instance.save_task(Task(name="Zulu First", schedule_name="FirstSchedule"))
    storage_instance.save_task(Task(name="Alpha Second", schedule_name="FirstSchedule"))

    assert [task.name for task in storage_instance.get_attached_tasks("FirstSchedule")] == [
        "Zulu First",
        "Alpha Second",
    ]

    first = storage_instance.get_task("Zulu First")
    first.schedule_name = "SecondSchedule"
    storage_instance.save_task(first)
    first.schedule_name = "FirstSchedule"
    storage_instance.save_task(first)

    assert [task.name for task in storage_instance.get_attached_tasks("FirstSchedule")] == [
        "Alpha Second",
        "Zulu First",
    ]


def test_legacy_attached_tasks_migrate_in_existing_json_order(storage_instance):
    raw = json.loads(storage_instance.data_file.read_text(encoding="utf-8"))
    first = Task(name="Zulu First", schedule_name="LegacySchedule").to_dict()
    second = Task(name="Alpha Second", schedule_name="LegacySchedule").to_dict()
    first.pop("schedule_order")
    second.pop("schedule_order")
    raw["tasks"] = {"Zulu First": first, "Alpha Second": second}
    storage_instance.data_file.write_text(json.dumps(raw), encoding="utf-8")

    attached = storage_instance.get_attached_tasks("LegacySchedule")

    assert [task.name for task in attached] == ["Zulu First", "Alpha Second"]
    assert [task.schedule_order for task in attached] == [0, 1]
