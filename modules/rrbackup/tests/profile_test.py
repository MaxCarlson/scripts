from __future__ import annotations

import json
from pathlib import Path

import pytest

from rrbackup.profile import (
    DEFAULT_REPOSITORY,
    ValueSource,
    discover_legacy_config,
    load_legacy_profile,
    read_path_list,
)


def test_defaults_produce_production_compatible_profile(tmp_path):
    profile, config_path = load_legacy_profile(environment={}, cwd=tmp_path)

    assert config_path is None
    assert profile.repository == DEFAULT_REPOSITORY
    assert profile.tag == "local-main"
    assert profile.use_fs_snapshot
    assert profile.exclude_caches
    assert profile.cpu_policy.normal_threshold == 25
    assert profile.cpu_policy.overdue_threshold == 85
    assert profile.attribution["repository"].source == ValueSource.DEFAULT


def test_environment_overrides_defaults(tmp_path):
    profile, _ = load_legacy_profile(
        environment={
            "BACKUP_MODULE_REPOSITORY": "remote:repo",
            "BACKUP_MODULE_TAG": "environment-tag",
        },
        cwd=tmp_path,
    )

    assert profile.repository == "remote:repo"
    assert profile.tag == "environment-tag"
    assert profile.attribution["repository"].source == ValueSource.ENVIRONMENT
    assert profile.attribution["repository"].detail == "BACKUP_MODULE_REPOSITORY"


def test_json_config_overrides_environment_and_resolves_relative_paths(tmp_path):
    config_path = tmp_path / "config" / "backup.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "repository": "repo",
                "password_file": "password.txt",
                "sources_file": "sources.txt",
                "excludes_file": None,
                "tag": "json-tag",
                "not_backup_days": 4,
                "min_cpu_cutoff": 20,
                "max_cpu_cutoff": 90,
            }
        ),
        encoding="utf-8",
    )

    profile, discovered = load_legacy_profile(
        str(config_path),
        environment={"BACKUP_MODULE_TAG": "environment-tag"},
        cwd=tmp_path,
    )

    assert discovered == config_path.resolve()
    assert profile.repository == str((config_path.parent / "repo").resolve())
    assert profile.password_file == str((config_path.parent / "password.txt").resolve())
    assert profile.sources_file == str((config_path.parent / "sources.txt").resolve())
    assert profile.excludes_file is None
    assert profile.tag == "json-tag"
    assert profile.cpu_policy.normal_threshold == 20
    assert profile.cpu_policy.overdue_threshold == 90
    assert profile.cpu_policy.overdue_after.days == 4
    assert profile.attribution["tag"].source == ValueSource.CONFIG_FILE


def test_explicit_overrides_have_highest_precedence(tmp_path):
    profile, _ = load_legacy_profile(
        environment={"BACKUP_MODULE_TAG": "environment-tag"},
        cwd=tmp_path,
        overrides={"tag": "explicit-tag", "default_restore_root": "restore"},
    )

    assert profile.tag == "explicit-tag"
    assert profile.restore_root == str((tmp_path / "restore").resolve())
    assert profile.attribution["tag"].source == ValueSource.EXPLICIT


def test_unknown_override_is_rejected(tmp_path):
    with pytest.raises(KeyError, match="Unknown profile override"):
        load_legacy_profile(
            environment={},
            cwd=tmp_path,
            overrides={"unknown": True},
        )


def test_discovery_precedence_and_explicit_missing_path(tmp_path):
    environment_config = tmp_path / "environment.json"
    environment_config.write_text("{}", encoding="utf-8")
    cwd_config = tmp_path / "local_backup_config.json"
    cwd_config.write_text("{}", encoding="utf-8")

    assert discover_legacy_config(
        environment={"BACKUP_MODULE_CONFIG": str(environment_config)},
        cwd=tmp_path,
    ) == environment_config.resolve()

    missing = tmp_path / "missing.json"
    assert discover_legacy_config(
        str(missing),
        environment={},
        cwd=tmp_path,
    ) == missing.resolve()

    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_legacy_profile(str(missing), environment={}, cwd=tmp_path)


def test_remote_repository_is_not_converted_to_local_path(tmp_path):
    config_path = tmp_path / "backup.json"
    config_path.write_text(
        json.dumps({"repository": "rclone:gdrive:/backups"}),
        encoding="utf-8",
    )

    profile, _ = load_legacy_profile(str(config_path), environment={}, cwd=tmp_path)

    assert profile.repository == "rclone:gdrive:/backups"


def test_public_dict_contains_values_and_source_attribution(tmp_path):
    profile, _ = load_legacy_profile(environment={}, cwd=tmp_path)

    public = profile.to_public_dict()

    assert public["values"]["repository"] == DEFAULT_REPOSITORY
    assert public["sources"]["repository"]["source"] == "default"
    assert "cpu_policy" in public["values"]


def test_read_path_list_ignores_blank_lines_comments_and_bom(tmp_path):
    path = tmp_path / "sources.txt"
    path.write_text("\ufeff# comment\nC:\\\n\nD:\\Pictures\n", encoding="utf-8")

    assert read_path_list(str(path)) == ["C:\\", "D:\\Pictures"]
    assert read_path_list(None) == []


def test_profile_validation_rejects_invalid_policy(tmp_path):
    with pytest.raises(ValueError, match="cannot be greater"):
        load_legacy_profile(
            environment={},
            cwd=tmp_path,
            overrides={"min_cpu_cutoff": 90, "max_cpu_cutoff": 80},
        )
