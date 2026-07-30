"""Operations-first backup dashboard with integrated run history.

This module intentionally reuses the verified execution and concurrency model from
``operations_dashboard`` while correcting its presentation semantics:

* current operational state is distinct from the latest attempt result;
* terminal progress is historical, never presented as live activity;
* bare ``backup view`` and interactive ``backup run`` share one control surface;
* History is a secondary read-only tab rather than a competing top-level dashboard.
"""

from __future__ import annotations

import copy
import curses
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import operations_dashboard as base
from .inventory import BackupInventoryRecord
from .models import RunRecord, RunState
from .presentation import human_age, human_bytes, human_datetime
from .run_progress import BackupProgress
from .state import RunStateStore
from .viewer import ViewerRow, build_history_page

RunCallback = base.RunCallback
OperationsOutcome = base.OperationsOutcome

_ACTIVE_RUN_STATES = {RunState.QUEUED, RunState.WAITING, RunState.RUNNING}
_ACTIVE_NOW_STATES = {"QUEUED", "WAITING", "RUNNING", "STOPPING"}
_ATTENTION_RESULTS = {"FAILURE", "INTERRUPTED", "SKIPPED"}


@dataclass(frozen=True)
class HubSnapshot:
    """Immutable display state for one configured backup."""

    name: str
    health: str
    state: str
    last_result: str
    progress: Optional[BackupProgress]
    last_attempt_progress: Optional[BackupProgress]
    selected: bool
    expanded: bool
    managed: bool
    sources: Tuple[str, ...]
    excludes_count: int
    tags: Tuple[str, ...]
    repository: str
    schedule: str
    retention: str
    last_complete: Optional[datetime]
    last_attempt: Optional[datetime]
    reason: Optional[str]
    current_drives: Tuple[str, ...]
    seen_drives: Tuple[str, ...]
    error: Optional[str]


@dataclass(frozen=True)
class HubDisplayLine:
    """One pure presentation line used by curses and focused tests."""

    text: str
    color: str
    job_name: Optional[str] = None
    parent: bool = False


def _run_time(run: Optional[RunRecord]) -> Optional[datetime]:
    if run is None:
        return None
    return run.finished_utc or run.started_utc or run.created_utc


def _last_complete_time(record: BackupInventoryRecord) -> Optional[datetime]:
    snapshot_time = None if record.latest_snapshot is None else record.latest_snapshot.time
    run = record.latest_run
    run_time = _run_time(run) if run is not None and run.state == RunState.SUCCESS else None
    candidates = [value for value in (snapshot_time, run_time) if value is not None]
    return max(candidates) if candidates else None


def _progress_from_run(run: Optional[RunRecord]) -> Optional[BackupProgress]:
    if run is None:
        return None
    value = run.metadata.get("progress")
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    payload["message_type"] = "status"
    return BackupProgress.from_mapping(payload)


def _active_progress(run: Optional[RunRecord]) -> Optional[BackupProgress]:
    if run is None or run.state not in _ACTIVE_RUN_STATES:
        return None
    return _progress_from_run(run)


def _current_state(run: Optional[RunRecord]) -> str:
    if run is not None and run.state in _ACTIVE_RUN_STATES:
        return run.state.value.upper()
    return "IDLE"


def _last_result(run: Optional[RunRecord], *, error: Optional[str] = None) -> str:
    if error:
        return "FAILURE"
    if run is None:
        return "NONE"
    return run.state.value.upper()


def _duration(value: Optional[float]) -> str:
    if value is None:
        return "-"
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes, secs)
    return "{0:02d}:{1:02d}".format(minutes, secs)


def _percent(progress: Optional[BackupProgress]) -> str:
    return "-" if progress is None else "{0:.2f}%".format(progress.percent_display)


def _speed(progress: Optional[BackupProgress]) -> str:
    if progress is None:
        return "-"
    return "{0}/s".format(human_bytes(int(progress.bytes_per_second)))


def _source_summary(sources: Sequence[str]) -> str:
    if not sources:
        return "No sources"
    if len(sources) == 1:
        return sources[0]
    return "{0} +{1}".format(sources[0], len(sources) - 1)


def _state_color(state: str, health: str, last_result: str) -> str:
    if state == "RUNNING":
        return "active"
    if state in {"QUEUED", "WAITING"}:
        return "warning"
    if state == "STOPPING":
        return "error"
    if last_result == "SUCCESS":
        return "success"
    if last_result in _ATTENTION_RESULTS or health == "CRITICAL":
        return "error"
    if health == "WARNING":
        return "warning"
    if last_result == "DRY-RUN":
        return "info"
    return "success"


def _matches(snapshot: HubSnapshot, pattern: str) -> bool:
    needle = pattern.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            snapshot.name,
            snapshot.health,
            snapshot.state,
            snapshot.last_result,
            snapshot.repository,
            snapshot.schedule,
            snapshot.retention,
            " ".join(snapshot.sources),
            " ".join(snapshot.tags),
        )
    ).lower()
    return needle in haystack


class OperationsHubModel(base.OperationsDashboardModel):
    """Verified operation model with corrected current-versus-historical semantics."""

    def __init__(self, records: Sequence[BackupInventoryRecord]) -> None:
        super().__init__(records)
        with self._lock:
            for job in self.jobs:
                self._apply_latest(job, job.record.latest_run)
        self.message = "Select a backup with Space. Press R to review and start."

    def _apply_latest(self, job: Any, latest: Optional[RunRecord]) -> None:
        job.record = replace(job.record, latest_run=latest)
        job.state = _current_state(latest)
        job.progress = _active_progress(latest)
        job.current_drives = base._current_drive_set(job.progress)
        job.seen_drives = set(job.current_drives)
        if job.state == "IDLE":
            job.current_drives.clear()
            job.seen_drives.clear()

    def _snapshot(self, job: Any) -> HubSnapshot:
        record = job.record
        run = record.latest_run
        live_progress = copy.deepcopy(job.progress) if job.state in _ACTIVE_NOW_STATES else None
        historical_progress = (
            copy.deepcopy(_progress_from_run(run))
            if run is not None and run.state not in _ACTIVE_RUN_STATES
            else None
        )
        result = job.state if job.state in _ACTIVE_NOW_STATES else _last_result(run, error=job.error)
        return HubSnapshot(
            name=record.definition.name,
            health=record.health.severity.value.upper(),
            state=job.state,
            last_result=result,
            progress=live_progress,
            last_attempt_progress=historical_progress,
            selected=job.selected,
            expanded=job.expanded,
            managed=job.managed,
            sources=tuple(record.definition.sources),
            excludes_count=len(record.definition.excludes),
            tags=tuple(record.definition.tags),
            repository=record.definition.profile.repository,
            schedule=record.definition.schedule_text,
            retention=record.definition.retention_text,
            last_complete=_last_complete_time(record),
            last_attempt=_run_time(run),
            reason=None if run is None else run.reason,
            current_drives=tuple(sorted(job.current_drives)),
            seen_drives=tuple(sorted(job.seen_drives)),
            error=job.error,
        )

    def snapshots(self, filter_text: str = "") -> Tuple[HubSnapshot, ...]:
        with self._lock:
            values = tuple(self._snapshot(job) for job in self.jobs)
        return tuple(value for value in values if _matches(value, filter_text))

    def confirmation_snapshots(self) -> Tuple[HubSnapshot, ...]:
        with self._lock:
            names = set(self.confirm_names)
            return tuple(
                self._snapshot(job)
                for job in self.jobs
                if job.record.definition.name in names
            )

    def current_records(self) -> Tuple[BackupInventoryRecord, ...]:
        with self._lock:
            return tuple(job.record for job in self.jobs)

    def refresh_persisted(self) -> bool:
        changed = False
        with self._lock:
            for job in self.jobs:
                if job.managed and job.thread is not None and job.thread.is_alive():
                    continue
                profile = job.record.definition.profile
                store = RunStateStore(Path(profile.status_file).parent / "rrbackup-state")
                latest = store.load_latest()
                if latest is not None and latest.profile != profile.name:
                    continue
                old_payload = None if job.record.latest_run is None else job.record.latest_run.to_dict()
                new_payload = None if latest is None else latest.to_dict()
                if old_payload == new_payload:
                    continue
                self._apply_latest(job, latest)
                changed = True
        return changed

    def complete(self, name: str, payload: Dict[str, Any], exit_code: int) -> None:
        super().complete(name, payload, exit_code)
        with self._lock:
            job = self._job(name)
            job.state = "IDLE"
            job.progress = None
            job.current_drives.clear()
            job.seen_drives.clear()
            result = _last_result(job.record.latest_run)
            self.message = "{0} is no longer running; latest result: {1}.".format(name, result)

    def fail(self, name: str, error: str) -> None:
        super().fail(name, error)
        with self._lock:
            job = self._job(name)
            job.state = "IDLE"
            job.progress = None
            job.current_drives.clear()
            job.seen_drives.clear()
            self.message = "{0} is no longer running; latest result: FAILURE.".format(name)

    def status_counts(self) -> Dict[str, int]:
        snapshots = self.snapshots()
        return {
            "running": sum(value.state == "RUNNING" for value in snapshots),
            "waiting": sum(value.state in {"QUEUED", "WAITING", "STOPPING"} for value in snapshots),
            "idle": sum(value.state == "IDLE" for value in snapshots),
            "attention": sum(
                value.last_result in _ATTENTION_RESULTS or value.health == "CRITICAL"
                for value in snapshots
            ),
        }

    def status_line(self) -> str:
        counts = self.status_counts()
        return (
            "RUNNING NOW: {running} | WAITING/STOPPING: {waiting} | "
            "IDLE: {idle} | ATTENTION: {attention}"
        ).format(**counts)

    def activity_line(self) -> str:
        snapshots = self.snapshots()
        active = [value for value in snapshots if value.state in _ACTIVE_NOW_STATES]
        if active:
            values = ", ".join("{0}={1}".format(value.name, value.state) for value in active)
            return "Active operations: {0}.".format(values)
        recent = sorted(
            (value for value in snapshots if value.last_attempt is not None),
            key=lambda value: value.last_attempt or datetime.min,
            reverse=True,
        )
        if recent:
            latest = recent[0]
            return "No backups are currently running. Latest attempt: {0} {1} ({2}).".format(
                latest.name,
                latest.last_result,
                human_age(latest.last_attempt),
            )
        return "No backups are currently running and no attempts have been recorded."


def _source_activity_lines(snapshot: HubSnapshot) -> List[HubDisplayLine]:
    lines: List[HubDisplayLine] = []
    current = set(snapshot.current_drives)
    seen = set(snapshot.seen_drives)
    active = snapshot.state in _ACTIVE_NOW_STATES
    for drive, paths in base._drive_groups(snapshot.sources):
        if not active:
            status = "CONFIGURED"
            color = "dim"
            suffix = "{0} configured path(s)".format(len(paths))
        elif drive in current:
            status = "ACTIVE"
            color = "active"
            suffix = "{0} configured path(s); aggregate totals only".format(len(paths))
        elif drive in seen:
            status = "SEEN"
            color = "success"
            suffix = "{0} configured path(s); aggregate totals only".format(len(paths))
        else:
            status = "PENDING"
            color = "dim"
            suffix = "{0} configured path(s); aggregate totals only".format(len(paths))
        lines.append(
            HubDisplayLine(
                text="    └─ {0:<18} {1:<11} {2}".format(drive, status, suffix),
                color=color,
                job_name=snapshot.name,
            )
        )
    return lines


def _progress_detail_lines(
    progress: BackupProgress,
    *,
    historical: bool,
) -> List[str]:
    prefix = "Last attempt partial" if historical else "Live"
    values = [
        "    {0} files: {1}/{2}".format(prefix, progress.files_done, progress.total_files),
        "    {0} bytes: {1}/{2}".format(
            prefix,
            human_bytes(progress.bytes_done),
            human_bytes(progress.total_bytes),
        ),
    ]
    if not historical:
        values.extend(
            [
                "    Live speed: {0}".format(_speed(progress)),
                "    Live ETA: {0}".format(_duration(progress.eta_seconds)),
            ]
        )
    if progress.current_files:
        values.append("    {0}:".format("Last observed files" if historical else "Current files"))
        values.extend("      - {0}".format(path) for path in progress.current_files)
    return values


def _expanded_detail_lines(snapshot: HubSnapshot) -> List[HubDisplayLine]:
    ownership = "LOCAL DASHBOARD" if snapshot.managed else "EXTERNAL/UNMANAGED"
    values = [
        "    Current state: {0}".format(snapshot.state),
        "    Latest attempt result: {0}".format(snapshot.last_result),
        "    Repository: {0}".format(snapshot.repository),
        "    Schedule: {0}".format(snapshot.schedule),
        "    Retention: {0}".format(snapshot.retention),
        "    Last complete: {0}".format(human_datetime(snapshot.last_complete)),
        "    Last attempt: {0}".format(human_datetime(snapshot.last_attempt)),
        "    Excludes: {0}; Tags: {1}".format(
            snapshot.excludes_count,
            ", ".join(snapshot.tags) or "-",
        ),
    ]
    if snapshot.state in _ACTIVE_NOW_STATES:
        values.append("    Ownership: {0}".format(ownership))
    if snapshot.reason:
        values.append("    Latest attempt reason: {0}".format(snapshot.reason))
    if snapshot.error:
        values.append("    Dashboard error: {0}".format(snapshot.error))
    if snapshot.progress is not None:
        values.extend(_progress_detail_lines(snapshot.progress, historical=False))
    elif snapshot.last_attempt_progress is not None:
        values.extend(_progress_detail_lines(snapshot.last_attempt_progress, historical=True))
    return [HubDisplayLine(text=value, color="dim", job_name=snapshot.name) for value in values]


def build_operation_lines(
    snapshots: Sequence[HubSnapshot],
    *,
    focused_name: Optional[str] = None,
) -> Tuple[HubDisplayLine, ...]:
    """Render current operations without presenting terminal progress as live."""

    lines: List[HubDisplayLine] = []
    for snapshot in snapshots:
        if focused_name is not None and snapshot.name != focused_name:
            continue
        marker = "*" if snapshot.selected else " "
        expanded_marker = "v" if snapshot.expanded else ">"
        line = (
            "{0}{1} {2:<20} {3:<9} {4:<10} {5:<8} {6:<13} {7:<9} "
            "{8:<12} {9:<12} {10:<12} {11}"
        ).format(
            marker,
            expanded_marker,
            snapshot.name,
            snapshot.health,
            snapshot.state,
            _percent(snapshot.progress),
            _speed(snapshot.progress),
            _duration(None if snapshot.progress is None else snapshot.progress.eta_seconds),
            snapshot.last_result,
            human_age(snapshot.last_attempt),
            human_age(snapshot.last_complete),
            _source_summary(snapshot.sources),
        )
        lines.append(
            HubDisplayLine(
                text=line,
                color=_state_color(snapshot.state, snapshot.health, snapshot.last_result),
                job_name=snapshot.name,
                parent=True,
            )
        )
        if snapshot.state in _ACTIVE_NOW_STATES or snapshot.expanded or focused_name is not None:
            lines.extend(_source_activity_lines(snapshot))
        if snapshot.expanded or focused_name is not None:
            lines.extend(_expanded_detail_lines(snapshot))
    return tuple(lines)


def build_confirmation_lines(
    snapshots: Sequence[HubSnapshot],
    *,
    dry_run: bool,
) -> Tuple[str, ...]:
    """Build the inline review surface for all selected backups."""

    mode = "DRY RUN" if dry_run else "REAL BACKUP"
    lines = [
        "CONFIRM START — {0} — {1} backup(s)".format(mode, len(snapshots)),
        "Nothing starts until Y is pressed. N or Esc cancels.",
    ]
    for snapshot in snapshots:
        lines.extend(
            [
                "",
                "{0} [{1}] — NOW {2}; LAST RESULT {3}".format(
                    snapshot.name,
                    snapshot.health,
                    snapshot.state,
                    snapshot.last_result,
                ),
                "  Repository: {0}".format(snapshot.repository),
                "  Schedule: {0}; Retention: {1}".format(
                    snapshot.schedule,
                    snapshot.retention,
                ),
                "  Last complete: {0}; Last attempt: {1}".format(
                    human_datetime(snapshot.last_complete),
                    human_datetime(snapshot.last_attempt),
                ),
                "  Excludes: {0}; Tags: {1}".format(
                    snapshot.excludes_count,
                    ", ".join(snapshot.tags) or "-",
                ),
                "  Sources ({0}):".format(len(snapshot.sources)),
            ]
        )
        lines.extend("    - {0}".format(source) for source in snapshot.sources)
    return tuple(lines)


def _history_rows(
    records: Sequence[BackupInventoryRecord],
    filter_text: str,
) -> Tuple[ViewerRow, ...]:
    rows = build_history_page(records).rows
    needle = filter_text.strip().lower()
    if not needle:
        return rows
    return tuple(row for row in rows if needle in row.search_text)


def _draw_history_detail(
    stdscr: Any,
    row: ViewerRow,
    *,
    scroll: int,
) -> int:
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()
    base._add_line(stdscr, 0, "RRBackup — History detail", max_x, base._attribute("header", bold=True))
    base._add_line(stdscr, 1, row.line, max_x, base._attribute("info"))
    body_height = max(1, max_y - 4)
    max_scroll = max(0, len(row.details) - body_height)
    scroll = max(0, min(scroll, max_scroll))
    for offset, text in enumerate(row.details[scroll : scroll + body_height]):
        base._add_line(stdscr, 3 + offset, text, max_x, base._attribute("default"))
    base._add_line(
        stdscr,
        max_y - 1,
        "Up/Down/PgUp/PgDn: scroll | Esc/q/Enter: back",
        max_x,
        base._attribute("header"),
    )
    stdscr.refresh()
    return max_scroll


def _draw_hub(
    stdscr: Any,
    model: OperationsHubModel,
    *,
    tab: str,
    filter_text: str,
    editing_filter: bool,
    filter_buffer: str,
    top_line: int,
    history_index: int,
    confirmation_scroll: int,
    dry_run: bool,
) -> Tuple[int, int, int, Tuple[ViewerRow, ...]]:
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()
    filter_label = filter_buffer if editing_filter else filter_text or "*"
    base._add_line(
        stdscr,
        0,
        "Filter: {0}".format(filter_label),
        max_x,
        base._attribute("header", bold=True),
    )
    view_number = "1/2" if tab == "operations" else "2/2"
    base._add_line(
        stdscr,
        1,
        "RRBackup — View: {0} — {1}".format(tab.upper(), view_number),
        max_x,
        base._attribute("header", bold=True),
    )
    base._add_line(stdscr, 2, model.status_line(), max_x, base._attribute("info", bold=True))
    base._add_line(
        stdscr,
        3,
        model.activity_line() if tab == "history" else model.message,
        max_x,
        base._attribute("info"),
    )

    confirmation_lines: Tuple[str, ...] = tuple()
    if tab == "operations" and model.confirm_action == "start":
        confirmation_lines = build_confirmation_lines(
            model.confirmation_snapshots(),
            dry_run=dry_run,
        )
    elif tab == "operations" and model.confirm_action == "stop":
        confirmation_lines = (
            "CONFIRM STOP — {0}".format(", ".join(model.confirm_names)),
            "Y stops selected locally managed Restic process(es); N or Esc cancels.",
        )

    footer_height = 3
    confirmation_height = 0
    if confirmation_lines:
        confirmation_height = min(max(8, max_y // 2), len(confirmation_lines) + 2)
    list_start = 6
    list_height = max(1, max_y - list_start - footer_height - confirmation_height)
    confirmation_max_scroll = 0
    history_rows: Tuple[ViewerRow, ...] = tuple()

    if tab == "operations":
        snapshots = model.snapshots(filter_text)
        lines = build_operation_lines(snapshots, focused_name=model.focused_name)
        base._add_line(
            stdscr,
            5,
            "SE BACKUP               HEALTH    NOW        DONE     SPEED         ETA       LAST RESULT  LAST ATTEMPT LAST COMPLETE SOURCES",
            max_x,
            base._attribute("header", bold=True),
        )
        parent_positions = {
            line.job_name: index
            for index, line in enumerate(lines)
            if line.parent and line.job_name is not None
        }
        selected_position = parent_positions.get(model.current_name, 0)
        if selected_position < top_line:
            top_line = selected_position
        elif selected_position >= top_line + list_height:
            top_line = selected_position - list_height + 1
        top_line = max(0, min(top_line, max(0, len(lines) - list_height)))
        for offset, line in enumerate(lines[top_line : top_line + list_height]):
            selected = line.parent and line.job_name == model.current_name
            base._add_line(
                stdscr,
                list_start + offset,
                line.text,
                max_x,
                base._attribute(line.color, selected=selected),
            )
    else:
        history_rows = _history_rows(model.current_records(), filter_text)
        base._add_line(
            stdscr,
            5,
            "WHEN              BACKUP               EVENT      RESULT       ID",
            max_x,
            base._attribute("header", bold=True),
        )
        if history_rows:
            history_index = max(0, min(history_index, len(history_rows) - 1))
            if history_index < top_line:
                top_line = history_index
            elif history_index >= top_line + list_height:
                top_line = history_index - list_height + 1
            top_line = max(0, min(top_line, max(0, len(history_rows) - list_height)))
            for offset, row in enumerate(history_rows[top_line : top_line + list_height]):
                selected = top_line + offset == history_index
                result = row.sort_values.get("state", "")
                color = "error" if result in {"failure", "interrupted"} else "success"
                base._add_line(
                    stdscr,
                    list_start + offset,
                    row.line,
                    max_x,
                    base._attribute(color, selected=selected),
                )
        else:
            base._add_line(stdscr, list_start, "No matching history records.", max_x)

    if confirmation_lines:
        separator_y = max_y - footer_height - confirmation_height
        try:
            stdscr.hline(separator_y, 0, curses.ACS_HLINE, max_x)
        except curses.error:
            pass
        visible_height = max(1, confirmation_height - 1)
        confirmation_max_scroll = max(0, len(confirmation_lines) - visible_height)
        confirmation_scroll = max(0, min(confirmation_scroll, confirmation_max_scroll))
        for offset, text in enumerate(
            confirmation_lines[confirmation_scroll : confirmation_scroll + visible_height]
        ):
            base._add_line(
                stdscr,
                separator_y + 1 + offset,
                text,
                max_x,
                base._attribute("warning", bold=offset == 0),
            )

    if tab == "operations":
        footer_one = "1/O: Operations | 2/H: History | Space: select | R: review/start | S: stop"
        footer_two = "e/c: expand/collapse | E/C: all | Enter/i/m: focus | f: filter | Ctrl+C: stop all"
    else:
        footer_one = "1/O: Operations (start/stop) | 2/H: History | Enter/i: details | f: filter"
        footer_two = "History is read-only; R returns to Operations | Up/Down/PgUp/PgDn: navigate"
    base._add_line(stdscr, max_y - 3, footer_one, max_x, base._attribute("header"))
    base._add_line(stdscr, max_y - 2, footer_two, max_x, base._attribute("header"))
    base._add_line(
        stdscr,
        max_y - 1,
        "q/Ctrl+Q: close when no locally managed backup is active",
        max_x,
        base._attribute("header"),
    )
    stdscr.refresh()
    return top_line, confirmation_max_scroll, history_index, history_rows


def _hub_main(
    stdscr: Any,
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    dry_run: bool,
    initial_tab: str,
) -> OperationsOutcome:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    base._initialize_colors()
    stdscr.timeout(200)
    model = OperationsHubModel(records)
    tab = initial_tab if initial_tab in {"operations", "history"} else "operations"
    filter_text = ""
    filter_buffer = ""
    editing_filter = False
    top_line = 0
    history_index = 0
    confirmation_scroll = 0
    history_detail: Optional[ViewerRow] = None
    detail_scroll = 0
    last_refresh = 0.0
    history_rows: Tuple[ViewerRow, ...] = tuple()

    while True:
        now = time.monotonic()
        if now - last_refresh >= 1.0:
            model.refresh_persisted()
            last_refresh = now

        if history_detail is not None:
            detail_max_scroll = _draw_history_detail(
                stdscr,
                history_detail,
                scroll=detail_scroll,
            )
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                key = 3
            if key in {-1, curses.KEY_RESIZE}:
                continue
            if key in {27, ord("q"), ord("Q"), 10, 13, curses.KEY_ENTER}:
                history_detail = None
                detail_scroll = 0
            elif key in {curses.KEY_UP, ord("k")}:
                detail_scroll = max(0, detail_scroll - 1)
            elif key in {curses.KEY_DOWN, ord("j")}:
                detail_scroll = min(detail_max_scroll, detail_scroll + 1)
            elif key == curses.KEY_PPAGE:
                detail_scroll = max(0, detail_scroll - 5)
            elif key == curses.KEY_NPAGE:
                detail_scroll = min(detail_max_scroll, detail_scroll + 5)
            elif key == 3:
                model.stop_all_managed()
            continue

        top_line, confirmation_max_scroll, history_index, history_rows = _draw_hub(
            stdscr,
            model,
            tab=tab,
            filter_text=filter_text,
            editing_filter=editing_filter,
            filter_buffer=filter_buffer,
            top_line=top_line,
            history_index=history_index,
            confirmation_scroll=confirmation_scroll,
            dry_run=dry_run,
        )
        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            key = 3
        if key in {-1, curses.KEY_RESIZE}:
            continue

        if editing_filter:
            if key in {10, 13, curses.KEY_ENTER}:
                filter_text = filter_buffer
                editing_filter = False
                top_line = 0
                history_index = 0
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
            elif key == 27:
                filter_buffer = filter_text
                editing_filter = False
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
            elif key in {curses.KEY_BACKSPACE, 127, 8}:
                filter_buffer = filter_buffer[:-1]
            elif 32 <= key <= 126:
                filter_buffer += chr(key)
            continue

        if model.confirm_action is not None:
            if key in {ord("y"), ord("Y")}:
                model.confirm(callback)
                confirmation_scroll = 0
            elif key in {ord("n"), ord("N"), 27}:
                model.cancel_confirmation()
                confirmation_scroll = 0
            elif key == curses.KEY_PPAGE:
                confirmation_scroll = max(0, confirmation_scroll - 5)
            elif key == curses.KEY_NPAGE:
                confirmation_scroll = min(confirmation_max_scroll, confirmation_scroll + 5)
            continue

        if key in {ord("1"), ord("o"), ord("O")}:
            tab = "operations"
            top_line = 0
        elif key in {ord("2"), ord("h"), ord("H")}:
            tab = "history"
            top_line = 0
            history_index = 0
        elif key == ord("f"):
            editing_filter = True
            filter_buffer = filter_text
            try:
                curses.curs_set(1)
            except curses.error:
                pass
        elif key == 3:
            model.stop_all_managed()
        elif tab == "history":
            if key in {curses.KEY_UP, ord("k")}:
                history_index = max(0, history_index - 1)
            elif key in {curses.KEY_DOWN, ord("j")}:
                history_index = min(max(0, len(history_rows) - 1), history_index + 1)
            elif key == curses.KEY_PPAGE:
                history_index = max(0, history_index - 10)
            elif key == curses.KEY_NPAGE:
                history_index = min(max(0, len(history_rows) - 1), history_index + 10)
            elif key in {10, 13, curses.KEY_ENTER, ord("i")} and history_rows:
                history_detail = history_rows[history_index]
            elif key in {ord("r"), ord("R"), ord("s"), ord("S")}:
                tab = "operations"
                top_line = 0
                model.message = "Start and Stop controls are available on the Operations view."
            elif key == 27:
                tab = "operations"
                top_line = 0
            elif key in {ord("q"), ord("Q"), 17}:
                if model.has_active_managed():
                    model.message = "A locally managed backup is active; press 1, then stop it before closing."
                    tab = "operations"
                else:
                    break
        else:
            if key in {curses.KEY_UP, ord("k")}:
                model.move_current(-1, filter_text)
            elif key in {curses.KEY_DOWN, ord("j")}:
                model.move_current(1, filter_text)
            elif key == ord(" "):
                model.toggle_selected()
            elif key in {ord("r"), ord("R")}:
                model.request_start()
            elif key in {ord("s"), ord("S")}:
                model.request_stop()
            elif key == ord("e"):
                model.toggle_expanded()
            elif key == ord("c"):
                model.toggle_expanded(False)
            elif key == ord("E"):
                model.set_all_expanded(model.visible_names(filter_text), True)
            elif key == ord("C"):
                model.set_all_expanded(model.visible_names(filter_text), False)
            elif key in {10, 13, curses.KEY_ENTER, ord("i"), ord("m")}:
                model.toggle_focus()
                top_line = 0
            elif key == 27 and model.focused_name is not None:
                model.toggle_focus()
                top_line = 0
            elif key in {ord("q"), ord("Q"), 17}:
                if model.focused_name is not None:
                    model.toggle_focus()
                    top_line = 0
                elif model.has_active_managed():
                    model.message = "A locally managed backup is active; stop it before closing."
                else:
                    break

    model.join()
    return model.outcome()


def run_operations_hub(
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    *,
    dry_run: bool = False,
    initial_tab: str = "operations",
) -> OperationsOutcome:
    """Open the operations-first dashboard shared by ``view`` and ``run``."""

    if not records:
        return OperationsOutcome(started_count=0, exit_codes=tuple())
    return curses.wrapper(_hub_main, records, callback, dry_run, initial_tab)
