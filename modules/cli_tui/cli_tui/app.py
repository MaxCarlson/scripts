from __future__ import annotations

import argparse
import curses
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from .console_pane import ConsolePaneRunner
from .layout_store import PaneLayoutStore
from .output_capture import OutputFileCapture
from .process_runner import OutputViewport, ProcessRunner, _visible_len, wrap_ansi_line
from .schema import CliCommand, introspect_parser
from .state import (
    FormState,
    NavigationStack,
    PaneSession,
    PaneType,
    PaneWorkspace,
    TuiScreenMode,
    copy_matching_form_values,
)
from .widgets import BaseWidget, create_widget_for_arg

try:
    from sysmon.sampler import (
        HardwareSampler,
        ProcessStats,
        SystemStats,
        TelemetryDisplayMode,
    )
except ImportError:
    HardwareSampler = None  # type: ignore
    ProcessStats = None  # type: ignore
    SystemStats = None  # type: ignore
    from enum import Enum

    class TelemetryDisplayMode(Enum):  # type: ignore
        FULL = "full"
        COMPACT = "compact"
        HIDDEN = "hidden"


def _color_metric(
    val_str: str,
    pct: Optional[float] = None,
    high: float = 85.0,
    mid: float = 60.0,
) -> str:
    """Apply ANSI threshold colors: green (< mid), yellow (mid <= x < high), red (>= high)."""
    if pct is None or val_str in ("—", "N/A"):
        return f"\x1b[90m{val_str}\x1b[0m"
    if pct >= high:
        return f"\x1b[1;31m{val_str}\x1b[0m"
    elif pct >= mid:
        return f"\x1b[1;33m{val_str}\x1b[0m"
    else:
        return f"\x1b[1;32m{val_str}\x1b[0m"


def _build_telemetry_bar(
    prefix: str, content: str, suffix: str, fill_char: str, width: int
) -> str:
    """Construct a full-width box line respecting embedded ANSI escape sequences."""
    overhead = _visible_len(prefix) + 1 + _visible_len(suffix)
    if width <= overhead:
        return (prefix + suffix)[:width]
    max_inner = max(0, width - overhead)
    if _visible_len(content) > max_inner:
        content = wrap_ansi_line(content, max_inner)[0]
    vis = _visible_len(content)
    pad = max(0, max_inner - vis)
    return f"{prefix}{content} " + (fill_char * pad) + suffix


def addstr_ansi(stdscr: Any, y: int, x: int, line: str, max_x: int) -> None:
    """Render a line with ANSI color and style sequences onto a curses window."""
    if y < 0 or x >= max_x or not line:
        return

    color_map = {
        "31": 4,  # Red
        "32": 2,  # Green
        "33": 3,  # Yellow
        "34": 6,  # Blue
        "35": 5,  # Magenta
        "36": 1,  # Cyan
        "37": 7,  # White
        "90": 7,  # Gray / bright black
        "91": 4,  # Bright Red
        "92": 2,  # Bright Green
        "93": 3,  # Bright Yellow
        "94": 6,  # Bright Blue
        "95": 5,  # Bright Magenta
        "96": 1,  # Bright Cyan
        "97": 7,  # Bright White
    }

    pattern = re.compile(r"(\x1b\[[0-9;]*m)")
    parts = pattern.split(line)

    curr_x = x
    curr_attr = curses.A_NORMAL
    curr_color_pair = 0

    has_colors = False
    try:
        has_colors = curses.has_colors()
    except Exception:
        pass

    for part in parts:
        if not part:
            continue
        if part.startswith("\x1b[") and part.endswith("m"):
            codes = part[2:-1].split(";")
            for code in codes:
                if not code or code == "0":
                    curr_attr = curses.A_NORMAL
                    curr_color_pair = 0
                elif code == "1":
                    curr_attr |= curses.A_BOLD
                elif code == "2":
                    curr_attr |= curses.A_DIM
                elif code in color_map and has_colors:
                    try:
                        curr_color_pair = curses.color_pair(color_map[code])
                    except Exception:
                        curr_color_pair = 0
                elif code == "39":
                    curr_color_pair = 0
        else:
            if curr_x >= max_x - 1:
                break
            avail = (max_x - 1) - curr_x
            to_draw = part[:avail]
            if not to_draw:
                continue
            attr = curr_attr | curr_color_pair
            try:
                stdscr.addstr(y, curr_x, to_draw, attr)
            except curses.error:
                pass
            curr_x += len(to_draw)


def format_hotkey_footer(badges: Sequence[str], width: int) -> List[str]:
    """Format hotkey badges into 1, 2, or 3 box-drawn footer lines fitting width."""
    if not badges:
        return ["└─".ljust(width - 1, "─") + "┘"]

    rows: List[List[str]] = []
    current_row: List[str] = []
    # "├─ " or "└─ " (3 chars) + " " before suffix (1 char) + suffix (1 char) = 5 chars overhead
    avail_width = max(10, width - 5)

    current_len = 0
    for badge in badges:
        badge_len = len(badge)
        needed = badge_len if not current_row else current_len + 2 + badge_len
        if needed <= avail_width:
            current_row.append(badge)
            current_len = needed
        else:
            if current_row:
                rows.append(current_row)
            current_row = [badge]
            current_len = badge_len

    if current_row:
        rows.append(current_row)

    lines: List[str] = []
    total_rows = len(rows)
    for idx, row in enumerate(rows):
        is_last = idx == total_rows - 1
        prefix = "└─ " if is_last else "├─ "
        suffix = "┘" if is_last else "┤"
        content = "  ".join(row)
        full_line = f"{prefix}{content} "
        if len(full_line) > width - 1:
            full_line = full_line[: max(0, width - 2)] + " "
        lines.append(full_line.ljust(width - 1, "─") + suffix)

    return lines


@dataclass
class PostRunAction:
    """Action callback offered after a process run finishes."""

    key: int
    label: str
    callback: Callable[[CliTuiApp], None]
    predicate: Optional[Callable[[CliTuiApp], bool]] = None


def _nonnegative_index(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    return False


class _RestoredPaneOutput:
    """Read-only output snapshot restored from a saved workspace layout."""

    def __init__(self, lines: Sequence[str]) -> None:
        self.lines = list(lines)
        self.is_running = False
        self.exit_code = 0
        self.elapsed_seconds = 0.0
        self.restored = True


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
        layout_dir: Optional[str | os.PathLike[str]] = None,
        launch_dir: Optional[str | os.PathLike[str]] = None,
        app_id: Optional[str] = None,
        enable_layout_persistence: bool = True,
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

        self.workspace = PaneWorkspace()
        self.workspace.active_pane.title = self.title
        self.form_widgets: List[BaseWidget] = []
        self.form_cursor: int = (
            0  # 0..len(widgets)-1: widget, len: [Run], len+1: [Preview], len+2: [Back]
        )
        self.menu_cursor: int = 0
        self.layout_store = PaneLayoutStore(layout_dir) if enable_layout_persistence else None
        self.layout_root = Path(launch_dir or os.getcwd()).expanduser().resolve()
        self.layout_app_id = app_id or self.root_command.prog or self.title
        self.last_message = ""
        self.is_confirming_layout_save = False
        self.is_showing_output_capture = False
        self.is_confirming_output_overwrite = False
        self.output_capture_directory = str(Path.cwd())
        self.output_capture_filename = "pane-output.log"
        self.output_capture_field = 0

        self.is_pane_manager_open: bool = False
        self.manager_cursor: int = 0
        self.is_showing_new_pane_choice: bool = False
        self.is_confirming_quit: bool = False
        self.is_showing_preview: bool = False
        self.is_terminated: bool = False

        self.telemetry_mode: TelemetryDisplayMode = (
            TelemetryDisplayMode.FULL
            if HardwareSampler is not None
            else TelemetryDisplayMode.HIDDEN
        )
        self.sampler: Optional[Any] = None
        if HardwareSampler is not None:
            try:
                self.sampler = HardwareSampler(interval=0.5)
                self.sampler.start()
            except Exception:
                self.sampler = None
        self._last_sys_stats: Optional[Any] = None
        self._last_proc_stats: Optional[Any] = None
        self._load_saved_layout()

    def _load_saved_layout(self) -> None:
        if self.layout_store is None:
            return
        saved = self.layout_store.load(self.layout_root, self.layout_app_id)
        if not saved or not isinstance(saved.get("panes"), list):
            return

        panes: List[PaneSession] = []
        for descriptor in saved["panes"][:50]:
            if not isinstance(descriptor, dict):
                continue
            try:
                pane_type = PaneType(descriptor.get("type", PaneType.COMMAND.value))
            except (TypeError, ValueError):
                pane_type = PaneType.COMMAND
            pane = PaneSession(
                id=os.urandom(4).hex(),
                title=str(descriptor.get("title") or "Main"),
                pane_type=pane_type,
            )
            path = descriptor.get("path", [])
            if not isinstance(path, list):
                path = []
            command = self.root_command
            for crumb in path:
                if not isinstance(crumb, str) or crumb not in command.subcommands:
                    break
                command = command.subcommands[crumb]
                pane.navigation.push(crumb, TuiScreenMode.MENU)

            screen_name = descriptor.get("screen", TuiScreenMode.MENU.name)
            try:
                screen = TuiScreenMode[screen_name]
            except (KeyError, TypeError):
                screen = TuiScreenMode.MENU
            values = descriptor.get("form_values")
            if pane_type == PaneType.COMMAND and isinstance(values, dict):
                pane.current_form = FormState(command, subcommands_path=pane.navigation.path)
                valid_destinations = {arg.dest for arg in command.arguments}
                for key, value in values.items():
                    if key in valid_destinations and _is_json_value(value):
                        pane.current_form.set_value(key, value)
                pane.current_form.focused_index = _nonnegative_index(
                    descriptor.get("form_cursor")
                )
            if screen == TuiScreenMode.RUNNING and pane_type == PaneType.COMMAND:
                output = descriptor.get("output", [])
                if isinstance(output, list) and all(isinstance(line, str) for line in output):
                    pane.runner = _RestoredPaneOutput(output)
            if pane_type == PaneType.CONSOLE:
                console_cwd = descriptor.get("console_cwd")
                if not isinstance(console_cwd, str) or not console_cwd:
                    console_cwd = os.getcwd()
                console = ConsolePaneRunner(cwd=console_cwd)
                history = descriptor.get("console_history")
                if isinstance(history, list) and all(isinstance(line, str) for line in history):
                    console.history_lines = history[-10000:]
                pane.runner = console
                pane.extra_data["console_runner"] = console
                screen = TuiScreenMode.RUNNING
            pane.navigation.current_screen = screen
            pane.screen_mode = screen
            pane.extra_data["form_cursor"] = _nonnegative_index(descriptor.get("form_cursor"))
            pane.extra_data["menu_cursor"] = _nonnegative_index(descriptor.get("menu_cursor"))
            viewport = descriptor.get("viewport")
            if isinstance(viewport, dict):
                pane.viewport.scroll_offset = _nonnegative_index(viewport.get("scroll_offset"))
                if isinstance(viewport.get("auto_scroll"), bool):
                    pane.viewport.auto_scroll = viewport["auto_scroll"]
            panes.append(pane)

        if panes:
            self.workspace.panes = panes
            self.workspace.active_index = min(
                _nonnegative_index(saved.get("active_index")), len(panes) - 1
            )
            self._restore_active_pane_state()

    def _layout_data(self) -> Dict[str, Any]:
        self._save_current_pane_state()
        panes: List[Dict[str, Any]] = []
        for pane in self.workspace.panes:
            screen = pane.navigation.current_screen
            output: List[str] = []
            if pane.runner is not None and hasattr(pane.runner, "lines"):
                try:
                    output = list(pane.runner.lines)[-10000:]
                except Exception:
                    output = []
            form_values = pane.current_form.values if pane.current_form else None
            try:
                import json

                safe_values = json.loads(json.dumps(form_values)) if form_values is not None else None
            except (TypeError, ValueError):
                safe_values = None
            descriptor: Dict[str, Any] = {
                "title": pane.title,
                "type": pane.pane_type.value,
                "screen": screen.name,
                "path": pane.navigation.path,
                "form_values": safe_values,
                "form_cursor": pane.extra_data.get(
                    "form_cursor", pane.current_form.focused_index if pane.current_form else 0
                ),
                "menu_cursor": pane.extra_data.get("menu_cursor", 0),
                "viewport": {
                    "scroll_offset": pane.viewport.scroll_offset,
                    "auto_scroll": pane.viewport.auto_scroll,
                },
            }
            if screen == TuiScreenMode.RUNNING:
                descriptor["output"] = output
            if pane.pane_type == PaneType.CONSOLE and pane.runner is not None:
                descriptor["console_cwd"] = getattr(pane.runner, "cwd", os.getcwd())
                descriptor["console_history"] = list(getattr(pane.runner, "lines", []))[-10000:]
            panes.append(descriptor)
        return {"panes": panes, "active_index": self.workspace.active_index}

    def save_layout(self) -> bool:
        if self.layout_store is None:
            self.last_message = "Pane layout saving is disabled"
            return False
        try:
            self.layout_store.save(self.layout_root, self.layout_app_id, self._layout_data())
        except (OSError, TypeError, ValueError) as exc:
            self.last_message = f"Could not save pane layout: {exc}"
            return False
        self.last_message = "Pane layout saved"
        return True

    def _finish_quit(self) -> None:
        self.workspace.terminate_all()
        if self.runner and getattr(self.runner, "is_running", False):
            self.runner.terminate()
        self.is_terminated = True
        self.is_confirming_quit = False
        self.is_confirming_layout_save = False

    def _open_output_capture_dialog(self) -> None:
        pane = self.workspace.active_pane
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", pane.title).strip("._") or "pane"
        self.output_capture_directory = str(Path.cwd())
        self.output_capture_filename = f"{safe_title}.log"
        self.output_capture_field = 0
        self.is_showing_output_capture = True
        self.is_confirming_output_overwrite = False

    def _handle_output_capture_key(self, key: int) -> bool:
        if self.is_confirming_output_overwrite:
            if key in (ord("y"), ord("Y")):
                self._start_output_capture(overwrite=True)
            elif key in (ord("n"), ord("N"), 27):
                self.is_confirming_output_overwrite = False
                self.is_showing_output_capture = False
            return True
        if key == 27:
            self.is_showing_output_capture = False
            return True
        if key in (9, curses.KEY_BTAB):
            self.output_capture_field = 1 - self.output_capture_field
            return True
        if key in (10, 13):
            if self.output_capture_field == 0:
                self.output_capture_field = 1
            else:
                target = Path(self.output_capture_directory).expanduser() / self.output_capture_filename
                if target.exists():
                    self.is_confirming_output_overwrite = True
                else:
                    self._start_output_capture(overwrite=False)
            return True
        values = [self.output_capture_directory, self.output_capture_filename]
        if key in (8, 127, curses.KEY_BACKSPACE):
            values[self.output_capture_field] = values[self.output_capture_field][:-1]
        elif 32 <= key <= 126:
            values[self.output_capture_field] += chr(key)
        self.output_capture_directory, self.output_capture_filename = values
        return True

    def _start_output_capture(self, *, overwrite: bool) -> None:
        self.is_confirming_output_overwrite = False
        self.is_showing_output_capture = False
        pane = self.workspace.active_pane
        target = Path(self.output_capture_directory).expanduser() / self.output_capture_filename
        capture: Optional[OutputFileCapture] = None
        try:
            previous = pane.extra_data.get("output_capture")
            if previous is not None:
                previous.close()
                pane.extra_data.pop("output_capture", None)
            capture = OutputFileCapture(
                target,
                overwrite=overwrite,
                on_error=lambda exc: setattr(self, "last_message", f"Output capture failed: {exc}"),
            )
            runner = pane.runner
            active_runner = getattr(runner, "active_runner", None) or runner
            capture_runner = runner if hasattr(runner, "subscribe_output") else active_runner
            if hasattr(capture_runner, "subscribe_output"):
                capture.attach(capture_runner)
            elif hasattr(runner, "lines"):
                capture.write_snapshot(runner.lines)
            else:
                capture.close()
                self.last_message = "The active pane has no capturable output"
                return
            pane.extra_data["output_capture"] = capture
            self.last_message = f"Saving pane output to {target}"
        except (OSError, TypeError, ValueError) as exc:
            if capture is not None:
                capture.close()
            self.last_message = f"Could not save pane output: {exc}"

    def _close_output_capture(self, pane: PaneSession) -> None:
        capture = pane.extra_data.pop("output_capture", None)
        if capture is not None:
            capture.close()

    def add_post_run_action(self, action: PostRunAction) -> None:
        """Register a post-run action callback."""
        self.post_run_actions.append(action)

    @property
    def navigation(self) -> NavigationStack:
        return self.workspace.active_pane.navigation

    @navigation.setter
    def navigation(self, nav: NavigationStack) -> None:
        self.workspace.active_pane.navigation = nav

    @property
    def current_form(self) -> Optional[FormState]:
        return self.workspace.active_pane.current_form

    @current_form.setter
    def current_form(self, form: Optional[FormState]) -> None:
        self.workspace.active_pane.current_form = form

    @property
    def runner(self) -> Optional[ProcessRunner]:
        return self.workspace.active_pane.runner

    @runner.setter
    def runner(self, r: Optional[ProcessRunner]) -> None:
        self.workspace.active_pane.runner = r

    @property
    def viewport(self) -> OutputViewport:
        return self.workspace.active_pane.viewport

    @viewport.setter
    def viewport(self, vp: OutputViewport) -> None:
        self.workspace.active_pane.viewport = vp

    @property
    def pane_workspace(self) -> PaneWorkspace:
        """Alias for workspace to support multi-pane management."""
        return self.workspace

    def _get_active_runner_pid(self) -> Optional[int]:
        """Retrieve OS PID of the currently active pane's runner, if active."""
        runner = self.workspace.active_pane.runner
        if runner is not None:
            is_running = getattr(runner, "is_running", False)
            if callable(is_running):
                is_running = is_running()
            if is_running:
                if (
                    hasattr(runner, "proc")
                    and runner.proc is not None
                    and hasattr(runner.proc, "pid")
                ):
                    return getattr(runner.proc, "pid")
                if hasattr(runner, "pid") and runner.pid is not None:
                    return getattr(runner.pid, "pid", runner.pid)
                if (
                    hasattr(runner, "_process")
                    and runner._process is not None
                    and hasattr(runner._process, "pid")
                ):
                    return getattr(runner._process, "pid")
                if (
                    hasattr(runner, "active_runner")
                    and runner.active_runner is not None
                ):
                    sub = runner.active_runner
                    if (
                        hasattr(sub, "proc")
                        and sub.proc is not None
                        and hasattr(sub.proc, "pid")
                    ):
                        return getattr(sub.proc, "pid")
                    if hasattr(sub, "pid") and sub.pid is not None:
                        return getattr(sub.pid, "pid", sub.pid)
                    if (
                        hasattr(sub, "_process")
                        and sub._process is not None
                        and hasattr(sub._process, "pid")
                    ):
                        return getattr(sub._process, "pid")
        return None

    def _sync_target_pid(self) -> None:
        """Synchronize the background hardware sampler target PID with active pane."""
        if self.sampler is not None:
            target_pid = self._get_active_runner_pid()
            self.sampler.set_target_pid(target_pid)

    def cycle_telemetry_mode(self) -> TelemetryDisplayMode:
        """Cycle telemetry display mode: FULL -> COMPACT -> HIDDEN -> FULL."""
        if self.telemetry_mode == TelemetryDisplayMode.FULL:
            self.telemetry_mode = TelemetryDisplayMode.COMPACT
        elif self.telemetry_mode == TelemetryDisplayMode.COMPACT:
            self.telemetry_mode = TelemetryDisplayMode.HIDDEN
        else:
            self.telemetry_mode = TelemetryDisplayMode.FULL
        return self.telemetry_mode

    def _save_current_pane_state(self) -> None:
        pane = self.workspace.active_pane
        pane.screen_mode = self.navigation.current_screen
        pane.extra_data["form_widgets"] = self.form_widgets
        pane.extra_data["form_cursor"] = self.form_cursor
        pane.extra_data["menu_cursor"] = self.menu_cursor

    def _restore_active_pane_state(self) -> None:
        pane = self.workspace.active_pane
        self.form_widgets = pane.extra_data.get("form_widgets", [])
        self.form_cursor = pane.extra_data.get("form_cursor", 0)
        self.menu_cursor = pane.extra_data.get("menu_cursor", 0)
        if pane.current_form and not self.form_widgets:
            self.form_widgets = [
                create_widget_for_arg(arg, pane.current_form.get_value(arg.dest))
                for arg in pane.current_form.command.arguments
            ]
        self._sync_target_pid()

    def cycle_pane_prev(self) -> None:
        if len(self.workspace.panes) <= 1:
            return
        self._save_current_pane_state()
        self.workspace.cycle_prev()
        self._restore_active_pane_state()

    def cycle_pane_next(self) -> None:
        if len(self.workspace.panes) <= 1:
            return
        self._save_current_pane_state()
        self.workspace.cycle_next()
        self._restore_active_pane_state()

    def switch_pane(self, index: int) -> bool:
        if 0 <= index < len(self.workspace.panes):
            self._save_current_pane_state()
            self.workspace.switch_to(index)
            self._restore_active_pane_state()
            return True
        return False

    def _switch_to_pane(self, target: Any) -> bool:
        """Switch to a pane by index, ID string, or pane object."""
        if isinstance(target, int):
            return self.switch_pane(target)
        target_id = getattr(target, "id", target)
        if isinstance(target_id, str):
            for idx, p in enumerate(self.workspace.panes):
                if p.id == target_id:
                    return self.switch_pane(idx)
        return False

    def _is_widget_editing(self) -> bool:
        if (
            self.screen_mode == TuiScreenMode.FORM
            and self.form_widgets
            and self.form_cursor < len(self.form_widgets)
        ):
            widget = self.form_widgets[self.form_cursor]
            return bool(getattr(widget, "is_editing", False))
        return False

    def branch_to_new_command_pane(self) -> PaneSession:
        """Branch from current pane into a new command pane with argument inheritance."""
        self._save_current_pane_state()
        source_form = self.current_form
        new_pane = self.workspace.create_pane(
            title=self.title,
            pane_type=PaneType.COMMAND,
            screen_mode=TuiScreenMode.MENU,
        )
        new_pane.navigation.current_screen = TuiScreenMode.MENU
        if source_form:
            new_pane.extra_data["parent_form"] = source_form
        self.form_widgets = []
        self.form_cursor = 0
        self.menu_cursor = 0
        return new_pane

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
        parent_form = self.workspace.active_pane.extra_data.get("parent_form")
        if parent_form:
            copy_matching_form_values(parent_form, self.current_form)
        self.form_widgets = [
            create_widget_for_arg(arg, self.current_form.get_value(arg.dest))
            for arg in cmd.arguments
        ]
        self.form_cursor = 0
        self.navigation.current_screen = TuiScreenMode.FORM
        self.workspace.active_pane.title = (
            " ".join(self.navigation.path) or cmd.prog or cmd.name
        )

    def process_key(self, key: int) -> bool:
        """Universal key processor returning True if handled."""
        if self.is_showing_output_capture:
            return self._handle_output_capture_key(key)
        if key == 19:  # Ctrl+S saves the current pane workspace.
            self.save_layout()
            return True
        if key == 15:  # Ctrl+O opens pane output capture.
            self._open_output_capture_dialog()
            return True

        # 0a. Choice dialog routing
        if getattr(self, "is_showing_new_pane_choice", False):
            return self._handle_choice_dialog_key(key)

        # 0b. Pane Manager active key routing
        if getattr(self, "is_pane_manager_open", False):
            return self._handle_pane_manager_key(key)

        # 0c. Preview dialog dismissal
        if getattr(self, "is_showing_preview", False):
            if key in (10, 13, 27, ord(" "), ord("q"), ord("Q")):
                self.is_showing_preview = False
                return True
            return True

        # 0d. Console pane active key routing
        if self.workspace.active_pane.pane_type == PaneType.CONSOLE:
            if key == 27:  # Esc opens pane manager
                self.is_pane_manager_open = True
                self.manager_cursor = self.workspace.active_index
                return True
            if key in (20, 353):  # Ctrl+T or Shift+Esc
                self.branch_to_new_command_pane()
                return True
            runner = self.workspace.active_pane.runner
            if runner and hasattr(runner, "handle_key"):
                handled = runner.handle_key(key)
                if getattr(runner, "is_terminated", False):
                    self._close_output_capture(self.workspace.active_pane)
                    self.workspace.delete_pane(self.workspace.active_index)
                    self._restore_active_pane_state()
                    return True
                return handled
            return False

        # 1. Immediate unconditional quit on 'Q'
        if key == ord("Q"):
            self.workspace.terminate_all()
            if self.runner and self.runner.is_running:
                self.runner.terminate()
            self.is_terminated = True
            self.is_confirming_quit = False
            return True

        # 2. Quit confirmation dialog handling
        if self.is_confirming_layout_save:
            if key in (ord("y"), ord("Y")):
                if self.save_layout():
                    self._finish_quit()
            elif key in (ord("n"), ord("N"), 27):
                self._finish_quit()
            return True

        if self.is_confirming_quit:
            if key in (ord("y"), ord("Y")):
                self.is_confirming_quit = False
                self.is_confirming_layout_save = True
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
                    if self.current_form:
                        self.navigation.current_screen = TuiScreenMode.FORM
                        return True
                    else:
                        self.navigation.current_screen = TuiScreenMode.MENU
                        return True
                return True
            elif self.screen_mode == TuiScreenMode.MENU:
                if self.navigation.path:
                    self.navigation.pop()
                    self.menu_cursor = 0
                else:
                    self.is_confirming_quit = True
                return True

        # Global branching shortcut (Ctrl+T or extended Shift+Esc)
        if key in (20, 353):
            if not self._is_widget_editing():
                self.branch_to_new_command_pane()
                return True

        # Global pane cycling
        if key in (ord("["), getattr(curses, "KEY_SLEFT", -999)):
            if not self._is_widget_editing():
                self.cycle_pane_prev()
                return True
        elif key in (ord("]"), getattr(curses, "KEY_SRIGHT", -999)):
            if not self._is_widget_editing():
                self.cycle_pane_next()
                return True

        # Pane manager toggle
        if key in (ord("p"), ord("P")):
            if not self._is_widget_editing():
                self._save_current_pane_state()
                self.is_pane_manager_open = True
                self.manager_cursor = self.workspace.active_index
                return True

        # Telemetry mode toggle: 't' / 'T' or Ctrl+H (ASCII 8) when not editing form widget
        if not self._is_widget_editing() and (key == 8 or key in (ord("t"), ord("T"))):
            self.cycle_telemetry_mode()
            return True

        # 5. Screen-specific dispatch
        if self.screen_mode == TuiScreenMode.MENU:
            return self._handle_menu_key(key)
        elif self.screen_mode == TuiScreenMode.FORM:
            return self._handle_form_key(key)
        elif self.screen_mode == TuiScreenMode.RUNNING:
            return self._handle_running_key(key)

        return False

    def _handle_pane_manager_key(self, key: int) -> bool:
        """Handle user input while Split Pane Manager overlay is active."""
        if key == 27:  # Esc closes manager
            self.is_pane_manager_open = False
            return True
        elif key in (10, 13):  # Enter switches to highlighted pane
            self.switch_pane(self.manager_cursor)
            self.is_pane_manager_open = False
            return True
        elif key in (curses.KEY_UP, ord("k")):
            if self.workspace.panes:
                self.manager_cursor = (self.manager_cursor - 1) % len(
                    self.workspace.panes
                )
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.workspace.panes:
                self.manager_cursor = (self.manager_cursor + 1) % len(
                    self.workspace.panes
                )
            return True
        elif key in (curses.KEY_PPAGE,):
            if 0 <= self.manager_cursor < len(self.workspace.panes):
                self.workspace.panes[self.manager_cursor].viewport.scroll_page_up(15)
            return True
        elif key in (curses.KEY_NPAGE,):
            if 0 <= self.manager_cursor < len(self.workspace.panes):
                self.workspace.panes[self.manager_cursor].viewport.scroll_page_down(15)
            return True
        elif key in (ord("n"), ord("N")):
            self.is_showing_new_pane_choice = True
            return True
        elif key == ord("d"):
            if len(self.workspace.panes) > 1:
                removed_pane = self.workspace.panes[self.manager_cursor]
                self.workspace.delete_pane(self.manager_cursor)
                self._close_output_capture(removed_pane)
                if self.manager_cursor >= len(self.workspace.panes):
                    self.manager_cursor = max(0, len(self.workspace.panes) - 1)
                self._restore_active_pane_state()
            return True
        elif key == ord("D"):
            for pane in self.workspace.panes:
                self._close_output_capture(pane)
            self.workspace.delete_all()
            self.manager_cursor = 0
            self._restore_active_pane_state()
            self.is_pane_manager_open = False
            return True
        return False

    def _handle_choice_dialog_key(self, key: int) -> bool:
        """Handle user choice between Command Menu and Shell Console."""
        if key in (ord("1"), ord("m"), ord("M")):
            self.is_showing_new_pane_choice = False
            self.is_pane_manager_open = False
            self.branch_to_new_command_pane()
            return True
        elif key in (ord("2"), ord("c"), ord("C")):
            self.is_showing_new_pane_choice = False
            self.is_pane_manager_open = False
            self._save_current_pane_state()
            new_pane = self.workspace.create_pane(
                title="Shell Console",
                pane_type=PaneType.CONSOLE,
                screen_mode=TuiScreenMode.RUNNING,
            )
            new_pane.navigation.current_screen = TuiScreenMode.RUNNING
            console_runner = ConsolePaneRunner(cwd=os.getcwd())
            new_pane.runner = console_runner
            new_pane.extra_data["console_runner"] = console_runner
            self._restore_active_pane_state()
            return True
        elif key in (27, ord("q"), ord("Q")):
            self.is_showing_new_pane_choice = False
            return True
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
        # Universal Run shortcut (Ctrl+R=18 or F5) from anywhere in form
        if key in (18, getattr(curses, "KEY_F5", 269)):
            self._start_execution()
            return True

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
        elif key in (curses.KEY_RIGHT, ord("l")):
            if self.form_cursor < len(self.form_widgets):
                active_widget = self.form_widgets[self.form_cursor]
                handled = active_widget.handle_key(key)
                if self.current_form:
                    self.current_form.set_value(
                        active_widget.arg.dest, active_widget.value
                    )
                return handled
            else:
                button_idx = (self.form_cursor - len(self.form_widgets) + 1) % 3
                self.form_cursor = len(self.form_widgets) + button_idx
                return True
        elif key in (curses.KEY_LEFT, ord("h")):
            if self.form_cursor < len(self.form_widgets):
                active_widget = self.form_widgets[self.form_cursor]
                handled = active_widget.handle_key(key)
                if self.current_form:
                    self.current_form.set_value(
                        active_widget.arg.dest, active_widget.value
                    )
                return handled
            else:
                button_idx = (self.form_cursor - len(self.form_widgets) - 1 + 3) % 3
                self.form_cursor = len(self.form_widgets) + button_idx
                return True
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
                    self.is_showing_preview = True
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
        argv = self._build_current_argv()
        if argv is None:
            return
        self.runner = ProcessRunner(argv)
        self.viewport.scroll_to_end()
        self.runner.start()
        self.navigation.current_screen = TuiScreenMode.RUNNING
        self._sync_target_pid()

    def _build_current_argv(self) -> Optional[List[str]]:
        if not self.current_form:
            return None
        try:
            argv = self.current_form.build_argv(executable=self.executable)
        except (TypeError, ValueError) as exc:
            self.last_message = f"Cannot build command: {exc}"
            return None
        if self.last_message.startswith("Cannot build command:"):
            self.last_message = ""
        return argv

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
        elif key in (curses.KEY_HOME, ord("g")):
            self.viewport.scroll_offset = 999999
            self.viewport.auto_scroll = False
            return True
        elif key in (curses.KEY_END, ord("G")):
            self.viewport.scroll_to_end()
            return True
        elif key in (ord("c"), ord("C")):
            if self.runner and self.runner.is_running:
                self.runner.terminate()
                return True
        elif key in (ord("s"), ord("S")):
            self.branch_to_new_command_pane()
            return True
        elif key in (ord("r"), ord("R")):
            if not self.runner or not self.runner.is_running:
                if self.current_form:
                    self._start_execution()
                    return True
        elif key in (10, 13):
            if not self.runner or not self.runner.is_running:
                if self.current_form:
                    self.navigation.current_screen = TuiScreenMode.FORM
                    return True
                else:
                    self.navigation.current_screen = TuiScreenMode.MENU
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

    def _get_active_hotkey_badges(self, *, is_scrollable: bool = False) -> List[str]:
        """Return complete list of active hotkey badges for the current screen."""
        if self.is_confirming_quit:
            return [
                "Are you sure you want to exit?",
                "[y] Yes",
                "[n] No",
                "[Esc] Cancel",
            ]

        has_multiple_panes = len(self.workspace.panes) > 1

        badge_map = {
            TelemetryDisplayMode.FULL: "[t] Telemetry: Full",
            TelemetryDisplayMode.COMPACT: "[t] Telemetry: Compact",
            TelemetryDisplayMode.HIDDEN: "[t] Telemetry: Off",
        }
        telemetry_badge = badge_map.get(self.telemetry_mode, "[t] Telemetry: Full")

        if self.screen_mode == TuiScreenMode.RUNNING:
            if self.runner and self.runner.is_running:
                badges = ["[c] Cancel", "[s] Branch", "[p] Panes", telemetry_badge]
                if has_multiple_panes:
                    badges.append("[[]/[]] Prev/Next")
                badges.append("[Shift+Esc] New Pane")
                if is_scrollable:
                    badges.append("[↑/↓] Scroll")
                badges.extend(["[q] Quit", "[Q] Force Quit"])
                return badges
            else:
                badges = [
                    "[q] Quit",
                    "[Q] Force Quit",
                    "[Esc] Back",
                    "[p] Panes",
                    telemetry_badge,
                ]
                if has_multiple_panes:
                    badges.append("[[]/[]] Prev/Next")
                badges.extend(["[s] Branch", "[r] Re-run"])
                for action in self.post_run_actions:
                    if action.predicate is None or action.predicate(self):
                        badges.append(action.label)
                if is_scrollable:
                    badges.append("[↑/↓] Scroll")
                badges.append("[Enter] Return")
                return badges

        elif self.screen_mode == TuiScreenMode.FORM:
            if self._is_widget_editing():
                return ["[Enter] Done", "[Esc] Cancel", "[Typing] Input"]

            run_focused = self.form_cursor == len(self.form_widgets)
            prev_focused = self.form_cursor == len(self.form_widgets) + 1
            back_focused = self.form_cursor == len(self.form_widgets) + 2

            if run_focused:
                action_badge = "[Enter] Run Command"
            elif prev_focused:
                action_badge = "[Enter] Preview CLI"
            elif back_focused:
                action_badge = "[Enter] Back to Menu"
            else:
                action_badge = "[Enter/Space] Edit"

            badges = [
                "[Ctrl+R] Run",
                "[↑/↓] Navigate",
                action_badge,
                "[Esc] Back",
                "[p] Panes",
                telemetry_badge,
                "[Shift+Esc] New Pane",
            ]
            if has_multiple_panes:
                badges.append("[[]/[]] Prev/Next")
            badges.extend(["[q] Quit", "[Q] Force Quit"])
            return badges

        elif self.screen_mode == TuiScreenMode.MENU:
            badges = [
                "[↑/↓] Navigate",
                "[Enter] Select",
                "[Esc] Back",
                "[p] Panes",
                telemetry_badge,
                "[Shift+Esc] New Pane",
            ]
            if has_multiple_panes:
                badges.append("[[]/[]] Prev/Next")
            badges.extend(["[q] Quit", "[Q] Force Quit"])
            return badges

        return [
            "[q] Quit",
            "[Q] Force Quit",
            "[Esc] Back",
            "[p] Panes",
            telemetry_badge,
        ]

    def render_tab_strip(self, width: int) -> str:
        """Render the top tab strip showing open panes and active focus."""
        tabs: List[str] = []
        for i, pane in enumerate(self.workspace.panes):
            idx = i + 1
            badge = pane.status_badge
            status_part = ""
            if badge == "FINISHED":
                status_part = " (done)"
            elif badge == "RUNNING":
                status_part = " (running)"
            elif badge == "CONFIG":
                status_part = " (editing)"
            elif badge == "CONSOLE":
                status_part = " (console)"

            if i == self.workspace.active_index:
                tabs.append(f"▶ [{idx}: {pane.title}{status_part}]")
            else:
                tabs.append(f"[{idx}: {pane.title}{status_part}]")

        tabs_str = "  ".join(tabs)
        hint = "[+ Shift+Esc]"

        prefix = "┌─ "
        suffix = "┐"
        full_content = f"{prefix}{tabs_str}  {hint} "
        if len(full_content) > width - 1:
            full_content = f"{prefix}{tabs_str} "
        if len(full_content) > width - 1:
            avail = max(0, width - 1 - len(prefix) - 1)
            full_content = f"{prefix}{tabs_str[:avail]} "

        return full_content.ljust(width - 1, "─") + suffix

    def render_pane_manager(self, *, height: int = 24, width: int = 80) -> List[str]:
        """Render the 30/70 split Pane Tree & Preview Manager overlay."""
        badges = ["[Enter] Switch", "[n] New Pane", "[d] Delete", "[D] Delete All"]
        if len(self.workspace.panes) > 1:
            badges.append("[↑/↓] Select")
        badges.extend(["[PgUp/PgDn] Scroll", "[Esc] Close"])
        footer_lines = format_hotkey_footer(badges, width)
        footer_count = len(footer_lines)

        lines: List[str] = []
        header = f"┌─ {self.title} Pane Manager ".ljust(width - 1, "─") + "┐"
        lines.append(header)

        inner_height = max(1, height - 1 - footer_count)

        if width < 60:
            content_w = max(10, width - 2)
            lines.append(
                f"│{' PANES (' + str(len(self.workspace.panes)) + ' Active)'.ljust(content_w)}│"
            )
            lines.append(f"├{'─' * content_w}┤")
            for i, p in enumerate(self.workspace.panes):
                ptr = "▶ " if i == self.manager_cursor else "  "
                lines.append(
                    f"│{(' ' + ptr + str(i + 1) + '. ' + p.title)[:content_w].ljust(content_w)}│"
                )
                lines.append(
                    f"│{('     ' + p.status_badge)[:content_w].ljust(content_w)}│"
                )
            while len(lines) < height - footer_count:
                lines.append(f"│{' ' * content_w}│")
        else:
            left_w = max(18, int(width * 0.30))
            right_w = max(18, width - 3 - left_w)

            total_panes = len(self.workspace.panes)
            if self.manager_cursor >= total_panes:
                self.manager_cursor = max(0, total_panes - 1)
            target_pane = (
                self.workspace.panes[self.manager_cursor]
                if total_panes > 0
                else self.workspace.active_pane
            )

            col1_title = f" PANES ({total_panes} Active)"
            col2_title = (
                f" PREVIEW: Pane {self.manager_cursor + 1} ({target_pane.title})"
            )

            lines.append(
                f"│{col1_title[:left_w].ljust(left_w)}│{col2_title[:right_w].ljust(right_w)}│"
            )
            lines.append(f"├{'─' * left_w}┼{'─' * right_w}┤")

            left_items: List[str] = []
            for i, p in enumerate(self.workspace.panes):
                ptr = "▶ " if i == self.manager_cursor else "  "
                left_items.append(f" {ptr}{i + 1}. {p.title}")
                left_items.append(f"     {p.status_badge}")
                left_items.append("")

            right_items: List[str] = []
            status_text = f"Status: {target_pane.status_badge}"
            if target_pane.runner and hasattr(target_pane.runner, "elapsed_seconds"):
                status_text += (
                    f"  |  Elapsed: {target_pane.runner.elapsed_seconds:.1f}s"
                )
            right_items.append(f"   {status_text}")
            right_items.append("")

            target_mode = (
                target_pane.navigation.current_screen
                if target_pane.navigation
                else target_pane.screen_mode
            )
            if target_pane.runner:
                raw_lines = target_pane.runner.lines
                visible = target_pane.viewport.get_visible_lines(
                    raw_lines,
                    height=max(1, inner_height - 3),
                    width=max(10, right_w - 4),
                )
                for vline in visible:
                    right_items.append(f"   {vline}")
            elif target_mode == TuiScreenMode.FORM and target_pane.current_form:
                form = target_pane.current_form
                right_items.append(f"   Command: {form.command.name}")
                right_items.append("   Arguments:")
                for arg in form.command.arguments:
                    val = form.get_value(arg.dest)
                    right_items.append(f"     --{arg.dest}: {val}")
            elif target_mode == TuiScreenMode.MENU:
                cmd = self.root_command
                for crumb in target_pane.navigation.path:
                    if crumb in cmd.subcommands:
                        cmd = cmd.subcommands[crumb]
                if cmd.subcommands:
                    right_items.append(f"   Menu: {target_pane.title}")
                    right_items.append("   Subcommands:")
                    for sub_name, sub_cmd in cmd.subcommands.items():
                        desc = (
                            f" - {sub_cmd.description}" if sub_cmd.description else ""
                        )
                        right_items.append(f"     • {sub_name}{desc}")
                else:
                    visible = target_pane.viewport.get_visible_lines(
                        [],
                        height=max(1, inner_height - 3),
                        width=max(10, right_w - 4),
                    )
                    for vline in visible:
                        right_items.append(f"   {vline}")
            else:
                visible = target_pane.viewport.get_visible_lines(
                    [], height=max(1, inner_height - 3), width=max(10, right_w - 4)
                )
                for vline in visible:
                    right_items.append(f"   {vline}")

            content_rows = max(1, height - 4 - footer_count)
            for r in range(content_rows):
                l_text = left_items[r] if r < len(left_items) else ""
                r_text = right_items[r] if r < len(right_items) else ""
                lines.append(
                    f"│{l_text[:left_w].ljust(left_w)}│{r_text[:right_w].ljust(right_w)}│"
                )

            lines.append(f"└{'─' * left_w}┴{'─' * right_w}┘")

        lines.extend(footer_lines)
        return lines[:height]

    def render_new_pane_choice_dialog(
        self, *, height: int = 24, width: int = 80
    ) -> List[str]:
        """Render modal dialog prompting choice between Command Menu and Console."""
        badges = [
            "[1] New Command (Menu)",
            "[2] Interactive Shell Console",
            "[Esc] Cancel",
        ]
        footer_lines = format_hotkey_footer(badges, width)
        inner_height = max(1, height - 1 - len(footer_lines))

        lines: List[str] = []
        header = f"┌─ {self.title} Pane Manager ".ljust(width - 1, "─") + "┐"
        lines.append(header)
        content_lines = [
            "",
            "  Create New Workspace Pane:",
            "",
            "    [1] New Command (Menu)",
            "    [2] Interactive Shell Console",
            "",
            "  [ Press 1 or 2 to choose, or Esc to cancel ]",
        ]
        while len(content_lines) < inner_height:
            content_lines.append("")
        lines.extend(content_lines[:inner_height])
        lines.extend(footer_lines)
        return lines[:height]

    def render_console_pane(self, *, height: int = 24, width: int = 80) -> List[str]:
        """Render interactive shell console inside the pane viewport."""
        telemetry_lines = self._format_telemetry_lines(width)
        pane = self.workspace.active_pane
        runner = pane.runner
        lines: List[str] = list(telemetry_lines)
        if len(self.workspace.panes) > 1:
            header = self.render_tab_strip(width)
        else:
            header = f"┌─ {self.title} > Shell Console ".ljust(width - 1, "─") + "┐"
        lines.append(header)

        badge_map = {
            TelemetryDisplayMode.FULL: "[t] Telemetry: Full",
            TelemetryDisplayMode.COMPACT: "[t] Telemetry: Compact",
            TelemetryDisplayMode.HIDDEN: "[t] Telemetry: Off",
        }
        telemetry_badge = badge_map.get(self.telemetry_mode, "[t] Telemetry: Full")

        badges = [
            "[Enter] Execute",
            "[p] Panes",
            telemetry_badge,
            "[Shift+Esc] New Pane",
        ]
        if len(self.workspace.panes) > 1:
            badges.append("[[]/[]] Prev/Next")
        badges.extend(["[Esc] Panes", "[exit] Close"])
        footer_lines = format_hotkey_footer(badges, width)
        inner_height = max(1, height - len(telemetry_lines) - 1 - len(footer_lines))

        raw_lines = runner.lines if runner else []
        visible = pane.viewport.get_visible_lines(
            raw_lines, height=max(1, inner_height - 2), width=max(10, width - 4)
        )
        content_lines = [""]
        content_lines.extend(f"  {line}" for line in visible)
        while len(content_lines) < inner_height - 1:
            content_lines.append("")
        cwd = getattr(runner, "cwd", os.getcwd()) if runner else os.getcwd()
        inp = getattr(runner, "input_buffer", "") if runner else ""
        content_lines.append(f"  [{cwd}]> {inp}█")
        lines.extend(content_lines[:inner_height])

        lines.extend(footer_lines)
        return lines[:height]

    def _update_telemetry(self) -> None:
        if self.sampler:
            sys_s, proc_s = self.sampler.get_snapshots()
            if sys_s is not None:
                self._last_sys_stats = sys_s
            if proc_s is not None:
                self._last_proc_stats = proc_s

    def _format_telemetry_lines(self, width: int) -> List[str]:
        self._update_telemetry()
        if self.telemetry_mode == TelemetryDisplayMode.HIDDEN:
            return []

        sys_s: Optional[Any] = self._last_sys_stats
        proc_s: Optional[Any] = self._last_proc_stats

        sep = "\x1b[90m│\x1b[0m"

        # 1. System telemetry formatting
        if sys_s:
            sys_cpu = _color_metric(f"{sys_s.cpu_pct:.0f}%", sys_s.cpu_pct)
            ram_gb = sys_s.ram_used_bytes / (1024**3)
            ram_tot = sys_s.ram_total_bytes / (1024**3)
            sys_ram_wide = (
                f"{_color_metric(f'{ram_gb:.1f} / {ram_tot:.1f} GB', sys_s.ram_pct)} "
                f"\x1b[90m({sys_s.ram_pct:.0f}%)\x1b[0m"
            )
            sys_ram_std = (
                f"{_color_metric(f'{ram_gb:.1f}G', sys_s.ram_pct)} "
                f"\x1b[90m({sys_s.ram_pct:.0f}%)\x1b[0m"
            )
            sys_ram_narrow = _color_metric(f"{sys_s.ram_pct:.0f}%", sys_s.ram_pct)

            if sys_s.gpu_load_pct is not None:
                vram_gb = (sys_s.gpu_mem_used_bytes or 0) / (1024**3)
                vram_tot = (sys_s.gpu_mem_total_bytes or 0) / (1024**3)
                temp_str = f" {sys_s.gpu_temp_c:.0f}°C" if sys_s.gpu_temp_c else ""
                gpu_name = f"{sys_s.gpu_name}: " if sys_s.gpu_name else ""
                gpu_load_col = _color_metric(
                    f"{sys_s.gpu_load_pct:.0f}%", sys_s.gpu_load_pct
                )
                sys_gpu_wide = f"{gpu_load_col} \x1b[90m({gpu_name}{vram_gb:.1f} / {vram_tot:.1f} GB{temp_str})\x1b[0m"
                sys_gpu_std = (
                    f"{gpu_load_col} \x1b[90m({vram_gb:.1f}G{temp_str})\x1b[0m"
                )
                sys_gpu_narrow = gpu_load_col
            else:
                sys_gpu_wide = sys_gpu_std = sys_gpu_narrow = "\x1b[90mN/A\x1b[0m"
        else:
            sys_cpu = "\x1b[90m—\x1b[0m"
            sys_ram_wide = sys_ram_std = sys_ram_narrow = "\x1b[90m—\x1b[0m"
            sys_gpu_wide = sys_gpu_std = sys_gpu_narrow = "\x1b[90m—\x1b[0m"

        # 2. Process telemetry formatting
        if proc_s and proc_s.is_active:
            p_cpu_text = (
                f"{proc_s.cpu_pct:.1f}%"
                if proc_s.cpu_pct < 10.0
                else f"{proc_s.cpu_pct:.0f}%"
            )
            p_cpu_col = _color_metric(p_cpu_text, proc_s.cpu_pct)
            raw_core = getattr(proc_s, "cpu_raw_pct", 0.0)
            if raw_core >= 1.0:
                p_cpu_wide = f"{p_cpu_col} \x1b[90m({raw_core:.0f}% core)\x1b[0m"
            else:
                p_cpu_wide = p_cpu_col
            p_cpu_std = p_cpu_col
            p_cpu_narrow = p_cpu_col

            if proc_s.memory_rss_bytes < 1024**3:
                rss_mb = proc_s.memory_rss_bytes / (1024**2)
                p_ram_wide = (
                    f"{_color_metric(f'{rss_mb:.1f} MB', proc_s.memory_pct)} "
                    f"\x1b[90m({proc_s.memory_pct:.1f}%)\x1b[0m"
                )
                p_ram_std = _color_metric(f"{rss_mb:.0f}M", proc_s.memory_pct)
                p_ram_narrow = _color_metric(f"{rss_mb:.0f}M", proc_s.memory_pct)
            else:
                p_ram_gb = proc_s.memory_rss_bytes / (1024**3)
                p_ram_wide = (
                    f"{_color_metric(f'{p_ram_gb:.2f} GB', proc_s.memory_pct)} "
                    f"\x1b[90m({proc_s.memory_pct:.0f}%)\x1b[0m"
                )
                p_ram_std = _color_metric(f"{p_ram_gb:.1f}G", proc_s.memory_pct)
                p_ram_narrow = _color_metric(f"{p_ram_gb:.1f}G", proc_s.memory_pct)

            p_gpu = (
                _color_metric(f"{proc_s.gpu_load_pct:.0f}%", proc_s.gpu_load_pct)
                if proc_s.gpu_load_pct is not None
                else "\x1b[90m—\x1b[0m"
            )
            p_info = f"\x1b[90m(pid: {proc_s.pid} {proc_s.name})\x1b[0m"
            p_info_short = f"\x1b[90m({proc_s.name})\x1b[0m"
        elif proc_s and not proc_s.is_active:
            p_cpu_wide = p_cpu_std = p_cpu_narrow = "\x1b[90m0%\x1b[0m"
            p_ram_wide = p_ram_std = p_ram_narrow = "\x1b[90m0.0M\x1b[0m"
            p_gpu = "\x1b[90m—\x1b[0m"
            p_info = "\x1b[90m(done)\x1b[0m"
            p_info_short = "\x1b[90m(done)\x1b[0m"
        else:
            p_cpu_wide = p_cpu_std = p_cpu_narrow = "\x1b[90m—\x1b[0m"
            p_ram_wide = p_ram_std = p_ram_narrow = "\x1b[90m—\x1b[0m"
            p_gpu = "\x1b[90m—\x1b[0m"
            p_info = "\x1b[90m[idle]\x1b[0m"
            p_info_short = "\x1b[90m[idle]\x1b[0m"

        if self.telemetry_mode == TelemetryDisplayMode.FULL:
            lbl_sys = "\x1b[1;36mSystem:\x1b[0m"
            lbl_act = "\x1b[1;32mActive:\x1b[0m"
            lbl_cpu = "\x1b[37mCPU\x1b[0m"
            lbl_ram = "\x1b[37mRAM\x1b[0m"
            lbl_gpu = "\x1b[37mGPU\x1b[0m"

            if width >= 100:
                line1_content = f"{lbl_sys} {lbl_cpu} {sys_cpu} {sep} {lbl_ram} {sys_ram_wide} {sep} {lbl_gpu} {sys_gpu_wide}"
                line2_content = f"{lbl_act} {lbl_cpu} {p_cpu_wide} {sep} {lbl_ram} {p_ram_wide} {sep} {lbl_gpu} {p_gpu} {p_info}"
            elif width >= 80:
                line1_content = f"{lbl_sys} {lbl_cpu} {sys_cpu} {sep} {lbl_ram} {sys_ram_std} {sep} {lbl_gpu} {sys_gpu_std}"
                line2_content = f"{lbl_act} {lbl_cpu} {p_cpu_std} {sep} {lbl_ram} {p_ram_std} {sep} {lbl_gpu} {p_gpu} {p_info_short}"
            else:
                lbl_sys_nar = "\x1b[1;36mSYS:\x1b[0m"
                lbl_act_nar = "\x1b[1;32mAPP:\x1b[0m"
                line1_content = f"{lbl_sys_nar} \x1b[37mC\x1b[0m {sys_cpu} \x1b[37mM\x1b[0m {sys_ram_narrow} \x1b[37mG\x1b[0m {sys_gpu_narrow}"
                line2_content = f"{lbl_act_nar} \x1b[37mC\x1b[0m {p_cpu_narrow} \x1b[37mM\x1b[0m {p_ram_narrow} \x1b[37mG\x1b[0m {p_gpu}"

            bar1 = _build_telemetry_bar("┌─ ", line1_content, "┐", "─", width)
            bar2 = _build_telemetry_bar("│  ", line2_content, "│", "─", width)
            return [bar1, bar2]

        elif self.telemetry_mode == TelemetryDisplayMode.COMPACT:
            if width >= 70:
                content = (
                    f"\x1b[37mCPU:\x1b[0m {sys_cpu} \x1b[90m(proc {p_cpu_std})\x1b[0m {sep} "
                    f"\x1b[37mRAM:\x1b[0m {sys_ram_std} \x1b[90m(proc {p_ram_std})\x1b[0m {sep} "
                    f"\x1b[37mGPU:\x1b[0m {sys_gpu_std} \x1b[90m(proc {p_gpu})\x1b[0m"
                )
            else:
                content = (
                    f"\x1b[37mC:\x1b[0m {sys_cpu} \x1b[90m({p_cpu_narrow})\x1b[0m {sep} "
                    f"\x1b[37mM:\x1b[0m {sys_ram_narrow} \x1b[90m({p_ram_narrow})\x1b[0m {sep} "
                    f"\x1b[37mG:\x1b[0m {sys_gpu_narrow}"
                )

            bar = _build_telemetry_bar("┌─ ", content, "┐", "─", width)
            return [bar]

        return []

    def render_virtual_screen(self, height: int = 24, width: int = 80) -> List[str]:
        """Render text representation of the screen for unit testing and display."""
        if self.is_confirming_layout_save:
            prompt = ["Save the current pane layout before exiting?", "[y] Save and exit", "[n] Exit without saving"]
            if self.last_message.startswith("Could not save"):
                prompt.insert(0, self.last_message)
            return self._render_simple_dialog("Save Pane Layout", prompt, height, width)
        if self.is_showing_output_capture:
            if self.is_confirming_output_overwrite:
                prompt = ["The target file already exists.", str(Path(self.output_capture_directory) / self.output_capture_filename), "[y] Overwrite", "[n] Cancel"]
                return self._render_simple_dialog("Confirm Output File", prompt, height, width)
            prompt = [
                "Directory (Tab to switch):",
                f"  {'▶ ' if self.output_capture_field == 0 else '  '}{self.output_capture_directory}",
                "Filename:",
                f"  {'▶ ' if self.output_capture_field == 1 else '  '}{self.output_capture_filename}",
                "[Enter] Continue / Save    [Esc] Cancel",
            ]
            return self._render_simple_dialog("Capture Pane Output", prompt, height, width)
        if getattr(self, "is_showing_new_pane_choice", False):
            return self.render_new_pane_choice_dialog(height=height, width=width)

        if getattr(self, "is_pane_manager_open", False):
            return self.render_pane_manager(height=height, width=width)

        if self.workspace.active_pane.pane_type == PaneType.CONSOLE:
            return self.render_console_pane(height=height, width=width)

        if getattr(self, "is_showing_preview", False):
            lines = []
            path_str = " > ".join([self.title] + self.navigation.path + ["Preview"])
            header = f"┌─ {path_str} (CLI Command Preview) ".ljust(width - 1, "─") + "┐"
            lines.append(header)
            footer_lines = format_hotkey_footer(
                ["[Esc/Enter/Space] Close Preview"], width
            )
            inner_height = max(1, height - 1 - len(footer_lines))
            cwd = os.getcwd()
            runner_str = (
                " ".join(self.executable) if self.executable else sys.executable
            )
            if self.current_form:
                argv = self._build_current_argv()
                if argv is None:
                    cmd_str = self.last_message
                    full_invocation = cmd_str
                else:
                    exec_len = len(self.executable) if self.executable else 0
                    cmd_tokens = argv[exec_len:] if exec_len > 0 else argv
                    cmd_str = " ".join(cmd_tokens)
                    full_invocation = " ".join(argv)
            else:
                cmd_str = ""
                full_invocation = runner_str

            content_lines = [
                "",
                "  Working Directory:",
                f"    {cwd}",
                "",
                "  Runner:",
                f"    {runner_str}",
                "",
                "  Command:",
                f"    {cmd_str}",
                "",
                "  Full Invocation:",
                f"    {full_invocation}",
                "",
                "  [ Press Enter, Space, or Esc to close ]",
            ]
            while len(content_lines) < inner_height:
                content_lines.append("")
            lines.extend(content_lines[:inner_height])
            lines.extend(footer_lines)
            return lines[:height]

        lines = []
        telemetry_lines = self._format_telemetry_lines(width)
        lines.extend(telemetry_lines)

        if len(self.workspace.panes) > 1:
            header = self.render_tab_strip(width)
        else:
            path_str = " > ".join([self.title] + self.navigation.path)
            header = f"┌─ {path_str} ".ljust(width - 1, "─") + "┐"
        lines.append(header)

        is_scrollable = False
        if self.screen_mode == TuiScreenMode.RUNNING:
            runner = self.runner
            raw_lines = runner.lines if runner else []
            visible_width = max(10, width - 4)
            _, _, total_l = self.viewport.get_scroll_bounds(
                raw_lines,
                height=max(1, height - len(telemetry_lines) - 6),
                width=visible_width,
            )
            is_scrollable = total_l > max(1, height - len(telemetry_lines) - 6)

        badges = self._get_active_hotkey_badges(is_scrollable=is_scrollable)
        if width >= 120:
            compact_labels = {
                "[Q] Force Quit": "[Q] Force",
                "[Esc] Back": "[Esc]",
                "[t] Telemetry: Full": "[t] Telemetry",
                "[t] Telemetry: Compact": "[t] Telemetry",
                "[t] Telemetry: Off": "[t] Telemetry",
                "[↑/↓] Scroll": "[↑/↓]",
            }
            badges = [compact_labels.get(badge, badge) for badge in badges]
            badges.append("[Ctrl+S] Save / [Ctrl+O] File")
        else:
            badges.extend(["[Ctrl+S] Save Layout", "[Ctrl+O] Capture Output"])
        if self.last_message:
            badges.append(self.last_message)
        footer_lines = format_hotkey_footer(badges, width)
        inner_height = max(1, height - len(telemetry_lines) - 1 - len(footer_lines))

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
            run_focused = self.form_cursor == len(self.form_widgets)
            prev_focused = self.form_cursor == len(self.form_widgets) + 1
            back_focused = self.form_cursor == len(self.form_widgets) + 2

            btn_run = "▶ [ Run Command ]" if run_focused else "  [ Run Command ]"
            btn_prev = "▶ [ Preview CLI ]" if prev_focused else "  [ Preview CLI ]"
            btn_back = "▶ [ Back ]" if back_focused else "  [ Back ]"
            button_row = f"  {btn_run}   {btn_prev}   {btn_back}"

            content_lines = [
                "",
                f"  Configure arguments for: {cmd.prog or cmd.name}",
                f"  {button_row.strip()}",
                f"  {'─' * max(20, width - 6)}",
            ]
            for idx, widget in enumerate(self.form_widgets):
                is_focused = idx == self.form_cursor
                for w_line in widget.render_lines(width - 4, is_focused):
                    content_lines.append("  " + w_line)

            content_lines.append("")
            content_lines.append(button_row)

            if self.current_form:
                argv = self._build_current_argv()
                exec_len = len(self.executable) if self.executable else 0
                runner_str = (
                    " ".join(self.executable) if self.executable else sys.executable
                )
                if argv is None:
                    cmd_str = self.last_message
                else:
                    cmd_tokens = argv[exec_len:] if exec_len > 0 else argv
                    cmd_str = " ".join(cmd_tokens)
                cwd = os.getcwd()

                content_lines.append("")
                content_lines.append(f"  Working Dir: {cwd}")
                content_lines.append(f"  Runner:      {runner_str}")
                content_lines.append(f"  Command:     {cmd_str}")

            show_inspector = inner_height >= 14
            inspector_lines: List[str] = []
            if show_inspector:
                border_w = max(20, width - 4)
                if self.form_cursor < len(self.form_widgets):
                    active_arg = self.form_widgets[self.form_cursor].arg
                    flags_str = (
                        ", ".join(active_arg.flags)
                        if active_arg.flags
                        else active_arg.dest
                    )
                    title = f" Option: {flags_str} "
                    h_top = ("  ┌─" + title)[: border_w - 1].ljust(
                        border_w - 1, "─"
                    ) + "┐"
                    help_str = active_arg.help or "(No description provided)"
                    h_help = (
                        f"  │ Help:    {help_str}"[: border_w - 1].ljust(border_w - 1)
                        + "│"
                    )
                    choices_part = (
                        f"Choices: {', '.join(str(c) for c in active_arg.choices)}"
                        if active_arg.choices
                        else "Choices: any"
                    )
                    def_part = (
                        f"Default: {active_arg.default}"
                        if active_arg.default is not None
                        else "Default: None"
                    )
                    h_choices = (
                        f"  │ {choices_part}  │  {def_part}"[: border_w - 1].ljust(
                            border_w - 1
                        )
                        + "│"
                    )
                    req_label = "Required" if active_arg.required else "Optional"
                    nargs_label = (
                        f" (nargs: {active_arg.nargs})" if active_arg.nargs else ""
                    )
                    type_label = (
                        f"Type: {active_arg.action_type}{nargs_label} [{req_label}]"
                    )
                    h_type = (
                        f"  │ {type_label}"[: border_w - 1].ljust(border_w - 1) + "│"
                    )
                    h_bot = "  └" + ("─" * (border_w - 2)) + "┘"
                    inspector_lines = [h_top, h_help, h_choices, h_type, h_bot]
                elif run_focused:
                    h_top = ("  ┌─ Action: Run Command ")[: border_w - 1].ljust(
                        border_w - 1, "─"
                    ) + "┐"
                    h_desc = (
                        "  │ Execute this command in the background with the configured arguments."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_key = (
                        "  │ Shortcut: Enter or Space on this button to start execution."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_hint = (
                        "  │ Process output will stream live in the running viewport."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_bot = "  └" + ("─" * (border_w - 2)) + "┘"
                    inspector_lines = [h_top, h_desc, h_key, h_hint, h_bot]
                elif prev_focused:
                    h_top = ("  ┌─ Action: Preview CLI ")[: border_w - 1].ljust(
                        border_w - 1, "─"
                    ) + "┐"
                    h_desc = (
                        "  │ View the exact command line invocation string and tokens."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_key = (
                        "  │ Shortcut: Enter or Space on this button."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_hint = (
                        "  │ Safe view mode; does not start any subprocess."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_bot = "  └" + ("─" * (border_w - 2)) + "┘"
                    inspector_lines = [h_top, h_desc, h_key, h_hint, h_bot]
                elif back_focused:
                    h_top = ("  ┌─ Action: Back ")[: border_w - 1].ljust(
                        border_w - 1, "─"
                    ) + "┐"
                    h_desc = (
                        "  │ Return to the previous menu or subcommand list."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_key = (
                        "  │ Shortcut: Enter or Space on this button, or press Esc."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_hint = (
                        "  │ Discards unsaved configuration changes."[
                            : border_w - 1
                        ].ljust(border_w - 1)
                        + "│"
                    )
                    h_bot = "  └" + ("─" * (border_w - 2)) + "┘"
                    inspector_lines = [h_top, h_desc, h_key, h_hint, h_bot]

            form_height = inner_height - len(inspector_lines)
            if len(content_lines) > form_height:
                focused_line_idx = 0
                for i, line in enumerate(content_lines):
                    if "▶" in line:
                        focused_line_idx = i
                        break
                half_h = form_height // 2
                start_idx = max(
                    0, min(focused_line_idx - half_h, len(content_lines) - form_height)
                )
                visible_form_lines = content_lines[start_idx : start_idx + form_height]
            else:
                visible_form_lines = list(content_lines)
                while len(visible_form_lines) < form_height:
                    visible_form_lines.append("")
            lines.extend(visible_form_lines[:form_height])
            if inspector_lines:
                lines.extend(inspector_lines)

        elif self.screen_mode == TuiScreenMode.RUNNING:
            runner = self.runner
            if runner and getattr(runner, "restored", False):
                status_text = "RESTORED OUTPUT  |  Process was not restarted"
            elif runner and runner.is_running:
                status_text = f"RUNNING  |  Elapsed: {runner.elapsed_seconds:.1f}s"
            elif runner and runner.exit_code == 0:
                status_text = (
                    f"FINISHED (Success)  |  Elapsed: {runner.elapsed_seconds:.1f}s"
                )
            else:
                code = runner.exit_code if runner else -1
                status_text = f"FAILED (exit code {code})  |  Elapsed: {runner.elapsed_seconds if runner else 0:.1f}s"

            raw_lines = runner.lines if runner else []
            visible_height = max(1, inner_height - 3)
            visible_width = max(10, width - 4)
            start_l, end_l, total_l = self.viewport.get_scroll_bounds(
                raw_lines, height=visible_height, width=visible_width
            )
            scroll_info = ""
            if total_l > visible_height:
                scroll_info = f"  |  Lines {start_l}-{end_l} of {total_l} (↑/↓/PgUp/PgDn to scroll)"

            content_lines = [
                f"  Status: {status_text}{scroll_info}",
                "",
            ]
            visible = self.viewport.get_visible_lines(
                raw_lines, height=visible_height, width=visible_width
            )
            content_lines.extend(f"  {line}" for line in visible)
            while len(content_lines) < inner_height:
                content_lines.append("")
            lines.extend(content_lines[:inner_height])

        lines.extend(footer_lines)
        return lines[:height]

    def _render_simple_dialog(self, title: str, content: List[str], height: int, width: int) -> List[str]:
        border_w = max(24, min(width - 2, 80))
        lines = [f"┌─ {title} ".ljust(border_w - 1, "─") + "┐"]
        inner_width = border_w - 4
        lines.extend(f"│  {line[:inner_width].ljust(inner_width)}  │" for line in content)
        lines.append("└" + "─" * (border_w - 2) + "┘")
        return lines[:height]

    def close(self) -> None:
        """Cleanly terminate runners, close output captures, and stop telemetry."""
        self.workspace.terminate_all()
        for pane in self.workspace.panes:
            self._close_output_capture(pane)
        if self.runner and self.runner.is_running:
            self.runner.terminate()
        if self.sampler is not None:
            self.sampler.stop()

    def __enter__(self) -> CliTuiApp:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            if getattr(self, "sampler", None) is not None:
                self.sampler.stop()
        except Exception:
            pass

    def run(self) -> int:
        """Run the interactive curses TUI."""
        try:
            return curses.wrapper(self._curses_loop)
        except KeyboardInterrupt:
            self.close()
            return 0
        finally:
            self.close()

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
            curses.init_pair(5, curses.COLOR_MAGENTA, -1)
            curses.init_pair(6, curses.COLOR_BLUE, -1)
            curses.init_pair(7, curses.COLOR_WHITE, -1)

        while not self.is_terminated:
            max_y, max_x = stdscr.getmaxyx()
            lines = self.render_virtual_screen(height=max_y, width=max_x)
            stdscr.erase()
            for y, line in enumerate(lines[:max_y]):
                addstr_ansi(stdscr, y, 0, line, max_x)
            stdscr.refresh()

            try:
                ch = stdscr.getch()
                if ch != -1:
                    self.process_key(ch)
            except curses.error:
                pass

        self.close()
        return 0
