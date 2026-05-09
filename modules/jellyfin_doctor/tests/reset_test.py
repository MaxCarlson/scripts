from __future__ import annotations

from pathlib import Path

from jellyfin_doctor.paths import JellyfinPaths
from jellyfin_doctor.reset import reset_state


def _paths(root: Path) -> JellyfinPaths:
    return JellyfinPaths.from_overrides(server_dir=root)


def test_reset_cache_renames_and_recreates_cache(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.cache_dir.mkdir(parents=True)
    (paths.cache_dir / "x").write_text("x", encoding="utf-8")
    result = reset_state(
        paths=paths,
        kind="cache",
        backup_dir=work_tmp,
        stamp="20260509_100000",
        running_check=lambda: False,
    )
    assert (paths.server_dir / "cache.disabled.20260509_100000" / "x").exists()
    assert paths.cache_dir.exists()
    assert result.recreated == [paths.cache_dir]


def test_reset_metadata_renames_cache_and_metadata(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    for directory in (paths.cache_dir, paths.metadata_dir):
        directory.mkdir(parents=True)
    reset_state(paths=paths, kind="metadata", backup_dir=work_tmp, stamp="20260509_100001", running_check=lambda: False)
    assert (paths.server_dir / "cache.disabled.20260509_100001").exists()
    assert (paths.server_dir / "metadata.disabled.20260509_100001").exists()
    assert paths.cache_dir.exists()
    assert paths.metadata_dir.exists()


def test_reset_db_renames_only_db_files(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "jellyfin.db").write_text("db", encoding="utf-8")
    media = work_tmp / "media"
    media.mkdir()
    reset_state(
        paths=paths,
        kind="db",
        backup_dir=work_tmp,
        yes=True,
        stamp="20260509_100002",
        running_check=lambda: False,
    )
    assert (paths.data_dir / "jellyfin.db.disabled.20260509_100002").exists()
    assert media.exists()


def test_reset_full_renames_state_and_recreates_required_dirs(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    for directory in paths.state_dirs().values():
        directory.mkdir(parents=True)
    result = reset_state(
        paths=paths,
        kind="full",
        backup_dir=work_tmp,
        yes=True,
        stamp="20260509_100003",
        running_check=lambda: False,
    )
    assert (paths.server_dir / "data.disabled.20260509_100003").exists()
    assert paths.data_dir.exists()
    assert paths.log_dir.exists()
    assert "Your media folders are not touched." in result.instructions


def test_dry_run_does_not_mutate_filesystem(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.cache_dir.mkdir(parents=True)
    reset_state(
        paths=paths,
        kind="cache",
        backup_dir=work_tmp,
        dry_run=True,
        stamp="20260509_100004",
        running_check=lambda: False,
    )
    assert paths.cache_dir.exists()
    assert not (paths.server_dir / "cache.disabled.20260509_100004").exists()


def test_backup_is_created_before_reset(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.cache_dir.mkdir(parents=True)
    result = reset_state(
        paths=paths,
        kind="cache",
        backup_dir=work_tmp,
        stamp="20260509_100005",
        running_check=lambda: False,
    )
    assert result.backup is not None
    assert result.backup.backup_path.exists()


def test_force_reset_stops_running_jellyfin_before_mutating(work_tmp: Path) -> None:
    paths = _paths(work_tmp / "server")
    paths.cache_dir.mkdir(parents=True)
    stopped = []

    def stop_func(*, force: bool) -> dict[str, object]:
        stopped.append(force)
        return {"still_running": False}

    states = iter([True, False])
    reset_state(
        paths=paths,
        kind="cache",
        backup_dir=work_tmp,
        force=True,
        stamp="20260509_100006",
        running_check=lambda: next(states),
        stop_func=stop_func,
    )
    assert stopped == [True]
    assert (paths.server_dir / "cache.disabled.20260509_100006").exists()


