"""
Unit tests for SchedulerService orchestration.
"""
from datetime import datetime, timedelta
import pytest
from scheduler.models import Schedule, ScheduleTiming, Task
from scheduler.service import SchedulerService
from scheduler.storage import StorageManager


@pytest.fixture
def service_instance(tmp_path):
    data_file = tmp_path / "scheduler_data.json"
    storage = StorageManager(data_file=data_file)
    return SchedulerService(storage=storage)


def test_service_execute_task(service_instance):
    task = Task(
        name="ServiceEcho",
        environment="terminal",
        admin=False,
        code="echo 'Service Test Output'",
    )
    service_instance.storage.save_task(task)

    res = service_instance.execute_task("ServiceEcho")
    assert res.success is True
    assert "Service Test Output" in res.stdout

    # Verify task updated in storage
    saved = service_instance.storage.get_task("ServiceEcho")
    assert saved.last_status == "success"
    assert saved.last_exit_code == 0
    assert saved.last_run_time is not None

    # Verify central log entry
    logs = service_instance.central_logger.read_recent_entries(10)
    assert any("TASK_SUCCESS" in line for line in logs)

    # Verify task run log file exists
    runs = service_instance.task_logger.list_task_runs("ServiceEcho")
    assert len(runs) == 1


def test_service_execute_schedule(service_instance):
    sched = Schedule(name="NightlySync", timing=ScheduleTiming(timing_type="daily", at_time="01:00"))
    service_instance.storage.save_schedule(sched)

    t1 = Task(name="Sync1", schedule_name="NightlySync", environment="terminal", code="echo 'Sync 1'")
    t2 = Task(name="Sync2", schedule_name="NightlySync", environment="terminal", code="echo 'Sync 2'")
    service_instance.storage.save_task(t1)
    service_instance.storage.save_task(t2)

    results = service_instance.execute_schedule("NightlySync")
    assert len(results) == 2
    assert all(r.success for r in results)

    # Verify schedule last_run_time updated
    updated_sched = service_instance.storage.get_schedule("NightlySync")
    assert updated_sched.last_run_time is not None
    assert updated_sched.next_run_time is not None


def test_service_catch_up_in_run_once(service_instance):
    now = datetime(2026, 9, 26, 17, 0, 0)
    # Schedule missed at 02:00
    sched = Schedule(
        name="MissedSchedule",
        timing=ScheduleTiming(timing_type="daily", at_time="02:00"),
        catch_up=True,
        enabled=True,
        created_at=(now - timedelta(days=2)).isoformat(),
        last_run_time=(now - timedelta(days=1, hours=15)).isoformat(),
    )
    service_instance.storage.save_schedule(sched)

    task = Task(name="MissedTask", schedule_name="MissedSchedule", environment="terminal", code="echo 'Caught Up'")
    service_instance.storage.save_task(task)

    results = service_instance.run_once(now=now)
    assert len(results) == 1
    assert results[0].success is True

    # Check that warning about catch-up was logged
    logs = service_instance.central_logger.read_recent_entries(20)
    assert any("WARNING" in line and "Catch-up" in line for line in logs)
