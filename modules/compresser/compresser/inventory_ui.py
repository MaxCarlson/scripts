"""Concise inventory statistics and live in-place scan progress shared by standalone and MangaDL CLIs."""

from __future__ import annotations

from collections import Counter, deque
import json
import os
from pathlib import Path
import shutil
import sys
import time

from termdash.live import LiveBlock
from termdash.progress import ProgressBar
from termdash.table import render_table
from termdash.utils import color_text, fmt_hms, format_bytes_decimal, format_rate_bps


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
        self.total_folders = max(0, int(total_folders))
        self._maybe_render()

    def start_folder(self, folder: Path, *, folders_done: int | None = None, total_folders: int | None = None) -> None:
        if not self.enabled:
            return
        self.phase = "SCANNING HEADERS" if self.depth == "headers" else "SCANNING FILES"
        if total_folders is not None:
            self.total_folders = max(0, int(total_folders))
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
    ) -> None:
        if not self.enabled:
            return
        self.phase = "SCANNING HEADERS" if self.depth == "headers" else "SCANNING FILES"
        parent = path.parent
        if parent not in self.seen_folders:
            self.seen_folders.add(parent)
            if self.total_folders is None:
                self.folders_processed = len(self.seen_folders)
        self.current_folder = parent.name or str(parent)
        self.current_file = path.name
        self.files_processed += 1
        if size_bytes > 0:
            self.bytes_processed += int(size_bytes)
        if reused:
            self.headers_reused += 1
        if inspected:
            self.headers_inspected += 1
        if unreadable:
            self.excluded_or_unreadable += 1
        if self.total_files is not None and self.total_files > 0:
            self.bar.set_total(max(1, self.total_files))
            self.bar.set(min(self.files_processed, self.total_files))
        self._maybe_render()

    def _maybe_render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        self._record_sample(now)
        if self.interactive:
            if force or (now - self.last_render) >= 0.08:
                self.block.update(self._lines)
                self.last_render = now
        else:
            if force or (now - self.last_render) >= 2.0:
                print(self.summary_line(), file=self.stream, flush=True)
                self.last_render = now

    def summary_line(self) -> str:
        now = time.monotonic()
        elapsed, files_s, bytes_s = self._rates(now)
        folder_part = (
            f"Folders: {self.folders_processed:,}/{self.total_folders:,}"
            if self.total_folders is not None
            else f"Folders: {self.folders_processed:,}"
        )
        file_part = (
            f"Files: {self.files_processed:,}/{self.total_files:,}"
            if self.total_files is not None
            else f"Files: {self.files_processed:,}"
        )
        detail_part = (
            f" (reused {self.headers_reused:,}, inspected {self.headers_inspected:,})"
            if self.depth == "headers"
            else ""
        )
        return (
            f"[{self.phase}] {folder_part} | {file_part}{detail_part} | "
            f"Size: {format_bytes_decimal(self.bytes_processed)} | "
            f"Rate: {files_s:,.1f} files/s ({format_rate_bps(bytes_s)}) | "
            f"Elapsed: {fmt_hms(elapsed)}"
        )

    def _lines(self) -> list[str]:
        now = time.monotonic()
        elapsed, files_s, bytes_s = self._rates(now)
        cols = shutil.get_terminal_size((100, 20)).columns
        folder_str = (
            f"{self.folders_processed:,}/{self.total_folders:,}"
            if self.total_folders is not None
            else f"{self.folders_processed:,}"
        )
        file_str = (
            f"{self.files_processed:,}/{self.total_files:,}"
            if self.total_files is not None
            else f"{self.files_processed:,}"
        )
        eta_str = "--:--:--"
        if self.total_files and self.files_processed > 0 and self.total_files >= self.files_processed and files_s > 0:
            rem = (self.total_files - self.files_processed) / files_s
            eta_str = fmt_hms(rem)

        header = f"[{self.phase}] Target: {self.root.name or str(self.root)} ({self.depth})"
        if self.total_files and self.total_files > 0:
            pct = 100.0 * min(self.files_processed, self.total_files) / max(1, self.total_files)
            bar_line = f"Progress: {self.bar} {pct:5.1f}% ({file_str} files) | ETA: {eta_str}"
        else:
            bar_line = f"Progress: {file_str} files scanned | Elapsed: {fmt_hms(elapsed)}"

        stats_line = (
            f"Folders:  {folder_str} | Size: {format_bytes_decimal(self.bytes_processed)} | "
            f"Rate: {files_s:,.1f} files/s ({format_rate_bps(bytes_s)}) | Elapsed: {fmt_hms(elapsed)}"
        )
        if self.depth == "headers":
            detail_line = (
                f"Headers:  reused {self.headers_reused:,} | inspected {self.headers_inspected:,} | "
                f"unreadable {self.excluded_or_unreadable:,} | Folder: {self.current_folder}"
            )
        else:
            detail_line = (
                f"Excluded: {self.excluded_or_unreadable:,} | "
                f"Folder: {self.current_folder} | File: {self.current_file}"
            )
        return [line[: max(40, cols - 1)] for line in (header, bar_line, stats_line, detail_line)]

    def close(self) -> None:
        if not self.enabled:
            return
        # close() stops the timer and erases its transient rows atomically.
        self.block.close()


def emit_inventory_report(report: dict, *, as_json: bool = False) -> None:
    """Keep redirected JSON compatible; show only a summary in an interactive terminal."""
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
