from __future__ import annotations

import argparse

from cli_tui.app import CliTuiApp
from cli_tui.state import TuiScreenMode


def build_sample_parser():
    parser = argparse.ArgumentParser(prog="sample")
    subparsers = parser.add_subparsers(dest="subcommand")

    build = subparsers.add_parser("build", help="Build project")
    build.add_argument("-t", "--target", default="all", help="Build target")
    build.add_argument("-v", "--verbose", action="store_true")

    test = subparsers.add_parser("test", help="Run tests")
    test.add_argument("-s", "--suite", default="unit")

    return parser


def test_app_initialization_and_menu_navigation():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser, title="Sample Tool")

    assert app.screen_mode == TuiScreenMode.MENU
    lines = app.render_virtual_screen(height=20, width=60)
    assert any("Sample Tool" in line for line in lines)
    assert any("build" in line for line in lines)
    assert any("test" in line for line in lines)

    # Press Enter on first choice ("build")
    app.process_key(10)  # Enter
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_command.name == "build"

    form_lines = app.render_virtual_screen(height=20, width=60)
    assert any("--target" in line for line in form_lines)
    assert any("[ Run Command ]" in line for line in form_lines)

    # Press Esc to go back
    app.process_key(27)  # Esc
    assert app.screen_mode == TuiScreenMode.MENU


def test_universal_key_q_confirmation_and_cancellation():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser)

    # Press 'q' from menu triggers confirmation
    app.process_key(ord("q"))
    assert app.is_confirming_quit is True
    lines = app.render_virtual_screen(height=20, width=60)
    assert any("Are you sure you want to exit?" in line for line in lines)

    # Press 'n' cancels confirmation
    app.process_key(ord("n"))
    assert app.is_confirming_quit is False
    assert app.is_terminated is False

    # Press 'q' then 'y' confirms quit
    app.process_key(ord("q"))
    assert app.is_confirming_quit is True
    app.process_key(ord("y"))
    assert app.is_terminated is True


def test_universal_key_Q_force_quit():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser)

    # Press 'Q' immediately terminates without confirmation
    app.process_key(ord("Q"))
    assert app.is_confirming_quit is False
    assert app.is_terminated is True
