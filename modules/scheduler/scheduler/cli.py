#!/usr/bin/env python
"""
Main CLI entry point for the scheduler module.
Matches the argument and subcommand structural pattern used in file-util.
"""
from __future__ import annotations

import argparse
import json as _json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .config import ConfigManager
from .models import Schedule, ScheduleTiming, Task
from .service import SchedulerService
from .storage import StorageManager
from .timing import (
    calculate_next_run,
    normalize_days,
    parse_interval_string,
)


def _launch_editor(initial_content: str = "", suffix: str = ".sh") -> str:
    """Launch $EDITOR or fallback editor to compose or edit script code."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        for candidate in ("nvim", "vim", "nano", "code", "notepad"):
            if shutil.which(candidate):
                editor = candidate
                break
    if not editor:
        editor = "nano" if os.name != "nt" else "notepad"

    with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(initial_content)
        temp_path = Path(f.name)

    try:
        subprocess.run([editor, str(temp_path)], check=True)
        with open(temp_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scheduler",
        description="A robust Python scheduling and task execution module.",
    )
    parser.add_argument(
        "-c",
        "--config-file",
        type=Path,
        default=None,
        help="Path to persistent JSON data file (defaults to scheduler_data.json in module directory).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-error output.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=False)

    # ─────────────────────────────────────────────────────────
    # schedule command
    # ─────────────────────────────────────────────────────────
    sched_parser = subparsers.add_parser("schedule", help="Manage timing schedules.")
    sched_sub = sched_parser.add_subparsers(dest="schedule_cmd", required=True)

    # schedule create
    sc_create = sched_sub.add_parser("create", help="Create a new schedule.")
    sc_create.add_argument("-n", "--name", required=True, help="Unique name for the schedule.")
    sc_create.add_argument(
        "-t",
        "--timing-type",
        choices=["daily", "interval", "hourly", "weekly", "specific_days", "monthly", "cron"],
        default="daily",
        help="Recurrence type.",
    )
    sc_create.add_argument("-a", "--at", default="00:00", help="Time of day (e.g. 00:00, 14:30, midnight).")
    sc_create.add_argument("-i", "--interval", default="1h", help="Interval duration (e.g. 3h, 30m, 3600s).")
    sc_create.add_argument("-d", "--days", default="", help="Comma-separated days (e.g. monday,wednesday,friday).")
    sc_create.add_argument("-m", "--day-of-month", type=int, default=1, help="Day of month (1-31).")
    sc_create.add_argument("-C", "--cron", default="", help="5-field cron expression.")
    sc_create.add_argument(
        "-u",
        "--catch-up",
        action="store_true",
        default=True,
        help="Run tasks ASAP if a scheduled time was missed (default: enabled).",
    )
    sc_create.add_argument("-U", "--no-catch-up", action="store_true", help="Disable catch-up feature.")
    sc_create.add_argument("-e", "--enable", action="store_true", default=True, help="Enable schedule on creation.")
    sc_create.add_argument("-D", "--disable", action="store_true", help="Create schedule in disabled state.")

    # schedule list
    sc_list = sched_sub.add_parser("list", help="List all schedules.")
    sc_list.add_argument("-f", "--format", choices=["table", "json", "plain"], default="table", help="Output format.")
    sc_list.add_argument("-a", "--all", action="store_true", help="Show all schedules including disabled.")

    # schedule show
    sc_show = sched_sub.add_parser("show", help="Show details for a schedule.")
    sc_show.add_argument("-n", "--name", required=True, help="Schedule name.")
    sc_show.add_argument("-f", "--format", choices=["table", "json", "plain"], default="table", help="Output format.")

    # schedule edit
    sc_edit = sched_sub.add_parser("edit", help="Edit an existing schedule.")
    sc_edit.add_argument("-n", "--name", required=True, help="Schedule name to edit.")
    sc_edit.add_argument("-r", "--rename", default=None, help="New name for the schedule.")
    sc_edit.add_argument(
        "-t",
        "--timing-type",
        choices=["daily", "interval", "hourly", "weekly", "specific_days", "monthly", "cron"],
        default=None,
        help="Recurrence type.",
    )
    sc_edit.add_argument("-a", "--at", default=None, help="Time of day (e.g. 00:00, 14:30).")
    sc_edit.add_argument("-i", "--interval", default=None, help="Interval duration (e.g. 3h, 30m).")
    sc_edit.add_argument("-d", "--days", default=None, help="Comma-separated days.")
    sc_edit.add_argument("-m", "--day-of-month", type=int, default=None, help="Day of month (1-31).")
    sc_edit.add_argument("-C", "--cron", default=None, help="5-field cron expression.")
    sc_edit.add_argument("-u", "--catch-up", action="store_true", help="Enable catch-up.")
    sc_edit.add_argument("-U", "--no-catch-up", action="store_true", help="Disable catch-up.")
    sc_edit.add_argument("-e", "--enable", action="store_true", help="Enable schedule.")
    sc_edit.add_argument("-D", "--disable", action="store_true", help="Disable schedule.")

    # schedule delete
    sc_del = sched_sub.add_parser("delete", help="Delete a schedule.")
    sc_del.add_argument("-n", "--name", required=True, help="Schedule name to delete.")
    sc_del.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force delete without prompt, even if attached tasks exist.",
    )
    sc_del.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt.")

    # ─────────────────────────────────────────────────────────
    # task command
    # ─────────────────────────────────────────────────────────
    task_parser = subparsers.add_parser("task", help="Manage automation tasks.")
    task_sub = task_parser.add_subparsers(dest="task_cmd", required=True)

    # task create
    tk_create = task_sub.add_parser("create", help="Create a new task.")
    tk_create.add_argument("-n", "--name", required=True, help="Unique name for the task.")
    tk_create.add_argument("-s", "--schedule", default=None, help="Schedule name to link to.")
    tk_create.add_argument(
        "-e",
        "--env",
        choices=["pwsh", "powershell", "terminal"],
        default="terminal",
        help="Execution environment.",
    )
    tk_create.add_argument("-a", "--admin", action="store_true", help="Run with admin/elevated privileges.")
    tk_create.add_argument("-N", "--no-admin", action="store_true", help="Run without elevation (default).")
    tk_create.add_argument("-c", "--command", default="", help="Command or code string to execute.")
    tk_create.add_argument("-i", "--input-file", type=Path, default=None, help="Path to script file to import.")
    tk_create.add_argument("-E", "--edit", action="store_true", help="Shell out to $EDITOR to compose script.")

    # task list
    tk_list = task_sub.add_parser("list", help="List tasks.")
    tk_list.add_argument("-s", "--schedule", default=None, help="Filter by schedule name.")
    tk_list.add_argument("-f", "--format", choices=["table", "json", "plain"], default="table", help="Output format.")

    # task show
    tk_show = task_sub.add_parser("show", help="Show task details.")
    tk_show.add_argument("-n", "--name", required=True, help="Task name.")
    tk_show.add_argument("-f", "--format", choices=["table", "json", "plain"], default="table", help="Output format.")

    # task edit
    tk_edit = task_sub.add_parser("edit", help="Edit an existing task.")
    tk_edit.add_argument("-n", "--name", required=True, help="Task name to edit.")
    tk_edit.add_argument("-r", "--rename", default=None, help="New name for the task.")
    tk_edit.add_argument("-s", "--schedule", default=None, help="Link to schedule (use 'none' to detach).")
    tk_edit.add_argument(
        "-e",
        "--env",
        choices=["pwsh", "powershell", "terminal"],
        default=None,
        help="Execution environment.",
    )
    tk_edit.add_argument("-a", "--admin", action="store_true", help="Enable admin elevation.")
    tk_edit.add_argument("-N", "--no-admin", action="store_true", help="Disable admin elevation.")
    tk_edit.add_argument("-c", "--command", default=None, help="New code block or command string.")
    tk_edit.add_argument("-i", "--input-file", type=Path, default=None, help="Import script file.")
    tk_edit.add_argument("-E", "--edit", action="store_true", help="Shell out to $EDITOR to modify script.")
    tk_edit.add_argument("-p", "--enable", action="store_true", help="Enable task.")
    tk_edit.add_argument("-d", "--disable", action="store_true", help="Disable task.")

    # task delete
    tk_del = task_sub.add_parser("delete", help="Delete a task.")
    tk_del.add_argument("-n", "--name", required=True, help="Task name to delete.")
    tk_del.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt.")

    # task attach
    tk_attach = task_sub.add_parser("attach", help="Attach a task to a schedule.")
    tk_attach.add_argument("-n", "--name", required=True, help="Task name.")
    tk_attach.add_argument("-s", "--schedule", required=True, help="Schedule name.")

    # task detach
    tk_detach = task_sub.add_parser("detach", help="Detach a task from its schedule.")
    tk_detach.add_argument("-n", "--name", required=True, help="Task name.")

    # ─────────────────────────────────────────────────────────
    # run command
    # ─────────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="Execute tasks or schedules on demand.")
    run_parser.add_argument("-t", "--task", default=None, help="Task name to execute.")
    run_parser.add_argument("-s", "--schedule", default=None, help="Schedule name whose tasks to execute.")
    run_parser.add_argument("-A", "--all", action="store_true", help="Run all enabled schedules.")
    run_parser.add_argument("-d", "--dry-run", action="store_true", help="Preview execution without running commands.")

    # ─────────────────────────────────────────────────────────
    # daemon / service command
    # ─────────────────────────────────────────────────────────
    daemon_parser = subparsers.add_parser("daemon", help="Run background scheduler service or single evaluation.")
    daemon_parser.add_argument("-o", "--once", action="store_true", help="Evaluate due and catch-up schedules once and exit.")
    daemon_parser.add_argument("-i", "--interval", type=float, default=10.0, help="Check interval in seconds.")
    daemon_parser.add_argument("-d", "--dry-run", action="store_true", help="Simulate run without invoking commands.")
    daemon_parser.add_argument("-m", "--max-ticks", type=int, default=None, help="Exit after N ticks (for testing).")

    # ─────────────────────────────────────────────────────────
    # logs command
    # ─────────────────────────────────────────────────────────
    logs_parser = subparsers.add_parser("logs", help="Inspect system or task execution logs.")
    logs_sub = logs_parser.add_subparsers(dest="logs_cmd", required=True)

    # logs system
    lg_sys = logs_sub.add_parser("system", help="View central system log.")
    lg_sys.add_argument("-n", "--lines", type=int, default=50, help="Number of recent log entries to show.")
    lg_sys.add_argument("-f", "--format", choices=["plain", "json"], default="plain", help="Output format.")

    # logs task
    lg_task = logs_sub.add_parser("task", help="View task execution logs.")
    lg_task.add_argument("-n", "--name", required=True, help="Task name.")
    lg_task.add_argument("-c", "--count", type=int, default=None, help="Number of recent runs to list.")
    lg_task.add_argument("-l", "--latest", action="store_true", help="Show full content of the latest run log.")

    # logs clear
    lg_clr = logs_sub.add_parser("clear", help="Clear logs.")
    lg_clr.add_argument(
        "-t",
        "--type",
        choices=["system", "tasks", "all"],
        default="system",
        help="Log target to clear.",
    )
    lg_clr.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt.")

    # ─────────────────────────────────────────────────────────
    # config command
    # ─────────────────────────────────────────────────────────
    cfg_parser = subparsers.add_parser("config", help="View or modify executable paths and settings.")
    cfg_sub = cfg_parser.add_subparsers(dest="config_cmd", required=True)

    # config show
    cf_show = cfg_sub.add_parser("show", help="Display current configuration.")
    cf_show.add_argument("-f", "--format", choices=["table", "json", "plain"], default="table", help="Output format.")

    # config set
    cf_set = cfg_sub.add_parser("set", help="Update configuration parameters.")
    cf_set.add_argument("-p", "--pwsh", default=None, help="Absolute path to pwsh executable.")
    cf_set.add_argument("-w", "--powershell", default=None, help="Absolute path to powershell executable.")
    cf_set.add_argument("-t", "--terminal", default=None, help="Absolute path to default terminal shell.")
    cf_set.add_argument("-r", "--retention", type=int, default=None, help="N recent runs to retain per task.")
    cf_set.add_argument(
        "-N",
        "--notifications",
        choices=["on", "off", "true", "false"],
        default=None,
        help="Enable or disable notifications.",
    )

    # config detect
    cf_det = cfg_sub.add_parser("detect", help="Auto-detect underlying shell executables on this machine.")
    cf_det.add_argument("-a", "--apply", action="store_true", help="Apply and save detected paths.")

    # ─────────────────────────────────────────────────────────
    # tui command
    # ─────────────────────────────────────────────────────────
    subparsers.add_parser("tui", help="Launch the interactive Terminal User Interface (TUI).")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    storage = StorageManager(data_file=args.config_file)
    service = SchedulerService(storage=storage)

    # If no command provided: launch TUI if running interactively, else show help
    if not args.subcommand:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_tui
            return run_tui(service=service)
        else:
            parser.print_help()
            return 0

    if args.subcommand == "tui":
        from .tui import run_tui
        return run_tui(service=service)

    # ─────────────────────────────────────────────────────────
    # Schedule Subcommands
    # ─────────────────────────────────────────────────────────
    if args.subcommand == "schedule":
        sc_cmd = args.schedule_cmd

        if sc_cmd == "create":
            existing = storage.get_schedule(args.name)
            if existing:
                print(f"[ERROR] Schedule '{args.name}' already exists.", file=sys.stderr)
                return 1

            timing_type = args.timing_type.lower()
            interval_sec = parse_interval_string(args.interval)
            days = normalize_days(args.days) if args.days else []
            dom = max(1, min(31, args.day_of_month))

            timing = ScheduleTiming(
                timing_type=timing_type,
                at_time=args.at,
                interval_seconds=interval_sec,
                days=days,
                day_of_month=dom,
                cron_expression=args.cron,
            )

            catch_up = False if args.no_catch_up else args.catch_up
            enabled = False if args.disable else args.enable

            next_run = calculate_next_run(timing)
            schedule = Schedule(
                name=args.name,
                timing=timing,
                catch_up=catch_up,
                enabled=enabled,
                next_run_time=next_run.isoformat(),
            )
            storage.save_schedule(schedule)
            service.central_logger.log_schedule_create(schedule.name, timing.human_readable())

            if not args.quiet:
                print(f"[OK] Schedule '{schedule.name}' created.")
                print(f"     Timing:   {timing.human_readable()}")
                print(f"     Catch-up: {'Enabled' if catch_up else 'Disabled'}")
                print(f"     Next Run: {next_run.isoformat()}")
            return 0

        elif sc_cmd == "list":
            schedules = storage.list_schedules()
            if not args.all:
                schedules = [s for s in schedules if s.enabled]

            if args.format == "json":
                out = [s.to_dict() for s in schedules]
                print(_json.dumps(out, indent=2))
                return 0

            if not schedules:
                if not args.quiet:
                    print("No schedules found.")
                return 0

            if args.format == "plain":
                for s in schedules:
                    attached = storage.get_attached_tasks(s.name)
                    print(f"{s.name}\t{s.timing.human_readable()}\t{'Enabled' if s.enabled else 'Disabled'}\tTasks:{len(attached)}")
                return 0

            # Table format
            header = f"{'SCHEDULE NAME':<22} | {'TIMING':<32} | {'CATCH-UP':<9} | {'STATUS':<9} | {'TASKS':<6} | {'NEXT RUN'}"
            print(header)
            print("-" * len(header))
            for s in schedules:
                attached = storage.get_attached_tasks(s.name)
                cu_str = "Yes" if s.catch_up else "No"
                st_str = "Active" if s.enabled else "Disabled"
                nr_str = s.next_run_time or "N/A"
                print(f"{s.name:<22} | {s.timing.human_readable():<32} | {cu_str:<9} | {st_str:<9} | {len(attached):<6} | {nr_str}")
            return 0

        elif sc_cmd == "show":
            s = storage.get_schedule(args.name)
            if not s:
                print(f"[ERROR] Schedule '{args.name}' not found.", file=sys.stderr)
                return 1

            attached = storage.get_attached_tasks(s.name)
            if args.format == "json":
                data = s.to_dict()
                data["attached_tasks"] = [t.name for t in attached]
                print(_json.dumps(data, indent=2))
                return 0

            print(f"Schedule:    {s.name}")
            print(f"Status:      {'Active' if s.enabled else 'Disabled'}")
            print(f"Timing:      {s.timing.human_readable()}")
            print(f"Catch-up:    {'Enabled' if s.catch_up else 'Disabled'}")
            print(f"Created:     {s.created_at}")
            print(f"Updated:     {s.updated_at}")
            print(f"Last Run:    {s.last_run_time or 'Never'}")
            print(f"Next Run:    {s.next_run_time or 'N/A'}")
            print(f"Attached Tasks ({len(attached)}):")
            for t in attached:
                print(f"  - {t.name} (env: {t.environment}, admin: {t.admin})")
            return 0

        elif sc_cmd == "edit":
            s = storage.get_schedule(args.name)
            if not s:
                print(f"[ERROR] Schedule '{args.name}' not found.", file=sys.stderr)
                return 1

            changes = []
            if args.timing_type:
                s.timing.timing_type = args.timing_type.lower()
                changes.append(f"timing_type={s.timing.timing_type}")
            if args.at is not None:
                s.timing.at_time = args.at
                changes.append(f"at={s.timing.at_time}")
            if args.interval is not None:
                s.timing.interval_seconds = parse_interval_string(args.interval)
                changes.append(f"interval={s.timing.interval_seconds}s")
            if args.days is not None:
                s.timing.days = normalize_days(args.days)
                changes.append(f"days={s.timing.days}")
            if args.day_of_month is not None:
                s.timing.day_of_month = max(1, min(31, args.day_of_month))
                changes.append(f"dom={s.timing.day_of_month}")
            if args.cron is not None:
                s.timing.cron_expression = args.cron
                changes.append(f"cron={s.timing.cron_expression}")
            if args.catch_up:
                s.catch_up = True
                changes.append("catch_up=True")
            elif args.no_catch_up:
                s.catch_up = False
                changes.append("catch_up=False")
            if args.enable:
                s.enabled = True
                changes.append("enabled=True")
            elif args.disable:
                s.enabled = False
                changes.append("enabled=False")

            # Handle rename
            if args.rename and args.rename != s.name:
                if storage.get_schedule(args.rename):
                    print(f"[ERROR] Schedule '{args.rename}' already exists.", file=sys.stderr)
                    return 1
                old_name = s.name
                s.name = args.rename
                # Relink attached tasks to new name
                attached = storage.get_attached_tasks(old_name)
                for t in attached:
                    t.schedule_name = s.name
                    storage.save_task(t)
                storage.delete_schedule(old_name, orphan_tasks=False)
                changes.append(f"renamed from '{old_name}'")

            s.next_run_time = calculate_next_run(s.timing).isoformat()
            storage.save_schedule(s)
            detail_str = ", ".join(changes) if changes else "no changes"
            service.central_logger.log_schedule_edit(s.name, detail_str)

            if not args.quiet:
                print(f"[OK] Schedule '{s.name}' updated: {detail_str}")
            return 0

        elif sc_cmd == "delete":
            s = storage.get_schedule(args.name)
            if not s:
                print(f"[ERROR] Schedule '{args.name}' not found.", file=sys.stderr)
                return 1

            attached = storage.get_attached_tasks(s.name)
            if attached and not args.force:
                print(f"[WARNING] Schedule '{s.name}' has {len(attached)} attached task(s):", file=sys.stderr)
                for t in attached:
                    print(f"  - {t.name}", file=sys.stderr)
                print("[WARNING] Deleting this schedule will leave these tasks orphaned (standalone).", file=sys.stderr)
                if not args.yes:
                    resp = input(f"Proceed with deleting '{s.name}'? [y/N]: ")
                    if resp.strip().lower() not in ("y", "yes"):
                        print("Aborted.")
                        return 0

            success, orphaned = storage.delete_schedule(s.name, orphan_tasks=True)
            if success:
                service.central_logger.log_schedule_delete(s.name, orphaned)
                if not args.quiet:
                    msg = f"[OK] Schedule '{s.name}' deleted."
                    if orphaned:
                        msg += f" {len(orphaned)} task(s) orphaned: {', '.join(orphaned)}"
                    print(msg)
                return 0
            return 1

    # ─────────────────────────────────────────────────────────
    # Task Subcommands
    # ─────────────────────────────────────────────────────────
    elif args.subcommand == "task":
        tk_cmd = args.task_cmd

        if tk_cmd == "create":
            existing = storage.get_task(args.name)
            if existing:
                print(f"[ERROR] Task '{args.name}' already exists.", file=sys.stderr)
                return 1

            if args.schedule:
                if not storage.get_schedule(args.schedule):
                    print(f"[ERROR] Schedule '{args.schedule}' does not exist.", file=sys.stderr)
                    return 1

            # Determine code
            code = args.command
            if args.input_file:
                p = Path(args.input_file)
                if not p.is_file():
                    print(f"[ERROR] Script file '{args.input_file}' not found.", file=sys.stderr)
                    return 1
                code = p.read_text(encoding="utf-8", errors="replace")
            elif args.edit:
                code = _launch_editor(code, suffix=".ps1" if args.env in ("pwsh", "powershell") else ".sh")

            admin = True if args.admin else False
            task = Task(
                name=args.name,
                schedule_name=args.schedule,
                environment=args.env,
                admin=admin,
                code=code,
                enabled=True,
            )
            storage.save_task(task)
            service.central_logger.log_task_create(task.name, task.environment, task.admin, task.schedule_name)

            if not args.quiet:
                print(f"[OK] Task '{task.name}' created.")
                print(f"     Environment: {task.environment} (Admin: {task.admin})")
                print(f"     Schedule:    {task.schedule_name or 'None (Standalone)'}")
                print(f"     Code Length: {len(task.code)} chars")
            return 0

        elif tk_cmd == "list":
            tasks = storage.list_tasks(schedule_name=args.schedule)
            if args.format == "json":
                out = [t.to_dict() for t in tasks]
                print(_json.dumps(out, indent=2))
                return 0

            if not tasks:
                if not args.quiet:
                    print("No tasks found.")
                return 0

            if args.format == "plain":
                for t in tasks:
                    print(f"{t.name}\t{t.schedule_name or '-'}\t{t.environment}\tAdmin:{t.admin}\tStatus:{t.last_status or 'None'}")
                return 0

            header = f"{'TASK NAME':<24} | {'SCHEDULE':<20} | {'ENV':<11} | {'ADMIN':<5} | {'LAST STATUS':<11} | {'LAST RUN'}"
            print(header)
            print("-" * len(header))
            for t in tasks:
                sched_str = t.schedule_name or "(standalone)"
                admin_str = "Yes" if t.admin else "No"
                stat_str = t.last_status or "Never run"
                last_run = t.last_run_time or "N/A"
                print(f"{t.name:<24} | {sched_str:<20} | {t.environment:<11} | {admin_str:<5} | {stat_str:<11} | {last_run}")
            return 0

        elif tk_cmd == "show":
            t = storage.get_task(args.name)
            if not t:
                print(f"[ERROR] Task '{args.name}' not found.", file=sys.stderr)
                return 1

            if args.format == "json":
                print(_json.dumps(t.to_dict(), indent=2))
                return 0

            print(f"Task Name:    {t.name}")
            print(f"Schedule:     {t.schedule_name or 'None (Standalone)'}")
            print(f"Environment:  {t.environment}")
            print(f"Admin Priv:   {'Yes' if t.admin else 'No'}")
            print(f"Enabled:      {'Yes' if t.enabled else 'No'}")
            print(f"Created At:   {t.created_at}")
            print(f"Updated At:   {t.updated_at}")
            print(f"Last Run:     {t.last_run_time or 'Never'}")
            print(f"Last Status:  {t.last_status or 'N/A'} (Exit Code: {t.last_exit_code})")
            print(f"Duration:     {f'{t.last_duration_sec:.2f}s' if t.last_duration_sec is not None else 'N/A'}")
            print("--- SCRIPT CODE ---")
            print(t.code if t.code else "(empty code block)")
            return 0

        elif tk_cmd == "edit":
            t = storage.get_task(args.name)
            if not t:
                print(f"[ERROR] Task '{args.name}' not found.", file=sys.stderr)
                return 1

            changes = []
            if args.schedule is not None:
                if args.schedule.lower() in ("none", "", "detach"):
                    t.schedule_name = None
                    changes.append("detached from schedule")
                else:
                    if not storage.get_schedule(args.schedule):
                        print(f"[ERROR] Schedule '{args.schedule}' does not exist.", file=sys.stderr)
                        return 1
                    t.schedule_name = args.schedule
                    changes.append(f"linked to schedule '{args.schedule}'")

            if args.env is not None:
                t.environment = args.env
                changes.append(f"env={t.environment}")

            if args.admin:
                t.admin = True
                changes.append("admin=True")
            elif args.no_admin:
                t.admin = False
                changes.append("admin=False")

            if args.command is not None:
                t.code = args.command
                changes.append("updated command code")
            elif args.input_file is not None:
                p = Path(args.input_file)
                if not p.is_file():
                    print(f"[ERROR] Script file '{args.input_file}' not found.", file=sys.stderr)
                    return 1
                t.code = p.read_text(encoding="utf-8", errors="replace")
                changes.append(f"imported script from {args.input_file}")
            elif args.edit:
                t.code = _launch_editor(t.code, suffix=".ps1" if t.environment in ("pwsh", "powershell") else ".sh")
                changes.append("edited code in $EDITOR")

            if args.enable:
                t.enabled = True
                changes.append("enabled=True")
            elif args.disable:
                t.enabled = False
                changes.append("enabled=False")

            if args.rename and args.rename != t.name:
                if storage.get_task(args.rename):
                    print(f"[ERROR] Task '{args.rename}' already exists.", file=sys.stderr)
                    return 1
                old_name = t.name
                t.name = args.rename
                storage.delete_task(old_name)
                changes.append(f"renamed from '{old_name}'")

            storage.save_task(t)
            detail_str = ", ".join(changes) if changes else "no changes"
            service.central_logger.log_task_edit(t.name, detail_str)

            if not args.quiet:
                print(f"[OK] Task '{t.name}' updated: {detail_str}")
            return 0

        elif tk_cmd == "delete":
            t = storage.get_task(args.name)
            if not t:
                print(f"[ERROR] Task '{args.name}' not found.", file=sys.stderr)
                return 1

            if not args.yes:
                resp = input(f"Are you sure you want to delete task '{t.name}'? [y/N]: ")
                if resp.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0

            success = storage.delete_task(t.name)
            if success:
                service.central_logger.log_task_delete(t.name)
                if not args.quiet:
                    print(f"[OK] Task '{t.name}' deleted.")
                return 0
            return 1

        elif tk_cmd == "attach":
            t = storage.get_task(args.name)
            if not t:
                print(f"[ERROR] Task '{args.name}' not found.", file=sys.stderr)
                return 1
            if not storage.get_schedule(args.schedule):
                print(f"[ERROR] Schedule '{args.schedule}' does not exist.", file=sys.stderr)
                return 1

            t.schedule_name = args.schedule
            storage.save_task(t)
            service.central_logger.log_task_attach(t.name, args.schedule)
            if not args.quiet:
                print(f"[OK] Task '{t.name}' attached to schedule '{args.schedule}'.")
            return 0

        elif tk_cmd == "detach":
            t = storage.get_task(args.name)
            if not t:
                print(f"[ERROR] Task '{args.name}' not found.", file=sys.stderr)
                return 1
            t.schedule_name = None
            storage.save_task(t)
            service.central_logger.log_task_detach(t.name)
            if not args.quiet:
                print(f"[OK] Task '{t.name}' detached from schedule.")
            return 0

    # ─────────────────────────────────────────────────────────
    # Run Command
    # ─────────────────────────────────────────────────────────
    elif args.subcommand == "run":
        if not args.task and not args.schedule and not args.all:
            print("[ERROR] Specify either -t/--task, -s/--schedule, or -A/--all to run.", file=sys.stderr)
            return 1

        if args.task:
            res = service.execute_task(args.task, dry_run=args.dry_run)
            if not args.quiet:
                status_str = "SUCCESS" if res.success else f"FAILED (Exit Code {res.exit_code})"
                print(f"[{status_str}] Task: {res.task_name} ({res.duration_sec:.2f}s)")
                if res.stdout:
                    print(res.stdout.rstrip())
                if res.stderr:
                    print(res.stderr.rstrip(), file=sys.stderr)
            return 0 if res.success else res.exit_code

        elif args.schedule:
            results = service.execute_schedule(args.schedule, dry_run=args.dry_run)
            failed = [r for r in results if not r.success]
            if not args.quiet:
                print(f"Executed {len(results)} task(s) for schedule '{args.schedule}'. Failed: {len(failed)}")
            return 1 if failed else 0

        elif args.all:
            results = service.run_once(dry_run=args.dry_run)
            failed = [r for r in results if not r.success]
            if not args.quiet:
                print(f"Evaluated all schedules. Triggered tasks: {len(results)}, Failed: {len(failed)}")
            return 1 if failed else 0

    # ─────────────────────────────────────────────────────────
    # Daemon / Service Command
    # ─────────────────────────────────────────────────────────
    elif args.subcommand == "daemon":
        if args.once:
            results = service.run_once(dry_run=args.dry_run)
            if not args.quiet:
                print(f"Single pass complete. Triggered tasks: {len(results)}")
            return 0
        service.run_daemon(interval_sec=args.interval, dry_run=args.dry_run, max_ticks=args.max_ticks)
        return 0

    # ─────────────────────────────────────────────────────────
    # Logs Command
    # ─────────────────────────────────────────────────────────
    elif args.subcommand == "logs":
        lg_cmd = args.logs_cmd

        if lg_cmd == "system":
            entries = service.central_logger.read_recent_entries(n=args.lines)
            if args.format == "json":
                print(_json.dumps(entries, indent=2))
                return 0
            for line in entries:
                print(line)
            return 0

        elif lg_cmd == "task":
            if args.latest:
                content = service.task_logger.read_latest_run_content(args.name)
                if not content:
                    print(f"No run logs found for task '{args.name}'.")
                    return 0
                print(content)
                return 0

            if args.count is not None and not args.latest:
                runs = service.task_logger.list_task_runs(args.name, count=args.count)
                if not runs:
                    print(f"No execution logs found for task '{args.name}'.")
                    return 0
                print(f"Recent runs for task '{args.name}' (from {service.task_logger.get_task_log_path(args.name)}):")
                for r in runs:
                    print(f"  - Run #{r['run_index']} ({r['timestamp']}, Status: {r['status']}, {r['size_bytes']} bytes)")
                return 0

            # Default: show complete single-file task log
            full_log = service.task_logger.read_task_log(args.name)
            if not full_log or not full_log.strip():
                print(f"No execution logs found for task '{args.name}'.")
                return 0
            print(full_log)
            return 0

        elif lg_cmd == "clear":
            if not args.yes:
                resp = input(f"Are you sure you want to clear '{args.type}' logs? [y/N]: ")
                if resp.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0
            if args.type in ("system", "all"):
                service.central_logger.clear()
            if args.type in ("tasks", "all"):
                service.task_logger.clear_task_logs()
            if not args.quiet:
                print(f"[OK] Cleared {args.type} logs.")
            return 0

    # ─────────────────────────────────────────────────────────
    # Config Command
    # ─────────────────────────────────────────────────────────
    elif args.subcommand == "config":
        cfg_cmd = args.config_cmd
        cfg = storage.get_config()

        if cfg_cmd == "show":
            if args.format == "json":
                print(_json.dumps(cfg.to_dict(), indent=2))
                return 0
            print(f"Configuration File: {storage.data_file}")
            print(f"PowerShell Core (pwsh): {cfg.executables.pwsh or '(not detected)'}")
            print(f"Windows PowerShell:     {cfg.executables.powershell or '(not detected)'}")
            print(f"Default Terminal:       {cfg.executables.terminal or '(not detected)'}")
            print(f"Task Log Retention:     {cfg.log_retention_runs} runs per task")
            print(f"Notifications Enabled:  {cfg.notifications_enabled}")
            print(f"Notify on Run:          {cfg.notify_on_run}")
            print(f"Notify on Success:      {cfg.notify_on_success}")
            print(f"Notify on Failure:      {cfg.notify_on_failure}")
            return 0

        elif cfg_cmd == "set":
            changed = False
            if args.pwsh is not None:
                cfg.executables.pwsh = str(Path(args.pwsh).resolve()) if args.pwsh else ""
                changed = True
            if args.powershell is not None:
                cfg.executables.powershell = str(Path(args.powershell).resolve()) if args.powershell else ""
                changed = True
            if args.terminal is not None:
                cfg.executables.terminal = str(Path(args.terminal).resolve()) if args.terminal else ""
                changed = True
            if args.retention is not None:
                cfg.log_retention_runs = max(1, args.retention)
                changed = True
            if args.notifications is not None:
                cfg.notifications_enabled = args.notifications.lower() in ("on", "true")
                changed = True

            if changed:
                storage.update_config(cfg)
                service.refresh_config()
                if not args.quiet:
                    print("[OK] Configuration updated successfully.")
            else:
                if not args.quiet:
                    print("No configuration parameters specified to update.")
            return 0

        elif cfg_cmd == "detect":
            detected = ConfigManager.detect_executables()
            print("Auto-detected Shell Executables:")
            print(f"  pwsh:       {detected.pwsh or '(not found)'}")
            print(f"  powershell: {detected.powershell or '(not found)'}")
            print(f"  terminal:   {detected.terminal or '(not found)'}")
            if args.apply:
                cfg.executables = detected
                storage.update_config(cfg)
                service.refresh_config()
                print("[OK] Applied detected paths to configuration.")
            else:
                print("Pass -a/--apply to save these paths to configuration.")
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
