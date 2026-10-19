import argparse
from cli_tui.app import CliTuiApp, format_hotkey_footer
from cli_tui.state import PaneType, TuiScreenMode


def build_test_parser():
    p = argparse.ArgumentParser(prog="sample")
    sub = p.add_subparsers(dest="cmd")
    c1 = sub.add_parser("inventory")
    c1.add_argument("-d", "--dest", default="somedir")
    sub.add_parser("plan")
    return p


def test_format_hotkey_footer_wrapping():
    badges = [
        "[q] Quit",
        "[Q] Force Quit",
        "[Esc] Back",
        "[p] Panes",
        "[s] Branch",
        "[r] Re-run",
        "[↑/↓] Scroll",
        "[Enter] Return",
    ]

    # Wide screen: fits in 1 row
    wide_lines = format_hotkey_footer(badges, width=140)
    assert len(wide_lines) == 1
    assert wide_lines[0].startswith("└─ ")
    assert wide_lines[0].endswith("┘")
    assert len(wide_lines[0]) == 140

    # Medium screen: wraps into 2 rows
    med_lines = format_hotkey_footer(badges, width=70)
    assert len(med_lines) == 2
    assert med_lines[0].startswith("├─ ")
    assert med_lines[0].endswith("┤")
    assert med_lines[1].startswith("└─ ")
    assert med_lines[1].endswith("┘")
    assert len(med_lines[0]) == 70
    assert len(med_lines[1]) == 70

    # Narrow screen: wraps into 3 rows
    narrow_lines = format_hotkey_footer(badges, width=40)
    assert len(narrow_lines) >= 3
    for line in narrow_lines[:-1]:
        assert line.startswith("├─ ")
        assert line.endswith("┤")
        assert len(line) == 40
    assert narrow_lines[-1].startswith("└─ ")
    assert narrow_lines[-1].endswith("┘")
    assert len(narrow_lines[-1]) == 40


def test_finished_runner_displays_all_hotkeys_and_wraps():
    app = CliTuiApp(parser=build_test_parser())
    # Navigate to inventory form
    app.process_key(10)

    class DummyRunner:
        is_running = False
        exit_code = 0
        elapsed_seconds = 12.3
        lines = [f"Output line {i}" for i in range(50)]

    app.runner = DummyRunner()
    app.navigation.current_screen = TuiScreenMode.RUNNING

    # Render at 80 cols (typical default)
    screen_80 = app.render_virtual_screen(height=24, width=80)
    assert len(screen_80) == 24
    screen_text = "\n".join(screen_80)

    # Must contain all available hotkeys
    assert "[p] Panes" in screen_text
    assert "[s] Branch" in screen_text
    assert "[r] Re-run" in screen_text
    assert "[Esc] Back" in screen_text
    assert "[q] Quit" in screen_text
    assert "[Enter] Return" in screen_text

    # Must have wrapped into multiple footer rows
    assert any(line.startswith("├─ ") for line in screen_80)
    assert any(line.startswith("└─ ") for line in screen_80)

    # Render at 140 cols (wide)
    screen_140 = app.render_virtual_screen(height=24, width=140)
    assert len(screen_140) == 24
    # Single row footer on wide width
    assert not any(line.startswith("├─ ") for line in screen_140)
    assert any(line.startswith("└─ ") for line in screen_140)


def test_menu_and_form_display_pane_and_branch_hotkeys():
    app = CliTuiApp(parser=build_test_parser())
    # Menu screen
    menu_screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "[p] Panes" in menu_screen
    assert "[Shift+Esc] New Pane" in menu_screen
    assert "[Enter] Select" in menu_screen
    assert "[q] Quit" in menu_screen

    # Form screen
    app.process_key(10)
    assert app.screen_mode == TuiScreenMode.FORM
    form_screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "[p] Panes" in form_screen
    assert "[Shift+Esc] New Pane" in form_screen
    assert "[q] Quit" in form_screen


def test_multiple_panes_displays_prev_next_cycling_hotkeys():
    app = CliTuiApp(parser=build_test_parser())
    # Create second pane
    app.workspace.create_pane(title="second", pane_type=PaneType.COMMAND)

    screen = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "[[]/[]] Prev/Next" in screen
