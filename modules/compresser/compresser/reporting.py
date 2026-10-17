"""Compression report composition; no terminal capture and no independent hero guesses."""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from termdash.table import render_table_panels, wrap_display_text
from termdash.utils import color_text

from .models import ComparisonRow
from .report_models import CompressionReport, ReportContext, ReportSection

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean(value) -> str:
    text = _ANSI.sub("", str(value))
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in text)


def binary_bytes(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    number = abs(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{sign}{number:.0f} B" if unit == "B" else f"{sign}{number:.2f} {unit}"
        number /= 1024


def section(title, headers, rows, identity=(0,), verbose=False) -> ReportSection:
    return ReportSection(
        title,
        tuple(clean(h) for h in headers),
        tuple(tuple(clean(cell) for cell in row) for row in rows),
        tuple(identity),
        verbose,
    )


def stdout_color_enabled() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def _context_sections(context: ReportContext):
    facts = [
        ["Target", str(context.target)],
        ["Status", context.status],
        ["Workspace", str(context.workspace) if context.workspace else "Not specified"],
    ]
    for name, value in context.snapshot.items():
        if name in ("created", "completed", "age_seconds", "warning", "policy") and value is not None:
            facts.append([f"Inventory {name}", str(value)])
    return [section("RUN CONTEXT", ("Metric", "Value"), facts)]


def build_comparison_report(rows: Sequence[ComparisonRow], *, context: ReportContext) -> CompressionReport:
    if context.status == "completed" and any(row.failed_count for row in rows):
        context = replace(context, status="completed_with_errors")
    sections = _context_sections(context)
    sampling = context.sampling or (rows[0].sampling if rows else {})
    coverage = rows[0].extrapolation.get("formats", {}) if rows else {}
    if not coverage:
        coverage = sampling.get("formats", {})
    if coverage:
        coverage_rows = []
        for fmt, value in sorted(coverage.items()):
            n, size = value.get("images", 0), value.get("bytes", 0)
            sn, sb = value.get("sample_images", 0), value.get("sample_bytes", 0)
            coverage_rows.append(
                [
                    fmt,
                    f"{n:,}",
                    binary_bytes(size),
                    f"{sn:,}",
                    binary_bytes(sb),
                    f"{sn/n*100:.3f}%" if n else "—",
                    f"{sb/size*100:.3f}%" if size else "—",
                    value.get("basis", "selected sample"),
                ]
            )
        totals = [
            sum(v.get(k, 0) for v in coverage.values()) for k in ("images", "bytes", "sample_images", "sample_bytes")
        ]
        n, size, sn, sb = totals
        coverage_rows.append(
            [
                "TOTAL",
                f"{n:,}",
                binary_bytes(size),
                f"{sn:,}",
                binary_bytes(sb),
                f"{sn/n*100:.3f}%" if n else "—",
                f"{sb/size*100:.3f}%" if size else "—",
                "eligible inventory",
            ]
        )
        sections.append(
            section(
                "SAMPLE COVERAGE",
                (
                    "Format",
                    "Target images",
                    "Target size",
                    "Sample images",
                    "Sample size",
                    "Count cover",
                    "Byte cover",
                    "Estimate basis",
                ),
                coverage_rows,
            )
        )
    if sampling:
        facts = [
            ["Gallery coverage", f"{sampling.get('sampled_galleries', 0)} / {sampling.get('galleries', 0)}"],
            ["Sampling", f"{sampling.get('allocation_method', 'gallery-stratified')} · seed {sampling.get('seed', 0)}"],
        ]
        if sampling.get("coverage_gaps"):
            facts.append(["WARNING: coverage", ", ".join(sampling["coverage_gaps"])])
        if sampling.get("sampled_galleries", 0) < sampling.get("galleries", 0):
            facts.append(
                [
                    "WARNING",
                    "Some galleries were not sampled; extrapolation may differ substantially from full processing.",
                ]
            )
        sections.append(section("COVERAGE DETAILS", ("Metric", "Value"), facts))
    impact, outcomes, issues, resources, phases, candidates, eligible = [], [], [], [], [], [], []
    calculated = bool(rows) and all(r.extrapolation.get("status") == "calculated" for r in rows)
    prefix = "Calculated" if calculated else "Estimated"
    for index, row in enumerate(rows, 1):
        ident = f"{index:02d}"
        e = row.extrapolation
        value = e.get("saved_bytes")
        percentage = e.get("reduction_percent")
        fallback = e.get("fallback_percent", 0)
        impact.append(
            [
                ident,
                row.strategy_name,
                row.quality_display,
                f"{row.average_ssim:.3f}" if row.average_ssim is not None else "—",
                binary_bytes(e.get("retained_bytes")),
                binary_bytes(value),
                f"{percentage:.1f}%" if percentage is not None else "—",
                f"Fallback {fallback:.1f}% of target bytes" if fallback else e.get("status", "No observations"),
            ]
        )
        status = (
            "No successful encodes; originals retained"
            if e and not e.get("successful_count")
            else "Partial failures" if row.failed_count else "OK"
        )
        rate = row.throughput_images_per_s
        rate_text = (
            f"{rate:.1f} /s"
            if math.isfinite(rate) and rate >= 0.1
            else "<0.1 /s" if math.isfinite(rate) and rate > 0 else "Not measured"
        )
        kind = (
            "Fully cached"
            if row.cache_hits and row.cache_hits == row.measured_images
            else "Mixed cache" if row.cache_hits else "Uncached trials"
        )
        outcomes.append(
            [
                ident,
                row.strategy_name,
                str(row.measured_images),
                str(row.failed_count),
                str(row.skipped_count),
                str(row.cache_hits),
                rate_text,
                kind,
                status,
            ]
        )
        for reason, count in row.issues.items():
            issues.append([ident, row.strategy_name, str(count), reason])
        if not row.issues:
            for reason in row.error_summary:
                issues.append([ident, row.strategy_name, "See reason", reason])
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 and e.get("successful_count", 0) > 0:
            eligible.append((row, ident))
        d = row.worker_diagnostics
        if d:
            resources.append(
                [
                    ident,
                    row.strategy_name,
                    str(d.get("requested_workers", "—")),
                    str(d.get("effective_workers", "—")),
                    str(d.get("limiter", "—")),
                    binary_bytes(d.get("peak_reserved_bytes")),
                    f"{d.get('dispatch_wait_seconds', 0):.3f}",
                ]
            )
            for name, seconds in sorted(d.get("phase_seconds", {}).items()):
                phases.append([ident, row.strategy_name, name, f"{seconds:.3f}"])
        if row.candidate_bytes is not None:
            candidates.append(
                [ident, row.strategy_name, binary_bytes(row.candidate_bytes), binary_bytes(row.original_bytes)]
            )
    sections.extend(
        [
            section(
                f"{prefix.upper()} WHOLE-TARGET IMPACT",
                (
                    "ID",
                    "Strategy",
                    "Quality",
                    "Mean SSIM",
                    f"{prefix} retained",
                    f"{prefix} saved",
                    "Reduction",
                    "Basis / status",
                ),
                impact,
                (0, 1),
            ),
            section(
                "SAMPLE OUTCOMES & EXECUTION",
                ("ID", "Strategy", "Evaluated", "Failed", "Unchanged", "Cached", "Trial rate", "Execution", "Status"),
                outcomes,
                (0, 1),
            ),
        ]
    )
    highlights = []
    for label, choices in (
        ("Largest target reduction", eligible),
        (
            "Higher-SSIM alternative (0.98 heuristic)",
            [
                (r, i)
                for r, i in eligible
                if r.mode == "lossless" or r.average_ssim is not None and r.average_ssim >= 0.98
            ],
        ),
        ("Lossless alternative", [(r, i) for r, i in eligible if r.mode == "lossless"]),
    ):
        if choices:
            best, ident = max(choices, key=lambda item: item[0].extrapolation["saved_bytes"])
            highlights.append(
                [
                    label,
                    ident,
                    best.strategy_name,
                    binary_bytes(best.extrapolation["saved_bytes"]),
                    (
                        "Partial failures"
                        if best.failed_count
                        else "Sample evidence, not a proven winner" if not calculated else "Calculated impact"
                    ),
                ]
            )
    sections.append(
        section(
            "QUALIFIED HIGHLIGHTS",
            ("Category", "ID", "Strategy", "Target saved", "Caveat"),
            highlights
            or [["No eligible positive-savings evidence", "—", "—", "—", "Originals retained or no observations"]],
        )
    )
    if issues:
        sections.append(section("ERRORS / RETAINED ORIGINALS", ("ID", "Strategy", "Count", "Reason"), issues, (0, 1)))
    if resources:
        sections.append(
            section(
                "RESOURCES",
                (
                    "ID",
                    "Strategy",
                    "Requested",
                    "Effective",
                    "Limiter",
                    "Peak reserved estimate",
                    "Dispatch task-seconds",
                ),
                resources,
                (0, 1),
            )
        )
    if context.cache:
        sections.append(section("CACHE", ("Metric", "Value"), [[k, str(v)] for k, v in sorted(context.cache.items())]))
    if phases:
        sections.append(section("PHASE WORKER-SECONDS", ("ID", "Strategy", "Phase", "Seconds"), phases, (0, 1), True))
    if candidates:
        sections.append(
            section(
                "RAW CANDIDATES BEFORE ORIGINAL-RETENTION POLICY",
                ("ID", "Strategy", "Candidate bytes", "Sample original bytes"),
                candidates,
                (0, 1),
                True,
            )
        )
    return CompressionReport(
        "COMPRESSION COMPARISON",
        context.operation,
        context.status,
        clean(context.target),
        tuple(sections),
        (
            "Format-ratio extrapolation applies observed byte-savings ratios to inventory bytes; unsampled formats use an explicitly marked overall-ratio fallback.",
            "Estimates are not guaranteed savings or confidence bounds. Small samples and gallery variation can change outcomes.",
        "Failed trials retain originals; larger candidates are retained only when explicitly allowed. Unchanged excludes failures; cached counts overlap outcomes.",
            "Mean SSIM includes unchanged originals and can hide individual poor results. Lossless means pixel preservation, not identical file bytes.",
            "Trial rates include failures and cache reuse; they are not encoder speed. Reserved memory is an estimate, not process RAM.",
            "Inspect full-resolution previews (-O) before lossy writes. Increase sampling to refine estimates; -U refresh updates inventory membership.",
        ),
    )


def render_console_report(report: CompressionReport, *, width: int, color: bool, verbose: bool = False) -> str:
    def paint(text, tone):
        return color_text(text, tone) if color else text

    lines = wrap_display_text(paint(f"{report.title} — {Path(report.target).name}", "cyan"), width)
    for s in report.sections:
        if s.verbose and not verbose:
            continue
        lines.append("")
        lines.extend(wrap_display_text(paint(s.title, "cyan"), width))
        rows = []
        for row in s.rows:
            cells = []
            for index, cell in enumerate(row):
                header = s.headers[index]
                tone = "blue" if index in s.identity_columns else None
                if "WARNING" in cell or "Partial" in cell or "Fallback" in cell:
                    tone = "yellow"
                if "ERROR" in s.title or "No successful" in cell or header == "Failed" and cell != "0":
                    tone = "red"
                if ("saved" in header.lower() or header == "Reduction") and cell not in ("—", "0 B", "0.0%"):
                    tone = "yellow" if cell.startswith("-") else "green"
                cells.append(paint(cell, tone) if tone else cell)
            rows.append(cells)
        panels = render_table_panels(
            s.headers,
            rows,
            identity_columns=s.identity_columns,
            max_width=width,
            alignments=["left" if i in s.identity_columns else "right" for i in range(len(s.headers))],
        )
        for number, panel in enumerate(panels, 1):
            if len(panels) > 1:
                lines.extend(wrap_display_text(f"Panel {number}/{len(panels)}", width))
            lines.extend(panel.splitlines())
    lines.append("")
    for note in report.notes:
        lines.extend(wrap_display_text(clean(note), width))
    lines.extend(wrap_display_text(f"{report.status.upper()} — {report.operation}", width))
    return "\n".join(lines)
