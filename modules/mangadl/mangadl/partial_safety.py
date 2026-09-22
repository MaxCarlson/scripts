from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

PARTIAL_FORMAT_VERSION = "1"
PARTIAL_VERSION_NAME = ".version"
PARTIAL_META_NAME = ".mangadl-partial.json"
PARTIAL_MANIFEST_NAME = ".mangadl-archive-entries.jsonl"
PARTIAL_CONTROL_NAMES = frozenset(
    {PARTIAL_VERSION_NAME, PARTIAL_META_NAME, PARTIAL_MANIFEST_NAME}
)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    archive_key: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class CleanupTarget:
    path: Path
    owner: Path
    relative_to_owner: Path
    files: int
    bytes: int
    last_activity: float
    entries: tuple[ManifestEntry, ...]
    archive: Path | None
    files_only: bool


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def initialize_partial(
    partial_root: Path,
    partial: Path,
    *,
    url: str,
    backend: str,
    archive: Path,
    run_id: str,
    job_id: int,
    attempt_id: str,
    worker: int,
) -> None:
    """Create durable ownership metadata before a backend writes partial data."""
    partial_root.mkdir(parents=True, exist_ok=True)
    version_path = partial_root / PARTIAL_VERSION_NAME
    if version_path.exists():
        version = version_path.read_text(encoding="utf-8", errors="replace").strip()
        if version != PARTIAL_FORMAT_VERSION:
            raise RuntimeError(
                f"unsupported partial format {version!r} in {partial_root}; expected {PARTIAL_FORMAT_VERSION}"
            )
    else:
        version_path.write_text(PARTIAL_FORMAT_VERSION + "\n", encoding="utf-8")

    partial.mkdir(parents=True, exist_ok=True)
    meta_path = partial / PARTIAL_META_NAME
    created_at = time.time()
    if meta_path.exists():
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = float(existing.get("created_at", created_at))
        previous_archive = Path(str(existing.get("archive", archive))).expanduser().resolve()
        if previous_archive != archive.expanduser().resolve():
            manifest = partial / PARTIAL_MANIFEST_NAME
            if manifest.exists() and manifest.stat().st_size:
                raise RuntimeError(
                    f"partial {partial.name} is already tracked against a different archive: {previous_archive}"
                )

    _atomic_json(
        meta_path,
        {
            "schema": 1,
            "partial_key": partial.name,
            "url": url,
            "backend": backend,
            "archive": str(archive.expanduser().resolve()),
            "run_id": run_id,
            "job_id": job_id,
            "attempt_id": attempt_id,
            "worker": worker,
            "worker_pid": os.getpid(),
            "created_at": created_at,
            "updated_at": time.time(),
        },
    )
    if backend == "gallery-dl":
        (partial / PARTIAL_MANIFEST_NAME).touch(exist_ok=True)


def append_manifest_entry(partial: Path, archive_key: str, downloaded_path: Path) -> None:
    resolved_partial = partial.resolve()
    resolved_path = downloaded_path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_partial)
    except ValueError as exc:
        raise ValueError(f"downloaded path is outside its partial: {downloaded_path}") from exc
    payload = {"archive_key": archive_key, "path": relative.as_posix()}
    with (partial / PARTIAL_MANIFEST_NAME).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")


def remove_partial_controls(partial: Path) -> None:
    for name in PARTIAL_CONTROL_NAMES:
        path = partial / name
        if path.exists():
            path.unlink()


def load_manifest(owner: Path) -> tuple[ManifestEntry, ...]:
    manifest = owner / PARTIAL_MANIFEST_NAME
    if not manifest.exists():
        raise ValueError(f"partial has no archive ownership manifest: {owner}")
    entries: list[ManifestEntry] = []
    for number, line in enumerate(manifest.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            key = str(payload["archive_key"])
            relative = Path(str(payload["path"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid manifest record {manifest}:{number}: {exc}") from exc
        if not key or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe manifest record {manifest}:{number}")
        entries.append(ManifestEntry(key, relative.as_posix()))
    return tuple(entries)


def _pid_running(pid: object) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _process_commands() -> tuple[tuple[int, str], ...] | None:
    """Best-effort process command-line inventory for legacy partial ownership."""
    if sys.platform == "win32":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            return None
        command = [
            executable,
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            payload = json.loads(result.stdout)
            rows = payload if isinstance(payload, list) else [payload]
            return tuple(
                (int(row["ProcessId"]), str(row.get("CommandLine") or ""))
                for row in rows
                if row.get("ProcessId") is not None
            )
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
            return None

    proc = Path("/proc")
    if proc.is_dir():
        commands: list[tuple[int, str]] = []
        for candidate in proc.iterdir():
            if not candidate.name.isdigit():
                continue
            try:
                raw = (candidate / "cmdline").read_bytes()
            except OSError:
                continue
            commands.append((int(candidate.name), raw.replace(b"\0", b" ").decode(errors="replace")))
        return tuple(commands)
    return None


def _gallery_processes_for_path(
    path: Path,
    commands: tuple[tuple[int, str], ...],
) -> tuple[int, ...]:
    needle = str(path.resolve()).replace("\\", "/").casefold()
    matches: list[int] = []
    for pid, command in commands:
        normalized = command.replace("\\", "/").casefold()
        if needle in normalized and ("gallery_dl" in normalized or "gallery-dl" in normalized):
            matches.append(pid)
    return tuple(sorted(set(matches)))


def _tree_snapshot(path: Path) -> tuple[int, int, float]:
    if path.is_symlink() or path.is_file():
        stat = path.lstat()
        return 1, stat.st_size, max(stat.st_ctime, stat.st_mtime)
    files = size = 0
    last_activity = 0.0
    for root, directories, names in os.walk(path, followlinks=False):
        root_path = Path(root)
        try:
            root_stat = root_path.stat()
            last_activity = max(last_activity, root_stat.st_ctime, root_stat.st_mtime)
        except OSError:
            pass
        for name in names:
            candidate = root_path / name
            files += 1
            try:
                stat = candidate.lstat()
                size += stat.st_size
                last_activity = max(last_activity, stat.st_ctime, stat.st_mtime)
            except OSError:
                pass
        directories[:] = [name for name in directories if not (root_path / name).is_symlink()]
    return files, size, last_activity


def _tree_size(path: Path) -> tuple[int, int]:
    files, size, _last_activity = _tree_snapshot(path)
    return files, size


def _normalize_targets(partial_root: Path, values: Iterable[str]) -> list[Path]:
    root = partial_root.expanduser().resolve()
    selected: list[Path] = []
    for value in values:
        supplied = Path(value).expanduser()
        candidate = (supplied if supplied.is_absolute() else root / supplied).resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"cleanup target escapes partial root: {value}") from exc
        if not relative.parts:
            raise ValueError("refusing to clean the entire partial root; select one or more children")
        if any(part in PARTIAL_CONTROL_NAMES for part in relative.parts):
            raise ValueError(f"select the owning partial or media path, not a control file: {value}")
        if not candidate.exists() and not candidate.is_symlink():
            raise ValueError(f"cleanup target does not exist: {candidate}")
        selected.append(candidate)

    unique = sorted(set(selected), key=lambda path: (len(path.parts), str(path).casefold()))
    return [
        path
        for index, path in enumerate(unique)
        if not any(path.is_relative_to(parent) for parent in unique[:index])
    ]


def _read_meta(owner: Path) -> dict[str, Any]:
    meta_path = owner / PARTIAL_META_NAME
    if not meta_path.exists():
        raise ValueError(f"legacy/untracked partial has no metadata: {owner}")
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid partial metadata {meta_path}: {exc}") from exc
    if payload.get("schema") != 1 or payload.get("partial_key") != owner.name:
        raise ValueError(f"partial metadata does not match its directory: {meta_path}")
    if _pid_running(payload.get("worker_pid")):
        raise ValueError(f"partial still belongs to active worker PID {payload['worker_pid']}: {owner}")
    return payload


def _entries_for_target(entries: tuple[ManifestEntry, ...], relative: Path) -> tuple[ManifestEntry, ...]:
    if relative == Path("."):
        return entries
    selected: dict[tuple[str, str], ManifestEntry] = {}
    for entry in entries:
        entry_path = Path(entry.relative_path)
        if entry_path == relative or entry_path.is_relative_to(relative):
            selected[(entry.archive_key, entry.relative_path)] = entry
    return tuple(selected.values())


def plan_cleanup(
    destination: Path,
    targets: Iterable[str],
    *,
    archive_override: Path | None = None,
    files_only: bool = False,
    legacy_archive_keys: Mapping[Path, Iterable[str]] | None = None,
) -> tuple[Path, tuple[CleanupTarget, ...]]:
    partial_root = destination.expanduser().resolve() / "_partial"
    if not partial_root.is_dir():
        raise ValueError(f"partial root does not exist: {partial_root}")
    planned: list[CleanupTarget] = []
    process_commands = _process_commands()
    for target in _normalize_targets(partial_root, targets):
        relative_to_root = target.relative_to(partial_root)
        owner = partial_root / relative_to_root.parts[0]
        active_pids = _gallery_processes_for_path(owner, process_commands or ())
        if active_pids:
            joined = ", ".join(str(pid) for pid in active_pids)
            raise ValueError(
                f"partial is still being written by gallery-dl PID(s) {joined}: {owner}"
            )
        relative_to_owner = target.relative_to(owner) if target != owner else Path(".")
        entries: tuple[ManifestEntry, ...] = ()
        archive: Path | None = None
        meta_path = owner / PARTIAL_META_NAME
        meta = _read_meta(owner) if meta_path.exists() else None
        if not files_only:
            if meta is None:
                resolved_owner = owner.resolve()
                supplied_keys = set((legacy_archive_keys or {}).get(resolved_owner, ()))
                if target != owner:
                    raise ValueError(
                        "legacy archive reconciliation requires selecting the whole partial owner: "
                        f"{owner}"
                    )
                if archive_override is None:
                    raise ValueError(
                        f"legacy partial requires an explicit archive and URL reconciliation: {owner}"
                    )
                if not supplied_keys:
                    raise ValueError(f"legacy partial has no reconstructed archive keys: {owner}")
                archive = archive_override.expanduser().resolve()
                if not archive.is_file():
                    raise ValueError(f"tracked archive does not exist: {archive}")
                entries = tuple(
                    ManifestEntry(key, ".") for key in sorted(supplied_keys)
                )
            elif meta.get("backend") == "gallery-dl":
                entries = _entries_for_target(load_manifest(owner), relative_to_owner)
                archive = Path(str(meta.get("archive", ""))).expanduser().resolve()
                if not str(meta.get("archive", "")):
                    raise ValueError(f"partial metadata has no archive path: {owner}")
                if archive_override is not None and archive != archive_override.expanduser().resolve():
                    raise ValueError(f"partial archive {archive} does not match requested archive {archive_override}")
                if not archive.is_file():
                    raise ValueError(f"tracked archive does not exist: {archive}")
        files, size, last_activity = _tree_snapshot(target)
        if (
            meta is None
            and process_commands is None
            and files >= 100
            and last_activity
            and time.time() - last_activity < 120
        ):
            raise ValueError(
                "legacy partial has filesystem activity within the last two minutes; "
                f"stop its writer and retry: {owner}"
            )
        planned.append(
            CleanupTarget(
                target,
                owner,
                relative_to_owner,
                files,
                size,
                last_activity,
                entries,
                archive,
                files_only,
            )
        )
    return partial_root, tuple(planned)


def _existing_archive_keys(archive: Path, keys: set[str]) -> set[str]:
    if not keys:
        return set()
    connection = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive'"
        ).fetchone()
        if table is None:
            raise ValueError(f"archive table is missing: {archive}")
        found: set[str] = set()
        values = sorted(keys)
        for offset in range(0, len(values), 500):
            chunk = values[offset : offset + 500]
            marks = ",".join("?" for _ in chunk)
            found.update(row[0] for row in connection.execute(f"SELECT entry FROM archive WHERE entry IN ({marks})", chunk))
        return found
    finally:
        connection.close()


def cleanup_preview(partial_root: Path, targets: tuple[CleanupTarget, ...]) -> dict[str, Any]:
    archives: dict[str, set[str]] = {}
    for target in targets:
        if target.archive is not None:
            archives.setdefault(str(target.archive), set()).update(entry.archive_key for entry in target.entries)
    matched = {
        archive: len(_existing_archive_keys(Path(archive), keys))
        for archive, keys in archives.items()
    }
    return {
        "partial_root": str(partial_root),
        "files": sum(target.files for target in targets),
        "bytes": sum(target.bytes for target in targets),
        "manifest_entries": sum(len(target.entries) for target in targets),
        "archive_matches": sum(matched.values()),
        "files_only": all(target.files_only for target in targets),
        "targets": [str(target.path) for target in targets],
        "archives": matched,
    }


def _backup_archive(archive: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = archive.with_name(f"{archive.name}.backup-{stamp}")
    suffix = 1
    while backup.exists():
        backup = archive.with_name(f"{archive.name}.backup-{stamp}-{suffix}")
        suffix += 1
    source = sqlite3.connect(str(archive))
    destination = sqlite3.connect(str(backup))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup


def _delete_archive_keys(archive: Path, keys: set[str]) -> int:
    if not keys:
        return 0
    connection = sqlite3.connect(str(archive), timeout=60)
    try:
        connection.execute("BEGIN IMMEDIATE")
        before = connection.total_changes
        connection.executemany("DELETE FROM archive WHERE entry=?", ((key,) for key in sorted(keys)))
        removed = connection.total_changes - before
        connection.commit()
        return removed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _remove_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def _rewrite_remaining_manifest(owner: Path, removed: set[tuple[str, str]]) -> None:
    manifest = owner / PARTIAL_MANIFEST_NAME
    if not owner.exists() or not manifest.exists():
        return
    remaining = [
        entry
        for entry in load_manifest(owner)
        if (entry.archive_key, entry.relative_path) not in removed
    ]
    temporary = manifest.with_name(manifest.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for entry in remaining:
            stream.write(
                json.dumps(
                    {"archive_key": entry.archive_key, "path": entry.relative_path},
                    sort_keys=True,
                )
                + "\n"
            )
    temporary.replace(manifest)


def apply_cleanup(targets: tuple[CleanupTarget, ...], *, backup: bool = True) -> dict[str, Any]:
    process_commands = _process_commands()
    for target in targets:
        active_pids = _gallery_processes_for_path(target.owner, process_commands or ())
        if active_pids:
            joined = ", ".join(str(pid) for pid in active_pids)
            raise RuntimeError(
                f"partial became active under gallery-dl PID(s) {joined}: {target.owner}"
            )
        meta_path = target.owner / PARTIAL_META_NAME
        if meta_path.is_file():
            _read_meta(target.owner)
        if not target.path.exists() and not target.path.is_symlink():
            raise RuntimeError(f"cleanup target disappeared after preview: {target.path}")
        current_files, current_bytes, current_activity = _tree_snapshot(target.path)
        if (current_files, current_bytes, current_activity) != (
            target.files,
            target.bytes,
            target.last_activity,
        ):
            raise RuntimeError(
                "cleanup target changed after preview; rerun cleanup before applying: "
                f"{target.path} (was {target.files} files/{target.bytes} bytes, "
                f"now {current_files} files/{current_bytes} bytes)"
            )

    archive_keys: dict[Path, set[str]] = {}
    for target in targets:
        if target.archive is not None:
            archive_keys.setdefault(target.archive, set()).update(entry.archive_key for entry in target.entries)

    backups: list[str] = []
    removed_entries = 0
    for archive, keys in archive_keys.items():
        if backup and keys:
            backups.append(str(_backup_archive(archive)))
        removed_entries += _delete_archive_keys(archive, keys)

    removed_by_owner: dict[Path, set[tuple[str, str]]] = {}
    for target in targets:
        removed_by_owner.setdefault(target.owner, set()).update(
            (entry.archive_key, entry.relative_path) for entry in target.entries
        )
        _remove_target(target.path)
    for owner, removed in removed_by_owner.items():
        _rewrite_remaining_manifest(owner, removed)

    return {
        "removed_files": sum(target.files for target in targets),
        "removed_bytes": sum(target.bytes for target in targets),
        "removed_archive_entries": removed_entries,
        "archive_backups": backups,
        "targets": [str(target.path) for target in targets],
    }
