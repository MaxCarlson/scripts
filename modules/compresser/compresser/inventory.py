"""Durable, non-evicting header inventory; successful scans publish atomically."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from statistics import median
from typing import Iterator

from .models import ImageMetadata


def inventory_path(args, root: Path) -> Path:
    """Resolve an external inventory, independently of trial-cache retention."""
    explicit = getattr(args, "inventory_file", None)
    cache = getattr(args, "cache_file", None)
    if explicit:
        path = Path(explicit).expanduser().resolve()
    elif cache:
        path = Path(cache).expanduser().resolve().with_suffix(".inventory.sqlite3")
    else:
        base = Path(os.environ.get("COMPRESSER_STATE_DIR") or os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
        identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
        path = base / "compresser" / "inventories" / f"{identity}.sqlite3"
    target = root.resolve()
    if path == target or (target.is_dir() and target in path.parents):
        raise ValueError("Inventory must be outside the input tree")
    if cache and path == Path(cache).expanduser().resolve():
        raise ValueError("Inventory and trial cache must use different files")
    return path


class InventoryStore:
    """Separate SQLite storage, not subject to compression-trial eviction."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.reports: list[dict] = []

    @contextmanager
    def scan(self, root: Path, recursive: bool) -> Iterator["InventorySession"]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS inventory_headers "
                "(path TEXT, grayscale INTEGER, fingerprint TEXT, metadata TEXT, "
                "PRIMARY KEY(path,grayscale))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS inventory_scans "
                "(root TEXT, recursive INTEGER, completed TEXT, report TEXT, "
                "PRIMARY KEY(root,recursive))"
            )
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            session = InventorySession(connection, root.resolve(), recursive)
            yield session
            # Only a successfully completed enumeration may remove missing records.
            prefix = session.root if session.root.is_dir() else session.root.parent
            start = str(prefix) + os.sep
            rows = connection.execute(
                "SELECT DISTINCT path FROM inventory_headers WHERE path=? OR (path>=? AND path<?)",
                (str(session.root), start, start + "\uffff"),
            ).fetchall()
            for (value,) in rows:
                candidate = Path(value)
                belongs = candidate == session.root or (
                    session.root.is_dir() and prefix in candidate.parents and (recursive or candidate.parent == prefix)
                )
                if belongs and value not in session.seen:
                    connection.execute("DELETE FROM inventory_headers WHERE path=?", (value,))
            report = session.report()
            connection.execute(
                "INSERT OR REPLACE INTO inventory_scans VALUES(?,?,?,?)",
                (str(session.root), int(recursive), report["completed"], json.dumps(report)),
            )
            connection.commit()
            self.reports.append(report)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def diagnostics(self) -> dict:
        """Expose scan failures and actual header operations, not integrity claims."""
        records = {row["path"]: row for report in self.reports for row in report["files"]}
        return {
            "inventory_file": str(self.path),
            "scanned_candidates": len(records),
            "unreadable_images": sum(row["status"] == "unreadable" for row in records.values()),
            "headers_reused": sum(r["headers_reused"] for r in self.reports),
            "headers_inspected": sum(r["headers_inspected"] for r in self.reports),
            "scan_scopes": [{key: value for key, value in report.items() if key != "files"} for report in self.reports],
        }


class InventorySession:
    def __init__(self, connection: sqlite3.Connection, root: Path, recursive: bool):
        self.connection = connection
        self.root = root
        self.recursive = recursive
        self.seen: dict[str, dict] = {}
        self.reused = 0
        self.inspected = 0

    def get_metadata(self, path: Path, check_grayscale: bool = False) -> ImageMetadata | None:
        stat = path.stat()
        fingerprint = json.dumps([1, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
        self.seen[str(path)] = {
            "path": str(path),
            "relative_path": str(path.relative_to(self.root)) if self.root.is_dir() else path.name,
            "extension": path.suffix.lower(),
            "bytes": stat.st_size,
            "fingerprint": fingerprint,
            "status": "unreadable",
        }
        row = self.connection.execute(
            "SELECT fingerprint,metadata FROM inventory_headers WHERE path=? AND grayscale=?",
            (str(path), int(check_grayscale)),
        ).fetchone()
        if row and row[0] == fingerprint:
            data = json.loads(row[1])
            data["path"] = Path(data["path"])
            meta = ImageMetadata(**data)
            self.reused += 1
            self.seen[str(path)].update(
                status="header_verified", format=meta.format, width=meta.width, height=meta.height
            )
            return meta
        self.inspected += 1
        return None

    def set_metadata(self, meta: ImageMetadata, check_grayscale: bool = False) -> None:
        stat = meta.path.stat()
        entry = self.seen[str(meta.path)]
        fingerprint = json.dumps([1, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
        if fingerprint != entry["fingerprint"] or stat.st_size != meta.size_bytes or stat.st_mtime_ns != meta.mtime_ns:
            raise RuntimeError(f"Source changed during inventory: {meta.path}")
        self.connection.execute(
            "INSERT OR REPLACE INTO inventory_headers VALUES(?,?,?,?)",
            (str(meta.path), int(check_grayscale), fingerprint, json.dumps(asdict(meta), default=str)),
        )
        entry.update(status="header_verified", format=meta.format, width=meta.width, height=meta.height)

    def report(self) -> dict:
        extensions = {}
        for entry in self.seen.values():
            row = extensions.setdefault(entry["extension"], {"files": 0, "bytes": 0})
            row["files"] += 1
            row["bytes"] += entry["bytes"]
        return {
            "schema": 1,
            "root": str(self.root),
            "recursive": self.recursive,
            "completed": datetime.now(timezone.utc).isoformat(),
            "status": "complete",
            "headers_reused": self.reused,
            "headers_inspected": self.inspected,
            "unreadable_images": sum(row["status"] == "unreadable" for row in self.seen.values()),
            "files": list(self.seen.values()),
            "candidate_extensions": extensions,
        }


def inventory_report(images, root: Path, *, gallery_keys=None) -> dict:
    """Summarize eligible images, keeping extensions separate from actual formats."""
    galleries = {}
    for image in images:
        relative = image.path.relative_to(root) if root.is_dir() else Path(image.path.name)
        key = (
            str(gallery_keys[image.path])
            if gallery_keys is not None
            else (relative.parts[0] if len(relative.parts) > 1 else root.name)
        )
        row = galleries.setdefault(key, {"images": 0, "bytes": 0, "extensions": {}, "formats": {}, "_sizes": []})
        row["images"] += 1
        row["bytes"] += image.size_bytes
        row["_sizes"].append(image.size_bytes)
        for field, value in (("extensions", image.path.suffix.lower()), ("formats", image.format.upper())):
            bucket = row[field].setdefault(value, {"images": 0, "bytes": 0})
            bucket["images"] += 1
            bucket["bytes"] += image.size_bytes
        row["extension_types"] = len(row["extensions"])
    total_bytes = sum(i.size_bytes for i in images)
    for row in galleries.values():
        sizes = row.pop("_sizes")
        row["size_distribution_bytes"] = {"min": min(sizes), "median": median(sizes), "max": max(sizes)}
        row["image_share_percent"] = 100 * row["images"] / max(1, len(images))
        row["byte_share_percent"] = 100 * row["bytes"] / max(1, total_bytes)
    return {
        "root": str(root),
        "images": len(images),
        "bytes": sum(i.size_bytes for i in images),
        "galleries": galleries,
        "note": "File bytes, not filesystem allocated size; headers are not a full decode audit.",
    }
