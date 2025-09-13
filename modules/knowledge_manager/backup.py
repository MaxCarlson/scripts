#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SQLite backup helpers for Knowledge Manager.

Usage via CLI: `km db backup [--dest DIR] [--keep N]`

Public function:
- perform_backup(base_data_dir: Optional[Path], dest_dir: Optional[Path], keep: int) -> Path
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
import logging
import sqlite3

from . import utils

def _rotate(backup_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    backups: List[Path] = sorted(backup_dir.glob("km_backup_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink(missing_ok=True)
        except Exception as ex:
            logging.getLogger(__name__).warning("Could not remove old backup %s: %s", old, ex)

def perform_backup(base_data_dir: Optional[Path] = None, dest_dir: Optional[Path] = None, keep: int = 10) -> Path:
    db_path = utils.get_db_path(base_data_dir)
    dest = Path(dest_dir) if dest_dir else db_path.parent / "backups"
    dest.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = dest / f"km_backup_{ts}.sqlite3"

    # Use the sqlite3 backup API for a consistent snapshot
    with sqlite3.connect(db_path) as src, sqlite3.connect(out_path) as dst:
        src.backup(dst)

    _rotate(dest, keep)
    logging.getLogger(__name__).info("Database backup created at %s", out_path)
    return out_path
