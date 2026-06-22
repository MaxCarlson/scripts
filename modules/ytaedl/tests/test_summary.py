"""Tests for the ytaedl summary subcommand and instance stats logic."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import ytaedl.manager as manager
import ytaedl.summary as summary


def test_write_instance_stats(tmp_path: Path) -> None:
    stats_dir = tmp_path / "archive" / "instance_stats"
    t0 = time.time() - 3600
    
    # Mock some worker states
    ws1 = MagicMock()
    ws1.proc = MagicMock()
    ws1.proc.poll.return_value = None
    ws1.urlfile = tmp_path / "stars" / "urls1.txt"
    ws1.is_waiting_urlfile_lock = False
    ws1.is_paused = False
    ws1.assign_t0 = t0 + 1800
    
    ws2 = MagicMock()
    ws2.proc = None
    ws2.urlfile = None
    
    workers = [ws1, ws2]
    
    manager._write_instance_stats(
        stats_dir,
        t0,
        workers,
        total_completed_urls=5,
        avg_speed_bps=1000000.0,
        total_speed_bps=500000.0,
    )
    
    active_file = stats_dir / f"active_manager_{os.getpid()}.json"
    assert active_file.exists()
    
    data = json.loads(active_file.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert data["workers_count"] == 2
    assert data["active_workers_count"] == 1
    assert data["finished_count"] == 5
    assert data["average_speed_bps"] == 1000000.0
    assert data["locks_held"] == [{
        "file_path": str(ws1.urlfile.resolve()),
        "time_held_seconds": pytest.approx(time.time() - ws1.assign_t0, abs=5),
    }]


def test_archive_instance_stats(tmp_path: Path) -> None:
    stats_dir = tmp_path / "archive" / "instance_stats"
    t0 = time.time() - 3600
    
    # Create active file
    stats_dir.mkdir(parents=True, exist_ok=True)
    active_file = stats_dir / f"active_manager_{os.getpid()}.json"
    active_file.write_text(json.dumps({"finished_count": 5}), encoding="utf-8")
    
    manager._archive_instance_stats(stats_dir, t0)
    
    assert not active_file.exists()
    
    stats_archive_dir = stats_dir / "stats_archive"
    assert stats_archive_dir.exists()
    
    archived_files = list(stats_archive_dir.glob("ended_*.json"))
    assert len(archived_files) == 1
    
    archived_file = archived_files[0]
    data = json.loads(archived_file.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert data["finished_count"] == 5
    assert data["runtime_seconds"] == pytest.approx(3600, abs=5)


def test_prune_instance_stats(tmp_path: Path) -> None:
    stats_dir = tmp_path / "archive" / "instance_stats"
    stats_archive_dir = stats_dir / "stats_archive"
    stats_archive_dir.mkdir(parents=True, exist_ok=True)
    
    # Create 10 active files and 45 archived files (total 55)
    for i in range(10):
        (stats_dir / f"active_manager_{i}.json").write_text("{}", encoding="utf-8")
        
    for i in range(45):
        # Format ended_YYYYMMDD_HHMMSS
        # Pad i to ensure alphabetical sorting matches creation age
        ended_str = f"20260622_1200{i:02d}"
        (stats_archive_dir / f"ended_{ended_str}_started_20260622_110000_{i}.json").write_text("{}", encoding="utf-8")
        
    # Prune
    manager._prune_instance_stats(stats_dir)
    
    active_files = list(stats_dir.glob("active_manager_*.json"))
    archived_files = list(stats_archive_dir.glob("ended_*.json"))
    
    # Total count should be pruned down to exactly 50
    # Active files must not be deleted (still 10)
    # Archived files should be pruned from 45 down to 40
    assert len(active_files) == 10
    assert len(archived_files) == 40
    
    # The oldest archived files (smallest indices 0 to 4) should have been deleted
    # The remaining archived files should have index >= 5
    for i in range(5):
        ended_str = f"20260622_1200{i:02d}"
        assert not (stats_archive_dir / f"ended_{ended_str}_started_20260622_110000_{i}.json").exists()
        
    for i in range(5, 45):
        ended_str = f"20260622_1200{i:02d}"
        assert (stats_archive_dir / f"ended_{ended_str}_started_20260622_110000_{i}.json").exists()


def test_process_exists_helper() -> None:
    # Test active PID (current process)
    assert summary.process_exists(os.getpid())
    
    # Test very large PID that is highly unlikely to exist
    assert not summary.process_exists(999999)


def test_summary_main_formatting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stats_dir = tmp_path / "archive" / "instance_stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    
    # Write one active file
    active_file = stats_dir / f"active_manager_{os.getpid()}.json"
    active_payload = {
        "pid": os.getpid(),
        "start_time": "2026-06-22T14:00:00",
        "last_updated": "2026-06-22T14:15:00",
        "runtime_seconds": 900.0,
        "workers_count": 4,
        "active_workers_count": 2,
        "finished_count": 12,
        "average_speed_bps": 10485760.0, # 10 MiB/s
        "avg_url_speed_bps": 2621440.0,  # 2.5 MiB/s
        "current_speed_bps": 20971520.0, # 20 MiB/s
        "locks_held": [
            {
                "file_path": str(tmp_path / "stars" / "urlfile1.txt"),
                "time_held_seconds": 300.0,
            },
            {
                "file_path": str(tmp_path / "ae-stars" / "urlfile2.txt"),
                "time_held_seconds": 150.0,
            }
        ]
    }
    active_file.write_text(json.dumps(active_payload), encoding="utf-8")
    
    # Write a stale active file (PID doesn't exist, will be archived during main)
    stale_file = stats_dir / "active_manager_999999.json"
    stale_payload = {
        "pid": 999999,
        "start_time": "2026-06-22T12:00:00",
        "last_updated": "2026-06-22T12:05:00",
        "runtime_seconds": 300.0,
        "workers_count": 2,
        "active_workers_count": 0,
        "finished_count": 3,
        "average_speed_bps": 0.0,
        "avg_url_speed_bps": 0.0,
        "current_speed_bps": 0.0,
        "locks_held": []
    }
    stale_file.write_text(json.dumps(stale_payload), encoding="utf-8")
    
    # Set the file modification time for the stale file to be old
    old_time = time.time() - 3600
    os.utime(stale_file, (old_time, old_time))
    
    rc = summary.main(["-a", str(tmp_path / "archive")])
    assert rc == 0
    
    # The stale file should have been archived and deleted from the active folder
    assert not stale_file.exists()
    archived_files = list((stats_dir / "stats_archive").glob("*999999.json"))
    assert len(archived_files) == 1
    
    # Capture printout
    captured = capsys.readouterr().out
    assert "instances" in captured
    assert "ytaedl_instance_1" in captured
    assert "4" in captured # workers
    assert "12" in captured # finished downloads
    assert "10.00MiB/s" in captured # average download speed
    assert "2.50MiB/s" in captured # avg url dl speed
    assert "20.00MiB/s" in captured # current dl speed
    assert "locks and times held:" in captured
    assert "stars/" in captured
    assert "urlfile1.txt" in captured
    assert "ae-stars/" in captured
    assert "urlfile2.txt" in captured
