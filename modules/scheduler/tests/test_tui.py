"""
Unit tests for scheduler TUI components and workflows with mock screen.
"""
from unittest.mock import MagicMock, patch
import pytest
from scheduler.models import Schedule, Task
from scheduler.service import SchedulerService
from scheduler.storage import StorageManager
from scheduler.tui import SchedulerTUI


@pytest.fixture(autouse=True)
def mock_curses_calls():
    with patch("curses.curs_set"), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch("curses.initscr"):
        yield


@pytest.fixture
def mock_curses_screen():
    screen = MagicMock()
    screen.getmaxyx.return_value = (24, 80)
    screen.getch.return_value = ord("q")
    return screen


@pytest.fixture
def tui_instance(tmp_path, mock_curses_screen):
    data_file = tmp_path / "scheduler_data.json"
    storage = StorageManager(data_file=data_file)
    service = SchedulerService(storage=storage)
    return SchedulerTUI(service, mock_curses_screen)


def test_tui_select_menu_quit(tui_instance, mock_curses_screen):
    mock_curses_screen.getch.return_value = ord("q")
    res = tui_instance.select_menu("Test Menu", ["Option 1", "Option 2"])
    assert res == -1


def test_tui_select_menu_enter(tui_instance, mock_curses_screen):
    mock_curses_screen.getch.return_value = 10
    res = tui_instance.select_menu("Test Menu", ["Option 1", "Option 2"])
    assert res == 0


def test_tui_warning_confirm(tui_instance, mock_curses_screen):
    mock_curses_screen.getch.return_value = 10
    res = tui_instance.show_warning_confirm("Warning", ["Orphaned tasks: task1"])
    assert res is False


def test_tui_run_exits_on_quit(tui_instance, mock_curses_screen):
    mock_curses_screen.getch.return_value = ord("q")
    rc = tui_instance.run()
    assert rc == 0


def test_tui_workflow_create_schedule(tui_instance):
    with patch.object(tui_instance, "prompt_text", side_effect=["MyTuiSchedule", "03:15"]), \
         patch.object(tui_instance, "select_menu", side_effect=[0, 0]), \
         patch.object(tui_instance, "show_message") as mock_msg:
        tui_instance.workflow_create_schedule()
        mock_msg.assert_called_once()
        sched = tui_instance.storage.get_schedule("MyTuiSchedule")
        assert sched is not None
        assert sched.timing.at_time == "03:15"
        assert sched.catch_up is True


def test_tui_workflow_create_task(tui_instance):
    with patch.object(tui_instance, "prompt_text", side_effect=["MyTuiTask", "echo hello"]), \
         patch.object(tui_instance, "select_menu", side_effect=[0, 0, 1, 0]), \
         patch.object(tui_instance, "show_message") as mock_msg:
        tui_instance.workflow_create_task()
        mock_msg.assert_called_once()
        task = tui_instance.storage.get_task("MyTuiTask")
        assert task is not None
        assert task.environment == "terminal"
        assert task.admin is False
        assert task.code == "echo hello"


def test_tui_workflow_edit_task_full(tui_instance):
    # Setup initial schedule and task
    sched = Schedule(name="SyncSchedule")
    tui_instance.storage.save_schedule(sched)
    t = Task(name="InitialTask", schedule_name=None, environment="terminal", admin=False, code="echo 1")
    tui_instance.storage.save_task(t)

    # In workflow_edit_task:
    # 1. select task 0 ("InitialTask")
    # 2. In _handle_single_task:
    #    - Action 0: Rename to "RenamedTask"
    #    - Action 1: Change Environment to pwsh (env_idx 1)
    #    - Action 2: Toggle Admin
    #    - Action 4: Edit Script Inline to "Get-Date"
    #    - Action 5: Link Schedule to SyncSchedule (sc_idx 1)
    #    - Action -1: Exit _handle_single_task
    # 3. select_menu in workflow_edit_task returns -1 to exit
    with patch.object(tui_instance, "select_menu", side_effect=[0, 0, 1, 1, 2, 4, 5, 1, -1, -1]), \
         patch.object(tui_instance, "prompt_text", side_effect=["RenamedTask", "Get-Date"]), \
         patch.object(tui_instance, "show_message"):
        tui_instance.workflow_edit_task()

    # Verify task updated
    assert tui_instance.storage.get_task("InitialTask") is None
    updated = tui_instance.storage.get_task("RenamedTask")
    assert updated is not None
    assert updated.environment == "pwsh"
    assert updated.admin is True
    assert updated.code == "Get-Date"
    assert updated.schedule_name == "SyncSchedule"


def test_tui_workflow_manage_schedules_delete_orphaned_warning(tui_instance):
    sched = Schedule(name="DelSched")
    tui_instance.storage.save_schedule(sched)
    t = Task(name="AttachedTask", schedule_name="DelSched", environment="terminal", code="ls")
    tui_instance.storage.save_task(t)

    # 1. select schedule 0, 2. select delete (option 5), 3. confirm delete -> True
    with patch.object(tui_instance, "select_menu", side_effect=[0, 5]), \
         patch.object(tui_instance, "show_warning_confirm", return_value=True) as mock_warn, \
         patch.object(tui_instance, "show_message"):
        tui_instance.workflow_manage_schedules()
        mock_warn.assert_called_once()
        warning_lines = mock_warn.call_args[0][1]
        assert any("AttachedTask" in line for line in warning_lines)
        assert tui_instance.storage.get_schedule("DelSched") is None
        task_after = tui_instance.storage.get_task("AttachedTask")
        assert task_after.schedule_name is None


def test_tui_workflow_view_logs(tui_instance):
    # Log a system event
    tui_instance.service.central_logger.log("SYSTEM_INFO", "Test log entry")

    # Run a task to create a task log file
    task = Task(name="RunLogTask", environment="terminal", code="echo 'log run'")
    tui_instance.storage.save_task(task)
    tui_instance.service.execute_task("RunLogTask")

    # In workflow_view_logs:
    # 1. Select option 0: Central System Log
    # 2. Select option 1: Task Log for RunLogTask
    # 3. Select -1: Exit
    with patch.object(tui_instance, "select_menu", side_effect=[0, 1, -1]), \
         patch.object(tui_instance, "_view_scrollable_text") as mock_view:
        tui_instance.workflow_view_logs()
        assert mock_view.call_count == 2
        # First call was system log
        assert "Central System Event Log" in mock_view.call_args_list[0][0][0]
        # Second call was task log
        assert "Task Log: RunLogTask.log" in mock_view.call_args_list[1][0][0]
