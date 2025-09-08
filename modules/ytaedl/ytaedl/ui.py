#!/usr/bin/env python3
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Any, Optional, Set

# TermDash UI
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
        return cls(id=int(getattr(item, "id", -1)), url=str(getattr(item, "url", "")), title=title, source_file_stem=stem)

# ------------------------------- UI base ---------------------------------

class UIBase:
    def begin_scan(self, num_workers: int, total_files: int) -> None: ...
    def set_scan_slot(self, slot: int, label: str) -> None: ...
    def advance_scan(self, delta: int = 1) -> None: ...
    def end_scan(self) -> None: ...
    def handle_event(self, event: Any) -> None: ...
    def set_footer(self, text: str) -> None: ...
    def set_paused(self, paused: bool) -> None: ...
    def pump(self) -> None: ...
    def summary(self, stats: Dict[str, int], elapsed: float) -> None: ...

# ---------------------------- Console fallback ---------------------------

class SimpleUI(UIBase):
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

    Header:
      Time | Speed | MB
      URLs done/total | Already | Bad

    Per worker (4 lines):
      Worker N | Set <file-stem> | URLs i/total
      Spd <inst> | ETA hh:mm:ss | MB/Seg d/t
      ID <id> | <title>
      Already a | Bad b

    Scanning section:
      Scanning | Files done/total
      Scan i | <label> | <status>
    """

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

        # scanning state
        self._scan_total = 0
        self._scan_done = 0
        self._scan_active = False

        # worker-op queue (optional if workers enqueue ops)
        self._ops: "queue.Queue[tuple[str, tuple, dict]]" = queue.Queue()

        # line name registry
        self._line_names: Dict[int, Tuple[str, str, str, str]] = {}
        self._known_lines: Set[str] = set()

        self._setup()

    # ------------- context manager -------------

    def __enter__(self):
        self.dash.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dash.__exit__(exc_type, exc_val, exc_tb)

    # ------------- helpers -------------

    def _add_line(self, name: str, line: Line):
        self.dash.add_line(name, line)
        self._known_lines.add(name)

    def _has_line(self, name: str) -> bool:
        return name in self._known_lines

    # ------------- layout -------------

    def _setup(self):
        # Header lines (clean prefixes – matches your old layout)
        self._add_line(
            "overall1",
            Line(
                "overall1",
                stats=[
                    Stat("time", "00:00:00", prefix="Time "),
                    Stat("speed", 0.0, prefix=" | Speed ", format_string="{:.1f}"),
                    Stat("mbytes", 0.0, prefix=" | MB ", format_string="{:.1f}"),
                ],
                style="header",
            ),
        )
        self._add_line(
            "overall2",
            Line(
                "overall2",
                stats=[
                    Stat("urls", (0, self.total_urls), prefix="URLs ", format_string="{}/{}"),
                    Stat("already", 0, prefix=" | Already "),
                    Stat("bad", 0, prefix=" | Bad "),
                ],
                style="header",
            ),
        )
        self.dash.add_separator()

        # Per-worker blocks (4 lines each)
        for i in range(self.num_workers):
            w = i + 1
            ln_main = f"w{w}:main"
            ln_s1 = f"w{w}:s1"
            ln_s2 = f"w{w}:s2"
            ln_s3 = f"w{w}:s3"
            self._add_line(
                ln_main,
                Line(
                    ln_main,
                    stats=[
                        Stat("w", f"Worker {w}", prefix="", no_expand=True, display_width=10),
                        Stat("set", "", prefix=" | Set ", no_expand=True, display_width=18),
                        Stat("urls", (0, 0), prefix=" | URLs ", format_string="{}/{}", no_expand=True, display_width=9),
                    ],
                ),
            )
            self._add_line(
                ln_s1,
                Line(
                    ln_s1,
                    stats=[
                        Stat("mbps", 0.0, prefix="Spd ", format_string="{:.1f}"),
                        Stat("eta", "--:--:--", prefix=" | ETA "),
                        Stat("mb", (0.0, 0.0), prefix=" | MB/Seg ", format_string="{:.1f}/{:.1f}"),
                    ],
                ),
            )
            self._add_line(
                ln_s2,
                Line(
                    ln_s2,
                    stats=[
                        Stat("id", "", prefix="ID ", no_expand=True, display_width=10),
                        Stat("title", "", prefix=" | ", no_expand=True, display_width=40),
                    ],
                ),
            )
            self._add_line(
                ln_s3,
                Line(
                    ln_s3,
                    stats=[Stat("already", 0, prefix="Already "), Stat("bad", 0, prefix=" | Bad ")],
                ),
            )
            self.dash.add_separator()
            self._line_names[i] = (ln_main, ln_s1, ln_s2, ln_s3)

        # Status/footer
        self._add_line(
            "status",
            Line("status", stats=[Stat("msg", "Keys: z pause/resume | q confirm quit | Q force quit", prefix="")]),
        )

    # ------------- scanning UI -------------

    def begin_scan(self, num_workers: int, total_files: int):
        self._scan_total = max(0, int(total_files))
        self._scan_done = 0
        self._scan_active = True

        if not self._has_line("scan:hdr"):
            self.dash.add_separator()
            self._add_line(
                "scan:hdr",
                Line(
                    "scan:hdr",
                    stats=[
                        Stat("scan", "Scanning", prefix=""),
                        Stat("files", (0, self._scan_total), prefix=" | Files ", format_string="{}/{}"),
                    ],
                ),
            )
            for i in range(self.num_workers):
                name = f"scan:{i}"
                self._add_line(
                    name,
                    Line(
                        name,
                        stats=[
                            Stat("slot", f"Scan {i+1}", prefix=""),
                            Stat("label", "", prefix=" | "),
                            Stat("status", "pending", prefix=" | "),
                        ],
                    ),
                )

    def set_scan_slot(self, slot: int, label: str):
        if not self._scan_active:
            return
        name = f"scan:{int(slot)}"
        if not self._has_line(name):
            return
        self.dash.update_stat(name, "label", str(label))
        self.dash.update_stat(name, "status", "working")

    def advance_scan(self, delta: int = 1):
        if not self._scan_active:
            return
        self._scan_done += int(delta)
        self.dash.update_stat("scan:hdr", "files", (self._scan_done, self._scan_total))

    def end_scan(self):
        if not self._scan_active:
            return
        self._scan_active = False
        for i in range(self.num_workers):
            nm = f"scan:{i}"
            if self._has_line(nm):
                self.dash.update_stat(nm, "status", "done")

    # ------------- events -------------

    def _slot_for_item(self, item_id: int) -> int:
        return int(item_id) % self.num_workers if self.num_workers else 0

    def handle_event(self, event: Any):
        etype = type(event).__name__

        if etype == "StartEvent":
            item = DownloadItemRef.from_event(event)
            slot = self._slot_for_item(item.id)
            ln_main, ln_s1, ln_s2, _ = self._line_names[slot]

            self.urls_started += 1
            cur, total = self.dash.read_stat(ln_main, "urls") or (0, 0)
            try:
                cur = int(cur)
                total = int(total)
            except Exception:
                cur, total = 0, 0

            set_total = getattr(getattr(event, "item", None), "total_in_set", None)
            if isinstance(set_total, int) and set_total >= 0:
                total = set_total

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
            speed = float(getattr(event, "speed_Bps", 0.0)) / (1024.0 * 1024.0)
            done = float(getattr(event, "downloaded_bytes", 0.0)) / (1024.0 * 1024.0)
            total = float(getattr(event, "total_bytes", 0.0)) / (1024.0 * 1024.0)
            eta = getattr(event, "eta_s", None)
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

    # ------------- status/footer -------------

    def set_footer(self, text: str):
        try:
            self.dash.update_stat("status", "msg", text or "")
        except Exception:
            pass

    def set_paused(self, paused: bool):
        self.set_footer(("⏸ paused" if paused else "▶ running") + " | z pause/resume | q confirm quit | Q force quit")

    # ------------- pump/summary -------------

    def pump(self):
        self._header_tick()
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

    # ------------- helpers -------------

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
    if TERMDASH_AVAILABLE:
        try:
            return TermdashUI(num_workers=num_workers, total_urls=total_urls)
        except Exception as e:
            print(f"[UI fallback] {e}")
    return SimpleUI(num_workers=num_workers, total_urls=total_urls)
