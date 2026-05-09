"""Reversible Jellyfin reset operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .backup import BackupResult, create_backup
from .paths import JellyfinPaths
from .process import is_jellyfin_running, start_tray, stop_jellyfin
from .utils import disabled_path, ensure_dir, timestamp

RESET_KINDS = ("cache", "metadata", "db", "root", "state", "full")


@dataclass
class ResetResult:
    """Result of a reset command."""

    kind: str
    renamed: list[tuple[Path, Path]] = field(default_factory=list)
    recreated: list[Path] = field(default_factory=list)
    backup: BackupResult | None = None
    dry_run: bool = False
    instructions: list[str] = field(default_factory=list)


def _rename(path: Path, result: ResetResult, stamp: str, *, dry_run: bool) -> None:
    if not path.exists():
        return
    target = disabled_path(path, stamp)
    result.renamed.append((path, target))
    if not dry_run:
        path.rename(target)


def _recreate(paths: list[Path], result: ResetResult, *, dry_run: bool) -> None:
    for path in paths:
        result.recreated.append(path)
        ensure_dir(path, dry_run=dry_run)


def reset_state(
    *,
    paths: JellyfinPaths,
    kind: str,
    backup_dir: Path,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
    no_backup: bool = False,
    start_after: bool = False,
    running_check=is_jellyfin_running,
    stop_func=stop_jellyfin,
    stamp: str | None = None,
) -> ResetResult:
    """Perform a reversible Jellyfin reset."""
    if kind not in RESET_KINDS:
        raise ValueError(f"Unsupported reset kind: {kind}")
    if running_check() and not dry_run:
        if not force:
            raise RuntimeError("Jellyfin appears to be running. Stop it first or use --force.")
        stop_result = stop_func(force=True)
        if stop_result.get("still_running") or running_check():
            raise RuntimeError("Jellyfin is still running after stop attempt; reset refused.")
    if not yes and kind in {"db", "state", "full"} and not dry_run:
        raise RuntimeError("High-risk reset requires --yes")

    stamp = stamp or timestamp()
    result = ResetResult(kind=kind, dry_run=dry_run)
    if not no_backup:
        backup_mode = "db" if kind == "db" else "full"
        if kind in {"cache", "metadata", "root"}:
            backup_mode = kind
        result.backup = create_backup(
            paths=paths,
            backup_dir=backup_dir,
            mode=backup_mode,
            dry_run=dry_run,
            stamp=stamp,
        )

    if kind == "cache":
        _rename(paths.cache_dir, result, stamp, dry_run=dry_run)
        _recreate([paths.cache_dir], result, dry_run=dry_run)
        result.instructions.append(
            "Start Jellyfin and test UI. If the issue persists, try reset metadata or reset full."
        )
    elif kind == "metadata":
        for path in (paths.cache_dir, paths.metadata_dir):
            _rename(path, result, stamp, dry_run=dry_run)
        _recreate([paths.cache_dir, paths.metadata_dir], result, dry_run=dry_run)
        result.instructions.append(
            "Metadata and artwork will be regenerated. Test one library before running broad scans."
        )
    elif kind == "root":
        _rename(paths.root_dir, result, stamp, dry_run=dry_run)
        _recreate([paths.root_dir], result, dry_run=dry_run)
        result.instructions.append("Restart Jellyfin and verify duplicate path warnings are gone.")
    elif kind == "db":
        ensure_dir(paths.data_dir, dry_run=dry_run)
        for db_file in sorted(paths.data_dir.glob("jellyfin.db*")):
            _rename(db_file, result, stamp, dry_run=dry_run)
        result.instructions.append("If startup fails with missing __EFMigrationsHistory, run reset full.")
    else:
        for path in (paths.data_dir, paths.config_dir, paths.cache_dir, paths.metadata_dir, paths.root_dir):
            _rename(path, result, stamp, dry_run=dry_run)
        _recreate(
            [paths.data_dir, paths.config_dir, paths.cache_dir, paths.metadata_dir, paths.root_dir, paths.log_dir],
            result,
            dry_run=dry_run,
        )
        result.instructions.extend(
            [
                "Your media folders are not touched.",
                "Old Jellyfin state was renamed with .disabled.<timestamp>.",
                "Open http://localhost:8096 and complete first-time setup.",
                "Add one test library only before recreating broader or overlapping libraries.",
            ]
        )

    if start_after and not dry_run:
        start_tray(paths.tray_exe)
    return result
