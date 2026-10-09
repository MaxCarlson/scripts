"""
Unit tests for SchedulerService orchestration.
"""
from datetime import datetime, timedelta
import pytest
from scheduler.models import ExecutionResult, Schedule, ScheduleTiming, Task
from scheduler.service import SchedulerService
from scheduler.storage import StorageManager
from unittest.mock import patch


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


def test_service_executes_attached_tasks_sequentially_in_assignment_order(service_instance):
    service_instance.storage.save_schedule(Schedule(name="OrderedSchedule"))
    service_instance.storage.save_task(Task(name="Zulu First", schedule_name="OrderedSchedule"))
    service_instance.storage.save_task(Task(name="Alpha Second", schedule_name="OrderedSchedule"))
    events = []

    def execute_in_order(task_name, dry_run=False, **kwargs):
        events.extend([f"start:{task_name}", f"finish:{task_name}"])
        return ExecutionResult(
            task_name=task_name,
            schedule_name="OrderedSchedule",
            timestamp=datetime.now().isoformat(),
            exit_code=0,
            stdout="",
            stderr="",
            duration_sec=0.0,
            environment="terminal",
            admin=False,
            success=True,
        )

    with patch.object(service_instance, "execute_task", side_effect=execute_in_order):
        results = service_instance.execute_schedule("OrderedSchedule")

    assert [result.task_name for result in results] == ["Zulu First", "Alpha Second"]
    assert events == ["start:Zulu First", "finish:Zulu First", "start:Alpha Second", "finish:Alpha Second"]


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


def test_queue_runner_test_requires_active_runner_and_admin_task(service_instance):
    task = Task(name="RunnerTest", admin=True, code="Write-Output test")
    service_instance.storage.save_task(task)

    with patch("scheduler.service.windows_task.get_runner_status", return_value={"installed": True, "state": "Ready"}):
        with pytest.raises(RuntimeError, match="not running"):
            service_instance.queue_runner_test("RunnerTest")
    assert list(service_instance.run_request_queue.directory.glob("*.json")) == []

    task.admin = False
    service_instance.storage.save_task(task)
    with pytest.raises(ValueError, match="only for tasks marked Admin"):
        service_instance.queue_runner_test("RunnerTest")


def test_queue_runner_test_uses_active_runner_and_due_request(service_instance):
    task = Task(name="RunnerTest", admin=True, code="Write-Output test")
    service_instance.storage.save_task(task)

    with patch("scheduler.service.windows_task.get_runner_status", return_value={
        "installed": True, "state": "Running", "adminWorker": {"installed": True, "state": "Running"}
    }):
        run_at = service_instance.queue_runner_test("RunnerTest", delay_seconds=10)

    requests = list(service_instance.run_request_queue.directory.glob("*.json"))
    assert len(requests) == 1
    assert run_at


def test_elevated_worker_processes_admin_request_without_persisting_scheduler_state(service_instance):
    task = Task(name="RunnerTest", admin=True, code="Write-Output test")
    service_instance.storage.save_task(task)
    service_instance.run_request_queue.enqueue(
        "RunnerTest", delay_seconds=1, now=datetime.now() - timedelta(seconds=2), visible_window=True
    )
    result = ExecutionResult(
        task_name="RunnerTest", schedule_name=None, timestamp="2026-10-08T12:00:00", exit_code=0,
        stdout="", stderr="", duration_sec=0.1, environment="pwsh", admin=True, success=True,
    )

    with patch.object(service_instance.executor, "execute", return_value=result) as execute:
        service_instance.process_admin_requests()

    execute.assert_called_once()
    assert execute.call_args.kwargs["visible_window"] is True
    result_files = list(service_instance.run_request_queue.directory.glob("*.result.json"))
    assert len(result_files) == 1
    assert service_instance.storage.get_task("RunnerTest").last_status is None


def test_limited_daemon_delegates_admin_tasks_but_runs_regular_tasks_itself(service_instance):
    admin_task = Task(name="Admin", admin=True, code="admin")
    regular_task = Task(name="Regular", admin=False, code="regular")
    service_instance.storage.save_task(admin_task)
    service_instance.storage.save_task(regular_task)
    service_instance._delegate_admin_tasks = True
    delegated = ExecutionResult(
        task_name="Admin", schedule_name=None, timestamp=datetime.now().isoformat(), exit_code=0,
        stdout="worker", stderr="", duration_sec=1, environment="pwsh", admin=True, success=True,
    )
    with patch.object(service_instance, "_execute_via_admin_worker", return_value=delegated) as worker, \
         patch.object(service_instance.executor, "execute", return_value=ExecutionResult(
             task_name="Regular", schedule_name=None, timestamp=datetime.now().isoformat(), exit_code=0,
             stdout="limited", stderr="", duration_sec=0, environment="terminal", admin=False, success=True,
         )) as execute:
        admin_result = service_instance.execute_task("Admin")
        regular_result = service_instance.execute_task("Regular")

    worker.assert_called_once()
    execute.assert_called_once()
    assert admin_result.stdout == "worker"
    assert regular_result.stdout == "limited"


def test_limited_daemon_waits_for_admin_worker_before_next_attached_task(service_instance):
    service_instance.storage.save_schedule(Schedule(name="Ordered"))
    service_instance.storage.save_task(Task(name="First Admin", schedule_name="Ordered", admin=True))
    service_instance.storage.save_task(Task(name="Second Regular", schedule_name="Ordered", admin=False))
    events = []

    def execute_admin(task, *, visible_window=False):
        events.append("admin-finished")
        return ExecutionResult(
            task_name=task.name, schedule_name=task.schedule_name, timestamp=datetime.now().isoformat(),
            exit_code=0, stdout="", stderr="", duration_sec=1, environment=task.environment, admin=True, success=True,
        )

    def execute_regular(task, *, visible_window=False):
        events.append("regular-started")
        return ExecutionResult(
            task_name=task.name, schedule_name=task.schedule_name, timestamp=datetime.now().isoformat(),
            exit_code=0, stdout="", stderr="", duration_sec=1, environment=task.environment, admin=False, success=True,
        )

    service_instance._delegate_admin_tasks = True
    with patch.object(service_instance, "_execute_via_admin_worker", side_effect=execute_admin), \
         patch.object(service_instance.executor, "execute", side_effect=execute_regular):
        service_instance.execute_schedule("Ordered")

    assert events == ["admin-finished", "regular-started"]
