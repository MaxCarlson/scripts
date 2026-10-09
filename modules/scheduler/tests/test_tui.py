"""
Unit tests for scheduler TUI components and workflows with mock screen.
"""
from unittest.mock import MagicMock, patch
import pytest
from scheduler.models import Schedule, Task
from scheduler.readiness import SetupState
from scheduler.service import SchedulerService
from scheduler.storage import StorageManager
from scheduler.tui import DetailRow, GoHome, SchedulerTUI


@pytest.fixture(autouse=True)
def mock_curses_calls():
    with patch("curses.curs_set"), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
        patch("curses.initscr"), \
         patch(
             "scheduler.tui.get_setup_state",
             return_value=SetupState(True, "Windows", "Windows scheduler setup is complete.", None),
         ):
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

    # System events and standalone tasks are distinct top-level groups.
    with patch.object(tui_instance, "select_menu", side_effect=[0, 1, 0, -1, -1]), \
         patch.object(tui_instance, "_view_task_details") as mock_task, \
         patch.object(tui_instance, "_view_scrollable_text") as mock_view:
        tui_instance.workflow_view_logs()
        assert mock_view.call_count == 1
        assert "Central System Event Log" in mock_view.call_args_list[0][0][0]
        assert mock_task.call_args.args[0].name == "RunLogTask"


def test_tui_schedule_task_run_hierarchy(tui_instance):
    schedule = Schedule(name="Nightly")
    task = Task(name="Backup", schedule_name="Nightly")
    tui_instance.storage.save_schedule(schedule)
    tui_instance.storage.save_task(task)
    with patch.object(tui_instance, "_select_details", side_effect=[("task", task), ("run", "run-id"), None, None]) as select, \
         patch.object(tui_instance, "_view_run") as view_run:
        tui_instance._view_schedule_details(schedule)
    assert "Schedule: Nightly" in select.call_args_list[0].args[0]
    assert "Task: Backup" in select.call_args_list[1].args[0]
    view_run.assert_called_once_with("run-id")


def test_tui_details_navigation_and_home(tui_instance, mock_curses_screen):
    rows = [DetailRow("Summary"), DetailRow("Run one", ("run", "one")), DetailRow("Run two", ("run", "two"))]
    mock_curses_screen.getch.side_effect = [10]
    assert tui_instance._select_details("Details", rows) == ("run", "one")
    mock_curses_screen.getch.side_effect = [ord("j"), 10]
    assert tui_instance._select_details("Details", rows) == ("run", "two")
    mock_curses_screen.getch.side_effect = [27]
    assert tui_instance._select_details("Details", rows) is None
    mock_curses_screen.getch.side_effect = [ord("H")]
    with pytest.raises(GoHome):
        tui_instance._select_details("Details", rows)


def test_tui_config_exposes_windows_runner_workflow(tui_instance):
    with patch("scheduler.tui.windows_task.get_runner_status", return_value={"installed": False}), \
         patch.object(tui_instance, "select_menu", side_effect=[6, -1, -1]):
        tui_instance.workflow_config()


def test_tui_windows_runner_install_uses_module_data_file(tui_instance):
    with patch("scheduler.tui.windows_task.get_runner_status", return_value={"installed": False}), \
         patch("scheduler.tui.windows_task.install_runner", return_value="installed") as install, \
         patch.object(tui_instance, "select_menu", side_effect=[1, -1]), \
         patch.object(tui_instance, "show_message") as show_message:
        tui_instance.workflow_windows_runner()

    install.assert_called_once_with(tui_instance.storage.data_file)
    assert show_message.call_args.args[0] == "Windows Runner Installed"


def test_tui_setup_gate_shows_warning_and_only_setup_option(tui_instance):
    missing = SetupState(False, "Windows", "The Windows scheduler runner has not been installed.", "scheduler setup windows")
    ready = SetupState(True, "Windows", "Windows scheduler setup is complete.", None)
    with patch("scheduler.tui.get_setup_state", side_effect=[missing, ready]), \
         patch.object(tui_instance, "select_menu", side_effect=[0, -1]) as select_menu, \
         patch.object(tui_instance, "workflow_windows_runner") as setup:
        assert tui_instance.run() == 0

    setup.assert_called_once_with()
    first_menu = select_menu.call_args_list[0]
    assert first_menu.args[0] == "Setup Required"
    assert first_menu.args[1] == ["1. Set up Windows scheduler runner"]
    assert "scheduler setup windows" in " ".join(first_menu.kwargs["warning_lines"])


def test_tui_warning_menu_renders_prominent_warning_in_red(tui_instance, mock_curses_screen):
    mock_curses_screen.getch.return_value = 10
    result = tui_instance.select_menu("Setup Required", ["Set up"], warning_lines=["Run scheduler setup windows"])

    assert result == 0
    rendered = [call.args[2] for call in mock_curses_screen.addstr.call_args_list if len(call.args) >= 3]
    assert "!!! SCHEDULER SETUP REQUIRED !!!" in rendered
    assert "Run scheduler setup windows" in rendered


def test_tui_windows_runner_start_requires_warning_confirmation(tui_instance):
    with patch("scheduler.tui.windows_task.get_runner_status", return_value={"installed": True}), \
         patch("scheduler.tui.windows_task.start_runner", return_value="started") as start, \
         patch.object(tui_instance, "select_menu", side_effect=[2, -1]), \
         patch.object(tui_instance, "show_warning_confirm", return_value=False) as confirm:
        tui_instance.workflow_windows_runner()

    confirm.assert_called_once()
    start.assert_not_called()


def test_tui_windows_runner_remove_requires_confirmation(tui_instance):
    with patch("scheduler.tui.windows_task.get_runner_status", return_value={"installed": True}), \
         patch("scheduler.tui.windows_task.remove_runner", return_value="removed") as remove, \
         patch.object(tui_instance, "select_menu", side_effect=[3, -1]), \
         patch.object(tui_instance, "show_warning_confirm", return_value=True) as confirm:
        tui_instance.workflow_windows_runner()

    confirm.assert_called_once()
    remove.assert_called_once_with()


def test_tui_selected_task_can_queue_delayed_runner_test(tui_instance):
    task = Task(name="Winget Update", admin=True, environment="pwsh", code="winget upgrade --all")
    tui_instance.storage.save_task(task)

    with patch.object(tui_instance, "select_menu", side_effect=[5, 0, 0, 1, 7]), \
         patch.object(tui_instance.service, "queue_runner_test", return_value="13:00:10") as queue_test, \
         patch.object(tui_instance.service, "execute_task") as execute_task, \
         patch.object(tui_instance, "show_message") as show_message:
        tui_instance.run()

    queue_test.assert_called_once_with("Winget Update", delay_seconds=10)
    execute_task.assert_not_called()
    assert show_message.call_args.args[0] == "Runner Test Queued"
    assert "visible console window" in " ".join(show_message.call_args.args[1])


def test_tui_non_admin_task_has_no_elevated_runner_option(tui_instance):
    task = Task(name="Scoop Update", admin=False, environment="pwsh", code="scoop update")
    tui_instance.storage.save_task(task)

    with patch.object(tui_instance, "select_menu", side_effect=[5, 0, 0, 0, 7]) as select_menu, \
         patch.object(tui_instance.service, "execute_task") as execute_task:
        tui_instance.run()

    run_menu = next(call for call in select_menu.call_args_list if call.args[0] == "Run Task: Scoop Update")
    assert run_menu.args[1] == ["Run immediately (manual)"]
    execute_task.assert_called_once_with("Scoop Update")


def test_tui_delayed_runner_test_reports_inactive_daemon(tui_instance):
    task = Task(name="Winget Update", admin=True, environment="pwsh", code="winget upgrade --all")
    tui_instance.storage.save_task(task)

    with patch.object(tui_instance, "select_menu", side_effect=[5, 0, 0, 1, 7]), \
         patch.object(tui_instance.service, "queue_runner_test", side_effect=RuntimeError("runner is not running")), \
         patch.object(tui_instance, "show_message") as show_message:
        tui_instance.run()

    assert show_message.call_args.args[0] == "Runner Test Not Queued"
    assert "runner is not running" in show_message.call_args.args[1][0]
