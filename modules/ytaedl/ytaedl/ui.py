"""UI layer with TermDash live dashboard and simple fallback.

This version is thread-safe: worker threads enqueue UI ops,
and the main thread applies them via `pump()`.
"""
from __future__ import annotations

import queue
import time
from abc import ABC, abstractmethod
from typing import Dict, Tuple

from .models import (
    DownloadEvent,
    FinishEvent,
    ProgressEvent,
    StartEvent,
    MetaEvent,
    DestinationEvent,
    AlreadyEvent,
    DownloadStatus,
)

try:
    from termdash import TermDash
    from termdash.components import Line, Stat
    from termdash.utils import fmt_hms, bytes_to_mib
    TERMDASH_AVAILABLE = True
except Exception:
    TERMDASH_AVAILABLE = False


class UIBase(ABC):
    @abstractmethod
    def __enter__(self): ...
    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...
    @abstractmethod
    def handle_event(self, event: DownloadEvent): ...
    @abstractmethod
    def summary(self, stats: Dict[str, int], elapsed: float): ...

    # Scan-phase hooks
    def begin_scan(self, num_workers: int, total_files: int): ...
    def set_scan_slot(self, slot: int, label: str): ...
    def advance_scan(self, delta: int = 1): ...
    def end_scan(self): ...

    # Main-thread pump (no-op for SimpleUI)
    def pump(self): ...

    # Footer status (pause/quit prompts)
    def set_footer(self, text: str): ...
    def set_paused(self, paused: bool): ...


class SimpleUI(UIBase):
    def __init__(self) -> None:
        self._start = time.monotonic()
        self._completed = 0
        self._scan_total = 0
        self._scan_done = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ...

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

    def handle_event(self, event: DownloadEvent):
        if isinstance(event, StartEvent):
            print(f"[START] {event.item.id}: {event.item.url}")
        elif isinstance(event, FinishEvent):
            print(f"[FINISH] {event.item.id}: {event.result.status.value.upper()}")
            self._completed += 1

    def set_footer(self, text: str):
        if text:
            print(f"[STATUS] {text}")

    def set_paused(self, paused: bool):
        print(f"[PAUSE] {'ON' if paused else 'OFF'}")

    def pump(self):
        # nothing to do for console mode
        ...

    def summary(self, stats: Dict[str, int], elapsed: float):
        print(f"Completed: {self._completed} in {elapsed:.2f}s")


class TermdashUI(UIBase):
    """Live dashboard using TermDash, updated from main thread via a queue."""

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

        # scan state
        self._scan_total = 0
        self._scan_done = 0
        self._scan_lines: Dict[int, str] = {}

        # op queue for thread-safe UI updates
        self._ops: "queue.Queue[tuple]" = queue.Queue()
        self._setup()

    def __enter__(self):
        self.dash.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dash.__exit__(exc_type, exc_val, exc_tb)

    # --------------------- layout ---------------------
    def _setup(self):
        self.dash.add_line(
            "overall1",
            Line(
                "overall1",
                stats=[
                    Stat("time", "00:00:00", prefix="Time "),
                    Stat("speed", 0.0, prefix=" Speed ", format_string="{:.1f}"),
                    Stat("mbytes", 0.0, prefix=" MB ", format_string="{:.1f}"),
                ],
                style="header",
            ),
        )
        self.dash.add_line(
            "overall2",
            Line(
                "overall2",
                stats=[
                    Stat("urls", (0, self.total_urls), prefix="URLs ", format_string="{}/{}"),
                    Stat("already", 0, prefix=" Already "),
                    Stat("bad", 0, prefix=" Bad "),
                ],
                style="header",
            ),
        )
        self.dash.add_separator()

        self._line_names: Dict[int, Tuple[str, str, str, str]] = {}
        for i in range(self.num_workers):
            w = i + 1
            ln_main = f"w{w}"
            ln_s1 = f"w{w}_s1"
            ln_s2 = f"w{w}_s2"
            ln_s3 = f"w{w}_s3"
            self.dash.add_line(
                ln_main,
                Line(
                    ln_main,
                    stats=[
                        Stat("label", f"Worker {w}"),
                        Stat("set", "", prefix=" Set "),
                        Stat("urls", (0, 0), prefix=" URLs ", format_string="{}/{}"),
                    ],
                ),
            )
            self.dash.add_line(
                ln_s1,
                Line(
                    ln_s1,
                    stats=[
                        Stat("mbps", 0.0, prefix="Spd ", format_string="{:.1f}"),
                        Stat("eta", "--:--:--", prefix=" ETA "),
                        Stat("mb", (0.0, 0.0), prefix=" MB/Seg ", format_string="{:.1f}/{:.1f}"),
                    ],
                ),
            )
            self.dash.add_line(
                ln_s2,
                Line(
                    ln_s2,
                    stats=[
                        Stat("id", "", prefix="ID ", no_expand=True, display_width=20),
                        Stat("title", "", prefix="", no_expand=True, display_width=40),
                    ],
                ),
            )
            self.dash.add_line(
                ln_s3,
                Line(
                    ln_s3,
                    stats=[Stat("already", 0, prefix="Already "), Stat("bad", 0, prefix=" Bad ")],
                ),
            )
            self.dash.add_separator()
            self._line_names[i] = (ln_main, ln_s1, ln_s2, ln_s3)

        # scan block placeholder
        self._add_scan_lines(0, 0)

        # footer
        self.dash.add_line(
            "footer",
            Line("footer", stats=[Stat("msg", "Keys: z pause/resume | q confirm quit | Q force quit", no_expand=False)]),
        )

    # --------------------- scan block ---------------------
    def _add_scan_lines(self, n_workers: int, total_files: int):
        self._scan_total = int(total_files)
        self._scan_done = 0
        if "scan_overall" not in self.dash.lines:
            self.dash.add_line(
                "scan_overall",
                Line(
                    "scan_overall",
                    stats=[
                        Stat("label", "Idle"),
                        Stat("files", (0, 0), prefix=" Files ", format_string="{}/{}"),
                    ],
                    style="header",
                ),
            )
        else:
            # reset
            self.dash.update_stat("scan_overall", "label", "Idle")
            self.dash.update_stat("scan_overall", "files", (0, 0))

        # remove previous scan worker lines if any
        for nm in list(self._scan_lines.values()):
            if nm in self.dash.lines:
                self.dash.remove_line(nm)
        self._scan_lines.clear()

        for i in range(max(0, n_workers)):
            nm = f"scan_w{i+1}"
            self._scan_lines[i] = nm
            self.dash.add_line(
                nm,
                Line(
                    nm,
                    stats=[
                        Stat("w", f"Scan {i+1}", no_expand=True),
                        Stat("file", "", no_expand=True, display_width=40),
                        Stat("status", "idle", no_expand=True),
                    ],
                ),
            )

    # --------------------- public scan API (thread-safe) ---------------------
    def begin_scan(self, num_workers: int, total_files: int):
        self._ops.put(("scan_begin", num_workers, total_files))

    def set_scan_slot(self, slot: int, label: str):
        self._ops.put(("scan_set", slot, label))

    def advance_scan(self, delta: int = 1):
        self._ops.put(("scan_advance", int(delta)))

    def end_scan(self):
        self._ops.put(("scan_end",))

    # --------------------- footer / pause ---------------------
    def set_footer(self, text: str):
        self._ops.put(("footer", text))

    def set_paused(self, paused: bool):
        self._ops.put(("paused", bool(paused)))

    # --------------------- download events (thread-safe) ---------------------
    def handle_event(self, event: DownloadEvent):
        self._ops.put(("event", event))

    # --------------------- main-thread pump ---------------------
    def _header_tick(self):
        elapsed = time.monotonic() - self.start_time
        # speed is the sum of per-worker "mbps" stats (already updated via events)
        try:
            speed_sum = 0.0
            for i in range(self.num_workers):
                _, s1, _, _ = self._line_names[i]
                v = self.dash.read_stat(s1, "mbps")
                if isinstance(v, (int, float)):
                    speed_sum += float(v)
        except Exception:
            speed_sum = 0.0
        self.dash.update_stat("overall1", "time", fmt_hms(elapsed))
        self.dash.update_stat("overall1", "speed", speed_sum)
        self.dash.update_stat("overall1", "mbytes", bytes_to_mib(self.bytes_downloaded))
        self.dash.update_stat("overall2", "urls", (self.urls_started, self.total_urls))
        self.dash.update_stat("overall2", "already", self.already)
        self.dash.update_stat("overall2", "bad", self.bad)

    def pump(self):
        """Apply queued UI ops (call from the main thread frequently)."""
        processed = 0
        while processed < 200:
            try:
                op = self._ops.get_nowait()
            except queue.Empty:
                break
            processed += 1

            kind = op[0]

            if kind == "scan_begin":
                _, nw, tf = op
                self._add_scan_lines(int(nw), int(tf))
                self.dash.update_stat("scan_overall", "label", "Scanning")
                self.dash.update_stat("scan_overall", "files", (0, int(tf)))

            elif kind == "scan_set":
                _, slot, label = op
                nm = self._scan_lines.get(int(slot))
                if nm:
                    self.dash.update_stat(nm, "file", str(label))
                    self.dash.update_stat(nm, "status", "working")

            elif kind == "scan_advance":
                _, d = op
                self._scan_done += int(d)
                self.dash.update_stat("scan_overall", "files", (self._scan_done, self._scan_total))

            elif kind == "scan_end":
                self.dash.update_stat("scan_overall", "label", "Scanned")
                for nm in self._scan_lines.values():
                    self.dash.update_stat(nm, "status", "done")

            elif kind == "footer":
                _, msg = op
                self.dash.update_stat("footer", "msg", str(msg))

            elif kind == "paused":
                _, on = op
                self.dash.update_stat("footer", "msg", f"{'PAUSED' if on else 'RUNNING'} | Keys: z pause/resume | q confirm quit | Q force quit")

            elif kind == "event":
                _, event = op
                self._apply_event(event)

        # keep header fresh (timer/speed/MB)
        self._header_tick()

    # -- internal: apply a download event (main thread only) --
    def _slot_for_item(self, item_id: int) -> int:
        return item_id % self.num_workers

    def _apply_event(self, event: DownloadEvent):
        if isinstance(event, StartEvent):
            slot = self._slot_for_item(event.item.id)
            ln_main, ln_s1, ln_s2, ln_s3 = self._line_names[slot]
            setname = event.item.source.file.stem if event.item.source else ""
            self.dash.update_stat(ln_main, "set", setname)
            self.urls_started += 1
            cur, total = self.dash.read_stat(ln_main, "urls") or (0, 0)
            cur_val = int(cur[0]) if isinstance(cur, tuple) else int(cur or 0)
            self.dash.update_stat(ln_main, "urls", (cur_val + 1, total or 0))
            self.dash.update_stat(ln_s2, "id", "")
            self.dash.update_stat(ln_s2, "title", event.item.url)

        elif isinstance(event, ProgressEvent):
            slot = self._slot_for_item(event.item.id)
            ln_main, ln_s1, ln_s2, ln_s3 = self._line_names[slot]
            if event.unit == "segments":
                if event.total_bytes is not None:
                    self.dash.update_stat(ln_s1, "mb", (float(event.downloaded_bytes or 0), float(event.total_bytes)))
                self.dash.update_stat(ln_s1, "mbps", float(event.speed_bps or 0.0))
                self.dash.update_stat(ln_s1, "eta", fmt_hms(event.eta_seconds))
            else:
                if event.total_bytes is not None:
                    cur = float(event.downloaded_bytes or 0.0)
                    self.bytes_downloaded += max(0.0, cur)  # rough addition; exact deltas not critical here
                    self.dash.update_stat(ln_s1, "mb", (cur / (1024 * 1024), float(event.total_bytes) / (1024 * 1024)))
                self.dash.update_stat(ln_s1, "mbps", float((event.speed_bps or 0.0) / (1024 * 1024)))
                self.dash.update_stat(ln_s1, "eta", fmt_hms(event.eta_seconds))

        elif isinstance(event, MetaEvent):
            slot = self._slot_for_item(event.item.id)
            _, _, ln_s2, _ = self._line_names[slot]
            self.dash.update_stat(ln_s2, "id", event.video_id)
            self.dash.update_stat(ln_s2, "title", event.title)

        elif isinstance(event, DestinationEvent):
            slot = self._slot_for_item(event.item.id)
            _, _, ln_s2, _ = self._line_names[slot]
            self.dash.update_stat(ln_s2, "title", event.path.name)

        elif isinstance(event, AlreadyEvent):
            slot = self._slot_for_item(event.item.id)
            _, _, _, ln_s3 = self._line_names[slot]
            self.already += 1
            cur = self.dash.read_stat(ln_s3, "already") or 0
            self.dash.update_stat(ln_s3, "already", int(cur) + 1)

        elif isinstance(event, FinishEvent):
            slot = self._slot_for_item(event.item.id)
            _, ln_s1, _, ln_s3 = self._line_names[slot]
            self.dash.update_stat(ln_s1, "mbps", 0.0)
            self.dash.update_stat(ln_s1, "eta", "--:--:--")
            if event.result.status == DownloadStatus.ALREADY_EXISTS:
                self.already += 1
                cur = self.dash.read_stat(ln_s3, "already") or 0
                self.dash.update_stat(ln_s3, "already", int(cur) + 1)
            elif event.result.status == DownloadStatus.FAILED:
                self.bad += 1
                cur = self.dash.read_stat(ln_s3, "bad") or 0
                self.dash.update_stat(ln_s3, "bad", int(cur) + 1)

    def summary(self, stats: Dict[str, int], elapsed: float):
        # nothing extra; dashboard shows the totals already
        pass
