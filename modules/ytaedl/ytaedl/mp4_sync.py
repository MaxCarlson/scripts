#!/usr/bin/env python3
"""
Utility for synchronising MP4 files between matching subdirectories.

Features:
    * Copy or move MP4 files from source to destination while respecting file size collisions.
    * Dry-run mode for safe simulation.
    * Analyse mode that reports planned operations with colourised output and emits a JSON plan.
    * Plan application mode allowing execution from a previously generated JSON plan.
    * Optional continuous scanning mode that watches for new MP4 files after the initial run.
    * Rich logging and a live console dashboard updating several times per second.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


LOGGER = logging.getLogger("mp4_sync")
LOG_START_TIME: float = 0.0
PROGRESS_TRACKER: Optional["ProgressState"] = None


# ---------------------------------------------------------------------------
# Console helpers


def enable_vt_mode() -> None:
    """Enable ANSI escape sequence support on Windows terminals when possible."""
    if os.name != "nt":
        return

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    if handle == 0 or handle == -1:
        return

    mode = ctypes.c_ulong()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return

    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
    kernel32.SetConsoleMode(handle, new_mode)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def colour(text: str, code: str) -> str:
    """Wrap text with an ANSI colour code."""
    return f"\033[{code}m{text}\033[0m"


def bright(text: str) -> str:
    return colour(text, "97")


def green(text: str) -> str:
    return colour(text, "32")


def yellow(text: str) -> str:
    return colour(text, "33")


def red(text: str) -> str:
    return colour(text, "31")


def cyan(text: str) -> str:
    return colour(text, "36")


def magenta(text: str) -> str:
    return colour(text, "35")


def console_print(message: str = "", *, end: str = "\n") -> None:
    """Write `message` to stdout using UTF-8, tolerating encoding errors."""
    output = f"{message}{end}"
    try:
        sys.stdout.buffer.write(output.encode("utf-8", "replace"))
        sys.stdout.flush()
    except Exception:
        try:
            sys.stdout.write(output)
            sys.stdout.flush()
        except Exception:
            pass


def format_bytes(num: int) -> str:
    """Format a byte count into a human friendly string."""
    if num < 1024:
        return f"{num} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    size = float(num)
    for unit in units:
        size /= 1024.0
        if size < 1024:
            return f"{size:.2f} {unit}"
    return f"{size:.2f} EB"


def format_rate(num: float) -> str:
    """Format a bytes-per-second rate."""
    if num <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024
        idx += 1
    return f"{num:.2f} {units[idx]}"


def format_duration(seconds: float) -> str:
    """Format seconds into H:MM:SS.mmm."""
    millis = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:d}:{mins:02d}:{secs:02d}.{millis:03d}"


def format_elapsed_for_log(elapsed: float) -> str:
    """Return elapsed time as [HH:MM:SS.mmm] with zero-padded hours."""
    millis = int((elapsed - int(elapsed)) * 1000)
    total_seconds = int(elapsed)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}]"


LOG_COLOURS = {
    "COPY": green,
    "MOVE": cyan,
    "DELETE": red,
    "REPLACE": magenta,
    "SKIP": yellow,
    "DIR": cyan,
    "PLAN": bright,
    "INFO": bright,
    "WARN": yellow,
    "ERROR": red,
    "DRYRUN": yellow,
    "SCAN": cyan,
    "MODE": cyan,
    "LIMIT": yellow,
    "TRIGGER": yellow,
    "STATE": cyan,
    "AUTO": magenta,
    "CONFIG": bright,
}


def log_event(status: str, message: str, *, level: int = logging.INFO) -> None:
    """Emit a log entry with the required prefixed timestamp and status.

    Multi-line messages are written as separate file records so that the watcher
    UI renders each sub-line on its own row rather than collapsing them with ' | '.
    Continuation lines (lines 2+) use a 4-space indent prefix in the file so the
    UI reader can distinguish them from new events.
    """
    elapsed = time.perf_counter() - LOG_START_TIME if LOG_START_TIME else 0.0
    prefix = format_elapsed_for_log(elapsed)
    status_upper = status.upper()
    formatted = message.splitlines() if message else []
    first_line_extra = formatted[0].strip() if formatted else ""
    colour_fn = LOG_COLOURS.get(status_upper, bright)
    status_coloured = colour_fn(status_upper)

    # Build the ANSI-coloured in-memory representation (for ProgressState / UI overlay)
    coloured_lines: List[str] = []
    if first_line_extra:
        coloured_lines.append(f"{prefix} {status_coloured} {first_line_extra}")
    else:
        coloured_lines.append(f"{prefix} {status_coloured}")

    # Plain continuation lines for the file (written as separate logger records)
    plain_continuations: List[str] = []
    for line in formatted[1:]:
        raw = line.strip()
        if not raw:
            coloured_lines.append("")
            continue
        if raw.startswith("→"):
            value = raw[1:].strip()
            coloured_lines.append(f"    → {colour_fn(value)}")
            plain_continuations.append(f"    → {value}")
        elif raw.startswith(("KEEP", "KEPT", "DEL ", "DEL\t")):
            coloured_lines.append(f"    {colour_fn(raw)}")
            plain_continuations.append(f"    {raw}")
        elif ":" in raw:
            # Guard against Windows drive letters (e.g. "B:/path") being split as label:value.
            # A valid label has length > 1 and contains no path separators.
            label_candidate = raw.partition(":")[0]
            label_clean = label_candidate.strip()
            if len(label_clean) > 1 and "/" not in label_candidate and "\\" not in label_candidate:
                label, value = raw.split(":", 1)
                coloured_lines.append(f"    {label.strip():<12}: {colour_fn(value.strip())}")
                plain_continuations.append(f"    {label.strip():<12}: {value.strip()}")
            else:
                coloured_lines.append(f"    {colour_fn(raw)}")
                plain_continuations.append(f"    {raw}")
        else:
            coloured_lines.append(f"    {colour_fn(raw)}")
            plain_continuations.append(f"    {raw}")

    full_message = "\n".join(coloured_lines)
    # Write the first line as the timestamped record, then each continuation separately
    # so the file reader (and UI) sees one display line per item.
    LOGGER.log(level, f"{prefix} {status_upper} {first_line_extra}".strip())
    for cont in plain_continuations:
        LOGGER.log(level, cont)
    if PROGRESS_TRACKER:
        PROGRESS_TRACKER.add_log_entry(full_message)


def set_progress_tracker(state: Optional["ProgressState"]) -> None:
    global PROGRESS_TRACKER
    PROGRESS_TRACKER = state


# ---------------------------------------------------------------------------
# Data structures


ACTION_COPY = "copy"
ACTION_MOVE = "move"
ACTION_SKIP = "skip"
ACTION_REPLACE = "replace"
ACTION_CREATE_DIR = "create_dir"
ACTION_DELETE = "delete"  # Delete an inferior copy (stay-at-staging collision resolution)

VALID_OPERATIONS = {ACTION_COPY, ACTION_MOVE}

ACTIONS_ORDER = [ACTION_COPY, ACTION_MOVE, ACTION_REPLACE, ACTION_SKIP, ACTION_DELETE]
ACTION_LABELS = {
    ACTION_COPY: "Copies",
    ACTION_MOVE: "Moves",
    ACTION_REPLACE: "Replacements",
    ACTION_SKIP: "Skipped",
    ACTION_DELETE: "Deletions",
}
ACTION_COLORS = {
    ACTION_COPY: green,
    ACTION_MOVE: cyan,
    ACTION_REPLACE: magenta,
    ACTION_SKIP: yellow,
    ACTION_DELETE: red,
}


@dataclass
class Action:
    """Plan entry describing an operation the tool should execute."""

    action: str
    source: Optional[str]
    destination: Optional[str]
    reason: str
    source_size: Optional[int] = None
    destination_size: Optional[int] = None
    collision: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "action": self.action,
            "source": self.source,
            "destination": self.destination,
            "reason": self.reason,
            "source_size": self.source_size,
            "destination_size": self.destination_size,
            "collision": self.collision,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "Action":
        return Action(
            action=str(payload["action"]),
            source=payload.get("source"),
            destination=payload.get("destination"),
            reason=str(payload.get("reason", "")),
            source_size=payload.get("source_size"),
            destination_size=payload.get("destination_size"),
            collision=bool(payload.get("collision", False)),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass
class Plan:
    """Collection of actions with metadata."""

    source: str
    destination: str
    operation: str
    generated_at: float
    actions: List[Action]

    def to_dict(self) -> Dict[str, object]:
        return {
            "metadata": {
                "source": self.source,
                "destination": self.destination,
                "operation": self.operation,
                "generated_at": self.generated_at,
                "action_count": len(self.actions),
            },
            "actions": [action.to_dict() for action in self.actions],
        }

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "Plan":
        metadata = dict(payload.get("metadata", {}))
        actions_payload = payload.get("actions", [])
        actions = [Action.from_dict(item) for item in actions_payload]
        return Plan(
            source=str(metadata.get("source", "")),
            destination=str(metadata.get("destination", "")),
            operation=str(metadata.get("operation", ACTION_COPY)),
            generated_at=float(metadata.get("generated_at", time.time())),
            actions=actions,
        )


class ProgressState:
    """Thread-safe progress tracker for the live UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.start_time = time.perf_counter()
            self.current_folder = ""
            self.current_file = ""
            self.total_files = 0
            self.processed_files = 0
            self.copied_without_collision = 0
            self.collisions = 0
            self.replaced_dest = 0
            self.kept_dest = 0
            self.scan_new_files = 0
            self.scanning = False
            self.running = True
            self.last_message = ""
            self.console_index = 0
            self.recent_logs: deque[str] = deque(maxlen=200)
            self.total_bytes = 0
            self.processed_bytes = 0
            self.current_file_size = 0
            self.current_file_done = 0
            self.current_speed = 0.0
            self.current_folder_key = ""
            self.current_folder_total_files = 0
            self.current_folder_processed_files = 0
            self.current_folder_total_bytes = 0
            self.current_folder_processed_bytes = 0
            self.folder_totals: Dict[str, Dict[str, int]] = {}
            self.folder_progress: Dict[str, Dict[str, int]] = {}
            self.ui_enabled = False

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            folder_key = self.current_folder_key
            folder_totals = self.folder_totals.get(folder_key, {"files": 0, "bytes": 0})
            folder_progress = self.folder_progress.get(folder_key, {"files": 0, "bytes": 0})
            return {
                "start_time": self.start_time,
                "current_folder": self.current_folder,
                "current_file": self.current_file,
                "total_files": self.total_files,
                "processed_files": self.processed_files,
                "copied_without_collision": self.copied_without_collision,
                "collisions": self.collisions,
                "replaced_dest": self.replaced_dest,
                "kept_dest": self.kept_dest,
                "scan_new_files": self.scan_new_files,
                "scanning": self.scanning,
                "running": self.running,
                "last_message": self.last_message,
                "console_index": self.console_index,
                "recent_logs": list(self.recent_logs),
                "total_bytes": self.total_bytes,
                "processed_bytes": self.processed_bytes,
                "current_file_size": self.current_file_size,
                "current_file_done": self.current_file_done,
                "current_speed": self.current_speed,
                "current_folder_key": folder_key,
                "current_folder_total_files": folder_totals.get("files", 0),
                "current_folder_total_bytes": folder_totals.get("bytes", 0),
                "current_folder_processed_files": folder_progress.get("files", 0),
                "current_folder_processed_bytes": folder_progress.get("bytes", 0),
                "ui_enabled": self.ui_enabled,
            }

    def update_current(self, folder: str, filename: str) -> None:
        with self._lock:
            self.current_folder = folder
            self.current_file = filename

    def set_total_bytes(self, value: int) -> None:
        with self._lock:
            self.total_bytes = value
            self.processed_bytes = 0

    def increment_processed(self) -> None:
        with self._lock:
            self.processed_files += 1

    def increment_total(self) -> None:
        with self._lock:
            self.total_files += 1

    def set_total_files(self, value: int) -> None:
        with self._lock:
            self.total_files = value

    def set_folder_totals(self, totals: Dict[str, Dict[str, int]]) -> None:
        with self._lock:
            self.folder_totals = totals
            self.folder_progress = {key: {"files": 0, "bytes": 0} for key in totals}

    def next_console_index(self) -> int:
        with self._lock:
            self.console_index += 1
            return self.console_index

    def increment_copied(self) -> None:
        with self._lock:
            self.copied_without_collision += 1

    def increment_collisions(self, replaced: bool) -> None:
        with self._lock:
            self.collisions += 1
            if replaced:
                self.replaced_dest += 1
            else:
                self.kept_dest += 1

    def add_scan_new_file(self) -> None:
        with self._lock:
            self.scan_new_files += 1

    def set_scanning(self, value: bool) -> None:
        with self._lock:
            self.scanning = value

    def set_running(self, value: bool) -> None:
        with self._lock:
            self.running = value

    def set_message(self, message: str) -> None:
        with self._lock:
            self.last_message = message

    def add_log_entry(self, entry: str) -> None:
        with self._lock:
            self.recent_logs.append(entry)

    def set_ui_enabled(self, value: bool) -> None:
        with self._lock:
            self.ui_enabled = value

    def ui_is_enabled(self) -> bool:
        with self._lock:
            return self.ui_enabled

    def start_file(self, folder_key: str, folder_name: str, filename: str, file_size: int) -> None:
        with self._lock:
            self.current_folder_key = folder_key
            self.current_folder_total_files = self.folder_totals.get(folder_key, {}).get("files", 0)
            self.current_folder_total_bytes = self.folder_totals.get(folder_key, {}).get("bytes", 0)
            progress = self.folder_progress.setdefault(folder_key, {"files": 0, "bytes": 0})
            self.current_folder_processed_files = progress.get("files", 0)
            self.current_folder_processed_bytes = progress.get("bytes", 0)
            self.current_file_size = file_size
            self.current_file_done = 0
            self.current_speed = 0.0
            self.current_folder = folder_name
            self.current_file = filename

    def update_file_progress(self, bytes_added: int, elapsed: float) -> None:
        if bytes_added <= 0:
            return
        with self._lock:
            self.current_file_done = min(self.current_file_done + bytes_added, self.current_file_size or float("inf"))
            self.processed_bytes += bytes_added
            folder_key = self.current_folder_key
            progress = self.folder_progress.setdefault(folder_key, {"files": 0, "bytes": 0})
            progress["bytes"] += bytes_added
            self.current_folder_processed_bytes = progress["bytes"]
            if elapsed > 0:
                instant_speed = bytes_added / elapsed
                if self.current_speed > 0:
                    self.current_speed = (self.current_speed * 0.7) + (instant_speed * 0.3)
                else:
                    self.current_speed = instant_speed

    def finish_file(self, file_size: int) -> None:
        with self._lock:
            folder_key = self.current_folder_key
            progress = self.folder_progress.setdefault(folder_key, {"files": 0, "bytes": 0})
            progress["files"] += 1
            self.current_folder_processed_files = progress["files"]
            self.current_folder_processed_bytes = progress["bytes"]
            if self.current_file_done < file_size:
                delta = file_size - self.current_file_done
                self.current_file_done = file_size
                self.processed_bytes += delta
                progress["bytes"] += delta
                self.current_folder_processed_bytes = progress["bytes"]

    def record_skip(self, file_size: int) -> None:
        with self._lock:
            folder_key = self.current_folder_key
            progress = self.folder_progress.setdefault(folder_key, {"files": 0, "bytes": 0})
            progress["files"] += 1
            progress["bytes"] += file_size
            self.current_folder_processed_files = progress["files"]
            self.current_folder_processed_bytes = progress["bytes"]
            self.processed_bytes += file_size
            self.current_file_done = file_size
            self.current_speed = 0.0

    def complete_simulated_file(self, file_size: int) -> None:
        with self._lock:
            folder_key = self.current_folder_key
            progress = self.folder_progress.setdefault(folder_key, {"files": 0, "bytes": 0})
            progress["files"] += 1
            progress["bytes"] += file_size
            self.current_folder_processed_files = progress["files"]
            self.current_folder_processed_bytes = progress["bytes"]
            self.processed_bytes += file_size
            self.current_file_done = file_size
            self.current_speed = 0.0


@dataclass
class SummaryRow:
    action: str
    label: str
    count: int = 0
    transfer_size: int = 0
    source_deleted_size: int = 0
    destination_added_size: int = 0
    destination_deleted_size: int = 0
    skipped_size: int = 0


@dataclass
class SummaryStats:
    rows: Dict[str, SummaryRow]
    total_transfer_size: int = 0
    total_source_deleted_count: int = 0
    total_source_deleted_size: int = 0
    total_destination_deleted_count: int = 0
    total_destination_deleted_size: int = 0
    total_destination_added_size: int = 0
    total_skipped_count: int = 0
    total_skipped_size: int = 0


# ---------------------------------------------------------------------------
# Summary helpers


def compute_summary(actions: Iterable[Action], *, delete_source: bool) -> SummaryStats:
    rows: Dict[str, SummaryRow] = {
        action: SummaryRow(action=action, label=ACTION_LABELS[action]) for action in ACTIONS_ORDER
    }
    stats = SummaryStats(rows=rows)

    for action in actions:
        if action.action == ACTION_CREATE_DIR:
            continue
        row = rows.setdefault(
            action.action,
            SummaryRow(action=action.action, label=ACTION_LABELS.get(action.action, action.action.title())),
        )
        source_size = action.source_size or 0
        dest_size = action.destination_size or 0
        row.count += 1
        metadata_flag = action.metadata.get("delete_source")
        delete_this_source = metadata_flag.lower() == "true" if isinstance(metadata_flag, str) else delete_source
        if action.action == ACTION_SKIP:
            row.skipped_size += source_size
            stats.total_skipped_count += 1
            stats.total_skipped_size += source_size
            if delete_this_source:
                row.source_deleted_size += source_size
                stats.total_source_deleted_count += 1
                stats.total_source_deleted_size += source_size
            continue

        row.transfer_size += source_size
        stats.total_transfer_size += source_size

        if action.action == ACTION_COPY:
            row.destination_added_size += source_size
            stats.total_destination_added_size += source_size
            if delete_this_source:
                row.source_deleted_size += source_size
                stats.total_source_deleted_count += 1
                stats.total_source_deleted_size += source_size
        elif action.action == ACTION_MOVE:
            row.destination_added_size += source_size
            stats.total_destination_added_size += source_size
            if delete_this_source:
                row.source_deleted_size += source_size
                stats.total_source_deleted_count += 1
                stats.total_source_deleted_size += source_size
        elif action.action == ACTION_REPLACE:
            row.destination_deleted_size += dest_size
            if dest_size:
                stats.total_destination_deleted_count += 1
                stats.total_destination_deleted_size += dest_size
            diff = max(source_size - dest_size, 0)
            row.destination_added_size += diff
            stats.total_destination_added_size += diff
            if delete_this_source:
                row.source_deleted_size += source_size
                stats.total_source_deleted_count += 1
                stats.total_source_deleted_size += source_size
        elif action.action == ACTION_DELETE:
            # source is the inferior copy being removed; no data is transferred.
            row.source_deleted_size += source_size
            stats.total_source_deleted_count += 1
            stats.total_source_deleted_size += source_size

    return stats


def format_summary_row(
    label: str, count, transfer: str, src_del: str, dest_add: str, dest_del: str, skipped: str
) -> str:
    def shorten(text: str, width: int) -> str:
        return text if len(text) <= width else text[: width - 1] + "…"

    label_fmt = shorten(str(label), 14)
    return "{:<14} | {:>5} | {:>10} | {:>11} | {:>11} | {:>11} | {:>11}".format(
        label_fmt,
        count,
        transfer,
        src_del,
        dest_add,
        dest_del,
        skipped,
    )


def print_summary_table(summary: SummaryStats, *, dry_run: bool = False) -> None:
    console_print()
    title = "Summary Table (dry-run preview)" if dry_run else "Summary Table"
    console_print(bright(title))
    if dry_run:
        console_print(yellow("Values indicate what would occur if changes were executed."))

    header = format_summary_row(
        "Operation",
        "Files",
        "Transfer",
        "Src Deleted",
        "Dest Added",
        "Dest Removed",
        "Skipped",
    )
    console_print(bright(header))
    console_print(bright("-" * len(header)))

    for action in ACTIONS_ORDER:
        row = summary.rows.get(action) or SummaryRow(action=action, label=ACTION_LABELS.get(action, action.title()))
        color_fn = ACTION_COLORS.get(action, bright)
        line = format_summary_row(
            row.label,
            row.count,
            format_bytes(row.transfer_size),
            format_bytes(row.source_deleted_size),
            format_bytes(row.destination_added_size),
            format_bytes(row.destination_deleted_size),
            format_bytes(row.skipped_size),
        )
        console_print(color_fn(line))

    console_print()
    console_print(bright("Totals"))
    console_print(
        f"  Source deletions: {summary.total_source_deleted_count} files | {format_bytes(summary.total_source_deleted_size)}"
    )
    console_print(
        f"  Destination deletions: {summary.total_destination_deleted_count} files | {format_bytes(summary.total_destination_deleted_size)}"
    )
    console_print(f"  Destination additions: {format_bytes(summary.total_destination_added_size)}")
    console_print(f"  Total data processed: {format_bytes(summary.total_transfer_size)}")
    if summary.total_skipped_count:
        console_print(
            f"  Skipped files: {summary.total_skipped_count} | {format_bytes(summary.total_skipped_size)} (destination kept)"
        )
    console_print()


class ProgressUI:
    """Background thread responsible for refreshing the console dashboard."""

    def __init__(self, state: ProgressState, enabled: bool = True, refresh_hz: float = 4.0) -> None:
        self.state = state
        self.enabled = enabled and sys.stdout.isatty()
        self.refresh_interval = 1.0 / max(refresh_hz, 0.1)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="progress-ui", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            snapshot = self.state.snapshot()
            now = time.perf_counter()
            elapsed = now - snapshot["start_time"]
            total_bytes = snapshot.get("total_bytes", 0)
            processed_bytes = snapshot.get("processed_bytes", 0)
            total_percent = (processed_bytes / total_bytes * 100) if total_bytes else 0.0
            current_file_size = snapshot.get("current_file_size", 0)
            current_file_done = snapshot.get("current_file_done", 0)
            file_percent = (current_file_done / current_file_size * 100) if current_file_size else 0.0
            folder_total_files = snapshot.get("current_folder_total_files", 0)
            folder_processed_files = snapshot.get("current_folder_processed_files", 0)
            folder_total_bytes = snapshot.get("current_folder_total_bytes", 0)
            folder_processed_bytes = snapshot.get("current_folder_processed_bytes", 0)
            folder_percent = folder_processed_bytes / folder_total_bytes * 100 if folder_total_bytes else 0.0
            current_speed = snapshot.get("current_speed", 0.0)
            lines = [
                bright("MP4 Folder Synchroniser"),
                f"Elapsed: {format_duration(elapsed)}",
                f"Current folder: {snapshot['current_folder'] or '-'}",
                f"Current file: {snapshot['current_file'] or '-'}",
                f"Files processed: {snapshot['processed_files']} / {snapshot['total_files']}",
                f"Copied (no collision): {snapshot['copied_without_collision']}",
                f"Collisions: {snapshot['collisions']} "
                f"(replaced: {snapshot['replaced_dest']}, kept dest: {snapshot['kept_dest']})",
                f"Total progress: {format_bytes(processed_bytes)} / {format_bytes(total_bytes)} ({total_percent:.1f}%)",
            ]
            lines.append("")
            lines.append(bright("Transfer Progress"))
            if current_file_size:
                lines.append(
                    f"File progress: {format_bytes(current_file_done)} / {format_bytes(current_file_size)} "
                    f"({file_percent:.1f}%) @ {format_rate(current_speed)}"
                )
            if folder_total_files:
                lines.append(
                    f"Folder progress: {folder_processed_files}/{folder_total_files} files | "
                    f"{format_bytes(folder_processed_bytes)} / {format_bytes(folder_total_bytes)} "
                    f"({folder_percent:.1f}%)"
                )
            if snapshot["scanning"]:
                lines.append(f"Scan mode: new files handled {snapshot['scan_new_files']}")
            if snapshot["last_message"]:
                lines.append(f"Status: {snapshot['last_message']}")
            recent_logs = snapshot.get("recent_logs") or []
            lines.append("")
            lines.append(bright("Recent Activity"))
            if recent_logs:
                for entry in recent_logs:
                    display = entry if len(entry) <= 120 else f"{entry[:117]}..."
                    lines.append(f"  {display}")
            else:
                lines.append("  (no events yet)")

            text = "\n".join(lines)
            output = f"\033[2J\033[H{text}\n"
            try:
                sys.stdout.write(output)
                sys.stdout.flush()
            except Exception:
                # Fallback to printing once if terminal write fails.
                print(text)
                break
            time.sleep(self.refresh_interval)


# ---------------------------------------------------------------------------
# Core functionality


def list_immediate_subdirs(path: Path) -> Iterable[Path]:
    for entry in path.iterdir():
        if entry.is_dir():
            yield entry


def iter_mp4_files(directory: Path) -> Iterable[Path]:
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        name_lower = entry.name.lower()
        if not name_lower.endswith(".mp4"):
            continue
        if name_lower.endswith(".part.mp4") or name_lower.endswith(".mp4.part"):
            continue
        yield entry


def _find_stem_in_dir(stem: str, directory: Path) -> Optional[Path]:
    """Return the first file in *directory* whose stem matches *stem* (case-insensitive).

    Allows the watcher to detect same-video files that have a different container
    extension in the destination (e.g. destination has .webm, staging has .mp4).
    Returns None if the directory doesn't exist or no match is found.
    """
    try:
        stem_lower = stem.lower()
        for p in directory.iterdir():
            if p.is_file() and p.stem.lower() == stem_lower:
                return p
    except Exception:
        pass
    return None


def ensure_directory_plan(actions: List[Action], directory: Path) -> None:
    directory_str = str(directory)
    if any(action.action == ACTION_CREATE_DIR and action.destination == directory_str for action in actions):
        return
    actions.append(
        Action(
            action=ACTION_CREATE_DIR,
            source=None,
            destination=directory_str,
            reason="destination subdirectory missing",
        )
    )


def determine_action(
    src_file: Path,
    dest_dir: Path,
    operation: str,
    *,
    src_size: Optional[int] = None,
) -> Action:
    dest_file = dest_dir / src_file.name
    if src_size is None:
        src_size = src_file.stat().st_size
    metadata = {"requested_operation": operation}

    if not dest_dir.exists():
        reason = "destination missing; will create directory and transfer file"
        return Action(
            action=operation,
            source=str(src_file),
            destination=str(dest_file),
            reason=reason,
            source_size=src_size,
            destination_size=None,
            collision=False,
            metadata=metadata,
        )

    if not dest_file.exists():
        # Fall back to stem-based match: catches same video in a different container format.
        stem_match = _find_stem_in_dir(src_file.stem, dest_dir)
        if stem_match is not None:
            dest_size = stem_match.stat().st_size
            if src_size <= dest_size:
                reason = (
                    f"stem match '{stem_match.name}' at destination is larger/equal; "
                    "skipping to avoid duplicate (different extension)"
                )
                collision_metadata = {
                    "source_path": str(src_file),
                    "destination_path": str(stem_match),
                    "requested_operation": operation,
                    "resolution": "skip",
                    "match_type": "stem",
                }
                return Action(
                    action=ACTION_SKIP,
                    source=str(src_file),
                    destination=str(stem_match),
                    reason=reason,
                    source_size=src_size,
                    destination_size=dest_size,
                    collision=True,
                    metadata=collision_metadata,
                )
            else:
                reason = (
                    f"stem match '{stem_match.name}' at destination is smaller; "
                    "replacing with larger source (different extension)"
                )
                collision_metadata = {
                    "source_path": str(src_file),
                    "destination_path": str(stem_match),
                    "requested_operation": operation,
                    "resolution": "replace",
                    "match_type": "stem",
                }
                return Action(
                    action=ACTION_REPLACE,
                    source=str(src_file),
                    destination=str(stem_match),
                    reason=reason,
                    source_size=src_size,
                    destination_size=dest_size,
                    collision=True,
                    metadata=collision_metadata,
                )
        reason = "no destination file; transfer needed"
        return Action(
            action=operation,
            source=str(src_file),
            destination=str(dest_file),
            reason=reason,
            source_size=src_size,
            destination_size=None,
            collision=False,
            metadata=metadata,
        )

    dest_size = dest_file.stat().st_size
    collision_metadata = {
        "source_path": str(src_file),
        "destination_path": str(dest_file),
        "requested_operation": operation,
    }

    if src_size > dest_size:
        reason = "collision resolved by replacing destination (source is larger)"
        collision_metadata["resolution"] = "replace"
        return Action(
            action=ACTION_REPLACE,
            source=str(src_file),
            destination=str(dest_file),
            reason=reason,
            source_size=src_size,
            destination_size=dest_size,
            collision=True,
            metadata=collision_metadata,
        )

    reason = "collision resolved by keeping destination (destination is larger or equal)"
    collision_metadata["resolution"] = "skip"
    return Action(
        action=ACTION_SKIP,
        source=str(src_file),
        destination=str(dest_file),
        reason=reason,
        source_size=src_size,
        destination_size=dest_size,
        collision=True,
        metadata=collision_metadata,
    )


def build_plan(
    source: Path,
    destination: Path,
    operation: str,
    progress: Optional[ProgressState] = None,
) -> Tuple[Plan, Dict[str, Dict[str, int]]]:
    actions: List[Action] = []
    total_files = 0
    folder_totals: Dict[str, Dict[str, int]] = {}

    for src_subdir in sorted(list_immediate_subdirs(source)):
        dest_subdir = destination / src_subdir.name
        mp4_files = sorted(iter_mp4_files(src_subdir))
        folder_total_files = len(mp4_files)
        folder_total_bytes = 0
        file_stats: List[Tuple[Path, int]] = []
        for src_file in mp4_files:
            try:
                size = src_file.stat().st_size
            except FileNotFoundError:
                continue
            folder_total_bytes += size
            file_stats.append((src_file, size))
        folder_key = src_subdir.name
        if folder_total_files:
            folder_totals[folder_key] = {"files": folder_total_files, "bytes": folder_total_bytes}
        if progress:
            progress.set_message(f"Scanning {src_subdir}")
        for src_file, src_size in file_stats:
            total_files += 1
            if progress:
                progress.increment_total()
            action = determine_action(src_file, dest_subdir, operation, src_size=src_size)
            action.metadata["folder_key"] = folder_key
            action.metadata["folder_total_files"] = folder_total_files
            action.metadata["folder_total_bytes"] = folder_total_bytes
            if action.action != ACTION_SKIP and not dest_subdir.exists():
                ensure_directory_plan(actions, dest_subdir)
            actions.append(action)

    plan = Plan(
        source=str(source),
        destination=str(destination),
        operation=operation,
        generated_at=time.time(),
        actions=actions,
    )

    if progress:
        progress.set_message(f"Plan prepared with {len(actions)} actions")
    log_event("PLAN", f"Plan generated: {len(actions)} actions across {total_files} source files")
    return plan, folder_totals


def _common_suffix_parts(path_a: Path, path_b: Path) -> List[str]:
    """Return the rightmost path-parent parts shared by both paths (case-insensitive)."""
    parts_a = list(path_a.parent.parts)
    parts_b = list(path_b.parent.parts)
    common: List[str] = []
    for pa, pb in zip(reversed(parts_a), reversed(parts_b)):
        if pa.lower() == pb.lower():
            common.append(pa)
        else:
            break
    common.reverse()
    return common


def _unique_location_label(path: Path, other: Path) -> str:
    """Return the shortest root prefix of *path* that distinguishes it from *other*.

    E.g. given ``B:\\stars\\yuki_rino\\file.mp4`` vs ``D:\\tmp\\stars\\yuki_rino\\file.mp4``
    the common suffix is ``stars\\yuki_rino`` so this returns ``B:\\``.
    """
    parts_self = list(path.parent.parts)
    parts_other = list(other.parent.parts)
    common_len = 0
    for ps, po in zip(reversed(parts_self), reversed(parts_other)):
        if ps.lower() == po.lower():
            common_len += 1
        else:
            break
    unique_parts = parts_self[: len(parts_self) - common_len] if common_len < len(parts_self) else parts_self
    if not unique_parts:
        return str(path.parent)
    try:
        result = str(Path(*unique_parts))
    except Exception:
        result = os.sep.join(unique_parts)
    if not result.endswith((os.sep, "/")):
        result += os.sep
    return result


def _format_collision_log(
    winner: Path,
    winner_size: int,
    loser: Path,
    loser_size: int,
    verdict: str,
    dry_run: bool,
) -> str:
    """Return a compact multi-line log message for a stay-at-staging collision.

    The first line is a one-line verdict bracket suitable as the log_event header.
    Subsequent lines show KEEP/DEL with minimal distinguishing paths so the reader
    can immediately see *where* each copy lives without repeating redundant path segments.
    """
    size_diff = abs(winner_size - loser_size)
    action_word = "would delete" if dry_run else "deleted"
    size_summary = f"{format_bytes(winner_size)} > {format_bytes(loser_size)}  (+{format_bytes(size_diff)})"
    header = f"[{verdict} · {size_summary} · {action_word} inferior copy]"

    same_name = winner.name.lower() == loser.name.lower()
    common = _common_suffix_parts(winner, loser)

    if common and same_name:
        # Compact form: show the filename + common path once, then just the unique roots
        common_str = os.sep.join(common)
        winner_root = _unique_location_label(winner, loser)
        loser_root = _unique_location_label(loser, winner)
        return (
            f"{header}\n"
            f"→ {winner.name}  (in ...{os.sep}{common_str}{os.sep})\n"
            f"KEEP   {winner_root}\n"
            f"DEL    {loser_root}"
        )
    else:
        # Full paths when names differ or no common parent
        return (
            f"{header}\n"
            f"KEEP   {winner}\n"
            f"DEL    {loser}"
        )


def build_stay_at_staging_plan(
    staging_root: Path,
    original_destination_root: Path,
    progress: Optional[ProgressState] = None,
) -> Tuple[Plan, Dict[str, Dict[str, int]]]:
    """Build a collision-check plan for stay-at-staging mode.

    In this mode files at *staging_root* are already in their final location and will
    not be moved.  We scan for duplicate files between *staging_root* and
    *original_destination_root* and plan to delete whichever copy is inferior (smaller).

    Actions produced:
    - ACTION_SKIP  – no collision; staging file is fine where it is.
    - ACTION_DELETE – delete the inferior duplicate.
        metadata["winner_path"]     = absolute path of the file that will be kept.
        metadata["winner_location"] = "staging" | "original_destination".
        metadata["loser_path"]      = absolute path of the file that will be deleted.
        metadata["loser_location"]  = "staging" | "original_destination".
        metadata["resolution"]      = "delete_original" | "delete_staging".
    """
    actions: List[Action] = []
    total_files = 0
    no_collision_count = 0
    folder_totals: Dict[str, Dict[str, int]] = {}

    for staging_subdir in sorted(list_immediate_subdirs(staging_root)):
        mp4_files = sorted(iter_mp4_files(staging_subdir))
        folder_total_files = len(mp4_files)
        folder_total_bytes = 0
        file_stats: List[Tuple[Path, int]] = []
        for staging_file in mp4_files:
            try:
                size = staging_file.stat().st_size
            except FileNotFoundError:
                continue
            folder_total_bytes += size
            file_stats.append((staging_file, size))

        folder_key = staging_subdir.name
        if folder_total_files:
            folder_totals[folder_key] = {"files": folder_total_files, "bytes": folder_total_bytes}

        orig_dest_subdir = original_destination_root / staging_subdir.name

        if progress:
            progress.set_message(f"Scanning {staging_subdir}")

        for staging_file, staging_size in file_stats:
            total_files += 1
            if progress:
                progress.increment_total()

            base_metadata: Dict[str, str] = {
                "folder_key": folder_key,
                "folder_total_files": str(folder_total_files),
                "folder_total_bytes": str(folder_total_bytes),
                "stay_at_staging": "true",
            }

            # Locate a matching file in the original destination (exact name or stem match).
            orig_match: Optional[Path] = None
            orig_size: int = 0
            orig_file = orig_dest_subdir / staging_file.name
            if orig_file.exists():
                orig_match = orig_file
                try:
                    orig_size = orig_file.stat().st_size
                except Exception:
                    orig_size = 0
            else:
                stem_match = _find_stem_in_dir(staging_file.stem, orig_dest_subdir)
                if stem_match is not None:
                    orig_match = stem_match
                    try:
                        orig_size = stem_match.stat().st_size
                    except Exception:
                        orig_size = 0

            if orig_match is None:
                # No collision – staging file is already correctly placed.
                no_collision_count += 1
                action = Action(
                    action=ACTION_SKIP,
                    source=str(staging_file),
                    destination=None,
                    reason="no collision detected; file stays at staging location",
                    source_size=staging_size,
                    destination_size=None,
                    collision=False,
                    metadata={
                        **base_metadata,
                        "winner_path": str(staging_file),
                        "winner_location": "staging",
                        "delete_source": "false",
                    },
                )
            elif staging_size >= orig_size:
                # Staging copy is better or equal – delete the original-destination copy.
                action = Action(
                    action=ACTION_DELETE,
                    source=str(orig_match),
                    destination=None,
                    reason=(
                        f"staging copy is larger or equal "
                        f"({format_bytes(staging_size)} >= {format_bytes(orig_size)}); "
                        "deleting inferior original-destination copy"
                    ),
                    source_size=orig_size,
                    destination_size=staging_size,
                    collision=True,
                    metadata={
                        **base_metadata,
                        "winner_path": str(staging_file),
                        "winner_location": "staging",
                        "loser_path": str(orig_match),
                        "loser_location": "original_destination",
                        "resolution": "delete_original",
                    },
                )
            else:
                # Original-destination copy is better – delete the staging copy.
                action = Action(
                    action=ACTION_DELETE,
                    source=str(staging_file),
                    destination=None,
                    reason=(
                        f"original-destination copy is larger "
                        f"({format_bytes(orig_size)} > {format_bytes(staging_size)}); "
                        "deleting inferior staging copy"
                    ),
                    source_size=staging_size,
                    destination_size=orig_size,
                    collision=True,
                    metadata={
                        **base_metadata,
                        "winner_path": str(orig_match),
                        "winner_location": "original_destination",
                        "loser_path": str(staging_file),
                        "loser_location": "staging",
                        "resolution": "delete_staging",
                    },
                )

            actions.append(action)

    plan = Plan(
        source=str(staging_root),
        destination=str(original_destination_root),
        operation="stay_at_staging",
        generated_at=time.time(),
        actions=actions,
    )

    collision_count = total_files - no_collision_count
    if progress:
        progress.set_message(f"Stay-at-staging plan ready: {collision_count} collision(s), {no_collision_count} clean")
    log_event(
        "PLAN",
        f"Stay-at-staging plan: {len(actions)} entries across {total_files} staging files "
        f"({collision_count} collision(s), {no_collision_count} with no duplicate)",
    )
    return plan, folder_totals


def write_plan(plan: Plan, output_path: Path) -> None:
    payload = plan.to_dict()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def load_plan(path: Path) -> Plan:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Plan.from_dict(data)


def derive_folder_metadata(plan: Plan, source_root: Path) -> Dict[str, Dict[str, int]]:
    folder_totals: Dict[str, Dict[str, int]] = {}
    for action in plan.actions:
        if action.action == ACTION_CREATE_DIR or not action.source:
            continue
        folder_path = Path(action.source).parent
        try:
            folder_key = folder_path.relative_to(source_root).parts[0]
        except Exception:
            folder_key = folder_path.name
        totals = folder_totals.setdefault(folder_key, {"files": 0, "bytes": 0})
        totals["files"] += 1
        totals["bytes"] += action.source_size or 0
        action.metadata.setdefault("folder_key", folder_key)
    for action in plan.actions:
        if action.action == ACTION_CREATE_DIR or not action.source:
            continue
        folder_key = action.metadata.get("folder_key")
        if folder_key in folder_totals:
            totals = folder_totals[folder_key]
            action.metadata["folder_total_files"] = totals["files"]
            action.metadata["folder_total_bytes"] = totals["bytes"]
    return folder_totals


def prompt_confirmation(action: Action) -> bool:
    """Ask the user whether to proceed with a planned operation."""
    while True:
        console_print("Proceed with this operation? [y]es / [n]o / [q]uit", end="")
        try:
            response = input(" ").strip().lower()
        except EOFError:
            return False
        if response in ("y", "yes", ""):
            return True
        if response in ("n", "no"):
            return False
        if response in ("q", "quit"):
            raise KeyboardInterrupt("User aborted interactive confirmation.")
        console_print("Please respond with y, n, or q.")


def _file_label(src_path: Path) -> str:
    """Compact display: filename + immediate parent folder (no full path repetition)."""
    return f"{src_path.name}  ({src_path.parent.name})"


def _skip_verdict(action: Action) -> str:
    dest_sz = format_bytes(action.destination_size or 0)
    src_sz = format_bytes(action.source_size or 0)
    if action.collision:
        return f"dest kept – {dest_sz} >= src {src_sz}"
    return "skipped"


def _replace_verdict(action: Action, *, dry_run: bool = False) -> str:
    src_sz = format_bytes(action.source_size or 0)
    dest_sz = format_bytes(action.destination_size or 0)
    verb = "would replace" if dry_run else "replaced"
    return f"{verb} – src {src_sz} > dest {dest_sz}"


def _transfer_verdict(action: Action, verb: str, *, dry_run: bool = False) -> str:
    src_sz = format_bytes(action.source_size or 0)
    prefix = "would " if dry_run else ""
    return f"{prefix}{verb} {src_sz}"


def maybe_delete_source(src_path: Path, dry_run: bool, no_delete: bool) -> bool:
    """Delete source file unless prevented; returns True if removed.

    Logging is intentionally omitted here — every caller already emits a log entry
    that names the file and describes the intended operation.  A separate DELETE /
    DRYRUN line would repeat the path and clutter the activity log.
    """
    if no_delete:
        return False
    if dry_run:
        return False
    if not src_path.exists():
        return True
    try:
        src_path.unlink()
        return True
    except Exception as exc:
        log_event("ERROR", f"delete failed: {src_path.name}\nerror: {exc}", level=logging.ERROR)
        return False


def copy_with_progress(
    src_path: Path, dest_path: Path, progress: ProgressState, chunk_size: int = 8 * 1024 * 1024
) -> None:
    src_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    last_time = time.perf_counter()
    bytes_copied = 0
    with src_path.open("rb") as src, dest_path.open("wb") as dest:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            dest.write(chunk)
            bytes_copied += len(chunk)
            now = time.perf_counter()
            elapsed = max(now - last_time, 1e-9)
            progress.update_file_progress(len(chunk), elapsed)
            last_time = now
    shutil.copystat(src_path, dest_path, follow_symlinks=True)


def execute_action(
    action: Action,
    dry_run: bool,
    progress: ProgressState,
    *,
    source_root: Optional[Path] = None,
    confirm: bool = False,
    no_delete: bool = False,
) -> Optional[Action]:
    action.metadata["delete_source"] = "true" if not no_delete else "false"
    if action.action == ACTION_CREATE_DIR:
        if dry_run:
            log_event("DRYRUN", f"path: {action.destination}\nreason: {action.reason}")
            progress.set_message(f"[dry-run] would create directory {action.destination}")
            return None
        path = Path(action.destination)
        path.mkdir(parents=True, exist_ok=True)
        log_event("DIR", f"path: {path}\nreason: {action.reason}")
        progress.set_message(f"Ensured destination directory {path}")
        if not progress.ui_is_enabled():
            console_print(cyan(f"Ensure directory: {path} ({action.reason})"))
            console_print()
        return None

    # Stay-at-staging no-collision skip: source is the staging file staying in place; no destination.
    if action.action == ACTION_SKIP and action.metadata.get("stay_at_staging") == "true":
        src_path = Path(action.source) if action.source else None
        file_size = action.source_size or 0
        f_key = action.metadata.get("folder_key", "")
        f_display = str(src_path.parent) if src_path else ""
        f_name = src_path.name if src_path else "?"
        progress.start_file(f_key or (src_path.parent.name if src_path else ""), f_display, f_name, file_size)
        log_event(
            "SKIP",
            f"[no collision – stays at staging]\n"
            f"→ {src_path}  ({format_bytes(file_size)})",
        )
        progress.increment_processed()
        progress.record_skip(file_size)
        progress.set_message(f"No collision: {f_name} stays at staging")
        action.metadata["delete_source"] = "false"
        return action

    # Stay-at-staging collision resolution: delete the inferior copy (no file transfer).
    if action.action == ACTION_DELETE:
        if not action.source:
            return None
        del_path = Path(action.source)
        file_size = action.source_size or 0
        f_key = action.metadata.get("folder_key", "")
        progress.start_file(f_key or del_path.parent.name, str(del_path.parent), del_path.name, file_size)
        winner_path_str = action.metadata.get("winner_path", "unknown")
        winner_p = Path(winner_path_str) if winner_path_str != "unknown" else del_path
        winner_size = action.destination_size or 0
        resolution = action.metadata.get("resolution", "")
        verdict = "staging wins" if resolution == "delete_original" else "orig-dest wins"
        collision_msg = _format_collision_log(
            winner=winner_p,
            winner_size=winner_size,
            loser=del_path,
            loser_size=file_size,
            verdict=verdict,
            dry_run=dry_run,
        )
        if dry_run:
            log_event("DRYRUN", collision_msg)
            progress.increment_processed()
            progress.increment_collisions(replaced=resolution == "delete_original")
            progress.set_message(f"[dry-run] would delete {del_path.name}")
            progress.complete_simulated_file(file_size)
            action.metadata["delete_source"] = "true"
            return action
        try:
            if del_path.exists():
                del_path.unlink()
            log_event("DELETE", collision_msg)
        except Exception as exc:
            log_event("ERROR", f"delete failed: {del_path}\nerror: {exc}", level=logging.ERROR)
            return None
        progress.increment_processed()
        progress.increment_collisions(replaced=resolution == "delete_original")
        progress.set_message(f"Deleted inferior copy: {del_path.name}")
        progress.finish_file(file_size)
        action.metadata["delete_source"] = "true"
        return action

    if not action.source or not action.destination:
        log_event("WARN", f"action: {action}", level=logging.WARNING)
        return None

    src_path = Path(action.source)
    dest_path = Path(action.destination)
    folder_key = action.metadata.get("folder_key")
    folder_display = str(src_path.parent)
    if not folder_key:
        folder_key = Path(folder_display).name
    file_size = action.source_size or 0
    progress.start_file(folder_key, folder_display, src_path.name, file_size)

    console_index = progress.next_console_index()
    console_block = format_action_for_console(
        console_index,
        action,
        dry_run=dry_run,
        source_root=source_root,
    )
    if not progress.ui_is_enabled():
        console_print(console_block)
        console_print()

    if confirm and not dry_run and action.action in {ACTION_COPY, ACTION_MOVE, ACTION_REPLACE}:
        proceed = prompt_confirmation(action)
        if not proceed:
            log_event("SKIP", f"[user declined]\n→ {_file_label(src_path)}")
            progress.increment_processed()
            progress.set_message("User declined operation")
            declined_metadata = dict(action.metadata)
            declined_metadata["user_declined"] = "true"
            progress.record_skip(file_size)
            declined_action = Action(
                action=ACTION_SKIP,
                source=str(src_path),
                destination=str(dest_path),
                reason="user declined operation",
                source_size=action.source_size,
                destination_size=action.destination_size,
                collision=action.collision,
                metadata=declined_metadata,
            )
            return declined_action

    if action.action == ACTION_SKIP:
        verdict = _skip_verdict(action)
        will_del = not no_delete
        del_note = " · src will be deleted" if will_del else ""
        log_event("SKIP", f"[{verdict}{del_note}]\n→ {_file_label(src_path)}")
        progress.increment_processed()
        progress.increment_collisions(replaced=False)
        progress.set_message(f"Skipped: {src_path.name}")
        progress.record_skip(file_size)
        removed = maybe_delete_source(src_path, dry_run=dry_run, no_delete=no_delete)
        if removed:
            progress.set_message(f"Skipped + removed src: {src_path.name}")
        if not no_delete:
            action.metadata["delete_source"] = "true" if dry_run or removed else "false"
        return action

    if dry_run:
        verb = "replace" if action.action == ACTION_REPLACE else ("move" if action.action == ACTION_MOVE else "copy")
        if action.action == ACTION_REPLACE:
            log_event("DRYRUN", f"[{_replace_verdict(action, dry_run=True)}]\n→ {_file_label(src_path)}")
        else:
            verdict = _transfer_verdict(action, verb, dry_run=True)
            log_event("DRYRUN", f"[{verdict}]\n→ {_file_label(src_path)}")
        progress.increment_processed()
        if action.collision:
            progress.increment_collisions(replaced=action.action == ACTION_REPLACE)
        else:
            progress.increment_copied()
        progress.set_message(f"[dry-run] would {verb} {src_path.name}")
        progress.complete_simulated_file(file_size)
        maybe_delete_source(src_path, dry_run=True, no_delete=no_delete)
        if not no_delete:
            action.metadata["delete_source"] = "true"
        return action

    if action.action == ACTION_REPLACE:
        if dest_path.exists():
            dest_path.unlink()

    try:
        copy_with_progress(src_path, dest_path, progress)
    except Exception as exc:
        log_event(
            "ERROR",
            f"copy failed: {_file_label(src_path)}\nerror: {exc}",
            level=logging.ERROR,
        )
        return None

    if action.action == ACTION_REPLACE:
        log_event("REPLACE", f"[{_replace_verdict(action, dry_run=False)}]\n→ {_file_label(src_path)}")
    elif action.action == ACTION_MOVE:
        log_event("MOVE", f"[{_transfer_verdict(action, 'move')}]\n→ {_file_label(src_path)}")
    else:
        log_event("COPY", f"[{_transfer_verdict(action, 'copy')}]\n→ {_file_label(src_path)}")

    progress.increment_processed()
    if action.collision:
        progress.increment_collisions(replaced=True)
        progress.set_message(f"Replaced dest with {src_path.name}")
    else:
        progress.increment_copied()
        verb = "Moved" if action.action == ACTION_MOVE else "Copied"
        progress.set_message(f"{verb} {src_path.name}")

    progress.finish_file(file_size)
    removed = maybe_delete_source(src_path, dry_run=dry_run, no_delete=no_delete)
    if not no_delete:
        action.metadata["delete_source"] = "true" if dry_run or removed else "false"

    return action


def execute_plan(
    plan: Plan,
    dry_run: bool,
    progress: ProgressState,
    *,
    confirm: bool = False,
    no_delete: bool = False,
    max_files: Optional[int] = None,
) -> List[Action]:
    processed: List[Action] = []
    processed_count = 0
    limit_reached = False

    for action in plan.actions:
        if action.action != ACTION_CREATE_DIR and max_files is not None and processed_count >= max_files:
            limit_reached = True
            break

        result = execute_action(
            action,
            dry_run=dry_run,
            progress=progress,
            source_root=Path(plan.source),
            confirm=confirm,
            no_delete=no_delete,
        )
        if result:
            processed.append(result)
            processed_count += 1

    if limit_reached:
        message = f"Reached max-files limit ({max_files}); remaining actions skipped."
        log_event("INFO", message)
        progress.set_message(message)

    return processed


def wait_for_file_stability(path: Path, attempts: int = 3, interval: float = 1.0) -> bool:
    """Check whether a file's size has stabilised, suggesting the file is complete."""
    try:
        previous_size = path.stat().st_size
    except FileNotFoundError:
        return False

    for _ in range(attempts):
        time.sleep(interval)
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            return False
        if current_size != previous_size:
            previous_size = current_size
            continue
        return True
    return True


def monitor_for_new_files(
    source: Path,
    destination: Path,
    operation: str,
    dry_run: bool,
    known_files: Dict[str, int],
    progress: ProgressState,
    stop_event: threading.Event,
    summary_actions: List[Action],
    confirm: bool = False,
    no_delete: bool = False,
    poll_interval: float = 5.0,
) -> None:
    progress.set_scanning(True)
    progress.set_message("Monitoring for new MP4 files")
    log_event("SCAN", "Monitoring for new MP4 files")

    try:
        while not stop_event.is_set():
            for src_subdir in list_immediate_subdirs(source):
                dest_subdir = destination / src_subdir.name
                for src_file in iter_mp4_files(src_subdir):
                    key = str(src_file)
                    if key in known_files:
                        continue
                    if not wait_for_file_stability(src_file):
                        continue

                    action = determine_action(src_file, dest_subdir, operation)
                    if action.action != ACTION_SKIP and not dest_subdir.exists() and not dry_run:
                        dest_subdir.mkdir(parents=True, exist_ok=True)

                    progress.increment_total()
                    result = execute_action(
                        action,
                        dry_run=dry_run,
                        progress=progress,
                        source_root=source,
                        confirm=confirm,
                        no_delete=no_delete,
                    )
                    try:
                        known_files[key] = src_file.stat().st_size
                    except FileNotFoundError:
                        continue
                    progress.add_scan_new_file()
                    if result:
                        summary_actions.append(result)

            stop_event.wait(poll_interval)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        progress.set_scanning(False)
        progress.set_message("Scan mode stopped")
        log_event("SCAN", "Scan mode stopped")


def analyse_plan(plan: Plan, *, delete_source: bool) -> None:
    dir_actions = [action for action in plan.actions if action.action == ACTION_CREATE_DIR]
    file_actions = [action for action in plan.actions if action.action != ACTION_CREATE_DIR]

    if not dir_actions and not file_actions:
        console_print(green("No MP4 files require action."))
        return

    console_print(bright("Planned MP4 operations:"))

    source_root = Path(plan.source)

    for index, action in enumerate(file_actions, start=1):
        src = Path(action.source or "")
        try:
            display_path = src.relative_to(source_root)
        except Exception:
            display_path = src

        header = f"{index}. {bright(str(display_path))}"
        console_print(header)

        indent = "    "
        dest_display = action.destination or "-"
        src_size = format_bytes(action.source_size or 0)
        dest_size = format_bytes(action.destination_size or 0) if action.destination_size is not None else "n/a"

        if action.action == ACTION_SKIP:
            op_line = yellow("Action: skip (destination kept)")
            collision_line = yellow(f"Collision: destination >= source ({src_size} vs {dest_size})")
        elif action.action == ACTION_REPLACE:
            requested = action.metadata.get("requested_operation", action.action).upper()
            op_line = magenta(f"Action: replace via {requested}")
            collision_line = magenta(f"Collision: source larger ({src_size} vs {dest_size})")
        elif action.action == ACTION_MOVE:
            op_line = cyan("Action: move")
            collision_line = ""
        else:
            op_line = green("Action: copy")
            collision_line = ""

        console_print(f"{indent}{op_line}")
        console_print(f"{indent}Destination: {dest_display}")
        console_print(f"{indent}Source size: {src_size}")
        if action.destination_size is not None:
            console_print(f"{indent}Destination size: {dest_size}")
        if collision_line:
            console_print(f"{indent}{collision_line}")
        console_print(f"{indent}Reason: {action.reason}")
        if action.metadata:
            for key, value in action.metadata.items():
                console_print(f"{indent}{cyan(f'Metadata {key}: {value}')}")
        console_print()

    if dir_actions:
        console_print(bright("Destination directories to ensure:"))
        for dir_action in dir_actions:
            console_print(f"    {cyan(dir_action.destination or '-')}: {dir_action.reason}")
        console_print()

    summary = compute_summary(file_actions, delete_source=delete_source)
    print_summary_table(summary, dry_run=True)


def format_action_for_console(
    index: int,
    action: Action,
    *,
    dry_run: bool,
    source_root: Optional[Path] = None,
) -> str:
    """Return a colourised, multi-line description of an action for console display."""
    src_path = Path(action.source or "")
    if source_root:
        try:
            display_path = src_path.relative_to(source_root)
        except Exception:
            display_path = src_path
    else:
        display_path = src_path

    dest_display = action.destination or "-"
    src_size = format_bytes(action.source_size or 0)
    dest_size = format_bytes(action.destination_size or 0) if action.destination_size is not None else "n/a"

    if action.action == ACTION_SKIP:
        colour_fn = yellow
        op_desc = "Skip (destination kept)"
    elif action.action == ACTION_REPLACE:
        colour_fn = magenta
        requested = action.metadata.get("requested_operation", action.action).upper()
        op_desc = f"Replace via {requested}"
    elif action.action == ACTION_MOVE:
        colour_fn = cyan
        op_desc = "Move"
    else:
        colour_fn = green
        op_desc = "Copy"

    header_components = [f"{index}. {display_path}"]
    if dry_run:
        header_components.append("[DRY-RUN]")
    header = colour_fn(" ".join(header_components))

    lines = [header]
    indent = "    "
    lines.append(f"{indent}{colour_fn(f'Action: {op_desc}')}")
    lines.append(f"{indent}Destination: {dest_display}")
    lines.append(f"{indent}Source size: {src_size}")
    if action.destination_size is not None:
        lines.append(f"{indent}Destination size: {dest_size}")
    if action.collision:
        if action.action == ACTION_REPLACE:
            collision_text = f"Collision: source larger ({src_size} vs {dest_size})"
        else:
            collision_text = f"Collision: destination larger or equal ({src_size} vs {dest_size})"
        lines.append(f"{indent}{colour_fn(collision_text)}")
    lines.append(f"{indent}Reason: {action.reason}")
    if action.metadata:
        ignored_keys = {
            "source_path",
            "destination_path",
            "folder_key",
            "folder_total_files",
            "folder_total_bytes",
            "delete_source",
        }
        for key, value in action.metadata.items():
            if key in ignored_keys:
                continue
            lines.append(f"{indent}{cyan(f'Metadata {key}: {value}')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Argument parsing and entry point


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronise MP4 files between matching subdirectories.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("source", type=Path, help="Source root directory")
    parser.add_argument("destination", type=Path, help="Destination root directory")
    parser.add_argument(
        "-o",
        "--operation",
        choices=sorted(VALID_OPERATIONS),
        default=ACTION_COPY,
        help="Whether to copy or move files during execution",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Simulate actions without making changes",
    )
    parser.add_argument(
        "-a",
        "--analyze",
        action="store_true",
        help="Analyse mode: only report actions",
    )
    parser.add_argument(
        "-p",
        "--plan-output",
        type=Path,
        default=Path("mp4_sync_plan.json"),
        help="Path to write the generated plan JSON when analysing",
    )
    parser.add_argument(
        "-A",
        "--apply-plan",
        type=Path,
        help="Execute actions from an existing plan JSON without re-scanning the folders",
    )
    parser.add_argument(
        "-w",
        "--scan",
        action="store_true",
        help="Enable continuous scan mode to watch for new MP4 files after initial run",
    )
    parser.add_argument(
        "-l",
        "--log-file",
        type=Path,
        default=Path("mp4scan-log.log"),
        help="Location of the detailed log file",
    )
    parser.add_argument(
        "-u",
        "--no-ui",
        action="store_true",
        help="Disable the live in-place console UI (helpful when redirecting output)",
    )
    parser.add_argument(
        "-W",
        "--scan-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds for scan mode",
    )
    parser.add_argument(
        "-y",
        "--confirm",
        action="store_true",
        help="Require confirmation before each copy/move/replace during execution",
    )
    parser.add_argument(
        "-m",
        "--max-files",
        type=int,
        help="Maximum number of files to process this run before stopping",
    )
    parser.add_argument(
        "-N",
        "--no-delete",
        action="store_true",
        help="Retain source MP4 files after processing (skip source cleanup)",
    )
    return parser.parse_args(argv)


def configure_logging(log_file: Path) -> None:
    global LOG_START_TIME
    LOG_START_TIME = time.perf_counter()

    if not log_file.is_absolute():
        log_file = Path.cwd() / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    LOGGER.handlers.clear()
    LOGGER.propagate = False
    LOGGER.setLevel(logging.INFO)

    formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)
    LOGGER.addHandler(console_handler)

    log_event("INFO", f"Logging initialised. Writing to {log_file}")


def validate_paths(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source directory '{source}' does not exist or is not a directory.")
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise NotADirectoryError(f"Destination path '{destination}' is not a directory.")


def collect_known_files(source: Path) -> Dict[str, int]:
    """Return current mp4 file sizes to seed scan mode."""
    known: Dict[str, int] = {}
    for subdir in list_immediate_subdirs(source):
        for mp4_file in iter_mp4_files(subdir):
            try:
                known[str(mp4_file)] = mp4_file.stat().st_size
            except FileNotFoundError:
                continue
    return known


def main(argv: Optional[Sequence[str]] = None) -> int:
    enable_vt_mode()
    args = parse_args(argv)
    configure_logging(args.log_file)

    try:
        validate_paths(args.source, args.destination)
    except Exception as exc:
        log_event("ERROR", str(exc), level=logging.ERROR)
        return 2

    if args.max_files is not None and args.max_files <= 0:
        log_event("ERROR", "--max-files must be a positive integer", level=logging.ERROR)
        return 2

    progress = ProgressState()
    set_progress_tracker(progress)
    ui_enabled = not args.no_ui and not args.dry_run and not args.analyze and not args.confirm
    progress.set_ui_enabled(ui_enabled)
    ui = ProgressUI(progress, enabled=ui_enabled)
    ui.start()

    overall_start = time.perf_counter()
    stop_event = threading.Event()
    processed_actions: List[Action] = []

    try:
        if args.apply_plan:
            plan = load_plan(args.apply_plan)
            progress.set_message(f"Loaded plan with {len(plan.actions)} actions")
            folder_totals = derive_folder_metadata(plan, args.source)
        else:
            plan, folder_totals = build_plan(args.source, args.destination, args.operation, progress=progress)

        file_action_count = sum(1 for action in plan.actions if action.action != ACTION_CREATE_DIR)
        effective_max_files = None if args.scan else args.max_files
        effective_total = min(file_action_count, effective_max_files) if effective_max_files else file_action_count
        progress.set_total_files(effective_total)
        actionable = [action for action in plan.actions if action.action != ACTION_CREATE_DIR]
        if effective_max_files:
            actionable = actionable[:effective_max_files]
        total_bytes = sum(action.source_size or 0 for action in actionable)
        progress.set_total_bytes(total_bytes)
        if effective_max_files:
            limited_totals: Dict[str, Dict[str, int]] = {}
            for action in actionable:
                if not action.source:
                    continue
                folder_key = action.metadata.get("folder_key") or Path(action.source).parent.name
                entry = limited_totals.setdefault(folder_key, {"files": 0, "bytes": 0})
                entry["files"] += 1
                entry["bytes"] += action.source_size or 0
            progress.set_folder_totals(limited_totals or folder_totals)
        else:
            progress.set_folder_totals(folder_totals)

        if args.analyze and not args.apply_plan:
            analyse_plan(plan, delete_source=not args.no_delete)
            write_plan(plan, args.plan_output)
            log_event("INFO", f"Analysis written to {args.plan_output}")
            return_code = 0
        else:
            processed_actions = execute_plan(
                plan,
                dry_run=args.dry_run,
                progress=progress,
                confirm=args.confirm,
                no_delete=args.no_delete,
                max_files=effective_max_files,
            )
            return_code = 0

        if args.scan:
            known_files = collect_known_files(args.source)
            monitor_for_new_files(
                source=args.source,
                destination=args.destination,
                operation=plan.operation,
                dry_run=args.dry_run or args.analyze,
                known_files=known_files,
                progress=progress,
                stop_event=stop_event,
                summary_actions=processed_actions,
                confirm=args.confirm,
                no_delete=args.no_delete,
                poll_interval=args.scan_interval,
            )
    except KeyboardInterrupt:
        log_event("WARN", "Interrupted by user.")
        stop_event.set()
        return_code = 130
    finally:
        progress.set_running(False)
        ui.stop()
        elapsed = time.perf_counter() - overall_start
        log_event("INFO", f"Completed in {format_duration(elapsed)}")
        set_progress_tracker(None)

    if not (args.analyze and not args.apply_plan):
        summary = compute_summary(processed_actions, delete_source=not args.no_delete)
        print_summary_table(summary, dry_run=args.dry_run)

    return return_code


if __name__ == "__main__":
    sys.exit(main())
