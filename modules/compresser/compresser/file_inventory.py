"""Filesystem-only candidate inventory. Never claims decoded image validity."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
from statistics import median
from typing import Iterable

from .scanner import IMAGE_EXTENSIONS


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _raise_walk_error(error: OSError) -> None:
    raise error


def scan_file_inventory(
    source: Path,
    database: Path,
    *,
    exclude_stems: Iterable[str] = (),
    single_gallery: bool = False,
) -> dict:
    """Refresh extension/size statistics and atomically save a complete enumeration."""
    if _linked(source):
        raise ValueError("Filesystem inventory cannot target a linked source")
    root = source.expanduser().resolve()
    destination = database.expanduser().resolve()
    directory = root.is_dir()
    if not root.exists():
        raise FileNotFoundError(root)
    if directory and (root.name.startswith(".") or root.name.casefold() == "_partial"):
        raise ValueError("Filesystem inventory cannot target hidden controls or partial downloads")
    if destination == root or (directory and root in destination.parents):
        raise ValueError("Inventory must be outside the input tree")
    excluded = {name.casefold() for name in exclude_stems}
    files = []
    errors = []
    excluded_directories = 0
    excluded_files = 0

    def candidates():
        nonlocal excluded_directories
        if not directory:
            yield root
            return
        for parent, dirs, names in os.walk(root, followlinks=False, onerror=_raise_walk_error):
            kept = [
                name
                for name in dirs
                if not name.startswith(".") and name.casefold() != "_partial" and not _linked(Path(parent) / name)
            ]
            excluded_directories += len(dirs) - len(kept)
            dirs[:] = kept
            for name in names:
                yield Path(parent) / name

    for path in candidates():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if path.name.startswith(".") or path.stem.casefold() in excluded:
            excluded_files += 1
            continue
        relative = path.relative_to(root) if directory else Path(path.name)
        gallery = root.name if single_gallery or len(relative.parts) == 1 else relative.parts[0]
        row = {
            "relative_path": str(relative),
            "gallery": gallery,
            "extension": path.suffix.lower(),
            "bytes": None,
            "format": None,
            "width": None,
            "height": None,
            "content_verified": False,
        }
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                excluded_files += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            row.update(bytes=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
        except OSError as exc:
            row["error"] = str(exc)
            errors.append({"relative_path": str(relative), "error": str(exc)})
        files.append(row)
    files.sort(key=lambda row: row["relative_path"].casefold())
    grouped = defaultdict(list)
    for row in files:
        grouped[row["gallery"]].append(row)
    known_total = sum(row["bytes"] for row in files if row["bytes"] is not None)
    galleries = {}
    for name, rows in sorted(grouped.items()):
        sizes = [row["bytes"] for row in rows if row["bytes"] is not None]
        extensions = {}
        for row in rows:
            bucket = extensions.setdefault(row["extension"], {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] = (
                bucket["bytes"] + row["bytes"] if bucket["bytes"] is not None and row["bytes"] is not None else None
            )
        galleries[name] = {
            "candidate_images": len(rows),
            "candidate_bytes": sum(sizes) if len(sizes) == len(rows) else None,
            "known_bytes": sum(sizes),
            "extension_types": len(extensions),
            "extensions": extensions,
            "formats": None,
            "content_verified": False,
            "stat_errors": len(rows) - len(sizes),
            "image_share_percent": 100 * len(rows) / max(1, len(files)),
            "byte_share_percent": 100 * sum(sizes) / max(1, known_total) if not errors else None,
            "size_distribution_bytes": {
                "min": min(sizes) if sizes else None,
                "median": median(sizes) if sizes else None,
                "max": max(sizes) if sizes else None,
            },
        }
    report = {
        "schema": 1,
        "root": str(root),
        "inventory_file": str(destination),
        "depth": "files",
        "status": "complete_enumeration",
        "completed": datetime.now(timezone.utc).isoformat(),
        "content_verified": False,
        "candidate_images": len(files),
        "known_bytes": known_total,
        "candidate_bytes": known_total if not errors else None,
        "totals_complete": not errors,
        "galleries": galleries,
        "files": files,
        "stat_errors": errors,
        "excluded_directories": excluded_directories,
        "excluded_candidate_files": excluded_files,
        "note": "Extension candidates only; formats/dimensions/content are unverified. "
        "File bytes are not filesystem allocated space. Not a trusted compression snapshot.",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    policy = json.dumps({"schema": 1, "exclude_stems": sorted(excluded), "single_gallery": single_gallery})
    with closing(sqlite3.connect(destination, timeout=5)) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS inventory_file_snapshots "
            "(root TEXT,policy TEXT,completed TEXT,report TEXT,PRIMARY KEY(root,policy))"
        )
        connection.execute(
            "INSERT OR REPLACE INTO inventory_file_snapshots VALUES(?,?,?,?)",
            (str(root), policy, report["completed"], json.dumps(report)),
        )
    return report
