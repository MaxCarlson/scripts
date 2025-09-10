#!/usr/bin/env python3
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

# TermDash (required for TermdashUI)
try:
    from termdash import TermDash, Line, Stat  # type: ignore
    TERMDASH_AVAILABLE = True
except Exception:
    TERMDASH_AVAILABLE = False


# ------------------------------- base types -------------------------------

@dataclass(frozen=True)
class DownloadItemRef:
    """Duck-typed view into an item; keeps UI decoupled from downloader internals."""
    id: int
    url: str
    title: Optional[str] = None
    source_file_stem: str = ""

    @classmethod
    def from_event(cls, ev: Any) -> "DownloadItemRef":
        item = getattr(ev, "item", None)
        if item is None:
            return cls(id=-1, url="")
        stem = ""
        try:
            src = getattr(item, "source", None)
            if src and getattr(src, "file", None):
                stem = Path(src.file).stem
        except Exception:
            stem = ""
        title = getattr(item, "title", None)
        return cls(
            id=int(getattr(item, "id", -1)),
            url=str(getattr(item, "url", "")),
            title=title,
            source_file_stem=stem,
        )


# ------------------------------- UI base ---------------------------------

class UIBase:
    def begin_scan(self, num_workers: int, total_files: int) -> None: ...
    def set_scan_slot(self, slot: int, label: str) -> None: ...
    def advance_scan(self, delta: int = 1) -> None: ...
    def end_scan(self) -> None: ...
    
    def reset_worker_stats(self, slot: int) -> None: ...
    def handle_event(self, event: Any) -> None: ...
    def set_footer(self, text: str) -> None: ...
    def set_paused(self, paused: bool) -> None: ...
    def pump(self) -> None: ...
    def summary(self, stats: Dict[str, int], elapsed: float) -> None: ...


# ---------------------------- Console fallback ---------------------------

class SimpleUI(UIBase):
    """Very simple console output; used when TermDash isn't available."""

    def __init__(self, num_workers: int, total_urls: int):
        self._completed = 0
        self._scan_total = 0
        self._scan_done = 0
        self._num_workers = int(num_workers)
        self._total_urls = int(total_urls)

    def begin_scan(self, num_workers: int, total_files: int):
        self._scan_total = int(total_files)
        self._scan_done = 0
        print(f"[SCAN] Starting scan: {total_files} file(s), {num_workers} worker(s)")

    def set_scan_slot(self, slot: int, label: str):
        print(f"[SCAN] Worker {slot+1}: {label}")

    def advance_scan(self, delta: int = 1):
        self._scan_done += int(delta)
        print(f"[SCAN] Progress: {self._scan_done}/{self._scan_total}")

    def end_scan(self):
        print(f"[SCAN] Completed: {self._scan_done}/{self._scan_total}")
        
    def reset_worker_stats(self, slot: int) -> None:
        print(f"[UI] Resetting stats for worker {slot+1}")

    def handle_event(self, event: Any):
        etype = type(event).__name__
        if etype == "StartEvent":
            item = DownloadItemRef.from_event(event)
            print(f"[START] {item.id}: {item.url}")
        elif etype == "FinishEvent":
            res = getattr(event, "result", None)
            status = getattr(getattr(res, "status", None), "value", "").upper()
            item = DownloadItemRef.from_event(event)
            print(f"[FINISH] {item.id}: {status}")
            self._completed += 1

    def set_footer(self, text: str):
        if text:
            print(f"[STATUS] {text}")

    def set_paused(self, paused: bool):
        print(f"[PAUSE] {'ON' if paused else 'OFF'}")

    def pump(self):
        ...

    def summary(self, stats: Dict[str, int], elapsed: float):
        print(f"Completed: {self._completed} in {elapsed:.2f}s")


# ------------------------------- TermDash UI ------------------------------

class TermdashUI(UIBase):
    """
    Live dashboard using TermDash.
    """

    _DEFAULT_SCAN_LOG = Path("ytaedl-scan-results.tsv")

    def __init__(self, num_workers: int, total_urls: int):
        if not TERMDASH_AVAILABLE:
            raise ImportError("TermDash is not installed/available.")

        self.num_workers = max(1, int(num_workers))
        self.total_urls = max(0, int(total_urls))
        self.dash = TermDash(
            refresh_rate=0.05,
            status_line=False,
            align_columns=True,
            column_sep="|",
            min_col_pad=2,
            max_col_width=40,
            enable_separators=True,
            separator_style="rule",
            reserve_extra_rows=8,
        )

        self.start_time = time.monotonic()
        self.bytes_downloaded = 0.0
        self.urls_started = 0
        self.already = 0
        self.bad = 0

        self._scan_total_files = 0
        self._scan_done_files = 0
        self._scan_active = False
        self._scan_start_time = 0.0
        self._scan_urls_total = 0
        self._scan_urls_already = 0
        self._scan_urls_bad = 0

        self._scan_log_path: Path = self._DEFAULT_SCAN_LOG
        self._scan_log_lock = threading.Lock()
        self._ops: "queue.Queue[tuple[str, tuple, dict]]" = queue.Queue()

        self._line_names: Dict[int, Tuple[str, str, str, str]] = {}
        self._known_lines: Set[str] = set()

        self._setup()

    def __enter__(self):
        self.dash.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dash.__exit__(exc_type, exc_val, exc_tb)

    def _add_line(self, name: str, line: Line, *, at_top: bool = False):
        # Keep your 'at_top' feature, but be compatible with test FakeDash
        try:
            self.dash.add_line(name, line, at_top=at_top)
        except TypeError:
            # Tests' FakeDash doesn't accept 'at_top'
            self.dash.add_line(name, line)
        self._known_lines.add(name)

    def _has_line(self, name: str) -> bool:
        return name in self._known_lines

    def _setup(self):
        from termdash import Line, Stat  # local import for type checkers

        self._add_line(
            "banner1",
            Line( "banner1", stats=[
                    Stat("sb_urls", (0, 0), prefix="Scanned ", format_string="{}/{}"),
                    Stat("sb_already", 0, prefix=" Already "),
                    Stat("sb_bad", 0, prefix=" Bad "),
                    Stat("sb_speed", "0.0", prefix=" URLs/s "),
                ], style="header",
            ), at_top=True,
        )
        self._add_line(
            "banner2",
            Line( "banner2", stats=[Stat("sb_hint", "Scanning phase statistics", prefix="")], style="header"), at_top=True,
        )
        self._add_line(
            "overall1",
            Line("overall1", stats=[
                    Stat("time", "00:00:00", prefix="Time "),
                    Stat("speed", 0.0, prefix=" Speed MB/s ", format_string="{:.1f}"),
                    Stat("mbytes", 0.0, prefix=" MB ", format_string="{:.1f}"),
                ], style="header",
            ),
        )
        self._add_line(
            "overall2",
            Line("overall2", stats=[
                    Stat("urls", (0, self.total_urls), prefix="URLs ", format_string="{}/{}"),
                    Stat("already", 0, prefix=" Already "),
                    Stat("bad", 0, prefix=" Bad "),
                ], style="header",
            ),
        )
        self.dash.add_separator()

        for i in range(self.num_workers):
            w = i + 1
            ln_main, ln_s1, ln_s2, ln_s3 = f"w{w}:main", f"w{w}:s1", f"w{w}:s2", f"w{w}:s3"
            self._add_line(ln_main, Line(ln_main, stats=[
                        Stat("w", f"Worker {w}", prefix="", no_expand=True, display_width=10),
                        Stat("set", "", prefix=" Set ", no_expand=True, display_width=18),
                        Stat("urls", (0, 0), prefix=" URLs ", format_string="{}/{}", no_expand=True, display_width=9),
                    ],
                ),
            )
            self._add_line(ln_s1, Line(ln_s1, stats=[
                        Stat("mbps", 0.0, prefix="MB/s ", format_string="{:.1f}"),
                        Stat("eta", "--:--:--", prefix=" ETA "),
                        Stat("mb", (0.0, 0.0), prefix=" MB ", format_string="{:.1f}/{:.1f}"),
                    ],
                ),
            )
            self._add_line(ln_s2, Line(ln_s2, stats=[
                        Stat("id", "", prefix="ID ", no_expand=True, display_width=12),
                        Stat("title", "", prefix="", no_expand=True, display_width=40),
                    ],
                ),
            )
            self._add_line(ln_s3, Line(ln_s3, stats=[
                        Stat("already", 0, prefix="Already "),
                        Stat("bad", 0, prefix=" Bad "),
                    ],
                ),
            )
            self.dash.add_separator()
            self._line_names[i] = (ln_main, ln_s1, ln_s2, ln_s3)

        self._add_line(
            "status",
            Line("status", stats=[Stat("msg", "▶ running  •  z pause/resume  •  q confirm quit  •  Q force quit", prefix="")]),
        )

    def set_scan_log_path(self, path: str | Path) -> None:
        self._scan_log_path = Path(path)

    def begin_scan(self, num_workers: int, total_files: int):
        self._scan_total_files = max(0, int(total_files))
        self._scan_done_files = 0
        self._scan_active = True
        self._scan_start_time = time.monotonic()
        self._scan_urls_total = 0
        self._scan_urls_already = 0
        self._scan_urls_bad = 0
        self._update_scan_banner()

        if not self._has_line("scan:hdr"):
            self.dash.add_separator()
            self._add_line("scan:hdr", Line("scan:hdr", stats=[
                        Stat("label", "Scanning", prefix=""),
                        Stat("files", (0, self._scan_total_files), prefix=" Files ", format_string="{}/{}"),
                    ],
                ),
            )
            for i in range(self.num_workers):
                name = f"scan:{i}"
                self._add_line(name, Line(name, stats=[
                            Stat("slot", f"Scan {i+1}", prefix=""),
                            Stat("label", "", prefix=" "),
                            Stat("status", "pending", prefix=" "),
                        ],
                    ),
                )

    def set_scan_slot(self, slot: int, label: str):
        if not self._scan_active:
            try:
                name = f"scan:{int(slot)}"
                if self._has_line(name):
                    self.dash.update_stat(name, "label", str(label))
                    self.dash.update_stat(name, "status", "downloading")
                else:
                    ln_main, _, _, _ = self._line_names[slot]
                    self.dash.update_stat(ln_main, "set", label)
            except:
                pass
            return
            
        name = f"scan:{int(slot)}"
        if not self._has_line(name):
            return
        self.dash.update_stat(name, "label", str(label))
        self.dash.update_stat(name, "status", "working")

    def advance_scan(self, delta: int = 1):
        if not self._scan_active:
            return
        self._scan_done_files += int(delta)
        self.dash.update_stat("scan:hdr", "files", (self._scan_done_files, self._scan_total_files))

    def scan_file_done(self, urlfile: str | Path, total: int, downloaded: int, bad: int) -> None:
        total = max(0, int(total))
        downloaded = max(0, int(downloaded))
        bad = max(0, int(bad))
        ready = max(0, total - downloaded - bad)

        self._scan_urls_total += total
        self._scan_urls_already += downloaded
        self._scan_urls_bad += bad
        self._update_scan_banner()

        with self._scan_log_lock:
            path = self._scan_log_path
            new_file = not path.exists()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            line = f"{Path(urlfile)}\t{total}\t{downloaded}\t{bad}\t{ready}\n"
            with path.open("a", encoding="utf-8", newline="") as f:
                if new_file:
                    f.write("urlfile\ttotal\talready\tbad\tready\n")
                f.write(line)

    def _update_scan_banner(self):
        if not self._has_line("banner1"):
            return
        elapsed = max(1e-6, (time.monotonic() - self._scan_start_time) if self._scan_start_time else 0.0)
        speed = self._scan_urls_total / elapsed
        self.dash.update_stat("banner1", "sb_urls", (self._scan_urls_total, self._scan_urls_total))
        self.dash.update_stat("banner1", "sb_already", self._scan_urls_already)
        self.dash.update_stat("banner1", "sb_bad", self._scan_urls_bad)
        self.dash.update_stat("banner1", "sb_speed", f"{speed:.1f}")

    def end_scan(self):
        if not self._scan_active:
            return
        self._scan_active = False
        for i in range(self.num_workers):
            nm = f"scan:{i}"
            if self._has_line(nm):
                self.dash.update_stat(nm, "status", "done")

    def _slot_for_item(self, item_id: int) -> int:
        return int(item_id) % self.num_workers if self.num_workers else 0
    
    def reset_worker_stats(self, slot: int):
        if slot not in self._line_names:
            return
        ln_main, ln_s1, ln_s2, ln_s3 = self._line_names[slot]
        self.dash.update_stat(ln_main, "set", "")
        self.dash.update_stat(ln_main, "urls", (0, 0))
        self.dash.update_stat(ln_s1, "mbps", 0.0)
        self.dash.update_stat(ln_s1, "eta", "--:--:--")
        self.dash.update_stat(ln_s1, "mb", (0.0, 0.0))
        self.dash.update_stat(ln_s2, "id", "")
        self.dash.update_stat(ln_s2, "title", "")
        self.dash.update_stat(ln_s3, "already", 0)
        self.dash.update_stat(ln_s3, "bad", 0)

    def handle_event(self, event: Any):
        etype = type(event).__name__

        if etype == "StartEvent":
            item = DownloadItemRef.from_event(event)
            slot = self._slot_for_item(item.id)
            ln_main, ln_s1, ln_s2, _ = self._line_names[slot]

            self.urls_started += 1
            cur_tuple = self.dash.read_stat(ln_main, "urls")
            cur = cur_tuple[0] if isinstance(cur_tuple, tuple) else 0

            set_total = getattr(getattr(event, "item", None), "total_in_set", None)
            total = set_total if isinstance(set_total, int) and set_total >= 0 else 0

            self.dash.update_stat(ln_main, "set", item.source_file_stem)
            self.dash.update_stat(ln_main, "urls", (cur + 1, total or 0))

            self.dash.update_stat(ln_s1, "mbps", 0.0)
            self.dash.update_stat(ln_s1, "eta", "--:--:--")
            self.dash.update_stat(ln_s1, "mb", (0.0, 0.0))

            self.dash.update_stat(ln_s2, "id", str(item.id))
            if item.title:
                self.dash.update_stat(ln_s2, "title", item.title)

        elif etype == "ProgressEvent":
            item = DownloadItemRef.from_event(event)
            slot = self._slot_for_item(item.id)
            _, ln_s1, _, _ = self._line_names[slot]
            speed = float(getattr(event, "speed_bps", 0.0)) / (1024.0 * 1024.0)
            done = float(getattr(event, "downloaded_bytes", 0.0)) / (1024.0 * 1024.0)
            total = float(getattr(event, "total_bytes", 0.0)) / (1024.0 * 1024.0)
            eta = getattr(event, "eta_seconds", None)
            self.dash.update_stat(ln_s1, "mbps", speed)
            self.dash.update_stat(ln_s1, "mb", (done, total))
            self.dash.update_stat(ln_s1, "eta", self._fmt_eta(eta))

        elif etype == "FinishEvent":
            res = getattr(event, "result", None)
            status = getattr(getattr(res, "status", None), "value", "").lower()
            item = DownloadItemRef.from_event(event)
            slot = self._slot_for_item(item.id)
            _, _, _, ln_s3 = self._line_names[slot]

            if status in ("completed", "success", "ok"):
                self.bytes_downloaded += float(getattr(res, "bytes_downloaded", 0.0))
            elif status in ("already_exists", "already"):
                self.already += 1
                self.dash.update_stat(ln_s3, "already", (self.dash.read_stat(ln_s3, "already") or 0) + 1)
            else:
                self.bad += 1
                self.dash.update_stat(ln_s3, "bad", (self.dash.read_stat(ln_s3, "bad") or 0) + 1)

    def set_footer(self, text: str):
        safe = (text or "").replace("|", "•")
        try:
            self.dash.update_stat("status", "msg", safe)
        except Exception:
            pass

    def set_paused(self, paused: bool):
        msg = "⏸ paused" if paused else "▶ running"
        self.set_footer(f"{msg}  •  z pause/resume  •  q confirm quit  •  Q force quit")

    def pump(self):
        self._header_tick()
        if self._scan_active:
            self._update_scan_banner()
        try:
            while True:
                op, args, kwargs = self._ops.get_nowait()
                getattr(self, op)(*args, **kwargs)
        except queue.Empty:
            pass

    def summary(self, stats: Dict[str, int], elapsed: float):
        self.dash.update_stat("overall2", "urls", (stats.get("completed", 0), self.total_urls))
        self.dash.update_stat("overall2", "already", stats.get("already", self.already))
        self.dash.update_stat("overall2", "bad", stats.get("bad", self.bad))
        self._header_tick()

    def _header_tick(self):
        from termdash.utils import fmt_hms, bytes_to_mib

        elapsed = time.monotonic() - self.start_time
        speed_sum = 0.0
        for i in range(self.num_workers):
            _, s1, _, _ = self._line_names[i]
            try:
                v = float(self.dash.read_stat(s1, "mbps") or 0.0)
                speed_sum += v
            except Exception:
                pass

        self.dash.update_stat("overall1", "time", fmt_hms(elapsed))
        self.dash.update_stat("overall1", "speed", speed_sum)
        self.dash.update_stat("overall1", "mbytes", bytes_to_mib(self.bytes_downloaded))

        done = min(self.urls_started, self.total_urls) if self.total_urls else self.urls_started
        self.dash.update_stat("overall2", "urls", (done, self.total_urls))
        self.dash.update_stat("overall2", "already", self.already)
        self.dash.update_stat("overall2", "bad", self.bad)

    @staticmethod
    def _fmt_eta(eta_s: Optional[float]) -> str:
        if eta_s is None or eta_s < 0:
            return "--:--:--"
        h = int(eta_s // 3600)
        m = int((eta_s % 3600) // 60)
        s = int(eta_s % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

# ------------------------------ factory -------------------------------

def make_ui(num_workers: int, total_urls: int) -> UIBase:
    """Helper for callers that want a best-available UI."""
    if TERMDASH_AVAILABLE:
        try:
            return TermdashUI(num_workers=num_workers, total_urls=total_urls)
        except Exception as e:
            print(f"[UI fallback] {e}")
    return SimpleUI(num_workers=num_workers, total_urls=total_urls)
