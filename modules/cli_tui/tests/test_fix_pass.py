import argparse
import os
import sys
import tempfile
from cli_tui.app import CliTuiApp
from cli_tui.console_pane import ConsolePaneRunner
from cli_tui.state import PaneType, PaneWorkspace, TuiScreenMode


def build_parser():
    p = argparse.ArgumentParser(prog="mytool")
    sub = p.add_subparsers(dest="subcommand")
    cmd1 = sub.add_parser("alpha")
    cmd1.add_argument("-d", "--dest", default="default_dest")
    sub.add_parser("beta")
    return p


def test_console_pane_rendered_when_active():
    app = CliTuiApp(parser=build_parser())
    # Create console pane via choice dialog
    app.process_key(ord("p"))
    app.process_key(ord("n"))
    app.process_key(ord("2"))

    assert app.workspace.active_pane.pane_type == PaneType.CONSOLE
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Must render console pane, NOT menu
    assert "Shell Console" in screen
    assert "Select an operation from" not in screen
    assert "]>" in screen


def test_console_runner_stop_and_exit_handling():
    app = CliTuiApp(parser=build_parser())
    app.process_key(ord("p"))
    app.process_key(ord("n"))
    app.process_key(ord("2"))

    # Test stop() does not raise AttributeError
    runner = app.workspace.active_pane.runner
    assert hasattr(runner, "stop")
    runner.stop()  # Should not raise

    # Type 'exit' and Enter in console
    for ch in "exit":
        app.process_key(ord(ch))
    app.process_key(10)  # Enter

    # Typing exit should close the console pane
    assert app.workspace.active_pane.pane_type != PaneType.CONSOLE


def test_pane_deletion_lifecycle_joins_runner():
    ws = PaneWorkspace()
    p2 = ws.create_pane(title="long_job", pane_type=PaneType.COMMAND)
    # Start actual long process
    from cli_tui.process_runner import ProcessRunner

    runner = ProcessRunner([sys.executable, "-c", "import time; time.sleep(5)"])
    runner.start()
    p2.runner = runner
    assert runner.is_running is True

    # Delete pane
    deleted = ws.delete_pane(1)
    assert deleted is True
    assert runner.is_running is False
    assert runner.thread is None or not runner.thread.is_alive()


def test_console_history_preserved_across_commands():
    runner = ConsolePaneRunner(cwd=".")
    runner.execute_line("echo first_output")
    runner.execute_line("echo second_output")
    runner.wait(timeout=2.0)
    lines = runner.lines
    assert any("first_output" in line for line in lines)
    assert any("second_output" in line for line in lines)


def test_cd_handling_quotes_and_variants():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub_dir = os.path.join(tmpdir, "space dir")
        os.makedirs(sub_dir, exist_ok=True)

        runner = ConsolePaneRunner(cwd=tmpdir)
        # Test quotes
        runner.execute_line(f'cd "{sub_dir}"')
        assert runner.cwd.lower() == sub_dir.lower()

        # Test cd..
        runner.execute_line("cd..")
        assert runner.cwd.lower() == tmpdir.lower()


def test_pane_manager_previews_form_and_menu():
    app = CliTuiApp(parser=build_parser())
    # Pane 0 is at MENU
    app.process_key(ord("p"))
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Menu preview must show subcommands
    assert "alpha" in screen or "PREVIEW" in screen
    app.process_key(27)  # Close manager

    # Enter FORM for alpha
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    app.process_key(ord("p"))
    screen_form = "\n".join(app.render_virtual_screen(height=24, width=80))
    # FORM preview must show form arguments
    assert "dest" in screen_form


def test_workspace_terminate_all():
    ws = PaneWorkspace()
    from cli_tui.process_runner import ProcessRunner

    r1 = ProcessRunner([sys.executable, "-c", "import time; time.sleep(5)"])
    r1.start()
    ws.panes[0].runner = r1

    ws.terminate_all()
    assert r1.is_running is False
