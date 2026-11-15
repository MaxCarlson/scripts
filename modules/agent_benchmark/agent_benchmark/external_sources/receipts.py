"""Persistence and integrity checking for installed source receipts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from uuid import uuid4

from .specs import InstallReceipt, InstalledSourcesLock


def load_sources_lock(lock_file: Path) -> InstalledSourcesLock:
    """Load the installed sources lock file, or return an empty lock if absent."""
    if not lock_file.is_file():
        return InstalledSourcesLock()
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        return InstalledSourcesLock.from_dict(data)
    except Exception as exc:
        raise ValueError(f"Installation receipt database is corrupt: {lock_file}: {exc}") from exc


def save_sources_lock(lock_file: Path, lock: InstalledSourcesLock) -> None:
    """Atomically save the installed sources lock file."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    temp = lock_file.with_name(f".{lock_file.name}.{uuid4().hex[:8]}.tmp")
    data = lock.to_dict()
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for attempt in range(10):
        try:
            os.replace(temp, lock_file)
            return
        except (PermissionError, OSError):
            time.sleep(0.02)

    temp.unlink(missing_ok=True)
    raise OSError(f"Unable to atomically write installation receipt database: {lock_file}")


def record_receipt(lock_file: Path, receipt: InstallReceipt) -> None:
    """Record a new or updated receipt into the persistent lock file."""
    lock = load_sources_lock(lock_file)
    lock.add_receipt(receipt)
    save_sources_lock(lock_file, lock)
