"""Command-line interface for ProcWatch (Phase 2: live guard + persistent flight recorder)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import queue
import sys
import time
from typing import Sequence

from procwatch import __version__
from procwatch.analyzers.ast_scanner import apply_proposed_fixes, scan_directory
from procwatch.analyzers.patterns import analyze_patterns
from procwatch.analyzers.task_auditor import run_audit
from procwatch.collectors.sysmon_evt import SysmonCollector
from procwatch.collectors.task_events import TaskSchedulerCollector
from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent, WmiProcessTraceCollector
from procwatch.config import (
    DEFAULT_AUTOMATION_TITLE_PATTERN,
    ConfigValidationError,
    GuardConfig,
    GuardMode,
    StorageConfig,
    WatchConfig,
    compile_optional_regex,
    get_data_dir,
)
from procwatch.correlator.ancestry import ProcessTableCache, get_boot_id
from procwatch.correlator.engine import LiveCorrelator
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import CollectorStats, RunStatus
from procwatch.mutex import CollectorAlreadyRunningError, CollectorMutex
from procwatch.renderers.console import (
    ConsoleRenderer,
    render_analyze_report,
    render_audit_report,
    render_explain_detail,
    render_history_rows,
    render_scan_report,
)
from procwatch.renderers.doctor_view import collect_doctor_report, render_doctor_report
from procwatch.runner.supervisor import execute as run_supervised
from procwatch.storage import FlightRecorderStorage


def _parse_time_window_utc(spec: str | None) -> str | None:
    """Convert relative durations like '24h', '30m', '7d' into a UTC ISO-8601 cutoff."""
    if not spec:
        return None
    raw = spec.strip().lower()
    if raw.endswith("s"):
        delta = timedelta(seconds=float(raw[:-1]))
    elif raw.endswith("m"):
        delta = timedelta(minutes=float(raw[:-1]))
    elif raw.endswith("h"):
        delta = timedelta(hours=float(raw[:-1]))
    elif raw.endswith("d"):
        delta = timedelta(days=float(raw[:-1]))
    else:
        raise ConfigValidationError(
            f"Invalid time window {spec!r}. Use e.g. '30m', '24h', or '7d'."
        )
    cutoff = datetime.now(UTC) - delta
    return cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase 2 CLI argument parser."""
    epilog = (
        "Distinctions:\n"
        "  Window Owner       Process owning the HWND (often WindowsTerminal.exe).\n"
        "  Suspected Cause    Candidate initiating process correlated by timing/ancestry.\n"
        "\n"
        "Examples:\n"
        "  procwatch watch -g -m all-consoles\n"
        "      Stream live events while minimizing every newly created console/terminal\n"
        "      window so background popups do not disrupt your active work.\n"
        "  procwatch guard -m all-consoles\n"
        "      Low-overhead subset of `procwatch watch -g -m all-consoles` that runs\n"
        "      only the window-suppression loop without printing the full event stream.\n"
        "  procwatch watch -p -c\n"
        "      Observe popup/window events in read-only mode with burst collapsing.\n"
        "  procwatch doctor -v\n"
        "      Inspect collector availability, terminal delegation, and DB health.\n"
        "  procwatch history -t 24h -p\n"
        "      List popup/guard incidents recorded over the last 24 hours.\n"
        "  procwatch scan -d . -u\n"
        "      Scan Python/PowerShell files for popup-launching patterns with diffs.\n"
        "  procwatch exec -- python -m pytest -q\n"
        "      Run a command headlessly inside a Windows Job Object (no popup console).\n"
        "\n"
        "Run `procwatch <command> -h` for subcommand options and examples."
    )
    parser = argparse.ArgumentParser(
        prog="procwatch",
        description="Windows 11 console popup guard, flight recorder, static/task auditor, pattern analyzer, and headless supervisor.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # 1. `procwatch watch`
    watch_p = subparsers.add_parser(
        "watch",
        help="Live stream of process and window events (read-only unless -g is set).",
        description="Observe transient console/terminal windows and process starts/stops in real time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch watch\n"
            "      Read-only live stream of window and process events.\n"
            "  procwatch watch -g -m all-consoles\n"
            "      Watch live events while minimizing every newly created console/terminal\n"
            "      window so popups do not disrupt you (`procwatch guard -m all-consoles`\n"
            "      is the low-overhead subset without live event streaming).\n"
            "  procwatch watch -g -m smart -p -c\n"
            "      Suppress only automation-like popups, show popup events, collapse bursts.\n"
            "  procwatch watch -s -f \"python|pwsh\" -o .\\events.jsonl\n"
            "      Include headless conhost 0x4 spawns, filter by regex, and save JSONL."
        ),
    )
    watch_p.add_argument(
        "-p",
        "--popups-only",
        action="store_true",
        help="Display only events that created a window or matched popup heuristics.",
    )
    watch_p.add_argument(
        "-g",
        "--guard-windows",
        action="store_true",
        help="Enable active NeutralizeEngine window suppression while watching.",
    )
    watch_p.add_argument(
        "-m",
        "--guard-mode",
        choices=[GuardMode.OBSERVE.value, GuardMode.SMART.value, GuardMode.ALL_CONSOLES.value],
        default=GuardMode.OBSERVE.value,
        help="Guard policy when -g is active (default: observe).",
    )
    watch_p.add_argument(
        "-c",
        "--collapse-bursts",
        action="store_true",
        help="Collapse repetitive process bursts into rolling counters.",
    )
    watch_p.add_argument(
        "-s",
        "--show-headless",
        action="store_true",
        help="Include headless conhost.exe 0x4 spawns in output.",
    )
    watch_p.add_argument(
        "-f",
        "--filter-regex",
        type=str,
        default=None,
        help="Filter output by window title/class, command line, or ancestor name.",
    )
    watch_p.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=None,
        help="Append redacted JSONL events to disk.",
    )

    # 2. `procwatch guard`
    guard_p = subparsers.add_parser(
        "guard",
        help="Dedicated low-overhead window guard loop (defaults to observe mode).",
        description="Intercept newly created console/terminal popup windows without interfering with interactive terminals.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch guard\n"
            "      Dry-run observe mode: log would-be interceptions without hiding windows.\n"
            "  procwatch guard -m all-consoles\n"
            "      Minimize every newly created console window and restore foreground focus.\n"
            "      This is the low-overhead subset of `procwatch watch -g -m all-consoles`.\n"
            "  procwatch guard -m smart -e \"Interactive|Admin\"\n"
            "      Suppress automation-matching console titles while protecting excluded titles.\n"
            "  pythonw.exe -m procwatch guard -m smart -q -o .\\guard.jsonl\n"
            "      Run silently in the background and append redacted JSONL events to disk."
        ),
    )
    guard_p.add_argument(
        "-m",
        "--mode",
        choices=[
            GuardMode.OBSERVE.value,
            GuardMode.SMART.value,
            GuardMode.ALL_CONSOLES.value,
            GuardMode.ALL_WINDOWS.value,
        ],
        default=GuardMode.OBSERVE.value,
        help="Suppression policy (default: observe; all-windows is experimental/unsafe).",
    )
    guard_p.add_argument(
        "-n",
        "--no-focus-restore",
        action="store_true",
        help="Minimize intercepted windows without restoring foreground focus.",
    )
    guard_p.add_argument(
        "-t",
        "--title-pattern",
        type=str,
        default=DEFAULT_AUTOMATION_TITLE_PATTERN,
        help="Regex of window titles to suppress in smart mode.",
    )
    guard_p.add_argument(
        "-e",
        "--exclude-pattern",
        type=str,
        default=None,
        help="Regex of window titles to never suppress.",
    )
    guard_p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress console log output (for background pythonw.exe usage).",
    )
    guard_p.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=None,
        help="Append redacted JSONL window events to disk.",
    )
    for live_p in (watch_p, guard_p):
        live_p.add_argument(
            "-d",
            "--db-path",
            type=Path,
            default=None,
            help="Override SQLite flight recorder DB path (default ~/.procwatch/events.db).",
        )
        live_p.add_argument(
            "-P",
            "--no-persist",
            action="store_true",
            help="Disable SQLite flight recorder persistence during this live session.",
        )

    doctor_p = subparsers.add_parser(
        "doctor",
        help="Check collector availability, terminal delegation, privileges, and DB health (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch doctor\n"
            "      Run a quick read-only check of collectors, privileges, and DB status.\n"
            "  procwatch doctor -v\n"
            "      Show detailed collector states (WinEvent, WMI, Sysmon, TaskScheduler)\n"
            "      and any recorded ingest gaps.\n"
            "  procwatch doctor -j -d C:\\path\\to\\events.db\n"
            "      Emit machine-readable JSON diagnostics for a specific SQLite DB."
        ),
    )
    doctor_p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Include detailed collector states and ingest gaps.",
    )
    doctor_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit diagnostics as JSON.",
    )
    doctor_p.add_argument(
        "-d",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )

    history_p = subparsers.add_parser(
        "history",
        help="Query persisted flight recorder incidents and optionally export a redacted bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch history\n"
            "      Show up to 50 incidents recorded in the last 24 hours.\n"
            "  procwatch history -t 7d -p -l 100\n"
            "      List up to 100 popup/guard incidents from the past 7 days.\n"
            "  procwatch history -t 2h -r -a codex\n"
            "      Replay matching incidents chronologically for `codex` agent runs.\n"
            "  procwatch history -t 24h -e .\\bundle.json\n"
            "      Export a secret-redacted JSON diagnostic bundle to disk."
        ),
    )
    history_p.add_argument(
        "-t",
        "--time-window",
        default="24h",
        help="Lookback window (e.g. '30m', '24h', '7d'; default '24h').",
    )
    history_p.add_argument(
        "-p",
        "--popups-only",
        action="store_true",
        help="Show only popup/guard incidents.",
    )
    history_p.add_argument(
        "-a",
        "--agent-filter",
        default=None,
        help="Filter incidents by attributed agent kind (e.g. 'codex', 'claude_code').",
    )
    history_p.add_argument(
        "-r",
        "--replay-timeline",
        action="store_true",
        help="Render matching incidents in chronological replay order.",
    )
    history_p.add_argument(
        "-e",
        "--export-bundle",
        type=Path,
        default=None,
        help="Write a redacted JSON diagnostic bundle to this path.",
    )
    history_p.add_argument(
        "-l",
        "--limit",
        type=int,
        default=50,
        help="Maximum number of incidents to display (default 50).",
    )
    history_p.add_argument(
        "-d",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )

    explain_p = subparsers.add_parser(
        "explain",
        help="Explain causal evidence edges and ancestry for an incident ID or PID.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch explain -i 42\n"
            "      Show causal evidence edges, window owner, and ancestry for incident 42.\n"
            "  procwatch explain -p 12345\n"
            "      Inspect recorded ancestry and linked incidents for PID 12345.\n"
            "  procwatch explain -i 42 -j -d C:\\path\\to\\events.db\n"
            "      Emit JSON causal attribution from a specific flight recorder DB."
        ),
    )
    explain_p.add_argument(
        "-i",
        "--incident-id",
        type=int,
        default=None,
        help="Incident ID from `procwatch history`.",
    )
    explain_p.add_argument(
        "-p",
        "--pid",
        type=int,
        default=None,
        help="Process ID to explain.",
    )
    explain_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit explanation details as JSON.",
    )
    explain_p.add_argument(
        "-d",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )

    mark_p = subparsers.add_parser(
        "mark",
        help="Record a timestamped user bookmark for manual popup correlation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch mark -l \"flash during git pull\"\n"
            "      Save a bookmark correlating events from the last 3 seconds.\n"
            "  procwatch mark -l \"modal console flash\" -w 10.0 -j\n"
            "      Correlate over a 10-second lookback window and output JSON."
        ),
    )
    mark_p.add_argument(
        "-l",
        "--label",
        required=True,
        help="Descriptive label for the observed popup or event.",
    )
    mark_p.add_argument(
        "-w",
        "--window-seconds",
        type=float,
        default=3.0,
        help="Correlation lookback window in seconds (default 3.0).",
    )
    mark_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit created bookmark as JSON.",
    )
    mark_p.add_argument(
        "-d",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )

    scan_p = subparsers.add_parser(
        "scan",
        help="Scan Python and PowerShell codebases for unintended console-launching patterns (read-only by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch scan -d C:\\path\\to\\repo\n"
            "      Read-only scan of Python and PowerShell files for popup-launching calls.\n"
            "  procwatch scan -d C:\\path\\to\\repo -w -u\n"
            "      Include active git worktrees and preview unified diffs for safe fixes.\n"
            "  procwatch scan -d C:\\path\\to\\repo -a\n"
            "      Apply verified safe Python patches with backups (skips dirty git files).\n"
            "  procwatch scan -d C:\\path\\to\\repo -j\n"
            "      Emit machine-readable JSON scan findings."
        ),
    )
    scan_p.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory or file to scan (default: current working directory).",
    )
    scan_p.add_argument(
        "-w",
        "--include-worktrees",
        action="store_true",
        help="Also discover and scan active git worktrees via `git worktree list --porcelain`.",
    )
    scan_p.add_argument(
        "-u",
        "--unified-diff",
        action="store_true",
        help="Print reviewable unified diffs for safe Python remediation candidates.",
    )
    scan_p.add_argument(
        "-a",
        "--apply-fixes",
        action="store_true",
        help="Explicitly apply verified safe Python patches (creates backups; skips dirty files without --force).",
    )
    scan_p.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow --apply-fixes on files with uncommitted git changes (still creates backups).",
    )
    scan_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit scan report as JSON.",
    )
    scan_p.add_argument(
        "-D",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path for incident linking.",
    )

    audit_p = subparsers.add_parser(
        "audit",
        help="Audit Scheduled Tasks, Startup folders, Registry Run keys, and Default Terminal (read-only by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch audit\n"
            "      Read-only audit of Scheduled Tasks, Startup folders, Run keys, and Default Terminal.\n"
            "  procwatch audit -t tasks -n \"Backup\"\n"
            "      Audit only Scheduled Tasks whose name or path contains `Backup`.\n"
            "  procwatch audit -t defterm -j\n"
            "      Inspect Windows Default Terminal delegation settings as JSON."
        ),
    )
    audit_p.add_argument(
        "-t",
        "--target-type",
        choices=["all", "tasks", "startup", "defterm"],
        default="all",
        help="Audit scope (default: all).",
    )
    audit_p.add_argument(
        "-n",
        "--task-name",
        default=None,
        help="Filter Scheduled Tasks by path/name substring.",
    )
    audit_p.add_argument(
        "-a",
        "--apply-task-fix",
        action="store_true",
        help="Preview-only notice in Phase 3 (live system task mutation requires explicit task XML backup flow).",
    )
    audit_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit audit report as JSON.",
    )
    audit_p.add_argument(
        "-D",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path for task/popup correlation.",
    )

    analyze_p = subparsers.add_parser(
        "analyze",
        help="Detect recurring process/popup bursts and compare coverage-normalized baselines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch analyze\n"
            "      Compare the last 1 hour of recorded events against a 24-hour baseline.\n"
            "  procwatch analyze -p -b 7d -w 1800\n"
            "      Filter to periodic/bursty signatures comparing the last 30m to a 7d baseline.\n"
            "  procwatch analyze -j -D C:\\path\\to\\events.db\n"
            "      Emit JSON periodicity/baseline analysis from a specific SQLite DB."
        ),
    )
    analyze_p.add_argument(
        "-p",
        "--periodicity",
        action="store_true",
        help="Filter output to periodic/bursty signatures.",
    )
    analyze_p.add_argument(
        "-b",
        "--baseline-window",
        default="24h",
        help="Baseline lookback duration before current window (e.g. '24h', '7d'; default '24h').",
    )
    analyze_p.add_argument(
        "-w",
        "--window-seconds",
        type=float,
        default=3600.0,
        help="Current comparison window duration in seconds (default 3600.0).",
    )
    analyze_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit analysis report as JSON.",
    )
    analyze_p.add_argument(
        "-D",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )

    exec_p = subparsers.add_parser(
        "exec",
        help="Run a background command under Windows Job Object supervision without opening a popup console.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  procwatch exec -- python -m pytest -q\n"
            "      Run headlessly inside a Windows Job Object with no popup console.\n"
            "  procwatch exec -t 30 -w C:\\path\\to\\repo -- git status\n"
            "      Run in a target working directory and kill the process tree after 30s.\n"
            "  procwatch exec -j -k -- pwsh -NoProfile -File .\\build.ps1\n"
            "      Emit structured RunResult JSON and log stderr diagnostics on failure.\n"
            "  procwatch exec -p inherited-console -- cmd /c echo ok\n"
            "      Share the caller's existing console while keeping Job Object containment."
        ),
    )
    exec_p.add_argument(
        "-c",
        "--command",
        dest="command_argv",
        nargs="+",
        default=None,
        help="Executable and arguments to run (or pass after '--').",
    )
    exec_p.add_argument(
        "-w",
        "--working-dir",
        type=Path,
        default=None,
        help="Working directory for the supervised child process.",
    )
    exec_p.add_argument(
        "-t",
        "--timeout-seconds",
        type=float,
        default=None,
        help="Terminate the supervised Job Object if execution exceeds this many seconds.",
    )
    exec_p.add_argument(
        "-k",
        "--keep-console-on-error",
        action="store_true",
        help="Emit a non-intrusive stderr failure diagnostic on nonzero/timeout exit (never opens a popup console).",
    )
    exec_p.add_argument(
        "-p",
        "--profile",
        choices=["headless", "inherited-console"],
        default="headless",
        help="Execution profile (default: headless).",
    )
    exec_p.add_argument(
        "-m",
        "--max-output-bytes",
        type=int,
        default=262_144,
        help="Maximum captured bytes per stream before truncation (default: 262144).",
    )
    exec_p.add_argument(
        "-j",
        "--json-output",
        action="store_true",
        help="Emit structured RunResult JSON.",
    )
    exec_p.add_argument(
        "-D",
        "--db-path",
        type=Path,
        default=None,
        help="Override SQLite flight recorder DB path.",
    )
    exec_p.add_argument(
        "-P",
        "--no-persist",
        action="store_true",
        help="Disable SQLite flight recorder persistence for this run.",
    )
    exec_p.add_argument(
        "remainder",
        nargs=argparse.REMAINDER,
        help="Command and arguments after '--'.",
    )

    return parser


def _run_live_session(
    *,
    command: str,
    guard_config: GuardConfig,
    watch_config: WatchConfig,
    renderer: ConsoleRenderer,
    db_path: Path | None = None,
    no_persist: bool = False,
) -> int:
    """Run the single-owner live WinEvent + WMI + Correlator loop until Ctrl+C."""
    if sys.platform != "win32":
        print("Error: procwatch live window/process collection requires Windows (win32).", file=sys.stderr)
        return 2

    mutex = CollectorMutex(mode=guard_config.mode.value, command=command)
    try:
        mutex.acquire()
    except CollectorAlreadyRunningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    storage: FlightRecorderStorage | None = None
    if not no_persist:
        try:
            storage = FlightRecorderStorage(db_path=db_path)
        except Exception as exc:
            if not guard_config.quiet:
                print(f"Warning: flight recorder persistence disabled ({exc}).", file=sys.stderr)

    stats = CollectorStats()
    win_queue: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=watch_config.event_queue_maxsize)
    wmi_queue: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=watch_config.event_queue_maxsize)

    cache = ProcessTableCache(
        max_entries=watch_config.process_cache_max_entries,
        ttl_seconds=watch_config.process_cache_ttl_seconds,
    )
    seeded = cache.seed_from_snapshot()

    win_collector = WinEventCollector(guard_config=guard_config, event_queue=win_queue, stats=stats)
    wmi_collector = WmiProcessTraceCollector(event_queue=wmi_queue, stats=stats)
    wmi_status = wmi_collector.start()

    sysmon_collector: SysmonCollector | None = None
    task_collector: TaskSchedulerCollector | None = None
    if storage is not None:
        boot_id = get_boot_id()
        sysmon_collector = SysmonCollector(storage, boot_id=boot_id)
        task_collector = TaskSchedulerCollector(storage, boot_id=boot_id)

    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_queue,
        wmi_queue=wmi_queue,
        watch_config=watch_config,
        stats=stats,
        on_incident=renderer.render,
        wmi_missing_reason=wmi_collector.missing_reason,
        storage=storage,
    )

    if not guard_config.quiet:
        print(
            f"ProcWatch {command} active (mode={guard_config.mode.value}, "
            f"seeded_procs={seeded}, wmi_trace={wmi_status}). Press Ctrl+C to stop.",
            flush=True,
        )
        if wmi_collector.last_error:
            print(f"Note: {wmi_collector.last_error}", flush=True)

    try:
        win_collector.start()
        correlator.start()
        if sysmon_collector is not None:
            sysmon_collector.start()
        if task_collector is not None:
            task_collector.start()
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        if not guard_config.quiet:
            print("\nStopping ProcWatch...", flush=True)
    finally:
        if task_collector is not None:
            task_collector.stop()
        if sysmon_collector is not None:
            sysmon_collector.stop()
        correlator.stop()
        win_collector.stop()
        wmi_collector.stop()
        renderer.close()
        if storage is not None:
            storage.close()
        mutex.release()

    if not guard_config.quiet:
        print(
            f"Stopped. win_events={stats.win_events_received} (dropped={stats.win_events_dropped}), "
            f"suppressed={stats.guard_suppressed_count}, allowed={stats.guard_allowed_count}, "
            f"pending={stats.guard_pending_count}, wmi_starts={stats.wmi_starts_received}.",
            flush=True,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `procwatch`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "watch":
            effective_mode = GuardMode(args.guard_mode) if args.guard_windows else GuardMode.OBSERVE
            guard_cfg = GuardConfig(mode=effective_mode)
            watch_cfg = WatchConfig(
                popups_only=args.popups_only,
                guard_windows=args.guard_windows,
                guard_mode=effective_mode,
                collapse_bursts=args.collapse_bursts,
                show_headless=args.show_headless,
                filter_regex=compile_optional_regex(args.filter_regex),
                output_file=args.output_file,
            )
            renderer = ConsoleRenderer(
                popups_only=watch_cfg.popups_only,
                collapse_bursts=watch_cfg.collapse_bursts,
                show_headless=watch_cfg.show_headless,
                filter_regex=watch_cfg.filter_regex,
                output_file=watch_cfg.output_file,
            )
            return _run_live_session(
                command="watch",
                guard_config=guard_cfg,
                watch_config=watch_cfg,
                renderer=renderer,
                db_path=args.db_path,
                no_persist=args.no_persist,
            )

        if args.command == "guard":
            mode = GuardMode(args.mode)
            title_re = compile_optional_regex(args.title_pattern)
            if title_re is None:
                raise ConfigValidationError("--title-pattern cannot be empty.")
            guard_cfg = GuardConfig(
                mode=mode,
                restore_focus=not args.no_focus_restore,
                title_pattern=title_re,
                exclude_pattern=compile_optional_regex(args.exclude_pattern),
                allow_all_windows_experimental=(mode == GuardMode.ALL_WINDOWS),
                quiet=args.quiet,
            )
            watch_cfg = WatchConfig(
                popups_only=True,
                guard_windows=(mode != GuardMode.OBSERVE),
                guard_mode=mode,
                output_file=args.output_file,
            )
            renderer = ConsoleRenderer(
                popups_only=True,
                output_file=watch_cfg.output_file,
                quiet=guard_cfg.quiet,
            )
            return _run_live_session(
                command="guard",
                guard_config=guard_cfg,
                watch_config=watch_cfg,
                renderer=renderer,
                db_path=args.db_path,
                no_persist=args.no_persist,
            )

        if args.command == "doctor":
            report = collect_doctor_report(db_path=args.db_path, verbose=args.verbose)
            render_doctor_report(report, json_output=args.json_output, verbose=args.verbose)
            return 0

        if args.command == "history":
            since_utc = _parse_time_window_utc(args.time_window)
            resolved_db = (args.db_path or StorageConfig().resolved_db_path(get_data_dir())).expanduser()
            if not resolved_db.exists():
                if args.export_bundle is not None:
                    args.export_bundle.write_text(
                        json.dumps({"incidents": [], "note": "flight recorder db not initialized"}, indent=2),
                        encoding="utf-8",
                    )
                render_history_rows([], replay_timeline=args.replay_timeline)
                return 0
            storage = FlightRecorderStorage(resolved_db, read_only=True)
            try:
                rows = storage.query_history(
                    since_utc=since_utc,
                    popups_only=args.popups_only,
                    agent_filter=args.agent_filter,
                    limit=args.limit,
                )
                if args.export_bundle is not None:
                    bundle = storage.export_bundle(
                        since_utc=since_utc,
                        popups_only=args.popups_only,
                        agent_filter=args.agent_filter,
                    )
                    args.export_bundle.parent.mkdir(parents=True, exist_ok=True)
                    args.export_bundle.write_text(
                        json.dumps(bundle, indent=2, default=str),
                        encoding="utf-8",
                    )
            finally:
                storage.close()
            render_history_rows(rows, replay_timeline=args.replay_timeline)
            return 0

        if args.command == "explain":
            if args.incident_id is None and args.pid is None:
                raise ConfigValidationError("Specify either --incident-id (-i) or --pid (-p).")
            resolved_db = (args.db_path or StorageConfig().resolved_db_path(get_data_dir())).expanduser()
            if not resolved_db.exists():
                print("Error: flight recorder DB does not exist yet.", file=sys.stderr)
                return 1
            storage = FlightRecorderStorage(resolved_db, read_only=True)
            try:
                detail: dict[str, object] | None = None
                if args.incident_id is not None:
                    detail = storage.get_incident_detail(args.incident_id)
                elif args.pid is not None:
                    proc = storage.get_process_by_pid(args.pid)
                    if proc is not None:
                        edges = storage.get_edges_for_node(str(proc["proc_key"]))
                        detail = {"process": proc, "edges": edges}
            finally:
                storage.close()
            if detail is None:
                print("No matching incident or process found.", file=sys.stderr)
                return 1
            render_explain_detail(detail, json_output=args.json_output)
            return 0

        if args.command == "mark":
            storage = FlightRecorderStorage(db_path=args.db_path)
            try:
                bm = storage.add_user_mark(args.label, window_seconds=args.window_seconds)
            finally:
                storage.close()
            if args.json_output:
                print(
                    json.dumps(
                        {
                            "bookmark_id": bm.bookmark_id,
                            "ts_utc": bm.ts_utc,
                            "label": bm.label,
                            "window_seconds": args.window_seconds,
                            "matched_incident_ids": bm.matched_incident_ids,
                        },
                        indent=2,
                    )
                )
            else:
                print(
                    f"Bookmark #{bm.bookmark_id} recorded at {bm.ts_utc}: "
                    f"{bm.label!r} (matched_incidents={bm.matched_incident_ids})"
                )
            return 0

        if args.command == "scan":
            report = scan_directory(
                args.directory,
                include_worktrees=args.include_worktrees,
                generate_diffs=True,
                db_path=args.db_path,
            )
            payload = report.to_dict()
            if args.apply_fixes:
                payload["apply_result"] = apply_proposed_fixes(
                    report,
                    apply_fixes=True,
                    force=args.force,
                )
            render_scan_report(
                payload,
                show_diff=args.unified_diff,
                json_output=args.json_output,
            )
            return 0

        if args.command == "audit":
            report = run_audit(
                target_type=args.target_type,
                task_name=args.task_name,
                db_path=args.db_path,
            )
            payload = report.to_dict()
            if args.apply_task_fix:
                payload["apply_notice"] = (
                    "Read-only audit complete; live system tasks are never mutated automatically. "
                    "Use `apply_task_fix_preview_or_xml` with explicit XML backup/hash verification."
                )
            render_audit_report(payload, json_output=args.json_output)
            return 0

        if args.command == "analyze":
            comp = analyze_patterns(
                db_path=args.db_path,
                window_seconds=args.window_seconds,
                baseline_window=args.baseline_window,
                periodicity_only=args.periodicity,
            )
            render_analyze_report(comp.to_dict(), json_output=args.json_output)
            return 0

        if args.command == "exec":
            cmd_argv = list(args.command_argv or [])
            if not cmd_argv:
                rem = list(args.remainder or [])
                if rem and rem[0] == "--":
                    rem = rem[1:]
                cmd_argv = rem
            if not cmd_argv:
                raise ConfigValidationError("Specify a command via -c/--command or after '--'.")

            storage: FlightRecorderStorage | None = None
            if not args.no_persist:
                try:
                    storage = FlightRecorderStorage(db_path=args.db_path)
                except Exception as exc:
                    print(f"Warning: flight recorder persistence disabled ({exc}).", file=sys.stderr)

            try:
                res = run_supervised(
                    cmd_argv,
                    cwd=args.working_dir,
                    profile=args.profile,
                    timeout_seconds=args.timeout_seconds,
                    max_output_bytes=args.max_output_bytes,
                    storage=storage,
                    keep_console_on_error=args.keep_console_on_error,
                )
            finally:
                if storage is not None:
                    storage.close()

            if args.json_output:
                print(json.dumps(res.to_dict(), indent=2, default=str))
            else:
                if res.stdout_redacted:
                    sys.stdout.write(res.stdout_redacted)
                    if not res.stdout_redacted.endswith("\n"):
                        sys.stdout.write("\n")
                if res.stderr_redacted:
                    sys.stderr.write(res.stderr_redacted)
                    if not res.stderr_redacted.endswith("\n"):
                        sys.stderr.write("\n")
                if res.status == RunStatus.LAUNCH_FAILED and res.error_detail:
                    print(f"Launch failed: {res.error_detail}", file=sys.stderr)

            if res.status == RunStatus.TIMEOUT:
                return 124
            if res.status == RunStatus.LAUNCH_FAILED:
                return 125
            if res.status == RunStatus.CANCELLED:
                return 130
            return res.exit_code if res.exit_code is not None else 1
    except ConfigValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1
