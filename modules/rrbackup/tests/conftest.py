"""Pytest fixtures and configuration for RRBackup tests."""

from __future__ import annotations

import os
import subprocess
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


RUN_GDRIVE_ENV = "RRBACKUP_RUN_GDRIVE_TESTS"


def check_user_config_exists() -> bool:
    """Return whether a user RRBackup config exists in the canonical location."""
    return platform_config_default().exists()


def check_gdrive_configured() -> tuple[bool, str | None]:
    """Return Google Drive test availability without running unless explicitly enabled."""
    if os.environ.get(RUN_GDRIVE_ENV) != "1":
        return False, f"set {RUN_GDRIVE_ENV}=1 to enable live Google Drive tests"

    try:
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return False, "rclone listremotes failed"

        remotes = result.stdout.strip().splitlines()
        if "gdrive:" not in remotes:
            return False, "gdrive: is not configured"

        result = subprocess.run(
            ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return True, result.stderr.strip() or "Google Drive connectivity check failed"

        return True, None
    except FileNotFoundError:
        return False, "rclone was not found on PATH"
    except subprocess.TimeoutExpired:
        return True, "Google Drive connectivity check timed out"
    except OSError as exc:
        return False, f"unable to inspect rclone configuration: {exc}"


@pytest.fixture(scope="session")
def user_config_exists() -> bool:
    """Return whether a user config exists without making it a test prerequisite."""
    return check_user_config_exists()


@pytest.fixture(scope="session")
def gdrive_status() -> tuple[bool, str | None]:
    """Return live Google Drive test status."""
    return check_gdrive_configured()


def pytest_configure(config: pytest.Config) -> None:
    """Print concise environment status at the beginning of a test run."""
    del config

    config_path = platform_config_default()
    config_status = "[OK] Found" if config_path.exists() else "[SKIP] Not found"

    gdrive_configured, gdrive_error = check_gdrive_configured()
    if gdrive_configured and gdrive_error is None:
        gdrive_status_text = "[OK] Explicitly enabled and reachable"
    elif gdrive_configured:
        gdrive_status_text = f"[ERROR] {gdrive_error}"
    else:
        gdrive_status_text = f"[SKIP] {gdrive_error or 'not configured'}"

    print("\n" + "=" * 60)
    print("RRBackup Test Environment Status")
    print("=" * 60)
    print(f"User config: {config_status} at {config_path}")
    print(f"Google Drive: {gdrive_status_text}")
    print("=" * 60 + "\n")


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip optional environment-dependent tests unless prerequisites are explicit."""
    if item.get_closest_marker("requires_config") and not check_user_config_exists():
        pytest.skip(
            f"User config not found at {platform_config_default()}; "
            "the default suite does not require user configuration."
        )

    if item.get_closest_marker("requires_gdrive"):
        gdrive_configured, gdrive_error = check_gdrive_configured()
        if not gdrive_configured:
            pytest.skip(gdrive_error or "Google Drive tests are not enabled.")
        if gdrive_error:
            pytest.fail(f"Google Drive is enabled but unavailable: {gdrive_error}")


@pytest.fixture
def temp_dir(tmp_path):
    """Return a pytest-managed temporary directory."""
    return tmp_path


@pytest.fixture
def temp_config_file(temp_dir):
    """Return a temporary config-file path."""
    return temp_dir / "config.toml"


@pytest.fixture
def temp_password_file(temp_dir):
    """Create and return a temporary password file."""
    password_file = temp_dir / "restic_password.txt"
    password_file.write_text("test-password-12345", encoding="utf-8")
    return password_file


@pytest.fixture
def sample_repo(temp_dir) -> Repo:
    """Return a sample repository configuration inside the pytest temp root."""
    return Repo(
        url=str(temp_dir / "repository"),
        password_file=str(temp_dir / "restic_password.txt"),
    )


@pytest.fixture
def sample_backup_set(temp_dir) -> BackupSet:
    """Return a sample backup-set configuration inside the pytest temp root."""
    return BackupSet(
        name="test-set",
        include=[str(temp_dir / "documents")],
        exclude=["**/.git", "**/__pycache__"],
        tags=["test", "sample"],
        one_fs=False,
        dry_run_default=False,
        backup_type="incremental",
        schedule=Schedule(type="daily", time="02:00"),
        retention=RetentionPolicy(
            keep_daily=7,
            keep_weekly=4,
            keep_monthly=6,
            keep_yearly=2,
        ),
    )


@pytest.fixture
def sample_retention() -> RetentionPolicy:
    """Return a sample retention policy."""
    return RetentionPolicy(
        keep_daily=7,
        keep_weekly=4,
        keep_monthly=6,
        keep_yearly=2,
    )


@pytest.fixture
def sample_settings(
    sample_repo: Repo,
    sample_backup_set: BackupSet,
    sample_retention: RetentionPolicy,
    temp_dir,
) -> Settings:
    """Return complete sample settings."""
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
    """Mock subprocess.Popen for Restic/Rclone command tests."""
    mocked_popen = mocker.patch("subprocess.Popen")
    process = mocker.MagicMock()
    process.stdout.readline = mocker.MagicMock(return_value=b"")
    process.wait = mocker.MagicMock(return_value=0)
    mocked_popen.return_value = process
    return mocked_popen


@pytest.fixture
def mock_restic_success(mock_subprocess_run):
    """Return a mocked successful Restic execution."""
    mock_subprocess_run.return_value.wait.return_value = 0
    return mock_subprocess_run


@pytest.fixture
def mock_restic_failure(mock_subprocess_run):
    """Return a mocked failed Restic execution."""
    mock_subprocess_run.return_value.wait.return_value = 1
    return mock_subprocess_run


@pytest.fixture
def sample_config_dict(temp_dir) -> dict[str, Any]:
    """Return a TOML-compatible config confined to the pytest temp root."""
    return {
        "repository": {
            "url": str(temp_dir / "repository"),
            "password_file": str(temp_dir / "restic_password.txt"),
        },
        "restic": {"bin": "restic"},
        "rclone": {"bin": "rclone"},
        "state": {"dir": str(temp_dir / "state")},
        "log": {"dir": str(temp_dir / "logs")},
        "retention_defaults": {
            "keep_daily": 7,
            "keep_weekly": 4,
            "keep_monthly": 6,
            "keep_yearly": 2,
        },
        "backup_sets": [
            {
                "name": "test-set",
                "include": [str(temp_dir / "documents")],
                "exclude": ["**/.git"],
                "tags": ["test"],
                "one_fs": False,
                "dry_run_default": False,
                "schedule": {"type": "daily", "time": "02:00"},
                "retention": {
                    "keep_daily": 7,
                    "keep_weekly": 4,
                    "keep_monthly": 6,
                    "keep_yearly": 2,
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch, temp_dir) -> None:
    """Isolate RRBackup environment variables and state directories per test."""
    monkeypatch.delenv("RRBACKUP_CONFIG", raising=False)
    monkeypatch.delenv(RUN_GDRIVE_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(temp_dir))
    monkeypatch.setenv("APPDATA", str(temp_dir))
