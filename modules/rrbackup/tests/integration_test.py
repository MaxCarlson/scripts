"""Integration tests for the canonical backup CLI and optional live services."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rrbackup.application import main
from rrbackup.config import load_config, platform_config_default


@pytest.mark.integration
@pytest.mark.requires_config
class TestWithUserConfig:
    def test_user_config_exists_and_loads(self) -> None:
        assert platform_config_default().exists()
        settings = load_config(None)
        assert settings.repo is not None
        assert settings.repo.url

    def test_user_config_has_valid_repository(self) -> None:
        settings = load_config(None)
        assert settings.repo is not None
        assert settings.repo.url
        assert settings.repo.password_file or settings.repo.password_env

    def test_user_config_has_backup_sets(self) -> None:
        settings = load_config(None)
        assert settings.sets
        assert settings.sets[0].name
        assert settings.sets[0].include

    def test_user_config_has_retention_policy(self) -> None:
        retention = load_config(None).retention_defaults
        assert any(
            value is not None
            for value in (
                retention.keep_last,
                retention.keep_hourly,
                retention.keep_daily,
                retention.keep_weekly,
                retention.keep_monthly,
                retention.keep_yearly,
            )
        )


@pytest.mark.integration
@pytest.mark.requires_gdrive
class TestWithGoogleDrive:
    def test_rclone_gdrive_configured(self) -> None:
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert "gdrive:" in result.stdout

    def test_rclone_gdrive_connectivity(self) -> None:
        result = subprocess.run(
            ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_rclone_can_create_directory(self) -> None:
        test_dir = "gdrive:/rrbackup-test-dir"
        created = subprocess.run(
            ["rclone", "mkdir", test_dir],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        try:
            assert created.returncode == 0, created.stderr
            listed = subprocess.run(
                ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            assert "rrbackup-test-dir" in listed.stdout
        finally:
            subprocess.run(
                ["rclone", "rmdir", test_dir],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )


@pytest.mark.integration
class TestBinaryAvailability:
    @pytest.mark.parametrize("command", ["restic", "rclone"])
    def test_binary_exists(self, command: str) -> None:
        result = subprocess.run(
            [command, "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert command in (result.stdout + result.stderr).lower()


@pytest.mark.integration
class TestEndToEndBackupRestore:
    @pytest.mark.slow
    def test_full_backup_restore_cycle(self, temp_dir: Path) -> None:
        import tomli_w

        source_dir = temp_dir / "source"
        source_dir.mkdir()
        (source_dir / "file1.txt").write_text("Test content 1", encoding="utf-8")
        (source_dir / "file2.txt").write_text("Test content 2", encoding="utf-8")
        (source_dir / "subdir").mkdir()
        (source_dir / "subdir" / "file3.txt").write_text("Test content 3", encoding="utf-8")

        repo_dir = temp_dir / "repo"
        password_file = temp_dir / "password.txt"
        password_file.write_text("test-password-integration", encoding="utf-8")
        config_file = temp_dir / "config.toml"
        config_file.write_text(
            tomli_w.dumps(
                {
                    "repository": {
                        "url": str(repo_dir),
                        "password_file": str(password_file),
                    },
                    "restic": {"bin": "restic"},
                    "rclone": {"bin": "rclone"},
                    "state": {"dir": str(temp_dir / "state")},
                    "log": {"dir": str(temp_dir / "logs")},
                    "retention_defaults": {"keep_daily": 7},
                    "backup_sets": [
                        {
                            "name": "test-set",
                            "include": [str(source_dir)],
                            "exclude": ["**/*.tmp"],
                            "tags": ["integration-test"],
                            "use_fs_snapshot": False,
                            "exclude_caches": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        initialized = subprocess.run(
            [
                "restic",
                "-r",
                str(repo_dir),
                "--password-file",
                str(password_file),
                "init",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert initialized.returncode == 0, initialized.stderr

        assert main(["--config", str(config_file), "run", "test-set", "--force"]) == 0
        assert main(["--config", str(config_file), "view", "--section", "history", "--plain"]) == 0
        assert main(["--config", str(config_file), "repo", "check", "--plain"]) == 0

        restore_dir = temp_dir / "restore"
        restored = subprocess.run(
            [
                "restic",
                "-r",
                str(repo_dir),
                "--password-file",
                str(password_file),
                "restore",
                "latest",
                "--target",
                str(restore_dir),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert restored.returncode == 0, restored.stderr
        assert len(list(restore_dir.rglob("*.txt"))) >= 3


@pytest.mark.integration
class TestCLIHelpOutput:
    def test_main_help_output(self) -> None:
        result = subprocess.run(
            ["backup", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert "backup create" in result.stdout
        assert "backup view" in result.stdout
        assert "repo" in result.stdout
        assert "rrb" not in result.stdout

    def test_run_help_output(self) -> None:
        result = subprocess.run(
            ["backup", "run", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert "auto" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--print-command-only" in result.stdout

    def test_view_help_is_condensed(self) -> None:
        result = subprocess.run(
            ["backup", "view", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert "--section" in result.stdout
        assert "timeline" not in result.stdout
        assert "snapshots" not in result.stdout

    def test_schedule_help_lists_editor(self) -> None:
        result = subprocess.run(
            ["backup", "schedule", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0
        assert "wizard" in result.stdout
        assert "edit" in result.stdout


@pytest.mark.integration
class TestErrorMessages:
    def test_missing_config_error_message(self, temp_dir: Path) -> None:
        missing_config = temp_dir / "nonexistent.toml"
        result = main(["--config", str(missing_config), "config", "show", "--json"])
        assert result != 0

    def test_invalid_backup_name_returns_nonzero(self, temp_dir: Path) -> None:
        import tomli_w

        password_file = temp_dir / "password.txt"
        password_file.write_text("test", encoding="utf-8")
        config_file = temp_dir / "config.toml"
        config_file.write_text(
            tomli_w.dumps(
                {
                    "repository": {
                        "url": str(temp_dir / "repo"),
                        "password_file": str(password_file),
                    },
                    "backup_sets": [
                        {
                            "name": "valid-set",
                            "include": [str(temp_dir)],
                            "use_fs_snapshot": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        assert main(["--config", str(config_file), "run", "missing", "--json"]) != 0
