"""
Interactive menu-driven Terminal User Interface (TUI) for the scheduler module.
Navigable via arrow keys, with $EDITOR integration and orphaned task warnings.
"""
from __future__ import annotations

import curses
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from script_logging import RunRecord

from .analytics import activity_cells, expected_daily_counts, punctuality, task_expected_counts, window_stats
from .models import Schedule, ScheduleTiming, ShellEnvironment, Task, TimingType
from .service import SchedulerService
from . import windows_task
from .readiness import get_setup_state
from .timing import (
    calculate_next_run,
    normalize_days,
    parse_interval_string,
)


class GoHome(Exception):
    """Unwind nested TUI workflows to the root menu."""


@dataclass(frozen=True)
class DetailRow:
    text: str
    action: Optional[tuple[str, Any]] = None
    graph_states: Optional[List[Optional[str]]] = None


HOME_KEY = 0x1FFF


class SchedulerTUI:
    """Curses-based interactive Terminal User Interface with arrow-key navigation."""

    def __init__(self, service: SchedulerService, stdscr: Any) -> None:
        self.service = service
        self.storage = service.storage
        self.stdscr = stdscr

        # Initialize curses settings
        curses.curs_set(0)
        self.stdscr.keypad(True)
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)    # Highlight
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # Success / Active
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)     # Error / Warning
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Header / Notice
        curses.init_pair(5, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Info
        if hasattr(curses, "define_key"):
            # Extended terminal keyboards can report Shift+Esc distinctly.
            for sequence in ("\x1b[27;2;27~", "\x1b[27;2u"):
                try:
                    curses.define_key(sequence, HOME_KEY)
                except curses.error:
                    pass

    def _draw_header(self, title: str) -> None:
        """Render standard top header and separator."""
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        bar_text = f"  SCHEDULER TUI  ::  {title.upper()}  "
        self.stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addstr(0, 0, bar_text[: width - 1])
        self.stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addstr(1, 0, "=" * (width - 1))

    def _draw_footer(self, hints: str = "Up/Down: Navigate | Enter: Select | Esc: Back | H: Home") -> None:
        """Render bottom status line."""
        height, width = self.stdscr.getmaxyx()
        if height > 2:
            self.stdscr.addstr(height - 2, 0, "-" * (width - 1))
            self.stdscr.attron(curses.color_pair(5))
            self.stdscr.addstr(height - 1, 0, f" {hints}"[: width - 1])
            self.stdscr.attroff(curses.color_pair(5))

    def select_menu(
        self,
        title: str,
        options: List[str],
        footer_hints: Optional[str] = None,
        warning_lines: Optional[List[str]] = None,
    ) -> int:
        """
        Render an arrow-key navigable menu and return selected index.
        Returns -1 on Esc or 'q'.
        """
        current_idx = 0
        top_idx = 0
        if not options:
            options = ["(No items)"]
        while True:
            self._draw_header(title)
            if footer_hints:
                self._draw_footer(footer_hints)
            else:
                self._draw_footer()

            height, width = self.stdscr.getmaxyx()
            start_y = 3
            if warning_lines:
                self.stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
                self.stdscr.addstr(2, 2, "!!! SCHEDULER SETUP REQUIRED !!!"[: width - 4])
                self.stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
                for offset, line in enumerate(warning_lines[: max(0, height - 12)]):
                    self.stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
                    self.stdscr.addstr(4 + offset, 2, line[: width - 4])
                    self.stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
                start_y = 5 + min(len(warning_lines), max(0, height - 12))
            visible_count = max(1, height - start_y - 3)
            top_idx = max(0, min(top_idx, max(0, len(options) - visible_count)))
            if current_idx < top_idx:
                top_idx = current_idx
            elif current_idx >= top_idx + visible_count:
                top_idx = current_idx - visible_count + 1

            for row_offset, i in enumerate(range(top_idx, min(len(options), top_idx + visible_count))):
                opt = options[i]
                y = start_y + row_offset
                if i == current_idx:
                    self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                    self.stdscr.addstr(y, 2, f" > {opt:<{width - 6}} "[: width - 4])
                    self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                else:
                    self.stdscr.addstr(y, 2, f"   {opt}"[: width - 4])

            self.stdscr.refresh()
            key = self.stdscr.getch()

            if key in (curses.KEY_UP, ord("k")):
                current_idx = (current_idx - 1) % len(options)
            elif key in (curses.KEY_DOWN, ord("j")):
                current_idx = (current_idx + 1) % len(options)
            elif key == curses.KEY_PPAGE:
                current_idx = max(0, current_idx - visible_count)
            elif key == curses.KEY_NPAGE:
                current_idx = min(len(options) - 1, current_idx + visible_count)
            elif key == curses.KEY_HOME:
                current_idx = 0
            elif key == curses.KEY_END:
                current_idx = len(options) - 1
            elif key in (curses.KEY_ENTER, 10, 13):
                return current_idx
            elif key in (HOME_KEY, ord("H")):
                raise GoHome()
            elif key in (27, ord("q"), ord("b")):  # Escape or q or b
                return -1

    def prompt_text(self, title: str, prompt_label: str, default: str = "") -> Optional[str]:
        """Display a prompt line and read text input with editing support."""
        self._draw_header(title)
        self._draw_footer("Enter: Confirm | Esc: Cancel")
        height, width = self.stdscr.getmaxyx()

        curses.curs_set(1)
        self.stdscr.addstr(3, 2, f"{prompt_label}: ")
        buffer = list(default)
        prompt_x = 2 + len(prompt_label) + 2

        while True:
            # Display buffer
            line_str = "".join(buffer)
            self.stdscr.addstr(3, prompt_x, line_str + " " * 20)
            self.stdscr.move(3, prompt_x + len(buffer))
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (curses.KEY_ENTER, 10, 13):
                curses.curs_set(0)
                res = "".join(buffer).strip()
                return res if res else (default if default else None)
            elif key == 27:  # Esc
                curses.curs_set(0)
                return None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if buffer:
                    buffer.pop()
            elif 32 <= key <= 126:
                if len(buffer) < width - prompt_x - 5:
                    buffer.append(chr(key))

    def show_message(self, title: str, lines: List[str], is_error: bool = False) -> None:
        """Display a message screen and wait for user keypress."""
        self._draw_header(title)
        self._draw_footer("Press any key to continue...")
        height, width = self.stdscr.getmaxyx()

        color = curses.color_pair(3) if is_error else curses.color_pair(2)
        for i, line in enumerate(lines[: height - 6]):
            self.stdscr.attron(color)
            self.stdscr.addstr(3 + i, 2, line[: width - 4])
            self.stdscr.attroff(color)

        self.stdscr.refresh()
        if self.stdscr.getch() in (HOME_KEY, ord("H")):
            raise GoHome()

    def show_warning_confirm(self, title: str, lines: List[str]) -> bool:
        """Display warning lines and ask for explicit [Yes / Cancel] confirmation."""
        while True:
            self._draw_header(title)
            self._draw_footer("Up/Down: Select | Enter: Confirm | Esc: Cancel")
            height, width = self.stdscr.getmaxyx()

            # Warning banner
            self.stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
            self.stdscr.addstr(3, 2, "!!! WARNING !!!"[: width - 4])
            self.stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

            for i, line in enumerate(lines[: height - 10]):
                self.stdscr.addstr(5 + i, 2, line[: width - 4])

            options = ["Cancel (Safe)", "Proceed with Deletion (Destructive)"]
            opt_y = 5 + len(lines) + 2
            selected = 0

            while True:
                for idx, opt in enumerate(options):
                    if idx == selected:
                        self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                        self.stdscr.addstr(opt_y + idx, 4, f" > {opt} ")
                        self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                    else:
                        self.stdscr.addstr(opt_y + idx, 4, f"   {opt} ")
                self.stdscr.refresh()
                k = self.stdscr.getch()
                if k in (curses.KEY_UP, ord("k"), curses.KEY_DOWN, ord("j")):
                    selected = 1 - selected
                elif k in (curses.KEY_ENTER, 10, 13):
                    return selected == 1
                elif k in (HOME_KEY, ord("H")):
                    raise GoHome()
                elif k in (27, ord("q")):
                    return False

    def shell_out_editor(self, initial_code: str = "", suffix: str = ".sh") -> str:
        """Temporarily suspend curses, open external editor on code, and resume curses."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            for candidate in ("nvim", "vim", "nano", "code", "notepad"):
                if shutil.which(candidate):
                    editor = candidate
                    break
        if not editor:
            editor = "nano" if os.name != "nt" else "notepad"

        curses.endwin()
        with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(initial_code)
            temp_path = Path(f.name)

        try:
            subprocess.run([editor, str(temp_path)], check=False)
            with open(temp_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            # Re-initialize curses screen
            self.stdscr = curses.initscr()
            curses.curs_set(0)
            self.stdscr.keypad(True)
            self.stdscr.clear()

    # ─────────────────────────────────────────────────────────
    # Subsystem Workflows
    # ─────────────────────────────────────────────────────────

    def workflow_create_schedule(self) -> None:
        """Create schedule workflow."""
        name = self.prompt_text("Create Schedule", "Schedule Name")
        if not name:
            return
        if self.storage.get_schedule(name):
            self.show_message("Error", [f"Schedule '{name}' already exists."], is_error=True)
            return

        timing_opts = [
            "1. Daily (at specified time e.g. 00:00)",
            "2. Interval / Hourly (e.g. every 3 hours)",
            "3. Weekly (on specific weekday at time)",
            "4. Specific Days of Week (e.g. Mon, Wed, Fri)",
            "5. Monthly (1st of month at midnight)",
            "6. Custom 5-Field Cron Expression",
        ]
        choice = self.select_menu("Select Timing Recurrence", timing_opts)
        if choice == -1:
            return

        timing = ScheduleTiming()
        if choice == 0:  # Daily
            t_str = self.prompt_text("Daily Timing", "Enter time (HH:MM or midnight)", default="00:00") or "00:00"
            timing.timing_type = TimingType.DAILY.value
            timing.at_time = t_str
        elif choice == 1:  # Interval
            inv_str = self.prompt_text("Interval Timing", "Enter interval (e.g. 3h, 30m, 1d)", default="3h") or "3h"
            timing.timing_type = TimingType.INTERVAL.value
            timing.interval_seconds = parse_interval_string(inv_str)
        elif choice == 2:  # Weekly
            day_str = self.prompt_text("Weekly Timing", "Enter weekday (e.g. monday)", default="monday") or "monday"
            t_str = self.prompt_text("Weekly Timing", "Enter time (HH:MM)", default="00:00") or "00:00"
            timing.timing_type = TimingType.WEEKLY.value
            timing.days = normalize_days(day_str)
            timing.at_time = t_str
        elif choice == 3:  # Specific Days
            days_str = (
                self.prompt_text("Specific Days", "Enter days separated by comma", default="monday,wednesday,friday")
                or "monday,wednesday,friday"
            )
            t_str = self.prompt_text("Specific Days", "Enter time (HH:MM)", default="12:00") or "12:00"
            timing.timing_type = TimingType.SPECIFIC_DAYS.value
            timing.days = normalize_days(days_str)
            timing.at_time = t_str
        elif choice == 4:  # Monthly (1st of month at midnight)
            dom_str = self.prompt_text("Monthly Timing", "Day of month (1-31)", default="1") or "1"
            timing.timing_type = TimingType.MONTHLY.value
            timing.day_of_month = max(1, min(31, int(dom_str)))
            timing.at_time = "00:00"
        elif choice == 5:  # Cron
            cron_str = self.prompt_text("Cron Timing", "5-field expression", default="0 0 1 * *") or "0 0 1 * *"
            timing.timing_type = TimingType.CRON.value
            timing.cron_expression = cron_str

        # Catch-up choice
        cu_choice = self.select_menu("Catch-Up Feature", ["1. Enable (Run tasks ASAP if scheduled time missed)", "2. Disable"])
        catch_up = (cu_choice == 0)

        next_run = calculate_next_run(timing)
        schedule = Schedule(
            name=name,
            timing=timing,
            catch_up=catch_up,
            enabled=True,
            next_run_time=next_run.isoformat(),
        )
        self.storage.save_schedule(schedule)
        self.service.central_logger.log_schedule_create(schedule.name, timing.human_readable())

        self.show_message(
            "Schedule Created",
            [
                f"Schedule '{name}' created successfully!",
                f"Timing:   {timing.human_readable()}",
                f"Catch-up: {'Enabled' if catch_up else 'Disabled'}",
                f"Next Run: {next_run.isoformat()}",
            ],
        )

    def workflow_manage_schedules(self) -> None:
        """Edit / Delete schedule workflow."""
        while True:
            schedules = self.storage.list_schedules()
            if not schedules:
                self.show_message("Schedules", ["No schedules exist. Create one first."])
                return

            opts = []
            for s in schedules:
                attached = self.storage.get_attached_tasks(s.name)
                status = "Active" if s.enabled else "Disabled"
                opts.append(f"{s.name:<20} | {s.timing.human_readable():<28} | {status} | Tasks: {len(attached)}")

            idx = self.select_menu("Select Schedule to Edit/Delete", opts)
            if idx == -1:
                return

            selected_sched = schedules[idx]
            self._handle_single_schedule(selected_sched)

    def _handle_single_schedule(self, s: Schedule) -> None:
        """Manage individual schedule options: timing, catch-up, enable/disable, delete."""
        while True:
            attached = self.storage.get_attached_tasks(s.name)
            menu_opts = [
                f"1. View Attached Tasks ({len(attached)} task(s))",
                f"2. Toggle Status (Currently: {'Active' if s.enabled else 'Disabled'})",
                f"3. Toggle Catch-up (Currently: {'Enabled' if s.catch_up else 'Disabled'})",
                "4. Edit Timing Settings",
                "5. Trigger All Tasks in Schedule Now",
                "6. Delete Schedule",
            ]
            action = self.select_menu(f"Manage Schedule: {s.name}", menu_opts)
            if action == -1:
                return

            if action == 0:
                task_lines = [f"Attached Tasks for '{s.name}':"]
                for t in attached:
                    task_lines.append(f"  - {t.name} (env: {t.environment}, admin: {t.admin})")
                if not attached:
                    task_lines.append("  (No tasks attached)")
                self.show_message("Attached Tasks", task_lines)

            elif action == 1:
                s.enabled = not s.enabled
                self.storage.save_schedule(s)
                self.service.central_logger.log_schedule_edit(s.name, f"enabled={s.enabled}")

            elif action == 2:
                s.catch_up = not s.catch_up
                self.storage.save_schedule(s)
                self.service.central_logger.log_schedule_edit(s.name, f"catch_up={s.catch_up}")

            elif action == 3:
                new_at = self.prompt_text("Edit Time", "Enter new time (HH:MM)", default=s.timing.at_time)
                if new_at:
                    s.timing.at_time = new_at
                    s.next_run_time = calculate_next_run(s.timing).isoformat()
                    self.storage.save_schedule(s)
                    self.service.central_logger.log_schedule_edit(s.name, f"at_time={new_at}")
                    self.show_message("Updated", [f"Updated timing to: {s.timing.human_readable()}"])

            elif action == 4:
                results = self.service.execute_schedule(s.name)
                self.show_message("Executed", [f"Triggered {len(results)} task(s)."])

            elif action == 5:
                # Delete schedule check
                attached = self.storage.get_attached_tasks(s.name)
                if attached:
                    lines = [
                        f"Deleting schedule '{s.name}' will leave the following tasks ORPHANED:",
                    ]
                    for t in attached:
                        lines.append(f"  - {t.name}")
                    lines.append("")
                    lines.append("These tasks will become standalone and will no longer run on this schedule.")
                    proceed = self.show_warning_confirm("Confirm Schedule Deletion", lines)
                else:
                    proceed = self.show_warning_confirm(
                        "Confirm Schedule Deletion",
                        [f"Are you sure you want to delete schedule '{s.name}'?"],
                    )

                if proceed:
                    self.storage.delete_schedule(s.name, orphan_tasks=True)
                    self.service.central_logger.log_schedule_delete(s.name, [t.name for t in attached])
                    self.show_message("Deleted", [f"Schedule '{s.name}' deleted."])
                    return

    def workflow_create_task(self) -> None:
        """Create task workflow."""
        name = self.prompt_text("Create Task", "Task Name")
        if not name:
            return
        if self.storage.get_task(name):
            self.show_message("Error", [f"Task '{name}' already exists."], is_error=True)
            return

        # Select environment
        env_opts = [
            "1. terminal (Default Shell: Bash / Sh / Cmd)",
            "2. pwsh (PowerShell 7+ / Core)",
            "3. powershell (Windows PowerShell)",
        ]
        env_idx = self.select_menu("Select Shell Environment", env_opts)
        if env_idx == -1:
            return
        env_map = {0: ShellEnvironment.TERMINAL.value, 1: ShellEnvironment.PWSH.value, 2: ShellEnvironment.POWERSHELL.value}
        env = env_map.get(env_idx, ShellEnvironment.TERMINAL.value)

        # Admin toggle
        admin_idx = self.select_menu("Admin / Elevated Privileges", ["1. Non-Admin (Standard)", "2. Admin (Elevated Privileges)"])
        admin = (admin_idx == 1)

        # Script Code entry method
        code_opts = [
            "1. Compose in $EDITOR (e.g. Neovim, Nano, Vim)",
            "2. Enter Single/Multi-line Code Directly",
        ]
        code_idx = self.select_menu("Script Code Input Method", code_opts)
        code = ""
        suffix = ".ps1" if env in ("pwsh", "powershell") else ".sh"
        if code_idx == 0:
            code = self.shell_out_editor("#!/usr/bin/env sh\n# Write task commands below:\n", suffix=suffix)
        elif code_idx == 1:
            code = self.prompt_text("Task Command", "Enter command/code", default="echo 'Hello Scheduler'") or ""

        # Link to schedule
        schedules = self.storage.list_schedules()
        sched_opts = ["(None - Standalone Task)"] + [f"{s.name} ({s.timing.human_readable()})" for s in schedules]
        sc_idx = self.select_menu("Link to Schedule", sched_opts)
        linked_sched = schedules[sc_idx - 1].name if sc_idx > 0 else None

        task = Task(
            name=name,
            schedule_name=linked_sched,
            environment=env,
            admin=admin,
            code=code,
            enabled=True,
        )
        self.storage.save_task(task)
        self.service.central_logger.log_task_create(task.name, task.environment, task.admin, task.schedule_name)

        self.show_message(
            "Task Created",
            [
                f"Task '{task.name}' created successfully!",
                f"Environment: {task.environment} (Admin: {task.admin})",
                f"Schedule:    {task.schedule_name or 'None (Standalone)'}",
                f"Code Length: {len(task.code)} characters",
            ],
        )

    def workflow_edit_task(self) -> None:
        """Dedicated Edit Task workflow."""
        while True:
            tasks = self.storage.list_tasks()
            if not tasks:
                self.show_message("Edit Task", ["No tasks exist. Create one first."])
                return

            opts = []
            for t in tasks:
                sched_str = t.schedule_name or "standalone"
                status_str = t.last_status or "unrun"
                opts.append(f"{t.name:<22} | {t.environment:<10} | Admin:{t.admin:<5} | {sched_str:<15} | {status_str}")

            idx = self.select_menu("Select Task to Edit", opts)
            if idx == -1:
                return

            selected_task = tasks[idx]
            self._handle_single_task(selected_task)

    def _handle_single_task(self, t: Task) -> None:
        """Manage individual task: modify name, environment, admin flag, script body, schedule, run, delete."""
        while True:
            menu_opts = [
                f"1. Modify Name (Currently: '{t.name}')",
                f"2. Change Execution Environment (Currently: {t.environment})",
                f"3. Toggle Admin Elevation (Currently: {'Elevated' if t.admin else 'Standard'})",
                "4. Edit Script Body in $EDITOR (Neovim/Vim/Nano)",
                "5. Edit Script Body Inline",
                f"6. Re-link or Detach Associated Schedule (Currently: {t.schedule_name or 'Standalone'})",
                f"7. Toggle Status (Currently: {'Active' if t.enabled else 'Disabled'})",
                "8. View Task Log File",
                "9. Run Task Now",
                "10. Delete Task",
            ]
            action = self.select_menu(f"Edit Task: {t.name}", menu_opts)
            if action == -1:
                return

            if action == 0:
                new_name = self.prompt_text("Modify Task Name", "Enter new name", default=t.name)
                if new_name and new_name != t.name:
                    if self.storage.get_task(new_name):
                        self.show_message("Error", [f"Task '{new_name}' already exists."], is_error=True)
                    else:
                        old_name = t.name
                        t.name = new_name
                        self.storage.delete_task(old_name)
                        self.storage.save_task(t)
                        self.service.central_logger.log_task_edit(t.name, f"renamed from '{old_name}'")
                        self.show_message("Renamed", [f"Task renamed to '{t.name}'."])

            elif action == 1:
                env_opts = ["1. terminal (Bash/Sh/Cmd)", "2. pwsh (PowerShell 7+)", "3. powershell (Windows PowerShell)"]
                env_idx = self.select_menu("Select Execution Environment", env_opts)
                if env_idx != -1:
                    t.environment = ["terminal", "pwsh", "powershell"][env_idx]
                    self.storage.save_task(t)
                    self.service.central_logger.log_task_edit(t.name, f"env={t.environment}")
                    self.show_message("Environment Updated", [f"Environment set to {t.environment}."])

            elif action == 2:
                t.admin = not t.admin
                self.storage.save_task(t)
                self.service.central_logger.log_task_edit(t.name, f"admin={t.admin}")
                self.show_message("Admin Elevation Updated", [f"Admin elevation: {t.admin}."])

            elif action == 3:
                suffix = ".ps1" if t.environment in ("pwsh", "powershell") else ".sh"
                new_code = self.shell_out_editor(t.code, suffix=suffix)
                if new_code != t.code:
                    t.code = new_code
                    self.storage.save_task(t)
                    self.service.central_logger.log_task_edit(t.name, "edited script body in $EDITOR")
                    self.show_message("Script Updated", ["Task script updated successfully from $EDITOR."])

            elif action == 4:
                new_code = self.prompt_text("Edit Script Inline", "Enter command/code", default=t.code)
                if new_code is not None:
                    t.code = new_code
                    self.storage.save_task(t)
                    self.service.central_logger.log_task_edit(t.name, "updated command string inline")
                    self.show_message("Script Updated", ["Task script updated inline."])

            elif action == 5:
                schedules = self.storage.list_schedules()
                sched_opts = ["(Detach - Run as Standalone Task)"] + [f"{s.name} ({s.timing.human_readable()})" for s in schedules]
                sc_idx = self.select_menu("Link or Detach Schedule", sched_opts)
                if sc_idx != -1:
                    if sc_idx == 0:
                        t.schedule_name = None
                        self.storage.save_task(t)
                        self.service.central_logger.log_task_detach(t.name)
                        self.show_message("Detached", [f"Task '{t.name}' is now standalone."])
                    else:
                        chosen_sched = schedules[sc_idx - 1].name
                        t.schedule_name = chosen_sched
                        self.storage.save_task(t)
                        self.service.central_logger.log_task_attach(t.name, chosen_sched)
                        self.show_message("Linked", [f"Task '{t.name}' linked to schedule '{chosen_sched}'."])

            elif action == 6:
                t.enabled = not t.enabled
                self.storage.save_task(t)
                self.service.central_logger.log_task_edit(t.name, f"enabled={t.enabled}")
                self.show_message("Status Updated", [f"Task status: {'Active' if t.enabled else 'Disabled'}."])

            elif action == 7:
                content = self.service.task_logger.read_task_log(t.name)
                if content:
                    self._view_scrollable_text(f"Task Log: {t.name}.log", content.splitlines())
                else:
                    self.show_message(f"Task Log: {t.name}", ["No execution run logs recorded yet."])

            elif action == 8:
                res = self.service.execute_task(t.name)
                status_str = "SUCCESS" if res.success else f"FAILED (Exit Code {res.exit_code})"
                lines = [
                    f"Result: {status_str} in {res.duration_sec:.2f}s",
                    "STDOUT:",
                    res.stdout[:500] if res.stdout else "(empty)",
                ]
                if res.stderr:
                    lines.extend(["STDERR:", res.stderr[:300]])
                self.show_message("Execution Finished", lines, is_error=not res.success)

            elif action == 9:
                confirm = self.show_warning_confirm("Delete Task", [f"Are you sure you want to delete task '{t.name}'?"])
                if confirm:
                    self.storage.delete_task(t.name)
                    self.service.central_logger.log_task_delete(t.name)
                    self.show_message("Deleted", [f"Task '{t.name}' deleted."])
                    return

    def workflow_view_logs(self) -> None:
        """Browse system events, schedules, tasks, and individual runs."""
        while True:
            schedules = sorted(self.storage.list_schedules(), key=lambda item: item.name.casefold())
            standalone = [task for task in self.storage.list_tasks() if not task.schedule_name]
            unmatched = self.service.history.unmatched_legacy_logs()
            options = ["System events"] + [
                f"Schedule: {schedule.name} | {schedule.timing.human_readable()} | "
                f"{len(self.storage.get_attached_tasks(schedule.name))} tasks | "
                f"{'enabled' if schedule.enabled else 'disabled'}"
                for schedule in schedules
            ]
            options += [f"Standalone tasks ({len(standalone)})", f"Unmatched legacy logs ({len(unmatched)})", "Clear all logs and history"]
            choice = self.select_menu("Logs and run history", options)
            if choice == -1:
                return
            if choice == 0:
                entries = self.service.central_logger.read_recent_entries(n=500)
                self._view_scrollable_text("Central System Event Log", entries or ["System log is empty."])
            elif choice <= len(schedules):
                self._view_schedule_details(schedules[choice - 1])
            elif choice == len(schedules) + 1:
                while True:
                    selected = self.select_menu("Standalone tasks", [task.name for task in standalone] or ["No standalone tasks"])
                    if selected == -1:
                        break
                    if standalone:
                        self._view_task_details(standalone[selected], None)
            elif choice == len(schedules) + 2:
                while True:
                    selected = self.select_menu("Unmatched legacy logs", [path.name for path in unmatched] or ["No unmatched logs"])
                    if selected == -1:
                        break
                    if unmatched:
                        self._view_scrollable_text(unmatched[selected].name, unmatched[selected].read_text(encoding="utf-8", errors="replace").splitlines())
            else:
                if self.show_warning_confirm("Clear Logs", ["This permanently deletes text logs, events, and run history."]):
                    self.service.central_logger.clear()
                    self.service.task_logger.clear_task_logs()
                    self.service.history.clear()
                    self.show_message("Logs Cleared", ["Text logs and structured history were cleared."])

    @staticmethod
    def _runtime_text(seconds: Optional[float]) -> str:
        return "n/a" if seconds is None else f"{seconds:.2f}s"

    def _stat_rows(self, runs: List[RunRecord]) -> List[DetailRow]:
        rows = []
        for days in (7, 30, 365):
            stats = window_stats(runs, days=days)
            rows.append(DetailRow(f"Last {days} days: {stats.total} runs | {stats.success} success | {stats.failure} failed"))
        stats = window_stats(runs)
        rows.append(DetailRow(
            f"Runtime min/avg/max: {self._runtime_text(stats.minimum_sec)} / "
            f"{self._runtime_text(stats.average_sec)} / {self._runtime_text(stats.maximum_sec)}"
        ))
        return rows

    def _activity_rows(self, runs: List[RunRecord], expected: Optional[dict[date, int]]) -> List[DetailRow]:
        cells = activity_cells(runs, expected=expected, tolerance_seconds=self.service.config.on_time_tolerance_seconds)
        today = date.today()
        start = today - timedelta(days=364)
        rows = [DetailRow("Activity: 52 weeks | green success, red failed/missed, yellow late/partial")]
        # Calendar weeks are aligned so each column represents one week.
        start -= timedelta(days=start.weekday())
        for weekday in range(7):
            states = [cells.get(start + timedelta(days=week * 7 + weekday)) for week in range(53)]
            rows.append(DetailRow("MTWTFSS"[weekday] + " " + "".join("■" if state else " " for state in states), graph_states=states))
        return rows

    def _select_details(self, title: str, rows: List[DetailRow]) -> Optional[tuple[str, Any]]:
        selected = next((i for i, row in enumerate(rows) if row.action), 0)
        top = 0
        while True:
            self._draw_header(title)
            self._draw_footer("Up/Down: Select | PgUp/PgDn: Scroll | Enter: Open | Esc: Back | H: Home")
            height, width = self.stdscr.getmaxyx()
            page = max(1, height - 6)
            top = max(0, min(top, max(0, len(rows) - page)))
            if selected < top:
                top = selected
            elif selected >= top + page:
                top = selected - page + 1
            for offset, row in enumerate(rows[top:top + page]):
                index = top + offset
                y = 3 + offset
                if index == selected and row.action:
                    self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                    self.stdscr.addstr(y, 2, ("> " + row.text)[:width - 4])
                    self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                elif row.graph_states:
                    self.stdscr.addstr(y, 2, row.text[:2])
                    for column, state in enumerate(row.graph_states[:max(0, width - 5)]):
                        color = 2 if state == "success" else 3 if state in {"failure", "missed"} else 4
                        self.stdscr.addstr(y, 4 + column, "■" if state else " ", curses.color_pair(color))
                else:
                    self.stdscr.addstr(y, 2, row.text[:width - 4])
            self.stdscr.refresh()
            key = self.stdscr.getch()
            choices = [i for i, row in enumerate(rows) if row.action]
            if key in (HOME_KEY, ord("H")):
                raise GoHome()
            if key in (27, ord("q"), ord("b")):
                return None
            if key in (10, 13, curses.KEY_ENTER) and rows[selected].action:
                return rows[selected].action
            if key in (curses.KEY_UP, ord("k")) and choices:
                selected = next((choice for choice in reversed(choices) if choice < selected), choices[-1])
            elif key in (curses.KEY_DOWN, ord("j")) and choices:
                selected = next((choice for choice in choices if choice > selected), choices[0])
            elif key == curses.KEY_PPAGE:
                selected = max(0, selected - page)
            elif key == curses.KEY_NPAGE:
                selected = min(len(rows) - 1, selected + page)
            elif key == curses.KEY_HOME:
                selected = 0
            elif key == curses.KEY_END:
                selected = len(rows) - 1

    def _run_label(self, run: RunRecord) -> str:
        local = datetime.fromisoformat(run.started_at).astimezone()
        return f"{local:%Y-%m-%d %H:%M:%S} | {run.status.upper()} | {run.duration_sec:.2f}s | {run.origin}"

    def _view_run(self, run_id: str) -> None:
        run = self.service.history.store.get_run(run_id)
        if run is None:
            self.show_message("Run missing", ["This run is no longer in history."], is_error=True)
            return
        lines = [f"{run.display_name} | {self._run_label(run)}", f"Exit code: {run.exit_code}"]
        if run.scheduled_for:
            lines.append(f"Scheduled for: {run.scheduled_for}")
        if run.entity_type == "schedule":
            children = self.service.history.store.list_runs(source="scheduler", parent_id=run.record_id)
            lines += [f"Tasks: {len(children)}"]
            for child in reversed(children):
                full = self.service.history.store.get_run(child.record_id)
                lines += [
                    "", "=" * 60, f"{child.display_name}: {child.status} ({child.duration_sec:.2f}s)",
                    "STDOUT:", "(output expired)" if full.stdout is None else (full.stdout or "(empty)"),
                    "STDERR:", "(output expired)" if full.stderr is None else (full.stderr or "(empty)"),
                ]
        else:
            lines += ["", "STDOUT:", run.stdout if run.stdout is not None else "(output expired)", "", "STDERR:", run.stderr if run.stderr is not None else "(output expired)"]
        self._view_scrollable_text(f"Run {run.record_id[:8]}", "\n".join(lines).splitlines())

    def _view_schedule_details(self, schedule: Schedule) -> None:
        while True:
            tasks = sorted((task for task in self.storage.list_tasks() if task.schedule_name == schedule.name), key=lambda task: (task.schedule_order or 0, task.name))
            runs = self.service.history.list_schedule_runs(schedule)
            now = datetime.now().astimezone()
            expected = expected_daily_counts(schedule, start=now.date() - timedelta(days=364), end=now.date(), coverage_start=self.service.history.coverage_start, now=now)
            punctual = punctuality(runs, tolerance_seconds=self.service.config.on_time_tolerance_seconds, expected=expected)
            rows = [
                DetailRow(f"Cadence: {schedule.timing.human_readable()} | {'enabled' if schedule.enabled else 'disabled'}"),
                DetailRow(f"Last run: {schedule.last_run_time or 'never'} | Next run: {schedule.next_run_time or 'unknown'}"),
                DetailRow(f"Expected runs use current cadence since {self.service.history.coverage_start[:10]} (history coverage)."),
            ]
            rows += self._stat_rows(runs)
            punctual_total = punctual['on_time'] + punctual['late'] + punctual['early']
            rate = (100 * punctual['on_time'] / punctual_total) if punctual_total else 0.0
            rows.append(DetailRow(
                f"Timing (±{self.service.config.on_time_tolerance_seconds}s): {punctual['on_time']} on time ({rate:.0f}%) | "
                f"{punctual['late']} late | {punctual['early']} early | {punctual['catch_up']} catch-up | {punctual['missed']} missed"
            ))
            rows += self._activity_rows(runs, expected)
            rows.append(DetailRow("Tasks (select to view task details):"))
            for task in tasks:
                task_stats = window_stats(self.service.history.list_task_runs(task))
                rows.append(DetailRow(
                    f"  {task.name} | {task_stats.total} runs | {task_stats.success} ok | {task_stats.failure} failed | "
                    f"avg {self._runtime_text(task_stats.average_sec)}", ("task", task),
                ))
            rows.append(DetailRow("Schedule runs (newest first):"))
            rows += [DetailRow("  " + self._run_label(run), ("run", run.record_id)) for run in runs]
            action = self._select_details(f"Schedule: {schedule.name}", rows)
            if action is None:
                return
            if action[0] == "task":
                self._view_task_details(action[1], schedule)
            else:
                self._view_run(action[1])

    def _view_task_details(self, task: Task, schedule: Optional[Schedule]) -> None:
        while True:
            runs = self.service.history.list_task_runs(task)
            now = datetime.now().astimezone()
            expected = task_expected_counts(task, schedule, start=now.date() - timedelta(days=364), end=now.date(), coverage_start=self.service.history.coverage_start, now=now)
            rows = [
                DetailRow(f"Schedule: {schedule.name if schedule else 'None'} | {'enabled' if task.enabled else 'disabled'} | {'admin' if task.admin else 'standard'}"),
                DetailRow(f"Recorded history since {self.service.history.coverage_start[:10]}; older retained logs may be partial."),
            ]
            if schedule:
                rows.append(DetailRow(f"Cadence: {schedule.timing.human_readable()}"))
            rows += self._stat_rows(runs)
            lifetime = window_stats(runs)
            success_rate = 100 * lifetime.success / lifetime.total if lifetime.total else 0.0
            rows.append(DetailRow(f"Lifetime: {lifetime.total} runs | {lifetime.success} success | {lifetime.failure} failed | {success_rate:.0f}% success"))
            rows += self._activity_rows(runs, expected)
            rows.append(DetailRow("Task runs (newest first):"))
            rows += [DetailRow("  " + self._run_label(run), ("run", run.record_id)) for run in runs]
            action = self._select_details(f"Task: {task.name}", rows)
            if action is None:
                return
            self._view_run(action[1])

    def _view_scrollable_text(self, title: str, lines: List[str]) -> None:
        """Display scrollable text with Up/Down, PageUp/PageDown, Home/End."""
        top_line = 0
        total_lines = len(lines)

        while True:
            height, width = self.stdscr.getmaxyx()
            page_height = max(1, height - 5)
            bottom_line = min(top_line + page_height, total_lines)

            pos_info = f"{title} [{top_line + 1}-{bottom_line}/{total_lines}]" if total_lines > 0 else title
            self._draw_header(pos_info)
            self._draw_footer("Up/Down: Scroll | PgUp/PgDn: Fast | Home/End: Jump | Esc: Back | H: Home")

            for i in range(page_height):
                line_idx = top_line + i
                if line_idx < total_lines:
                    self.stdscr.addstr(3 + i, 2, lines[line_idx][: width - 4])

            self.stdscr.refresh()
            k = self.stdscr.getch()

            if k in (curses.KEY_UP, ord("k")):
                top_line = max(0, top_line - 1)
            elif k in (curses.KEY_DOWN, ord("j")):
                if top_line + 1 < total_lines:
                    top_line += 1
            elif k in (curses.KEY_PPAGE, ord("u"), 2):  # Page Up / Ctrl+B
                top_line = max(0, top_line - page_height)
            elif k in (curses.KEY_NPAGE, ord("d"), ord(" "), 6):  # Page Down / Space / Ctrl+F
                if top_line + page_height < total_lines:
                    top_line = min(total_lines - page_height, top_line + page_height)
            elif k in (curses.KEY_HOME, ord("g")):
                top_line = 0
            elif k in (curses.KEY_END, ord("G")):
                top_line = max(0, total_lines - page_height)
            elif k in (HOME_KEY, ord("H")):
                raise GoHome()
            elif k in (27, ord("q"), ord("b")):
                return

    def workflow_config(self) -> None:
        """View and adjust configuration and executable paths."""
        while True:
            cfg = self.service.refresh_config()
            opts = [
                f"pwsh path:       {cfg.executables.pwsh or '(not detected)'}",
                f"powershell path: {cfg.executables.powershell or '(not detected)'}",
                f"terminal path:   {cfg.executables.terminal or '(not detected)'}",
                f"Log retention:   {cfg.log_retention_runs} runs per task",
                f"Notifications:   {'Enabled' if cfg.notifications_enabled else 'Disabled'}",
                "Auto-detect shell paths and save",
                "Windows background runner setup / status",
            ]
            idx = self.select_menu("Configuration & Executables", opts)
            if idx == -1:
                return

            if idx == 0:
                new_p = self.prompt_text("pwsh Path", "Path to pwsh", default=cfg.executables.pwsh)
                if new_p:
                    cfg.executables.pwsh = new_p
                    self.storage.update_config(cfg)
            elif idx == 1:
                new_p = self.prompt_text("powershell Path", "Path to powershell", default=cfg.executables.powershell)
                if new_p:
                    cfg.executables.powershell = new_p
                    self.storage.update_config(cfg)
            elif idx == 2:
                new_p = self.prompt_text("terminal Path", "Path to default terminal", default=cfg.executables.terminal)
                if new_p:
                    cfg.executables.terminal = new_p
                    self.storage.update_config(cfg)
            elif idx == 3:
                ret = self.prompt_text("Log Retention", "Runs to retain (N)", default=str(cfg.log_retention_runs))
                if ret and ret.isdigit():
                    cfg.log_retention_runs = max(1, int(ret))
                    self.storage.update_config(cfg)
            elif idx == 4:
                cfg.notifications_enabled = not cfg.notifications_enabled
                self.storage.update_config(cfg)
            elif idx == 5:
                from .config import ConfigManager
                detected = ConfigManager.detect_executables()
                cfg.executables = detected
                self.storage.update_config(cfg)
                self.show_message("Auto-Detect", ["Applied auto-detected shell paths."])
            elif idx == 6:
                self.workflow_windows_runner()

    def workflow_windows_runner(self) -> None:
        """Inspect and manage the Windows logon daemon task from the TUI."""
        while True:
            try:
                status = windows_task.get_runner_status()
                worker_status = status.get("adminWorker", {})
                status_label = (
                    "Installed" if status.get("installed") and worker_status.get("installed") else "Needs setup"
                )
            except (OSError, RuntimeError) as exc:
                status = {"installed": False}
                status_label = f"Unavailable: {exc}"

            choice = self.select_menu(
                "Windows Background Runner",
                [
                    f"Status: {status_label}",
                    "Install / update logon runner (one-time UAC approval)",
                    "Start runner now (may execute catch-up tasks)",
                    "Remove logon runner",
                ],
            )
            if choice == -1:
                return
            if choice == 0:
                lines = []
                for key, value in status.items():
                    if key == "adminWorker" and isinstance(value, dict):
                        lines.extend(f"adminWorker.{worker_key}: {worker_value}" for worker_key, worker_value in value.items())
                    else:
                        lines.append(f"{key}: {value}")
                if not lines:
                    lines = [status_label]
                self.show_message("Windows Runner Status", lines)
            elif choice == 1:
                try:
                    message = windows_task.install_runner(self.storage.data_file)
                    self.show_message(
                        "Windows Runner Installed",
                        [message, "The daemon runs with limited privileges; a separate elevated worker runs only tasks marked Admin."],
                    )
                    return
                except (OSError, RuntimeError, ValueError) as exc:
                    self.show_message("Runner Setup Failed", [str(exc)], is_error=True)
            elif choice == 2:
                if not self.show_warning_confirm(
                    "Start Scheduler Daemon",
                    [
                        "Starting the daemon may execute due or missed schedule tasks now.",
                        "Continue only if you are ready for those tasks to run.",
                    ],
                ):
                    continue
                try:
                    message = windows_task.start_runner()
                    self.show_message("Windows Runner Started", [message])
                except (OSError, RuntimeError) as exc:
                    self.show_message("Runner Start Failed", [str(exc)], is_error=True)
            elif choice == 3:
                if not self.show_warning_confirm(
                    "Remove Windows Runner",
                    ["The logon-triggered daemon task will be removed."],
                ):
                    continue
                try:
                    message = windows_task.remove_runner()
                    self.show_message("Windows Runner Removed", [message])
                except (OSError, RuntimeError) as exc:
                    self.show_message("Runner Removal Failed", [str(exc)], is_error=True)

    def run(self) -> int:
        """Return to the main menu from deeply nested screens on H/Shift+Esc."""
        while True:
            try:
                return self._run_menu_loop()
            except GoHome:
                continue

    def _run_menu_loop(self) -> int:
        """Main TUI loop."""
        main_options = [
            "1. Create Schedule",
            "2. Edit / Delete Schedule",
            "3. Create Task",
            "4. Edit Task",
            "5. View Logs",
            "6. Run Tasks / Schedules",
            "7. Configuration & Shell Paths",
            "8. Exit",
        ]

        while True:
            setup_state = get_setup_state()
            if not setup_state.complete:
                warning_lines = [setup_state.message]
                if setup_state.setup_command:
                    warning_lines.extend(
                        [
                            "The scheduler stays locked until this one-time setup succeeds.",
                            f"CLI command: {setup_state.setup_command}",
                            "Setup asks for administrator approval once; later runs use the registered task.",
                        ]
                    )
                    options = ["1. Set up Windows scheduler runner"]
                else:
                    warning_lines.extend(
                        [
                            "The scheduler stays locked until setup is available for this OS.",
                            f"{setup_state.platform_name} setup has not been implemented yet.",
                        ]
                    )
                    options = ["Exit scheduler"]

                choice = self.select_menu(
                    "Setup Required",
                    options,
                    footer_hints="Enter: Select | Esc/q: Exit",
                    warning_lines=warning_lines,
                )
                if choice == -1 or not setup_state.setup_command:
                    return 0
                self.workflow_windows_runner()
                continue

            choice = self.select_menu("Main Menu", main_options)
            if choice in (-1, 7):  # Exit or Esc
                break
            elif choice == 0:
                self.workflow_create_schedule()
            elif choice == 1:
                self.workflow_manage_schedules()
            elif choice == 2:
                self.workflow_create_task()
            elif choice == 3:
                self.workflow_edit_task()
            elif choice == 4:
                self.workflow_view_logs()
            elif choice == 5:
                # Run tasks / schedules
                sub = self.select_menu("Run Now", ["1. Run Single Task", "2. Run Entire Schedule", "3. Evaluate All Schedules Once"])
                if sub == 0:
                    tasks = self.storage.list_tasks()
                    if tasks:
                        t_idx = self.select_menu("Select Task to Run", [t.name for t in tasks])
                        if t_idx != -1:
                            task = tasks[t_idx]
                            run_options = [
                                "Run immediately (manual; may request UAC)" if task.admin else "Run immediately (manual)"
                            ]
                            if task.admin:
                                run_options.append("Schedule elevated runner test in about 10 seconds (visible window)")
                            mode = self.select_menu(
                                f"Run Task: {task.name}",
                                run_options,
                            )
                            if mode == 0:
                                res = self.service.execute_task(task.name)
                                self.show_message(
                                    "Execution Finished",
                                    [
                                        f"Status: {'SUCCESS' if res.success else 'FAILED'} (Exit: {res.exit_code})",
                                        "The TUI waited for this manual run to finish.",
                                    ],
                                    is_error=not res.success,
                                )
                            elif mode == 1:
                                try:
                                    run_at = self.service.queue_runner_test(task.name, delay_seconds=10)
                                    self.show_message(
                                        "Runner Test Queued",
                                        [
                                            f"Task '{task.name}' is queued for about 10 seconds from now ({run_at}).",
                                            "The active elevated runner will open a visible console window when it starts.",
                                            "The TUI returns immediately; the task output appears in that window.",
                                        ],
                                    )
                                except (OSError, RuntimeError, ValueError) as exc:
                                    self.show_message("Runner Test Not Queued", [str(exc)], is_error=True)
                elif sub == 1:
                    schedules = self.storage.list_schedules()
                    if schedules:
                        s_idx = self.select_menu("Select Schedule to Run", [s.name for s in schedules])
                        if s_idx != -1:
                            res = self.service.execute_schedule(schedules[s_idx].name)
                            self.show_message("Execution Finished", [f"Triggered {len(res)} tasks."])
                elif sub == 2:
                    res = self.service.run_once()
                    self.show_message("Evaluation Complete", [f"Triggered {len(res)} tasks across all schedules."])
            elif choice == 6:
                self.workflow_config()

        return 0


def run_tui(service: Optional[SchedulerService] = None) -> int:
    """Entry point for launching the TUI."""
    if service is None:
        service = SchedulerService()

    try:
        return curses.wrapper(lambda scr: SchedulerTUI(service, scr).run())
    except Exception as e:
        print(f"[ERROR] Could not start TUI: {e}", file=sys.stderr)
        return 1
