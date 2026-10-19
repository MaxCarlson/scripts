import argparse
from cli_tui.app import CliTuiApp
from cli_tui.state import PaneType


def test_tab_strip_hidden_when_single_pane():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Should not display tab strip indicators when only 1 pane exists
    assert "▶ [1:" not in screen


def test_tab_strip_shown_and_cycles_when_multiple_panes():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    # Add second pane
    app.workspace.create_pane(title="compress plan", pane_type=PaneType.COMMAND)
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))

    # Top lines must render tabs
    tab_line = [line for line in screen.splitlines() if "1:" in line][0]
    assert "2: compress plan" in tab_line
    assert "▶" in tab_line

    # Cycle to previous pane with '['
    app.process_key(ord("["))
    assert app.workspace.active_index == 0

    # Cycle to next pane with ']'
    app.process_key(ord("]"))
    assert app.workspace.active_index == 1
