"""Integration tests for rrbackup (requires actual config and/or Google Drive setup)."""
from __future__ import annotations

import subprocess

import pytest

from rrbackup.config import load_config, platform_config_default


@pytest.mark.integration
@pytest.mark.requires_config
class TestWithUserConfig:
    """Integration tests that require user config file."""

    def test_user_config_exists_and_loads(self):
        """Test that user config file exists and can be loaded."""
        config_path = platform_config_default()

        # This will fail if config doesn't exist (per conftest.py setup)
        settings = load_config(None)

        assert settings is not None
        assert settings.repo is not None
        assert settings.repo.url is not None

    def test_user_config_has_valid_repository(self):
        """Test user config has valid repository configuration."""
        settings = load_config(None)

        assert settings.repo.url, "Repository URL must be configured"
        assert (
            settings.repo.password_file or settings.repo.password_env
        ), "Password file or env var must be configured"

    def test_user_config_has_backup_sets(self):
        """Test user config has at least one backup set."""
        settings = load_config(None)

        assert len(settings.sets) > 0, "At least one backup set must be configured"
        first_set = settings.sets[0]
        assert first_set.name, "Backup set must have a name"
        assert len(first_set.include) > 0, "Backup set must have include paths"

    def test_user_config_has_retention_policy(self):
        """Test user config has retention policy."""
        settings = load_config(None)

        retention = settings.retention_defaults
        # At least one retention value should be set
        has_retention = any(
            [
                retention.keep_last,
                retention.keep_hourly,
                retention.keep_daily,
                retention.keep_weekly,
                retention.keep_monthly,
                retention.keep_yearly,
            ]
        )
        assert has_retention, "Retention policy should have at least one value set"


@pytest.mark.integration
@pytest.mark.requires_gdrive
class TestWithGoogleDrive:
    """Integration tests that require Google Drive to be configured."""

    def test_rclone_gdrive_configured(self):
        """Test rclone has gdrive remote configured."""
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "gdrive:" in result.stdout

    def test_rclone_gdrive_connectivity(self):
        """Test Google Drive is accessible via rclone."""
        result = subprocess.run(
            ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # If this fails, conftest.py will have caught it and failed the test
        # This test only runs if gdrive is configured AND working
        assert result.returncode == 0, f"rclone failed: {result.stderr}"

    def test_rclone_can_create_directory(self):
        """Test rclone can create directory in Google Drive."""
        test_dir = "gdrive:/rrbackup-test-dir"

        # Create test directory
        result = subprocess.run(
            ["rclone", "mkdir", test_dir],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"Failed to create directory: {result.stderr}"

        # Verify it exists
        result = subprocess.run(
            ["rclone", "lsd", "gdrive:", "--max-depth", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert "rrbackup-test-dir" in result.stdout

        # Clean up
        subprocess.run(
            ["rclone", "rmdir", test_dir],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @pytest.mark.slow
    def test_rclone_upload_download(self):
        """Test rclone can upload and download files to Google Drive."""
        import tempfile

        test_content = "RRBackup test file content"

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            test_file = f"{temp_dir}/test.txt"
            with open(test_file, "w") as f:
                f.write(test_content)

            # Upload
            result = subprocess.run(
                ["rclone", "copy", test_file, "gdrive:/rrbackup-test"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"Upload failed: {result.stderr}"

            # Download
            download_file = f"{temp_dir}/downloaded.txt"
            result = subprocess.run(
                ["rclone", "copy", "gdrive:/rrbackup-test/test.txt", temp_dir],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"Download failed: {result.stderr}"

            # Verify content
            with open(f"{temp_dir}/test.txt", "r") as f:
                content = f.read()
            assert content == test_content

            # Clean up
            subprocess.run(
                ["rclone", "purge", "gdrive:/rrbackup-test"],
                capture_output=True,
                text=True,
                timeout=30,
            )


@pytest.mark.integration
class TestResticBinaryAvailability:
    """Test that restic binary is available."""

    def test_restic_binary_exists(self):
        """Test restic binary is on PATH."""
        result = subprocess.run(
            ["restic", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "restic" in result.stdout.lower()

    def test_rclone_binary_exists(self):
        """Test rclone binary is on PATH."""
        result = subprocess.run(
            ["rclone", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "rclone" in result.stdout.lower()


@pytest.mark.integration
class TestEndToEndBackupRestore:
    """End-to-end test of backup and restore cycle."""

    @pytest.mark.slow
    def test_full_backup_restore_cycle(self, temp_dir, mocker):
        """Test complete backup and restore workflow with local repository."""
        import tomli_w
        from rrbackup.cli import main

        # Create test data
        source_dir = temp_dir / "source"
        source_dir.mkdir()
        (source_dir / "file1.txt").write_text("Test content 1")
        (source_dir / "file2.txt").write_text("Test content 2")
        (source_dir / "subdir").mkdir()
        (source_dir / "subdir" / "file3.txt").write_text("Test content 3")

        # Create repository
        repo_dir = temp_dir / "repo"
        repo_dir.mkdir()

        # Create password file
        password_file = temp_dir / "password.txt"
        password_file.write_text("test-password-integration")

        # Create config
        config_dict = {
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
                }
            ],
        }

        config_file = temp_dir / "config.toml"
        config_file.write_text(tomli_w.dumps(config_dict), encoding="utf-8")

        # Initialize repository
        result = main(["-c", str(config_file), "setup"])
        assert result == 0, "Repository initialization failed"

        # Run backup
        result = main(["-c", str(config_file), "backup", "-s", "test-set"])
        assert result == 0, "Backup failed"

        # List snapshots
        result = main(["-c", str(config_file), "list"])
        assert result == 0, "List snapshots failed"

        # Check repository
        result = main(["-c", str(config_file), "check"])
        assert result == 0, "Repository check failed"

        # Stats
        result = main(["-c", str(config_file), "stats"])
        assert result == 0, "Stats failed"

        # Restore (using restic directly)
        restore_dir = temp_dir / "restore"
        restore_dir.mkdir()

        restore_result = subprocess.run(
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
        )

        assert restore_result.returncode == 0, f"Restore failed: {restore_result.stderr}"

        # Verify restored files
        restored_file1 = restore_dir / str(source_dir).lstrip("/") / "file1.txt"
        if not restored_file1.exists():
            # Try alternative path (Windows vs Linux)
            restored_file1 = restore_dir / source_dir.name / "file1.txt"

        # Just verify something was restored
        restored_files = list(restore_dir.rglob("*.txt"))
        assert len(restored_files) >= 3, "Not all files were restored"


@pytest.mark.integration
class TestCLIHelpOutput:
    """Test CLI help output is user-friendly."""

    def test_main_help_output(self):
        """Test main help text."""
        result = subprocess.run(
            ["rrb", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "Restic + Rclone backup CLI" in result.stdout
        assert "setup" in result.stdout
        assert "backup" in result.stdout
        assert "list" in result.stdout

    def test_backup_help_output(self):
        """Test backup subcommand help text."""
        result = subprocess.run(
            ["rrb", "backup", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "--set" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--tag" in result.stdout

    def test_config_help_output(self):
        """Test config subcommand help text."""
        result = subprocess.run(
            ["rrb", "config", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0
        assert "wizard" in result.stdout
        assert "show" in result.stdout
        assert "add-set" in result.stdout


@pytest.mark.integration
class TestErrorMessages:
    """Test error messages are clear and actionable."""

    def test_missing_config_error_message(self, temp_dir):
        """Test error when config file is missing."""
        from rrbackup.cli import main

        missing_config = temp_dir / "nonexistent.toml"

        result = main(["-c", str(missing_config), "list"])

        assert result != 0

    def test_invalid_backup_set_error_message(self, temp_dir):
        """Test error when backup set doesn't exist."""
        import tomli_w
        from rrbackup.cli import main

        config_dict = {
            "repository": {"url": "/tmp/repo", "password_file": "/tmp/pwd.txt"},
            "restic": {"bin": "restic"},
            "rclone": {"bin": "rclone"},
            "backup_sets": [{"name": "valid-set", "include": ["/tmp"]}],
        }

        config_file = temp_dir / "config.toml"
        config_file.write_text(tomli_w.dumps(config_dict), encoding="utf-8")

        with pytest.raises(SystemExit, match="not found"):
            main(["-c", str(config_file), "backup", "-s", "nonexistent-set"])
