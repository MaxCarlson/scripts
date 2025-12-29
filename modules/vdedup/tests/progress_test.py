from rich.text import Text

from vdedup.progress import ProgressReporter


def test_progress_bar_returns_rich_text() -> None:
    reporter = ProgressReporter(enable_dash=False)
    bar = reporter._progress_bar(42.5)
    assert isinstance(bar, Text)
    assert "[green]" not in bar.plain
    assert "%" in bar.plain


def test_stage_extension_request_updates_plan() -> None:
    reporter = ProgressReporter(enable_dash=False)
    reporter.set_stage_plan(["discovering files", "scanning files"])
    reporter.set_stage_ceiling(2)
    assert reporter.request_stage_extension() is True
    additions = reporter.consume_stage_extensions(2)
    assert additions == [3]
    reporter.append_stage_entries(["Q3 metadata"])
    stage_names = [entry["display"] for entry in reporter.stage_records.values()]
    assert "Q3 metadata" in stage_names
