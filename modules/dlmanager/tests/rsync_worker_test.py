#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rsync worker."""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Import the worker module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from dlmanager.workers.rsync_worker import build_rsync_cmd, parse_args


def test_build_rsync_cmd_local_copy():
    """Test building rsync command for local copy."""
    spec = {
        "src": "/source/path",
        "dst": "/dest/path",
        "dst_path": "/dest/subfolder",
        "replace": False,
        "delete_source": False,
        "resume": True,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    assert "rsync" in cmd
    assert "-a" in cmd
    assert "-h" in cmd
    assert "--info=progress2" in cmd
    assert "--ignore-existing" in cmd  # replace=False
    assert "--partial" in cmd  # resume=True
    assert "--append-verify" in cmd
    assert "/source/path" in cmd
    assert "/dest/subfolder" in cmd


def test_build_rsync_cmd_remote_ssh():
    """Test building rsync command for SSH remote transfer."""
    spec = {
        "src": "/local/files",
        "dst": "user@remote.host",
        "dst_path": "~/backup",
        "replace": True,
        "delete_source": False,
        "resume": True,
        "dry_run": False,
        "dst_os": "auto",
    }

    cmd = build_rsync_cmd(spec)

    assert "rsync" in cmd
    assert "/local/files" in cmd
    # Should combine dst and dst_path
    assert any("user@remote.host:~/backup" in arg for arg in cmd)


def test_build_rsync_cmd_with_replace():
    """Test that replace=True doesn't add --ignore-existing."""
    spec = {
        "src": "/src",
        "dst": "/dst",
        "dst_path": "/dst/path",
        "replace": True,  # Should NOT add --ignore-existing
        "delete_source": False,
        "resume": False,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    assert "--ignore-existing" not in cmd


def test_build_rsync_cmd_with_delete_source():
    """Test that delete_source=True adds --remove-source-files."""
    spec = {
        "src": "/src",
        "dst": "/dst",
        "dst_path": "/dst/path",
        "replace": False,
        "delete_source": True,
        "resume": False,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    assert "--remove-source-files" in cmd


def test_build_rsync_cmd_dry_run():
    """Test that dry_run=True adds --dry-run."""
    spec = {
        "src": "/src",
        "dst": "/dst",
        "dst_path": "/dst/path",
        "replace": False,
        "delete_source": False,
        "resume": False,
        "dry_run": True,
    }

    cmd = build_rsync_cmd(spec)

    assert "--dry-run" in cmd


def test_build_rsync_cmd_no_resume():
    """Test that resume=False doesn't add partial flags."""
    spec = {
        "src": "/src",
        "dst": "/dst",
        "dst_path": "/dst/path",
        "replace": False,
        "delete_source": False,
        "resume": False,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    assert "--partial" not in cmd
    assert "--append-verify" not in cmd


def test_build_rsync_cmd_cygwin_path_normalization():
    """Test path normalization for Windows Cygwin destination."""
    spec = {
        "src": "/local/files",
        "dst": "user@winhost",
        "dst_path": "C:\\Users\\user\\backup",
        "dst_os": "windows-cygwin",
        "replace": False,
        "delete_source": False,
        "resume": False,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    # Path should be converted to Cygwin format
    assert any("/cygdrive/c/Users/user/backup" in arg for arg in cmd)


def test_build_rsync_cmd_strips_trailing_slash():
    """Test that trailing slash is stripped from source."""
    spec = {
        "src": "/source/path/",  # Has trailing slash
        "dst": "/dest",
        "dst_path": "/dest/path",
        "replace": False,
        "delete_source": False,
        "resume": False,
        "dry_run": False,
    }

    cmd = build_rsync_cmd(spec)

    # Should strip trailing slash
    assert "/source/path" in cmd
    assert "/source/path/" not in cmd


def test_parse_args_with_job_file():
    """Test CLI argument parsing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        job_path = f.name

    try:
        sys.argv = ["rsync_worker.py", "-j", job_path]
        args = parse_args()
        assert args.job == job_path
    finally:
        Path(job_path).unlink(missing_ok=True)


def test_parse_args_long_form():
    """Test CLI argument parsing with long form."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        job_path = f.name

    try:
        sys.argv = ["rsync_worker.py", "--job", job_path]
        args = parse_args()
        assert args.job == job_path
    finally:
        Path(job_path).unlink(missing_ok=True)


@patch('dlmanager.workers.rsync_worker.subprocess.Popen')
@patch('dlmanager.workers.rsync_worker.iter_parsed_events')
def test_run_and_stream_success(mock_iter_events, mock_popen):
    """Test successful rsync run with progress events."""
    # Mock subprocess
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.wait.return_value = 0
    mock_popen.return_value = mock_proc

    # Mock parsed events from procparsers
    mock_events = [
        {"event": "progress", "percent": 50.0, "downloaded": 5000000, "total": 10000000, "speed_bps": 1000000},
        {"event": "file", "path": "/test/file.txt"},
        {"event": "progress", "percent": 100.0, "downloaded": 10000000, "total": 10000000, "speed_bps": 1000000},
    ]
    mock_iter_events.return_value = iter(mock_events)

    # Import here to use mocked modules
    from dlmanager.workers.rsync_worker import run_and_stream

    # Run the worker
    cmd = ["rsync", "-a", "/src", "/dst"]
    job_id = "test-job-123"

    with patch('dlmanager.workers.rsync_worker.emit') as mock_emit:
        ret = run_and_stream(cmd, job_id)

    # Verify return code
    assert ret == 0

    emit_calls = [call[1] for call in mock_emit.call_args_list]
    events = [call.get('event') for call in emit_calls]
    assert "start" in events
    assert "progress" in events
    assert "file" in events
    assert "finish" in events
    progress_events = [c for c in emit_calls if c.get("event") == "progress"]
    assert progress_events[0]["bytes_dl"] == 5_000_000
    assert progress_events[0]["total_bytes"] == 10_000_000
    assert progress_events[0]["status"] == "running"


@patch('dlmanager.workers.rsync_worker.subprocess.Popen')
@patch('dlmanager.workers.rsync_worker.iter_parsed_events')
def test_run_and_stream_failure(mock_iter_events, mock_popen):
    """Test rsync failure handling."""
    # Mock subprocess with non-zero exit
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.wait.return_value = 23  # rsync error code
    mock_popen.return_value = mock_proc

    # Mock parsed events
    mock_events = []
    mock_iter_events.return_value = iter(mock_events)

    from dlmanager.workers.rsync_worker import run_and_stream

    cmd = ["rsync", "-a", "/src", "/dst"]
    job_id = "test-job-fail"

    with patch('dlmanager.workers.rsync_worker.emit') as mock_emit:
        ret = run_and_stream(cmd, job_id)

    # Verify return code
    assert ret == 23

    # Verify finish event shows failure
    emit_calls = [call[1] for call in mock_emit.call_args_list]
    finish_events = [call for call in emit_calls if call.get('event') == 'finish']
    assert len(finish_events) > 0
    assert finish_events[0].get('status') == 'failed'
    assert finish_events[0].get('returncode') == 23


@patch('dlmanager.workers.rsync_worker.subprocess.Popen')
@patch('dlmanager.workers.rsync_worker.iter_parsed_events')
def test_run_and_stream_skips_heartbeats(mock_iter_events, mock_popen):
    """Test that heartbeat events are filtered out."""
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.wait.return_value = 0
    mock_popen.return_value = mock_proc

    # Include heartbeat events that should be filtered
    mock_events = [
        {"event": "heartbeat", "tool": "rsync"},  # Should be skipped
        {"event": "progress", "percent": 50.0},
        {"event": "heartbeat", "tool": "rsync"},  # Should be skipped
        {"event": "progress", "percent": 100.0},
    ]
    mock_iter_events.return_value = iter(mock_events)

    from dlmanager.workers.rsync_worker import run_and_stream

    cmd = ["rsync", "-a", "/src", "/dst"]
    job_id = "test-job-heartbeat"

    with patch('dlmanager.workers.rsync_worker.emit') as mock_emit:
        ret = run_and_stream(cmd, job_id)

    # Verify heartbeat events were not emitted
    emit_calls = [call[1] for call in mock_emit.call_args_list]
    events = [call.get('event') for call in emit_calls]
    assert "heartbeat" not in events
    # But progress events should be there
    assert events.count("progress") == 2
