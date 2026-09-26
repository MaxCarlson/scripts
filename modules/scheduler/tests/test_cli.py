"""
Unit tests for scheduler CLI commands and subcommands.
"""
import json
import pytest
from scheduler.cli import main


@pytest.fixture
def data_file_arg(tmp_path):
    data_file = tmp_path / "scheduler_data.json"
    return ["-c", str(data_file)]


def test_cli_schedule_lifecycle(data_file_arg, capsys):
    # 1. Create schedule
    rc = main(data_file_arg + ["schedule", "create", "-n", "DailySync", "-t", "daily", "-a", "03:00", "-u"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Schedule 'DailySync' created" in out

    # 2. List schedules
    rc = main(data_file_arg + ["schedule", "list", "-f", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["name"] == "DailySync"

    # 3. Show schedule
    rc = main(data_file_arg + ["schedule", "show", "-n", "DailySync", "-f", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["name"] == "DailySync"
    assert data["timing"]["at_time"] == "03:00"

    # 4. Edit schedule
    rc = main(data_file_arg + ["schedule", "edit", "-n", "DailySync", "-a", "04:30", "-r", "RenamedSync"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "RenamedSync" in out

    # 5. Delete schedule
    rc = main(data_file_arg + ["schedule", "delete", "-n", "RenamedSync", "-y", "-f"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "deleted" in out


def test_cli_task_lifecycle_and_attach(data_file_arg, capsys):
    # Create schedule first
    main(data_file_arg + ["schedule", "create", "-n", "BackupSchedule", "-t", "daily", "-a", "01:00"])
    capsys.readouterr()

    # 1. Create task
    rc = main(data_file_arg + [
        "task", "create",
        "-n", "DbBackup",
        "-s", "BackupSchedule",
        "-e", "terminal",
        "-c", "echo 'backing up'",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Task 'DbBackup' created" in out

    # 2. List tasks
    rc = main(data_file_arg + ["task", "list", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["name"] == "DbBackup"
    assert data[0]["schedule_name"] == "BackupSchedule"

    # 3. Show task
    rc = main(data_file_arg + ["task", "show", "-n", "DbBackup", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "DbBackup"
    assert data["code"] == "echo 'backing up'"

    # 4. Detach task
    rc = main(data_file_arg + ["task", "detach", "-n", "DbBackup"])
    assert rc == 0
    capsys.readouterr()

    rc = main(data_file_arg + ["task", "show", "-n", "DbBackup", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["schedule_name"] is None

    # 5. Attach task back
    rc = main(data_file_arg + ["task", "attach", "-n", "DbBackup", "-s", "BackupSchedule"])
    assert rc == 0
    capsys.readouterr()

    # 6. Run task
    rc = main(data_file_arg + ["run", "-t", "DbBackup"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SUCCESS" in out
    assert "backing up" in out

    # 7. Delete task
    rc = main(data_file_arg + ["task", "delete", "-n", "DbBackup", "-y"])
    assert rc == 0


def test_cli_task_edit_all_properties(data_file_arg, capsys):
    # Setup schedule and task
    main(data_file_arg + ["schedule", "create", "-n", "FirstSchedule", "-t", "daily", "-a", "00:00"])
    main(data_file_arg + ["schedule", "create", "-n", "SecondSchedule", "-t", "daily", "-a", "06:00"])
    main(data_file_arg + [
        "task", "create",
        "-n", "OriginalTask",
        "-s", "FirstSchedule",
        "-e", "terminal",
        "-c", "echo 'initial'",
    ])
    capsys.readouterr()

    # Edit task: rename, change env, enable admin, change script code, re-link schedule, disable
    rc = main(data_file_arg + [
        "task", "edit",
        "-n", "OriginalTask",
        "-r", "ModifiedTask",
        "-e", "pwsh",
        "-a",
        "-c", "Write-Output 'modified'",
        "-s", "SecondSchedule",
        "-d",
    ])
    assert rc == 0
    capsys.readouterr()

    # Inspect modified task
    rc = main(data_file_arg + ["task", "show", "-n", "ModifiedTask", "-f", "json"])
    assert rc == 0
    t_data = json.loads(capsys.readouterr().out)
    assert t_data["name"] == "ModifiedTask"
    assert t_data["environment"] == "pwsh"
    assert t_data["admin"] is True
    assert t_data["code"] == "Write-Output 'modified'"
    assert t_data["schedule_name"] == "SecondSchedule"
    assert t_data["enabled"] is False

    # Edit task: detach schedule and re-enable
    rc = main(data_file_arg + [
        "task", "edit",
        "-n", "ModifiedTask",
        "-s", "none",
        "-p",
        "-N",
    ])
    assert rc == 0
    capsys.readouterr()

    rc = main(data_file_arg + ["task", "show", "-n", "ModifiedTask", "-f", "json"])
    assert rc == 0
    t_data = json.loads(capsys.readouterr().out)
    assert t_data["schedule_name"] is None
    assert t_data["enabled"] is True
    assert t_data["admin"] is False


def test_cli_logs_and_config(data_file_arg, capsys):
    # Create task and run to generate logs
    main(data_file_arg + ["task", "create", "-n", "LogTester", "-e", "terminal", "-c", "echo 'logging'"])
    main(data_file_arg + ["run", "-t", "LogTester"])
    capsys.readouterr()

    # View system logs
    rc = main(data_file_arg + ["logs", "system", "-n", "10", "-f", "json"])
    assert rc == 0
    entries = json.loads(capsys.readouterr().out)
    assert len(entries) > 0

    # View task logs (latest run)
    rc = main(data_file_arg + ["logs", "task", "-n", "LogTester", "-l"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "TASK EXECUTION REPORT: LogTester" in out
    assert "logging" in out

    # View task logs (full single-file log)
    rc = main(data_file_arg + ["logs", "task", "-n", "LogTester"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "TASK EXECUTION REPORT: LogTester" in out

    # View task logs run count summary
    rc = main(data_file_arg + ["logs", "task", "-n", "LogTester", "-c", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Recent runs for task 'LogTester'" in out

    # Config show
    rc = main(data_file_arg + ["config", "show", "-f", "json"])
    assert rc == 0
    cfg_data = json.loads(capsys.readouterr().out)
    assert "executables" in cfg_data

    # Config set
    rc = main(data_file_arg + ["config", "set", "-r", "15"])
    assert rc == 0
    capsys.readouterr()

    rc = main(data_file_arg + ["config", "show", "-f", "json"])
    cfg_data = json.loads(capsys.readouterr().out)
    assert cfg_data["log_retention_runs"] == 15

    # Config detect
    rc = main(data_file_arg + ["config", "detect"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Auto-detected Shell Executables" in out


def test_cli_daemon_once(data_file_arg, capsys):
    rc = main(data_file_arg + ["daemon", "-o", "-d"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Single pass complete" in out
