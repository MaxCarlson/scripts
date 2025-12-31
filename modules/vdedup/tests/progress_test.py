import time

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


def test_add_score_sample_updates_histogram() -> None:
    reporter = ProgressReporter(enable_dash=False)
    reporter.add_score_sample(0.2, detector="subset-phash", penalties=["duration_mismatch"])
    reporter.add_score_sample(0.8, detector="subset-scene")
    assert reporter.score_histogram["0-0.25"] == 1
    assert reporter.score_histogram["0.75-1.0"] == 1
    assert reporter.detector_counts["subset-phash"] == 1
    assert reporter.low_confidence == 1
    assert reporter.penalty_counts["duration_mismatch"] == 1


def test_log_storage_and_filters() -> None:
    reporter = ProgressReporter(enable_dash=False)
    reporter.add_log("info", "INFO", source="PIPE")
    reporter.add_log("warn", "WARNING", source="PIPE")
    reporter.add_log("error", "ERROR", source="PIPE")
    entries = reporter.recent_logs()
    assert entries[-1][3] == "PIPE"
    reporter._log_page_size = 2
    reporter._set_log_level(1)
    assert reporter._log_level == 1
    # Add enough logs to exercise the scroll bounds.
    for idx in range(4):
        reporter.add_log(f"err-{idx}", "ERROR")
    reporter._scroll_logs(1)
    assert reporter._log_scroll == reporter._log_page_size
    reporter._scroll_logs(-1)
    assert reporter._log_scroll == 0


def test_stage_stall_detector_emits_warning() -> None:
    reporter = ProgressReporter(enable_dash=False)
    reporter._stage_stall_threshold = 0.05
    reporter.stage_name = "Q2 FULL HASH"
    reporter._stage_activity_ts = time.time() - 0.1
    reporter._check_stage_stall()
    logs = reporter.recent_logs()
    assert logs[-1][3] == "WATCHDOG"
    last_count = len(logs)
    # second call without new activity should not duplicate warning
    reporter._check_stage_stall()
    assert len(reporter.recent_logs()) == last_count
