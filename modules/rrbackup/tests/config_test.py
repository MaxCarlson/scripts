"""Tests for rrbackup.config module."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

from rrbackup.config import (
    BackupSet,
    Repo,
    RetentionPolicy,
    Schedule,
    Settings,
    load_config,
    platform_config_default,
    resolve_config_path,
    save_config,
    settings_to_dict,
)


@pytest.mark.unit
class TestPlatformConfigDefault:
    """Tests for platform_config_default function."""

    def test_windows_config_path(self, monkeypatch):
        """Test Windows config path uses APPDATA."""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")

        result = platform_config_default()

        assert isinstance(result, pathlib.Path)
        assert "rrbackup" in str(result)
        assert "config.toml" in str(result)
        assert "AppData" in str(result)

    def test_linux_config_path(self, monkeypatch):
        """Test Linux config path uses ~/.config."""
        monkeypatch.setattr("os.name", "posix")
        monkeypatch.setenv("HOME", "/home/testuser")

        result = platform_config_default()

        assert isinstance(result, pathlib.Path)
        assert ".config/rrbackup/config.toml" in str(result)


@pytest.mark.unit
class TestRepoDataclass:
    """Tests for Repo dataclass."""

    def test_repo_creation(self):
        """Test creating Repo with basic fields."""
        repo = Repo(url="/tmp/repo", password_file="/tmp/password.txt")

        assert repo.url == "/tmp/repo"
        assert repo.password_file == "/tmp/password.txt"
        assert repo.password_env is None

    def test_repo_with_password_env(self):
        """Test Repo with environment variable for password."""
        repo = Repo(url="/tmp/repo", password_env="RESTIC_PASSWORD")

        assert repo.password_env == "RESTIC_PASSWORD"
        assert repo.password_file is None

    def test_repo_expand(self, monkeypatch):
        """Test Repo.expand() expands tildes in paths."""
        monkeypatch.setenv("HOME", "/home/testuser")

        repo = Repo(url="~/backups/repo", password_file="~/passwords/restic.txt")
        expanded = repo.expand()

        assert "~" not in expanded.url
        assert "~" not in expanded.password_file
        assert expanded.password_file.startswith("/")


@pytest.mark.unit
class TestBackupSetDataclass:
    """Tests for BackupSet dataclass."""

    def test_backup_set_minimal(self):
        """Test BackupSet with minimal required fields."""
        bset = BackupSet(name="test", include=["/data"])

        assert bset.name == "test"
        assert bset.include == ["/data"]
        assert bset.exclude == []
        assert bset.tags == []
        assert bset.one_fs is False
        assert bset.dry_run_default is False

    def test_backup_set_full(self):
        """Test BackupSet with all fields."""
        bset = BackupSet(
            name="full-test",
            include=["/home", "/data"],
            exclude=["**/.git", "**/__pycache__"],
            tags=["important", "daily"],
            one_fs=True,
            dry_run_default=True,
            schedule=Schedule(type="daily", time="02:00"),
            backup_type="incremental",
            encryption="AES256",
            compression="max",
            retention=RetentionPolicy(keep_last=30),
        )

        assert bset.name == "full-test"
        assert len(bset.include) == 2
        assert len(bset.exclude) == 2
        assert len(bset.tags) == 2
        assert bset.one_fs is True
        assert bset.dry_run_default is True
        assert isinstance(bset.schedule, Schedule)
        assert bset.schedule.type == "daily"
        assert bset.schedule.time == "02:00"
        assert bset.retention.keep_last == 30


@pytest.mark.unit
class TestRetentionPolicyDataclass:
    """Tests for RetentionPolicy dataclass."""

    def test_retention_defaults(self):
        """Test RetentionPolicy with default values."""
        retention = RetentionPolicy()

        assert retention.keep_last is None
        assert retention.keep_hourly is None
        assert retention.keep_daily == 7
        assert retention.keep_weekly == 4
        assert retention.keep_monthly == 6
        assert retention.keep_yearly == 2

    def test_retention_custom(self):
        """Test RetentionPolicy with custom values."""
        retention = RetentionPolicy(
            keep_last=10,
            keep_hourly=24,
            keep_daily=14,
            keep_weekly=8,
            keep_monthly=12,
            keep_yearly=5,
            max_total_size="512GB",
        )

        assert retention.keep_last == 10
        assert retention.keep_hourly == 24
        assert retention.keep_daily == 14
        assert retention.keep_weekly == 8
        assert retention.keep_monthly == 12
        assert retention.keep_yearly == 5
        assert retention.max_total_size == "512GB"


@pytest.mark.unit
class TestSettingsDataclass:
    """Tests for Settings dataclass."""

    def test_settings_minimal(self):
        """Test Settings with minimal configuration."""
        settings = Settings()

        assert settings.restic_bin == "restic"
        assert settings.rclone_bin == "rclone"
        assert settings.log_dir is None
        assert settings.state_dir is None
        assert settings.repo is None
        assert settings.sets == []

    def test_settings_expand(self, monkeypatch, temp_dir):
        """Test Settings.expand() resolves defaults."""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_dir))

        repo = Repo(url="~/backups", password_file="~/pwd.txt")
        settings = Settings(repo=repo)

        expanded = settings.expand()

        # Should have resolved state_dir and log_dir
        assert expanded.state_dir is not None
        assert expanded.log_dir is not None
        assert "rrbackup" in expanded.state_dir
        # Repo should be expanded
        assert "~" not in expanded.repo.url


@pytest.mark.unit
class TestResolveConfigPath:
    """Tests for resolve_config_path function."""

    def test_explicit_path_takes_precedence(self, temp_dir):
        """Test explicit path overrides environment and defaults."""
        explicit = temp_dir / "custom.toml"

        result = resolve_config_path(explicit)

        assert result == explicit

    def test_env_var_takes_precedence_over_default(self, monkeypatch, temp_dir):
        """Test RRBACKUP_CONFIG env var overrides default."""
        env_path = temp_dir / "env-config.toml"
        monkeypatch.setenv("RRBACKUP_CONFIG", str(env_path))

        result = resolve_config_path(None)

        assert result == env_path

    def test_default_when_no_override(self, monkeypatch):
        """Test platform default used when no overrides."""
        monkeypatch.delenv("RRBACKUP_CONFIG", raising=False)

        result = resolve_config_path(None)

        assert "rrbackup" in str(result)
        assert "config.toml" in str(result)


@pytest.mark.unit
class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, temp_dir, sample_config_dict, mocker):
        """Test loading valid TOML configuration."""
        import tomli_w

        config_file = temp_dir / "config.toml"
        config_file.write_text(tomli_w.dumps(sample_config_dict), encoding="utf-8")

        # Mock shutil.which to avoid binary checks
        mocker.patch("shutil.which", return_value="/usr/bin/restic")

        settings = load_config(config_file)

        assert settings.restic_bin == "restic"
        assert settings.rclone_bin == "rclone"
        assert settings.repo.url == "/tmp/test-repo"
        assert len(settings.sets) == 1
        assert settings.sets[0].name == "test-set"

    def test_load_config_file_not_found(self, temp_dir):
        """Test loading nonexistent config raises FileNotFoundError."""
        missing_file = temp_dir / "missing.toml"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(missing_file)

    def test_load_config_warns_missing_binaries(self, temp_dir, sample_config_dict, mocker, capsys):
        """Test warning when restic/rclone not found."""
        import tomli_w

        config_file = temp_dir / "config.toml"
        config_file.write_text(tomli_w.dumps(sample_config_dict), encoding="utf-8")

        # Mock shutil.which to return None (not found)
        mocker.patch("shutil.which", return_value=None)

        settings = load_config(config_file)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "not found on PATH" in captured.err

    def test_load_config_no_expand(self, temp_dir, sample_config_dict):
        """Test loading config without expansion."""
        import tomli_w

        config_file = temp_dir / "config.toml"
        config_file.write_text(tomli_w.dumps(sample_config_dict), encoding="utf-8")

        settings = load_config(config_file, expand=False)

        # state_dir and log_dir should not be set
        assert settings.state_dir is None
        assert settings.log_dir is None


@pytest.mark.unit
class TestSettingsToDict:
    """Tests for settings_to_dict function."""

    def test_minimal_settings_to_dict(self):
        """Test serializing minimal Settings to dict."""
        settings = Settings(restic_bin="restic", rclone_bin="rclone")

        result = settings_to_dict(settings)

        assert result["restic"]["bin"] == "restic"
        assert result["rclone"]["bin"] == "rclone"
        assert "repository" not in result  # No repo configured
        assert "backup_sets" not in result  # No sets

    def test_full_settings_to_dict(self, sample_settings):
        """Test serializing complete Settings to dict."""
        result = settings_to_dict(sample_settings)

        assert "repository" in result
        assert result["repository"]["url"] == "/tmp/test-repo"
        assert "backup_sets" in result
        assert len(result["backup_sets"]) == 1
        assert result["backup_sets"][0]["name"] == "test-set"
        assert "retention_defaults" in result
        assert result["retention_defaults"]["keep_daily"] == 7

    def test_settings_to_dict_excludes_none_values(self):
        """Test that None values are excluded from output."""
        settings = Settings(
            restic_bin="restic",
            rclone_bin="rclone",
            repo=Repo(url="/repo", password_file="/pwd.txt", password_env=None),
        )

        result = settings_to_dict(settings)

        # password_env should not be in output
        assert "password_env" not in result["repository"]
        assert result["repository"]["password_file"] == "/pwd.txt"


@pytest.mark.unit
class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config_creates_file(self, temp_dir, sample_settings):
        """Test saving config creates valid TOML file."""
        config_file = temp_dir / "new-config.toml"

        result = save_config(sample_settings, config_file)

        assert result == config_file
        assert config_file.exists()

        # Verify it's valid TOML by reading it back
        loaded = load_config(config_file, expand=False)
        assert loaded.restic_bin == sample_settings.restic_bin

    def test_save_config_creates_parent_dirs(self, temp_dir, sample_settings):
        """Test saving config creates parent directories."""
        nested_file = temp_dir / "subdir" / "another" / "config.toml"

        save_config(sample_settings, nested_file)

        assert nested_file.exists()
        assert nested_file.parent.exists()

    def test_save_config_fails_if_exists(self, temp_dir, sample_settings):
        """Test saving config fails if file already exists."""
        config_file = temp_dir / "existing.toml"
        config_file.write_text("existing content", encoding="utf-8")

        with pytest.raises(FileExistsError, match="already exists"):
            save_config(sample_settings, config_file, overwrite=False)

    def test_save_config_overwrites_if_allowed(self, temp_dir, sample_settings):
        """Test saving config overwrites if overwrite=True."""
        config_file = temp_dir / "existing.toml"
        config_file.write_text("old content", encoding="utf-8")

        save_config(sample_settings, config_file, overwrite=True)

        content = config_file.read_text()
        assert "old content" not in content
        assert "restic" in content


@pytest.mark.unit
class TestConfigRoundTrip:
    """Tests for config serialization/deserialization round-trip."""

    def test_save_and_load_roundtrip(self, temp_dir, sample_settings, mocker):
        """Test saving and loading config preserves data."""
        config_file = temp_dir / "roundtrip.toml"

        # Mock binary checks
        mocker.patch("shutil.which", return_value="/usr/bin/restic")

        # Save
        save_config(sample_settings, config_file)

        # Load
        loaded = load_config(config_file, expand=False)

        # Compare (note: expanded paths may differ)
        assert loaded.restic_bin == sample_settings.restic_bin
        assert loaded.rclone_bin == sample_settings.rclone_bin
        assert loaded.repo.url == sample_settings.repo.url
        assert len(loaded.sets) == len(sample_settings.sets)
        assert loaded.sets[0].name == sample_settings.sets[0].name
        assert loaded.retention_defaults.keep_daily == sample_settings.retention_defaults.keep_daily


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_backup_sets(self, temp_dir):
        """Test config with no backup sets."""
        import tomli_w

        config_dict = {
            "repository": {"url": "/repo", "password_file": "/pwd.txt"},
            "restic": {"bin": "restic"},
            "rclone": {"bin": "rclone"},
        }

        config_file = temp_dir / "no-sets.toml"
        config_file.write_text(tomli_w.dumps(config_dict), encoding="utf-8")

        settings = load_config(config_file, expand=False)

        assert settings.sets == []

    def test_backup_set_with_empty_lists(self):
        """Test BackupSet with empty exclude/tags."""
        bset = BackupSet(name="test", include=["/data"], exclude=[], tags=[])

        assert bset.exclude == []
        assert bset.tags == []

    def test_retention_all_none(self):
        """Test Retention with all values set to None."""
        retention = RetentionPolicy(
            keep_last=None,
            keep_hourly=None,
            keep_daily=None,
            keep_weekly=None,
            keep_monthly=None,
            keep_yearly=None,
        )

        result = settings_to_dict(Settings(retention_defaults=retention))

        # Should still include retention section if any non-None values
        # But since all are None, it might be omitted
        assert "retention_defaults" not in result or result["retention_defaults"] == {}

    def test_unicode_paths_in_config(self, temp_dir, mocker):
        """Test config with Unicode characters in paths."""
        import tomli_w

        config_dict = {
            "repository": {"url": "/tmp/café-repo", "password_file": "/tmp/pāss.txt"},
            "restic": {"bin": "restic"},
            "rclone": {"bin": "rclone"},
            "backup_sets": [
                {
                    "name": "unicode-test",
                    "include": ["/home/user/文档"],
                    "exclude": ["**/🗑️"],
                    "tags": ["日本語"],
                }
            ],
        }

        config_file = temp_dir / "unicode.toml"
        config_file.write_text(tomli_w.dumps(config_dict), encoding="utf-8")

        mocker.patch("shutil.which", return_value="/usr/bin/restic")

        settings = load_config(config_file)

        assert "café" in settings.repo.url
        assert "文档" in settings.sets[0].include[0]
        assert "日本語" in settings.sets[0].tags
