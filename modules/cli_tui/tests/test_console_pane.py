import argparse
from cli_tui.app import CliTuiApp
from cli_tui.console_pane import ConsolePaneRunner


def test_console_pane_runner_executes_command():
    runner = ConsolePaneRunner(cwd=".")
    assert runner.is_running is False
    # Execute simple echo command
    runner.execute_line("echo hello_console")
    runner.wait(timeout=3.0)
    lines = runner.lines
    assert any("hello_console" in line for line in lines)


def test_pane_manager_n_key_opens_choice_dialog():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    app.process_key(ord("p"))  # Open manager
    app.process_key(ord("n"))  # Press 'n'

    # Must open choice dialog
    assert getattr(app, "is_showing_new_pane_choice", False) is True
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "New Command (Menu)" in screen
    assert "Interactive Shell Console" in screen

    # Select [2] for console pane
    app.process_key(ord("2"))
    assert app.workspace.active_pane.pane_type.value == "console"
