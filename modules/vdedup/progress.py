#!/usr/bin/env python3
"""
vdedup.progress

Live progress reporter with a responsive TermDash UI + hotkeys:
- 'z' to Pause/Resume pipeline work (UI shows [PAUSED])
- 'q' to request Quit (prompts [y/N] in the console)

Layout:
- Auto layout: wide (multi-column) or stacked (1 stat per line) based on terminal width.
- Can be forced with stacked_ui=True / wide_ui=True flags.

Thread-safety:
- All counters are protected by a lock.
- wait_if_paused() can be called inside worker threads to block while paused.

This module does not require TermDash to run; when it is not available,
all update calls are no-ops (the pipeline still functions).
"""

from __future__ import annotations

import atexit
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
TermDash = Line = Stat = None  # type: ignore
try:
    from termdash import TermDash, Line, Stat  # type: ignore
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
    Counters + live UI + hotkeys.
    Public methods used by the pipeline/CLI:
      - start_stage(name, total)
      - set_total_files(n)
      - inc_scanned(n=1, bytes_added=0, is_video=False)
      - set_hash_total(n)
      - inc_hashed(n=1, cache_hit=False)
      - inc_group(mode, n=1)   # mode in {"hash","meta","phash"}
      - set_results(dup_groups, losers_count, bytes_total)
      - set_banner(text)
      - wait_if_paused()
      - should_quit()
      - flush()
      - stop()
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

        # Pause / Quit controls
        self._paused = False
        self._pause_cv = threading.Condition()
        self._quit = False

        # Dashboard runtime
        self.dash: Optional[TermDash] = None  # type: ignore
        self._ticker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._key_thread: Optional[threading.Thread] = None

        # POSIX raw mode handles
        self._tty_restore = None

    # ------------- Hotkeys -------------

    def _enable_posix_cbreak(self):
        """Enable cbreak mode on POSIX to read single keys from stdin."""
        if os.name != "nt" and sys.stdin.isatty():
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._tty_restore = (fd, old)

            def _restore():
                try:
                    if self._tty_restore:
                        termios.tcsetattr(self._tty_restore[0], termios.TCSADRAIN, self._tty_restore[1])
                except Exception:
                    pass

            atexit.register(_restore)

    def _key_loop(self):
        """Background key watcher: 'z' pause/resume, 'q' quit? [y/N]."""
        try:
            if os.name != "nt":
                self._enable_posix_cbreak()
        except Exception:
            pass

        while not self._stop_evt.is_set() and not self._quit:
            ch = None
            try:
                if os.name == "nt":
                    try:
                        import msvcrt  # type: ignore
                        if msvcrt.kbhit():
                            ch = msvcrt.getwch()
                    except Exception:
                        time.sleep(0.2)
                        continue
                else:
                    # POSIX: non-blocking select on stdin
                    r, _w, _e = select.select([sys.stdin], [], [], 0.2)
                    if r:
                        ch = sys.stdin.read(1)
            except Exception:
                # No input
                time.sleep(0.2)
                continue

            if not ch:
                continue
            if ch in ("z", "Z"):
                self.toggle_pause()
            elif ch in ("q", "Q"):
                # Prompt for confirmation in console
                try:
                    # Temporarily show prompt outside the dashboard
                    sys.stdout.write("\nQuit? [y/N]: ")
                    sys.stdout.flush()
                    ans = None
                    if os.name == "nt":
                        import msvcrt  # type: ignore
                        # read a single key; fall back to input if needed
                        t0 = time.time()
                        while time.time() - t0 < 10:
                            if msvcrt.kbhit():
                                ans = msvcrt.getwch()
                                break
                            time.sleep(0.05)
                    else:
                        r, _w, _e = select.select([sys.stdin], [], [], 10.0)
                        if r:
                            ans = sys.stdin.read(1)
                    if (ans or "").lower() == "y":
                        with self.lock:
                            self._quit = True
                        sys.stdout.write(" quitting...\n")
                        sys.stdout.flush()
                        break
                    else:
                        sys.stdout.write(" continuing.\n")
                        sys.stdout.flush()
                except Exception:
                    # If prompt fails, do nothing
                    pass

    def toggle_pause(self):
        with self._pause_cv:
            self._paused = not self._paused
            if not self._paused:
                self._pause_cv.notify_all()
        self.flush()  # refresh "[PAUSED]" marker

    def wait_if_paused(self):
        """Worker threads call this to block while paused."""
        with self._pause_cv:
            while self._paused and not self._quit:
                self._pause_cv.wait(timeout=0.25)

    def should_quit(self) -> bool:
        with self.lock:
            return bool(self._quit)

    # ----------- UI helpers -----------

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
        # Start key watcher even if UI is disabled (hotkeys still work)
        self._stop_evt.clear()
        if self._key_thread is None or not self._key_thread.is_alive():
            self._key_thread = threading.Thread(target=self._key_loop, daemon=True)
            self._key_thread.start()

        if not self.enable_dash:
            return

        self._layout = self._choose_layout()

        # Start TermDash
        self.dash = TermDash(  # type: ignore
            refresh_rate=self.refresh_rate,
            enable_separators=False,
            reserve_extra_rows=2,
            align_columns=True,
            max_col_width=None,
        )
        self.dash.__enter__()  # type: ignore

        # Title
        self.dash.add_line(  # type: ignore
            "title",
            Line("title", stats=[Stat("title", "Video Deduper — Live (press 'z' pause/resume, 'q' quit) ", format_string="{}")], style="header"),  # type: ignore
            at_top=True,
        )

        # Banner
        bw = max(20, min(self._layout.cols - 2, 200))
        self._add_line("banner", Stat("banner", self.banner, format_string="{}", no_expand=True, display_width=bw))

        if self._layout.stacked:
            w = bw
            self._add_line("stage", Stat("stage", "idle", prefix="Stage: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("elapsed", Stat("elapsed", "00:00:00", prefix="Elapsed: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("eta", Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("files", Stat("files", (0, 0), prefix="Files: ", format_string="{}/{}", no_expand=True, display_width=w))
            self._add_line("videos", Stat("videos", 0, prefix="Videos: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("hashed", Stat("hashed", (0, 0), prefix="Hashed: ", format_string="{}/{}", no_expand=True, display_width=w))
            self._add_line("cache", Stat("cache_hits", 0, prefix="Cache hits: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("scan", Stat("scanned", "0 MiB", prefix="Scanned: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("g_hash", Stat("g_hash", 0, prefix="Hash groups: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("g_meta", Stat("g_meta", 0, prefix="Meta groups: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("g_phash", Stat("g_phash", 0, prefix="pHash groups: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("g_subset", Stat("g_subset", 0, prefix="Subset groups: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("dup_files", Stat("dup_files", 0, prefix="Dup files: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("bytes_rm", Stat("bytes_rm", "0 MiB", prefix="To remove: ", format_string="{}", no_expand=True, display_width=w))
            self._add_line("total_elapsed", Stat("tot_elapsed", "00:00:00", prefix="Total elapsed: ", format_string="{}", no_expand=True, display_width=w))
        else:
            self._add_line(
                "stage",
                Stat("stage", "idle", prefix="Stage: ", format_string="{}", no_expand=True, display_width=28),
                Stat("elapsed", "00:00:00", prefix="Elapsed: ", format_string="{}", no_expand=True, display_width=14),
                Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}", no_expand=True, display_width=14),
            )
            self._add_line(
                "files",
                Stat("files", (0, 0), prefix="Files: ", format_string="{}/{}", no_expand=True, display_width=22),
                Stat("videos", 0, prefix="Videos: ", format_string="{}", no_expand=True, display_width=18),
            )
            self._add_line(
                "hash",
                Stat("hashed", (0, 0), prefix="Hashed: ", format_string="{}/{}", no_expand=True, display_width=22),
                Stat("cache_hits", 0, prefix="Cache hits: ", format_string="{}", no_expand=True, display_width=18),
            )
            self._add_line("scan", Stat("scanned", "0 MiB", prefix="Scanned: ", format_string="{}", no_expand=True, display_width=22))
            self._add_line(
                "groups1",
                Stat("g_hash", 0, prefix="Hash groups: ", format_string="{}", no_expand=True, display_width=22),
                Stat("g_meta", 0, prefix="Meta groups: ", format_string="{}", no_expand=True, display_width=22),
            )
            self._add_line(
                "groups2",
                Stat("g_phash", 0, prefix="pHash groups: ", format_string="{}", no_expand=True, display_width=22),
                Stat("g_subset", 0, prefix="Subset groups: ", format_string="{}", no_expand=True, display_width=22),
            )
            self._add_line(
                "results",
                Stat("dup_files", 0, prefix="Dup files: ", format_string="{}", no_expand=True, display_width=22),
                Stat("bytes_rm", "0 MiB", prefix="To remove: ", format_string="{}", no_expand=True, display_width=22),
            )
            self._add_line("total", Stat("tot_elapsed", "00:00:00", prefix="Total elapsed: ", format_string="{}", no_expand=True, display_width=16))

        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()
        self.flush()

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
        eta_text = _fmt_hms(self._estimate_remaining())
        elapsed_stage = _fmt_hms(time.time() - self.stage_start_ts)
        elapsed_total = _fmt_hms(time.time() - self.start_ts)
        # stage row
        name = self.stage_name + (" [PAUSED]" if self._paused else "")
        self.dash.update_stat("stage", "stage", name)  # type: ignore
        self.dash.update_stat("stage", "eta", eta_text)  # type: ignore
        if self._layout.stacked:
            self.dash.update_stat("elapsed", "elapsed", elapsed_stage)  # type: ignore
            self.dash.update_stat("total_elapsed", "tot_elapsed", elapsed_total)  # type: ignore
        else:
            self.dash.update_stat("stage", "elapsed", elapsed_stage)  # type: ignore
            self.dash.update_stat("total", "tot_elapsed", elapsed_total)  # type: ignore

    def set_banner(self, text: str):
        self.banner = text
        if self.enable_dash and self.dash:
            self.dash.update_stat("banner", "banner", text)  # type: ignore

    def flush(self):
        # Also refresh stage name with [PAUSED] marker
        if self.enable_dash and self.dash:
            name = self.stage_name + (" [PAUSED]" if self._paused else "")
            self.dash.update_stat("stage", "stage", name)  # type: ignore

        if not self.enable_dash or not self.dash:
            return
        with self.lock:
            self.dash.update_stat("files", "files", (self.scanned_files, self.total_files))  # type: ignore
            if self._layout.stacked:
                self.dash.update_stat("videos", "videos", self.video_files)  # type: ignore
                self.dash.update_stat("hashed", "hashed", (self.hash_done, self.hash_total))  # type: ignore
                self.dash.update_stat("cache", "cache_hits", self.cache_hits)  # type: ignore
                self.dash.update_stat("scan", "scanned", f"{self.bytes_seen/1048576:.0f} MiB")  # type: ignore
                self.dash.update_stat("g_hash", "g_hash", self.groups_hash)  # type: ignore
                self.dash.update_stat("g_meta", "g_meta", self.groups_meta)  # type: ignore
                self.dash.update_stat("g_phash", "g_phash", self.groups_phash)  # type: ignore
                self.dash.update_stat("g_subset", "g_subset", self.groups_subset)  # type: ignore
                self.dash.update_stat("dup_files", "dup_files", self.losers_total)  # type: ignore
                self.dash.update_stat("bytes_rm", "bytes_rm", f"{self.bytes_to_remove/1048576:.0f} MiB")  # type: ignore
            else:
                self.dash.update_stat("files", "videos", self.video_files)  # type: ignore
                self.dash.update_stat("hash", "hashed", (self.hash_done, self.hash_total))  # type: ignore
                self.dash.update_stat("hash", "cache_hits", self.cache_hits)  # type: ignore
                self.dash.update_stat("scan", "scanned", f"{self.bytes_seen/1048576:.0f} MiB")  # type: ignore
                self.dash.update_stat("groups1", "g_hash", self.groups_hash)  # type: ignore
                self.dash.update_stat("groups1", "g_meta", self.groups_meta)  # type: ignore
                self.dash.update_stat("groups2", "g_phash", self.groups_phash)  # type: ignore
                self.dash.update_stat("groups2", "g_subset", self.groups_subset)  # type: ignore
                self.dash.update_stat("results", "dup_files", self.losers_total)  # type: ignore
                self.dash.update_stat("results", "bytes_rm", f"{self.bytes_to_remove/1048576:.0f} MiB")  # type: ignore

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
        self.flush()

    def set_results(self, dup_groups: int, losers_count: int, bytes_total: int):
        with self.lock:
            self.dup_groups_total = int(dup_groups)
            self.losers_total = int(losers_count)
            self.bytes_to_remove = int(bytes_total)
        self.flush()

    def stop(self):
        # stop threads and restore terminal
        self._stop_evt.set()
        if self._ticker:
            try:
                self._ticker.join(timeout=1.0)
            except Exception:
                pass
        if self._key_thread:
            try:
                self._key_thread.join(timeout=0.5)
            except Exception:
                pass
        if self.enable_dash and self.dash:
            try:
                self.dash.__exit__(None, None, None)  # type: ignore
            except Exception:
                pass
