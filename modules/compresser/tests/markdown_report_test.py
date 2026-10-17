from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from compresser.report_models import CompressionReport, ReportSection


def report():
    return CompressionReport(
        "Comparison",
        "comparison",
        "completed",
        "B:/book",
        (
            ReportSection("Impact", ("Strategy", "Saved"), (("a|b`x", "512.00 MiB"),)),
            ReportSection("Details", ("Phase", "Seconds"), (("encoding", "1.23"),), verbose=True),
        ),
        ("Estimated, not guaranteed",),
    )


def test_markdown_keeps_details_without_ANSI_or_broken_cells():
    from compresser.markdown_report import render_markdown_report

    text = render_markdown_report(report())
    assert "512.00 MiB" in text and "1.23" in text and "completed" in text
    assert "a\\|b&#96;x" in text and "\x1b[" not in text


def workspace(tmp_path):
    from compresser.workspace import resolve_workspace, initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    result = resolve_workspace(target, None, owner="compresser")
    initialize_workspace(result)
    return result


def test_concurrent_reports_are_unique_and_latest_is_complete(tmp_path):
    from compresser.markdown_report import publish_markdown_report

    ws = workspace(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        reports = list(pool.map(lambda n: publish_markdown_report(ws, replace(report(), status=f"run{n}")), range(2)))
    assert reports[0].archive_path != reports[1].archive_path
    archives = [r.archive_path.read_text(encoding="utf-8") for r in reports]
    assert (ws.reports_dir / "latest.md").read_text(encoding="utf-8") in archives
    assert len(list(ws.reports_dir.glob("*-comparison.md"))) == 2
    assert not list(ws.reports_dir.glob("*.tmp"))


def test_latest_is_not_a_mutable_alias_of_archive(tmp_path):
    from compresser.markdown_report import publish_markdown_report

    files = publish_markdown_report(workspace(tmp_path), report())
    before = files.archive_path.read_bytes()
    files.latest_path.write_text("user annotation", encoding="utf-8")
    assert files.archive_path.read_bytes() == before


@pytest.mark.parametrize("failure", ["temp", "archive", "latest"])
def test_publication_failure_preserves_prior_latest_and_no_partials(tmp_path, monkeypatch, failure):
    import compresser.markdown_report as publisher

    ws = workspace(tmp_path)
    first = publisher.publish_markdown_report(ws, report())
    before = first.latest_path.read_bytes()

    def fail(*a, **k):
        raise PermissionError("simulated full/read-only disk")

    if failure == "temp":
        monkeypatch.setattr(publisher, "_write_temp", fail)
    elif failure == "archive":
        monkeypatch.setattr(publisher.os, "link", fail)
    else:
        monkeypatch.setattr(publisher.os, "replace", fail)
    with pytest.raises(OSError):
        publisher.publish_markdown_report(ws, replace(report(), status="partial"))
    assert first.latest_path.read_bytes() == before
    assert first.archive_path.read_bytes() == before
    assert not list(ws.reports_dir.glob("*.tmp"))
