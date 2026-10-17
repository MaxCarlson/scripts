"""Concise inventory statistics, shared by standalone and MangaDL CLIs."""

from collections import Counter
import json
import os
import sys

from termdash.table import render_table
from termdash.utils import color_text, format_bytes_decimal


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
