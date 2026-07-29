"""Interactive multi-page viewer, compact diagnostics, and safe demo fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .audit import AuditReport
from .config import RetentionPolicy, Schedule
from .health import HealthIssue, HealthReport, HealthSeverity
from .inventory import BackupDefinition, BackupInventoryRecord
from .models import RunRecord, RunState
from .presentation import (
    backup_detail_lines,
    human_age,
    human_bytes,
    human_datetime,
    render_repository_summary,
    strip_ansi,
)
from .profile import BackupProfile
from .repository_summary import RepositorySummary
from .schedule_discovery import ScheduleRecord
from .snapshots import SnapshotRecord

UTC = timezone.utc
_MIN_TIME = datetime.min.replace(tzinfo=UTC)
_MAX_TIME = datetime.max.replace(tzinfo=UTC)
VIEWER_PAGE_NAMES = (
    "overview",
    "backups",
    "history",
    "repository",
    "schedules",
    "diagnostics",
)


@dataclass(frozen=True)
class ViewerRow:
    """One searchable, sortable row displayed by the shared TermDash list."""

    row_id: str
    line: str
    details: Tuple[str, ...]
    search_text: str
    sort_values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ViewerPage:
    """One page in the interactive backup-view carousel."""

    name: str
    columns: str
    rows: Tuple[ViewerRow, ...]
    sort_fields: Tuple[str, ...]
    initial_sort: str
    descending: bool = False


class _SelectionComplete(Exception):
    pass


def _run_time(run: Optional[RunRecord]) -> Optional[datetime]:
    if run is None:
        return None
    return run.finished_utc or run.started_utc or run.created_utc


def _last_complete_time(record: BackupInventoryRecord) -> Optional[datetime]:
    snapshot_time = None if record.latest_snapshot is None else record.latest_snapshot.time
    run = record.latest_run
    run_time = (
        _run_time(run)
        if run is not None and run.state == RunState.SUCCESS
        else None
    )
    values = [value for value in (snapshot_time, run_time) if value is not None]
    return max(values) if values else None


def _attempt_state(record: BackupInventoryRecord) -> str:
    if record.latest_run is None:
        return "NONE"
    return record.latest_run.state.value.upper()


def _schedule_state(record: BackupInventoryRecord) -> str:
    scheduler = record.scheduler_record
    if scheduler is None:
        return "MANUAL" if record.definition.schedule.type == "manual" else "MISSING"
    if scheduler.enabled is False:
        return "DISABLED"
    return (scheduler.state or "ENABLED").upper()


def _fit_line(line: str, width: int, scroll_offset: int) -> str:
    visible = line[scroll_offset:] if scroll_offset else line
    return visible.ljust(width)[:width]


def _placeholder_page(name: str, message: str) -> ViewerPage:
    row = ViewerRow(
        row_id="{0}-empty".format(name),
        line=message,
        details=(message,),
        search_text=message,
        sort_values={"name": message.lower()},
    )
    return ViewerPage(
        name=name,
        columns="STATUS",
        rows=(row,),
        sort_fields=("name",),
        initial_sort="name",
    )


def build_overview_page(records: Sequence[BackupInventoryRecord]) -> ViewerPage:
    """Build the compact health and recency overview page."""

    rows: List[ViewerRow] = []
    for record in records:
        complete = _last_complete_time(record)
        attempted = _run_time(record.latest_run)
        missed = "?" if record.missed_runs is None else str(record.missed_runs)
        line = (
            "{0:<20} {1:<9} {2:<13} {3:<13} {4:<12} "
            "{5:<16} {6:>6} {7}"
        ).format(
            record.definition.name,
            record.health.severity.value.upper(),
            human_age(complete),
            human_age(attempted),
            _attempt_state(record),
            human_datetime(record.next_run),
            missed,
            record.definition.source_summary,
        )
        rows.append(
            ViewerRow(
                row_id="overview:{0}".format(record.definition.name),
                line=line,
                details=tuple(backup_detail_lines(record)),
                search_text=" ".join(
                    (
                        record.definition.name,
                        record.definition.source_summary,
                        record.health.severity.value,
                        _attempt_state(record),
                        record.definition.schedule_text,
                    )
                ).lower(),
                sort_values={
                    "name": record.definition.name.lower(),
                    "health": record.health.severity.value,
                    "complete": complete or _MIN_TIME,
                    "attempt": attempted or _MIN_TIME,
                    "state": _attempt_state(record),
                    "next": record.next_run or _MAX_TIME,
                    "missed": -1 if record.missed_runs is None else record.missed_runs,
                },
            )
        )
    if not rows:
        return _placeholder_page("overview", "No configured backups were found.")
    return ViewerPage(
        name="overview",
        columns=(
            "BACKUP               HEALTH    LAST COMPLETE LAST ATTEMPT  STATE        "
            "NEXT             MISSED SOURCES"
        ),
        rows=tuple(rows),
        sort_fields=("name", "health", "complete", "attempt", "state", "next", "missed"),
        initial_sort="name",
    )


def build_backups_page(records: Sequence[BackupInventoryRecord]) -> ViewerPage:
    """Build the configured-input and repository page."""

    rows: List[ViewerRow] = []
    for record in records:
        line = "{0:<20} {1:<28} {2:<30} {3:<28} {4}".format(
            record.definition.name,
            record.definition.source_summary,
            record.definition.profile.repository,
            record.definition.schedule_text,
            record.definition.retention_text,
        )
        rows.append(
            ViewerRow(
                row_id="backup:{0}".format(record.definition.name),
                line=line,
                details=tuple(backup_detail_lines(record)),
                search_text=" ".join(
                    (
                        record.definition.name,
                        record.definition.source_summary,
                        record.definition.profile.repository,
                        record.definition.schedule_text,
                        record.definition.retention_text,
                    )
                ).lower(),
                sort_values={
                    "name": record.definition.name.lower(),
                    "repository": record.definition.profile.repository.lower(),
                    "schedule": record.definition.schedule_text.lower(),
                },
            )
        )
    if not rows:
        return _placeholder_page("backups", "No configured backups were found.")
    return ViewerPage(
        name="backups",
        columns=(
            "BACKUP               SOURCES                      REPOSITORY                     "
            "SCHEDULE                     RETENTION"
        ),
        rows=tuple(rows),
        sort_fields=("name", "repository", "schedule"),
        initial_sort="name",
    )


def _snapshot_details(record: BackupInventoryRecord) -> Tuple[str, ...]:
    snapshot = record.latest_snapshot
    if snapshot is None:
        return ("No completed snapshot is available.",)
    lines = [
        "Completed snapshot",
        "  Backup: {0}".format(record.definition.name),
        "  Snapshot ID: {0}".format(snapshot.snapshot_id),
        "  Time: {0}".format(human_datetime(snapshot.time)),
        "  Host: {0}".format(snapshot.hostname or "-"),
        "  User: {0}".format(snapshot.username or "-"),
        "  Tags: {0}".format(", ".join(snapshot.tags) or "-"),
        "  Paths:",
    ]
    lines.extend("    - {0}".format(path) for path in snapshot.paths)
    if snapshot.summary:
        lines.append("  Summary:")
        for key, value in sorted(snapshot.summary.items()):
            lines.append("    {0}: {1}".format(key, value))
    return tuple(lines)


def _run_details(record: BackupInventoryRecord) -> Tuple[str, ...]:
    run = record.latest_run
    if run is None:
        return ("No structured run attempt is available.",)
    lines = [
        "Attempted run",
        "  Backup: {0}".format(record.definition.name),
        "  Run ID: {0}".format(run.run_id),
        "  State: {0}".format(run.state.value.upper()),
        "  Created: {0}".format(human_datetime(run.created_utc)),
        "  Started: {0}".format(human_datetime(run.started_utc)),
        "  Finished: {0}".format(human_datetime(run.finished_utc)),
        "  Exit code: {0}".format("-" if run.exit_code is None else run.exit_code),
        "  Snapshot ID: {0}".format(run.snapshot_id or "-"),
        "  Reason: {0}".format(run.reason or "-"),
    ]
    return tuple(lines)


def build_history_page(records: Sequence[BackupInventoryRecord]) -> ViewerPage:
    """Build a merged completed-snapshot and attempted-run page."""

    events: List[Tuple[datetime, ViewerRow]] = []
    for record in records:
        snapshot = record.latest_snapshot
        if snapshot is not None:
            events.append(
                (
                    snapshot.time,
                    ViewerRow(
                        row_id="snapshot:{0}:{1}".format(
                            record.definition.name,
                            snapshot.snapshot_id,
                        ),
                        line="{0:<17} {1:<20} {2:<10} {3:<12} {4}".format(
                            human_datetime(snapshot.time),
                            record.definition.name,
                            "SNAPSHOT",
                            "COMPLETED",
                            snapshot.short_id,
                        ),
                        details=_snapshot_details(record),
                        search_text="{0} snapshot completed {1}".format(
                            record.definition.name,
                            snapshot.snapshot_id,
                        ).lower(),
                        sort_values={
                            "time": snapshot.time,
                            "name": record.definition.name.lower(),
                            "type": "snapshot",
                            "state": "completed",
                        },
                    ),
                )
            )
        run = record.latest_run
        if run is not None:
            event_time = _run_time(run) or run.created_utc
            events.append(
                (
                    event_time,
                    ViewerRow(
                        row_id="run:{0}:{1}".format(record.definition.name, run.run_id),
                        line="{0:<17} {1:<20} {2:<10} {3:<12} {4}".format(
                            human_datetime(event_time),
                            record.definition.name,
                            "ATTEMPT",
                            run.state.value.upper(),
                            run.run_id[:8],
                        ),
                        details=_run_details(record),
                        search_text="{0} attempt {1} {2}".format(
                            record.definition.name,
                            run.state.value,
                            run.run_id,
                        ).lower(),
                        sort_values={
                            "time": event_time,
                            "name": record.definition.name.lower(),
                            "type": "attempt",
                            "state": run.state.value,
                        },
                    ),
                )
            )
    rows = tuple(row for _, row in sorted(events, key=lambda item: item[0], reverse=True))
    if not rows:
        return _placeholder_page("history", "No snapshot or run history was found.")
    return ViewerPage(
        name="history",
        columns="WHEN              BACKUP               EVENT      STATE        ID",
        rows=rows,
        sort_fields=("time", "name", "type", "state"),
        initial_sort="time",
        descending=True,
    )


def build_repository_page(summaries: Sequence[RepositorySummary]) -> ViewerPage:
    """Build a repository status page from already collected summaries."""

    rows: List[ViewerRow] = []
    for summary in summaries:
        latest = summary.latest_snapshot
        storage = (
            "not cached"
            if summary.storage is None
            else human_bytes(int(summary.storage.payload.get("total_size", 0)))
        )
        line = "{0:<34} {1:<11} {2:<7} {3:>9} {4:<17} {5}".format(
            summary.repository,
            "AVAILABLE" if summary.available else "UNAVAILABLE",
            summary.format_version or "-",
            summary.snapshot_count,
            "-" if latest is None else human_datetime(latest.time),
            storage,
        )
        details = tuple(
            strip_ansi(render_repository_summary(summary)).splitlines()
        )
        rows.append(
            ViewerRow(
                row_id="repository:{0}".format(summary.repository),
                line=line,
                details=details,
                search_text="{0} {1} {2}".format(
                    summary.repository,
                    "available" if summary.available else "unavailable",
                    " ".join(summary.warnings),
                ).lower(),
                sort_values={
                    "repository": summary.repository.lower(),
                    "status": 0 if summary.available else 1,
                    "snapshots": summary.snapshot_count,
                    "latest": _MIN_TIME if latest is None else latest.time,
                },
            )
        )
    if not rows:
        return _placeholder_page("repository", "No repository summaries were found.")
    return ViewerPage(
        name="repository",
        columns=(
            "REPOSITORY                         STATUS      FORMAT  SNAPSHOTS "
            "LATEST            STORAGE"
        ),
        rows=tuple(rows),
        sort_fields=("repository", "status", "snapshots", "latest"),
        initial_sort="repository",
    )


def build_demo_repository_page(records: Sequence[BackupInventoryRecord]) -> ViewerPage:
    """Build repository rows for demo mode without invoking Restic."""

    grouped: Dict[str, List[BackupInventoryRecord]] = {}
    for record in records:
        grouped.setdefault(record.definition.profile.repository, []).append(record)
    rows: List[ViewerRow] = []
    for index, (repository, values) in enumerate(sorted(grouped.items())):
        snapshots = [value.latest_snapshot for value in values if value.latest_snapshot]
        latest = max((snapshot.time for snapshot in snapshots), default=None)
        storage = (index + 1) * 384 * 1024**3
        details = (
            "DEMO repository — no Restic command was executed.",
            "Location: {0}".format(repository),
            "Status: AVAILABLE",
            "Backups: {0}".format(", ".join(value.definition.name for value in values)),
            "Snapshots represented: {0}".format(len(snapshots)),
            "Synthetic storage: {0}".format(human_bytes(storage)),
        )
        rows.append(
            ViewerRow(
                row_id="demo-repository:{0}".format(repository),
                line="{0:<34} {1:<11} {2:<7} {3:>9} {4:<17} {5}".format(
                    repository,
                    "AVAILABLE",
                    2,
                    len(snapshots),
                    human_datetime(latest),
                    human_bytes(storage),
                ),
                details=details,
                search_text="{0} demo available".format(repository).lower(),
                sort_values={
                    "repository": repository.lower(),
                    "status": 0,
                    "snapshots": len(snapshots),
                    "latest": latest or _MIN_TIME,
                },
            )
        )
    return ViewerPage(
        name="repository",
        columns=(
            "REPOSITORY                         STATUS      FORMAT  SNAPSHOTS "
            "LATEST            STORAGE"
        ),
        rows=tuple(rows),
        sort_fields=("repository", "status", "snapshots", "latest"),
        initial_sort="repository",
    )


def build_schedules_page(records: Sequence[BackupInventoryRecord]) -> ViewerPage:
    """Build the backup-centric schedule page."""

    rows: List[ViewerRow] = []
    for record in records:
        missed = "?" if record.missed_runs is None else str(record.missed_runs)
        line = "{0:<20} {1:<10} {2:<30} {3:<17} {4:>6} {5}".format(
            record.definition.name,
            _schedule_state(record),
            record.definition.schedule_text,
            human_datetime(record.next_run),
            missed,
            record.definition.retention_text,
        )
        rows.append(
            ViewerRow(
                row_id="schedule:{0}".format(record.definition.name),
                line=line,
                details=tuple(backup_detail_lines(record)),
                search_text="{0} {1} {2} {3}".format(
                    record.definition.name,
                    _schedule_state(record),
                    record.definition.schedule_text,
                    record.definition.retention_text,
                ).lower(),
                sort_values={
                    "name": record.definition.name.lower(),
                    "state": _schedule_state(record),
                    "next": record.next_run or _MAX_TIME,
                    "missed": -1 if record.missed_runs is None else record.missed_runs,
                },
            )
        )
    if not rows:
        return _placeholder_page("schedules", "No configured backup schedules were found.")
    return ViewerPage(
        name="schedules",
        columns=(
            "BACKUP               STATE      SCHEDULE                       "
            "NEXT              MISSED RETENTION"
        ),
        rows=tuple(rows),
        sort_fields=("name", "state", "next", "missed"),
        initial_sort="name",
    )


def _flatten_details(value: Any, *, prefix: str = "", depth: int = 0) -> List[str]:
    if depth > 3:
        return ["{0}{1}".format(prefix, value)]
    if isinstance(value, Mapping):
        lines: List[str] = []
        for key, nested in value.items():
            label = "{0}{1}".format(prefix, key)
            if isinstance(nested, (Mapping, list, tuple)):
                lines.append("{0}:".format(label))
                lines.extend(_flatten_details(nested, prefix="  " + prefix, depth=depth + 1))
            else:
                lines.append("{0}: {1}".format(label, nested))
        return lines
    if isinstance(value, (list, tuple)):
        lines = []
        for nested in value:
            if isinstance(nested, (Mapping, list, tuple)):
                lines.append("{0}-".format(prefix))
                lines.extend(_flatten_details(nested, prefix="  " + prefix, depth=depth + 1))
            else:
                lines.append("{0}- {1}".format(prefix, nested))
        return lines
    return ["{0}{1}".format(prefix, value)]


def _diagnostic_summary(name: str, value: Any) -> Tuple[str, str]:
    if name == "commands" and isinstance(value, Mapping):
        resolved = sum(
            1
            for command in value.values()
            if isinstance(command, Mapping) and command.get("resolved")
        )
        missing = len(value) - resolved
        return ("WARNING" if missing else "OK", "{0} resolved, {1} missing".format(resolved, missing))
    if name == "runtime" and isinstance(value, Mapping):
        return (
            "OK",
            "RRBackup {0}; Python {1}; host {2}".format(
                value.get("rrbackup_version", "?"),
                str(value.get("python_version", "?")).split()[0],
                value.get("hostname", "?"),
            ),
        )
    if name == "paths" and isinstance(value, Mapping):
        existing = sum(
            1 for item in value.values() if isinstance(item, Mapping) and item.get("exists")
        )
        missing = sum(
            1
            for item in value.values()
            if isinstance(item, Mapping) and item.get("configured") and not item.get("exists")
        )
        return ("WARNING" if missing else "OK", "{0} existing, {1} missing".format(existing, missing))
    if name == "environment" and isinstance(value, Mapping):
        return ("OK", "{0} relevant variables defined".format(len(value)))
    if name == "provenance" and isinstance(value, Mapping):
        return ("OK", str(value.get("conclusion") or "Provenance collected"))
    if name == "recommendations" and isinstance(value, Sequence) and not isinstance(value, str):
        return ("WARNING" if value else "OK", "{0} recommendation(s)".format(len(value)))
    if isinstance(value, Mapping):
        return ("OK", "{0} field(s)".format(len(value)))
    if isinstance(value, Sequence) and not isinstance(value, str):
        return ("OK", "{0} item(s)".format(len(value)))
    return ("OK", str(value))


def build_diagnostics_page(report: AuditReport) -> ViewerPage:
    """Build a compact diagnostics index with expandable details."""

    rows: List[ViewerRow] = []
    preferred_order = (
        "runtime",
        "commands",
        "configuration",
        "config-files",
        "paths",
        "inputs",
        "environment",
        "provenance",
        "recommendations",
    )
    for name in preferred_order:
        if name not in report.sections:
            continue
        value = report.sections[name]
        status, summary = _diagnostic_summary(name, value)
        details = [
            "Diagnostic section: {0}".format(name),
            "Status: {0}".format(status),
            "Summary: {0}".format(summary),
            "",
        ]
        details.extend(_flatten_details(value))
        rows.append(
            ViewerRow(
                row_id="diagnostic:{0}".format(name),
                line="{0:<18} {1:<9} {2}".format(name.upper(), status, summary),
                details=tuple(details),
                search_text="{0} {1} {2}".format(name, status, summary).lower(),
                sort_values={"category": preferred_order.index(name), "status": status},
            )
        )
    if report.warnings:
        rows.append(
            ViewerRow(
                row_id="diagnostic:warnings",
                line="{0:<18} {1:<9} {2}".format(
                    "WARNINGS",
                    "WARNING",
                    "{0} warning(s)".format(len(report.warnings)),
                ),
                details=tuple(["Warnings:"] + ["  - {0}".format(value) for value in report.warnings]),
                search_text="warnings " + " ".join(report.warnings).lower(),
                sort_values={"category": len(preferred_order), "status": "WARNING"},
            )
        )
    if not rows:
        return _placeholder_page("diagnostics", "No diagnostic information was collected.")
    return ViewerPage(
        name="diagnostics",
        columns="CATEGORY           STATUS    SUMMARY",
        rows=tuple(rows),
        sort_fields=("category", "status"),
        initial_sort="category",
    )


def build_demo_diagnostics_page() -> ViewerPage:
    """Build deterministic diagnostic rows without probing the host."""

    rows = (
        ViewerRow(
            row_id="demo-diagnostic:runtime",
            line="{0:<18} {1:<9} {2}".format(
                "RUNTIME",
                "OK",
                "RRBackup demo mode; no host probes executed",
            ),
            details=(
                "DEMO diagnostic data",
                "No commands, files, environment variables, or repositories were inspected.",
            ),
            search_text="runtime demo ok",
            sort_values={"category": 0, "status": "OK"},
        ),
        ViewerRow(
            row_id="demo-diagnostic:warning",
            line="{0:<18} {1:<9} {2}".format(
                "SCHEDULES",
                "WARNING",
                "Includes disabled and missing synthetic schedules",
            ),
            details=(
                "Synthetic warning",
                "This exists only to exercise visual warning states.",
            ),
            search_text="schedules warning demo",
            sort_values={"category": 1, "status": "WARNING"},
        ),
    )
    return ViewerPage(
        name="diagnostics",
        columns="CATEGORY           STATUS    SUMMARY",
        rows=rows,
        sort_fields=("category", "status"),
        initial_sort="category",
    )


def render_viewer_page_plain(page: ViewerPage) -> str:
    """Render a carousel page without curses or ANSI styling."""

    lines = ["View: {0}".format(page.name.upper()), page.columns]
    lines.append("─" * min(max(len(page.columns), 10), 160))
    lines.extend(row.line for row in page.rows)
    return "\n".join(lines)


def render_audit_summary(report: AuditReport) -> str:
    """Render a compact human index while keeping full audit data explicit."""

    lines = [
        "Backup Audit Summary",
        "  Generated:  {0}".format(human_datetime(report.generated_utc)),
        "  Profile:    {0}".format(report.profile),
        "  Sections:   {0}".format(len(report.sections)),
        "  Warnings:   {0}".format(len(report.warnings)),
        "",
        "Collected sections:",
    ]
    lines.extend("  - {0}".format(name) for name in report.sections)
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend("  - {0}".format(value) for value in report.warnings)
    lines.extend(
        [
            "",
            "Use --json for the complete machine-readable audit or --markdown for export.",
        ]
    )
    return "\n".join(lines)


def _viewer_formatter(
    item: ViewerRow,
    sort_field: str,
    width: int,
    show_date: bool,
    show_time: bool,
    scroll_offset: int,
) -> str:
    del sort_field, show_date, show_time
    return _fit_line(item.line, width, scroll_offset)


def _viewer_filter(item: ViewerRow, pattern: str) -> bool:
    needle = pattern.lower().replace("*", "")
    return needle in item.search_text


def run_viewer_carousel(
    records: Sequence[BackupInventoryRecord],
    *,
    start_page: str = "overview",
    repository_loader: Callable[[], ViewerPage],
    diagnostics_loader: Callable[[], ViewerPage],
    demo: bool = False,
) -> None:
    """Run the six-page viewer using the shared TermDash list component."""

    from termdash.interactive_list import InteractiveList

    loaders: Dict[str, Callable[[], ViewerPage]] = {
        "overview": lambda: build_overview_page(records),
        "backups": lambda: build_backups_page(records),
        "history": lambda: build_history_page(records),
        "repository": repository_loader,
        "schedules": lambda: build_schedules_page(records),
        "diagnostics": diagnostics_loader,
    }
    cache: Dict[str, ViewerPage] = {}
    holder: Dict[str, Any] = {}
    page_index = VIEWER_PAGE_NAMES.index(
        start_page if start_page in VIEWER_PAGE_NAMES else "overview"
    )

    def load_page(index: int) -> ViewerPage:
        name = VIEWER_PAGE_NAMES[index]
        if name not in cache:
            cache[name] = loaders[name]()
        return cache[name]

    def sorters_for(page: ViewerPage) -> Dict[str, Callable[[ViewerRow], Any]]:
        return {
            field_name: (
                lambda item, field_name=field_name: item.sort_values.get(field_name)
            )
            for field_name in page.sort_fields
        }

    def page_header(index: int) -> str:
        prefix = "DEMO " if demo else ""
        return "{0}View: {1} — pg. {2}/{3}".format(
            prefix,
            VIEWER_PAGE_NAMES[index].upper(),
            index + 1,
            len(VIEWER_PAGE_NAMES),
        )

    def apply_page(index: int) -> None:
        nonlocal page_index
        page_index = index % len(VIEWER_PAGE_NAMES)
        page = load_page(page_index)
        view = holder["view"]
        view.state.items = list(page.rows)
        view.state.header = page_header(page_index)
        view.state.columns_line = page.columns
        view.state.sorters = sorters_for(page)
        view.state.sort_field = page.initial_sort
        view.state.descending = page.descending
        view.state.filter_pattern = ""
        view.state.exclusion_pattern = ""
        view.state.scroll_offset = 0
        view.state.detail_view = False
        view.detail_formatter = lambda item: list(item.details)
        view._update_visible_items(reset_selection=True)

    def key_handler(key: int, current: ViewerRow, state: Any) -> Tuple[bool, bool]:
        del current, state
        if key in {ord("]"), 9}:
            apply_page(page_index + 1)
            return True, False
        if key == ord("["):
            apply_page(page_index - 1)
            return True, False
        if ord("1") <= key <= ord(str(len(VIEWER_PAGE_NAMES))):
            apply_page(key - ord("1"))
            return True, False
        return False, False

    initial = load_page(page_index)
    view = InteractiveList(
        items=list(initial.rows),
        sorters=sorters_for(initial),
        formatter=_viewer_formatter,
        filter_func=_viewer_filter,
        initial_sort=initial.initial_sort,
        initial_order="desc" if initial.descending else "asc",
        header=page_header(page_index),
        columns_line=initial.columns,
        footer_lines=[
            "[/]: previous/next view | Tab: next | 1-6: jump | Enter/i: details",
            "Up/Down/j/k: move | PgUp/PgDn: page | f: filter | Left/Right: scroll | Ctrl+Q: close",
        ],
        detail_formatter=lambda item: list(item.details),
        key_handler=key_handler,
        item_key_func=lambda item: item.row_id,
        dirs_first=False,
    )
    holder["view"] = view
    view.run()


def select_backups(
    records: Sequence[BackupInventoryRecord],
    *,
    title: str,
    multi_select: bool = False,
    action_key: str = "r",
    action_label: str = "run selected backups",
) -> List[BackupInventoryRecord]:
    """Select backups with concise columns; execution confirmation is added later."""

    if not records:
        return []
    from termdash.interactive_list import InteractiveList

    selected: List[BackupInventoryRecord] = []
    holder: Dict[str, Any] = {}

    def formatter(
        item: BackupInventoryRecord,
        sort_field: str,
        width: int,
        show_date: bool,
        show_time: bool,
        scroll_offset: int,
    ) -> str:
        del sort_field, show_date, show_time
        line = (
            "{0:<20} {1:<9} {2:<13} {3:<13} {4:<12} {5:<16} {6:>6} {7}"
        ).format(
            item.definition.name,
            item.health.severity.value.upper(),
            human_age(_last_complete_time(item)),
            human_age(_run_time(item.latest_run)),
            _attempt_state(item),
            human_datetime(item.next_run),
            "?" if item.missed_runs is None else item.missed_runs,
            item.definition.source_summary,
        )
        return _fit_line(line, width, scroll_offset)

    def filter_item(item: BackupInventoryRecord, pattern: str) -> bool:
        needle = pattern.lower().replace("*", "")
        return needle in " ".join(
            (
                item.definition.name,
                item.definition.source_summary,
                item.definition.profile.repository,
                item.definition.schedule_text,
                item.health.severity.value,
                _attempt_state(item),
            )
        ).lower()

    def key_handler(
        key: int,
        current: BackupInventoryRecord,
        state: Any,
    ) -> Tuple[bool, bool]:
        del state
        if key in {ord(action_key.lower()), ord(action_key.upper())}:
            view = holder["view"]
            chosen = view.get_selected_items() if multi_select else [current]
            if not chosen:
                chosen = [current]
            selected.extend(chosen)
            raise _SelectionComplete()
        return False, False

    footer = [
        "Up/Down/j/k: move | PgUp/PgDn: page | f: filter | Enter/i: details | Left/Right: scroll",
    ]
    if multi_select:
        footer.append("Space: select/deselect")
    footer.append(
        "{0}: {1} | Ctrl+Q: cancel".format(action_key.upper(), action_label)
    )
    view = InteractiveList(
        items=list(records),
        sorters={
            "name": lambda item: item.definition.name.lower(),
            "health": lambda item: item.health.severity.value,
            "complete": lambda item: _last_complete_time(item) or _MIN_TIME,
            "attempt": lambda item: _run_time(item.latest_run) or _MIN_TIME,
            "next": lambda item: item.next_run or _MAX_TIME,
            "missed": lambda item: -1 if item.missed_runs is None else item.missed_runs,
        },
        formatter=formatter,
        filter_func=filter_item,
        initial_sort="name",
        initial_order="asc",
        header=title,
        columns_line=(
            "BACKUP               HEALTH    LAST COMPLETE LAST ATTEMPT  STATE        "
            "NEXT             MISSED SOURCES"
        ),
        footer_lines=footer,
        detail_formatter=backup_detail_lines,
        key_handler=key_handler,
        multi_select=multi_select,
        item_key_func=lambda item: item.definition.name,
        dirs_first=False,
    )
    holder["view"] = view
    try:
        view.run()
    except _SelectionComplete:
        pass
    return selected


def _demo_run(
    name: str,
    state: Optional[RunState],
    *,
    now: datetime,
    snapshot_id: Optional[str] = None,
) -> Optional[RunRecord]:
    if state is None:
        return None
    run = RunRecord.create(
        profile=name,
        backup_set=name,
        now=now - timedelta(minutes=20),
        run_id=(name.replace("-", "") + "0" * 32)[:32],
    )
    if state == RunState.SKIPPED:
        return run.transition(
            RunState.SKIPPED,
            now=now - timedelta(minutes=19),
            reason="Synthetic CPU-policy skip.",
        )
    run = run.transition(RunState.RUNNING, now=now - timedelta(minutes=19))
    if state == RunState.RUNNING:
        return run
    reason = {
        RunState.SUCCESS: "Synthetic backup completed.",
        RunState.FAILURE: "Synthetic repository connection failure.",
        RunState.INTERRUPTED: "Synthetic user interruption.",
        RunState.DRY_RUN: "Synthetic dry-run completed.",
    }.get(state)
    return run.transition(
        state,
        now=now - timedelta(minutes=5),
        exit_code=0 if state in {RunState.SUCCESS, RunState.DRY_RUN} else 3,
        reason=reason,
        snapshot_id=snapshot_id,
    )


def build_demo_records(*, now: Optional[datetime] = None) -> Tuple[BackupInventoryRecord, ...]:
    """Return varied, deterministic visual fixtures without touching production state."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    definitions = (
        (
            "daily-documents",
            HealthSeverity.OK,
            RunState.SUCCESS,
            timedelta(hours=8),
            Schedule(type="daily", time="03:00"),
            RetentionPolicy(keep_daily=10),
            True,
            0,
            "B:\\DemoRepos\\Primary",
            ("C:\\Users\\Demo\\Documents",),
        ),
        (
            "weekly-media",
            HealthSeverity.WARNING,
            RunState.SKIPPED,
            timedelta(days=6),
            Schedule(type="weekly", time="04:00", weekday=6),
            RetentionPolicy(keep_weekly=8),
            True,
            1,
            "B:\\DemoRepos\\Primary",
            ("D:\\Pictures", "D:\\Videos"),
        ),
        (
            "failed-projects",
            HealthSeverity.CRITICAL,
            RunState.FAILURE,
            timedelta(days=12),
            Schedule(type="daily", time="01:30"),
            RetentionPolicy(keep_daily=14),
            True,
            3,
            "Z:\\OfflineRepo",
            ("C:\\Repos",),
        ),
        (
            "interrupted-games",
            HealthSeverity.CRITICAL,
            RunState.INTERRUPTED,
            timedelta(days=30),
            Schedule(type="monthly", time="02:00", day_of_month=1),
            RetentionPolicy(keep_monthly=3),
            True,
            0,
            "B:\\DemoRepos\\Archive",
            ("C:\\Games", "D:\\Games"),
        ),
        (
            "running-phone-sync",
            HealthSeverity.INFO,
            RunState.RUNNING,
            timedelta(days=1),
            Schedule(type="hourly", minute=15),
            RetentionPolicy(keep_hourly=24),
            True,
            0,
            "B:\\DemoRepos\\Primary",
            ("E:\\Phone",),
        ),
        (
            "disabled-cold-storage",
            HealthSeverity.WARNING,
            None,
            timedelta(days=90),
            Schedule(type="yearly", time="05:00", month=1, day_of_month=1),
            RetentionPolicy(keep_yearly=5),
            False,
            0,
            "Y:\\ColdStorage",
            ("D:\\Archive", "D:\\OldProjects", "D:\\Exports"),
        ),
    )
    records: List[BackupInventoryRecord] = []
    for index, (
        name,
        severity,
        run_state,
        snapshot_age,
        schedule,
        retention,
        scheduler_enabled,
        missed,
        repository,
        sources,
    ) in enumerate(definitions):
        profile = BackupProfile(
            name=name,
            repository=repository,
            password_file="DEMO_ONLY/password.txt",
            sources_file="DEMO_ONLY/sources.txt",
            excludes_file="DEMO_ONLY/excludes.txt",
            status_file="DEMO_ONLY/{0}/status.json".format(name),
            log_file="DEMO_ONLY/{0}.log".format(name),
            lock_file="DEMO_ONLY/{0}.lock".format(name),
            tag=name,
            restic_executable="restic",
            restore_root="DEMO_ONLY/restore/{0}".format(name),
        )
        snapshot_id = ("{0:08x}".format(index + 1) * 8)[:64]
        snapshot = SnapshotRecord(
            snapshot_id=snapshot_id,
            short_id=snapshot_id[:8],
            time=current - snapshot_age,
            hostname="DEMO-HOST",
            username="demo",
            paths=sources,
            tags=(name,),
            summary={"total_bytes_processed": (index + 1) * 125 * 1024**3},
        )
        run = _demo_run(
            name,
            run_state,
            now=current,
            snapshot_id=snapshot_id if run_state == RunState.SUCCESS else None,
        )
        definition = BackupDefinition(
            name=name,
            profile=profile,
            sources=sources,
            excludes=("**/.cache/**", "**/Temp/**"),
            tags=(name,),
            schedule=schedule,
            retention=retention,
            source_kind="demo",
        )
        issue = HealthIssue(
            code="demo-{0}".format(severity.value),
            severity=severity,
            message="Synthetic {0} state for visual testing.".format(severity.value),
            recommendation="Demo data only; no action is required.",
        )
        health = HealthReport(
            profile=name,
            severity=severity,
            generated_utc=current,
            latest_snapshot=snapshot,
            latest_run=run,
            issues=tuple() if severity == HealthSeverity.OK else (issue,),
        )
        scheduler = ScheduleRecord(
            backend="demo",
            identifier="RRBackup::{0}".format(name),
            enabled=scheduler_enabled,
            state="Ready" if scheduler_enabled else "Disabled",
            executable="backup",
            arguments=("run", name),
            last_run=human_datetime(current - snapshot_age),
            next_run=human_datetime(current + timedelta(hours=index + 1)),
            missed_runs=missed,
        )
        records.append(
            BackupInventoryRecord(
                definition=definition,
                latest_snapshot=snapshot,
                latest_run=run,
                scheduler_record=scheduler,
                next_run=current + timedelta(hours=index + 1),
                missed_runs=missed,
                health=health,
            )
        )
    return tuple(records)
