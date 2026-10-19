import argparse
import curses
import sys
from cli_tui.app import CliTuiApp
from cli_tui.state import TuiScreenMode


def build_test_parser():
    p = argparse.ArgumentParser(prog="tool")
    sub = p.add_subparsers(dest="subcommand")
    cmd1 = sub.add_parser("inventory")
    cmd1.add_argument("-d", "--destination", default="")
    cmd2 = sub.add_parser("plan")
    cmd2.add_argument("-d", "--destination", default="")
    return p


def test_branching_preserves_run_and_inherits_args():
    app = CliTuiApp(
        parser=build_test_parser(),
        executable=[sys.executable, "-c", "import time; time.sleep(0.5)"],
    )
    # Enter inventory form
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_form is not None
    app.current_form.set_value("destination", "hent1")

    # Move cursor to [ Run Command ] (widget 0 -> button 0)
    app.process_key(curses.KEY_DOWN if hasattr(curses, "KEY_DOWN") else 258)
    # Start run (mocked)
    app.process_key(10)  # Run
    assert app.screen_mode == TuiScreenMode.RUNNING

    # Press 's' (or Shift+Esc trigger) to branch
    app.process_key(ord("s"))
    assert len(app.workspace.panes) == 2
    # Old pane 0 is preserved in RUNNING mode with its output intact
    assert app.workspace.panes[0].screen_mode == TuiScreenMode.RUNNING
    # Active pane 1 is at MENU mode
    assert app.workspace.active_index == 1
    assert app.screen_mode == TuiScreenMode.MENU

    # Select 'plan' command in pane 1
    # Move down to 'plan' and enter
    app.process_key(curses.KEY_DOWN if hasattr(curses, "KEY_DOWN") else 258)
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    # Argument 'destination' must be pre-filled with 'hent1'
    assert app.current_form.get_value("destination") == "hent1"


def test_finished_pane_preservation_and_rerun():
    app = CliTuiApp(
        parser=build_test_parser(),
        executable=[sys.executable, "-c", "pass"],
    )
    app.process_key(10)  # Enter inventory form
    app.current_form.set_value("destination", "hent1")
    app.process_key(curses.KEY_DOWN if hasattr(curses, "KEY_DOWN") else 258)
    app.process_key(10)  # Run
    assert app.screen_mode == TuiScreenMode.RUNNING

    # Wait for runner to finish
    app.runner.wait(timeout=2.0)
    assert app.runner.is_running is False

    # Branch to new pane
    app.branch_to_new_command_pane()
    assert len(app.workspace.panes) == 2
    assert app.workspace.active_index == 1

    # Switch back to finished pane 0
    app.cycle_pane_prev()
    assert app.workspace.active_index == 0
    assert app.screen_mode == TuiScreenMode.RUNNING

    # Esc in finished pane should return to form with args preserved
    app.process_key(27)
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_form is not None
    assert app.current_form.get_value("destination") == "hent1"
