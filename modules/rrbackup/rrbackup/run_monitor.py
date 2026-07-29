"""Confirmed curses monitor for interactive backup execution."""

from __future__ import annotations

import copy
import curses
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .inventory import BackupInventoryRecord
from .monitored_restic import ResticExecutionControl
from .presentation import human_bytes
from .run_progress import BackupProgress


RunCallback = Callable[
    [BackupInventoryRecord, Callable[[BackupProgress], None], ResticExecutionControl],
    Tuple[Dict[str, Any], int],
]


@dataclass
class MonitorJob:
    """Mutable presentation state for one selected backup."""

    name: str
    state: str = "PENDING"
    progress: Optional[BackupProgress] = None
    payload: Optional[Dict[str, Any]] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class MonitorOutcome:
    """Result returned after the monitor is closed."""

    cancelled: bool
    payloads: Tuple[Dict[str, Any], ...]
    exit_codes: Tuple[int, ...]


class RunMonitorModel:
    """Thread-safe state shared by the curses UI and execution worker."""

    def __init__(self, records: Sequence[BackupInventoryRecord]) -> None:
        self._lock = threading.Lock()
        self.jobs = [MonitorJob(record.definition.name) for record in records]
        self.active_name: Optional[str] = None
        self.message = "Review the selected backups, then press Y to start."
        self.started = False
        self.cancelled = False
        self.stop_all = False
        self.done = threading.Event()
        self._active_control: Optional[ResticExecutionControl] = None

    def snapshot(self) -> Tuple[List[MonitorJob], Optional[str], str, bool, bool]:
        """Return a stable UI snapshot."""

        with self._lock:
            return (
                copy.deepcopy(self.jobs),
                self.active_name,
                self.message,
                self.started,
                self.stop_all,
            )

    def begin(self, name: str) -> None:
        with self._lock:
            self.active_name = name
            self.message = "Preparing {0}; CPU policy and lock checks may run first.".format(name)
            for job in self.jobs:
                if job.name == name:
                    job.state = "WAITING"
                    break

    def attach_control(self, control: ResticExecutionControl) -> None:
        with self._lock:
            self._active_control = control

    def clear_control(self, control: ResticExecutionControl) -> None:
        with self._lock:
            if self._active_control is control:
                self._active_control = None

    def update_progress(self, name: str, progress: BackupProgress) -> None:
        with self._lock:
            self.active_name = name
            self.message = "Restic is processing {0}.".format(name)
            for job in self.jobs:
                if job.name == name:
                    job.state = "RUNNING"
                    job.progress = progress
                    break

    def complete(self, name: str, payload: Dict[str, Any], exit_code: int) -> None:
        state = str(payload.get("record", {}).get("state", "completed")).upper()
        with self._lock:
            for job in self.jobs:
                if job.name == name:
                    job.state = state
                    job.payload = copy.deepcopy(payload)
                    job.exit_code = exit_code
                    break
            self.message = "{0} finished as {1}.".format(name, state)
            self.active_name = None

    def fail(self, name: str, error: str) -> None:
        with self._lock:
            for job in self.jobs:
                if job.name == name:
                    job.state = "FAILURE"
                    job.error = error
                    job.exit_code = 3
                    break
            self.message = "{0} failed: {1}".format(name, error)
            self.active_name = None

    def cancel_pending(self) -> None:
        with self._lock:
            for job in self.jobs:
                if job.state == "PENDING":
                    job.state = "CANCELLED"
            self.active_name = None

    def request_stop(self) -> bool:
        """Stop the active Restic process and cancel remaining selected backups."""

        with self._lock:
            self.stop_all = True
            control = self._active_control
            active_name = self.active_name
            if active_name:
                for job in self.jobs:
                    if job.name == active_name and job.state in {"WAITING", "RUNNING"}:
                        job.state = "STOPPING"
                        break
            self.message = "Graceful stop requested; waiting for Restic to exit."
        if control is None:
            return False
        return control.request_stop()

    def outcome(self) -> MonitorOutcome:
        with self._lock:
            payloads = tuple(
                copy.deepcopy(job.payload)
                for job in self.jobs
                if job.payload is not None
            )
            exit_codes = tuple(
                int(job.exit_code)
                for job in self.jobs
                if job.exit_code is not None
            )
            return MonitorOutcome(
                cancelled=self.cancelled,
                payloads=payloads,
                exit_codes=exit_codes,
            )


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes, secs)
    return "{0:02d}:{1:02d}".format(minutes, secs)


def _progress_values(progress: Optional[BackupProgress]) -> Tuple[str, str, str, str, str, str]:
    if progress is None:
        return "-", "-", "-", "-", "-", "-"
    return (
        "{0:6.2f}%".format(progress.percent_display),
        "{0}/{1}".format(progress.files_done, progress.total_files),
        "{0}/{1}".format(human_bytes(progress.bytes_done), human_bytes(progress.total_bytes)),
        "{0}/s".format(human_bytes(int(progress.bytes_per_second))),
        _duration(progress.seconds_elapsed),
        _duration(progress.eta_seconds),
    )


def _add_line(stdscr: Any, y: int, text: str, width: int, attribute: int = 0) -> None:
    try:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 0, text[: max(0, width - 1)], attribute)
    except curses.error:
        pass


def _draw_confirmation(
    stdscr: Any,
    records: Sequence[BackupInventoryRecord],
    message: str,
) -> None:
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()
    _add_line(
        stdscr,
        0,
        "RRBackup - Confirm backup execution",
        max_x,
        curses.A_BOLD,
    )
    _add_line(stdscr, 2, "The following real backup runs are selected:", max_x)
    line = 4
    for record in records:
        profile = record.definition.profile
        _add_line(
            stdscr,
            line,
            "  - {0}: {1} -> {2}".format(
                record.definition.name,
                record.definition.source_summary,
                profile.repository,
            ),
            max_x,
        )
        line += 1
    _add_line(stdscr, min(line + 1, max_y - 4), message, max_x)
    _add_line(
        stdscr,
        max_y - 2,
        "Y: start inside monitor | N/Esc/Ctrl+Q: cancel",
        max_x,
        curses.A_BOLD,
    )
    stdscr.refresh()


def _draw_monitor(stdscr: Any, model: RunMonitorModel, stop_confirmation: bool) -> None:
    jobs, active_name, message, _, _ = model.snapshot()
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()
    _add_line(stdscr, 0, "RRBackup - Aggregate Restic progress", max_x, curses.A_BOLD)
    _add_line(stdscr, 1, message, max_x)
    _add_line(
        stdscr,
        3,
        "BACKUP               STATE        DONE     FILES             BYTES                   SPEED          ELAPSED   ETA",
        max_x,
        curses.A_BOLD,
    )
    line = 4
    active_progress: Optional[BackupProgress] = None
    for job in jobs:
        percent, files, byte_text, speed, elapsed, eta = _progress_values(job.progress)
        _add_line(
            stdscr,
            line,
            "{0:<20} {1:<12} {2:<8} {3:<17} {4:<23} {5:<14} {6:<9} {7}".format(
                job.name,
                job.state,
                percent,
                files,
                byte_text,
                speed,
                elapsed,
                eta,
            ),
            max_x,
        )
        line += 1
        if job.name == active_name:
            active_progress = job.progress
        if job.error and line < max_y - 5:
            _add_line(stdscr, line, "  Error: {0}".format(job.error), max_x)
            line += 1

    if active_progress is not None and line < max_y - 5:
        line += 1
        _add_line(stdscr, line, "Current files:", max_x, curses.A_BOLD)
        line += 1
        available = max(0, max_y - line - 4)
        for path in active_progress.current_files[-available:]:
            _add_line(stdscr, line, "  {0}".format(path), max_x)
            line += 1

    if stop_confirmation:
        _add_line(
            stdscr,
            max_y - 3,
            "Stop the active backup and cancel remaining selections? (y/N)",
            max_x,
            curses.A_BOLD | curses.A_REVERSE,
        )
    _add_line(
        stdscr,
        max_y - 2,
        "S: graceful stop | Ctrl+C: emergency graceful stop | resize supported",
        max_x,
    )
    _add_line(
        stdscr,
        max_y - 1,
        "After all runs finish: Enter/q/Ctrl+Q closes this monitor",
        max_x,
    )
    stdscr.refresh()


def _worker(
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    model: RunMonitorModel,
) -> None:
    try:
        for record in records:
            if model.stop_all:
                break
            name = record.definition.name
            model.begin(name)
            control = ResticExecutionControl()
            model.attach_control(control)
            try:
                payload, exit_code = callback(
                    record,
                    lambda progress, name=name: model.update_progress(name, progress),
                    control,
                )
                model.complete(name, payload, exit_code)
            except Exception as exc:
                model.fail(name, str(exc))
            finally:
                model.clear_control(control)
            if model.stop_all:
                break
    finally:
        model.cancel_pending()
        model.done.set()


def _monitor_main(
    stdscr: Any,
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
    model: RunMonitorModel,
) -> MonitorOutcome:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.timeout(200)
    worker: Optional[threading.Thread] = None
    stop_confirmation = False

    while True:
        if not model.started:
            _draw_confirmation(stdscr, records, model.message)
        else:
            _draw_monitor(stdscr, model, stop_confirmation)

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            key = 3
        if key == -1 or key == curses.KEY_RESIZE:
            continue

        if not model.started:
            if key in {ord("y"), ord("Y")}:
                model.started = True
                model.message = "Starting selected backups."
                worker = threading.Thread(
                    target=_worker,
                    args=(records, callback, model),
                    name="rrbackup-run-monitor",
                    daemon=False,
                )
                worker.start()
                continue
            if key in {ord("n"), ord("N"), 27, 17, ord("q"), ord("Q")}:
                model.cancelled = True
                return model.outcome()
            continue

        if model.done.is_set():
            if key in {10, 13, ord("q"), ord("Q"), 17, 27}:
                if worker is not None:
                    worker.join()
                return model.outcome()
            continue

        if stop_confirmation:
            if key in {ord("y"), ord("Y")}:
                model.request_stop()
                stop_confirmation = False
            elif key in {ord("n"), ord("N"), 27}:
                stop_confirmation = False
            continue

        if key in {ord("s"), ord("S")}:
            stop_confirmation = True
        elif key == 3:
            model.request_stop()
        elif key in {ord("q"), ord("Q"), 17}:
            model.message = "A backup is active; use S or Ctrl+C to stop it before closing."


def run_backup_monitor(
    records: Sequence[BackupInventoryRecord],
    callback: RunCallback,
) -> MonitorOutcome:
    """Confirm selected backups and keep execution inside one progress UI."""

    if not records:
        return MonitorOutcome(cancelled=True, payloads=tuple(), exit_codes=tuple())
    model = RunMonitorModel(records)
    return curses.wrapper(_monitor_main, records, callback, model)
