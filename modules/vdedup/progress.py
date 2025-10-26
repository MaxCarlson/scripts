#!/usr/bin/env python3
"""
vdedup.progress

Live progress reporter with a responsive TermDash UI.
- Auto layout: wide (multi-column) or stacked (1 stat per line) based on terminal width.
- Can be forced with stacked_ui=True / wide_ui=True flags.
- Thread-safe counters and per-stage ETA + total elapsed.
- Key controls:
    Z or P = pause/resume pipeline
    Q = request quit (press 'y' to confirm)

This module does not require TermDash to run; when it is not available,
all update calls are no-ops (the pipeline still functions).
"""

from __future__ import annotations

import os
import select
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Try to import TermDash (user-provided module)
TERMDASH_AVAILABLE = False
TermDash = Line = Stat = ProgressBar = None  # type: ignore
try:
    from termdash import TermDash, Line, Stat, ProgressBar  # type: ignore
    from termdash.utils import format_bytes, fmt_hms, bytes_to_mib  # type: ignore
    TERMDASH_AVAILABLE = True
except Exception:
    TERMDASH_AVAILABLE = False


def _fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "--:--:--"
    s = int(seconds)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


@dataclass
class _LayoutChoice:
    stacked: bool
    cols: int


class ProgressReporter:
    """
    Enhanced progress reporter with visual indicators, progress bars, and color coding.

    Features:
    - Dynamic progress bars for each pipeline stage
    - Color-coded status indicators
    - Real-time throughput and ETA calculations
    - Visual feedback for pause/resume states
    - Cache hit rate indicators
    - Memory and performance metrics

    Public methods used by the pipeline/CLI:
      - start_stage(name, total)
      - set_total_files(n)
      - inc_scanned(n=1, bytes_added=0, is_video=False)
      - set_hash_total(n)
      - inc_hashed(n=1, cache_hit=False)
      - inc_group(mode, n=1)   # mode in {"hash","meta","phash"}
      - set_results(dup_groups, losers_count, bytes_total)
      - set_banner(text)
      - flush()
      - stop()

    Control helpers for pipeline:
      - wait_if_paused()
      - should_quit() -> bool
    """

    def __init__(
        self,
        enable_dash: bool,
        *,
        refresh_rate: float = 0.2,
        banner: str = "",
        stacked_ui: Optional[bool] = None,  # None->auto
    ):
        self.enable_dash = bool(enable_dash and TERMDASH_AVAILABLE)
        self.refresh_rate = max(0.05, float(refresh_rate))
        self.banner = banner

        # Layout preference / actual
        self._stacked_pref = stacked_ui
        self._layout = _LayoutChoice(stacked=False, cols=120)

        # Locks & timing
        self.lock = threading.Lock()
        self.start_ts = time.time()

        # Track main thread for thread-safe UI updates
        self.main_thread = threading.current_thread()

        # High-level counters
        self.total_files = 0
        self.scanned_files = 0
        self.video_files = 0
        self.bytes_seen = 0

        # Discovery / root tracking
        self.status_line = "Initializing"
        self.discovery_files = 0
        self.discovery_skipped = 0
        self.roots_total = 0
        self.roots_completed = 0
        self.current_root_display = ""
        self._spinner_chars = "|/-\\"
        self._spinner_idx = 0
        no_color_env = os.environ.get("NO_COLOR")
        disable_color_env = os.environ.get("VDDEDUP_NO_COLOR")
        self._color_enabled = not bool(no_color_env or disable_color_env)

        # Hash/probe counters (generic "hashed" progress bar reused by stages)
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
        self._ema_rate = 0.0  # items/sec (EMA)

        # Enhanced UI metrics
        self.throughput_files_per_sec = 0.0
        self.throughput_bytes_per_sec = 0.0
        self.cache_hit_rate = 0.0
        self.current_file_name = ""
        self.stage_progress_percent = 0.0
        self.memory_usage_mb = 0.0

        # Dashboard runtime
        self.dash: Optional[TermDash] = None  # type: ignore
        self._ticker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._progress_bars = {}  # Progress bars for different stages

        # Controls
        self._paused_evt = threading.Event()
        self._paused_evt.set()  # "not paused" means set
        self._quit_evt = threading.Event()
        self._keys_thread: Optional[threading.Thread] = None
        self._await_quit_confirm = False
        self._stdin_ok = sys.stdin and sys.stdin.isatty()

    # --------------- Enhanced UI helpers ---------------

    def _get_stage_color(self, stage_name: str) -> str:
        """Return ANSI color code based on stage type and status."""
        if not TERMDASH_AVAILABLE:
            return ""

        stage_lower = stage_name.lower()
        if "scan" in stage_lower:
            return "0;36"  # Cyan for scanning
        elif "hash" in stage_lower:
            return "0;33"  # Yellow for hashing
        elif "meta" in stage_lower:
            return "0;35"  # Magenta for metadata
        elif "phash" in stage_lower or "subset" in stage_lower:
            return "0;31"  # Red for intensive operations
        elif "complete" in stage_lower or "done" in stage_lower:
            return "0;32"  # Green for completion
        else:
            return "0;37"  # White for other stages

    def _get_status_indicator(self) -> str:
        """Return a visual status indicator based on current state."""
        if not self._paused_evt.is_set():
            return "[||] "  # Paused
        elif self.stage_done > 0 and self.stage_total > 0:
            progress = self.stage_done / self.stage_total
            if progress < 0.1:
                return "[>] "  # Starting
            elif progress < 0.9:
                return "[*] "  # Active
            else:
                return "[~] "  # Nearly done
        else:
            return "[-] "  # Idle

    def _calculate_throughput(self):
        """Calculate real-time throughput metrics."""
        with self.lock:
            elapsed = max(1e-6, time.time() - self.stage_start_ts)
            self.throughput_files_per_sec = self.stage_done / elapsed
            self.throughput_bytes_per_sec = self.bytes_seen / elapsed

            if self.hash_done > 0:
                self.cache_hit_rate = (self.cache_hits / self.hash_done) * 100.0
            else:
                self.cache_hit_rate = 0.0

            if self.stage_total > 0:
                self.stage_progress_percent = (self.stage_done / self.stage_total) * 100.0
            else:
                self.stage_progress_percent = 0.0

    def _format_throughput(self, value: float, unit: str) -> str:
        """Format throughput values with appropriate units."""
        if value >= 1000:
            return f"{value/1000:.1f}k {unit}/s"
        elif value >= 1:
            return f"{value:.1f} {unit}/s"
        else:
            return f"{value:.2f} {unit}/s"

    def _colorize(self, text: str, color_code: str) -> str:
        if not self.enable_dash or not self._color_enabled or not color_code:
            return text
        return f"\033[{color_code}m{text}\033[0m"

    def _shorten(self, text: str, width: int = 60) -> str:
        if not text:
            return ""
        if len(text) <= width:
            return text
        return f"…{text[-(width - 1):]}"

    def _next_spinner(self) -> str:
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
        return self._spinner_chars[self._spinner_idx]

    def set_status(self, text: str) -> None:
        with self.lock:
            self.status_line = text
        if self.enable_dash:
            self.flush()

    def update_root_progress(self, *, current: Optional[Path], completed: int, total: int) -> None:
        if not self.enable_dash:
            return
        with self.lock:
            self.roots_total = max(0, int(total))
            self.roots_completed = max(0, min(int(completed), self.roots_total))
            self.current_root_display = str(current) if current else ""
        self.flush()

    def update_discovery(self, discovered: int, *, skipped: int = 0) -> None:
        if not self.enable_dash:
            return
        with self.lock:
            self.discovery_files = max(0, int(discovered))
            self.discovery_skipped = max(0, int(skipped))
            if self.stage_total <= 0:
                self.stage_done = self.discovery_files
        self.flush()

    # --------------- keyboard handling ---------------

    def _keys_loop(self):
        """
        Very small non-blocking key reader:
          - Windows: use msvcrt.getch
          - POSIX: select on sys.stdin
        """
        if not self._stdin_ok:
            return
        is_win = os.name == "nt"
        if is_win:
            try:
                import msvcrt  # type: ignore
            except Exception:
                return
            while not self._stop_evt.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    self._handle_key(ch)
                time.sleep(0.05)
        else:
            fd = sys.stdin.fileno()
            while not self._stop_evt.is_set():
                r, _w, _e = select.select([fd], [], [], 0.05)
                if r:
                    try:
                        ch = os.read(fd, 1).decode(errors="ignore")
                    except Exception:
                        ch = ""
                    if ch:
                        self._handle_key(ch)
            return

    def _handle_key(self, ch: str):
        ch = (ch or "").lower()
        if ch == "z" or ch == "p":  # Support both 'z' and 'p' for pause
            if self._paused_evt.is_set():
                # pause now
                self._paused_evt.clear()
                self.set_banner((self.banner or "") + "  [PAUSED]")
            else:
                # resume
                self._paused_evt.set()
                self.set_banner((self.banner or "").replace("  [PAUSED]", ""))
        elif ch == "q":
            # require next 'y' to confirm
            self._await_quit_confirm = True
            if self.dash:
                self.set_banner((self.banner or "") + "  [Quit? press 'y' to confirm]")
        elif ch == "y" and self._await_quit_confirm:
            self._quit_evt.set()
            self._await_quit_confirm = False

    def wait_if_paused(self):
        # Block pipeline worker threads while paused
        while not self._paused_evt.is_set():
            time.sleep(0.05)

    def should_quit(self) -> bool:
        return self._quit_evt.is_set()

    # ---------------- UI plumbing --------------------

    def _term_cols(self) -> int:
        try:
            return shutil.get_terminal_size(fallback=(120, 30)).columns
        except Exception:
            return 120

    def _choose_layout(self) -> _LayoutChoice:
        cols = self._term_cols()
        if self._stacked_pref is None:
            stacked = cols < 120  # auto
        else:
            stacked = bool(self._stacked_pref)
        return _LayoutChoice(stacked=stacked, cols=cols)

    def _add_line(self, key: str, *stats):
        if not self.dash:
            return
        self.dash.add_line(key, Line(key, stats=list(stats)))  # type: ignore

    def start(self):
        if not self.enable_dash:
            # still start key thread for pause/quit convenience if stdin is a TTY
            if self._stdin_ok and not self._keys_thread:
                self._keys_thread = threading.Thread(target=self._keys_loop, daemon=True)
                self._keys_thread.start()
            return

        # Clear screen before starting UI
        import os
        if os.name == 'nt':  # Windows
            os.system('cls')
        else:  # Unix/Linux/macOS
            os.system('clear')

        self._layout = self._choose_layout()

        # STEP 14: Create simple custom UI without TermDash to avoid infinite loops
        try:
            # Use simple ANSI-based UI instead of TermDash
            self.dash = None  # No TermDash instance
            self._simple_ui_initialized = True
            print("\033[2J\033[H", end="", flush=True)  # Clear screen and go to top
            print("=== Video Deduplication Pipeline ===", flush=True)
            print("Initializing...", flush=True)
        except Exception as e:
            print(f"Warning: Failed to initialize simple UI: {e}", file=sys.stderr)
            self.enable_dash = False
            return

        # STEP 16: ALL TermDash setup code removed - using simple custom UI only
        # The old TermDash initialization code has been completely removed to prevent
        # infinite loops and UI freezing. Now only the simple ANSI-based UI is used.

        # STEP 9: Remove ticker thread that causes infinite refresh loops
        # Only start keys thread for pause/quit functionality
        if self._stdin_ok and not self._keys_thread:
            self._keys_thread = threading.Thread(target=self._keys_loop, daemon=True)
            self._keys_thread.start()

        # STEP 13: Initialize flush lock but skip initial flush test
        # The infinite loop might be caused by the initial flush call
        self._flush_lock = threading.Lock()

    # STEP 12: _tick_loop method removed - no ticker thread

    # STEP 11: _update_eta method removed - timing updates now handled in flush()

    def set_banner(self, text: str):
        self.banner = text
        # Banner updates are handled in the simple UI flush() method
        # No need for TermDash-specific banner updates

    def flush(self):
        if not (self.enable_dash and hasattr(self, "_simple_ui_initialized")):
            return

        if not hasattr(self, "_flush_lock"):
            self._flush_lock = threading.Lock()

        if not self._flush_lock.acquire(blocking=False):
            return

        try:
            with self.lock:
                self._calculate_throughput()

                scanned_text = self._format_data_size(self.bytes_seen)
                remove_text = self._format_data_size(self.bytes_to_remove)
                eta_text = _fmt_hms(self._estimate_remaining())

                now = time.time()
                elapsed_stage = _fmt_hms(now - self.stage_start_ts)
                elapsed_total = _fmt_hms(now - self.start_ts)
                clock_display = time.strftime("%H:%M:%S")

                bar_width = 30
                if self.stage_total > 0:
                    progress_pct = self.stage_done / self.stage_total if self.stage_total else 0.0
                    progress_pct = max(0.0, min(progress_pct, 1.0))
                    filled = int(progress_pct * bar_width)
                    bar_text = f"[{'#' * filled}{'.' * (bar_width - filled)}] {progress_pct * 100:5.1f}%"
                else:
                    spinner = self._next_spinner()
                    bar_text = f"[{spinner}{'.' * (bar_width - 1)}]  --.-%"

                indicator = self._get_status_indicator()
                stage_label = self._colorize(self.stage_name.title(), self._get_stage_color(self.stage_name))
                status_text = self.status_line or "Working"

                cache_line = f"Hashed: {self.hash_done}/{self.hash_total}"
                hit_pct = (self.cache_hits / self.hash_done * 100.0) if self.hash_done else 0.0
                if self.hash_done:
                    cache_line += f" | Cache hits: {self.cache_hits} ({hit_pct:.1f}%)"

                root_line = ""
                if self.roots_total:
                    active_root = self._shorten(self.current_root_display, 64) if self.current_root_display else "—"
                    root_line = f"Roots: {self.roots_completed}/{self.roots_total} | Active: {active_root}"

                discovery_line = ""
                if self.discovery_files and self.stage_name.lower().startswith("discover"):
                    discovery_line = f"Discovered: {self.discovery_files}"
                    if self.discovery_skipped:
                        discovery_line += f" | Skipped: {self.discovery_skipped}"

                throughput_line = ""
                if self.throughput_files_per_sec > 0:
                    mib_per_sec = self.throughput_bytes_per_sec / (1024 * 1024)
                    throughput_line = f"Speed: {self.throughput_files_per_sec:.1f} files/s, {mib_per_sec:.1f} MiB/s"

                files_line = f"Files: {self.scanned_files}/{self.total_files} | Videos: {self.video_files}"
                groups_line = f"Groups: H={self.groups_hash} M={self.groups_meta} P={self.groups_phash} S={self.groups_subset}"
                summary_line = f"Summary: groups={self.dup_groups_total} losers={self.losers_total} reclaim={remove_text}"
                data_line = f"Data seen: {scanned_text}"
                timing_line = f"Clock: {clock_display} | Stage: {elapsed_stage} | Total: {elapsed_total} | ETA: {eta_text}"

                render_lines = [
                    "=== Video Deduplication Pipeline ===",
                    f"{indicator}{stage_label}",
                    f"Status: {status_text}",
                ]

                if root_line:
                    render_lines.append(root_line)
                if discovery_line:
                    render_lines.append(discovery_line)

                render_lines.extend(
                    [
                        f"Progress: {bar_text}",
                        files_line,
                        cache_line,
                        groups_line,
                        summary_line,
                        data_line,
                        timing_line,
                    ]
                )

                if throughput_line:
                    render_lines.append(throughput_line)

                render_lines.append("-" * 60)

            print("\033[2J\033[H", end="", flush=True)
            for line in render_lines:
                print(line, flush=True)
        finally:
            self._flush_lock.release()

    def _format_data_size(self, bytes_value: int) -> str:
        """Format byte values with appropriate units and colors."""
        if TERMDASH_AVAILABLE and hasattr(self, 'format_bytes'):
            mib_val = bytes_value / (1024 * 1024)
            return format_bytes(mib_val)  # type: ignore
        else:
            # Fallback formatting
            if bytes_value >= 1024**3:
                return f"{bytes_value/(1024**3):.1f} GiB"
            elif bytes_value >= 1024**2:
                return f"{bytes_value/(1024**2):.1f} MiB"
            elif bytes_value >= 1024:
                return f"{bytes_value/1024:.1f} KiB"
            else:
                return f"{bytes_value} B"

    def start_stage(self, name: str, total: int):
        with self.lock:
            self.stage_name = name
            self.stage_total = max(0, int(total))
            self.stage_done = 0
            self.stage_start_ts = time.time()
            self._ema_rate = 0.0
            self.status_line = name
            if not name.lower().startswith("discover"):
                self.discovery_files = 0
                self.discovery_skipped = 0
        self.flush()

    def _bump_stage(self, n: int = 1):
        with self.lock:
            self.stage_done += int(n)
            elapsed = max(1e-6, time.time() - self.stage_start_ts)
            inst = self.stage_done / elapsed
            alpha = 0.15
            self._ema_rate = inst if self._ema_rate <= 0 else (alpha * inst + (1 - alpha) * self._ema_rate)

    def _estimate_remaining(self) -> Optional[float]:
        with self.lock:
            if self.stage_total <= 0:
                return None
            remaining = self.stage_total - self.stage_done
            if remaining <= 0:
                return 0.0
            rate = self._ema_rate
            if rate <= 0:
                elapsed = max(1e-6, time.time() - self.stage_start_ts)
                rate = self.stage_done / elapsed if self.stage_done > 0 else 0.0
            return (remaining / rate) if rate > 0 else None

    def set_total_files(self, n: int):
        with self.lock:
            self.total_files = int(n)
        self.flush()

    def inc_scanned(self, n: int = 1, *, bytes_added: int = 0, is_video: bool = False):
        with self.lock:
            self.scanned_files += int(n)
            self.bytes_seen += int(bytes_added)
            if is_video:
                self.video_files += int(n)
        if self.stage_name.lower().startswith("scan"):
            self._bump_stage(n)
        self.flush()

    def set_hash_total(self, n: int):
        with self.lock:
            self.hash_total = int(n)
            self.hash_done = 0
        self.flush()

    def inc_hashed(self, n: int = 1, cache_hit: bool = False):
        with self.lock:
            self.hash_done += int(n)
            if cache_hit:
                self.cache_hits += int(n)
        self._bump_stage(n)
        self.flush()

    def inc_group(self, mode: str, n: int = 1):
        with self.lock:
            if mode == "hash":
                self.groups_hash += int(n)
            elif mode == "meta":
                self.groups_meta += int(n)
            elif mode == "phash":
                self.groups_phash += int(n)
            elif mode == "subset":
                self.groups_subset += int(n)
        self.flush()

    def set_current_file(self, filename: str):
        """Update the current file being processed for display."""
        with self.lock:
            self.current_file_name = filename
            # Update banner to show current file (truncated for display)
            if len(filename) > 50:
                display_name = "..." + filename[-47:]
            else:
                display_name = filename
            if self.banner and not filename.startswith("Processing:"):
                self.set_banner(f"{self.banner} | Processing: {display_name}")

    def clear_current_file(self):
        """Clear the current file display."""
        with self.lock:
            self.current_file_name = ""
            # Restore original banner
            if " | Processing:" in self.banner:
                original_banner = self.banner.split(" | Processing:")[0]
                self.set_banner(original_banner)

    def set_results(self, dup_groups: int, losers_count: int, bytes_total: int):
        with self.lock:
            self.dup_groups_total = int(dup_groups)
            self.losers_total = int(losers_count)
            self.bytes_to_remove = int(bytes_total)
        self.flush()

    def update_progress_periodically(self, current_step: int, total_steps: int, force_update: bool = False):
        """
        Call this periodically during single-threaded processing to update UI.
        Designed to be called every N iterations to keep UI responsive.
        """
        if not self.enable_dash:
            return

        # Update stage progress
        with self.lock:
            self.stage_done = current_step
            if total_steps > 0:
                self.stage_total = max(self.stage_total, total_steps)

        # STEP 7: More conservative throttling - only update every 500ms
        import time
        now = time.time()
        last_update = getattr(self, '_last_periodic_update', 0)

        if force_update or (now - last_update) >= 0.5:  # 500ms throttle
            self._last_periodic_update = now
            self.flush()

    def copy_state_from(self, other_reporter):
        """Copy progress state from another reporter (thread-safe)."""
        if not other_reporter:
            return

        with self.lock:
            with other_reporter.lock:
                # Copy all state variables
                self.stage_name = other_reporter.stage_name
                self.stage_total = other_reporter.stage_total
                self.stage_done = other_reporter.stage_done
                self.stage_start_ts = other_reporter.stage_start_ts
                self._ema_rate = other_reporter._ema_rate

                self.total_files = other_reporter.total_files
                self.scanned_files = other_reporter.scanned_files
                self.video_files = other_reporter.video_files
                self.bytes_seen = other_reporter.bytes_seen

                self.hash_total = other_reporter.hash_total
                self.hash_done = other_reporter.hash_done
                self.cache_hits = other_reporter.cache_hits

                self.groups_hash = other_reporter.groups_hash
                self.groups_meta = other_reporter.groups_meta
                self.groups_phash = other_reporter.groups_phash
                self.groups_subset = other_reporter.groups_subset

                self.dup_groups_total = other_reporter.dup_groups_total
                self.losers_total = other_reporter.losers_total
                self.bytes_to_remove = other_reporter.bytes_to_remove

    def stop(self):
        # Stop keys thread only (no ticker thread in simple UI)
        self._stop_evt.set()
        if self._keys_thread:
            try:
                self._keys_thread.join(timeout=1.0)
            except Exception:
                pass
        # Simple UI cleanup - just clear screen
        if self.enable_dash and hasattr(self, '_simple_ui_initialized'):
            print("\033[2J\033[H", end="", flush=True)  # Clear screen
            print("=== Pipeline Complete ===", flush=True)
