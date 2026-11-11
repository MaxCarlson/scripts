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


def test_unrepresentable_append_default_is_reported_without_starting_runner():
    parser = argparse.ArgumentParser(prog="sample")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("run")
    command.add_argument("--tag", action="append", choices=("base", "extra"), default=["base"])
    app = CliTuiApp(parser=parser)
    app.process_key(10)
    app.current_form.set_value("tag", ["extra"])

    app._start_execution()

    assert app.runner is None
    assert "Cannot build command" in app.last_message
    app.is_showing_preview = True
    lines = app.render_virtual_screen(height=24, width=80)
    assert any("Cannot build command" in line for line in lines)


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


def test_mouse_click_form_widget_focus_and_cursor():
    from cli_tui.widgets import TextWidget

    parser = argparse.ArgumentParser(prog="mytool")
    parser.add_argument("-t", "--target", default="initial_value")
    parser.add_argument("-v", "--verbose", action="store_true")

    app = CliTuiApp(parser=parser)
    app._open_form_for_command(app.root_command)
    assert app.screen_mode == TuiScreenMode.FORM

    # Render screen to populate row maps
    app.render_virtual_screen(height=24, width=80)

    # Find the row of the first widget (--target)
    target_row = None
    for r_y, (idx, widget) in app._widget_row_map.items():
        if idx == 0:
            target_row = r_y
            break
    assert target_row is not None

    # Initially not editing
    target_w = app.form_widgets[0]
    assert isinstance(target_w, TextWidget)
    assert target_w.is_editing is False

    # Click on the text field of widget 0 at character offset 3
    text_start = 2 + target_w.text_start_offset()
    consumed = app.handle_mouse_click(mx=text_start + 3, my=target_row)
    assert consumed is True
    assert app.form_cursor == 0
    assert target_w.is_editing is True
    assert target_w.cursor_pos == 3

    # Click on second widget (--verbose, boolean)
    verbose_row = None
    for r_y, (idx, widget) in app._widget_row_map.items():
        if idx == 1:
            verbose_row = r_y
            break
    assert verbose_row is not None
    assert app.form_widgets[1].value is False

    consumed = app.handle_mouse_click(mx=10, my=verbose_row)
    assert consumed is True
    assert app.form_cursor == 1
    assert app.form_widgets[1].value is True  # Toggled by click!


def test_mouse_click_preview_button():
    parser = argparse.ArgumentParser(prog="mytool")
    parser.add_argument("-t", "--target", default="test")

    app = CliTuiApp(parser=parser)
    app._open_form_for_command(app.root_command)
    app.render_virtual_screen(height=24, width=80)

    # Find top preview button hitbox
    prev_box = next((b for b in app._button_boxes if b[3] == "prev"), None)
    assert prev_box is not None
    by, bx_start, _, _ = prev_box

    assert app.is_showing_preview is False
    consumed = app.handle_mouse_click(mx=bx_start + 2, my=by)
    assert consumed is True
    assert app.is_showing_preview is True


def test_running_dual_focus_toggle_and_key_forwarding():
    import curses
    from cli_tui.state import RunningFocusMode

    class DummyRunner:
        def __init__(self):
            self.is_running = True
            self.written: list[str] = []
            self.lines = ["Worker 01 running...", "Worker 02 running..."]
            self.elapsed_seconds = 12.5
            self.exit_code = None

        def write_input(self, data: str) -> bool:
            self.written.append(data)
            return True

        def terminate(self):
            self.is_running = False

    parser = argparse.ArgumentParser(prog="mangadl run")
    app = CliTuiApp(parser=parser, executable=[sys.executable])
    app.navigation.current_screen = TuiScreenMode.RUNNING
    dummy_runner = DummyRunner()
    app.runner = dummy_runner
    app.workspace.active_pane.running_focus = RunningFocusMode.PROGRAM

    # Initial focus is PROGRAM
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM

    # 1. Ctrl+F (key 6) toggles focus to TUI
    handled = app.process_key(6)
    assert handled is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI
    assert "CLI-TUI" in app.last_message

    # 2. Ctrl+F toggles back to PROGRAM
    handled = app.process_key(6)
    assert handled is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM

    # 3. F6 (key 270) toggles focus to TUI
    handled = app.process_key(270)
    assert handled is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI

    # Toggle back to PROGRAM
    app.process_key(6)
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM

    # 4. Render virtual screen to establish layout hitbox coordinates
    app.render_virtual_screen(24, 80)
    assert hasattr(app, "_running_status_row")
    assert hasattr(app, "_running_footer_row")

    # Click on status line sets focus to TUI (returns True because focus changed)
    consumed = app.handle_mouse_click(mx=10, my=app._running_status_row)
    assert consumed is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI

    # Subsequent click on status line when already in TUI focus does NOT consume event (allows drag selection)
    consumed_again = app.handle_mouse_click(mx=10, my=app._running_status_row)
    assert consumed_again is False

    # Click inside GUI program area sets focus to PROGRAM (returns True because focus changed)
    consumed = app.handle_mouse_click(mx=10, my=app._running_status_row + 2)
    assert consumed is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM

    # Subsequent click inside GUI program area when already in PROGRAM focus does NOT consume event (allows drag selection)
    consumed_again = app.handle_mouse_click(mx=10, my=app._running_status_row + 2)
    assert consumed_again is False

    # Click on footer row sets focus to TUI (returns True because focus changed)
    consumed = app.handle_mouse_click(mx=10, my=app._running_footer_row)
    assert consumed is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI

    # Subsequent click on footer row when already in TUI focus does NOT consume event
    consumed_again = app.handle_mouse_click(mx=10, my=app._running_footer_row)
    assert consumed_again is False

    # Set back to PROGRAM focus for key forwarding verification
    app.workspace.active_pane.running_focus = RunningFocusMode.PROGRAM

    # In PROGRAM focus, 'p' should forward to child stdin, NOT open pane manager
    handled = app.process_key(ord("p"))
    assert handled is True
    assert "p" in dummy_runner.written
    assert getattr(app, "is_pane_manager_open", False) is False

    # 'q' should forward to child stdin, NOT prompt for TUI quit
    handled = app.process_key(ord("q"))
    assert handled is True
    assert "q" in dummy_runner.written
    assert app.is_confirming_quit is False

    # 'v' and 'l' should forward to child stdin
    app.process_key(ord("v"))
    assert "v" in dummy_runner.written
    app.process_key(ord("l"))
    assert "l" in dummy_runner.written

    # Up and Down arrows should forward as 'k' and 'j'
    app.process_key(curses.KEY_UP)
    assert "k" in dummy_runner.written
    app.process_key(curses.KEY_DOWN)
    assert "j" in dummy_runner.written

    # Left and Right arrows should forward as '[' and ']'
    app.process_key(curses.KEY_LEFT)
    assert "[" in dummy_runner.written
    app.process_key(curses.KEY_RIGHT)
    assert "]" in dummy_runner.written

    # Switch to TUI focus: 'p' should open Pane Manager
    app.workspace.active_pane.running_focus = RunningFocusMode.TUI
    handled = app.process_key(ord("p"))
    assert handled is True
    assert app.is_pane_manager_open is True


def test_running_screen_rendering_colors_and_completion_box():
    from cli_tui.state import RunningFocusMode

    class FinishedRunner:
        def __init__(self, exit_code: int = 0):
            self.is_running = False
            self.exit_code = exit_code
            self.lines = ["Job 1 complete", "Job 2 complete"]
            self.elapsed_seconds = 45.2

        def write_input(self, data: str) -> bool:
            return False

    parser = argparse.ArgumentParser(prog="mangadl run")
    app = CliTuiApp(parser=parser, executable=[sys.executable])
    app._open_form_for_command(app.root_command)
    app.navigation.current_screen = TuiScreenMode.RUNNING
    app.runner = FinishedRunner(exit_code=0)
    app.workspace.active_pane.running_focus = RunningFocusMode.TUI

    # Render running screen when finished
    lines = app.render_virtual_screen(24, 80)
    rendered_text = "\n".join(lines)

    # 1. Status line contains green FINISHED (Success)
    assert "FINISHED (Success)" in rendered_text
    assert "\x1b[32;1m" in rendered_text

    # 2. Status line contains Focus badge
    assert "Focus:" in rendered_text

    # 3. Prominent completion box is rendered
    assert "✔ PROCESS FINISHED SUCCESSFULLY (exit code 0)" in rendered_text
    assert "▶ Press [Enter] to conclude and return to form" in rendered_text
    assert "▶ Press [r] to re-run with same arguments" in rendered_text
    assert "▶ Press [Esc] to return to menu" in rendered_text

    # 4. Badges contain [Enter] Return to Form as the first badge
    badges = app._get_active_hotkey_badges()
    assert badges[0] == "[Enter] Return to Form"

    # 5. Pressing Enter returns to form screen
    handled = app.process_key(10)
    assert handled is True
    assert app.screen_mode == TuiScreenMode.FORM


def test_mouse_drag_selection_and_clipboard_copy(monkeypatch):
    import curses
    from cli_tui.state import RunningFocusMode

    parser = argparse.ArgumentParser(prog="mangadl run")
    app = CliTuiApp(parser=parser, executable=[sys.executable])
    app._open_form_for_command(app.root_command)
    app.navigation.current_screen = TuiScreenMode.RUNNING
    app.workspace.active_pane.running_focus = RunningFocusMode.PROGRAM

    # Render screen so _last_rendered_screen is populated
    app.render_virtual_screen(24, 80)
    assert len(app._last_rendered_screen) == 24

    copied_texts = []
    monkeypatch.setattr("cli_tui.app.copy_to_clipboard", lambda text: copied_texts.append(text) or True)

    btn1_pressed = getattr(curses, "BUTTON1_PRESSED", 2)
    btn1_released = getattr(curses, "BUTTON1_RELEASED", 1)
    report_pos = getattr(curses, "REPORT_MOUSE_POSITION", 536870912)

    # 1. Mouse down at (5, 2)
    app.handle_mouse_click(5, 2, btn1_pressed)
    assert app._mouse_is_down is True
    assert app._mouse_down_pos == (5, 2)
    assert app._mouse_drag_moved is False
    assert app._active_selection is None

    # 2. Mouse drag to (35, 4)
    app.handle_mouse_click(35, 4, report_pos)
    assert app._mouse_drag_moved is True
    assert app._active_selection == ((5, 2), (35, 4))

    # 3. Mouse release at (35, 4)
    handled = app.handle_mouse_click(35, 4, btn1_released)
    assert handled is True
    assert app._mouse_is_down is False
    assert len(copied_texts) == 1
    assert len(copied_texts[0]) > 0
    # Crucially, drag selection should NEVER change focus!
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM
    assert "Copied" in app.last_message

    # 4. Any key interaction clears active visual selection
    app.process_key(curses.KEY_UP)
    assert app._active_selection is None


def test_mouse_single_click_in_focused_area_does_not_switch_focus():
    import curses
    from cli_tui.state import RunningFocusMode

    parser = argparse.ArgumentParser(prog="mangadl run")
    app = CliTuiApp(parser=parser, executable=[sys.executable])
    app._open_form_for_command(app.root_command)
    app.navigation.current_screen = TuiScreenMode.RUNNING
    app.workspace.active_pane.running_focus = RunningFocusMode.PROGRAM

    app.render_virtual_screen(24, 80)

    btn1_clicked = getattr(curses, "BUTTON1_CLICKED", 4)

    # Click inside program area (e.g. row 8) when already in PROGRAM focus -> does nothing
    res = app.handle_mouse_click(20, 8, btn1_clicked)
    assert res is False
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM

    # Click on TUI status line (row <= _running_status_row) -> switches to TUI focus
    status_row = app._running_status_row
    res = app.handle_mouse_click(20, status_row, btn1_clicked)
    assert res is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI
    assert app.last_message == "Focus: CLI-TUI"

    # Click on TUI status line again when already in TUI focus -> does nothing
    res = app.handle_mouse_click(20, status_row, btn1_clicked)
    assert res is False
    assert app.workspace.active_pane.running_focus == RunningFocusMode.TUI

    # Click inside program area (row 8) -> switches back to PROGRAM focus
    res = app.handle_mouse_click(20, 8, btn1_clicked)
    assert res is True
    assert app.workspace.active_pane.running_focus == RunningFocusMode.PROGRAM


def test_extract_screen_text():
    parser = argparse.ArgumentParser(prog="mangadl")
    app = CliTuiApp(parser=parser)
    app._last_rendered_screen = [
        "Line 0: \x1b[32mHello\x1b[0m World",
        "Line 1: Second line of text",
        "Line 2: Third line of text",
    ]

    # Single line extraction
    text = app._extract_screen_text((8, 0), (18, 0))
    assert text == "Hello World"

    # Multi-line extraction
    text = app._extract_screen_text((8, 0), (13, 1))
    assert "Hello World" in text
    assert "Line 1" in text

    # Reversed coordinates (dragged bottom-right to top-left)
    text_rev = app._extract_screen_text((13, 1), (8, 0))
    assert text_rev == text



