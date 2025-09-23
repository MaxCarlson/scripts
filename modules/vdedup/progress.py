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

        # Start TermDash with enhanced settings
        try:
            self.dash = TermDash(  # type: ignore
                refresh_rate=self.refresh_rate,
                enable_separators=True,
                reserve_extra_rows=3,
                align_columns=True,
                max_col_width=None,
            )
            self.dash.__enter__()  # type: ignore
        except Exception as e:
            # Fallback to non-UI mode if TermDash fails
            print(f"Warning: Failed to initialize UI: {e}", file=sys.stderr)
            self.enable_dash = False
            return

        # Enhanced title with visual indicator
        status_indicator = self._get_status_indicator()
        self.dash.add_line(  # type: ignore
            "title",
            Line("title", stats=[
                Stat("title", f"{status_indicator}Video Deduplication Pipeline",
                     format_string="{}", color="1;36")  # Bold cyan
            ], style="header"),  # type: ignore
            at_top=True,
        )

        # Banner with mode information
        bw = max(30, min(self._layout.cols - 2, 200))
        self._add_line("banner", Stat("banner", self.banner, format_string="{}",
                                    no_expand=True, display_width=bw, color="0;37"))

        # Add main progress bar for current stage
        if TERMDASH_AVAILABLE:
            self._progress_bars["main"] = ProgressBar(
                name="stage_progress",
                total=100,
                current=0,
                width=min(60, self._layout.cols - 20),
                charset="ascii",  # Use ASCII characters for Windows compatibility
                show_percent=True
            )

        if self._layout.stacked:
            w = bw
            # Current stage with color coding
            self._add_line("stage", Stat("stage", "idle", prefix="[S] Stage: ",
                                       format_string="{}", no_expand=True, display_width=w,
                                       color=lambda v: self._get_stage_color(str(v))))

            # Progress bar for current stage
            if TERMDASH_AVAILABLE and "main" in self._progress_bars:
                # Create a simple text-based progress bar for display
                bar_width = min(40, w - 20)
                if self.stage_total > 0:
                    progress_pct = (self.stage_done / self.stage_total)
                    filled = int(progress_pct * bar_width)
                    bar_text = f"[{'#' * filled}{'.' * (bar_width - filled)}] {progress_pct * 100:.1f}%"
                else:
                    bar_text = f"[{'.' * bar_width}] 0.0%"

                self._add_line("progress", Stat("progress_bar", bar_text,
                                               format_string="{}", no_expand=True, display_width=w, color="0;32"))

            # Timing information with better formatting
            self._add_line("timing",
                          Stat("elapsed", "00:00:00", prefix="[T] Stage: ", format_string="{}",
                               no_expand=True, display_width=w//2, color="0;33"),
                          Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}",
                               no_expand=True, display_width=w//2, color="0;36"))

            # File processing stats
            self._add_line("files", Stat("files", (0, 0), prefix="[F] Files: ",
                                       format_string="{}/{}", no_expand=True, display_width=w,
                                       color=lambda v: "0;32" if isinstance(v, tuple) and v[0] == v[1] and v[1] > 0 else "0;37"))
            self._add_line("videos", Stat("videos", 0, prefix="[V] Videos: ",
                                        format_string="{}", no_expand=True, display_width=w, color="0;35"))

            # Hashing progress with cache hit rate
            self._add_line("hashing",
                          Stat("hashed", (0, 0), prefix="[H] Hashed: ", format_string="{}/{}",
                               no_expand=True, display_width=w//2, color="0;33"),
                          Stat("cache_rate", "0%", prefix="Cache: ", format_string="{}",
                               no_expand=True, display_width=w//2,
                               color=lambda v: "0;32" if "%" in str(v) and float(str(v).rstrip('%')) > 50 else "0;37"))

            # Data volume with throughput
            self._add_line("throughput",
                          Stat("scanned", "0 MiB", prefix="[D] Data: ", format_string="{}",
                               no_expand=True, display_width=w//2, color="0;36"),
                          Stat("speed", "0 MB/s", prefix="Speed: ", format_string="{}",
                               no_expand=True, display_width=w//2, color="0;32"))

            # Duplicate detection results
            self._add_line("groups_hash", Stat("g_hash", 0, prefix="[G] Hash groups: ",
                                             format_string="{}", no_expand=True, display_width=w, color="0;33"))
            self._add_line("groups_meta", Stat("g_meta", 0, prefix="[M] Meta groups: ",
                                             format_string="{}", no_expand=True, display_width=w, color="0;35"))
            self._add_line("groups_phash", Stat("g_phash", 0, prefix="[P] pHash groups: ",
                                              format_string="{}", no_expand=True, display_width=w, color="0;31"))
            self._add_line("groups_subset", Stat("g_subset", 0, prefix="[S] Subset groups: ",
                                                format_string="{}", no_expand=True, display_width=w, color="0;31"))

            # Final results
            self._add_line("results",
                          Stat("dup_files", 0, prefix="[X] Duplicates: ", format_string="{}",
                               no_expand=True, display_width=w//2,
                               color=lambda v: "0;31" if v > 0 else "0;37"),
                          Stat("bytes_rm", "0 MiB", prefix="Space: ", format_string="{}",
                               no_expand=True, display_width=w//2,
                               color=lambda v: "0;32" if "GiB" in str(v) else "0;33" if "MiB" in str(v) else "0;37"))

            self._add_line("total_elapsed", Stat("tot_elapsed", "00:00:00", prefix="[T] Total: ",
                                                format_string="{}", no_expand=True, display_width=w, color="0;37"))
        else:
            # Wide layout with enhanced visuals
            self._add_line(
                "stage",
                Stat("stage", "idle", prefix="[S] Stage: ", format_string="{}",
                     no_expand=True, display_width=26,
                     color=lambda v: self._get_stage_color(str(v))),
                Stat("elapsed", "00:00:00", prefix="[T] ", format_string="{}",
                     no_expand=True, display_width=16, color="0;33"),
                Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}",
                     no_expand=True, display_width=16, color="0;36"),
            )

            # Progress bar row
            if TERMDASH_AVAILABLE and "main" in self._progress_bars:
                # Create text-based progress bar for wide layout too
                bar_width = 40
                if self.stage_total > 0:
                    progress_pct = (self.stage_done / self.stage_total)
                    filled = int(progress_pct * bar_width)
                    bar_text = f"[{'#' * filled}{'.' * (bar_width - filled)}] {progress_pct * 100:.1f}%"
                else:
                    bar_text = f"[{'.' * bar_width}] 0.0%"

                self._add_line("progress", Stat("progress_bar", bar_text,
                                               format_string="{}", no_expand=True, display_width=62, color="0;32"))

            self._add_line(
                "files",
                Stat("files", (0, 0), prefix="[F] Files: ", format_string="{}/{}",
                     no_expand=True, display_width=26,
                     color=lambda v: "0;32" if isinstance(v, tuple) and v[0] == v[1] and v[1] > 0 else "0;37"),
                Stat("videos", 0, prefix="[V] Videos: ", format_string="{}",
                     no_expand=True, display_width=20, color="0;35"),
                Stat("speed", "0 files/s", prefix="[>] ", format_string="{}",
                     no_expand=True, display_width=16, color="0;32"),
            )
            self._add_line(
                "hash",
                Stat("hashed", (0, 0), prefix="[H] Hashed: ", format_string="{}/{}",
                     no_expand=True, display_width=26, color="0;33"),
                Stat("cache_rate", "0%", prefix="[C] Cache: ", format_string="{}",
                     no_expand=True, display_width=20,
                     color=lambda v: "0;32" if "%" in str(v) and float(str(v).rstrip('%')) > 50 else "0;37"),
                Stat("scanned", "0 MiB", prefix="[D] ", format_string="{}",
                     no_expand=True, display_width=16, color="0;36"),
            )
            self._add_line(
                "groups1",
                Stat("g_hash", 0, prefix="[G] Hash: ", format_string="{}",
                     no_expand=True, display_width=18, color="0;33"),
                Stat("g_meta", 0, prefix="[M] Meta: ", format_string="{}",
                     no_expand=True, display_width=18, color="0;35"),
                Stat("g_phash", 0, prefix="[P] pHash: ", format_string="{}",
                     no_expand=True, display_width=18, color="0;31"),
                Stat("g_subset", 0, prefix="[S] Subset: ", format_string="{}",
                     no_expand=True, display_width=18, color="0;31"),
            )
            self._add_line(
                "results",
                Stat("dup_files", 0, prefix="[X] Duplicates: ", format_string="{}",
                     no_expand=True, display_width=26,
                     color=lambda v: "0;31" if v > 0 else "0;37"),
                Stat("bytes_rm", "0 MiB", prefix="[B] Space: ", format_string="{}",
                     no_expand=True, display_width=24,
                     color=lambda v: "0;32" if "GiB" in str(v) else "0;33" if "MiB" in str(v) else "0;37"),
                Stat("tot_elapsed", "00:00:00", prefix="[T] ", format_string="{}",
                     no_expand=True, display_width=16, color="0;37"),
            )

        # start ticker + keys
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()
        if self._stdin_ok and not self._keys_thread:
            self._keys_thread = threading.Thread(target=self._keys_loop, daemon=True)
            self._keys_thread.start()

        # Use a non-blocking initial flush with timeout
        def _safe_flush():
            try:
                self.flush()
            except Exception:
                pass

        flush_thread = threading.Thread(target=_safe_flush, daemon=True)
        flush_thread.start()
        # Don't wait for flush to complete - let it run in background

    def _tick_loop(self):
        while not self._stop_evt.is_set():
            try:
                self._update_eta()
            except Exception:
                pass
            time.sleep(self.refresh_rate)

    def _update_eta(self):
        if not self.enable_dash or not self.dash:
            return

        # Calculate throughput and metrics
        self._calculate_throughput()

        # Update timing
        eta_text = _fmt_hms(self._estimate_remaining())
        elapsed_stage = _fmt_hms(time.time() - self.stage_start_ts)
        elapsed_total = _fmt_hms(time.time() - self.start_ts)

        # Update progress bar
        if "main" in self._progress_bars and self.stage_total > 0:
            self._progress_bars["main"].set(self.stage_done)
            self._progress_bars["main"].set_total(self.stage_total)

            # Update the text-based progress bar display
            try:
                bar_width = 40
                progress_pct = (self.stage_done / self.stage_total) if self.stage_total > 0 else 0
                filled = int(progress_pct * bar_width)
                bar_text = f"[{'#' * filled}{'.' * (bar_width - filled)}] {progress_pct * 100:.1f}%"
                self.dash.update_stat("progress", "progress_bar", bar_text)  # type: ignore
            except:
                pass

        # Update title with current status
        status_indicator = self._get_status_indicator()
        try:
            self.dash.update_stat("title", "title", f"{status_indicator}Video Deduplication Pipeline")  # type: ignore
        except:
            pass

        # Update timing stats
        self.dash.update_stat("stage", "eta", eta_text)  # type: ignore
        if self._layout.stacked:
            self.dash.update_stat("timing", "elapsed", elapsed_stage)  # type: ignore
            self.dash.update_stat("total_elapsed", "tot_elapsed", elapsed_total)  # type: ignore
            # Update throughput stats
            if self.throughput_files_per_sec > 0:
                self.dash.update_stat("throughput", "speed", self._format_throughput(self.throughput_files_per_sec, "files"))  # type: ignore
            if self.cache_hit_rate > 0:
                self.dash.update_stat("hashing", "cache_rate", f"{self.cache_hit_rate:.1f}%")  # type: ignore
        else:
            self.dash.update_stat("stage", "elapsed", elapsed_stage)  # type: ignore
            self.dash.update_stat("results", "tot_elapsed", elapsed_total)  # type: ignore
            # Update wide layout throughput
            if self.throughput_files_per_sec > 0:
                self.dash.update_stat("files", "speed", self._format_throughput(self.throughput_files_per_sec, "files"))  # type: ignore
            if self.cache_hit_rate > 0:
                self.dash.update_stat("hash", "cache_rate", f"{self.cache_hit_rate:.1f}%")  # type: ignore

    def set_banner(self, text: str):
        self.banner = text
        if self.enable_dash and self.dash:
            self.dash.update_stat("banner", "banner", text)  # type: ignore

    def flush(self):
        if self.enable_dash and self.dash:
            # Now safe for single-threaded processing with periodic updates
            # if threading.current_thread() != self.main_thread:
            #     return

            with self.lock:
                # Calculate enhanced metrics
                self._calculate_throughput()

                # Format data sizes with better units
                scanned_text = self._format_data_size(self.bytes_seen)
                remove_text = self._format_data_size(self.bytes_to_remove)

                self.dash.update_stat("stage", "stage", self.stage_name)  # type: ignore
                self.dash.update_stat("files", "files", (self.scanned_files, self.total_files))  # type: ignore

                if self._layout.stacked:
                    self.dash.update_stat("videos", "videos", self.video_files)  # type: ignore
                    self.dash.update_stat("hashing", "hashed", (self.hash_done, self.hash_total))  # type: ignore
                    self.dash.update_stat("throughput", "scanned", scanned_text)  # type: ignore
                    self.dash.update_stat("groups_hash", "g_hash", self.groups_hash)  # type: ignore
                    self.dash.update_stat("groups_meta", "g_meta", self.groups_meta)  # type: ignore
                    self.dash.update_stat("groups_phash", "g_phash", self.groups_phash)  # type: ignore
                    self.dash.update_stat("groups_subset", "g_subset", self.groups_subset)  # type: ignore
                    self.dash.update_stat("results", "dup_files", self.losers_total)  # type: ignore
                    self.dash.update_stat("results", "bytes_rm", remove_text)  # type: ignore
                else:
                    self.dash.update_stat("files", "videos", self.video_files)  # type: ignore
                    self.dash.update_stat("hash", "hashed", (self.hash_done, self.hash_total))  # type: ignore
                    self.dash.update_stat("hash", "scanned", scanned_text)  # type: ignore
                    self.dash.update_stat("groups1", "g_hash", self.groups_hash)  # type: ignore
                    self.dash.update_stat("groups1", "g_meta", self.groups_meta)  # type: ignore
                    self.dash.update_stat("groups1", "g_phash", self.groups_phash)  # type: ignore
                    self.dash.update_stat("groups1", "g_subset", self.groups_subset)  # type: ignore
                    self.dash.update_stat("results", "dup_files", self.losers_total)  # type: ignore
                    self.dash.update_stat("results", "bytes_rm", remove_text)  # type: ignore

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

        # Throttle updates - only update every 100ms at most
        import time
        now = time.time()
        last_update = getattr(self, '_last_periodic_update', 0)

        if force_update or (now - last_update) >= 0.1:  # 100ms throttle
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
        # stop ticker + keys threads
        self._stop_evt.set()
        if self._ticker:
            try:
                self._ticker.join(timeout=1.0)
            except Exception:
                pass
        if self._keys_thread:
            try:
                self._keys_thread.join(timeout=1.0)
            except Exception:
                pass
        if self.enable_dash and self.dash:
            try:
                self.dash.__exit__(None, None, None)  # type: ignore
            except Exception:
                pass
