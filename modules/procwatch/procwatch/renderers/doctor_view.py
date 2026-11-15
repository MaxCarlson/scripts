"""Read-only environment, collector, terminal, and storage diagnostics for `procwatch doctor`."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from procwatch import __version__
from procwatch.collectors.sysmon_evt import check_sysmon_channel
from procwatch.collectors.task_events import check_task_scheduler_channel
from procwatch.config import StorageConfig, get_data_dir
from procwatch.correlator.terminal_session import read_console_delegation_status
from procwatch.storage import FlightRecorderStorage


def _is_admin() -> bool:
    if sys.platform != "win32":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def collect_doctor_report(
    *,
    db_path: Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Gather strictly read-only environment, collector, terminal, and storage telemetry."""
    resolved_db = (db_path or StorageConfig().resolved_db_path(get_data_dir())).expanduser()
    sysmon = check_sysmon_channel()
    tasks = check_task_scheduler_channel()
    delegation = read_console_delegation_status()
    is_admin = _is_admin()

    db_info: dict[str, Any] = {"path": str(resolved_db), "exists": resolved_db.exists()}
    collector_states: list[dict[str, Any]] = []
    ingest_gaps: list[dict[str, Any]] = []
    if resolved_db.exists():
        try:
            storage = FlightRecorderStorage(resolved_db, read_only=True)
            try:
                db_info.update(storage.db_stats())
                if verbose:
                    collector_states = storage.get_collector_state()
                    ingest_gaps = storage.get_ingest_gaps()
            finally:
                storage.close()
        except Exception as exc:
            db_info["error"] = str(exc)

    report: dict[str, Any] = {
        "version": __version__,
        "platform": sys.platform,
        "elevated_admin": is_admin,
        "collectors": {
            "win_event": {
                "status": "active" if sys.platform == "win32" else "unavailable",
                "coverage_state": "live" if sys.platform == "win32" else "unavailable",
            },
            "wmi_trace": {
                "status": "active" if is_admin and sys.platform == "win32" else "degraded",
                "coverage_state": "live" if is_admin and sys.platform == "win32" else "access_denied",
                "detail": "Requires admin for Win32_ProcessStartTrace; Toolhelp32 snapshot fallback active."
                if not is_admin
                else "Admin privileges present",
            },
            "sysmon_evt": {
                "channel": sysmon.channel,
                "available": sysmon.available,
                "status": sysmon.status,
                "coverage_state": sysmon.coverage_state,
                "detail": sysmon.detail,
            },
            "task_events": {
                "channel": tasks.channel,
                "available": tasks.available,
                "status": tasks.status,
                "coverage_state": tasks.coverage_state,
                "detail": tasks.detail,
            },
        },
        "terminal_delegation": {
            "default_host": delegation.default_host,
            "delegation_console": delegation.delegation_console,
            "delegation_terminal": delegation.delegation_terminal,
        },
        "storage": db_info,
    }
    if verbose:
        report["collector_states"] = collector_states
        report["ingest_gaps"] = ingest_gaps
    return report


def render_doctor_report(
    report: dict[str, Any],
    *,
    json_output: bool = False,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Print doctor diagnostics as JSON or Rich tables."""
    if json_output:
        print(json.dumps(report, indent=2, default=str))
        return

    con = console or Console()
    con.print(f"[bold cyan]ProcWatch Doctor[/bold cyan] v{report['version']} ({report['platform']})")
    con.print(f"Elevated Admin: {'yes' if report['elevated_admin'] else 'no (standard user)'}")

    table = Table(title="Collector & Telemetry Readiness")
    table.add_column("Source", style="bold")
    table.add_column("Status")
    table.add_column("Coverage")
    table.add_column("Detail")
    for name, info in report["collectors"].items():
        table.add_row(
            name,
            str(info.get("status", "")),
            str(info.get("coverage_state", "")),
            str(info.get("detail", "")),
        )
    con.print(table)

    td = report["terminal_delegation"]
    con.print(f"Terminal Delegation (HKCU\\Console\\%%Startup): [bold]{td['default_host']}[/bold]")

    st = report["storage"]
    if st.get("exists"):
        con.print(
            f"Flight Recorder DB: {st['path']} "
            f"(size={st.get('size_bytes', 0)} bytes, "
            f"processes={st.get('processes', 0)}, windows={st.get('windows', 0)}, "
            f"incidents={st.get('incidents', 0)}, raw_events={st.get('raw_events', 0)})"
        )
    else:
        con.print(f"Flight Recorder DB: {st['path']} (not yet initialized)")

    if verbose and report.get("ingest_gaps"):
        con.print(f"[yellow]Ingest Gaps ({len(report['ingest_gaps'])}):[/yellow]")
        for gap in report["ingest_gaps"][:10]:
            con.print(f"  - [{gap['source']}] {gap['reason']} ({gap['created_at_utc']})")
