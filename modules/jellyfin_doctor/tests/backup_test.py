from __future__ import annotations

from pathlib import Path

from jellyfin_doctor.backup import create_backup, latest_backup, size_report
from jellyfin_doctor.paths import JellyfinPaths


def _paths(root: Path) -> JellyfinPaths:
    return JellyfinPaths.from_overrides(server_dir=root)


def test_db_backup_copies_db_sidecars(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.data_dir.mkdir(parents=True)
    for name in ("jellyfin.db", "jellyfin.db-wal", "jellyfin.db-shm"):
        (paths.data_dir / name).write_text(name, encoding="utf-8")
    result = create_backup(paths=paths, backup_dir=work_tmp, mode="db", stamp="20260509_103409")
    assert result.backup_path.name == "jellyfin_db_backup_20260509_103409"
    assert (result.backup_path / "jellyfin.db").exists()
    assert (result.backup_path / "jellyfin.db-wal").exists()
    assert (result.backup_path / "jellyfin.db-shm").exists()


def test_full_backup_copies_selected_state_dirs(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    for directory in paths.state_dirs().values():
        directory.mkdir(parents=True)
        (directory / "file.txt").write_text("x", encoding="utf-8")
    result = create_backup(paths=paths, backup_dir=work_tmp, mode="full", stamp="20260509_103410")
    assert (result.backup_path / "data" / "file.txt").exists()
    assert (result.backup_path / "root" / "file.txt").exists()
    assert not (result.backup_path / "log").exists()


def test_missing_folders_are_reported_gracefully(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    result = create_backup(paths=paths, backup_dir=work_tmp, mode="cache", stamp="20260509_103411")
    assert result.missing == [paths.cache_dir]


def test_size_report_includes_latest_backup(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "jellyfin.db").write_text("data", encoding="utf-8")
    created = create_backup(paths=paths, backup_dir=work_tmp, mode="db", stamp="20260509_103412")
    report = size_report(paths, work_tmp)
    assert latest_backup(work_tmp) == created.backup_path
    assert report["latest_backup"]["path"] == created.backup_path


