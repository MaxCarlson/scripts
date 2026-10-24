from __future__ import annotations

import argparse
import curses
import sys

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
    assert app.is_confirming_layout_save is True
    assert app.is_terminated is False
    app.process_key(ord("n"))
    assert app.is_terminated is True


def test_universal_key_Q_force_quit():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser)

    # Press 'Q' immediately terminates without confirmation
    app.process_key(ord("Q"))
    assert app.is_confirming_quit is False
    assert app.is_terminated is True


def test_form_footer_layout():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser, executable=["python", "-m", "sample"])
    app.process_key(10)  # Enter 'build' form
    assert app.screen_mode == TuiScreenMode.FORM

    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    # Must separate working directory, runner, and tool command
    assert "Working Dir:" in screen
    assert "Runner:" in screen
    assert "python -m" in screen
    assert "Command:" in screen
    assert "build" in screen


def test_preview_cli_dialog():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser, executable=["python", "-m", "sample"])
    app.process_key(10)  # Enter 'build' form

    # Move down to [ Preview CLI ]
    # form cursor: widget 0 (-t), widget 1 (-v), button 0 ([ Run ]), button 1 ([ Preview ])
    for _ in range(3):
        app.process_key(curses.KEY_DOWN)

    # Press Enter on [ Preview CLI ]
    app.process_key(10)
    assert getattr(app, "is_showing_preview", False) is True

    preview_screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "CLI Command Preview" in preview_screen
    assert "Working Directory:" in preview_screen
    assert "Runner:" in preview_screen
    assert "Command:" in preview_screen

    # Dismiss with Esc or Enter
    app.process_key(27)  # Esc
    assert getattr(app, "is_showing_preview", False) is False


def test_addstr_ansi_parsing(monkeypatch):
    from unittest.mock import MagicMock
    from cli_tui.app import addstr_ansi

    stdscr = MagicMock()
    # Mock curses color support
    monkeypatch.setattr(curses, "has_colors", lambda: True)
    monkeypatch.setattr(curses, "color_pair", lambda n: n * 100)

    # 1. Plain text
    addstr_ansi(stdscr, y=0, x=0, line="Hello World", max_x=80)
    stdscr.addstr.assert_called_once_with(0, 0, "Hello World", curses.A_NORMAL)
    stdscr.addstr.reset_mock()

    # 2. Colored text with Cyan (code 36 -> pair 1 -> 100)
    addstr_ansi(stdscr, y=1, x=2, line="\033[36mCyan Text\033[0m", max_x=80)
    stdscr.addstr.assert_called_once_with(1, 2, "Cyan Text", curses.A_NORMAL | 100)
    stdscr.addstr.reset_mock()

    # 3. Bold Green text (code 1;32 -> bold + pair 2 -> 200)
    addstr_ansi(stdscr, y=2, x=0, line="\033[1;32mBold Green\033[0m", max_x=80)
    stdscr.addstr.assert_called_once_with(2, 0, "Bold Green", curses.A_BOLD | 200)


def test_failed_command_esc_and_enter_return_to_form():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser)
    app.process_key(10)  # Enter 'build' form
    app.current_form.set_value("target", "my_target")

    class FailedRunner:
        is_running = False
        exit_code = 2
        elapsed_seconds = 0.5
        lines = ["error: argument --quality invalid"]

    app.runner = FailedRunner()
    app.navigation.current_screen = TuiScreenMode.RUNNING

    # Esc returns to form with arguments preserved
    app.process_key(27)
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_form.get_value("target") == "my_target"

    # Re-enter running screen, Enter also returns to form
    app.navigation.current_screen = TuiScreenMode.RUNNING
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_form.get_value("target") == "my_target"


def test_form_scrolling_keeps_focused_item_visible():
    p = argparse.ArgumentParser(prog="many_args")
    for i in range(20):
        p.add_argument(f"--arg{i}", default=f"val{i}")
    app = CliTuiApp(parser=p)
    app._open_form_for_command(app.root_command)
    # Cursor to bottom button [ Run Command ] (index 20)
    app.form_cursor = 20
    screen = app.render_virtual_screen(height=15, width=80)
    screen_text = "\n".join(screen)
    assert "▶ [ Run Command ]" in screen_text


def test_form_run_button_and_ctrl_r_shortcut():
    parser = build_sample_parser()
    app = CliTuiApp(parser=parser, executable=[sys.executable, "-c", "pass"])
    app.process_key(10)  # Enter 'build' form
    assert app.screen_mode == TuiScreenMode.FORM

    # 1. Top button bar is visible near the top of the screen
    screen = app.render_virtual_screen(height=24, width=80)
    screen_top_text = "\n".join(screen[:6])
    assert "[ Run Command ]" in screen_top_text
    assert "[Ctrl+R] Run" in "\n".join(screen[-3:])

    # 2. Left and Right arrows cycle across buttons
    app.form_cursor = len(app.form_widgets)  # on [ Run Command ]
    assert "[Enter] Run Command" in "\n".join(
        app.render_virtual_screen(height=24, width=80)[-3:]
    )

    app.process_key(curses.KEY_RIGHT)
    assert app.form_cursor == len(app.form_widgets) + 1  # on [ Preview CLI ]
    app.process_key(curses.KEY_LEFT)
    assert app.form_cursor == len(app.form_widgets)  # back to [ Run Command ]

    # 3. Ctrl+R (18) executes command immediately from anywhere
    app.form_cursor = 0  # on first widget
    app.process_key(18)  # Ctrl+R
    assert app.screen_mode == TuiScreenMode.RUNNING
    assert app.runner is not None


def test_form_argument_inspector_displays_help_and_details():
    parser = argparse.ArgumentParser(prog="mytool")
    parser.add_argument(
        "-f", "--format",
        choices=("auto", "webp", "jpeg"),
        default="auto",
        help="Target encoding format for images",
    )
    app = CliTuiApp(parser=parser)
    app._open_form_for_command(app.root_command)
    assert app.screen_mode == TuiScreenMode.FORM

    # Cursor on first widget (--format)
    app.form_cursor = 0
    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "Option: -f, --format" in screen
    assert "Help:    Target encoding format for images" in screen
    assert "Choices: auto, webp, jpeg" in screen
    assert "Default: auto" in screen

    # Move cursor to [ Run Command ] button
    app.form_cursor = len(app.form_widgets)
    screen_btn = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "Action: Run Command" in screen_btn
    assert "Execute this command in the background" in screen_btn

