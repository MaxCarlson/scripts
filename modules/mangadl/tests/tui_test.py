from __future__ import annotations

from cli_tui.state import TuiScreenMode
from mangadl.tui import build_tui_app


def test_build_tui_app_structure_and_categories():
    app = build_tui_app()

    assert app.title == "MangaDL Interactive Dashboard"
    assert app.screen_mode == TuiScreenMode.MENU

    # Top-level commands should include key MangaDL operations
    root = app.root_command
    assert "run" in root.subcommands
    assert "compress" in root.subcommands
    assert "covers" in root.subcommands
    assert "archive" in root.subcommands

    # Nested compress operations
    compress_cmd = root.subcommands["compress"]
    assert "estimate" in compress_cmd.subcommands
    assert "preview" in compress_cmd.subcommands
    assert "apply" in compress_cmd.subcommands
    assert "inventory" in compress_cmd.subcommands


def test_tui_navigate_to_compress_estimate():
    app = build_tui_app()

    # Move to compress and select
    compress_idx = list(app.root_command.subcommands.keys()).index("compress")
    app.menu_cursor = compress_idx
    app.process_key(10)  # Enter

    assert app.screen_mode == TuiScreenMode.MENU
    assert app.navigation.path == ["compress"]

    # Inside compress, select estimate
    estimate_idx = list(app.current_command.subcommands.keys()).index("estimate")
    app.menu_cursor = estimate_idx
    app.process_key(10)  # Enter

    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_command.name == "estimate"

    # Verify form has destination, format, quality, etc.
    dests = [w.arg.dest for w in app.form_widgets]
    assert "destination" in dests
    assert "format" in dests
    assert "quality" in dests
