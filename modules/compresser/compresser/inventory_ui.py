"""Concise inventory statistics and live in-place scan progress shared by standalone and MangaDL CLIs."""

from __future__ import annotations

from collections import Counter, deque
import json
import os
from pathlib import Path
import sys
import time
import threading

from termdash.live import LiveBlock
from termdash.progress import ProgressBar
from termdash.table import render_table
from termdash.utils import color_text, fmt_hms, format_bytes_decimal, format_rate_bps
from .timing import pipeline_report


class InventoryProgress:
    """Live in-place progress display for filesystem and header inventory scans."""

    def __init__(
        self,
        root: Path,
        *,
        depth: str = "headers",
        enabled: bool = True,
        stream=None,
        interactive: bool | None = None,
    ) -> None:
        self.root = root
        self.depth = depth
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = bool(enabled)
        self.block = LiveBlock(stream=self.stream, enabled=self.enabled)
        self.interactive = bool(interactive) if interactive is not None else self.block.interactive
        self.start_time = time.monotonic()
        self.last_render = 0.0
        self._lock = threading.RLock()
        self._galleries: dict[str, dict] = {}
        self._display_key: str | None = None
        self._completion_samples = deque([(self.start_time, 0)])

        self.phase = "DISCOVERING"
        self.folders_processed = 0
        self.total_folders: int | None = None
        self.seen_folders: set[Path] = set()
        self.current_folder: str = root.name or str(root)

        self.files_processed = 0
        self.total_files: int | None = None
        self.bytes_processed = 0
        self.headers_reused = 0
        self.headers_inspected = 0
        self.excluded_or_unreadable = 0
        self.current_file: str = ""

        self.samples: deque[tuple[float, int, int]] = deque([(self.start_time, 0, 0)])
        self.bar = ProgressBar("scan", 1, 0, width=28, charset="block")
        if self.enabled and self.interactive:
            self.block.update(self._lines)

    def _record_sample(self, now: float) -> None:
        self.samples.append((now, self.files_processed, self.bytes_processed))
        while len(self.samples) > 1 and self.samples[0][0] < now - 10.0:
            self.samples.popleft()

    def _rates(self, now: float) -> tuple[float, float, float]:
        elapsed = max(0.001, now - self.start_time)
        avg_files_s = self.files_processed / elapsed
        avg_bytes_s = self.bytes_processed / elapsed
        if len(self.samples) >= 2:
            dt = max(0.001, self.samples[-1][0] - self.samples[0][0])
            df = max(0, self.samples[-1][1] - self.samples[0][1])
            avg_files_s = df / dt if dt >= 0.25 else avg_files_s
        return elapsed, avg_files_s, avg_bytes_s

    def set_folder_total(self, total_folders: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.total_folders = max(0, int(total_folders))
        self._maybe_render()

    def start_gallery(self, key: str | Path, total_files: int | None = None) -> None:
        if not self.enabled:
            return
        key = str(key)
        with self._lock:
            self.phase = "SCANNING HEADERS" if self.depth == "headers" else "SCANNING FILES"
            if key not in self._galleries:
                self._galleries[key] = {"done": 0, "total": total_files, "status": "running", "errors": 0}
            elif total_files is not None and self._galleries[key]["status"] == "running":
                self._galleries[key]["total"] = total_files
            if self._display_key is None or self._galleries[self._display_key]["status"] != "running":
                self._display_key = key
        self._maybe_render()

    def finish_gallery(self, key: str | Path, status: str = "complete") -> None:
        if not self.enabled:
            return
        if status not in ("complete", "complete_with_errors", "failed", "cancelled"):
            raise ValueError("Invalid inventory gallery completion status")
        key = str(key)
        with self._lock:
            row = self._galleries[key]
            if row["status"] != "running":
                return
            row["status"] = "complete_with_errors" if row["errors"] and status == "complete" else status
            if row["total"] is None:
                row["total"] = row["done"]
            self.folders_processed = sum(item["status"] != "running" for item in self._galleries.values())
            now = time.monotonic()
            self._completion_samples.append((now, self.folders_processed))
            while len(self._completion_samples) > 2 and self._completion_samples[1][0] < now - 15:
                self._completion_samples.popleft()
            active = [name for name, item in self._galleries.items() if item["status"] == "running"]
            if self._display_key == key and active:
                self._display_key = active[0]
        self._maybe_render()

    def snapshot(self) -> dict:
        """Copy render state under a short lock; no filesystem or renderer calls."""
        with self._lock:
            now = time.monotonic()
            elapsed, files_s, bytes_s = self._rates(now)
            completed = self.folders_processed
            total = self.total_folders
            row = self._galleries.get(self._display_key)
            active = sum(item["status"] == "running" for item in self._galleries.values())
            overall = min(100.0, 100 * completed / total) if total else None
            eta = None
            if total is not None and completed == total and not active:
                overall, eta = 100.0, 0.0
            elif total and completed >= 3 and elapsed >= 5:
                sample_time, sample_count = self._completion_samples[0]
                duration = now - sample_time
                rate = (completed - sample_count) / duration if duration > 0 else 0
                if rate > 0 and now - self._completion_samples[-1][0] <= 15:
                    eta = max(0.0, (total - completed) / rate)
            done = row["done"] if row else self.files_processed
            count = row["total"] if row else self.total_files
            fraction = min(100.0, 100 * done / count) if count else None
            if row and row["status"] != "running" and count == 0:
                fraction = 100.0
            return {
                "phase": self.phase,
                "active_gallery": self._display_key,
                "current_folder": Path(self._display_key).name if row else self.current_folder,
                "current_files_done": done,
                "current_files_total": count,
                "current_percent": fraction,
                "completed_galleries": completed,
                "total_galleries": total,
                "active_galleries": active,
                "overall_percent": overall,
                "eta_seconds": eta,
                "files_done": self.files_processed,
                "files_total": self.total_files,
                "bytes": self.bytes_processed,
                "files_s": files_s,
                "bytes_s": bytes_s,
                "elapsed": elapsed,
                "reused": self.headers_reused,
                "inspected": self.headers_inspected,
                "unreadable": self.excluded_or_unreadable,
                "error_galleries": sum(
                    item["status"] in ("complete_with_errors", "failed", "cancelled")
                    for item in self._galleries.values()
                ),
            }

    def start_folder(self, folder: Path, *, folders_done: int | None = None, total_folders: int | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.phase = "SCANNING HEADERS" if self.depth == "headers" else "SCANNING FILES"
            if total_folders is not None:
                self.total_folders = max(0, int(total_folders))
            if not self._galleries:
                if folders_done is not None:
                    self.folders_processed = max(0, int(folders_done))
                elif folder not in self.seen_folders:
                    self.seen_folders.add(folder)
                    self.folders_processed = len(self.seen_folders)
            self.current_folder = folder.name or str(folder)
        self._maybe_render()

    def add_total_files(self, count: int) -> None:
        if not self.enabled or count <= 0:
            return
        with self._lock:
            self.total_files = (self.total_files or 0) + int(count)
            self.bar.set_total(max(1, self.total_files))
        self._maybe_render()

    def advance_file(
        self,
        path: Path,
        *,
        size_bytes: int = 0,
        reused: bool = False,
        inspected: bool = False,
        unreadable: bool = False,
        gallery_key: str | Path | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.phase = "SCANNING HEADERS" if self.depth == "headers" else "SCANNING FILES"
            parent = path.parent
            if gallery_key is not None:
                row = self._galleries[str(gallery_key)]
                row["done"] += 1
                row["errors"] += bool(unreadable)
            elif parent not in self.seen_folders and not self._galleries:
                self.seen_folders.add(parent)
                if self.total_folders is None:
                    self.folders_processed = len(self.seen_folders)
            self.current_folder = parent.name or str(parent)
            self.current_file = path.name
            self.files_processed += 1
            if size_bytes > 0:
                self.bytes_processed += int(size_bytes)
            self.headers_reused += bool(reused)
            self.headers_inspected += bool(inspected)
            self.excluded_or_unreadable += bool(unreadable)
            if self.total_files is not None and self.total_files > 0:
                self.bar.set_total(max(1, self.total_files))
                self.bar.set(min(self.files_processed, self.total_files))
        self._maybe_render()

    def _maybe_render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        with self._lock:
            now = time.monotonic()
            self._record_sample(now)
            render = force or now - self.last_render >= (0.08 if self.interactive else 2.0)
            if render:
                self.last_render = now
        # Never hold our state lock while the renderer acquires its own lock.
        if render:
            if self.interactive:
                self.block.update(self._lines)
            else:
                print(self.summary_line(), file=self.stream, flush=True)

    def summary_line(self) -> str:
        state = self.snapshot()
        elapsed, files_s, bytes_s = state["elapsed"], state["files_s"], state["bytes_s"]
        folder_part = (
            f"Folders: {state['completed_galleries']:,}/{state['total_galleries']:,}"
            if state["total_galleries"] is not None
            else f"Folders: {state['completed_galleries']:,}"
        )
        file_part = (
            f"Files: {state['files_done']:,}/{state['files_total']:,}"
            if state["files_total"] is not None
            else f"Files: {state['files_done']:,}"
        )
        detail_part = (
            f" (reused {state['reused']:,}, inspected {state['inspected']:,})" if self.depth == "headers" else ""
        )
        return (
            f"[{state['phase']}] {folder_part} | {file_part}{detail_part} | "
            f"Size: {format_bytes_decimal(state['bytes'])} | "
            f"Rate: {files_s:,.1f} files/s ({format_rate_bps(bytes_s)}) | "
            f"Elapsed: {fmt_hms(elapsed)}"
        )

    def _lines(self) -> list[str]:
        state = self.snapshot()
        elapsed, files_s, bytes_s = state["elapsed"], state["files_s"], state["bytes_s"]
        count = state["current_files_total"]
        total = state["total_galleries"]
        current_pct = state["current_percent"]
        overall_pct = state["overall_percent"]
        current_bar = ProgressBar("folder", 100, current_pct or 0, width=28, show_percent=current_pct is not None)
        overall_bar = ProgressBar("overall", 100, overall_pct or 0, width=28, show_percent=overall_pct is not None)
        current_count = (
            f"{state['current_files_done']:,}/{count:,}" if count is not None else f"{state['current_files_done']:,}/?"
        )
        folder_count = (
            f"{state['completed_galleries']:,}/{total:,}"
            if total is not None
            else f"{state['completed_galleries']:,}/?"
        )
        eta = fmt_hms(state["eta_seconds"]) + " estimated" if state["eta_seconds"] is not None else "unknown"
        current_label = f"{current_pct:.1f}%" if current_pct is not None else "unknown"
        overall_label = f"{overall_pct:.1f}%" if overall_pct is not None else "unknown"
        header = f"[{state['phase']}] {state['current_folder']} | other active: {max(0, state['active_galleries'] - 1)}"
        current_line = f"Folder:  {current_bar} {current_label} ({current_count} files)"
        overall_line = f"Overall: {overall_bar} {overall_label} ({folder_count} folders)"
        clock_line = f"Elapsed: {fmt_hms(elapsed)} | ETA: {eta} | Rate: {files_s:.1f} files/s"
        stats_line = f"Files: {state['files_done']:,} | {format_bytes_decimal(state['bytes'])} | {format_rate_bps(bytes_s)} | folders with errors: {state['error_galleries']}"
        detail_line = f"Headers reused/inspected: {state['reused']:,}/{state['inspected']:,} | unreadable/excluded: {state['unreadable']:,}"
        # LiveBlock clips by terminal display width, including CJK and ANSI spans.
        return [header, current_line, overall_line, clock_line, stats_line, detail_line]

    def close(self) -> None:
        if not self.enabled:
            return
        # close() stops the timer and erases its transient rows atomically.
        self.block.close()


def emit_inventory_report(report: dict, *, as_json: bool = False) -> None:
    """Keep redirected JSON compatible; show only a summary in an interactive terminal."""
    report["pipeline"] = pipeline_report()
    if as_json or not sys.stdout.isatty():
        print(json.dumps(report, indent=2), flush=True)
    if not as_json:
        print_inventory_summary(report)


def print_inventory_summary(report: dict) -> None:
    """Summarize observed eligible populations, never implying full image integrity."""
    stream = sys.stderr
    colored = stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"

    def paint(text, color):
        return color_text(text, color) if colored else text

    files_only = report.get("depth") == "files"
    galleries = report["galleries"]
    count = report["candidate_images"] if files_only else report["images"]
    total_bytes = report["candidate_bytes"] if files_only else report["bytes"]
    rows = [
        ["Scan depth", "Files only (content unverified)" if files_only else "Image headers (not full decode)"],
        ["Gallery folders with images", f"{len(galleries):,}"],
        ["Candidate images" if files_only else "Eligible image headers", f"{count:,}"],
        ["File bytes", format_bytes_decimal(total_bytes) if total_bytes is not None else "Unknown (stat errors)"],
    ]
    if files_only:
        if total_bytes is None:
            rows.append(["Known file bytes (partial)", format_bytes_decimal(report["known_bytes"])])
        errors = len(report["stat_errors"])
        rows.extend(
            [
                ["Stat errors", paint(str(errors), "red" if errors else "green")],
                ["Excluded directories", f"{report['excluded_directories']:,}"],
                ["Excluded image candidates", f"{report['excluded_candidate_files']:,}"],
            ]
        )
    else:
        unreadable = report["unreadable_images"]
        rows.extend(
            [
                ["Unreadable candidates", paint(str(unreadable), "red" if unreadable else "green")],
                ["Headers reused / inspected", f"{report['headers_reused']:,} / {report['headers_inspected']:,}"],
            ]
        )
    extensions = {}
    formats = Counter()
    for gallery in galleries.values():
        for extension, bucket in gallery["extensions"].items():
            combined = extensions.setdefault(extension, {"count": 0, "bytes": 0})
            combined["count"] += bucket["files" if files_only else "images"]
            combined["bytes"] = (
                combined["bytes"] + bucket["bytes"]
                if combined["bytes"] is not None and bucket["bytes"] is not None
                else None
            )
        for fmt, bucket in (gallery.get("formats") or {}).items():
            formats[fmt] += bucket["images"]

    print("\n" + paint("Inventory Summary", "cyan"), file=stream)
    print(f"Target: {report['root']}", file=stream)
    print(render_table(headers=["Metric", "Value"], rows=rows, alignments=["left", "right"]), file=stream)
    if extensions:
        details = [
            [
                ext,
                f"{bucket['count']:,}",
                format_bytes_decimal(bucket["bytes"]) if bucket["bytes"] is not None else "Unknown",
                f"{100 * bucket['count'] / max(1, count):.1f}%",
                f"{100 * bucket['bytes'] / total_bytes:.1f}%" if total_bytes and bucket["bytes"] is not None else "N/A",
            ]
            for ext, bucket in sorted(extensions.items())
        ]
        print(
            render_table(
                headers=["Ext", "Files", "Size", "Files %", "Bytes %"],
                rows=details,
                alignments=["left", "right", "right", "right", "right"],
            ),
            file=stream,
        )
    if formats:
        print("Detected formats: " + ", ".join(f"{fmt}: {n:,}" for fmt, n in sorted(formats.items())), file=stream)
    print(
        (
            "Extension candidates only; image content is unverified."
            if files_only
            else "Only eligible headers counted; unreadable candidates excluded. Headers are not a full decode audit."
        ),
        file=stream,
    )
    print("File lengths, not filesystem allocated space; no compression performed.", file=stream)
    print(f"Saved inventory: {report['inventory_file']}", file=stream, flush=True)
    pipeline = report.get("pipeline", {})
    phases = pipeline.get("coordinator_seconds", {})
    if phases:
        print(
            "Measured coordinator seconds: "
            + ", ".join(f"{name}={seconds:.3f}" for name, seconds in sorted(phases.items())),
            file=stream,
        )
        counts = pipeline.get("counters", {})
        print(
            f"Inventory DB: {counts.get('inventory_connections', 0)} connections, "
            f"{counts.get('inventory_queries', 0)} statements, {counts.get('inventory_commits', 0)} commits. "
            "Current-run measured phases; uninstrumented overhead remains.",
            file=stream,
        )
