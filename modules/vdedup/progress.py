#!/usr/bin/env python3
"""
vdedup.progress - Simple progress reporter

Minimal, functional progress tracking without complex UI.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

_UI_LINE = "=" * 80  # ASCII-only horizontal rule for UI output


class ProgressReporter:
    """
    Minimal progress reporter with fixed in-place UI updates.
    """

    def __init__(
        self,
        enable_dash: bool,
        *,
        refresh_rate: float = 1.0,  # 1 second for smooth, non-spammy updates
        banner: str = "",
        stacked_ui: Optional[bool] = None,
    ):
        self.enable_dash = bool(enable_dash)
        self.refresh_rate = max(0.5, float(refresh_rate))
        self.banner = banner

        # Locks & timing
        self.lock = threading.Lock()
        self.start_ts = time.time()

        # UI state
        self._ui_lines_written = 0  # Track how many lines we've written
        self._ui_initialized = False

        # Counters
        self.total_files = 0
        self.scanned_files = 0
        self.video_files = 0
        self.bytes_seen = 0

        # Discovery tracking
        self.status_line = "Initializing"
        self.discovery_files = 0
        self.discovery_skipped = 0
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

        # Results summary
        self.dup_groups_total = 0
        self.losers_total = 0
        self.bytes_to_remove = 0

        # Stage/ETA
        self.stage_name = "idle"
        self.stage_total = 0
        self.stage_done = 0
        self.stage_start_ts = time.time()

        # Controls
        self._paused_evt = threading.Event()
        self._paused_evt.set()  # "not paused" means set
        self._quit_evt = threading.Event()
        self._stop_evt = threading.Event()

        # Last print time for throttling
        self._last_print = 0.0

        # In-memory log buffer to allow external components to surface UI notes
        self._log_messages: List[Tuple[str, str, float]] = []

    def start(self):
        """Start the progress reporter with fixed UI area."""
        if self.enable_dash:
            # Clear screen and position at top
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(_UI_LINE + "\n")
            sys.stdout.write("Video Deduplication Pipeline\n")
            sys.stdout.write(_UI_LINE + "\n")
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._ui_initialized = True
            self._ui_start_line = 5  # UI updates start at line 5

    def set_status(self, text: str) -> None:
        """Update status."""
        with self.lock:
            self.status_line = text
        self._print_if_due()

    def update_root_progress(self, *, current: Optional[Path], completed: int, total: int) -> None:
        """Update root progress."""
        with self.lock:
            self.roots_total = max(0, int(total))
            self.roots_completed = max(0, min(int(completed), self.roots_total))
            self.current_root_display = str(current) if current else ""

    def update_discovery(self, discovered: int, *, skipped: int = 0) -> None:
        """Update discovery progress."""
        with self.lock:
            self.discovery_files = max(0, int(discovered))
            self.discovery_skipped = max(0, int(skipped))
        self._print_if_due()

    def start_stage(self, name: str, total: int):
        """Start a new stage - UI updates in-place automatically."""
        with self.lock:
            self.stage_name = name
            self.stage_total = max(0, int(total))
            self.stage_done = 0
            self.stage_start_ts = time.time()
            self.status_line = name
        # Trigger immediate update to show new stage
        self._print_now()

    def set_total_files(self, n: int):
        """Set total files - UI updates in-place automatically."""
        with self.lock:
            self.total_files = int(n)
        # Trigger immediate update
        self._print_now()

    def inc_scanned(self, n: int = 1, *, bytes_added: int = 0, is_video: bool = False):
        """Increment scanned counter."""
        with self.lock:
            self.scanned_files += int(n)
            self.bytes_seen += int(bytes_added)
            if is_video:
                self.video_files += int(n)
            self.stage_done += int(n)
        self._print_if_due()

    def set_hash_total(self, n: int):
        """Set hash total."""
        with self.lock:
            self.hash_total = int(n)
            self.hash_done = 0

    def inc_hashed(self, n: int = 1, cache_hit: bool = False):
        """Increment hashed counter."""
        with self.lock:
            self.hash_done += int(n)
            if cache_hit:
                self.cache_hits += int(n)
            self.stage_done += int(n)
        self._print_if_due()

    def inc_group(self, mode: str, n: int = 1):
        """Increment group counter."""
        with self.lock:
            if mode == "hash":
                self.groups_hash += int(n)
            elif mode == "meta":
                self.groups_meta += int(n)
            elif mode == "phash":
                self.groups_phash += int(n)
            elif mode == "subset":
                self.groups_subset += int(n)

    def set_results(self, dup_groups: int, losers_count: int, bytes_total: int):
        """Set final results."""
        with self.lock:
            self.dup_groups_total = int(dup_groups)
            self.losers_total = int(losers_count)
            self.bytes_to_remove = int(bytes_total)

    def update_progress_periodically(self, current_step: int, total_steps: int, force_update: bool = False):
        """Update progress periodically."""
        with self.lock:
            self.stage_done = current_step
            if total_steps > 0:
                self.stage_total = max(self.stage_total, total_steps)
        if force_update:
            self._print_now()
        else:
            self._print_if_due()

    def _print_if_due(self):
        """Print progress if enough time has passed."""
        now = time.time()
        if (now - self._last_print) >= self.refresh_rate:
            self._print_now()

    def _print_now(self):
        """Print current progress with fixed in-place UI updates."""
        if not self.enable_dash or not self._ui_initialized:
            return

        now = time.time()
        self._last_print = now

        with self.lock:
            elapsed = now - self.start_ts
            stage_elapsed = now - self.stage_start_ts
            pct = 0.0
            if self.stage_total > 0:
                pct = (self.stage_done / self.stage_total) * 100.0

            stage_lower = self.stage_name.lower()

            # Build UI lines
            lines = []
            lines.append(_UI_LINE)
            lines.append(f"Stage: {self.stage_name.upper()}")
            lines.append(_UI_LINE)

            # Stage-specific metrics
            if "discover" in stage_lower:
                gb = self.bytes_seen / (1024**3)
                lines.append(f"  Files Found: {self.discovery_files:,}")
                lines.append(f"  Data Scanned: {gb:.1f} GiB")
                lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            elif "scan" in stage_lower:
                if self.stage_total > 0:
                    rate = self.stage_done / max(1, stage_elapsed)
                    gb = self.bytes_seen / (1024**3)
                    lines.append(f"  Progress: {self.stage_done:,}/{self.stage_total:,} ({pct:.1f}%)")
                    lines.append(f"  Rate: {rate:.0f} files/s")
                    lines.append(f"  Data Scanned: {gb:.1f} GiB")
                    lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            elif "partial" in stage_lower:
                if self.stage_total > 0:
                    rate = self.stage_done / max(1, stage_elapsed)
                    cache_pct = (self.cache_hits / max(1, self.hash_done)) * 100 if self.hash_done > 0 else 0
                    eta_sec = (self.stage_total - self.stage_done) / rate if rate > 0 else 0
                    lines.append(f"  Progress: {self.stage_done:,}/{self.stage_total:,} ({pct:.1f}%)")
                    lines.append(f"  Hash Rate: {rate:.1f} files/s")
                    lines.append(f"  Cache Hit Rate: {cache_pct:.0f}%")
                    lines.append(f"  ETA: {int(eta_sec)}s")
                    lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            elif "sha" in stage_lower:
                if self.stage_total > 0:
                    rate = self.stage_done / max(1, stage_elapsed)
                    cache_pct = (self.cache_hits / max(1, self.hash_done)) * 100 if self.hash_done > 0 else 0
                    eta_sec = (self.stage_total - self.stage_done) / rate if rate > 0 else 0
                    eta_min = int(eta_sec / 60)
                    lines.append(f"  Progress: {self.stage_done:,}/{self.stage_total:,} ({pct:.1f}%)")
                    lines.append(f"  Hash Rate: {rate:.2f} files/s")
                    lines.append(f"  Cache Hit Rate: {cache_pct:.0f}%")
                    lines.append(f"  ETA: {eta_min}m {int(eta_sec % 60)}s")
                    lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            elif "phash" in stage_lower:
                if self.stage_total > 0:
                    rate = self.stage_done / max(1, stage_elapsed)
                    eta_sec = (self.stage_total - self.stage_done) / rate if rate > 0 else 0
                    lines.append(f"  Progress: {self.stage_done:,}/{self.stage_total:,} ({pct:.1f}%)")
                    lines.append(f"  Rate: {rate:.1f} frames/s")
                    lines.append(f"  ETA: {int(eta_sec)}s")
                    lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            else:
                # Generic stage
                if self.stage_total > 0:
                    lines.append(f"  Progress: {self.stage_done:,}/{self.stage_total:,} ({pct:.1f}%)")
                lines.append(f"  Elapsed: {int(stage_elapsed)}s")

            lines.append(_UI_LINE)
            lines.append(f"Total Elapsed: {int(elapsed)}s")
            lines.append("")

        # Move cursor to UI start line and clear down
        sys.stdout.write(f"\033[{self._ui_start_line};1H")  # Move to line 5, column 1
        sys.stdout.write("\033[J")  # Clear from cursor to end of screen

        # Write all lines
        for line in lines:
            sys.stdout.write(line + "\n")

        sys.stdout.flush()

    def flush(self):
        """Flush progress output."""
        if self.enable_dash:
            print("", flush=True)

    def wait_if_paused(self):
        """Block if paused."""
        self._paused_evt.wait()

    def should_quit(self) -> bool:
        """Check if quit requested."""
        return self._quit_evt.is_set()

    def stop(self):
        """Stop the progress reporter."""
        self._stop_evt.set()
        if self.enable_dash:
            print("\n" + _UI_LINE)
            print("Pipeline Complete")
            print(_UI_LINE)
            sys.stdout.flush()

    def add_log(self, message: str, level: str = "INFO") -> None:
        """Record a diagnostic log entry for later inspection."""
        entry = (level.upper(), str(message), time.time())
        with self.lock:
            self._log_messages.append(entry)
            # Keep buffer bounded to prevent unbounded growth
            if len(self._log_messages) > 200:
                self._log_messages.pop(0)

    def recent_logs(self) -> List[Tuple[str, str, float]]:
        """Return a snapshot of recent log entries."""
        with self.lock:
            return list(self._log_messages)
