from __future__ import annotations

import argparse
import curses
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from .process_runner import OutputViewport, ProcessRunner
from .schema import CliCommand, introspect_parser
from .state import FormState, NavigationStack, TuiScreenMode
from .widgets import BaseWidget, create_widget_for_arg


@dataclass
class PostRunAction:
    """Action callback offered after a process run finishes."""

    key: int
    label: str
    callback: Callable[[CliTuiApp], None]
    predicate: Optional[Callable[[CliTuiApp], bool]] = None


class CliTuiApp:
    """Main interactive TUI controller for command-line tools."""

    def __init__(
        self,
        parser: Optional[argparse.ArgumentParser] = None,
        *,
        root_command: Optional[CliCommand] = None,
        title: Optional[str] = None,
        executable: Optional[Sequence[str]] = None,
        action_handlers: Optional[Dict[str, Callable[[], None]]] = None,
    ) -> None:
        if root_command is not None:
            self.root_command = root_command
        elif parser is not None:
            self.root_command = introspect_parser(parser)
        else:
            raise ValueError("Either parser or root_command must be provided.")

        self.title = title or self.root_command.prog or "CLI TUI"
        self.executable = (
            list(executable)
            if executable
            else [self.root_command.prog or sys.executable]
        )
        self.action_handlers = action_handlers or {}
        self.post_run_actions: List[PostRunAction] = []

        self.navigation = NavigationStack()
        self.current_form: Optional[FormState] = None
        self.form_widgets: List[BaseWidget] = []
        self.form_cursor: int = (
            0  # 0..len(widgets)-1: widget, len: [Run], len+1: [Preview], len+2: [Back]
        )
        self.menu_cursor: int = 0

        self.runner: Optional[ProcessRunner] = None
        self.viewport = OutputViewport()
        self.is_confirming_quit: bool = False
        self.is_terminated: bool = False

    def add_post_run_action(self, action: PostRunAction) -> None:
        """Register a post-run action callback."""
        self.post_run_actions.append(action)

    @property
    def screen_mode(self) -> TuiScreenMode:
        return self.navigation.current_screen

    @property
    def current_command(self) -> CliCommand:
        curr = self.root_command
        for crumb in self.navigation.path:
            if crumb in curr.subcommands:
                curr = curr.subcommands[crumb]
        return curr

    def _open_form_for_command(self, cmd: CliCommand) -> None:
        subcommands_path = self.navigation.path
        self.current_form = FormState(cmd, subcommands_path=subcommands_path)
        self.form_widgets = [
            create_widget_for_arg(arg, self.current_form.get_value(arg.dest))
            for arg in cmd.arguments
        ]
        self.form_cursor = 0
        self.navigation.current_screen = TuiScreenMode.FORM

    def process_key(self, key: int) -> bool:
        """Universal key processor returning True if handled."""
        # 1. Immediate unconditional quit on 'Q'
        if key == ord("Q"):
            if self.runner and self.runner.is_running:
                self.runner.terminate()
            self.is_terminated = True
            self.is_confirming_quit = False
            return True

        # 2. Quit confirmation dialog handling
        if self.is_confirming_quit:
            if key in (ord("y"), ord("Y")):
                if self.runner and self.runner.is_running:
                    self.runner.terminate()
                self.is_terminated = True
                self.is_confirming_quit = False
            elif key in (ord("n"), ord("N"), 27):  # 'n' or Esc cancels
                self.is_confirming_quit = False
            return True

        # 3. 'q' prompt handling
        if key == ord("q"):
            # If in a text widget currently being edited, type 'q'
            if (
                self.screen_mode == TuiScreenMode.FORM
                and self.form_widgets
                and self.form_cursor < len(self.form_widgets)
            ):
                active_widget = self.form_widgets[self.form_cursor]
                if getattr(active_widget, "is_editing", False):
                    return active_widget.handle_key(key)
            self.is_confirming_quit = True
            return True

        # 4. Esc back-navigation
        if key == 27:
            if self.screen_mode == TuiScreenMode.FORM:
                if self.form_widgets and self.form_cursor < len(self.form_widgets):
                    active_widget = self.form_widgets[self.form_cursor]
                    if getattr(active_widget, "is_editing", False):
                        active_widget.handle_key(key)
                        return True
                # Return to menu
                self.navigation.pop()
                self.current_form = None
                self.form_widgets = []
                return True
            elif self.screen_mode == TuiScreenMode.RUNNING:
                if not self.runner or not self.runner.is_running:
                    self.navigation.current_screen = TuiScreenMode.FORM
                return True
            elif self.screen_mode == TuiScreenMode.MENU:
                if self.navigation.path:
                    self.navigation.pop()
                    self.menu_cursor = 0
                else:
                    self.is_confirming_quit = True
                return True

        # 5. Screen-specific dispatch
        if self.screen_mode == TuiScreenMode.MENU:
            return self._handle_menu_key(key)
        elif self.screen_mode == TuiScreenMode.FORM:
            return self._handle_form_key(key)
        elif self.screen_mode == TuiScreenMode.RUNNING:
            return self._handle_running_key(key)

        return False

    def _handle_menu_key(self, key: int) -> bool:
        cmd = self.current_command
        choices = list(cmd.subcommands.keys())
        if not choices:
            return False

        if key in (curses.KEY_UP, ord("k")):
            self.menu_cursor = (self.menu_cursor - 1 + len(choices)) % len(choices)
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            self.menu_cursor = (self.menu_cursor + 1) % len(choices)
            return True
        elif key in (10, 13, ord(" ")):
            selected_name = choices[self.menu_cursor]
            target_cmd = cmd.subcommands[selected_name]
            if target_cmd.subcommands:
                self.navigation.push(selected_name, TuiScreenMode.MENU)
                self.menu_cursor = 0
            else:
                self.navigation.push(selected_name, TuiScreenMode.FORM)
                self._open_form_for_command(target_cmd)
            return True
        return False

    def _handle_form_key(self, key: int) -> bool:
        total_items = len(self.form_widgets) + 3  # widgets + [Run], [Preview], [Back]
        if self.form_cursor < len(self.form_widgets):
            active_widget = self.form_widgets[self.form_cursor]
            if getattr(active_widget, "is_editing", False):
                handled = active_widget.handle_key(key)
                if self.current_form:
                    self.current_form.set_value(
                        active_widget.arg.dest, active_widget.value
                    )
                return handled

        if key in (curses.KEY_UP, ord("k")):
            self.form_cursor = (self.form_cursor - 1 + total_items) % total_items
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            self.form_cursor = (self.form_cursor + 1) % total_items
            return True
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            if self.form_cursor < len(self.form_widgets):
                active_widget = self.form_widgets[self.form_cursor]
                handled = active_widget.handle_key(key)
                if self.current_form:
                    self.current_form.set_value(
                        active_widget.arg.dest, active_widget.value
                    )
                return handled
        elif key in (10, 13, ord(" ")):
            if self.form_cursor < len(self.form_widgets):
                active_widget = self.form_widgets[self.form_cursor]
                handled = active_widget.handle_key(key)
                if self.current_form:
                    self.current_form.set_value(
                        active_widget.arg.dest, active_widget.value
                    )
                return handled
            else:
                button_idx = self.form_cursor - len(self.form_widgets)
                if button_idx == 0:  # [ Run Command ]
                    self._start_execution()
                    return True
                elif button_idx == 1:  # [ Preview CLI ]
                    return True
                elif button_idx == 2:  # [ Back ]
                    self.navigation.pop()
                    self.current_form = None
                    self.form_widgets = []
                    return True
        return False

    def _start_execution(self) -> None:
        if not self.current_form:
            return
        argv = self.current_form.build_argv(executable=self.executable)
        self.runner = ProcessRunner(argv)
        self.viewport.scroll_to_end()
        self.runner.start()
        self.navigation.current_screen = TuiScreenMode.RUNNING

    def _handle_running_key(self, key: int) -> bool:
        if key in (curses.KEY_UP, ord("k")):
            self.viewport.scroll_up(1)
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            self.viewport.scroll_down(1)
            return True
        elif key in (curses.KEY_PPAGE,):  # Page Up
            self.viewport.scroll_page_up(15)
            return True
        elif key in (curses.KEY_NPAGE,):  # Page Down
            self.viewport.scroll_page_down(15)
            return True
        elif key in (curses.KEY_END,):
            self.viewport.scroll_to_end()
            return True
        elif key in (ord("c"), ord("C")):
            if self.runner and self.runner.is_running:
                self.runner.terminate()
                return True
        elif key in (10, 13):
            if not self.runner or not self.runner.is_running:
                self.navigation.current_screen = TuiScreenMode.FORM
                return True

        # Check post-run action callbacks when runner is finished
        if not self.runner or not self.runner.is_running:
            for action in self.post_run_actions:
                if action.predicate is None or action.predicate(self):
                    matches = False
                    if key == action.key:
                        matches = True
                    elif 0 <= action.key <= 127 and chr(action.key).isalpha():
                        if chr(key).lower() == chr(action.key).lower():
                            matches = True
                    if matches:
                        action.callback(self)
                        return True

        return False

    def render_virtual_screen(self, *, height: int = 24, width: int = 80) -> List[str]:
        """Render text representation of the screen for unit testing and display."""
        lines: List[str] = []
        path_str = " > ".join([self.title] + self.navigation.path)
        header = f"┌─ {path_str} ".ljust(width - 1, "─") + "┐"
        lines.append(header)

        inner_height = max(1, height - 3)

        if self.screen_mode == TuiScreenMode.MENU:
            cmd = self.current_command
            choices = list(cmd.subcommands.keys())
            content_lines = ["", f"  Select an operation from {cmd.name}:", ""]
            for idx, choice in enumerate(choices):
                sub_cmd = cmd.subcommands[choice]
                help_hint = f" — {sub_cmd.help}" if sub_cmd.help else ""
                ptr = "▶ " if idx == self.menu_cursor else "  "
                content_lines.append(f"  {ptr}{choice}{help_hint}")
            while len(content_lines) < inner_height:
                content_lines.append("")
            lines.extend(content_lines[:inner_height])

        elif self.screen_mode == TuiScreenMode.FORM:
            cmd = self.current_command
            content_lines = [
                "",
                f"  Configure arguments for: {cmd.prog or cmd.name}",
                "",
            ]
            for idx, widget in enumerate(self.form_widgets):
                is_focused = idx == self.form_cursor
                content_lines.append("  " + widget.render_line(width - 4, is_focused))

            content_lines.append("")
            run_focused = self.form_cursor == len(self.form_widgets)
            prev_focused = self.form_cursor == len(self.form_widgets) + 1
            back_focused = self.form_cursor == len(self.form_widgets) + 2

            btn_run = "▶ [ Run Command ]" if run_focused else "  [ Run Command ]"
            btn_prev = "▶ [ Preview CLI ]" if prev_focused else "  [ Preview CLI ]"
            btn_back = "▶ [ Back ]" if back_focused else "  [ Back ]"
            content_lines.append(f"  {btn_run}   {btn_prev}   {btn_back}")

            if self.current_form:
                argv = self.current_form.build_argv(executable=self.executable)
                content_lines.append("")
                content_lines.append(f"  Command: {' '.join(argv)}")

            while len(content_lines) < inner_height:
                content_lines.append("")
            lines.extend(content_lines[:inner_height])

        elif self.screen_mode == TuiScreenMode.RUNNING:
            runner = self.runner
            status_text = (
                "RUNNING"
                if runner and runner.is_running
                else f"FINISHED (exit code {runner.exit_code if runner else 0})"
            )
            content_lines = [
                f"  Status: {status_text}  |  Elapsed: {runner.elapsed_seconds if runner else 0:.1f}s",
                "",
            ]
            raw_lines = runner.lines if runner else []
            visible = self.viewport.get_visible_lines(
                raw_lines, height=inner_height - 3, width=width
            )
            content_lines.extend(f"  {line}" for line in visible)
            while len(content_lines) < inner_height:
                content_lines.append("")
            lines.extend(content_lines[:inner_height])

        # Footer
        if self.is_confirming_quit:
            footer = (
                "└─ Are you sure you want to exit? (y/n) ".ljust(width - 1, "─") + "┘"
            )
        elif self.screen_mode == TuiScreenMode.RUNNING and (
            not self.runner or not self.runner.is_running
        ):
            active_actions = [
                a
                for a in self.post_run_actions
                if a.predicate is None or a.predicate(self)
            ]
            if active_actions:
                actions_str = "  ".join(a.label for a in active_actions)
                footer = (
                    f"└─ [q] Quit  [Esc] Back  {actions_str}  [Enter] Return ".ljust(
                        width - 1, "─"
                    )
                    + "┘"
                )
            else:
                footer = (
                    "└─ [q] Quit  [Q] Force Quit  [Esc] Back  [Enter] Return ".ljust(
                        width - 1, "─"
                    )
                    + "┘"
                )
        else:
            footer = (
                "└─ [q] Quit  [Q] Force Quit  [Esc] Back  [Enter] Select ".ljust(
                    width - 1, "─"
                )
                + "┘"
            )
        lines.append(footer)

        return lines[:height]

    def run(self) -> int:
        """Run the interactive curses TUI."""
        try:
            return curses.wrapper(self._curses_loop)
        except KeyboardInterrupt:
            if self.runner and self.runner.is_running:
                self.runner.terminate()
            return 0

    def _curses_loop(self, stdscr: Any) -> int:
        curses.curs_set(0)
        stdscr.timeout(50)  # 50ms tick for smooth live runner updates
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)

        while not self.is_terminated:
            max_y, max_x = stdscr.getmaxyx()
            lines = self.render_virtual_screen(height=max_y, width=max_x)
            stdscr.erase()
            for y, line in enumerate(lines[:max_y]):
                try:
                    stdscr.addstr(y, 0, line[: max_x - 1])
                except curses.error:
                    pass
            stdscr.refresh()

            try:
                ch = stdscr.getch()
                if ch != -1:
                    self.process_key(ch)
            except curses.error:
                pass

        if self.runner and self.runner.is_running:
            self.runner.terminate()
        return 0
