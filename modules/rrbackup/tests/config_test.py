"""Isolated tests for RRBackup configuration models and TOML persistence."""

from __future__ import annotations

import os
import pathlib

import pytest

from rrbackup.config import (
    BackupSet,
    Repo,
    RetentionPolicy,
    Schedule,
    Settings,
    _parse_retention,
    _parse_schedule,
    _parse_size_to_bytes,
    load_config,
    platform_config_default,
    resolve_config_path,
    save_config,
    settings_to_dict,
)


@pytest.mark.unit
class TestPlatformConfigDefault:
    """Test the native platform without mutating ``os.name``."""

    def test_native_config_path(self, monkeypatch, temp_dir) -> None:
        monkeypatch.delenv("RRBACKUP_CONFIG", raising=False)

        if os.name == "nt":
            monkeypatch.setenv("APPDATA", str(temp_dir))
            expected = temp_dir / "rrbackup" / "config.toml"
        else:
            expected = pathlib.Path.home() / ".config" / "rrbackup" / "config.toml"

        assert platform_config_default() == expected


@pytest.mark.unit
class TestRepo:
    """Cover repository credential and path expansion behavior."""

    def test_creation_with_password_file(self) -> None:
        repo = Repo(url="/tmp/repo", password_file="/tmp/password.txt")

        assert repo.url == "/tmp/repo"
        assert repo.password_file == "/tmp/password.txt"
        assert repo.password_env is None

    def test_creation_with_password_environment(self) -> None:
        repo = Repo(url="/tmp/repo", password_env="RESTIC_PASSWORD")

        assert repo.password_env == "RESTIC_PASSWORD"
        assert repo.password_file is None

    def test_expand_uses_native_user_home(self) -> None:
        repo = Repo(url="~/backups/repo", password_file="~/passwords/restic.txt")

        expanded = repo.expand()

        assert expanded.url == os.path.expanduser("~/backups/repo")
        assert expanded.password_file == os.path.expanduser("~/passwords/restic.txt")
        assert "~" not in expanded.url
        assert "~" not in expanded.password_file


@pytest.mark.unit
class TestSchedule:
    """Cover schedule serialization and parsing."""

    def test_manual_schedule_serializes_minimally(self) -> None:
        assert Schedule().to_dict() == {"type": "manual"}

    def test_full_schedule_serialization(self) -> None:
        schedule = Schedule(
            type="weekly",
            time="02:30",
            interval_hours=24,
            day_of_week="SUN",
            day_of_month=1,
            description="weekly test",
        )

        assert schedule.to_dict() == {
            "type": "weekly",
            "time": "02:30",
            "interval_hours": 24,
            "day_of_week": "SUN",
            "day_of_month": 1,
            "description": "weekly test",
        }

    def test_parse_mapping(self) -> None:
        schedule = _parse_schedule({"type": "daily", "time": "03:00"})

        assert schedule.type == "daily"
        assert schedule.time == "03:00"

    def test_parse_legacy_string(self) -> None:
        schedule = _parse_schedule("daily 03:00")

        assert schedule.type == "custom"
        assert schedule.description == "daily 03:00"

    def test_parse_missing_value_returns_manual(self) -> None:
        assert _parse_schedule(None) == Schedule()


@pytest.mark.unit
class TestRetentionPolicy:
    """Cover retention parsing and serialization."""

    def test_defaults(self) -> None:
        retention = RetentionPolicy()

        assert retention.keep_last is None
        assert retention.keep_hourly is None
        assert retention.keep_daily == 7
        assert retention.keep_weekly == 4
        assert retention.keep_monthly == 6
        assert retention.keep_yearly == 2

    def test_custom_to_dict(self) -> None:
        retention = RetentionPolicy(
            keep_last=10,
            keep_hourly=24,
            keep_daily=14,
            keep_weekly=8,
            keep_monthly=12,
            keep_yearly=5,
            max_total_size="512GB",
        )

        assert retention.to_dict() == {
            "keep_last": 10,
            "keep_hourly": 24,
            "keep_daily": 14,
            "keep_weekly": 8,
            "keep_monthly": 12,
            "keep_yearly": 5,
            "max_total_size": "512GB",
        }

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, (None, None)),
            ("", (None, None)),
            ("1024", ("1024", 1024)),
            ("1KB", ("1KB", 1024)),
            ("1.5MB", ("1.5MB", 1572864)),
            ("2GB", ("2GB", 2 * 1024**3)),
            ("1TB", ("1TB", 1024**4)),
        ],
    )
    def test_size_parsing(
        self,
        value: str | None,
        expected: tuple[str | None, int | None],
    ) -> None:
        assert _parse_size_to_bytes(value) == expected

    def test_invalid_size_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid size"):
            _parse_size_to_bytes("large")

    def test_retention_mapping_parses_size(self) -> None:
        retention = _parse_retention({"keep_last": 5, "max_total_size": "512GB"})

        assert retention is not None
        assert retention.keep_last == 5
        assert retention.max_total_size == "512GB"
        assert retention.max_total_size_bytes == 512 * 1024**3

    def test_existing_retention_is_returned(self) -> None:
        retention = RetentionPolicy(keep_last=2)

        assert _parse_retention(retention) is retention

    def test_invalid_retention_type_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a dict"):
            _parse_retention("daily")


@pytest.mark.unit
class TestBackupSetAndSettings:
    """Cover configuration data models and native expansion."""

    def test_minimal_backup_set(self) -> None:
        backup_set = BackupSet(name="test", include=["/data"])

        assert backup_set.name == "test"
        assert backup_set.include == ["/data"]
        assert backup_set.exclude == []
        assert backup_set.tags == []
        assert backup_set.schedule == Schedule()

    def test_full_backup_set(self) -> None:
        backup_set = BackupSet(
            name="full-test",
            include=["/home", "/data"],
            exclude=["**/.git", "**/__pycache__"],
            tags=["important", "daily"],
            one_fs=True,
            dry_run_default=True,
            backup_type="incremental",
            encryption="repository-managed",
            compression="max",
            schedule=Schedule(type="daily", time="02:00"),
            retention=RetentionPolicy(keep_last=30),
        )

        assert backup_set.one_fs is True
        assert backup_set.dry_run_default is True
        assert backup_set.schedule.time == "02:00"
        assert backup_set.retention is not None
        assert backup_set.retention.keep_last == 30

    def test_settings_defaults(self) -> None:
        settings = Settings()

        assert settings.restic_bin == "restic"
        assert settings.rclone_bin == "rclone"
        assert settings.state_dir is None
        assert settings.log_dir is None
        assert settings.repo is None
        assert settings.sets == []

    def test_settings_expand_resolves_native_defaults(self, temp_dir, monkeypatch) -> None:
        if os.name == "nt":
            monkeypatch.setenv("LOCALAPPDATA", str(temp_dir))

        settings = Settings(
            repo=Repo(url="~/backups", password_file="~/pwd.txt"),
            sets=[BackupSet(name="home", include=["~/documents"])],
        )

        expanded = settings.expand()

        assert expanded.state_dir is not None
        assert expanded.log_dir == str(pathlib.Path(expanded.state_dir) / "logs")
        assert "rrbackup" in expanded.state_dir
        assert expanded.repo is not None
        assert "~" not in expanded.repo.url
        assert "~" not in expanded.sets[0].include[0]


@pytest.mark.unit
class TestResolveConfigPath:
    """Cover explicit, environment, and platform config precedence."""

    def test_explicit_path_takes_precedence(self, temp_dir, monkeypatch) -> None:
        explicit = temp_dir / "custom.toml"
        monkeypatch.setenv("RRBACKUP_CONFIG", str(temp_dir / "environment.toml"))

        assert resolve_config_path(explicit) == explicit

    def test_environment_precedes_default(self, temp_dir, monkeypatch) -> None:
        environment_path = temp_dir / "environment.toml"
        monkeypatch.setenv("RRBACKUP_CONFIG", str(environment_path))

        assert resolve_config_path(None) == environment_path

    def test_default_used_without_override(self, monkeypatch) -> None:
        monkeypatch.delenv("RRBACKUP_CONFIG", raising=False)

        result = resolve_config_path(None)

        assert result.name == "config.toml"
        assert result.parent.name == "rrbackup"


@pytest.mark.unit
class TestLoadConfig:
    """Cover TOML loading, expansion, and warning behavior."""

    @staticmethod
    def _write_config(path, payload) -> None:
        import tomli_w

        path.write_text(tomli_w.dumps(payload), encoding="utf-8")

    def test_load_valid_config(self, temp_dir, sample_config_dict, mocker) -> None:
        config_file = temp_dir / "config.toml"
        self._write_config(config_file, sample_config_dict)
        mocker.patch("rrbackup.config.shutil.which", return_value="restic")

        settings = load_config(config_file)

        assert settings.restic_bin == "restic"
        assert settings.rclone_bin == "rclone"
        assert settings.repo is not None
        assert settings.repo.url == str(temp_dir / "repository")
        assert [backup_set.name for backup_set in settings.sets] == ["test-set"]

    def test_missing_config_raises(self, temp_dir) -> None:
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(temp_dir / "missing.toml")

    def test_missing_binaries_warn(self, temp_dir, sample_config_dict, mocker, capsys) -> None:
        config_file = temp_dir / "config.toml"
        self._write_config(config_file, sample_config_dict)
        mocker.patch("rrbackup.config.shutil.which", return_value=None)

        load_config(config_file)

        captured = capsys.readouterr()
        assert "'restic' not found on PATH" in captured.err
        assert "'rclone' not found on PATH" in captured.err

    def test_no_expand_preserves_explicit_values(self, temp_dir, sample_config_dict) -> None:
        config_file = temp_dir / "config.toml"
        self._write_config(config_file, sample_config_dict)

        settings = load_config(config_file, expand=False)

        assert settings.state_dir == str(temp_dir / "state")
        assert settings.log_dir == str(temp_dir / "logs")
        assert settings.repo is not None
        assert settings.repo.password_file == str(temp_dir / "restic_password.txt")

    def test_legacy_max_snapshots_maps_to_retention(self, temp_dir) -> None:
        config_file = temp_dir / "legacy.toml"
        self._write_config(
            config_file,
            {
                "backup_sets": [
                    {"name": "legacy", "include": [str(temp_dir / "data")], "max_snapshots": 12}
                ]
            },
        )

        settings = load_config(config_file, expand=False)

        assert settings.sets[0].retention is not None
        assert settings.sets[0].retention.keep_last == 12


@pytest.mark.unit
class TestSettingsSerialization:
    """Cover TOML-compatible serialization and persistence."""

    def test_minimal_settings_to_dict(self) -> None:
        result = settings_to_dict(Settings(restic_bin="restic", rclone_bin="rclone"))

        assert result == {
            "restic": {"bin": "restic"},
            "rclone": {"bin": "rclone"},
            "retention_defaults": {
                "keep_daily": 7,
                "keep_weekly": 4,
                "keep_monthly": 6,
                "keep_yearly": 2,
            },
        }

    def test_full_settings_to_dict(self, sample_settings) -> None:
        result = settings_to_dict(sample_settings)

        assert result["repository"]["url"] == sample_settings.repo.url
        assert "password_env" not in result["repository"]
        assert result["backup_sets"][0]["name"] == "test-set"
        assert result["backup_sets"][0]["schedule"] == {
            "type": "daily",
            "time": "02:00",
        }
        assert result["retention_defaults"]["keep_daily"] == 7

    def test_save_creates_parent_and_round_trips(self, temp_dir, sample_settings, mocker) -> None:
        config_file = temp_dir / "nested" / "config.toml"
        mocker.patch("rrbackup.config.shutil.which", return_value="restic")

        saved = save_config(sample_settings, config_file)
        loaded = load_config(config_file)

        assert saved == config_file
        assert config_file.exists()
        assert loaded.repo is not None
        assert loaded.repo.url == sample_settings.repo.url
        assert loaded.sets[0].name == sample_settings.sets[0].name

    def test_save_refuses_existing_file_without_overwrite(self, temp_dir, sample_settings) -> None:
        config_file = temp_dir / "config.toml"
        config_file.write_text("existing", encoding="utf-8")

        with pytest.raises(FileExistsError, match="already exists"):
            save_config(sample_settings, config_file)

    def test_save_overwrites_when_explicit(self, temp_dir, sample_settings) -> None:
        config_file = temp_dir / "config.toml"
        config_file.write_text("existing", encoding="utf-8")

        save_config(sample_settings, config_file, overwrite=True)

        assert "existing" not in config_file.read_text(encoding="utf-8")

    def test_unicode_paths_round_trip(self, temp_dir, mocker) -> None:
        config_file = temp_dir / "unicode.toml"
        settings = Settings(
            repo=Repo(url=str(temp_dir / "备份"), password_file=str(temp_dir / "密码.txt")),
            sets=[BackupSet(name="写真", include=[str(temp_dir / "写真")])],
        )
        mocker.patch("rrbackup.config.shutil.which", return_value="restic")

        save_config(settings, config_file)
        loaded = load_config(config_file)

        assert loaded.sets[0].name == "写真"
        assert "写真" in loaded.sets[0].include[0]
