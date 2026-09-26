"""Stage MangaDL control databases and run logs on scratch until run completion."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .scratch import partial_root_for


def _database_stamp(path: Path) -> list[list[int]]:
    stamp: list[list[int]] = []
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            info = candidate.stat()
            stamp.append([info.st_size, info.st_mtime_ns])
        except FileNotFoundError:
            stamp.append([])
    return stamp


def _backup_database(source: Path | None, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source is None or not source.is_file():
        with (
            sqlite3.connect(":memory:") as input_db,
            sqlite3.connect(target) as output_db,
        ):
            input_db.backup(output_db)
        return
    with (
        sqlite3.connect(f"file:{source}?mode=ro", uri=True) as input_db,
        sqlite3.connect(target) as output_db,
    ):
        input_db.backup(output_db)


class ScratchControls:
    """Keep active SQLite/log I/O on scratch and sync canonical files at the end."""

    def __init__(
        self,
        destination: Path,
        scratch_dir: Path,
        archive: Path,
        state_db: Path,
        log_dir: Path,
    ) -> None:
        self.root = partial_root_for(destination, scratch_dir).parent / ".control"
        self.archive = self.root / "archive.sqlite3"
        self.state_db = self.root / "state.sqlite3"
        self.log_dir = self.root / "logs"
        self.canonical_archive = archive.resolve()
        self.canonical_state_db = state_db.resolve()
        self.canonical_log_dir = log_dir.resolve()
        self.manifest = self.root / "control.json"

    def _identity(self) -> dict[str, str]:
        return {
            "archive": str(self.canonical_archive),
            "state_db": str(self.canonical_state_db),
            "log_dir": str(self.canonical_log_dir),
        }

    def _stamps(self) -> dict[str, list[list[int]]]:
        return {
            "archive": _database_stamp(self.canonical_archive),
            "state_db": _database_stamp(self.canonical_state_db),
        }

    def _write_manifest(self, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.manifest)

    def prepare(self) -> None:
        if self.manifest.exists():
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
            if payload.get("identity") != self._identity():
                raise RuntimeError(
                    f"scratch control files belong to different archive/state/log paths: {self.manifest}"
                )
            if payload.get("pending"):
                if payload.get("baseline") != self._stamps():
                    raise RuntimeError(
                        "canonical control databases changed while scratch had unsynced work; "
                        f"preserved scratch at {self.root}; reconcile manually before another run"
                    )
                if not self.archive.is_file() or not self.state_db.is_file():
                    raise RuntimeError(
                        f"unsynced scratch control database is missing: {self.root}"
                    )
                return
        self.root.mkdir(parents=True, exist_ok=True)
        _backup_database(self.canonical_archive, self.archive)
        _backup_database(self.canonical_state_db, self.state_db)
        self._write_manifest(
            {"identity": self._identity(), "baseline": self._stamps(), "pending": True}
        )

    def sync(self, run_id: str, *, archive_safe: bool = True) -> None:
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        if payload.get("baseline") != self._stamps():
            raise RuntimeError(
                "canonical control databases changed during the scratch run; "
                f"preserved scratch at {self.root}; no control database was overwritten"
            )
        databases = [("state_db", self.state_db, self.canonical_state_db)]
        if archive_safe:
            databases.insert(0, ("archive", self.archive, self.canonical_archive))
        for name, source, target in databases:
            _backup_database(source, target)
            payload["baseline"][name] = _database_stamp(target)
            self._write_manifest(payload)
        source_logs = self.log_dir / run_id
        if source_logs.is_dir():
            shutil.copytree(
                source_logs, self.canonical_log_dir / run_id, dirs_exist_ok=True
            )
        payload["baseline"] = self._stamps()
        payload["pending"] = not archive_safe
        self._write_manifest(payload)


def archive_cleanup_checkpoint(
    partial_root: Path, working_archive: Path, canonical_archive: Path, *, verify: bool
) -> None:
    """Keep the scratch conflict baseline consistent with archive-aware cleanup."""
    manifest = partial_root.parent / ".control" / "control.json"
    if not manifest.is_file():
        return
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    identity = payload.get("identity", {})
    if (
        identity.get("archive") != str(canonical_archive)
        or working_archive != partial_root.parent / ".control" / "archive.sqlite3"
    ):
        raise RuntimeError(
            f"scratch archive ownership does not match control manifest: {manifest}"
        )
    current = _database_stamp(canonical_archive)
    if verify:
        if payload.get("baseline", {}).get("archive") != current:
            raise RuntimeError(
                f"canonical archive changed since scratch staging: {canonical_archive}"
            )
        return
    payload["baseline"]["archive"] = current
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(manifest)
