"""Persistent curses dashboard for starting and managing backup operations."""

from __future__ import annotations

import copy
import curses
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .inventory import BackupInventoryRecord
from .models import RunRecord, RunState
from .monitored_restic import ResticExecutionControl
from .presentation import backup_detail_lines, human_age, human_bytes, human_datetime
from .run_progress import BackupProgress
from .state import RunStateStore

RunCallback = Callable[
    [BackupInventoryRecord, Callable[[BackupProgress], None], ResticExecutionControl],
    Tuple[Dict[str, Any], int],
]

_ACTIVE_STATES = {"QUEUED", "WAITING", "RUNNING", "STOPPING"}
_TERMINAL_ERROR_STATES = {"FAILURE", "INTERRUPTED"}


@dataclass
class _OperationJob:
    record: BackupInventoryRecord
    state: str
    progress: Optional[BackupProgress] = None
    control: Optional[ResticExecutionControl] = None
    thread: Optional[threading.Thread] = None
    payload: Optional[Dict[str, Any]] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    selected: bool = False
    expanded: bool = False
    managed: bool = False
    current_drives: Set[str] = field(default_factory=set)
    seen_drives: Set[str] = field(default_factory=set)


@dataclass(frozen=True)
class OperationJobSnapshot:
    """Immutable presentation snapshot for one configured backup."""

    name: str
    health: str
    state: str
    progress: Optional[BackupProgress]
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
class OperationsOutcome:
    """Completed operations and their aggregate command exit codes."""

    started_count: int
    exit_codes: Tuple[int, ...]


@dataclass(frozen=True)
class DisplayLine:
    """One pure presentation line used by the curses renderer and tests."""

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
    values = [value for value in (snapshot_time, run_time) if value is not None]
    return max(values) if values else None


def _state_from_record(record: BackupInventoryRecord) -> str:
    return "IDLE" if record.latest_run is None else record.latest_run.state.value.upper()


def _progress_from_record(record: BackupInventoryRecord) -> Optional[BackupProgress]:
    run = record.latest_run
    if run is None:
        return None
    value = run.metadata.get("progress")
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    payload["message_type"] = "status"
    return BackupProgress.from_mapping(payload)


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


def _drive_key(path: str) -> str:
    value = path.strip().replace("/", "\\")
    if len(value) >= 3 and value[0] == "\\" and value[1].isalpha() and value[2] == "\\":
        return value[1].upper() + ":"
    if len(value) >= 2 and value[0].isalpha() and value[1] == ":":
        return value[0].upper() + ":"
    if value.startswith("\\\\"):
        parts = [part for part in value.split("\\") if part]
        if len(parts) >= 2:
            return "\\\\{0}\\{1}".format(parts[0], parts[1])
    if value.startswith("\\"):
        return "\\"
    return value.split("\\", 1)[0] or "?"


def _drive_groups(sources: Sequence[str]) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    groups: Dict[str, List[str]] = {}
    for source in sources:
        groups.setdefault(_drive_key(source), []).append(source)
    return tuple(
        (drive, tuple(paths))
        for drive, paths in sorted(groups.items(), key=lambda item: item[0].lower())
    )


def _current_drive_set(progress: Optional[BackupProgress]) -> Set[str]:
    if progress is None:
        return set()
    return {_drive_key(path) for path in progress.current_files}


def _state_color(state: str, health: str) -> str:
    if state == "RUNNING":
        return "active"
    if state in {"QUEUED", "WAITING"}:
        return "warning"
    if state == "STOPPING" or state in _TERMINAL_ERROR_STATES:
        return "error"
    if state == "SUCCESS":
        return "success"
    if state in {"SKIPPED", "DRY-RUN"}:
        return "info"
    if health == "CRITICAL":
        return "error"
    if health == "WARNING":
        return "warning"
    return "success"


def _job_matches(snapshot: OperationJobSnapshot, pattern: str) -> bool:
    needle = pattern.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            snapshot.name,
            snapshot.health,
            snapshot.state,
            snapshot.repository,
            snapshot.schedule,
            snapshot.retention,
            " ".join(snapshot.sources),
            " ".join(snapshot.tags),
        )
    ).lower()
    return needle in haystack


def _source_activity_lines(snapshot: OperationJobSnapshot) -> List[DisplayLine]:
    lines: List[DisplayLine] = []
    current = set(snapshot.current_drives)
    seen = set(snapshot.seen_drives)
    for drive, paths in _drive_groups(snapshot.sources):
        if drive in current:
            status = "ACTIVE"
            color = "active"
        elif drive in seen:
            status = "SEEN"
            color = "success"
        else:
            status = "PENDING"
            color = "dim"
        suffix = "{0} configured path(s); aggregate totals only".format(len(paths))
        lines.append(
            DisplayLine(
                text="    └─ {0:<18} {1:<8} {2}".format(drive, status, suffix),
                color=color,
                job_name=snapshot.name,
            )
        )
    return lines


def _expanded_detail_lines(snapshot: OperationJobSnapshot) -> List[DisplayLine]:
    values = [
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
    if snapshot.reason:
        values.append("    Reason: {0}".format(snapshot.reason))
    if snapshot.error:
        values.append("    Error: {0}".format(snapshot.error))
    if snapshot.progress is not None:
        values.extend(
            [
                "    Files: {0}/{1}".format(
                    snapshot.progress.files_done,
                    snapshot.progress.total_files,
                ),
                "    Bytes: {0}/{1}".format(
                    human_bytes(snapshot.progress.bytes_done),
                    human_bytes(snapshot.progress.total_bytes),
                ),
            ]
        )
        if snapshot.progress.current_files:
            values.append("    Current files:")
            values.extend("      - {0}".format(path) for path in snapshot.progress.current_files)
    return [DisplayLine(text=value, color="dim", job_name=snapshot.name) for value in values]


def build_operation_lines(
    snapshots: Sequence[OperationJobSnapshot],
    *,
    focused_name: Optional[str] = None,
) -> Tuple[DisplayLine, ...]:
    """Build dashboard lines while keeping active source-drive activity inline."""

    lines: List[DisplayLine] = []
    for snapshot in snapshots:
        if focused_name is not None and snapshot.name != focused_name:
            continue
        marker = "*" if snapshot.selected else " "
        expanded_marker = "v" if snapshot.expanded else ">"
        line = (
            "{0}{1} {2:<20} {3:<9} {4:<12} {5:<8} {6:<14} {7:<9} "
            "{8:<13} {9:<13} {10}"
        ).format(
            marker,
            expanded_marker,
            snapshot.name,
            snapshot.health,
            snapshot.state,
            _percent(snapshot.progress),
            _speed(snapshot.progress),
            _duration(None if snapshot.progress is None else snapshot.progress.eta_seconds),
            human_age(snapshot.last_complete),
            human_age(snapshot.last_attempt),
            snapshot.sources[0] + (" +{0}".format(len(snapshot.sources) - 1) if len(snapshot.sources) > 1 else "")
            if snapshot.sources
            else "No sources",
        )
        lines.append(
            DisplayLine(
                text=line,
                color=_state_color(snapshot.state, snapshot.health),
                job_name=snapshot.name,
                parent=True,
            )
        )
        if snapshot.state in _ACTIVE_STATES or snapshot.expanded or focused_name is not None:
            lines.extend(_source_activity_lines(snapshot))
        if snapshot.expanded or focused_name is not None:
            lines.extend(_expanded_detail_lines(snapshot))
    return tuple(lines)


def build_confirmation_lines(
    snapshots: Sequence[OperationJobSnapshot],
    *,
    dry_run: bool,
) -> Tuple[str, ...]:
    """Build a complete inline confirmation summary for every selected backup."""

    mode = "DRY RUN" if dry_run else "REAL BACKUP"
    lines = [
        "CONFIRM START — {0} — {1} backup(s)".format(mode, len(snapshots)),
        "Nothing starts until Y is pressed. N or Esc cancels.",
    ]
    for snapshot in snapshots:
        lines.extend(
            [
                "",
                "{0} [{1}] — current state {2}".format(
                    snapshot.name,
                    snapshot.health,
                    snapshot.state,
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


class OperationsDashboardModel:
    """Thread-safe model for one persistent operations dashboard."""

    def __init__(self, records: Sequence[BackupInventoryRecord]) -> None:
        self._lock = threading.RLock()
        self.jobs = [
            _OperationJob(
                record=record,
                state=_state_from_record(record),
                progress=_progress_from_record(record),
                current_drives=_current_drive_set(_progress_from_record(record)),
                seen_drives=_current_drive_set(_progress_from_record(record)),
            )
            for record in records
        ]
        self.current_name: Optional[str] = self.jobs[0].record.definition.name if self.jobs else None
        self.focused_name: Optional[str] = None
        self.message = "Select backups with Space. Press R to review and start."
        self.confirm_action: Optional[str] = None
        self.confirm_names: Tuple[str, ...] = tuple()
        self.started_count = 0
        self.exit_codes: List[int] = []

    def _job(self, name: str) -> _OperationJob:
        return next(job for job in self.jobs if job.record.definition.name == name)

    @staticmethod
    def _is_active(job: _OperationJob) -> bool:
        thread_active = job.thread is not None and job.thread.is_alive()
        return thread_active or job.state in _ACTIVE_STATES

    def snapshots(self, filter_text: str = "") -> Tuple[OperationJobSnapshot, ...]:
        with self._lock:
            values = tuple(self._snapshot(job) for job in self.jobs)
        return tuple(value for value in values if _job_matches(value, filter_text))

    def _snapshot(self, job: _OperationJob) -> OperationJobSnapshot:
        record = job.record
        run = record.latest_run
        return OperationJobSnapshot(
            name=record.definition.name,
            health=record.health.severity.value.upper(),
            state=job.state,
            progress=copy.deepcopy(job.progress),
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

    def visible_names(self, filter_text: str = "") -> Tuple[str, ...]:
        return tuple(snapshot.name for snapshot in self.snapshots(filter_text))

    def move_current(self, delta: int, filter_text: str = "") -> None:
        names = self.visible_names(filter_text)
        if not names:
            self.current_name = None
            return
        if self.current_name not in names:
            self.current_name = names[0]
            return
        index = names.index(self.current_name)
        self.current_name = names[max(0, min(len(names) - 1, index + delta))]

    def toggle_selected(self) -> None:
        with self._lock:
            if self.current_name is None:
                return
            job = self._job(self.current_name)
            job.selected = not job.selected

    def toggle_expanded(self, value: Optional[bool] = None) -> None:
        with self._lock:
            if self.current_name is None:
                return
            job = self._job(self.current_name)
            job.expanded = not job.expanded if value is None else value

    def set_all_expanded(self, names: Iterable[str], value: bool) -> None:
        targets = set(names)
        with self._lock:
            for job in self.jobs:
                if job.record.definition.name in targets:
                    job.expanded = value

    def toggle_focus(self) -> None:
        with self._lock:
            if self.focused_name is None:
                self.focused_name = self.current_name
            else:
                self.focused_name = None

    def _selected_or_current(self) -> List[_OperationJob]:
        selected = [job for job in self.jobs if job.selected]
        if selected:
            return selected
        if self.current_name is None:
            return []
        return [self._job(self.current_name)]

    def request_start(self) -> bool:
        with self._lock:
            candidates = [job for job in self._selected_or_current() if not self._is_active(job)]
            if not candidates:
                self.message = "No selected backup is eligible to start."
                return False
            self.confirm_action = "start"
            self.confirm_names = tuple(job.record.definition.name for job in candidates)
            self.message = "Review every selected backup below; press Y to start or N to cancel."
            return True

    def request_stop(self) -> bool:
        with self._lock:
            candidates = [
                job
                for job in self._selected_or_current()
                if job.managed and self._is_active(job)
            ]
            if not candidates:
                self.message = "No selected active backup is managed by this dashboard."
                return False
            self.confirm_action = "stop"
            self.confirm_names = tuple(job.record.definition.name for job in candidates)
            self.message = "Stop the selected active backup(s)? Press Y to confirm or N to cancel."
            return True

    def cancel_confirmation(self) -> None:
        with self._lock:
            self.confirm_action = None
            self.confirm_names = tuple()
            self.message = "Confirmation cancelled."

    def confirmation_snapshots(self) -> Tuple[OperationJobSnapshot, ...]:
        with self._lock:
            names = set(self.confirm_names)
            return tuple(self._snapshot(job) for job in self.jobs if job.record.definition.name in names)

    def confirm(self, callback: RunCallback) -> None:
        with self._lock:
            action = self.confirm_action
            names = self.confirm_names
            self.confirm_action = None
            self.confirm_names = tuple()
        if action == "start":
            self._start_names(names, callback)
        elif action == "stop":
            self._stop_names(names)

    def _start_names(self, names: Sequence[str], callback: RunCallback) -> None:
        for name in names:
            with self._lock:
                job = self._job(name)
                if self._is_active(job):
                    continue
                job.state = "WAITING"
                job.progress = None
                job.payload = None
                job.exit_code = None
                job.error = None
                job.current_drives.clear()
                job.seen_drives.clear()
                job.managed = True
                job.selected = False
                control = ResticExecutionControl()
                job.control = control
                thread = threading.Thread(
                    target=self._worker,
                    args=(name, callback, control),
                    name="rrbackup-operation-{0}".format(name),
                    daemon=False,
                )
                job.thread = thread
                self.started_count += 1
                self.message = "Starting {0}; other backups remain available.".format(name)
            thread.start()

    def _worker(
        self,
        name: str,
        callback: RunCallback,
        control: ResticExecutionControl,
    ) -> None:
        job = self._job(name)
        try:
            payload, exit_code = callback(
                job.record,
                lambda progress: self.update_progress(name, progress),
                control,
            )
            self.complete(name, payload, exit_code)
        except Exception as exc:
            self.fail(name, str(exc))
        finally:
            with self._lock:
                job = self._job(name)
                job.control = None

    def update_progress(self, name: str, progress: BackupProgress) -> None:
        with self._lock:
            job = self._job(name)
            job.state = "RUNNING"
            job.progress = progress
            job.current_drives = _current_drive_set(progress)
            job.seen_drives.update(job.current_drives)
            self.message = "{0} is running; select another idle backup and press R to start it.".format(name)

    def complete(self, name: str, payload: Dict[str, Any], exit_code: int) -> None:
        record_payload = payload.get("record")
        with self._lock:
            job = self._job(name)
            if isinstance(record_payload, Mapping):
                run = RunRecord.from_dict(record_payload)
                job.record = replace(job.record, latest_run=run)
                job.state = run.state.value.upper()
                job.progress = _progress_from_record(job.record) or job.progress
            else:
                job.state = "COMPLETED"
            job.payload = copy.deepcopy(payload)
            job.exit_code = int(exit_code)
            job.managed = False
            job.current_drives.clear()
            self.exit_codes.append(int(exit_code))
            self.message = "{0} finished as {1}.".format(name, job.state)

    def fail(self, name: str, error: str) -> None:
        with self._lock:
            job = self._job(name)
            job.state = "FAILURE"
            job.error = error
            job.exit_code = 3
            job.managed = False
            job.current_drives.clear()
            self.exit_codes.append(3)
            self.message = "{0} failed: {1}".format(name, error)

    def _stop_names(self, names: Sequence[str]) -> None:
        requested = 0
        with self._lock:
            jobs = [self._job(name) for name in names]
            for job in jobs:
                if job.control is None or not self._is_active(job):
                    continue
                job.state = "STOPPING"
                job.control.request_stop()
                requested += 1
            self.message = (
                "Graceful stop requested for {0} backup(s).".format(requested)
                if requested
                else "No active Restic process was available to stop."
            )

    def stop_all_managed(self) -> None:
        with self._lock:
            names = tuple(
                job.record.definition.name
                for job in self.jobs
                if job.managed and self._is_active(job)
            )
        self._stop_names(names)

    def has_active_managed(self) -> bool:
        with self._lock:
            return any(job.managed and self._is_active(job) for job in self.jobs)

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
                job.record = replace(job.record, latest_run=latest)
                job.state = "IDLE" if latest is None else latest.state.value.upper()
                job.progress = _progress_from_record(job.record)
                job.current_drives = _current_drive_set(job.progress)
                job.seen_drives.update(job.current_drives)
                changed = True
        return changed

    def join(self) -> None:
        with self._lock:
            threads = [job.thread for job in self.jobs if job.thread is not None]
        for thread in threads:
            thread.join()

    def outcome(self) -> OperationsOutcome:
        with self._lock:
            return OperationsOutcome(
                started_count=self.started_count,
                exit_codes=tuple(self.exit_codes),
            )


_COLOR_PAIRS = {
    "default": 1,
    "header": 2,
    "warning": 3,
    "success": 4,
    "info": 5,
    "active": 7,
    "error": 8,
    "dim": 1,
}


def _initialize_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_CYAN, -1)
    curses.init_pair(7, curses.COLOR_MAGENTA, -1)
    curses.init_pair(8, curses.COLOR_RED, -1)


def _attribute(color: str, *, selected: bool = False, bold: bool = False) -> int:
    value = curses.color_pair(_COLOR_PAIRS.get(color, 1))
    if color == "dim":
        value |= curses.A_DIM
    if selected:
        value |= curses.A_REVERSE
    if bold:
        value |= curses.A_BOLD
    return value


def _add_line(stdscr: Any, y: int, text: str, width: int, attribute: int = 0) -> None:
    if y < 0:
        return
    try:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 0, text[: max(0, width - 1)], attribute)
    except curses.error:
        pass


def _draw_dashboard(
    stdscr: Any,
    model: OperationsDashboardModel,
    *,
    filter_text: str,
    editing_filter: bool,
    filter_buffer: str,
    top_line: int,
    confirmation_scroll: int,
    dry_run: bool,
) -> Tuple[int, int]:
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()
    snapshots = model.snapshots(filter_text)
    focused = model.focused_name
    lines = build_operation_lines(snapshots, focused_name=focused)
    current_name = model.current_name

    title = "RRBackup — Backup Operations"
    if focused:
        title += " — FOCUSED: {0}".format(focused)
    filter_label = filter_buffer if editing_filter else filter_text or "*"
    _add_line(stdscr, 0, "Filter: {0}".format(filter_label), max_x, _attribute("header", bold=True))
    _add_line(stdscr, 1, title, max_x, _attribute("header", bold=True))
    _add_line(stdscr, 2, model.message, max_x, _attribute("info"))
    _add_line(
        stdscr,
        4,
        "SE BACKUP               HEALTH    STATE        DONE     SPEED          ETA       LAST COMPLETE LAST ATTEMPT  SOURCES",
        max_x,
        _attribute("header", bold=True),
    )

    confirmation_lines: Tuple[str, ...] = tuple()
    if model.confirm_action == "start":
        confirmation_lines = build_confirmation_lines(
            model.confirmation_snapshots(),
            dry_run=dry_run,
        )
    elif model.confirm_action == "stop":
        names = ", ".join(model.confirm_names)
        confirmation_lines = (
            "CONFIRM STOP — {0}".format(names),
            "Y stops the selected locally managed Restic process(es); N or Esc cancels.",
        )

    footer_height = 3
    confirmation_height = 0
    if confirmation_lines:
        confirmation_height = min(max(6, max_y // 2), len(confirmation_lines) + 2)
    list_start = 5
    list_height = max(1, max_y - list_start - footer_height - confirmation_height)

    parent_positions = {
        line.job_name: index
        for index, line in enumerate(lines)
        if line.parent and line.job_name is not None
    }
    selected_position = parent_positions.get(current_name, 0)
    if selected_position < top_line:
        top_line = selected_position
    elif selected_position >= top_line + list_height:
        top_line = selected_position - list_height + 1
    top_line = max(0, min(top_line, max(0, len(lines) - list_height)))

    for offset, line in enumerate(lines[top_line : top_line + list_height]):
        selected = line.parent and line.job_name == current_name
        _add_line(
            stdscr,
            list_start + offset,
            line.text,
            max_x,
            _attribute(line.color, selected=selected),
        )

    confirmation_max_scroll = 0
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
            _add_line(
                stdscr,
                separator_y + 1 + offset,
                text,
                max_x,
                _attribute("warning", bold=offset == 0),
            )

    _add_line(
        stdscr,
        max_y - 3,
        "Space: select | R: review/start | S: stop | e/c: expand/collapse | E/C: all | Enter/i/m: focus",
        max_x,
        _attribute("header"),
    )
    _add_line(
        stdscr,
        max_y - 2,
        "Up/Down/j/k: move | f: filter | PgUp/PgDn: confirmation scroll | Esc: back/cancel | Ctrl+C: stop all",
        max_x,
        _attribute("header"),
    )
    _add_line(
        stdscr,
        max_y - 1,
        "q/Ctrl+Q: close when no locally managed backup is active",
        max_x,
        _attribute("header"),
    )
    stdscr.refresh()
    return top_line, confirmation_max_scroll


def _dashboard_main(
    stdscr: Any,
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    dry_run: bool,
) -> OperationsOutcome:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    _initialize_colors()
    stdscr.timeout(200)
    model = OperationsDashboardModel(records)
    filter_text = ""
    filter_buffer = ""
    editing_filter = False
    top_line = 0
    confirmation_scroll = 0
    last_refresh = 0.0

    while True:
        now = time.monotonic()
        if now - last_refresh >= 1.0:
            model.refresh_persisted()
            last_refresh = now
        top_line, confirmation_max_scroll = _draw_dashboard(
            stdscr,
            model,
            filter_text=filter_text,
            editing_filter=editing_filter,
            filter_buffer=filter_buffer,
            top_line=top_line,
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
        elif key == ord("f"):
            editing_filter = True
            filter_buffer = filter_text
            try:
                curses.curs_set(1)
            except curses.error:
                pass
        elif key == 27 and model.focused_name is not None:
            model.toggle_focus()
            top_line = 0
        elif key == 3:
            model.stop_all_managed()
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


def run_operations_dashboard(
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    *,
    dry_run: bool = False,
) -> OperationsOutcome:
    """Keep inventory, confirmation, execution, and management in one UI."""

    if not records:
        return OperationsOutcome(started_count=0, exit_codes=tuple())
    return curses.wrapper(_dashboard_main, records, callback, dry_run)
