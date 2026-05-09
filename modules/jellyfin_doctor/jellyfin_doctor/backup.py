"""Backup and size-report operations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .paths import JellyfinPaths
from .utils import ensure_dir, timestamp, tree_size

BACKUP_PREFIX_BY_MODE = {"db": "jellyfin_db_backup", "full": "jellyfin_manual_backup"}
BACKUP_MODES = ("db", "cache", "metadata", "root", "config", "full")
DB_GLOB = "jellyfin.db*"


@dataclass
class BackupResult:
    """Result of a backup create operation."""

    backup_path: Path
    mode: str
    copied: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    dry_run: bool = False


def backup_name(mode: str, stamp: str | None = None) -> str:
    """Return a backup folder name for a mode."""
    prefix = BACKUP_PREFIX_BY_MODE.get(mode, "jellyfin_manual_backup")
    return f"{prefix}_{stamp or timestamp()}"


def _sources_for_mode(paths: JellyfinPaths, mode: str) -> list[Path]:
    if mode == "db":
        return sorted(paths.data_dir.glob(DB_GLOB)) if paths.data_dir.exists() else [paths.data_dir / "jellyfin.db"]
    if mode == "full":
        return [paths.data_dir, paths.config_dir, paths.cache_dir, paths.metadata_dir, paths.root_dir]
    mapping = {
        "cache": paths.cache_dir,
        "metadata": paths.metadata_dir,
        "root": paths.root_dir,
        "config": paths.config_dir,
    }
    return [mapping[mode]]


def create_backup(
    *,
    paths: JellyfinPaths,
    backup_dir: Path,
    mode: str = "db",
    dry_run: bool = False,
    stamp: str | None = None,
) -> BackupResult:
    """Create a timestamped Jellyfin backup."""
    if mode not in BACKUP_MODES:
        raise ValueError(f"Unsupported backup mode: {mode}")
    target = backup_dir / backup_name(mode, stamp)
    result = BackupResult(backup_path=target, mode=mode, dry_run=dry_run)
    if not dry_run:
        target.mkdir(parents=True, exist_ok=False)
    for source in _sources_for_mode(paths, mode):
        if not source.exists():
            result.missing.append(source)
            continue
        destination = target / source.name
        result.copied.append(destination)
        if dry_run:
            continue
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            ensure_dir(destination.parent)
            shutil.copy2(source, destination)
    return result


def latest_backup(backup_dir: Path) -> Path | None:
    """Return newest Jellyfin backup folder under ``backup_dir``."""
    candidates: list[Path] = []
    for pattern in ("jellyfin_manual_backup_*", "jellyfin_db_backup_*"):
        candidates.extend(path for path in backup_dir.glob(pattern) if path.is_dir())
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def size_report(paths: JellyfinPaths, backup_dir: Path) -> dict[str, object]:
    """Return size and file-count information for Jellyfin state and latest backup."""
    state: dict[str, dict[str, object]] = {}
    for name, path in paths.report_dirs().items():
        bytes_total, files = tree_size(path)
        state[name] = {"path": path, "exists": path.exists(), "bytes": bytes_total, "files": files}
    db_files = []
    if paths.data_dir.exists():
        for db_file in sorted(paths.data_dir.glob(DB_GLOB)):
            db_files.append({"path": db_file, "bytes": db_file.stat().st_size})
    latest = latest_backup(backup_dir)
    latest_info = None
    if latest:
        latest_info = {"path": latest, "bytes": tree_size(latest)[0], "files": tree_size(latest)[1]}
    return {"state": state, "db_files": db_files, "latest_backup": latest_info}


def restore_backup(
    *,
    backup_path: Path,
    paths: JellyfinPaths,
    mode: str,
    dry_run: bool = False,
    yes: bool = False,
) -> dict[str, object]:
    """Restore selected files from a backup path."""
    if not yes and not dry_run:
        raise RuntimeError("Restore requires --yes")
    restored: list[Path] = []
    if mode == "db":
        ensure_dir(paths.data_dir, dry_run=dry_run)
        for source in sorted(backup_path.glob(DB_GLOB)):
            target = paths.data_dir / source.name
            restored.append(target)
            if not dry_run:
                shutil.copy2(source, target)
    else:
        for source in _sources_for_mode(paths, mode):
            backup_source = backup_path / source.name
            if not backup_source.exists():
                continue
            restored.append(source)
            if dry_run:
                continue
            if source.exists():
                raise RuntimeError(f"Refusing to overwrite existing restore target: {source}")
            if backup_source.is_dir():
                shutil.copytree(backup_source, source)
            else:
                ensure_dir(source.parent)
                shutil.copy2(backup_source, source)
    return {"backup_path": backup_path, "mode": mode, "restored": restored, "dry_run": dry_run}

