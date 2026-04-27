from __future__ import annotations

from backup_module.core import (
    DEFAULT_EXCLUDES_FILE,
    DEFAULT_LOCK_FILE,
    DEFAULT_LOG_FILE,
    DEFAULT_PASSWORD_FILE,
    DEFAULT_REPOSITORY,
    DEFAULT_RESTORE_ROOT,
    DEFAULT_SOURCES_FILE,
    DEFAULT_STATUS_FILE,
    DEFAULT_TAG,
    BackupConfig,
    build_restore_command,
    build_restic_backup_command,
    default_restore_target,
    expand_restore_include_values,
    to_restic_path,
)


def make_config() -> BackupConfig:
    return BackupConfig(
        repository="B:\\ResticRepos\\PC-Local",
        password_file="C:\\BackupConfig\\restic-local-password.txt",
        sources_file="C:\\BackupConfig\\local-sources.txt",
        excludes_file="C:\\BackupConfig\\local-excludes.txt",
        status_file="C:\\BackupConfig\\local-backup-status.json",
        log_file="C:\\BackupConfig\\local-backup.log",
        lock_file="C:\\BackupConfig\\local-backup.lock",
        tag="local-main",
        restic_executable="restic",
        default_restore_root="B:\\ResticRestore",
    )


def test_default_config_uses_current_windows_setup_values() -> None:
    config = BackupConfig()

    assert config.repository == DEFAULT_REPOSITORY
    assert config.password_file == DEFAULT_PASSWORD_FILE
    assert config.sources_file == DEFAULT_SOURCES_FILE
    assert config.excludes_file == DEFAULT_EXCLUDES_FILE
    assert config.status_file == DEFAULT_STATUS_FILE
    assert config.log_file == DEFAULT_LOG_FILE
    assert config.lock_file == DEFAULT_LOCK_FILE
    assert config.tag == DEFAULT_TAG
    assert config.default_restore_root == DEFAULT_RESTORE_ROOT


def test_default_restore_target_uses_configured_restore_root() -> None:
    target = default_restore_target("B:\\ResticRestore")

    assert target.startswith("B:\\ResticRestore")
    assert "restore-" in target


def test_to_restic_path_converts_windows_drive_path() -> None:
    assert (
        to_restic_path("D:\\Pictures\\Saved\\tmpvids\\tmphent2")
        == "/D/Pictures/Saved/tmpvids/tmphent2"
    )


def test_to_restic_path_preserves_existing_restic_path() -> None:
    assert (
        to_restic_path("/D/Pictures/Saved/tmpvids/tmphent2")
        == "/D/Pictures/Saved/tmpvids/tmphent2"
    )


def test_expand_restore_include_values_expands_bare_name() -> None:
    assert expand_restore_include_values(["tmphent2"], []) == [
        "**/tmphent2",
        "**/tmphent2/**",
    ]


def test_expand_restore_include_values_expands_windows_path() -> None:
    assert expand_restore_include_values(
        ["D:\\Pictures\\Saved\\tmpvids\\tmphent2"], []
    ) == [
        "/D/Pictures/Saved/tmpvids/tmphent2",
        "/D/Pictures/Saved/tmpvids/tmphent2/**",
    ]


def test_build_restore_command_uses_latest_by_default_shape() -> None:
    config = make_config()
    command = build_restore_command(
        config,
        snapshot_id="latest",
        target_path="B:\\RestoreTarget",
        include_paths=["D:\\Pictures\\Saved\\tmpvids\\tmphent2"],
    )

    assert command[:6] == [
        "restic",
        "-r",
        "B:\\ResticRepos\\PC-Local",
        "--password-file",
        config.password_file,
        "restore",
    ]
    assert "latest" in command
    assert "--target" in command
    assert "B:\\RestoreTarget" in command
    assert "--iinclude" in command
    assert "/D/Pictures/Saved/tmpvids/tmphent2" in command
    assert "/D/Pictures/Saved/tmpvids/tmphent2/**" in command


def test_build_restic_backup_command_includes_expected_flags() -> None:
    config = make_config()
    command = build_restic_backup_command(config)

    assert command[:6] == [
        "restic",
        "-r",
        "B:\\ResticRepos\\PC-Local",
        "--password-file",
        config.password_file,
        "backup",
    ]
    assert "--use-fs-snapshot" in command
    assert "--files-from-verbatim" in command
    assert config.sources_file in command
    assert "--iexclude-file" in command
    assert config.excludes_file in command
    assert "--exclude-caches" in command
    assert "--tag" in command
    assert "local-main" in command
