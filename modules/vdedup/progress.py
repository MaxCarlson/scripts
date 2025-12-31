#!/usr/bin/env python3
"""
vdedup.progress

Rich-powered status dashboard that surfaces pipeline health in real time.
"""

from __future__ import annotations

import os
import select
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _format_bytes(amount: int) -> str:
    """Return human-readable representation for byte counts."""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(amount)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            precision = 2 if unit in {"GiB", "TiB"} else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PiB"


def _format_eta(seconds: Optional[float]) -> str:
    """Pretty-print an ETA in h/m/s."""
    if seconds is None or seconds == float("inf"):
        return "--"
    secs = max(0, int(seconds))
    minutes, sec = divmod(secs, 60)
    hours, minute = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minute:02d}m"
    if minute > 0:
        return f"{minute}m {sec:02d}s"
    return f"{sec}s"


def _stage_key(name: str) -> str:
    """Stable key for stage lookups."""
    return name.strip().lower().replace(" ", "_")


class _KeyReader:
    """Cross-platform, non-blocking key reader."""

    def __init__(self) -> None:
        if not sys.stdin.isatty():
            raise RuntimeError("stdin is not attached to a TTY")
        self._win = os.name == "nt"
        self._closed = False
        if self._win:
            import msvcrt  # type: ignore # noqa: F401
        else:
            import termios  # type: ignore
            import tty  # type: ignore

            self._termios = termios  # type: ignore[attr-defined]
            self._tty = tty  # type: ignore[attr-defined]
            self._fd = sys.stdin.fileno()
            self._old_settings = self._termios.tcgetattr(self._fd)
            self._tty.setcbreak(self._fd)

    def close(self) -> None:
        if self._win or self._closed:
            return
        self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old_settings)
        self._closed = True

    def read_key(self, timeout: float = 0.1) -> Optional[str]:
        if self._win:
            import msvcrt  # type: ignore

            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():  # type: ignore[attr-defined]
                    ch = msvcrt.getwch()  # type: ignore[attr-defined]
                    if ch in ("\x00", "\xe0"):
                        if msvcrt.kbhit():  # type: ignore[attr-defined]
                            code = msvcrt.getwch()  # type: ignore[attr-defined]
                        else:
                            code = msvcrt.getwch()  # type: ignore[attr-defined]
                        if code.upper() == "I":
                            return "PAGE_UP"
                        if code.upper() == "Q":
                            return "PAGE_DOWN"
                        continue
                    return ch
                time.sleep(0.01)
            return None
        else:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if ready:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = ch
                    while True:
                        ready_more, _, _ = select.select([sys.stdin], [], [], 0.01)
                        if not ready_more:
                            break
                        seq += sys.stdin.read(1)
                        if seq.endswith("~") or len(seq) >= 5:
                            break
                    if seq in ("\x1b[5~", "\x1b[5^"):
                        return "PAGE_UP"
                    if seq in ("\x1b[6~", "\x1b[6^"):
                        return "PAGE_DOWN"
                    return ch
                return ch
            return None


class ProgressReporter:
    """Thread-safe progress reporter with multi-panel dashboard output."""

    def __init__(
        self,
        enable_dash: bool,
        *,
        refresh_rate: float = 1.0,
        banner: str = "",
        stacked_ui: Optional[bool] = None,  # preserved for backwards compatibility
    ):
        self.enable_dash = bool(enable_dash)
        # Clamp refresh rate between 0.1s (10 Hz) and 1.0s (1 Hz) for responsive UI
        self.refresh_rate = max(0.1, min(1.0, float(refresh_rate)))
        self.banner = banner
        self._stacked_ui = stacked_ui

        # Locks & timing
        self.lock = threading.Lock()
        self.start_ts = time.time()
        self.stage_start_ts = self.start_ts

        # UI state
        self._ui_initialized = False
        self._live: Optional[Live] = None
        self.console = Console(highlight=False, soft_wrap=False)
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_interval = 0.25
        self._stage_activity_ts = self.start_ts
        self._stage_stall_logged: Optional[str] = None
        self._stage_stall_threshold = 90.0  # seconds

        # Counters
        self.total_files = 0
        self.total_bytes = 0
        self.scanned_files = 0
        self.video_files = 0
        self.video_bytes_total = 0
        self.video_bytes_processed = 0
        self.bytes_seen = 0

        # Discovery tracking
        self.status_line = "Initializing"
        self.discovery_files = 0
        self.discovery_skipped = 0
        self.discovery_artifacts = 0
        self.discovery_bytes = 0
        self.roots_total = 0
        self.roots_completed = 0
        self.current_root_display = ""

        # Hash/probe counters
        self.hash_total = 0
        self.hash_done = 0
        self.cache_hits = 0

        # Group counters
        self.groups_hash = 0
        self.groups_meta = 0
        self.groups_phash = 0
        self.groups_subset = 0
        self.groups_scene = 0
        self.groups_audio = 0
        self.groups_timeline = 0

        # Results summary
        self.dup_groups_total = 0
        self.losers_total = 0
        self.bytes_to_remove = 0
        self.duplicates_found = 0

        # Stage progress
        self.stage_name = "idle"
        self.stage_total = 0
        self.stage_done = 0
        self.stage_metrics: Dict[str, Dict[str, Any]] = {}
        self.stage_status: Dict[str, str] = {}
        self.stage_display: Dict[str, str] = {}
        self.stage_order: List[str] = []
        self.stage_plan_keys: List[str] = []
        self.stage_records: Dict[str, Dict[str, Any]] = {}
        self.stage_total_count = 0

        # Controls
        self._paused_evt = threading.Event()
        self._paused_evt.set()
        self._quit_evt = threading.Event()
        self._stop_evt = threading.Event()
        self._control_messages: Deque[str] = deque(maxlen=4)
        self._controls_enabled = False
        self._control_thread: Optional[threading.Thread] = None
        self._control_stop = threading.Event()
        self._key_reader: Optional[_KeyReader] = None
        self._stage_ceiling = 0

        # Last print time for throttling
        self._last_print = 0.0

        # In-memory log buffer
        self._log_messages: List[Tuple[str, str, float, str]] = []
        self._log_scroll = 0
        self._log_level = 2  # 1=errors, 2=warnings+info, 3=debug
        self._log_page_size = 6
        self._log_filters = {
            1: {"ERROR"},
            2: {"ERROR", "WARNING", "INFO"},
            3: {"ERROR", "WARNING", "INFO", "DEBUG"},
        }

        # Scoring / detector telemetry
        self.score_histogram: Dict[str, int] = {
            "0-0.25": 0,
            "0.25-0.5": 0,
            "0.5-0.75": 0,
            "0.75-1.0": 0,
        }
        self.detector_counts: Dict[str, int] = {}
        self.score_samples = 0
        self.score_sum = 0.0
        self.low_confidence = 0
        self.penalty_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------ public API

    def start(self) -> None:
        """Start dashboard rendering if enabled."""
        if self.enable_dash and not self._ui_initialized:
            # Use at least 4 refreshes per second for smooth, responsive UI
            # This ensures updates feel live and don't appear frozen
            refresh_per_second = max(4, int(round(1 / self.refresh_rate)))
            self._live = Live(
                self._render_layout(),
                console=self.console,
                refresh_per_second=refresh_per_second,
                transient=False,
            )
            self._live.start()
            self._ui_initialized = True
            self._start_control_listener()
            self._start_heartbeat()

    def set_status(self, text: str) -> None:
        """Update status line."""
        with self.lock:
            self.status_line = text
        self._print_if_due()

    def set_stage_plan(self, names: Sequence[str]) -> None:
        """Define the order of stages for Stage X/Y tracking."""
        with self.lock:
            self.stage_plan_keys = []
            self.stage_order = []
            self.stage_records = {}
            self.stage_status = {}
            self.stage_display = {}
            for name in names:
                self._add_stage_entry_unlocked(name)
            self.stage_total_count = len(self.stage_plan_keys)

    def set_stage_ceiling(self, stage: int) -> None:
        """Record the highest quality level selected at startup."""
        with self.lock:
            self._stage_ceiling = max(self._stage_ceiling, int(stage))

    def consume_stage_extensions(self, current_max: int) -> List[int]:
        """Return any newly requested quality levels beyond current_max."""
        with self.lock:
            target = self._stage_ceiling
        additions: List[int] = []
        next_stage = max(0, int(current_max))
        while next_stage < target:
            next_stage += 1
            additions.append(next_stage)
        return additions

    def append_stage_entries(self, displays: Sequence[str]) -> None:
        """Append new stage entries to the timeline."""
        if not displays:
            return
        with self.lock:
            for display in displays:
                self._add_stage_entry_unlocked(display)

    def request_stage_extension(self) -> bool:
        """Increase the requested quality depth by one level."""
        with self.lock:
            if self._stage_ceiling >= 7:
                target = None
            else:
                self._stage_ceiling += 1
                target = self._stage_ceiling
        if target is None:
            self._record_control_event("Already at maximum quality (Q7)")
            return False
        self._record_control_event(f"Extending scan to Q{target}")
        self.add_log(f"Runtime stage extension requested: Q{target}", "INFO", source="controls")
        return True

    def update_root_progress(self, *, current: Optional[Path], completed: int, total: int) -> None:
        """Track directory traversal progress."""
        with self.lock:
            self.roots_total = max(0, int(total))
            self.roots_completed = max(0, min(int(completed), self.roots_total))
            self.current_root_display = str(current) if current else ""
            key = _stage_key("discovering files")
            bucket = self.stage_metrics.setdefault(key, {})
            bucket.update(
                {
                    "roots_done": f"{self.roots_completed}/{self.roots_total}",
                    "current_root": self.current_root_display or "--",
                }
            )
        self._print_if_due()

    def update_discovery(
        self,
        discovered: int,
        *,
        skipped: int = 0,
        artifacts: int = 0,
        bytes_total: Optional[int] = None,
    ) -> None:
        """Update file discovery counters."""
        with self.lock:
            self.discovery_files = max(0, int(discovered))
            self.discovery_skipped = max(0, int(skipped))
            self.discovery_artifacts = max(0, int(artifacts))
            if bytes_total is not None:
                self.discovery_bytes = max(0, int(bytes_total))
            key = _stage_key("discovering files")
            bucket = self.stage_metrics.setdefault(key, {})
            bucket.update(
                {
                    "files_found": f"{self.discovery_files:,}",
                    "skipped": f"{self.discovery_skipped:,}",
                    "artifacts": f"{self.discovery_artifacts:,}",
                    "data_found": _format_bytes(self.discovery_bytes),
                }
            )
        self._print_if_due()

    def start_stage(self, name: str, total: int) -> None:
        """Begin a new stage and reset stage-local counters."""
        now = time.time()
        with self.lock:
            prev_key = _stage_key(self.stage_name)
            prev_entry = self.stage_records.get(prev_key)
            if prev_entry and prev_entry.get("status") == "running":
                self._finalize_stage_entry(prev_key, status="done", now=now)

            entry = self._ensure_stage_entry(name)
            entry["status"] = "running"
            entry["start"] = now
            entry["end"] = None
            entry["duration"] = None

            self.stage_status[_stage_key(name)] = "running"
            self.stage_name = name
            self.stage_total = max(0, int(total))
            self.stage_done = 0
            self.stage_start_ts = now
            self.status_line = name
            self._note_stage_activity_locked()
        self._print_now()

    def finish_stage(self, name: Optional[str] = None, *, status: str = "done") -> None:
        """Mark a stage as completed."""
        with self.lock:
            stage = name or self.stage_name
            key = _stage_key(stage)
            self._finalize_stage_entry(key, status=status)
        self._print_if_due()

    def mark_stage_skipped(self, name: str) -> None:
        """Explicitly mark a stage as skipped (no-op for stages not in plan)."""
        with self.lock:
            key = _stage_key(name)
            entry = self._ensure_stage_entry(name)
            if entry.get("start") is None:
                entry["start"] = time.time()
            self._finalize_stage_entry(key, status="skipped")
        self._print_if_due()

    def set_total_files(self, n: int) -> None:
        """Set total file count."""
        with self.lock:
            self.total_files = int(n)
        self._print_now()

    def set_total_bytes(self, total: int) -> None:
        """Record total payload size for ETA calculations."""
        with self.lock:
            self.total_bytes = max(0, int(total))
        self._print_if_due()

    def mark_video_bytes_total(self, total: int) -> None:
        """Record total bytes attributed to video files."""
        with self.lock:
            self.video_bytes_total = max(0, int(total))
        self._print_if_due()

    def inc_scanned(self, n: int = 1, *, bytes_added: int = 0, is_video: bool = False) -> None:
        """Increment metadata scanning counters."""
        with self.lock:
            inc = int(n)
            self.scanned_files += inc
            self.bytes_seen += int(bytes_added)
            if is_video:
                self.video_files += inc
                self.video_bytes_processed += int(bytes_added)
            before = self.stage_done
            self.stage_done += inc
            if self.stage_done != before:
                self._note_stage_activity_locked()
        self._print_if_due()

    def set_hash_total(self, n: int) -> None:
        """Set number of items that require hashing/probing."""
        with self.lock:
            self.hash_total = int(n)
            self.hash_done = 0

    def inc_hashed(self, n: int = 1, cache_hit: bool = False) -> None:
        """Increment hashing/probe counters."""
        with self.lock:
            inc = int(n)
            self.hash_done += inc
            if cache_hit:
                self.cache_hits += inc
            before = self.stage_done
            self.stage_done += inc
            if self.stage_done != before:
                self._note_stage_activity_locked()
        self._print_if_due()

    def inc_group(self, mode: str, n: int = 1) -> None:
        """Increment deduplication group counters by stage."""
        with self.lock:
            value = int(n)
            if mode == "hash":
                self.groups_hash += value
            elif mode == "meta":
                self.groups_meta += value
            elif mode == "phash":
                self.groups_phash += value
            elif mode == "subset":
                self.groups_subset += value
            elif mode == "scene":
                self.groups_scene += value
            elif mode == "audio":
                self.groups_audio += value
            elif mode == "timeline":
                self.groups_timeline += value
        self._print_if_due()

    def add_duplicate_files(self, dup_count: int) -> None:
        """Add to the running duplicate counter."""
        if dup_count <= 0:
            return
        with self.lock:
            self.duplicates_found += int(dup_count)
        self._print_if_due()

    def set_results(self, dup_groups: int, losers_count: int, bytes_total: int) -> None:
        """Record final results."""
        with self.lock:
            self.dup_groups_total = int(dup_groups)
            self.losers_total = int(losers_count)
            self.bytes_to_remove = int(bytes_total)
        self._print_if_due()

    def update_stage_metrics(self, stage_name: str, **metrics: Any) -> None:
        """Attach additional metrics to the named stage."""
        key = _stage_key(stage_name)
        with self.lock:
            bucket = self.stage_metrics.setdefault(key, {})
            bucket.update(metrics)
        self._print_if_due()

    def update_progress_periodically(self, current_step: int, total_steps: int, force_update: bool = False) -> None:
        """Update progress counters and refresh UI if needed."""
        with self.lock:
            previous = self.stage_done
            self.stage_done = max(0, int(current_step))
            if total_steps > 0:
                self.stage_total = max(self.stage_total, int(total_steps))
            if self.stage_done != previous:
                self._note_stage_activity_locked()
        if force_update:
            self._print_now()
        else:
            self._print_if_due()

    def flush(self) -> None:
        """Force an immediate refresh."""
        self._print_now()

    def wait_if_paused(self) -> None:
        """Block worker threads when paused."""
        self._paused_evt.wait()

    def should_quit(self) -> bool:
        """Return True if shutdown requested."""
        return self._quit_evt.is_set()

    def stop(self) -> None:
        """Stop rendering and print final summary."""
        self._stop_evt.set()
        self._control_stop.set()
        self._stop_heartbeat()
        if self._key_reader:
            try:
                self._key_reader.close()
            except Exception:
                pass
            self._key_reader = None
        if self._control_thread:
            self._control_thread.join(timeout=0.5)
            self._control_thread = None
        self._controls_enabled = False
        if self.enable_dash and self._live:
            self._live.stop()
            self._live = None
            final = Panel(
                Align.center(Text("Pipeline Complete", style="bold green")),
                border_style="green",
            )
            self.console.print(final)

    def add_log(self, message: str, level: str = "INFO", *, source: str = "pipeline") -> None:
        """Record a diagnostic log entry for the UI."""
        entry = (level.upper(), str(message), time.time(), source.upper())
        with self.lock:
            self._log_messages.append(entry)
            if len(self._log_messages) > 200:
                self._log_messages.pop(0)
                self._log_scroll = max(0, self._log_scroll - 1)
        self._print_if_due()

    def add_score_sample(
        self,
        score: float,
        *,
        detector: Optional[str] = None,
        penalties: Optional[Sequence[str]] = None,
    ) -> None:
        """Record a scoring event for histogram + detector summaries."""
        try:
            s = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            return
        with self.lock:
            self.score_samples += 1
            self.score_sum += s
            bucket = self._score_bucket(s)
            self.score_histogram[bucket] = self.score_histogram.get(bucket, 0) + 1
            if detector:
                self.detector_counts[detector] = self.detector_counts.get(detector, 0) + 1
            if s < 0.5:
                self.low_confidence += 1
            if penalties:
                for key in penalties:
                    if not key:
                        continue
                    self.penalty_counts[key] = self.penalty_counts.get(key, 0) + 1
        self._print_if_due()

    def recent_logs(self) -> List[Tuple[str, str, float, str]]:
        """Return recent log entries."""
        with self.lock:
            return list(self._log_messages[-5:])

    def _record_control_event(self, message: str) -> None:
        with self.lock:
            self._control_messages.append(message)
            if len(self._control_messages) > 5:
                self._control_messages.popleft()

    def _note_stage_activity_locked(self) -> None:
        self._stage_activity_ts = time.time()
        self._stage_stall_logged = None

    def _add_stage_entry_unlocked(self, display: str) -> None:
        key = _stage_key(display)
        if key in self.stage_records:
            return
        entry = {
            "display": display,
            "status": "pending",
            "index": len(self.stage_plan_keys),
            "start": None,
            "end": None,
            "duration": None,
        }
        self.stage_plan_keys.append(key)
        self.stage_order.append(display)
        self.stage_display[key] = display
        self.stage_status[key] = "pending"
        self.stage_records[key] = entry
        self.stage_total_count = len(self.stage_plan_keys)

    def _ensure_stage_entry(self, display: str) -> Dict[str, Any]:
        """Guarantee that a stage entry exists for the given display name."""
        key = _stage_key(display)
        entry = self.stage_records.get(key)
        if entry is None:
            idx = len(self.stage_plan_keys)
            self.stage_plan_keys.append(key)
            self.stage_order.append(display)
            entry = {
                "display": display,
                "status": "pending",
                "index": idx,
                "start": None,
                "end": None,
                "duration": None,
            }
            self.stage_records[key] = entry
            self.stage_status[key] = "pending"
            self.stage_display[key] = display
            self.stage_total_count = len(self.stage_plan_keys)
        return entry

    def _finalize_stage_entry(self, key: str, *, status: str, now: Optional[float] = None) -> None:
        """Update bookkeeping when a stage finishes/skips."""
        entry = self.stage_records.get(key)
        if entry is None:
            return
        ts = now or time.time()
        if entry.get("start") is None:
            entry["start"] = ts
        entry["end"] = ts
        if status == "done":
            entry["duration"] = max(0.0, ts - (entry.get("start") or ts))
        elif entry.get("duration") is None:
            entry["duration"] = 0.0
        entry["status"] = status
        self.stage_status[key] = status

    # ------------------------------------------------------------------ rendering

    def _print_if_due(self) -> None:
        """Refresh UI if enough time has elapsed."""
        if not self.enable_dash or not self._ui_initialized:
            return
        now = time.time()
        if (now - self._last_print) >= self.refresh_rate:
            self._print_now()

    def _print_now(self) -> None:
        """Immediate UI refresh."""
        if not self.enable_dash or not self._ui_initialized or not self._live:
            return
        self._last_print = time.time()
        self._live.update(self._render_layout(), refresh=True)

    def _start_control_listener(self) -> None:
        """Begin listening for runtime hotkeys if possible."""
        if self._control_thread or not self.enable_dash:
            return
        try:
            self._key_reader = _KeyReader()
        except Exception:
            self._controls_enabled = False
            self._record_control_event("Controls unavailable (no interactive terminal)")
            return
        self._controls_enabled = True
        self._control_stop = threading.Event()
        self._control_thread = threading.Thread(target=self._control_loop, daemon=True)
        self._control_thread.start()
        self._record_control_event("Controls: P=Pause, +=Extend, S=Stop, Q=Abort, 1/2/3=Log filter, PgUp/PgDn=Scroll")

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread or not self.enable_dash:
            return
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        if not self._heartbeat_thread:
            return
        self._heartbeat_stop.set()
        self._heartbeat_thread.join(timeout=0.5)
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self._heartbeat_interval):
            if not self._ui_initialized:
                continue
            self._check_stage_stall()
            self._print_now()

    def _check_stage_stall(self) -> None:
        now = time.time()
        trigger_warning = False
        idle_seconds = 0.0
        stage_name = ""
        with self.lock:
            idle_seconds = now - self._stage_activity_ts
            stage_name = self.stage_name
            if idle_seconds >= self._stage_stall_threshold and self._stage_stall_logged != stage_name:
                self._stage_stall_logged = stage_name
                trigger_warning = True
            elif idle_seconds < self._stage_stall_threshold and self._stage_stall_logged:
                self._stage_stall_logged = None
        if trigger_warning:
            self.add_log(
                f"{stage_name} idle for {int(idle_seconds)}s without progress (workers may be blocked)",
                "WARNING",
                source="watchdog",
            )

    def _control_loop(self) -> None:
        """Background loop that processes hotkeys."""
        reader = self._key_reader
        if reader is None:
            return
        while not self._control_stop.is_set():
            try:
                key = reader.read_key(0.1)
            except Exception:
                break
            if not key:
                continue
            self._handle_control_key(key)

    def _handle_control_key(self, raw_key: str) -> None:
        """Map key presses to control actions."""
        if raw_key == "PAGE_UP":
            self._scroll_logs(1)
            return
        if raw_key == "PAGE_DOWN":
            self._scroll_logs(-1)
            return
        key = raw_key.lower()
        if key == "p":
            self._toggle_pause()
            return
        if key == "s":
            self._quit_evt.set()
            self._record_control_event("Stop requested (S)")
            self.add_log("Stop requested via dashboard controls", "WARNING", source="controls")
            return
        if key == "q":
            self._quit_evt.set()
            self._stop_evt.set()
            self._record_control_event("Abort requested (Q)")
            self.add_log("Abort requested via dashboard controls", "ERROR", source="controls")
            return
        if key == "+":
            self.request_stage_extension()
            return
        if key in {"1", "2", "3"}:
            self._set_log_level(int(key))
            return

    def _toggle_pause(self) -> None:
        """Pause or resume worker activity."""
        if self._paused_evt.is_set():
            self._paused_evt.clear()
            self._record_control_event("Paused (P)")
            self.add_log("Pipeline paused via dashboard controls", "WARNING", source="controls")
        else:
            self._paused_evt.set()
            self._record_control_event("Resumed (P)")
            self.add_log("Pipeline resumed via dashboard controls", "INFO", source="controls")
        self._print_if_due()

    def _render_layout(self) -> Layout:
        """Build the main dashboard layout."""
        with self.lock:
            elapsed = max(0.0, time.time() - self.start_ts)
            stage_elapsed = max(0.0, time.time() - self.stage_start_ts)
            pct = (self.stage_done / self.stage_total * 100.0) if self.stage_total > 0 else 0.0
            current_key = _stage_key(self.stage_name)
            current_metrics = dict(self.stage_metrics.get(current_key, {}))
            stage_entries: List[Dict[str, Any]] = []
            for key in self.stage_plan_keys:
                entry = self.stage_records.get(key)
                if entry:
                    stage_entries.append(entry.copy())
            current_entry = self.stage_records.get(current_key)
            stage_total_count = self.stage_total_count or len(stage_entries)
            completed = sum(1 for entry in stage_entries if entry.get("status") in {"done", "skipped"})
            if current_entry:
                stage_position = (current_entry.get("index") or 0) + 1
            else:
                stage_position = completed
            stage_position = max(0, min(stage_total_count or stage_position, stage_position))
            stage_eta = None
            if self.stage_total > 0 and self.stage_done > 0 and stage_elapsed > 0:
                rate = self.stage_done / stage_elapsed
                remaining = self.stage_total - self.stage_done
                if rate > 0 and remaining >= 0:
                    stage_eta = remaining / rate
            page_size = self._log_page_size
            allowed_levels = self._log_filters.get(self._log_level, {"ERROR", "WARNING", "INFO", "DEBUG"})
            filtered_logs = [entry for entry in self._log_messages if entry[0] in allowed_levels]
            max_scroll = max(0, len(filtered_logs) - page_size)
            if self._log_scroll > max_scroll:
                self._log_scroll = max_scroll
            start = max(0, len(filtered_logs) - page_size - self._log_scroll)
            end = max(0, len(filtered_logs) - self._log_scroll)
            logs = filtered_logs[start:end]
            score_hist_snapshot = dict(self.score_histogram)
            score_samples = self.score_samples
            score_sum = self.score_sum
            low_confidence = self.low_confidence
            detector_counts = dict(self.detector_counts)
            penalty_counts = dict(self.penalty_counts)

        layout = Layout()
        layout.split_column(
            Layout(
                self._render_header(elapsed, stage_elapsed, pct, stage_position, stage_total_count, stage_eta),
                size=7,
            ),
            Layout(name="body", ratio=1),
            Layout(
                self._render_command_deck(
                    logs,
                    throughput=(self.bytes_seen / elapsed) if elapsed > 0 else 0.0,
                    score_hist=score_hist_snapshot,
                    detector_counts=detector_counts,
                    penalty_counts=penalty_counts,
                ),
                size=10,
            ),
        )
        layout["body"].split_row(
            Layout(self._render_stage_panel(current_metrics, stage_entries, stage_elapsed), ratio=2),
            Layout(
                self._render_stats_panel(
                    elapsed,
                    stage_position,
                    stage_total_count,
                    stage_eta,
                    score_hist_snapshot,
                    score_samples,
                    score_sum,
                    low_confidence,
                    detector_counts,
                    penalty_counts,
                ),
                ratio=3,
            ),
        )
        return layout

    def _render_header(
        self,
        elapsed: float,
        stage_elapsed: float,
        pct: float,
        stage_position: int,
        stage_total_count: int,
        stage_eta: Optional[float],
    ) -> Panel:
        """Pipeline headline with progress bar."""
        table = Table.grid(expand=True)
        table.add_column(ratio=3)
        table.add_column(justify="right", ratio=2)

        stage_text = Text(self.stage_name.upper(), style="bold cyan")
        stage_counter = (
            Text(f"Stage {stage_position}/{stage_total_count}", style="bold white")
            if stage_total_count
            else Text("Stage --", style="bold white")
        )
        table.add_row(stage_text, stage_counter)

        timing_text = Text(f"Elapsed: {int(elapsed)}s  Stage: {int(stage_elapsed)}s", style="bold")
        eta_text = Text(f"ETA: {_format_eta(stage_eta)}", style="bold magenta")
        table.add_row(timing_text, eta_text)

        bar = self._progress_bar(pct)
        counts = Text(f"{self.stage_done:,}/{self.stage_total:,}" if self.stage_total else f"{self.stage_done:,}", style="bold")
        table.add_row(bar, counts)

        status = Text()
        if not self._paused_evt.is_set():
            status.append("PAUSED ", style="bold yellow")
        if self._quit_evt.is_set():
            status.append("STOPPING ", style="bold red")
        status.append(self.status_line, style="italic magenta")
        banner = Text(self.banner, style="dim") if self.banner else Text("")
        table.add_row(status, banner)

        return Panel(table, title="Video Deduplication Pipeline", border_style="cyan")

    def _render_stage_panel(self, metrics: Dict[str, Any], stage_entries: List[Dict[str, Any]], stage_elapsed: float) -> Panel:
        """Render per-stage timeline and metrics."""
        timeline = Table(box=None, expand=True, padding=(0, 1))
        timeline.add_column("#", justify="right", width=4)
        timeline.add_column("Stage", justify="left")
        timeline.add_column("Time", justify="right")

        if stage_entries:
            style_map = {
                "running": "bold yellow",
                "done": "green",
                "pending": "magenta",
                "skipped": "grey62",
            }
            for entry in stage_entries:
                idx = (entry.get("index") or 0) + 1
                status = entry.get("status", "pending")
                style = style_map.get(status, "grey62")
                duration = entry.get("duration")
                if status == "running":
                    time_text = f"{int(stage_elapsed)}s"
                elif duration is not None:
                    time_text = f"{duration:.1f}s"
                else:
                    time_text = "--"
                timeline.add_row(
                    Text(f"{idx}.", style=style),
                    Text(str(entry.get("display", "")).upper(), style=style),
                    Text(time_text, style=style),
                )
        else:
            timeline.add_row("", Text("No stages planned", style="dim"), "")

        metrics_table = Table.grid(expand=True)
        metrics_table.add_column(justify="left")
        metrics_table.add_column(justify="right")
        if metrics:
            for key, value in metrics.items():
                metrics_table.add_row(str(key).replace("_", " ").title(), Text(str(value), style="bold"))
        else:
            metrics_table.add_row("info", Text("Collecting metrics...", style="dim"))

        metrics_panel = Panel(metrics_table, title="Stage Metrics", border_style="magenta")
        body = Group(Align.left(timeline), metrics_panel)
        return Panel(body, title="Stage Timeline", border_style="magenta")

    def _render_stats_panel(
        self,
        elapsed: float,
        stage_position: int,
        stage_total_count: int,
        stage_eta: Optional[float],
        score_hist: Dict[str, int],
        score_samples: int,
        score_sum: float,
        low_confidence: int,
        detector_counts: Dict[str, int],
        penalty_counts: Dict[str, int],
    ) -> Panel:
        """Render global statistics."""
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_column(justify="right")

        bytes_remaining = max(0, self.total_bytes - self.bytes_seen)
        throughput = (self.bytes_seen / elapsed) if elapsed > 0 else 0.0
        dup_ratio = (self.duplicates_found / self.video_files) * 100 if self.video_files else 0.0
        stage_progress = f"{stage_position}/{stage_total_count}" if stage_total_count else "--"
        score_avg = (score_sum / score_samples) if score_samples else 0.0
        bucket_text = " ".join(f"{label}:{score_hist.get(label, 0)}" for label in score_hist.keys())
        detector_text = " ".join(
            f"{name}:{detector_counts[name]}"
            for name in sorted(detector_counts, key=lambda k: detector_counts[k], reverse=True)[:3]
        )
        penalty_text = " ".join(
            f"{name}:{penalty_counts[name]}"
            for name in sorted(penalty_counts, key=lambda k: penalty_counts[k], reverse=True)[:2]
        )

        summary = [
            ("Stage Progress", stage_progress),
            ("Stage ETA", _format_eta(stage_eta)),
            ("Total Files", f"{self.total_files:,}"),
            ("Scanned Files", f"{self.scanned_files:,}"),
            ("Video Files", f"{self.video_files:,}"),
            ("Duplicates Found", f"{self.duplicates_found:,} ({dup_ratio:.1f}%)"),
            ("Artifacts Skipped", f"{self.discovery_artifacts:,}"),
            ("Data Scanned", _format_bytes(self.bytes_seen)),
            ("Data Remaining", _format_bytes(bytes_remaining)),
            ("Throughput", f"{_format_bytes(int(throughput))}/s"),
            ("Cache Hit Rate", f"{(self.cache_hits / self.hash_done * 100):.1f}%"
             if self.hash_done else "0.0%"),
            ("Group Counts",
             f"H:{self.groups_hash} M:{self.groups_meta} P:{self.groups_phash} "
             f"S:{self.groups_subset} C:{self.groups_scene} A:{self.groups_audio} T:{self.groups_timeline}"),
            ("Score Avg", f"{score_avg:.2f} ({score_samples})"),
            ("Score Buckets", bucket_text or "--"),
            ("Low Confidence (<0.5)", f"{low_confidence}"),
            ("Detectors", detector_text or "--"),
            ("Penalties", penalty_text or "--"),
        ]

        for label, value in summary:
            table.add_row(label, Text(value, style="bold"))

        return Panel(table, title="Pipeline Stats", border_style="blue")

    def _render_command_deck(
        self,
        logs: List[Tuple[str, str, float, str]],
        *,
        throughput: float,
        score_hist: Dict[str, int],
        detector_counts: Dict[str, int],
        penalty_counts: Dict[str, int],
    ) -> Panel:
        """Render the hotkey ribbon plus log feed & telemetry cards."""
        table = Table.grid(expand=True)
        table.add_column(ratio=3)
        table.add_column(ratio=2)
        hotkeys = Text(
            "Hotkeys: P=Pause | +=Extend | S=Stop | Q=Abort | 1/2/3=Log level | PgUp/PgDn=scroll | Ctrl+C=exit UI",
            style="bold white",
        )
        filter_label = {1: "Errors", 2: "Stages+Warn", 3: "Full debug"}.get(self._log_level, "Custom")
        status_bits = [
            f"Paused={'YES' if not self._paused_evt.is_set() else 'NO'}",
            f"Target={'Q'+str(self._stage_ceiling) if self._stage_ceiling else '--'}",
            f"Log={filter_label}",
        ]
        if self._log_scroll:
            status_bits.append(f"Scroll={self._log_scroll}")
        table.add_row(hotkeys, Text(" | ".join(status_bits), style="cyan"))

        log_panel = Panel(self._render_log_lines(logs), title="Command Log", border_style="grey50")
        meta_panel = self._render_log_meta(throughput, score_hist, detector_counts, penalty_counts)
        table.add_row(log_panel, meta_panel)

        hint = self._control_messages[-1] if self._control_messages else "Use these hotkeys to steer the scan in real time."
        table.add_row(Text(hint, style="magenta"), Text("", style="dim"))
        return Panel(table, title="Command & Log Deck", border_style="grey39")

    def _render_log_lines(self, logs: List[Tuple[str, str, float, str]]) -> Table:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        if not logs:
            grid.add_row(Text("No log entries (press 3 for verbose).", style="dim"))
            return grid
        for level, message, ts, source in logs:
            style = {"ERROR": "bold red", "WARNING": "yellow", "INFO": "white", "DEBUG": "cyan"}.get(level, "white")
            stamp = self._format_log_timestamp(ts - self.start_ts)
            grid.add_row(Text(f"{stamp} {level:<7} {source:<10} \"{message}\"", style=style))
        return grid

    def _render_log_meta(
        self,
        throughput: float,
        score_hist: Dict[str, int],
        detector_counts: Dict[str, int],
        penalty_counts: Dict[str, int],
    ) -> Panel:
        runtime_lines = [
            f"Throughput : {_format_bytes(int(throughput))}/s",
            f"Cache hits : {self.cache_hits:,}",
            f"Low confidence : {self.low_confidence:,}",
            f"Dup groups : {self.dup_groups_total:,}",
        ]
        score_lines = [f"{bucket:>9}: {score_hist.get(bucket, 0):>4}" for bucket in score_hist.keys()]
        detector_lines = (
            [f"{name:<10}{count:>4}" for name, count in sorted(detector_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]]
            if detector_counts
            else ["--"]
        )
        penalty_lines = (
            [f"{name:<10}{count:>4}" for name, count in sorted(penalty_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]]
            if penalty_counts
            else ["--"]
        )
        runtime_panel = Panel(Text("\n".join(runtime_lines)), title="Runtime", border_style="blue")
        score_panel = Panel(Text("\n".join(score_lines)), title="Score Buckets", border_style="green")
        detector_panel = Panel(
            Text("Signals:\n" + "\n".join(detector_lines) + "\nPenalties:\n" + "\n".join(penalty_lines)),
            title="Signals / Penalties",
            border_style="magenta",
        )
        return Panel(Group(runtime_panel, score_panel, detector_panel), border_style="grey42")

    def _progress_bar(self, pct: float) -> Text:
        """Return a colorized progress bar string."""
        pct_clamped = max(0.0, min(100.0, pct))
        width = 42
        filled = int(round((pct_clamped / 100.0) * width))
        remaining = width - filled
        bar = Text(justify="left")
        if filled:
            bar.append("█" * filled, style="green")
        if remaining:
            bar.append("░" * remaining, style="grey30")
        bar.append(f" {pct_clamped:5.1f}%")
        return bar

    def _score_bucket(self, value: float) -> str:
        if value < 0.25:
            return "0-0.25"
        if value < 0.5:
            return "0.25-0.5"
        if value < 0.75:
            return "0.5-0.75"
        return "0.75-1.0"

    def _set_log_level(self, level: int) -> None:
        if level not in self._log_filters:
            return
        with self.lock:
            if self._log_level == level:
                return
            self._log_level = level
            self._log_scroll = 0
        label = {1: "errors only", 2: "stage + warnings", 3: "full detail"}.get(level, "custom")
        self._record_control_event(f"Log filter set to {label}")
        self._print_if_due()

    def _scroll_logs(self, direction: int) -> None:
        with self.lock:
            allowed = self._log_filters.get(self._log_level, {"ERROR", "WARNING", "INFO", "DEBUG"})
            filtered = [entry for entry in self._log_messages if entry[0] in allowed]
            max_scroll = max(0, len(filtered) - self._log_page_size)
            if max_scroll <= 0:
                self._log_scroll = 0
                return
            self._log_scroll = max(0, min(max_scroll, self._log_scroll + direction * self._log_page_size))
        self._print_if_due()

    def _format_log_timestamp(self, elapsed: float) -> str:
        if elapsed < 0:
            elapsed = 0.0
        total_seconds = int(elapsed)
        frames = int((elapsed - total_seconds) * 100)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"[{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}]"
