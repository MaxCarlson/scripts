from __future__ import annotations

from jellyfin_doctor.logs import analyze_lines, classify_line


def test_log_classification_detects_observed_failure_modes() -> None:
    lines = [
        "SQLite Error 5: 'database is locked'",
        "Optimizing and vacuuming jellyfin.db...",
        "jellyfin.db optimized successfully!",
        "SQLite Error 1: 'no such table: __EFMigrationsHistory'",
        'Found duplicate path: "D:\\Pictures\\Saved\\tmpvids\\stars"',
        'GET /Users/u/Items?StartIndex=0&Limit=100&ParentId=p&SortBy=IsFolder%2CSortName&SortOrder=Descending',
        '"Scan Media Library" Completed after 1 minute',
        "SubtitleResolver failed ffprobe on bad.srt",
    ]
    summary = analyze_lines(lines)
    assert summary.counts["sqlite_lock"] == 1
    assert summary.counts["optimize_start"] == 1
    assert summary.counts["optimize_success"] == 1
    assert summary.counts["migration_missing"] == 1
    assert summary.counts["duplicate_path"] == 1
    assert summary.counts["items_query"] == 1
    assert summary.counts["scan_completed"] == 1
    assert summary.counts["subtitle_ffprobe"] == 1
    assert "reset full" in summary.recommended_next_action


def test_scan_failure_classification_has_recommendation() -> None:
    findings = classify_line('"Scan Media Library" Failed after 2 minute(s)')
    assert findings[0].kind == "scan_failed"
    assert "Review nearby errors" in findings[0].recommendation


