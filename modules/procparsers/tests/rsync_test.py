#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rsync parser."""
import math
from procparsers.rsync import parse_line


def test_progress_line_basic():
    """Test parsing typical rsync --info=progress2 line."""
    line = "1,234,567  12%   12.34MB/s    0:01:23 (xfr#5, to-chk=10/123)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 1234567
    assert d["percent"] == 12.0
    assert math.isclose(d["speed_bps"], 12.34 * 1024 * 1024, rel_tol=1e-3)
    assert d["eta_s"] == 83  # 1*60 + 23 seconds
    assert d["files_done"] == 113  # 123 - 10
    assert d["files_total"] == 123
    assert d["xfr_number"] == 5


def test_progress_line_kb_speed():
    """Test parsing with KB/s speed unit."""
    line = "524,288  5%   512KB/s    0:00:45 (xfr#1, to-chk=50/100)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 524288
    assert d["percent"] == 5.0
    assert d["speed_bps"] == 512 * 1024
    assert d["eta_s"] == 45
    assert d["files_done"] == 50
    assert d["files_total"] == 100


def test_progress_line_gb_speed():
    """Test parsing with GB/s speed (high-bandwidth transfer)."""
    line = "10,737,418,240  50%   1.50GB/s    0:10:00 (xfr#100, to-chk=500/1000)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 10737418240
    assert d["percent"] == 50.0
    assert math.isclose(d["speed_bps"], 1.50 * 1024 ** 3, rel_tol=1e-3)
    assert d["eta_s"] == 600  # 10 minutes
    assert d["files_done"] == 500
    assert d["files_total"] == 1000


def test_progress_line_no_comma_separators():
    """Test parsing line without comma separators in bytes."""
    line = "1234567  12%   12.34MB/s    0:01:23 (xfr#5, to-chk=10/123)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 1234567


def test_file_line_simple_path():
    """Test parsing simple file path line."""
    line = "path/to/file.txt"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "file"
    assert d["path"] == "path/to/file.txt"


def test_file_line_with_itemize():
    """Test parsing file line with itemize-changes prefix."""
    line = ">f+++++++++ documents/report.pdf"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "file"
    assert "report.pdf" in d["path"]


def test_summary_files_transferred():
    """Test parsing files transferred summary line."""
    line = "Number of files transferred: 42"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "summary"
    assert d["files_transferred"] == 42


def test_summary_total_size():
    """Test parsing total size summary line."""
    line = "total size is 1,234,567,890"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "summary"
    assert d["total_size"] == 1234567890


def test_skip_known_non_file_lines():
    """Test that known non-file lines return None."""
    lines = [
        "sending incremental file list",
        "receiving incremental file list",
        "sent 1234 bytes  received 5678 bytes",
        "total size is 1234567",
        "speedup is 10.00",
        "building file list ... done",
        "deleting file.txt",
    ]
    for line in lines:
        d = parse_line(line)
        # These should either return None or specific summary events
        if d is not None:
            assert d["event"] in ["summary"]


def test_skip_error_lines():
    """Test that error/warning lines return None."""
    lines = [
        "rsync: failed to open file: Permission denied",
        "[sender] skipping directory file",
        "WARNING: some warning message",
        "ERROR: connection failed",
    ]
    for line in lines:
        d = parse_line(line)
        assert d is None


def test_empty_line_returns_none():
    """Test that empty lines return None."""
    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("\n") is None


def test_ansi_codes_stripped():
    """Test that ANSI color codes are properly stripped."""
    line = "\x1b[32m1,234,567  12%   12.34MB/s    0:01:23 (xfr#5, to-chk=10/123)\x1b[0m"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["downloaded"] == 1234567


def test_progress_line_zero_eta():
    """Test parsing progress line with 0:00:00 ETA (near completion)."""
    line = "10,000,000  99%   5.00MB/s    0:00:00 (xfr#20, to-chk=0/20)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["percent"] == 99.0
    assert d["eta_s"] == 0
    assert d["files_done"] == 20
    assert d["files_total"] == 20


def test_progress_line_long_eta():
    """Test parsing progress line with long ETA (hours)."""
    line = "100,000  1%   100KB/s    2:30:45 (xfr#1, to-chk=999/1000)"
    d = parse_line(line)
    assert d is not None
    assert d["event"] == "progress"
    assert d["eta_s"] == 2 * 3600 + 30 * 60 + 45  # 2 hours 30 minutes 45 seconds
