"""Unit tests for Phase 3 periodicity, burst, and baseline analyzer (`patterns`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from procwatch.analyzers.patterns import (
    compare_incident_windows,
    compute_pattern_summaries,
    normalize_command_signature,
)
from procwatch.cli import main
from procwatch.models import IncidentRecord
from procwatch.storage import FlightRecorderStorage


def test_signature_normalization_preserves_distinct_commands() -> None:
    s1 = normalize_command_signature("python.exe", r"python.exe C:\Users\x\AppData\Local\Temp\run12345.py --pid 9999")
    s2 = normalize_command_signature("python.exe", r"python.exe C:\Users\x\AppData\Local\Temp\run67890.py --pid 1111")
    s3 = normalize_command_signature("python.exe", "python.exe sync_db.py")
    assert s1 == s2
    assert s1 != s3


def test_periodic_10s_detection_and_duplicate_filtering() -> None:
    base = datetime(2026, 11, 15, 10, 0, 0, tzinfo=UTC)
    incidents = []
    # 6 launches ~10s apart with slight jitter + one near-simultaneous duplicate (0.01s)
    offsets = [0.0, 0.01, 10.1, 20.0, 30.2, 40.0, 50.1]
    for idx, off in enumerate(offsets):
        ts = (base + timedelta(seconds=off)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        incidents.append(
            {
                "incident_id": idx + 1,
                "created_ts_utc": ts,
                "category": "visible_popup",
                "image_name": "python.exe",
                "cmdline_redacted": "python.exe poll.py",
            }
        )

    patterns = compute_pattern_summaries(incidents)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.observed_count == 7
    assert p.popup_count == 7
    assert p.is_periodic is True
    assert p.median_interval_seconds is not None
    assert 9.5 <= p.median_interval_seconds <= 10.5
    assert p.confidence == "high"


def test_baseline_comparison_and_insufficient_coverage_flag() -> None:
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
    # 10 incidents in baseline (-2h..-1h), 0 in current (-1h..now)
    incidents = [
        {
            "incident_id": i + 1,
            "created_ts_utc": (now - timedelta(hours=1, minutes=5 + i * 2)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "category": "visible_popup",
            "image_name": "cmd.exe",
            "cmdline_redacted": "cmd.exe /c check.bat",
        }
        for i in range(10)
    ]

    improved = compare_incident_windows(
        incidents,
        now_utc=now,
        window_seconds=3600.0,
        baseline_seconds=3600.0,
        collector_active=True,
    )
    assert improved.outcome == "improved"
    assert improved.baseline_count == 10
    assert improved.current_count == 0

    # Same 0 current events, but collector inactive -> must report insufficient_coverage!
    uncertain = compare_incident_windows(
        incidents,
        now_utc=now,
        window_seconds=3600.0,
        baseline_seconds=3600.0,
        collector_active=False,
    )
    assert uncertain.outcome == "insufficient_coverage"
    assert uncertain.coverage_warning is not None


def test_analyze_cli_json_deterministic(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "analyze.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        now = datetime.now(UTC)
        for i in range(4):
            ts = (now - timedelta(seconds=30 * (i + 1))).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            storage.insert_incident(
                IncidentRecord(
                    created_ts_utc=ts,
                    category="visible_popup",
                    summary_text="python.exe heartbeat.py",
                )
            )
    finally:
        storage.close()

    assert main(["analyze", "-w", "3600", "-b", "24h", "-j", "-D", str(db_path)]) == 0
    out1 = json.loads(capsys.readouterr().out)
    assert main(["analyze", "-w", "3600", "-b", "24h", "-j", "-D", str(db_path)]) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out1["schema_version"] == 1
    assert out1["current_count"] == 4
    assert out1["patterns"] == out2["patterns"]
