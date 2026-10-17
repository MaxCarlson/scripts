from dataclasses import replace
from pathlib import Path

import pytest

from compresser.models import ComparisonRow


def sample_row(**changes):
    row = ComparisonRow(
        "auto-lossy-q85",
        "auto",
        "lossy",
        "q=85",
        50,
        50,
        50,
        0.983,
        9000,
        measured_images=2,
        cache_hits=2,
        extrapolation=dict(
            status="estimated",
            target_bytes=1024**3,
            saved_bytes=512 * 1024**2,
            retained_bytes=512 * 1024**2,
            reduction_percent=50,
            successful_count=2,
            fallback_percent=0,
            warnings=[],
            formats={},
        ),
        issues={"EXIF failed": 1},
    )
    return replace(row, **changes)


@pytest.mark.parametrize("width", [40, 60, 80, 100, 120, 160])
def test_report_retains_complete_values_and_bounds(width):
    from compresser.reporting import build_comparison_report, render_console_report
    from compresser.report_models import ReportContext
    from termdash.table import _visible_len

    report = build_comparison_report([sample_row()], context=ReportContext(target=Path("library")))
    out = render_console_report(report, width=width, color=False)
    assert "512.00 MiB" in out and "auto-lossy-q85" in out
    assert "Estimated" in out and "EXIF failed" in out
    assert "cached" in out.lower() and "encoder speed" in " ".join(out.lower().split())
    assert "imperceptible" not in out.lower() and "READY TO COMPRESS" not in out
    assert all(_visible_len(line) <= width for line in out.splitlines())


def test_all_failed_or_nonpositive_cannot_be_highlighted():
    from compresser.reporting import build_comparison_report, render_console_report
    from compresser.report_models import ReportContext

    failed = sample_row(extrapolation=dict(successful_count=0, saved_bytes=999), failed_count=2)
    out = render_console_report(
        build_comparison_report([failed], context=ReportContext(Path("x"))), width=120, color=False
    )
    assert "No eligible positive-savings" in out


def test_color_never_leaks_when_disabled():
    from compresser.reporting import build_comparison_report, render_console_report
    from compresser.report_models import ReportContext

    report = build_comparison_report([sample_row()], context=ReportContext(Path("x")))
    assert "\x1b[" not in render_console_report(report, width=100, color=False)
    assert "\x1b[" in render_console_report(report, width=100, color=True)
