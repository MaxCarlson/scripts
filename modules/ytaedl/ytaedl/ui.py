"""UI layer with TermDash live dashboard and simple fallback."""
from __future__ import annotations

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


class SimpleUI(UIBase):
    def __init__(self) -> None:
        self._start = time.monotonic()
        self._completed = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ...

    def handle_event(self, event: DownloadEvent):
        if isinstance(event, StartEvent):
            print(f"[START] {event.item.id}: {event.item.url}")
        elif isinstance(event, FinishEvent):
            print(f"[FINISH] {event.item.id}: {event.result.status.value.upper()}")
            self._completed += 1

    def summary(self, stats: Dict[str, int], elapsed: float):
        print(f"Completed: {self._completed} in {elapsed:.2f}s")


class TermdashUI(UIBase):
    """
    Live dashboard using TermDash.
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
            reserve_extra_rows=6,
        )
        self.start_time = time.monotonic()
        self.bytes_downloaded = 0.0
        self.urls_started = 0
        self.already = 0
        self.bad = 0
        self._last_bytes_per_worker = {i: 0 for i in range(self.num_workers)}
        self._setup()

    def __enter__(self):
        self.dash.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dash.__exit__(exc_type, exc_val, exc_tb)

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

    def _header_tick(self):
        from termdash.utils import fmt_hms, bytes_to_mib
        elapsed = time.monotonic() - self.start_time
        speed_sum = 0.0
        for i in range(self.num_workers):
            _, s1, _, _ = self._line_names[i]
            try:
                speed_sum += float(self.dash.read_stat(s1, "mbps") or 0.0)
            except Exception:
                pass
        self.dash.update_stat("overall1", "time", fmt_hms(elapsed))
        self.dash.update_stat("overall1", "speed", speed_sum)
        self.dash.update_stat("overall1", "mbytes", bytes_to_mib(self.bytes_downloaded))
        self.dash.update_stat("overall2", "urls", (self.urls_started, self.total_urls))
        self.dash.update_stat("overall2", "already", self.already)
        self.dash.update_stat("overall2", "bad", self.bad)

    def _slot_for_item(self, item_id: int) -> int:
        return item_id % self.num_workers

    def handle_event(self, event: DownloadEvent):
        self._header_tick()

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
                self.dash.update_stat(ln_s1, "mbps", float(event.speed_bps or 0.0))  # it/s
                self.dash.update_stat(ln_s1, "eta", fmt_hms(event.eta_seconds))
            else:  # bytes
                if event.total_bytes is not None:
                    prev = self._last_bytes_per_worker.get(slot, 0)
                    cur = int(event.downloaded_bytes or 0)
                    delta = max(0, cur - prev)
                    self._last_bytes_per_worker[slot] = cur
                    self.bytes_downloaded += delta
                    self.dash.update_stat(ln_s1, "mb", (float(cur) / (1024 * 1024), float(event.total_bytes) / (1024 * 1024)))
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
        pass
