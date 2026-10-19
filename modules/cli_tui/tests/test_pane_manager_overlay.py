import argparse
from cli_tui.app import CliTuiApp
from cli_tui.state import PaneType


def test_pane_manager_overlay_rendering_and_actions():
    p = argparse.ArgumentParser(prog="tool")
    app = CliTuiApp(parser=p)
    app.workspace.create_pane(title="compress inventory", pane_type=PaneType.COMMAND)
    app.workspace.panes[0].viewport.get_visible_lines = lambda lines, **kw: [
        "Sample Summary Table",
        "Files: 100",
    ]

    # Press 'p' to open Pane Manager
    app.process_key(ord("p"))
    assert app.is_pane_manager_open is True

    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Must show dual column divider and titles
    assert "MangaDL Pane Manager" in screen or "Pane Manager" in screen
    assert "PANES" in screen
    assert "PREVIEW" in screen
    assert "[d] Delete" in screen

    # Close with Esc
    app.process_key(27)  # Esc
    assert app.is_pane_manager_open is False

    # Reopen and delete pane
    app.process_key(ord("p"))
    app.process_key(ord("d"))
    # One pane remains
    assert len(app.workspace.panes) == 1
