from __future__ import annotations

from pathlib import Path

from jellyfin_doctor.monitor import monitor_log, monitor_scan_file


def test_monitor_scan_detects_completion(work_tmp: Path) -> None:
    log = work_tmp / "log_20260509_001.log"
    log.write_text('"Scan Media Library" Completed after 1 minute', encoding="utf-8")
    result = monitor_scan_file(log_file=log)
    assert result["status"] == "completed"
    assert result["exit_code"] == 0


def test_monitor_scan_detects_failure(work_tmp: Path) -> None:
    log = work_tmp / "log_20260509_001.log"
    log.write_text('"Scan Media Library" Aborted', encoding="utf-8")
    result = monitor_scan_file(log_file=log)
    assert result["status"] == "failed"
    assert result["exit_code"] == 1


def test_monitor_scan_timeout_when_no_terminal_state(work_tmp: Path) -> None:
    log = work_tmp / "log_20260509_001.log"
    log.write_text("scan still running", encoding="utf-8")
    result = monitor_scan_file(log_file=log, timeout_minutes=0)
    assert result["status"] == "timeout"
    assert result["exit_code"] == 2


def test_monitor_scan_missing_log() -> None:
    result = monitor_scan_file(log_file=Path("missing.log"))
    assert result["status"] == "missing_log"
    assert result["exit_code"] == 3


def test_monitor_log_pattern_ignore_case(work_tmp: Path) -> None:
    log = work_tmp / "log_20260509_001.log"
    log.write_text("DATABASE IS LOCKED\nok", encoding="utf-8")
    result = monitor_log(log_file=log, pattern="database is locked", ignore_case=True)
    assert result["status"] == "matched"
    assert result["matches"] == ["DATABASE IS LOCKED"]


