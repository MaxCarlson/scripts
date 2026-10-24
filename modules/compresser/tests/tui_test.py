from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from compresser.cli import build_parser, main
from compresser.tui import build_tui_app, launch_tui


def test_build_tui_app_structure():
    """Verify build_tui_app constructs an introspected dashboard with recursion filtered out."""
    app = build_tui_app()
    assert app.title == "Compresser Interactive Dashboard"
    subcommands = app.root_command.subcommands
    # Must include standard image compression operations
    expected_ops = ["inventory", "plan", "estimate", "analyze", "compare", "preview", "apply", "recover"]
    for op in expected_ops:
        assert op in subcommands, f"Expected {op} in TUI subcommands"
    # Must NOT include tui to prevent infinite recursion
    assert "tui" not in subcommands


def test_compresser_parser_tui_flags():
    """Verify that build_parser includes the -T/--tui option and tui subcommand."""
    parser = build_parser()
    # Check -T / --tui option on root parser
    parsed_root = parser.parse_args(["-T"])
    assert parsed_root.tui is True

    # Check tui subcommand
    parsed_sub = parser.parse_args(["tui", "-v"])
    assert parsed_sub.operation == "tui"
    assert parsed_sub.verbose == 1


def test_launch_tui_help(capsys):
    """Verify launch_tui with --help prints help and exits with 0 without launching curses."""
    ret = launch_tui(["--help"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "usage: compresser tui" in captured.out


def test_main_routes_to_tui_before_normalization():
    """Verify main routes tui, -T, and --tui without calling image-only argument normalization."""
    with patch("compresser.tui.launch_tui", return_value=42) as mock_launch:
        assert main(["tui"]) == 42
        mock_launch.assert_called_with([])

    with patch("compresser.tui.launch_tui", return_value=42) as mock_launch:
        assert main(["-T"]) == 42

    with patch("compresser.tui.launch_tui", return_value=42) as mock_launch:
        assert main(["--tui"]) == 42


def test_post_run_preview_action():
    """Verify the [v] View Previews post-run action is configured for the preview operation."""
    app = build_tui_app()
    assert len(app.post_run_actions) == 1
    action = app.post_run_actions[0]
    assert action.label == "[v] View Previews"

    # Mock app state where navigation path is ['preview'] and runner finished with 0
    mock_app = MagicMock()
    mock_app.navigation.path = ["preview"]
    mock_app.runner.exit_code = 0
    assert action.predicate(mock_app) is True

    # When runner failed, predicate should be False
    mock_app.runner.exit_code = 1
    assert action.predicate(mock_app) is False

    # When operation is not preview, predicate should be False
    mock_app.navigation.path = ["inventory"]
    mock_app.runner.exit_code = 0
    assert action.predicate(mock_app) is False


def test_tui_virtual_screen_navigation():
    """Verify that keyboard navigation from menu to operation form functions correctly."""
    app = build_tui_app()
    lines = app.render_virtual_screen(height=24, width=80)
    assert len(lines) == 24

    # Menu contains expected operation titles
    rendered = "".join(lines)
    assert "inventory" in rendered
    assert "plan" in rendered

    # Move down to 'plan' and enter form
    app.process_key(ord("j"))
    app.process_key(10)  # Enter

    assert app.navigation.path == ["plan"]
    widget_labels = [w.label for w in app.form_widgets]
    assert "--input (-i)" in widget_labels
    assert "--format (-f)" in widget_labels
    assert "--mode (-m)" in widget_labels
