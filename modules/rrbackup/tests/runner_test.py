"""Tests for rrbackup.runner module."""
from __future__ import annotations

import os
import pathlib
from unittest.mock import MagicMock, mock_open

import pytest

from rrbackup.config import BackupSet, Retention, Settings
from rrbackup.runner import (
    RunError,
    _env_for_repo,
    _logfile,
    _now_stamp,
    _pidfile,
    _repo_url,
    list_snapshots,
    repo_stats,
    run_check,
    run_forget_prune,
    run_restic,
    show_in_progress,
    start_backup,
)


@pytest.mark.unit
class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_now_stamp_format(self):
        """Test timestamp format is YYYYMMDD-HHMMSS."""
        stamp = _now_stamp()

        assert len(stamp) == 15
        assert stamp[8] == "-"
        assert stamp[:8].isdigit()
        assert stamp[9:].isdigit()

    def test_logfile_path(self, sample_settings):
        """Test log file path generation."""
        logfile = _logfile(sample_settings, "backup")

        assert "backup" in str(logfile)
        assert ".log" in str(logfile)
        assert sample_settings.log_dir in str(logfile)

    def test_pidfile_path(self, sample_settings):
        """Test PID file path generation."""
        pidfile = _pidfile(sample_settings, "backup-docs")

        assert "running-backup-docs.pid" in str(pidfile)
        assert sample_settings.state_dir in str(pidfile)

    def test_repo_url(self, sample_settings):
        """Test repository URL extraction."""
        url = _repo_url(sample_settings)

        assert url == sample_settings.repo.url


@pytest.mark.unit
class TestEnvForRepo:
    """Tests for _env_for_repo function."""

    def test_env_with_password_file(self, sample_settings):
        """Test environment setup with password file."""
        env = _env_for_repo(sample_settings)

        assert "RESTIC_PASSWORD_FILE" in env
        assert env["RESTIC_PASSWORD_FILE"] == sample_settings.repo.password_file

    def test_env_with_password_env(self, sample_settings, monkeypatch):
        """Test environment setup with password environment variable."""
        monkeypatch.setenv("MY_RESTIC_PWD", "secret123")
        sample_settings.repo.password_file = None
        sample_settings.repo.password_env = "MY_RESTIC_PWD"

        env = _env_for_repo(sample_settings)

        assert "RESTIC_PASSWORD" in env
        assert env["RESTIC_PASSWORD"] == "secret123"

    def test_env_missing_password_env_raises_error(self, sample_settings, monkeypatch):
        """Test error when password env var not set."""
        monkeypatch.delenv("MY_PASSWORD", raising=False)
        sample_settings.repo.password_file = None
        sample_settings.repo.password_env = "MY_PASSWORD"

        with pytest.raises(RunError, match="Password env.*not present"):
            _env_for_repo(sample_settings)

    def test_env_no_repo_raises_error(self):
        """Test error when no repository configured."""
        settings = Settings()

        with pytest.raises(RunError, match="Repository not configured"):
            _env_for_repo(settings)


@pytest.mark.unit
class TestRunRestic:
    """Tests for run_restic function."""

    def test_run_restic_success(self, sample_settings, mocker, temp_dir):
        """Test successful restic command execution."""
        # Mock subprocess.Popen
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(side_effect=[b"output line\n", b""])
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        # Mock file opening
        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        result = run_restic(sample_settings, ["snapshots"], log_prefix="test")

        assert result == 0
        mock_popen.assert_called_once()

        # Check command arguments
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0] == sample_settings.restic_bin
        assert "-r" in cmd
        assert "snapshots" in cmd

    def test_run_restic_failure_raises_error(self, sample_settings, mocker, temp_dir):
        """Test failed restic command raises RunError."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=1)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        with pytest.raises(RunError, match="Command failed.*rc=1"):
            run_restic(sample_settings, ["backup"], log_prefix="test")

    def test_run_restic_creates_log_file(self, sample_settings, mocker, temp_dir):
        """Test log file is created for restic command."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mock_open_call = mocker.patch("pathlib.Path.open", mock_file)

        run_restic(sample_settings, ["check"], log_prefix="check")

        # Verify file was opened for writing
        mock_open_call.assert_called()
        call_args = mock_open_call.call_args[0]
        assert call_args[0] == "wb"


@pytest.mark.unit
class TestStartBackup:
    """Tests for start_backup function."""

    def test_start_backup_creates_pid_file(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test PID file is created during backup."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.unlink")
        mock_write_text = mocker.patch("pathlib.Path.write_text")

        start_backup(sample_settings, sample_backup_set, name_hint="test")

        # Verify PID was written
        mock_write_text.assert_called()

    def test_start_backup_includes_tags(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test backup includes configured tags."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.unlink")

        sample_backup_set.tags = ["important", "daily"]
        start_backup(sample_settings, sample_backup_set)

        # Check command includes tags
        call_args = mock_popen.call_args[0][0]
        assert "--tag" in call_args
        assert "important" in call_args
        assert "daily" in call_args

    def test_start_backup_includes_excludes(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test backup includes exclude patterns."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.unlink")

        sample_backup_set.exclude = ["**/.git", "**/__pycache__"]
        start_backup(sample_settings, sample_backup_set)

        call_args = mock_popen.call_args[0][0]
        assert "--exclude" in call_args
        assert "**/.git" in call_args

    def test_start_backup_dry_run(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test dry-run mode is passed to restic."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.unlink")

        sample_backup_set.dry_run_default = True
        start_backup(sample_settings, sample_backup_set)

        call_args = mock_popen.call_args[0][0]
        assert "--dry-run" in call_args

    def test_start_backup_one_file_system(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test --one-file-system flag is passed when enabled."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.unlink")

        sample_backup_set.one_fs = True
        start_backup(sample_settings, sample_backup_set)

        call_args = mock_popen.call_args[0][0]
        assert "--one-file-system" in call_args

    def test_start_backup_cleans_up_pid_on_error(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test PID file is cleaned up even on error."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=1)  # Simulate failure
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mock_write_text = mocker.patch("pathlib.Path.write_text")
        mock_unlink = mocker.patch("pathlib.Path.unlink")

        with pytest.raises(RunError):
            start_backup(sample_settings, sample_backup_set)

        # PID file should be unlinked
        mock_unlink.assert_called()


@pytest.mark.unit
class TestListSnapshots:
    """Tests for list_snapshots function."""

    def test_list_snapshots_no_filters(self, sample_settings, mocker, temp_dir):
        """Test listing snapshots without filters."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        list_snapshots(sample_settings)

        call_args = mock_popen.call_args[0][0]
        assert "snapshots" in call_args

    def test_list_snapshots_with_filters(self, sample_settings, mocker, temp_dir):
        """Test listing snapshots with extra filters."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        list_snapshots(sample_settings, extra_args=["--tag", "important"])

        call_args = mock_popen.call_args[0][0]
        assert "--tag" in call_args
        assert "important" in call_args


@pytest.mark.unit
class TestRepoStats:
    """Tests for repo_stats function."""

    def test_repo_stats(self, sample_settings, mocker, temp_dir):
        """Test repository stats command."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        repo_stats(sample_settings)

        call_args = mock_popen.call_args[0][0]
        assert "stats" in call_args
        assert "--mode" in call_args
        assert "restore-size" in call_args


@pytest.mark.unit
class TestRunCheck:
    """Tests for run_check function."""

    def test_run_check(self, sample_settings, mocker, temp_dir):
        """Test integrity check command."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        run_check(sample_settings)

        call_args = mock_popen.call_args[0][0]
        assert "check" in call_args


@pytest.mark.unit
class TestRunForgetPrune:
    """Tests for run_forget_prune function."""

    def test_forget_prune_with_retention(self, sample_settings, mocker, temp_dir):
        """Test forget/prune with retention policy."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        sample_settings.retention = Retention(
            keep_last=5,
            keep_daily=7,
            keep_weekly=4,
            keep_monthly=6,
            keep_yearly=2,
        )

        run_forget_prune(sample_settings)

        call_args = mock_popen.call_args[0][0]
        assert "forget" in call_args
        assert "--prune" in call_args
        assert "--keep-last" in call_args
        assert "--keep-daily" in call_args
        assert "--keep-weekly" in call_args
        assert "--keep-monthly" in call_args
        assert "--keep-yearly" in call_args

    def test_forget_prune_skips_none_values(self, sample_settings, mocker, temp_dir):
        """Test forget/prune skips None retention values."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        sample_settings.retention = Retention(
            keep_daily=7,
            keep_hourly=None,  # Should be skipped
        )

        run_forget_prune(sample_settings)

        call_args = mock_popen.call_args[0][0]
        assert "--keep-hourly" not in call_args
        assert "--keep-daily" in call_args


@pytest.mark.unit
class TestShowInProgress:
    """Tests for show_in_progress function."""

    def test_show_in_progress_no_pidfiles(self, sample_settings, mocker, temp_dir, capsys):
        """Test progress display with no active tasks."""
        mocker.patch("pathlib.Path.glob", return_value=[])

        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        show_in_progress(sample_settings)

        captured = capsys.readouterr()
        assert "No rrbackup PID files found" in captured.out

    def test_show_in_progress_with_pidfiles(self, sample_settings, mocker, temp_dir, capsys):
        """Test progress display with active tasks."""
        # Mock PID file
        mock_pidfile = MagicMock()
        mock_pidfile.name = "running-backup-docs.pid"
        mock_pidfile.read_text = MagicMock(return_value="12345")

        mocker.patch("pathlib.Path.glob", return_value=[mock_pidfile])

        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        show_in_progress(sample_settings)

        captured = capsys.readouterr()
        assert "in-progress" in captured.out
        assert "12345" in captured.out


@pytest.mark.unit
class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_backup_with_missing_include_paths(self, sample_settings, sample_backup_set, mocker, temp_dir):
        """Test backup proceeds even if include paths don't exist (restic handles this)."""
        sample_backup_set.include = ["/nonexistent/path"]

        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value=b"")
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path.write_text")
        mocker.patch("pathlib.Path.unlink")

        # Should not raise error - restic will handle missing paths
        start_backup(sample_settings, sample_backup_set)

    def test_restic_timeout_handling(self, sample_settings, mocker, temp_dir):
        """Test handling of long-running restic commands."""
        # Simulate very long output
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(side_effect=[b"line\n"] * 1000 + [b""])
        mock_proc.wait = MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)

        # Should handle large output without issue
        result = run_restic(sample_settings, ["backup", "/tmp"], log_prefix="test")
        assert result == 0
