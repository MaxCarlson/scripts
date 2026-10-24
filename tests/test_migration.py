from scripts_setup.launcher_generator import (
    migrate_wrappers,
    rollback_wrappers,
    is_managed_wrapper,
)


def test_dry_run_never_modifies_files_or_manifest(tmp_path):
    repo_root = tmp_path / "repo"
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True)

    # Legacy file
    legacy_file = bin_dir / "legacy.cmd"
    legacy_content = '@echo off\r\nsetlocal\r\nset "_B=%~dp0"\r\nset "_V=%_B%..\\.venv\\Scripts"\r\n"%_V%\\legacy.exe" %*\r\n'
    legacy_file.write_bytes(legacy_content.encode("utf-8"))

    # Unmanaged custom file
    custom_file = bin_dir / "custom.cmd"
    custom_content = "@echo off\r\necho User custom script\r\n"
    custom_file.write_bytes(custom_content.encode("utf-8"))

    # Run dry-run
    report = migrate_wrappers(repo_root, bin_dir, dry_run=True)
    assert report.is_dry_run is True
    assert not (repo_root / "scripts_manifest.json").exists()
    assert legacy_file.read_bytes() == legacy_content.encode("utf-8")
    assert custom_file.read_bytes() == custom_content.encode("utf-8")


def test_apply_migration_backs_up_and_preserves_unmanaged(tmp_path):
    repo_root = tmp_path / "repo"
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True)

    # Setup dummy module
    mod_dir = repo_root / "modules" / "tool"
    mod_dir.mkdir(parents=True)
    (mod_dir / "pyproject.toml").write_text(
        '[project]\nname = "tool"\nversion = "1.0"\n[project.scripts]\ntool = "tool:main"\n',
        encoding="utf-8",
    )

    # Existing legacy tool wrapper
    legacy_file = bin_dir / "tool.cmd"
    legacy_content = '@echo off\r\nset "_V=%_B%..\\.venv\\Scripts"\r\n'
    legacy_file.write_bytes(legacy_content.encode("utf-8"))

    # Existing custom unmanaged wrapper
    custom_file = bin_dir / "my_custom.cmd"
    custom_content = "@echo off\r\necho USER SCRIPT\r\n"
    custom_file.write_bytes(custom_content.encode("utf-8"))

    backup_dir = tmp_path / "custom_backup"

    # Apply migration
    report = migrate_wrappers(repo_root, bin_dir, dry_run=False, backup_dir=backup_dir)
    assert report.is_dry_run is False
    assert (repo_root / "scripts_manifest.json").is_file()

    # Tool wrapper is updated with managed signature
    assert is_managed_wrapper(legacy_file) is True
    assert "Scripts Toolkit Managed Wrapper" in legacy_file.read_text(encoding="utf-8")

    # Unmanaged custom script is completely UNTOUCHED
    assert custom_file.read_bytes() == custom_content.encode("utf-8")

    # Backup was created and contains the original files
    assert (backup_dir / "tool.cmd").read_bytes() == legacy_content.encode("utf-8")
    assert (backup_dir / "my_custom.cmd").read_bytes() == custom_content.encode("utf-8")


def test_rollback_restores_from_backup(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True)

    # Backup has original versions
    (backup_dir / "foo.cmd").write_text("ORIGINAL FOO", encoding="utf-8")
    (backup_dir / "bar.cmd").write_text("ORIGINAL BAR", encoding="utf-8")

    # bin has modified versions
    (bin_dir / "foo.cmd").write_text("MODIFIED FOO", encoding="utf-8")
    (bin_dir / "bar.cmd").write_text("MODIFIED BAR", encoding="utf-8")

    report = rollback_wrappers(backup_dir, bin_dir)
    assert report.restored_count == 2
    assert (bin_dir / "foo.cmd").read_text(encoding="utf-8") == "ORIGINAL FOO"
    assert (bin_dir / "bar.cmd").read_text(encoding="utf-8") == "ORIGINAL BAR"
