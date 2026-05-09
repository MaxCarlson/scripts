"""Argparse CLI for Jellyfin Doctor."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .backup import create_backup, latest_backup, restore_backup, size_report
from .diagnose import diagnose_db, diagnose_logs, diagnose_paths, diagnose_processes
from .monitor import monitor_log, monitor_processes, monitor_scan_file, monitor_startup
from .paths import JellyfinPaths
from .process import start_tray, stop_jellyfin
from .reset import reset_state
from .utils import emit_result


def add_option(parser: argparse.ArgumentParser, short: str, long: str, *args: object, **kwargs: object) -> None:
    """Add a public option with both short and long forms."""
    parser.add_argument(short, long, *args, **kwargs)


def _paths_from_args(args: argparse.Namespace) -> JellyfinPaths:
    return JellyfinPaths.from_overrides(
        server_dir=getattr(args, "server_dir", None),
        install_dir=getattr(args, "install_dir", None),
        data_dir=getattr(args, "data_dir", None),
        log_dir=getattr(args, "log_dir", None),
        tray_exe=getattr(args, "tray_exe", None),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jellyfin-doctor",
        description="Diagnose, monitor, back up, and safely reset Jellyfin.",
    )
    add_option(parser, "-v", "--verbose", action="store_true", help="Enable verbose output.")
    add_option(parser, "-q", "--quiet", action="store_true", help="Reduce human-readable output.")
    add_option(parser, "-n", "--dry-run", action="store_true", help="Show planned changes without mutating files.")
    add_option(parser, "-y", "--yes", action="store_true", help="Confirm high-risk or destructive operations.")
    add_option(parser, "-j", "--json", action="store_true", help="Print JSON output.")
    add_option(parser, "-c", "--config", type=Path, help="Optional configuration file.")
    add_option(
        parser,
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor = subparsers.add_parser("monitor", help="Read-only monitoring commands.")
    monitor_sub = monitor.add_subparsers(dest="monitor_command", required=True)
    scan = monitor_sub.add_parser(
        "scan",
        description="Tail Jellyfin logs and report Scan Media Library completion, failure, or stall.",
    )
    add_option(scan, "-l", "--log-file", type=Path, help="Specific Jellyfin log file.")
    add_option(scan, "-d", "--log-dir", type=Path, help="Jellyfin log directory.")
    add_option(scan, "-a", "--alert", action="store_true", help="Enable requested alert channels.")
    add_option(scan, "-b", "--beep", action="store_true", help="Beep when scan finishes or fails.")
    add_option(scan, "-p", "--popup", action="store_true", help="Show a Windows popup when scan finishes or fails.")
    add_option(scan, "-w", "--watch-seconds", type=float, default=30.0, help="Expected watch interval for live output.")
    add_option(scan, "-t", "--timeout-minutes", type=float, default=0.0, help="Timeout before returning stalled.")
    add_option(scan, "-e", "--error-on-stall", action="store_true", help="Return a non-zero code on stall.")
    add_option(scan, "-r", "--refresh-seconds", type=float, default=2.0, help="Refresh interval.")
    add_option(scan, "-j", "--json", action="store_true", help="Print JSON output.")
    scan.set_defaults(handler=_handle_monitor_scan)

    proc = monitor_sub.add_parser("process", description="Monitor Jellyfin, tray, ffmpeg, and ffprobe process health.")
    add_option(proc, "-r", "--refresh-seconds", type=float, default=5.0, help="Refresh interval.")
    add_option(proc, "-i", "--in-place", action="store_true", help="Render in place.")
    add_option(proc, "-p", "--processes", nargs="+", help="Process names to match.")
    add_option(proc, "-m", "--max-memory-gb", type=float, help="Alert above this RSS size.")
    add_option(proc, "-c", "--cpu-stall-seconds", type=float, help="Mark possibly stalled after unchanged CPU time.")
    add_option(proc, "-a", "--alert", action="store_true", help="Enable alerts.")
    add_option(proc, "-b", "--beep", action="store_true", help="Beep on warnings.")
    add_option(proc, "-j", "--json", action="store_true", help="Print JSON output.")
    proc.set_defaults(handler=_handle_monitor_process)

    startup = monitor_sub.add_parser("startup", description="Monitor startup after a reset.")
    add_option(startup, "-l", "--log-dir", type=Path, help="Jellyfin log directory.")
    add_option(startup, "-t", "--timeout-minutes", type=float, default=5.0, help="Startup timeout.")
    add_option(startup, "-a", "--alert", action="store_true", help="Enable alerts.")
    add_option(startup, "-b", "--beep", action="store_true", help="Beep on startup status.")
    add_option(startup, "-p", "--popup", action="store_true", help="Show popup on startup status.")
    add_option(startup, "-j", "--json", action="store_true", help="Print JSON output.")
    startup.set_defaults(handler=_handle_monitor_startup)

    log = monitor_sub.add_parser("log", description="Tail and filter Jellyfin logs.")
    add_option(log, "-l", "--log-file", type=Path, help="Specific Jellyfin log file.")
    add_option(log, "-d", "--log-dir", type=Path, help="Jellyfin log directory.")
    add_option(log, "-p", "--pattern", help="Regex pattern to match.")
    add_option(log, "-i", "--ignore-case", action="store_true", help="Use case-insensitive matching.")
    add_option(log, "-a", "--alert", action="store_true", help="Enable alerts.")
    add_option(log, "-b", "--beep", action="store_true", help="Beep on match.")
    add_option(log, "-o", "--once", action="store_true", help="Exit after one pass.")
    add_option(log, "-T", "--tail-lines", type=int, default=120, help="Number of lines to read from the end.")
    log.set_defaults(handler=_handle_monitor_log)

    backup = subparsers.add_parser("backup", help="Backup and restore Jellyfin state.")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    sizes = backup_sub.add_parser("sizes", description="Report Jellyfin state and backup sizes.")
    add_option(sizes, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(sizes, "-b", "--backup-dir", type=Path, default=Path.cwd(), help="Backup directory.")
    add_option(sizes, "-r", "--recursive", action="store_true", help="Measure recursively.")
    add_option(sizes, "-j", "--json", action="store_true", help="Print JSON output.")
    sizes.set_defaults(handler=_handle_backup_sizes)

    create = backup_sub.add_parser("create", description="Create a timestamped Jellyfin backup.")
    add_option(create, "-b", "--backup-dir", type=Path, default=Path.cwd(), help="Destination backup directory.")
    add_option(
        create,
        "-m",
        "--mode",
        choices=["db", "cache", "metadata", "root", "config", "full"],
        default="db",
        help="Backup mode.",
    )
    add_option(create, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(create, "-n", "--dry-run", action="store_true", help="Show planned copies without writing files.")
    add_option(create, "-f", "--force", action="store_true", help="Allow forceful behavior where supported.")
    add_option(create, "-j", "--json", action="store_true", help="Print JSON output.")
    create.set_defaults(handler=_handle_backup_create)

    latest = backup_sub.add_parser("latest", description="Show latest Jellyfin backup.")
    add_option(latest, "-b", "--backup-dir", type=Path, default=Path.cwd(), help="Backup directory.")
    add_option(latest, "-j", "--json", action="store_true", help="Print JSON output.")
    latest.set_defaults(handler=_handle_backup_latest)

    restore = backup_sub.add_parser("restore", description="Restore from a Jellyfin backup with explicit confirmation.")
    add_option(restore, "-b", "--backup-path", type=Path, required=True, help="Backup path to restore from.")
    add_option(
        restore,
        "-m",
        "--mode",
        choices=["db", "cache", "metadata", "root", "config", "full"],
        default="db",
        help="Restore mode.",
    )
    add_option(restore, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(restore, "-y", "--yes", action="store_true", help="Confirm restore.")
    add_option(restore, "-n", "--dry-run", action="store_true", help="Show planned restore without writing files.")
    add_option(restore, "-j", "--json", action="store_true", help="Print JSON output.")
    restore.set_defaults(handler=_handle_backup_restore)

    reset = subparsers.add_parser("reset", help="Reversible reset commands.")
    reset_sub = reset.add_subparsers(dest="reset_command", required=True)
    for name in ("cache", "metadata", "db", "state", "full", "root"):
        reset_parser = reset_sub.add_parser(name, description=f"Reset Jellyfin {name} state by renaming files/folders.")
        add_reset_options(reset_parser)
        reset_parser.set_defaults(handler=_handle_reset, reset_kind=name)

    diagnose = subparsers.add_parser("diagnose", help="Diagnose logs, DBs, processes, and paths.")
    diagnose_sub = diagnose.add_subparsers(dest="diagnose_command", required=True)
    dlogs = diagnose_sub.add_parser("logs", description="Analyze recent Jellyfin logs and recommend next action.")
    add_option(dlogs, "-l", "--log-file", type=Path, help="Specific Jellyfin log file.")
    add_option(dlogs, "-d", "--log-dir", type=Path, help="Jellyfin log directory.")
    add_option(dlogs, "-L", "--lines", type=int, default=500, help="Number of recent lines to inspect.")
    add_option(dlogs, "-j", "--json", action="store_true", help="Print JSON output.")
    dlogs.set_defaults(handler=_handle_diagnose_logs)

    ddb = diagnose_sub.add_parser("db", description="Run offline SQLite checks against jellyfin.db.")
    add_option(ddb, "-d", "--database", type=Path, help="Path to jellyfin.db.")
    add_option(ddb, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(ddb, "-f", "--full", action="store_true", help="Run PRAGMA integrity_check in addition to quick_check.")
    add_option(ddb, "-F", "--force", action="store_true", help="Force checks even if safety warnings apply.")
    add_option(ddb, "-j", "--json", action="store_true", help="Print JSON output.")
    ddb.set_defaults(handler=_handle_diagnose_db)

    dproc = diagnose_sub.add_parser("processes", description="Show Jellyfin process tree information.")
    add_option(dproc, "-p", "--processes", nargs="+", help="Process names to match.")
    add_option(dproc, "-j", "--json", action="store_true", help="Print JSON output.")
    dproc.set_defaults(handler=_handle_diagnose_processes)

    dpaths = diagnose_sub.add_parser("paths", description="Show Jellyfin path status.")
    add_option(dpaths, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(dpaths, "-j", "--json", action="store_true", help="Print JSON output.")
    dpaths.set_defaults(handler=_handle_diagnose_paths)

    server = subparsers.add_parser("server", help="Control native Windows Jellyfin.")
    server_sub = server.add_subparsers(dest="server_command", required=True)
    stop = server_sub.add_parser("stop", description="Stop Jellyfin server and tray processes.")
    add_option(stop, "-f", "--force", action="store_true", help="Kill instead of terminate.")
    add_option(stop, "-j", "--json", action="store_true", help="Print JSON output.")
    stop.set_defaults(handler=_handle_server_stop)
    start = server_sub.add_parser("start", description="Start the Jellyfin Windows tray executable.")
    add_option(start, "-t", "--tray-exe", type=Path, help="Path to Jellyfin.Windows.Tray.exe.")
    add_option(start, "-m", "--monitor", action="store_true", help="Monitor startup after starting.")
    add_option(start, "-j", "--json", action="store_true", help="Print JSON output.")
    start.set_defaults(handler=_handle_server_start)
    restart = server_sub.add_parser("restart", description="Restart Jellyfin and optionally monitor startup.")
    add_option(restart, "-f", "--force", action="store_true", help="Kill instead of terminate.")
    add_option(restart, "-m", "--monitor", action="store_true", help="Monitor startup after restart.")
    add_option(restart, "-w", "--wait-seconds", type=float, default=2.0, help="Seconds to wait between stop and start.")
    add_option(restart, "-j", "--json", action="store_true", help="Print JSON output.")
    restart.set_defaults(handler=_handle_server_restart)

    library = subparsers.add_parser("library", help="Library rebuild guidance.")
    library_sub = library.add_subparsers(dest="library_command", required=True)
    plan = library_sub.add_parser("plan", description="Print safe library rebuild guidance.")
    add_option(plan, "-p", "--path", type=Path, required=True, help="Library root path.")
    add_option(plan, "-n", "--name", help="Library name.")
    add_option(plan, "-t", "--type", default="Home Videos and Photos", help="Jellyfin content type.")
    add_option(plan, "-j", "--json", action="store_true", help="Print JSON output.")
    plan.set_defaults(handler=_handle_library_plan)
    scan_watch = library_sub.add_parser("scan-watch", description="Alias for monitor scan.")
    add_option(scan_watch, "-l", "--log-file", type=Path, help="Specific Jellyfin log file.")
    add_option(scan_watch, "-d", "--log-dir", type=Path, help="Jellyfin log directory.")
    add_option(scan_watch, "-a", "--alert", action="store_true", help="Enable alerts.")
    add_option(scan_watch, "-b", "--beep", action="store_true", help="Beep on scan status.")
    add_option(scan_watch, "-p", "--popup", action="store_true", help="Popup on scan status.")
    add_option(scan_watch, "-t", "--timeout-minutes", type=float, default=0.0, help="Timeout before returning stalled.")
    add_option(scan_watch, "-j", "--json", action="store_true", help="Print JSON output.")
    scan_watch.set_defaults(handler=_handle_monitor_scan)

    return parser


def add_reset_options(parser: argparse.ArgumentParser) -> None:
    add_option(parser, "-s", "--server-dir", type=Path, help="Jellyfin server directory.")
    add_option(parser, "-b", "--backup-dir", type=Path, default=Path.cwd(), help="Backup directory.")
    add_option(parser, "-y", "--yes", action="store_true", help="Confirm high-risk reset.")
    add_option(parser, "-n", "--dry-run", action="store_true", help="Show planned reset without mutating files.")
    add_option(parser, "-f", "--force", action="store_true", help="Proceed when Jellyfin is running.")
    add_option(parser, "-N", "--no-backup", action="store_true", help="Skip automatic backup.")
    add_option(parser, "-S", "--start-after", action="store_true", help="Start Jellyfin after reset.")
    add_option(parser, "-m", "--monitor-after", action="store_true", help="Monitor startup after reset.")
    add_option(parser, "-j", "--json", action="store_true", help="Print JSON output.")


def _handle_monitor_scan(args: argparse.Namespace) -> int:
    result = monitor_scan_file(
        log_file=getattr(args, "log_file", None),
        log_dir=getattr(args, "log_dir", None),
        timeout_minutes=getattr(args, "timeout_minutes", 0.0),
        alert=getattr(args, "alert", False),
        beep=getattr(args, "beep", False),
        popup=getattr(args, "popup", False),
    )
    emit_result(result, json_output=getattr(args, "json", False))
    return int(result.get("exit_code", 0))


def _handle_monitor_process(args: argparse.Namespace) -> int:
    result = monitor_processes(
        processes=args.processes,
        refresh_seconds=args.refresh_seconds,
        in_place=args.in_place,
        max_memory_gb=args.max_memory_gb,
        cpu_stall_seconds=args.cpu_stall_seconds,
    )
    emit_result(result, json_output=args.json)
    return 0


def _handle_monitor_startup(args: argparse.Namespace) -> int:
    result = monitor_startup(
        log_dir=getattr(args, "log_dir", None),
        timeout_minutes=getattr(args, "timeout_minutes", 5.0),
        alert=getattr(args, "alert", False),
        beep=getattr(args, "beep", False),
        popup=getattr(args, "popup", False),
    )
    emit_result(result, json_output=args.json)
    return int(result.get("exit_code", 0))


def _handle_monitor_log(args: argparse.Namespace) -> int:
    result = monitor_log(
        log_file=args.log_file,
        log_dir=args.log_dir,
        pattern=args.pattern,
        ignore_case=args.ignore_case,
        tail_lines=args.tail_lines,
        once=args.once,
        alert=args.alert,
        beep=args.beep,
    )
    emit_result(result, json_output=False)
    return int(result.get("exit_code", 0))


def _handle_backup_sizes(args: argparse.Namespace) -> int:
    emit_result(size_report(_paths_from_args(args), args.backup_dir), json_output=args.json)
    return 0


def _handle_backup_create(args: argparse.Namespace) -> int:
    result = create_backup(
        paths=_paths_from_args(args),
        backup_dir=args.backup_dir,
        mode=args.mode,
        dry_run=args.dry_run,
    )
    emit_result(result, json_output=args.json)
    return 0


def _handle_backup_latest(args: argparse.Namespace) -> int:
    emit_result({"latest_backup": latest_backup(args.backup_dir)}, json_output=args.json)
    return 0


def _handle_backup_restore(args: argparse.Namespace) -> int:
    result = restore_backup(
        backup_path=args.backup_path,
        paths=_paths_from_args(args),
        mode=args.mode,
        dry_run=args.dry_run,
        yes=args.yes,
    )
    emit_result(result, json_output=args.json)
    return 0


def _handle_reset(args: argparse.Namespace) -> int:
    result = reset_state(
        paths=_paths_from_args(args),
        kind=args.reset_kind,
        backup_dir=args.backup_dir,
        dry_run=args.dry_run,
        yes=args.yes,
        force=args.force,
        no_backup=args.no_backup,
        start_after=args.start_after,
    )
    emit_result(result, json_output=args.json)
    if args.monitor_after:
        _handle_monitor_startup(args)
    return 0


def _handle_diagnose_logs(args: argparse.Namespace) -> int:
    emit_result(diagnose_logs(log_file=args.log_file, log_dir=args.log_dir, lines=args.lines), json_output=args.json)
    return 0


def _handle_diagnose_db(args: argparse.Namespace) -> int:
    paths = _paths_from_args(args)
    database = args.database or paths.data_dir / "jellyfin.db"
    emit_result(diagnose_db(database=database, full=args.full, force=args.force), json_output=args.json)
    return 0


def _handle_diagnose_processes(args: argparse.Namespace) -> int:
    emit_result(diagnose_processes(args.processes), json_output=args.json)
    return 0


def _handle_diagnose_paths(args: argparse.Namespace) -> int:
    emit_result(diagnose_paths(_paths_from_args(args)), json_output=args.json)
    return 0


def _handle_server_stop(args: argparse.Namespace) -> int:
    emit_result(stop_jellyfin(force=args.force), json_output=args.json)
    return 0


def _handle_server_start(args: argparse.Namespace) -> int:
    paths = _paths_from_args(args)
    result = start_tray(paths.tray_exe)
    emit_result(result, json_output=args.json)
    if args.monitor:
        _handle_monitor_startup(args)
    return 0 if result.get("started") else 1


def _handle_server_restart(args: argparse.Namespace) -> int:
    import time

    stop_result = stop_jellyfin(force=args.force)
    time.sleep(args.wait_seconds)
    start_result = start_tray(JellyfinPaths().tray_exe)
    emit_result({"stop": stop_result, "start": start_result}, json_output=args.json)
    return 0 if start_result.get("started") else 1


def _handle_library_plan(args: argparse.Namespace) -> int:
    result = {
        "name": args.name or args.path.name,
        "type": args.type,
        "path": args.path,
        "recommended_settings": {
            "realtime_monitoring": "off initially",
            "trickplay": "off initially",
            "chapter_image_extraction": "off initially",
            "subtitle_downloads": "off initially",
            "metadata_downloads": "off initially",
            "screen_grabber": "off initially",
        },
        "workflow": [
            "Add one root path only.",
            "Let scan finish.",
            "Open library.",
            "Add second root as a separate library.",
            "Only combine later if both work independently.",
        ],
    }
    emit_result(result, json_output=args.json)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    return int(args.handler(args))
