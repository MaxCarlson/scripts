#!/usr/bin/env python3
"""
vdedup.progress

Rich-powered status dashboard that surfaces pipeline health in real time.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.1f} PiB"


def _stage_key(name: str) -> str:
    """Stable key for stage lookups."""
    return name.strip().lower().replace(" ", "_")


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
        self.refresh_rate = max(0.2, float(refresh_rate))
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

        # Controls
        self._paused_evt = threading.Event()
        self._paused_evt.set()
        self._quit_evt = threading.Event()
        self._stop_evt = threading.Event()

        # Last print time for throttling
        self._last_print = 0.0

        # In-memory log buffer
        self._log_messages: List[Tuple[str, str, float]] = []

    # ------------------------------------------------------------------ public API

    def start(self) -> None:
        """Start dashboard rendering if enabled."""
        if self.enable_dash and not self._ui_initialized:
            refresh_per_second = max(1, int(round(1 / self.refresh_rate)))
            self._live = Live(
                self._render_layout(),
                console=self.console,
                refresh_per_second=refresh_per_second,
                transient=False,
            )
            self._live.start()
            self._ui_initialized = True

    def set_status(self, text: str) -> None:
        """Update status line."""
        with self.lock:
            self.status_line = text
        self._print_if_due()

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
        with self.lock:
            prev_key = _stage_key(self.stage_name)
            if prev_key in self.stage_status and self.stage_status[prev_key] == "running":
                self.stage_status[prev_key] = "done"

            key = _stage_key(name)
            self.stage_display[key] = name
            if key not in self.stage_order:
                self.stage_order.append(key)

            self.stage_status[key] = "running"
            self.stage_name = name
            self.stage_total = max(0, int(total))
            self.stage_done = 0
            self.stage_start_ts = time.time()
            self.status_line = name
        self._print_now()

    def finish_stage(self, name: Optional[str] = None) -> None:
        """Mark a stage as completed."""
        with self.lock:
            stage = name or self.stage_name
            key = _stage_key(stage)
            if key in self.stage_status:
                self.stage_status[key] = "done"
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
            self.stage_done += inc
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
            self.stage_done += inc
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
            self.stage_done = max(0, int(current_step))
            if total_steps > 0:
                self.stage_total = max(self.stage_total, int(total_steps))
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
        if self.enable_dash and self._live:
            self._live.stop()
            self._live = None
            final = Panel(
                Align.center(Text("Pipeline Complete", style="bold green")),
                border_style="green",
            )
            self.console.print(final)

    def add_log(self, message: str, level: str = "INFO") -> None:
        """Record a diagnostic log entry for the UI."""
        entry = (level.upper(), str(message), time.time())
        with self.lock:
            self._log_messages.append(entry)
            if len(self._log_messages) > 200:
                self._log_messages.pop(0)
        self._print_if_due()

    def recent_logs(self) -> List[Tuple[str, str, float]]:
        """Return recent log entries."""
        with self.lock:
            return list(self._log_messages[-5:])

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

    def _render_layout(self) -> Layout:
        """Build the main dashboard layout."""
        with self.lock:
            elapsed = max(0.0, time.time() - self.start_ts)
            stage_elapsed = max(0.0, time.time() - self.stage_start_ts)
            pct = (self.stage_done / self.stage_total * 100.0) if self.stage_total > 0 else 0.0
            current_key = _stage_key(self.stage_name)
            current_metrics = dict(self.stage_metrics.get(current_key, {}))
            logs = list(self._log_messages[-4:])

        layout = Layout()
        layout.split_column(
            Layout(self._render_header(elapsed, stage_elapsed, pct), size=6),
            Layout(name="body", ratio=1),
            Layout(self._render_footer(logs), size=7),
        )
        layout["body"].split_row(
            Layout(self._render_stage_panel(current_metrics), ratio=2),
            Layout(self._render_stats_panel(elapsed), ratio=3),
        )
        return layout

    def _render_header(self, elapsed: float, stage_elapsed: float, pct: float) -> Panel:
        """Pipeline headline with progress bar."""
        table = Table.grid(expand=True)
        table.add_column(ratio=3)
        table.add_column(justify="right", ratio=2)

        stage_text = Text(self.stage_name.upper(), style="bold cyan")
        elapsed_text = Text(f"Elapsed: {int(elapsed)}s  Stage: {int(stage_elapsed)}s", style="bold")
        table.add_row(stage_text, elapsed_text)

        bar = self._progress_bar(pct)
        counts = Text(f"{self.stage_done:,}/{self.stage_total:,}" if self.stage_total else f"{self.stage_done:,}", style="bold")
        table.add_row(bar, counts)

        status = Text(self.status_line, style="italic magenta")
        banner = Text(self.banner, style="dim") if self.banner else Text("")
        table.add_row(status, banner)

        return Panel(table, title="Video Deduplication Pipeline", border_style="cyan")

    def _render_stage_panel(self, metrics: Dict[str, Any]) -> Panel:
        """Render per-stage timeline and metrics."""
        timeline = Table(box=None, expand=True, padding=(0, 1))
        timeline.add_column("Stage", justify="left")
        timeline.add_column("Status", justify="right")

        for key in self.stage_order:
            display = self.stage_display.get(key, key.title())
            status = self.stage_status.get(key, "pending")
            style = {
                "running": "bold yellow",
                "done": "green",
                "pending": "grey62",
            }.get(status, "grey62")
            timeline.add_row(display, Text(status.upper(), style=style))

        metrics_table = Table.grid(expand=True)
        metrics_table.add_column(justify="left")
        metrics_table.add_column(justify="right")
        if metrics:
            for key, value in metrics.items():
                metrics_table.add_row(str(key).replace("_", " ").title(), Text(str(value), style="bold"))
        else:
            metrics_table.add_row("info", Text("Collecting metrics...", style="dim"))

        body = Group(
            Align.left(timeline),
            Panel(metrics_table, title="Stage Metrics", border_style="magenta"),
        )
        return Panel(body, title="Stage Timeline", border_style="magenta")

    def _render_stats_panel(self, elapsed: float) -> Panel:
        """Render global statistics."""
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_column(justify="right")

        bytes_remaining = max(0, self.total_bytes - self.bytes_seen)
        throughput = (self.bytes_seen / elapsed) if elapsed > 0 else 0.0
        dup_ratio = (self.duplicates_found / self.video_files) * 100 if self.video_files else 0.0

        summary = [
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
        ]

        for label, value in summary:
            table.add_row(label, Text(value, style="bold"))

        return Panel(table, title="Pipeline Stats", border_style="blue")

    def _render_footer(self, logs: List[Tuple[str, str, float]]) -> Panel:
        """Show recent log lines."""
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        if logs:
            for level, message, _ in logs:
                style = {"ERROR": "bold red", "WARNING": "yellow", "INFO": "white", "DEBUG": "cyan"}.get(level, "white")
                table.add_row(Text(f"[{level}] {message}", style=style))
        else:
            table.add_row(Text("No recent log entries", style="dim"))
        return Panel(table, title="Recent Activity", border_style="grey50")

    def _progress_bar(self, pct: float) -> Text:
        """Return a colorized progress bar string."""
        pct_clamped = max(0.0, min(100.0, pct))
        width = 42
        filled = int(round((pct_clamped / 100.0) * width))
        remaining = width - filled
        bar = f"[green]{'█' * filled}[/green][grey30]{'░' * remaining}[/grey30]"
        return Text(f"{bar} {pct_clamped:5.1f}%", justify="left")
