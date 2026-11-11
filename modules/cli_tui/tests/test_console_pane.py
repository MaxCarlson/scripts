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
    pane = app.workspace.active_pane
    assert pane.pane_type.value == "console"
    assert pane.title == pane.runner.shell_name


def test_detect_shell_returns_valid_tuple():
    from cli_tui.console_pane import detect_shell

    shell_exe, shell_name, shell_prefix = detect_shell()
    assert isinstance(shell_exe, str) and len(shell_exe) > 0
    assert shell_name.lower() in ("pwsh", "powershell", "cmd", "bash", "zsh", "sh")
    assert isinstance(shell_prefix, list) and len(shell_prefix) >= 2


def test_console_pane_dual_focus_and_key_routing():
    from cli_tui.state import RunningFocusMode

    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    app.process_key(ord("p"))
    app.process_key(ord("n"))
    app.process_key(ord("2"))

    pane = app.workspace.active_pane
    runner = pane.runner
    assert pane.running_focus == RunningFocusMode.PROGRAM

    # Verify initial render has shell focus badge
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert f"Focus: {runner.shell_name.upper()}" in screen
    assert "[Ctrl+F] Toggle Focus" in screen

    # In PROGRAM focus, typing goes to runner
    app.process_key(ord("e"))
    app.process_key(ord("c"))
    app.process_key(ord("h"))
    app.process_key(ord("o"))
    assert runner.input_buffer == "echo"

    # Esc with non-empty buffer clears it
    app.process_key(27)
    assert runner.input_buffer == ""

    # Esc with empty buffer toggles to TUI focus
    app.process_key(27)
    assert pane.running_focus == RunningFocusMode.TUI
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "Focus: CLI-TUI" in screen

    # In TUI focus, 'p' opens Pane Manager overlay
    app.process_key(ord("p"))
    assert app.is_pane_manager_open is True
    # Esc closes Pane Manager
    app.process_key(27)
    assert app.is_pane_manager_open is False

    # In TUI focus, Enter switches focus back to PROGRAM
    app.process_key(10)
    assert pane.running_focus == RunningFocusMode.PROGRAM

    # Ctrl+F (key 6) toggles focus back to TUI
    app.process_key(6)
    assert pane.running_focus == RunningFocusMode.TUI
    # Ctrl+F again toggles back to PROGRAM
    app.process_key(6)
    assert pane.running_focus == RunningFocusMode.PROGRAM

