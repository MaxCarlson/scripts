#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rclone parser."""
import json
import math
from procparsers.rclone import parse_line


def test_stats_line_full():
    """Test parsing full rclone stats line with total and ETA."""
    line = "Transferred:   	    1.234 GiB / 10 GiB, 12%, 12.34 MiB/s, ETA 1m23s"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert math.isclose(d["downloaded"], 1.234 * 1024 ** 3, rel_tol=1e-3)
    assert math.isclose(d["total"], 10 * 1024 ** 3, rel_tol=1e-3)
    assert d["percent"] == 12.0
    assert math.isclose(d["speed_bps"], 12.34 * 1024 ** 2, rel_tol=1e-3)
    assert d["eta_s"] == 83  # 1 minute 23 seconds


def test_stats_line_mb_units():
    """Test parsing with MB (decimal) units."""
    line = "Transferred:   	    500 MB / 2 GB, 25%, 10.5 MB/s, ETA 2m30s"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 500 * 1000 ** 2
    assert d["total"] == 2 * 1000 ** 3
    assert d["percent"] == 25.0
    assert math.isclose(d["speed_bps"], 10.5 * 1000 ** 2, rel_tol=1e-3)
    assert d["eta_s"] == 150  # 2 minutes 30 seconds


def test_stats_line_hours_eta():
    """Test parsing ETA with hours."""
    line = "Transferred:   	    1 GiB / 100 GiB, 1%, 5 MiB/s, ETA 1h2m3s"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["eta_s"] == 3600 + 120 + 3  # 1 hour 2 minutes 3 seconds


def test_stats_line_no_eta():
    """Test parsing stats line with dash ETA (unknown)."""
    line = "Transferred:   	    100 KiB / 1 MiB, 10%, 50 KiB/s, ETA -"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 100 * 1024
    assert d["total"] == 1 * 1024 ** 2
    assert d["eta_s"] is None


def test_progress_line_no_total():
    """Test parsing simpler progress line without total."""
    line = "Transferred:   	    1.5 GiB, 25 MiB/s"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert math.isclose(d["downloaded"], 1.5 * 1024 ** 3, rel_tol=1e-3)
    assert d["total"] is None
    assert math.isclose(d["speed_bps"], 25 * 1024 ** 2, rel_tol=1e-3)
    assert d["eta_s"] is None


def test_file_operation_copied():
    """Test parsing file operation log (Copied)."""
    line = "INFO  : file.txt: Copied (new)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "file"
    assert d["path"] == "file.txt"
    assert "Copied" in d["action"]


def test_file_operation_moved():
    """Test parsing file operation log (Moved)."""
    line = "NOTICE: documents/report.pdf: Moved (server-side)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "file"
    assert "report.pdf" in d["path"]
    assert "Moved" in d["action"]


def test_json_stats_output():
    """Test parsing JSON stats from --log-format json."""
    json_line = json.dumps({
        "level": "info",
        "time": "2024-10-15T12:34:56",
        "stats": {
            "bytes": 1234567890,
            "totalBytes": 10000000000,
            "speed": 12345678.0,
            "eta": 120
        }
    })
    d = parse_line(json_line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 1234567890
    assert d["total"] == 10000000000
    assert math.isclose(d["percent"], 12.34567890, rel_tol=1e-3)
    assert d["speed_bps"] == 12345678.0
    assert d["eta_s"] == 120


def test_json_file_operation():
    """Test parsing JSON file operation log."""
    json_line = json.dumps({
        "level": "info",
        "msg": "Copied (new)",
        "source": "path/to/file.txt"
    })
    d = parse_line(json_line)
    assert d is not None
    assert d["event"] == "file"
    assert d["path"] == "path/to/file.txt"
    assert "Copied" in d["action"]


def test_json_stats_without_eta():
    """Test parsing JSON stats without ETA field."""
    json_line = json.dumps({
        "stats": {
            "bytes": 500000,
            "totalBytes": 1000000,
            "speed": 100000.0
        }
    })
    d = parse_line(json_line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 500000
    assert d["total"] == 1000000
    assert d["percent"] == 50.0
    assert d["eta_s"] is None


def test_invalid_json_fallback_to_text():
    """Test that invalid JSON falls back to text parsing."""
    line = "{invalid json} Transferred: 100 MiB / 1 GiB, 10%, 5 MiB/s, ETA 1m"
    # Should not crash, might return None if neither JSON nor text patterns match
    d = parse_line(line)
    # This specific malformed input won't match text patterns either
    assert d is None


def test_empty_line_returns_none():
    """Test that empty lines return None."""
    assert parse_line("") is None
    assert parse_line("   ") is None


def test_non_matching_line_returns_none():
    """Test that non-matching lines return None."""
    lines = [
        "Starting rclone copy...",
        "ERROR: some error message",
        "2024/10/15 12:34:56 DEBUG: some debug info",
        "Checks: 0 / 100, 0%",  # Different format
    ]
    for line in lines:
        d = parse_line(line)
        assert d is None


def test_ansi_codes_stripped():
    """Test that ANSI color codes are properly stripped."""
    line = "\x1b[32mTransferred:   	    1 GiB / 10 GiB, 10%, 10 MiB/s, ETA 1m\x1b[0m"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["percent"] == 10.0


def test_eta_variations():
    """Test various ETA format variations."""
    test_cases = [
        ("ETA 45s", 45),
        ("ETA 1m", 60),
        ("ETA 2m30s", 150),
        ("ETA 1h", 3600),
        ("ETA 1h30m", 5400),
        ("ETA 2h15m30s", 8130),
    ]
    for eta_str, expected_seconds in test_cases:
        line = f"Transferred:   	    1 GiB / 10 GiB, 10%, 10 MiB/s, {eta_str}"
        d = parse_line(line)
        assert d is not None
        assert d["eta_s"] == expected_seconds, f"Failed for {eta_str}"


def test_binary_vs_decimal_units():
    """Test that binary (GiB) and decimal (GB) units are handled correctly."""
    # Binary units (1024-based)
    line_binary = "Transferred:   	    1 GiB / 10 GiB, 10%, 1 MiB/s, ETA 1m"
    d_binary = parse_line(line_binary)
    assert d_binary["downloaded"] == 1024 ** 3
    assert d_binary["total"] == 10 * 1024 ** 3
    assert d_binary["speed_bps"] == 1024 ** 2

    # Decimal units (1000-based)
    line_decimal = "Transferred:   	    1 GB / 10 GB, 10%, 1 MB/s, ETA 1m"
    d_decimal = parse_line(line_decimal)
    assert d_decimal["downloaded"] == 1000 ** 3
    assert d_decimal["total"] == 10 * 1000 ** 3
    assert d_decimal["speed_bps"] == 1000 ** 2
