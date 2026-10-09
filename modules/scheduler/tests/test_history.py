"""Structured scheduler history and conservative legacy import."""
from datetime import datetime, timedelta

from scheduler.history import SchedulerHistory
from scheduler.logger import TaskLogger
from scheduler.models import ExecutionResult, Schedule, Task
from scheduler.service import SchedulerService
from scheduler.storage import StorageManager


def result(name: str, *, output: str = "done", exit_code: int = 0) -> ExecutionResult:
    return ExecutionResult(
        task_name=name, schedule_name=None, timestamp=datetime.now().astimezone().isoformat(),
        exit_code=exit_code, stdout=output, stderr="", duration_sec=2.5,
        environment="terminal", admin=False, success=exit_code == 0,
    )


def test_schedule_and_task_runs_are_linked_and_renames_keep_identity(tmp_path, monkeypatch):
    storage = StorageManager(data_file=tmp_path / "scheduler_data.json")
    schedule = Schedule(name="Nightly")
    task = Task(name="First", schedule_name="Nightly")
    storage.save_schedule(schedule)
    storage.save_task(task)
    service = SchedulerService(storage=storage)
    monkeypatch.setattr(service.executor, "execute", lambda item, **kwargs: result(item.name))

    service.execute_schedule("Nightly", scheduled_for=datetime.now().astimezone().isoformat())
    schedule_run = service.history.list_schedule_runs(schedule)[0]
    task_run = service.history.list_task_runs(task)[0]
    assert task_run.parent_id == schedule_run.record_id
    assert task_run.scheduled_for == schedule_run.scheduled_for
    assert service.history.store.get_run(task_run.record_id).stdout == "done"

    renamed = storage.get_task("First")
    storage.delete_task("First")
    renamed.name = "Renamed"
    storage.save_task(renamed)
    assert storage.get_task("Renamed").task_id == task.task_id
    assert storage.get_task("Renamed").attached_at == task.attached_at
    assert len(service.history.list_task_runs(renamed)) == 1


def test_legacy_name_collision_is_left_unassigned(tmp_path):
    storage = StorageManager(data_file=tmp_path / "scheduler_data.json")
    first = Task(name="Foo Bar")
    second = Task(name="Foo_Bar")
    storage.save_task(first)
    storage.save_task(second)
    logger = TaskLogger(tmp_path / "logs" / "tasks")
    logger.log_run(result(first.name))
    history = SchedulerHistory(storage, logger)
    assert [path.name for path in history.unmatched_legacy_logs()] == ["Foo_Bar.log"]
    assert history.list_task_runs(first) == []
    assert history.list_task_runs(second) == []


def test_output_retention_preserves_metadata_and_clear_resets_coverage(tmp_path):
    storage = StorageManager(data_file=tmp_path / "scheduler_data.json")
    task = Task(name="Old")
    storage.save_task(task)
    logger = TaskLogger(tmp_path / "logs" / "tasks")
    history = SchedulerHistory(storage, logger, output_retention_days=1)
    old_result = result(task.name, output="secret output")
    old_result.timestamp = (datetime.now().astimezone() - timedelta(days=3)).isoformat()
    run = history.record_task(task, old_result, origin="manual")
    retained = history.store.get_run(run.record_id)
    assert retained.status == "success"
    assert retained.stdout is None
    history.clear()
    assert history.list_task_runs(task) == []
    assert history.store.list_events(source="scheduler", event_type="HISTORY_STARTED")
    refreshed = SchedulerHistory(storage, logger)
    assert refreshed.coverage_start == history.coverage_start
