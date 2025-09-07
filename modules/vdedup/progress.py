#!/usr/bin/env python3
from __future__ import annotations
import shutil
import threading
import time
from typing import Optional

# Optional TermDash module (user-provided)
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


def _bytes_to_mib(n: int) -> float:
    try:
        return float(n) / (1024.0 * 1024.0)
    except Exception:
        return 0.0


class ProgressReporter:
    """Thread-safe counters + optional TermDash updates, with per-stage ETA and Elapsed."""
    def __init__(self, enable_dash: bool, *, refresh_rate: float = 0.2, banner: str = "", stacked_ui: Optional[bool] = None):
        self.enable_dash = enable_dash and TERMDASH_AVAILABLE
        self.refresh_rate = max(0.05, float(refresh_rate))
        self.lock = threading.Lock()
        self.start_ts = time.time()
        self.banner = banner
        self._stacked_pref = stacked_ui

        # Counters
        self.total_files = 0
        self.scanned_files = 0
        self.video_files = 0
        self.bytes_seen = 0

        self.hash_total = 0
        self.hash_done = 0
        self.cache_hits = 0

        self.groups_hash = 0
        self.groups_meta = 0
        self.groups_phash = 0
        self.groups_subset = 0

        self.dup_groups_total = 0
        self.losers_total = 0
        self.bytes_to_remove = 0

        self.stage_name = "idle"
        self.stage_total = 0
        self.stage_done = 0
        self.stage_start_ts = time.time()
        self._ema_rate = 0.0

        self.dash: Optional[TermDash] = None  # type: ignore
        self._ticker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        self._stacked = False
        self._term_cols = 120

    def _term_width(self) -> int:
        try:
            return shutil.get_terminal_size(fallback=(120, 30)).columns
        except Exception:
            return 120

    def _add_header(self):
        self._line_title = Line("title", stats=[Stat("title", "Video Deduper — Live", format_string="{}")], style="header")
        self.dash.__enter__()
        self.dash.add_line("title", self._line_title, at_top=True)

    def _add_line(self, key: str, stats):
        self.dash.add_line(key, Line(key, stats=stats))

    def start(self):
        if not self.enable_dash:
            return

        self._term_cols = self._term_width()
        self._stacked = (self._stacked_pref if self._stacked_pref is not None else (self._term_cols < 120))

        self.dash = TermDash(
            refresh_rate=self.refresh_rate,
            enable_separators=False,
            reserve_extra_rows=2,
            align_columns=True,
            max_col_width=None,
        )

        if self._stacked:
            w = max(20, min(self._term_cols - 2, 200))
            self._add_header()
            self._add_line("banner", [Stat("banner", self.banner, format_string="{}", no_expand=True, display_width=w)])
            self._add_line("stage", [Stat("stage", "scanning", prefix="Stage: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("elapsed", [Stat("elapsed", "00:00:00", prefix="Elapsed: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("eta", [Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("files", [Stat("files", (0, 0), prefix="Files: ", format_string="{}/{}", no_expand=True, display_width=w)])
            self._add_line("videos", [Stat("videos", 0, prefix="Videos: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("hashed", [Stat("hashed", (0, 0), prefix="Hashed: ", format_string="{}/{}", no_expand=True, display_width=w)])
            self._add_line("cache", [Stat("cache_hits", 0, prefix="Cache hits: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("scan", [Stat("scanned", "0 MiB", prefix="Scanned: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("g_hash", [Stat("g_hash", 0, prefix="Hash groups: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("g_meta", [Stat("g_meta", 0, prefix="Meta groups: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("g_phash", [Stat("g_phash", 0, prefix="pHash groups: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("g_subset", [Stat("g_subset", 0, prefix="Subset groups: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("dup_files", [Stat("dup_files", 0, prefix="Dup files: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("bytes_rm", [Stat("bytes_rm", "0 MiB", prefix="To remove: ", format_string="{}", no_expand=True, display_width=w)])
            self._add_line("total_elapsed", [Stat("tot_elapsed", "00:00:00", prefix="Total elapsed: ", format_string="{}", no_expand=True, display_width=w)])
        else:
            self._add_header()
            self._add_line("banner", [Stat("banner", self.banner, format_string="{}", no_expand=True, display_width=120)])
            self._add_line("stage", [
                Stat("stage", "scanning", prefix="Stage: ", format_string="{}", no_expand=True, display_width=22),
                Stat("elapsed", "00:00:00", prefix="Elapsed: ", format_string="{}", no_expand=True, display_width=14),
                Stat("eta", "--:--:--", prefix="ETA: ", format_string="{}", no_expand=True, display_width=14),
            ])
            self._add_line("files", [
                Stat("files", (0, 0), prefix="Files: ", format_string="{}/{}", no_expand=True, display_width=22),
                Stat("videos", 0, prefix="Videos: ", format_string="{}", no_expand=True, display_width=18),
            ])
            self._add_line("hash", [
                Stat("hashed", (0, 0), prefix="Hashed: ", format_string="{}/{}", no_expand=True, display_width=22),
                Stat("cache_hits", 0, prefix="Cache hits: ", format_string="{}", no_expand=True, display_width=18),
            ])
            self._add_line("scan", [Stat("scanned", "0 MiB", prefix="Scanned: ", format_string="{}", no_expand=True, display_width=22)])
            self._add_line("groups1", [
                Stat("g_hash", 0, prefix="Hash groups: ", format_string="{}", no_expand=True, display_width=22),
                Stat("g_meta", 0, prefix="Meta groups: ", format_string="{}", no_expand=True, display_width=22),
            ])
            self._add_line("groups2", [
                Stat("g_phash", 0, prefix="pHash groups: ", format_string="{}", no_expand=True, display_width=22),
                Stat("g_subset", 0, prefix="Subset groups: ", format_string="{}", no_expand=True, display_width=22),
            ])
            self._add_line("results", [
                Stat("dup_files", 0, prefix="Dup files: ", format_string="{}", no_expand=True, display_width=22),
                Stat("bytes_rm", "0 MiB", prefix="To remove: ", format_string="{}", no_expand=True, display_width=22),
            ])
            self._add_line("total", [Stat("tot_elapsed", "00:00:00", prefix="Total elapsed: ", format_string="{}", no_expand=True, display_width=16)])

        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()
        self.flush()

    def stop(self):
        if not self.enable_dash:
            return
        self._stop_evt.set()
        if self._ticker:
            self._ticker.join(timeout=1)
        if self.dash:
            try:
                self.dash.__exit__(None, None, None)
            except Exception:
                pass

    def _tick_loop(self):
        while not self._stop_evt.is_set():
            self._update_eta()
            time.sleep(self.refresh_rate)

    def _estimate_remaining(self) -> Optional[float]:
        if self.stage_total <= 0:
            return None
        remaining = self.stage_total - self.stage_done
        if remaining <= 0:
            return 0.0
        elapsed = max(1e-6, time.time() - self.stage_start_ts)
        inst = self.stage_done / elapsed if self.stage_done > 0 else 0.0
        alpha = 0.15
        self._ema_rate = inst if getattr(self, "_ema_rate", 0.0) <= 0 else (alpha * inst + (1 - alpha) * getattr(self, "_ema_rate", 0.0))
        rate = self._ema_rate
        return (remaining / rate) if rate > 0 else None

    def _update_eta(self):
        if not self.enable_dash or not self.dash:
            return
        eta_text = _fmt_hms(self._estimate_remaining())
        elapsed_stage = _fmt_hms(time.time() - self.stage_start_ts)
        elapsed_total = _fmt_hms(time.time() - self.start_ts)
        self.dash.update_stat("stage", "eta", eta_text)
        self.dash.update_stat("stage" if not self._stacked else "elapsed", "elapsed", elapsed_stage)
        self.dash.update_stat("total" if not self._stacked else "total_elapsed", "tot_elapsed", elapsed_total)

    def set_banner(self, text: str):
        self.banner = text
        if self.enable_dash and self.dash:
            self.dash.update_stat("banner", "banner", text)

    def flush(self):
        if not self.enable_dash or not self.dash:
            return
        with self.lock:
            self.dash.update_stat("stage", "stage", self.stage_name)
            self.dash.update_stat("files", "files", (self.scanned_files, self.total_files))
            if self._stacked:
                self.dash.update_stat("videos", "videos", self.video_files)
                self.dash.update_stat("hashed", "hashed", (self.hash_done, self.hash_total))
                self.dash.update_stat("cache", "cache_hits", self.cache_hits)
                self.dash.update_stat("scan", "scanned", f"{_bytes_to_mib(self.bytes_seen):.0f} MiB")
                self.dash.update_stat("g_hash", "g_hash", self.groups_hash)
                self.dash.update_stat("g_meta", "g_meta", self.groups_meta)
                self.dash.update_stat("g_phash", "g_phash", self.groups_phash)
                self.dash.update_stat("g_subset", "g_subset", self.groups_subset)
                self.dash.update_stat("dup_files", "dup_files", self.losers_total)
                self.dash.update_stat("bytes_rm", "bytes_rm", f"{_bytes_to_mib(self.bytes_to_remove):.0f} MiB")
            else:
                self.dash.update_stat("files", "videos", self.video_files)
                self.dash.update_stat("hash", "hashed", (self.hash_done, self.hash_total))
                self.dash.update_stat("hash", "cache_hits", self.cache_hits)
                self.dash.update_stat("scan", "scanned", f"{_bytes_to_mib(self.bytes_seen):.0f} MiB")
                self.dash.update_stat("groups1", "g_hash", self.groups_hash)
                self.dash.update_stat("groups1", "g_meta", self.groups_meta)
                self.dash.update_stat("groups2", "g_phash", self.groups_phash)
                self.dash.update_stat("groups2", "g_subset", self.groups_subset)
                self.dash.update_stat("results", "dup_files", self.losers_total)
                self.dash.update_stat("results", "bytes_rm", f"{_bytes_to_mib(self.bytes_to_remove):.0f} MiB")

    # Stage helpers
    def start_stage(self, name: str, total: int):
        with self.lock:
            self.stage_name = name
            self.stage_total = max(0, int(total))
            self.stage_done = 0
            self.stage_start_ts = time.time()
            self._ema_rate = 0.0
        self.flush()

    def bump_stage(self, n: int = 1):
        with self.lock:
            self.stage_done += int(n)
