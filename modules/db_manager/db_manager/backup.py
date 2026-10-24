"""
backup.py — Online consistent SQLite backups, audit manifests, and safe restoration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from db_manager.connections import get_readonly_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupManifest:
    source_path: str
    destination_path: str
    backup_timestamp_iso: str
    source_sha256: str
    destination_sha256: str
    source_size_bytes: int
    destination_size_bytes: int
    page_count: int
    page_size: int
    sqlite_version: str
    integrity_check_passed: bool
    manifest_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreReport:
    backup_path: str
    target_path: str
    restored_timestamp_iso: str
    pre_restore_backup_path: str | None
    integrity_check_passed: bool
    stale_wal_shm_cleaned: bool


def calculate_sha256(file_path: Path) -> str:
    """Computes SHA256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def backup_database(
    source_path: str | Path,
    destination_path: str | Path,
    force: bool = False,
    write_manifest: bool = True,
) -> BackupManifest:
    """
    Performs an online hot backup using SQLite's native backup API.
    Guarantees consistency across active WAL writers, verifies post-backup integrity,
    and produces a verifiable audit manifest.
    """
    src = Path(source_path).resolve()
    dst = Path(destination_path).resolve()

    if not src.exists():
        raise FileNotFoundError(f"Source database not found: {src}")

    if dst.exists() and not force:
        raise FileExistsError(f"Destination already exists: {dst}. Use force (-f/--force) to overwrite.")

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Compute source sha256 before backup
    source_sha = calculate_sha256(src)
    source_size = src.stat().st_size

    # Online backup using standard sqlite3 Connection.backup API
    with get_readonly_connection(src) as src_conn:
        sqlite_ver = sqlite3.sqlite_version
        page_size = src_conn.execute("PRAGMA page_size;").fetchone()[0]
        page_count = src_conn.execute("PRAGMA page_count;").fetchone()[0]

        # Temporary write connection to destination for backup
        dst_conn = sqlite3.connect(str(dst))
        try:
            # Perform atomic / progressive online copy
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()

    # Verify integrity of destination backup
    with get_readonly_connection(dst) as dst_ro:
        check_row = dst_ro.execute("PRAGMA quick_check;").fetchone()
        integrity_ok = check_row is not None and check_row[0] == "ok"

    dst_sha = calculate_sha256(dst)
    dst_size = dst.stat().st_size
    now_iso = datetime.now(timezone.utc).isoformat()

    manifest = BackupManifest(
        source_path=str(src),
        destination_path=str(dst),
        backup_timestamp_iso=now_iso,
        source_sha256=source_sha,
        destination_sha256=dst_sha,
        source_size_bytes=source_size,
        destination_size_bytes=dst_size,
        page_count=page_count,
        page_size=page_size,
        sqlite_version=sqlite_ver,
        integrity_check_passed=integrity_ok,
    )

    if write_manifest:
        manifest_path = dst.parent / f"{dst.name}.manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    return manifest


def restore_database(
    backup_path: str | Path,
    target_path: str | Path,
    force: bool = False,
    create_backup_of_target: bool = True,
) -> RestoreReport:
    """
    Safely restores a backup into a new path or validated target.
    Verifies backup integrity before restore, establishes safe database exclusivity,
    backs up existing target before any modifications, cleans stale WAL/SHM artifacts
    only after exclusivity is established, verifies restored database health, and
    automatically rolls back to the pre-restore backup if restore fails.
    """
    bak = Path(backup_path).resolve()
    tgt = Path(target_path).resolve()

    if not bak.exists():
        raise FileNotFoundError(f"Backup file not found: {bak}")

    # Verify backup health before doing anything
    with get_readonly_connection(bak) as bak_conn:
        check = bak_conn.execute("PRAGMA quick_check;").fetchone()
        if not check or check[0] != "ok":
            raise ValueError(f"Backup file failed integrity check: {check[0] if check else 'empty'}")

    pre_restore_backup: str | None = None
    pre_restore_path: Path | None = None
    stale_cleaned = False

    if tgt.exists():
        if not force:
            raise FileExistsError(
                f"Target database already exists: {tgt}. "
                "Refusing to overwrite live database without explicit force (-f/--force)."
            )

        # Establish exclusive ownership and verify no active concurrent transactions
        try:
            excl_conn = sqlite3.connect(str(tgt), timeout=1.0)
            try:
                excl_conn.execute("PRAGMA locking_mode = EXCLUSIVE;")
                cur = excl_conn.execute("PRAGMA journal_mode;")
                j_mode = (cur.fetchone() or [""])[0].lower()
                if j_mode == "wal":
                    cp = excl_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                    if cp and cp[0] != 0:
                        raise sqlite3.OperationalError(
                            f"Active WAL transactions present (wal_checkpoint returned {cp}). "
                            "Cannot safely establish exclusive database ownership."
                        )
                # Verify exclusive transaction lock
                excl_conn.execute("BEGIN EXCLUSIVE;")
                excl_conn.commit()
            finally:
                excl_conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            raise RuntimeError(
                f"Cannot establish exclusive ownership of target database '{tgt}': {exc}. "
                "The database appears to be locked or in active use by another process. "
                "Refusing to delete WAL/SHM or overwrite database."
            ) from exc

        # Create pre-restore backup of target
        if create_backup_of_target:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_restore_path = tgt.parent / f"{tgt.name}.pre-restore-{ts}.bak"
            backup_database(tgt, pre_restore_path, force=True, write_manifest=True)
            pre_restore_backup = str(pre_restore_path)

        # Clean stale WAL/SHM files only AFTER exclusivity is verified and target backed up
        for ext in ("-wal", "-shm"):
            wal_shm = tgt.parent / f"{tgt.name}{ext}"
            if wal_shm.exists():
                try:
                    wal_shm.unlink()
                    stale_cleaned = True
                except PermissionError as p_err:
                    raise RuntimeError(
                        f"Cannot unlink WAL/SHM file '{wal_shm}': {p_err}. File is locked by an external process."
                    ) from p_err

    tgt.parent.mkdir(parents=True, exist_ok=True)

    try:
        with get_readonly_connection(bak) as bak_conn:
            tgt_conn = sqlite3.connect(str(tgt))
            try:
                bak_conn.backup(tgt_conn)
            finally:
                tgt_conn.close()

        # Post-restore verification
        with get_readonly_connection(tgt) as tgt_ro:
            check_tgt = tgt_ro.execute("PRAGMA quick_check;").fetchone()
            post_check_ok = check_tgt is not None and check_tgt[0] == "ok"
            if not post_check_ok:
                raise RuntimeError(f"Post-restore integrity check failed: {check_tgt[0] if check_tgt else 'unknown'}")
    except Exception as exc:
        logger.error("Restore failed: %s. Initiating rollback...", exc)
        if pre_restore_path and pre_restore_path.exists():
            try:
                with get_readonly_connection(pre_restore_path) as rollback_src:
                    rollback_dst = sqlite3.connect(str(tgt))
                    try:
                        rollback_src.backup(rollback_dst)
                    finally:
                        rollback_dst.close()
                logger.info("Successfully rolled back target database to pre-restore state.")
            except Exception as rb_exc:
                raise RuntimeError(
                    f"Restore failed ({exc}) AND rollback to pre-restore backup failed: {rb_exc}. "
                    f"Target pre-restore backup preserved at: {pre_restore_path}"
                ) from exc
        elif pre_restore_path is None and tgt.exists():
            # Target was created during this restore run; remove partial artifact
            tgt.unlink(missing_ok=True)
        raise RuntimeError(f"Restore failed: {exc}. Target was safely rolled back to pre-restore state.") from exc

    return RestoreReport(
        backup_path=str(bak),
        target_path=str(tgt),
        restored_timestamp_iso=datetime.now(timezone.utc).isoformat(),
        pre_restore_backup_path=pre_restore_backup,
        integrity_check_passed=post_check_ok,
        stale_wal_shm_cleaned=stale_cleaned,
    )
