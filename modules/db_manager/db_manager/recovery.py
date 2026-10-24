"""
recovery.py — Database recovery diagnostics, backup inventory, and external .recover invocation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any

from db_manager.connections import get_readonly_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupCandidate:
    path: str
    manifest_path: str | None
    mtime_iso: str
    size_bytes: int
    is_valid_sqlite: bool


@dataclass(frozen=True)
class RecoveryDiagnostics:
    database_path: str
    is_file: bool
    file_size_bytes: int
    header_valid: bool
    integrity_output: list[str]
    nearby_backups: list[BackupCandidate]
    sqlite3_cli_available: bool
    sqlite3_recover_supported: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_sqlite_header(path: Path) -> bool:
    """Verifies that the first 16 bytes contain the standard SQLite magic string."""
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\x00"
    except Exception:
        return False


def find_nearby_backups(db_path: Path) -> list[BackupCandidate]:
    """Scans the database directory for candidate backup files and manifests."""
    candidates: list[BackupCandidate] = []
    parent = db_path.parent
    prefix = db_path.stem

    for item in parent.iterdir():
        if item == db_path:
            continue
        if item.name.startswith(prefix) and (item.name.endswith(".bak") or ".pre-" in item.name):
            manifest = parent / f"{item.name}.manifest.json"
            valid_header = check_sqlite_header(item)

            candidates.append(
                BackupCandidate(
                    path=str(item),
                    manifest_path=str(manifest) if manifest.exists() else None,
                    mtime_iso=item.stat().st_mtime_ns.__str__(),
                    size_bytes=item.stat().st_size,
                    is_valid_sqlite=valid_header,
                )
            )

    return sorted(candidates, key=lambda c: c.path)


def check_external_sqlite3_cli() -> tuple[bool, bool]:
    """Checks whether the external `sqlite3` CLI is on PATH and supports `.recover`."""
    cli_path = shutil.which("sqlite3")
    if not cli_path:
        return False, False

    try:
        proc = subprocess.run(
            ["sqlite3", ":memory:", ".help"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        has_recover = ".recover" in proc.stdout
        return True, has_recover
    except Exception:
        return True, False


def diagnose_database_recovery(db_path: str | Path) -> RecoveryDiagnostics:
    """
    Performs non-destructive diagnostics on a damaged or unreadable SQLite database.
    Does not promise forensic row reconstruction without surviving backup/journal data.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    size = path.stat().st_size
    valid_header = check_sqlite_header(path)

    integrity_lines: list[str] = []
    try:
        with get_readonly_connection(path, timeout=2.0) as conn:
            rows = conn.execute("PRAGMA integrity_check;").fetchall()
            integrity_lines = [r[0] for r in rows]
    except Exception as exc:
        integrity_lines = [f"Cannot open connection: {exc}"]

    backups = find_nearby_backups(path)
    cli_avail, recover_avail = check_external_sqlite3_cli()

    notes = (
        "Deleted rows cannot generally be reconstructed from an ordinary SQLite DB without backups "
        "or surviving journal/WAL data. If the database file is corrupted, restore from the latest valid "
        "backup listed above, or invoke external SQLite .recover into a new output file."
    )

    return RecoveryDiagnostics(
        database_path=str(path),
        is_file=path.is_file(),
        file_size_bytes=size,
        header_valid=valid_header,
        integrity_output=integrity_lines,
        nearby_backups=backups,
        sqlite3_cli_available=cli_avail,
        sqlite3_recover_supported=recover_avail,
        notes=notes,
    )


def execute_external_recover(
    corrupt_db_path: str | Path,
    output_db_path: str | Path,
    force: bool = False,
) -> bool:
    """
    Invokes external `sqlite3 <db> .recover | sqlite3 <new_db>` to salvage readable pages into a new database.
    Never alters source database bytes.
    """
    src = Path(corrupt_db_path).resolve()
    dst = Path(output_db_path).resolve()

    if not src.exists():
        raise FileNotFoundError(f"Source database not found: {src}")
    if dst.exists() and not force:
        raise FileExistsError(f"Destination recovery file already exists: {dst}. Pass force (-f/--force) to overwrite.")

    cli_avail, recover_avail = check_external_sqlite3_cli()
    if not cli_avail:
        raise RuntimeError("External 'sqlite3' CLI tool is not installed on PATH.")
    if not recover_avail:
        raise RuntimeError("Installed 'sqlite3' CLI does not support the .recover command (requires SQLite 3.29+).")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and force:
        dst.unlink()

    # Execute piped command safely
    proc1 = subprocess.Popen(["sqlite3", str(src), ".recover"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc2 = subprocess.Popen(["sqlite3", str(dst)], stdin=proc1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc1.stdout:
        proc1.stdout.close()

    _, stderr2 = proc2.communicate()
    proc1.wait()

    if proc2.returncode != 0:
        raise RuntimeError(f"Recovery failed with return code {proc2.returncode}: {stderr2.decode(errors='replace')}")

    return dst.exists() and dst.stat().st_size > 0
