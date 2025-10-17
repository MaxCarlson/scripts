"""Pytest fixtures and configuration for rrbackup tests."""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
from typing import Any

import pytest

from rrbackup.config import (
    BackupSet,
    Repo,
    RetentionPolicy,
    Schedule,
    Settings,
    platform_config_default,
)


# ==================== Environment Detection ====================


def check_user_config_exists() -> bool:
    """Check if user has a valid config file setup."""
    config_path = platform_config_default()
    return config_path.exists()


def check_gdrive_configured() -> tuple[bool, str | None]:
    """
    Check if Google Drive is configured in rclone.
    Returns: (is_configured, error_message)
    """
    try:
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "rclone command failed"

        remotes = result.stdout.strip().split("\n")
        if "gdrive:" not in remotes:
            return False, None  # Not configured, not an error

        # Test connectivity
        result = subprocess.run(
            ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return True, result.stderr  # Configured but not working

        return True, None  # Configured and working

    except FileNotFoundError:
        return False, "rclone not found on PATH"
    except subprocess.TimeoutExpired:
        return True, "rclone timeout (network issue?)"
    except Exception as e:
        return False, f"Unexpected error: {e}"


@pytest.fixture(scope="session")
def user_config_exists():
    """Session-scoped fixture indicating if user config exists."""
    return check_user_config_exists()


@pytest.fixture(scope="session")
def gdrive_status():
    """
    Session-scoped fixture for Google Drive status.
    Returns: (is_configured, error_message)
    """
    return check_gdrive_configured()


def pytest_configure(config):
    """Print environment status at start of test run."""
    print("\n" + "=" * 60)
    print("RRBackup Test Environment Status")
    print("=" * 60)

    # Check user config
    config_exists = check_user_config_exists()
    config_path = platform_config_default()
    status = "[OK] Found" if config_exists else "[MISSING] Not found"
    print(f"User config: {status} at {config_path}")

    # Check Google Drive
    gdrive_configured, gdrive_error = check_gdrive_configured()
    if gdrive_configured and gdrive_error is None:
        print("Google Drive: [OK] Configured and working")
    elif gdrive_configured and gdrive_error:
        print(f"Google Drive: [ERROR] Configured but not working - {gdrive_error}")
    else:
        if gdrive_error:
            print(f"Google Drive: [ERROR] {gdrive_error}")
        else:
            print("Google Drive: [SKIP] Not configured (tests will be skipped)")

    print("=" * 60 + "\n")


# ==================== Skip/Fail Markers ====================


def pytest_runtest_setup(item):
    """Custom logic to skip or fail tests based on markers."""
    # Handle requires_config marker
    if item.get_closest_marker("requires_config"):
        if not check_user_config_exists():
            pytest.fail(
                f"User config file required but not found at {platform_config_default()}. "
                "Create config file first (see SETUP_INSTRUCTIONS.md)"
            )

    # Handle requires_gdrive marker
    if item.get_closest_marker("requires_gdrive"):
        gdrive_configured, gdrive_error = check_gdrive_configured()

        if not gdrive_configured:
            # Not configured - skip with message
            skip_msg = "Google Drive not configured. "
            if gdrive_error:
                skip_msg += f"({gdrive_error}) "
            skip_msg += "See GOOGLE_DRIVE_SETUP.md to configure."
            pytest.skip(skip_msg)

        elif gdrive_error:
            # Configured but not working - fail
            pytest.fail(
                f"Google Drive is configured but not working: {gdrive_error}. "
                "Run 'rclone config reconnect gdrive:' to fix."
            )


# ==================== Test Fixtures ====================


@pytest.fixture
def temp_dir(tmp_path):
    """Temporary directory for test files."""
    return tmp_path


@pytest.fixture
def temp_config_file(temp_dir):
    """Path to temporary config file."""
    return temp_dir / "config.toml"


@pytest.fixture
def temp_password_file(temp_dir):
    """Create temporary password file with test password."""
    pwd_file = temp_dir / "restic_password.txt"
    pwd_file.write_text("test-password-12345", encoding="utf-8")
    return pwd_file


@pytest.fixture
def sample_repo():
    """Sample repository configuration."""
    return Repo(
        url="/tmp/test-repo",
        password_file="/tmp/restic_password.txt",
    )


@pytest.fixture
def sample_backup_set():
    """Sample backup set configuration."""
    return BackupSet(
        name="test-set",
        include=["/home/user/documents"],
        exclude=["**/.git", "**/__pycache__"],
        tags=["test", "sample"],
        one_fs=False,
        dry_run_default=False,
        backup_type="incremental",
        schedule=Schedule(type="daily", time="02:00"),
        retention=RetentionPolicy(keep_daily=7, keep_weekly=4, keep_monthly=6, keep_yearly=2),
    )


@pytest.fixture
def sample_retention():
    """Sample retention policy."""
    return RetentionPolicy(
        keep_daily=7,
        keep_weekly=4,
        keep_monthly=6,
        keep_yearly=2,
    )


@pytest.fixture
def sample_settings(sample_repo, sample_backup_set, sample_retention, temp_dir):
    """Complete sample settings."""
    return Settings(
        restic_bin="restic",
        rclone_bin="rclone",
        log_dir=str(temp_dir / "logs"),
        state_dir=str(temp_dir / "state"),
        repo=sample_repo,
        sets=[sample_backup_set],
        retention_defaults=sample_retention,
    )


@pytest.fixture
def mock_subprocess_run(mocker):
    """Mock subprocess.run for restic/rclone commands."""
    mock = mocker.patch("subprocess.Popen")
    mock_proc = mocker.MagicMock()
    mock_proc.stdout.readline = mocker.MagicMock(return_value=b"")
    mock_proc.wait = mocker.MagicMock(return_value=0)
    mock.return_value = mock_proc
    return mock


@pytest.fixture
def mock_restic_success(mock_subprocess_run):
    """Mock successful restic command execution."""
    mock_subprocess_run.return_value.wait.return_value = 0
    return mock_subprocess_run


@pytest.fixture
def mock_restic_failure(mock_subprocess_run):
    """Mock failed restic command execution."""
    mock_subprocess_run.return_value.wait.return_value = 1
    return mock_subprocess_run


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary (TOML format)."""
    return {
        "repository": {
            "url": "/tmp/test-repo",
            "password_file": "/tmp/restic_password.txt",
        },
        "restic": {"bin": "restic"},
        "rclone": {"bin": "rclone"},
        "state": {"dir": "/tmp/rrbackup/state"},
        "log": {"dir": "/tmp/rrbackup/logs"},
        "retention_defaults": {
            "keep_daily": 7,
            "keep_weekly": 4,
            "keep_monthly": 6,
            "keep_yearly": 2,
        },
        "backup_sets": [
            {
                "name": "test-set",
                "include": ["/home/user/documents"],
                "exclude": ["**/.git"],
                "tags": ["test"],
                "one_fs": False,
                "dry_run_default": False,
                "schedule": {"type": "daily", "time": "02:00"},
                "retention": {"keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6, "keep_yearly": 2},
            }
        ],
    }


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch, temp_dir):
    """Reset environment variables for each test."""
    # Clear RRBACKUP_CONFIG to avoid interference
    monkeypatch.delenv("RRBACKUP_CONFIG", raising=False)

    # Set temp directory for state/logs
    monkeypatch.setenv("LOCALAPPDATA", str(temp_dir))
    monkeypatch.setenv("APPDATA", str(temp_dir))
