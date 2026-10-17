"""Preserved renderer fixtures; estimator phase/unknown/cache/cancel cases join in Task 7."""

from pathlib import Path
import io
import re

import pytest

from compresser.markdown_report import render_markdown_report
from compresser.inventory_ui import InventoryProgress
from compresser.report_models import ReportContext
from compresser.reporting import (
    build_comparison_report,
    build_inventory_report,
    render_console_report,
)
from reporting_test import sample_row
from termdash.table import _visible_len

FIXTURES = Path(__file__).parent / "fixtures" / "preserved_reports"


@pytest.mark.parametrize("width", [80, 120, 160])
def test_preserved_inventory_progress_layout(width, monkeypatch):
    import compresser.inventory_ui as inventory_ui
    from termdash.table import _truncate_cell

    clock = [10.0]
    monkeypatch.setattr(inventory_ui.time, "monotonic", lambda: clock[0])
    progress = InventoryProgress(
        Path("fixtures/library"), stream=io.StringIO(), interactive=False
    )
    try:
        progress.set_folder_total(3)
        gallery = Path("fixtures/library/漫画")
        progress.start_gallery(gallery, total_files=4)
        progress.advance_file(
            gallery / "01.jpg",
            size_bytes=1024,
            reused=True,
            gallery_key=gallery,
        )
        clock[0] = 12.0
        progress.advance_file(
            gallery / "02.webp", size_bytes=2048, inspected=True, gallery_key=gallery
        )
        lines = [_truncate_cell(line, width) for line in progress._lines()]
        expected = (
            (FIXTURES / f"progress-{width}.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert lines == expected
        assert all("\x1b" not in line for line in lines)
    finally:
        progress.close()


@pytest.fixture(params=["comparison", "inventory"])
def preserved_report(request):
    context = ReportContext(
        Path("fixtures/library"),
        snapshot={
            "age_seconds": 123,
            "completed": "2026-10-17T12:00:00+00:00",
            "membership_verified": False,
        },
    )
    if request.param == "comparison":
        return request.param, build_comparison_report([sample_row()], context=context)
    return request.param, build_inventory_report(
        {
            "depth": "files",
            "candidate_images": 1234,
            "candidate_bytes": 1073741824,
            "content_verified": False,
            "galleries": {"gallery": {"files": 1234, "bytes": 1073741824}},
        },
        context=context,
    )


@pytest.mark.parametrize("width", [80, 120, 160])
def test_preserved_report_layout(preserved_report, width):
    name, report = preserved_report
    text = render_console_report(report, width=width, color=False)
    expected = (FIXTURES / f"{name}-{width}.txt").read_text(encoding="utf-8")
    assert text.replace(
        "fixtures\\library", "fixtures/library"
    ) + "\n" == expected.replace("fixtures\\library", "fixtures/library")
    assert all(_visible_len(line) <= width for line in text.splitlines())
    assert "\x1b" not in text
    markdown = render_markdown_report(report)
    assert "\x1b" not in markdown
    if name == "comparison":
        assert "512.00 MiB" in text and "512.00 MiB" in markdown


@pytest.mark.parametrize("width", [80, 120, 160])
def test_wrapped_cjk_and_control_labels_preserve_values(width):
    label = "漫画" * 24 + "end\x1b[31m\tvalue"
    report = build_comparison_report(
        [sample_row(strategy_name=label)],
        context=ReportContext(Path("fixtures/library")),
    )
    text = render_console_report(report, width=width, color=False)
    assert all(_visible_len(line) <= width for line in text.splitlines())
    assert "\x1b" not in text and "\t" not in text
    assert "漫画" * 24 + "end" in re.sub(r"[\s│]", "", text)
    assert "512.00 MiB" in text
    assert "漫画" * 24 + "end" in render_markdown_report(report)
