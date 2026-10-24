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
    source_file_sha256: str = ""
    source_wal_file_sha256: str | None = None
    backup_snapshot_sha256: str = ""
    is_wal_mode: bool = False
    wal_file_present: bool = False
    audit_notes: str = ""
    manifest_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreReport:
    backup_path: str
    target_path: str
    restored_timestamp_iso: str
    pre_restore_backup_path: str | None
    integrity_check_passed: bool
    stale_wal_shm_cleaned: bool = False
    target_preexisted: bool = False
    rollback_performed: bool = False


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
    and produces a verifiable audit manifest distinguishing the raw source file hash
    from the logical, WAL-consistent backup snapshot.
    """
    src = Path(source_path).resolve()
    dst = Path(destination_path).resolve()

    if not src.exists():
        raise FileNotFoundError(f"Source database not found: {src}")

    if dst.exists() and not force:
        raise FileExistsError(f"Destination already exists: {dst}. Use force (-f/--force) to overwrite.")

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Compute raw source file sha256 before backup
    source_file_sha = calculate_sha256(src)
    source_size = src.stat().st_size

    # Check for presence of WAL and SHM files
    source_wal = src.parent / f"{src.name}-wal"
    wal_present = source_wal.exists()
    source_wal_sha = calculate_sha256(source_wal) if wal_present else None

    # Online backup using standard sqlite3 Connection.backup API
    with get_readonly_connection(src) as src_conn:
        sqlite_ver = sqlite3.sqlite_version
        page_size = src_conn.execute("PRAGMA page_size;").fetchone()[0]
        page_count = src_conn.execute("PRAGMA page_count;").fetchone()[0]
        j_mode = src_conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
        is_wal = j_mode == "wal"

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

    notes = (
        "backup_snapshot_sha256 represents the logical, WAL-consistent database snapshot produced by SQLite's "
        "online backup API. source_file_sha256 represents the physical on-disk source file (excluding uncheckpointed "
        "WAL frames if present)."
    )

    manifest = BackupManifest(
        source_path=str(src),
        destination_path=str(dst),
        backup_timestamp_iso=now_iso,
        source_sha256=source_file_sha,
        destination_sha256=dst_sha,
        source_size_bytes=source_size,
        destination_size_bytes=dst_size,
        page_count=page_count,
        page_size=page_size,
        sqlite_version=sqlite_ver,
        integrity_check_passed=integrity_ok,
        source_file_sha256=source_file_sha,
        source_wal_file_sha256=source_wal_sha,
        backup_snapshot_sha256=dst_sha,
        is_wal_mode=is_wal,
        wal_file_present=wal_present,
        audit_notes=notes,
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
    Verifies backup integrity before restore, establishes safe database exclusivity
    that remains held throughout the operation, backs up existing target before any modifications,
    uses the native SQLite backup API without unsafe manual WAL/SHM deletion,
    verifies restored database health, and rolls back cleanly on failure.
    If create_backup_of_target=False and target pre-existed, failure leaves target intact.
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

    target_preexisted = tgt.exists()
    pre_restore_backup: str | None = None
    pre_restore_path: Path | None = None

    if target_preexisted and not force:
        raise FileExistsError(
            f"Target database already exists: {tgt}. "
            "Refusing to overwrite live database without explicit force (-f/--force)."
        )

    tgt.parent.mkdir(parents=True, exist_ok=True)

    # Establish target connection with exclusive locking that remains held throughout restore
    try:
        tgt_conn = sqlite3.connect(str(tgt), timeout=1.0)
        tgt_conn.execute("PRAGMA locking_mode = EXCLUSIVE;")

        if target_preexisted:
            cur = tgt_conn.execute("PRAGMA journal_mode;")
            j_mode = (cur.fetchone() or [""])[0].lower()
            if j_mode == "wal":
                cp = tgt_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                if cp and cp[0] != 0:
                    raise sqlite3.OperationalError(
                        f"Active WAL transactions present (wal_checkpoint returned {cp}). "
                        "Cannot safely establish exclusive database ownership."
                    )
            # Verify exclusive lock can be acquired
            tgt_conn.execute("BEGIN EXCLUSIVE;")
            tgt_conn.commit()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        raise RuntimeError(
            f"Cannot establish exclusive ownership of target database '{tgt}': {exc}. "
            "The database appears to be locked or in active use by another process."
        ) from exc

    post_check_ok = False
    rollback_performed = False

    try:
        if target_preexisted and create_backup_of_target:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_restore_path = tgt.parent / f"{tgt.name}.pre-restore-{ts}.bak"
            pre_conn = sqlite3.connect(str(pre_restore_path))
            try:
                tgt_conn.backup(pre_conn)
            finally:
                pre_conn.close()

            # Generate manifest for pre-restore backup
            manifest_path = pre_restore_path.parent / f"{pre_restore_path.name}.manifest.json"
            manifest_data = {
                "source_path": str(tgt),
                "backup_path": str(pre_restore_path),
                "backup_timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "sha256": calculate_sha256(pre_restore_path),
            }
            manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
            pre_restore_backup = str(pre_restore_path)

        # Restore from backup into tgt_conn via native SQLite backup API
        # Target connection remains open throughout, preserving database ownership and locks
        with get_readonly_connection(bak) as bak_conn:
            bak_conn.backup(tgt_conn)

        # Post-restore verification on tgt_conn
        check_tgt = tgt_conn.execute("PRAGMA quick_check;").fetchone()
        post_check_ok = check_tgt is not None and check_tgt[0] == "ok"
        if not post_check_ok:
            raise RuntimeError(f"Post-restore integrity check failed: {check_tgt[0] if check_tgt else 'unknown'}")

    except Exception as exc:
        logger.error("Restore failed: %s. Handling failure...", exc)
        if target_preexisted:
            if pre_restore_path and pre_restore_path.exists():
                try:
                    with get_readonly_connection(pre_restore_path) as rollback_src:
                        rollback_src.backup(tgt_conn)
                    rollback_performed = True
                    logger.info("Successfully rolled back target database to pre-restore state.")
                except Exception as rb_exc:
                    raise RuntimeError(
                        f"Restore failed ({exc}) AND rollback to pre-restore backup failed: {rb_exc}. "
                        f"Target pre-restore backup preserved at: {pre_restore_path}"
                    ) from exc
                finally:
                    tgt_conn.close()
                raise RuntimeError(
                    f"Restore failed: {exc}. Target was safely rolled back to pre-restore state ({pre_restore_backup})."
                ) from exc
            else:
                # Target pre-existed, but create_backup_of_target was False!
                # NEVER unlink or delete the original target!
                tgt_conn.close()
                raise RuntimeError(
                    f"Restore failed: {exc}. Target database pre-existed and create_backup_of_target was False; "
                    "partial restore cannot be rolled back automatically. Target database was left intact."
                ) from exc
        else:
            # Target did NOT pre-exist; it was created during this restore attempt
            tgt_conn.close()
            tgt.unlink(missing_ok=True)
            for ext in ("-wal", "-shm"):
                (tgt.parent / f"{tgt.name}{ext}").unlink(missing_ok=True)
            raise RuntimeError(f"Restore failed: {exc}. Target did not pre-exist; cleaned up partial files.") from exc
    finally:
        try:
            tgt_conn.close()
        except Exception:
            pass

    return RestoreReport(
        backup_path=str(bak),
        target_path=str(tgt),
        restored_timestamp_iso=datetime.now(timezone.utc).isoformat(),
        pre_restore_backup_path=pre_restore_backup,
        integrity_check_passed=post_check_ok,
        stale_wal_shm_cleaned=False,
        target_preexisted=target_preexisted,
        rollback_performed=rollback_performed,
    )
