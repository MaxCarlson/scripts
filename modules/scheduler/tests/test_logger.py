"""
Unit tests for central system logger and task run log retention.
"""
import re
from datetime import datetime
from scheduler.logger import CentralLogger, TaskLogger
from scheduler.models import ExecutionResult


def test_central_logger_strict_format(tmp_path):
    log_file = tmp_path / "system.log"
    logger = CentralLogger(log_file)

    dt = datetime(2026, 9, 26, 15, 30, 45)
    entry = logger.log("SCHEDULE_CREATE", "Created schedule 'DailyBackup' with timing daily at 00:00", dt=dt)

    assert entry == '[2026-09-26 15:30:45] | [SCHEDULE_CREATE]: "Created schedule \'DailyBackup\' with timing daily at 00:00"'

    # Verify content in file
    content = log_file.read_text(encoding="utf-8")
    assert content.strip() == entry

    # Verify strict regex pattern: ^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \| \[[A-Z_]+\]: ".*"$
    pattern = r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \| \[[A-Z_]+\]: \".*\"$"
    assert re.match(pattern, entry) is not None

    # Test semantic helper methods
    logger.log_task_create("Backup", "pwsh", True, "DailyBackup")
    logger.log_warning("Catch-up executed")
    logger.log_error("Failure encountered")

    recent = logger.read_recent_entries(n=10)
    assert len(recent) == 4
    for line in recent:
        assert re.match(pattern, line) is not None


def test_task_logger_single_file_and_bounded_retention(tmp_path):
    tasks_dir = tmp_path / "tasks"
    # Set retention to 3 runs
    task_logger = TaskLogger(tasks_dir, default_retention=3)

    task_name = "MySpecialTask"
    log_file = task_logger.get_task_log_path(task_name)

    for i in range(5):
        result = ExecutionResult(
            task_name=task_name,
            schedule_name="Nightly",
            timestamp=f"2026-09-26T15:0{i}:00",
            exit_code=0,
            stdout=f"Output run {i}",
            stderr="",
            duration_sec=0.1,
            environment="terminal",
            admin=False,
            success=True,
        )
        task_logger.log_run(result, script_code=f"echo run {i}", retention=3)

    # 1. Verify single log file exists directly in tasks/
    assert log_file.is_file()
    assert log_file.name == "MySpecialTask.log"

    # 2. Verify bounded retention in the single file (runs 0 and 1 truncated, runs 2, 3, 4 retained)
    raw_content = log_file.read_text(encoding="utf-8")
    assert "Output run 0" not in raw_content
    assert "Output run 1" not in raw_content
    assert "Output run 2" in raw_content
    assert "Output run 3" in raw_content
    assert "Output run 4" in raw_content

    # 3. Verify helper methods
    runs = task_logger.list_task_runs(task_name, count=10)
    assert len(runs) == 3

    latest = task_logger.read_latest_run_content(task_name)
    assert latest is not None
    assert "Output run 4" in latest

    all_logs = task_logger.list_all_task_logs()
    assert len(all_logs) == 1
    assert all_logs[0]["task_slug"] == "MySpecialTask"
    assert all_logs[0]["run_count"] == 3
