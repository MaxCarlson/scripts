"""Durable, non-evicting header inventory; successful scans publish atomically."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
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
from .timing import increment, pipeline_report, timed


def header_fingerprint(info: os.stat_result) -> list[int]:
    """Versioned identity evidence; older cache rows require fresh observation."""
    return [2, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino]


def connect_inventory(*args, **kwargs) -> sqlite3.Connection:
    """Count actual SQL work without changing connection ownership/transactions."""
    connection = sqlite3.connect(*args, **kwargs)
    increment("inventory_connections")

    def trace(statement):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb == "COMMIT":
            increment("inventory_commits")
        elif verb == "ROLLBACK":
            increment("inventory_rollbacks")
        elif verb != "BEGIN":
            increment("inventory_queries")

    connection.set_trace_callback(trace)
    return connection


def inventory_path(args, root: Path) -> Path:
    """Resolve an external inventory, independently of trial-cache retention."""
    if getattr(args, "_workspace", None):
        return args._workspace.inventory_file
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
        self._connection: sqlite3.Connection | None = None
        self._connection_readonly = False
        self._running = False
        self._resources: ExitStack | None = None
        self._headers = None

    @contextmanager
    def run(self) -> Iterator["InventoryStore"]:
        """One coordinator-owned connection across the selection's scan scopes."""
        if self._running:
            yield self
            return
        self._running = True
        self.reports.clear()
        self._resources = ExitStack()
        try:
            yield self
        finally:
            try:
                self._resources.close()
            finally:
                self._resources = None
                self._headers = None
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
                self._running = False

    @contextmanager
    def header_pipeline(self, workers: int):
        from .inventory_pipeline import HeaderPipeline

        if self._resources is not None:
            if self._headers is None:
                self._headers = self._resources.enter_context(HeaderPipeline(workers))
            elif self._headers.workers != workers:
                raise ValueError("Use one header worker limit throughout an inventory run")
            yield self._headers
        else:
            with HeaderPipeline(workers) as pipeline:
                yield pipeline

    @contextmanager
    def connection(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """Borrow this run's connection; standalone callers retain scoped ownership."""
        if self._connection is not None and self._connection_readonly and not readonly:
            # Trust loads stay genuinely read-only; saving later sample provenance
            # explicitly upgrades after that read scope has ended.
            self._connection.close()
            self._connection = None
        if self._connection is not None:
            yield self._connection
            return
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.as_uri() + "?mode=ro" if readonly else self.path
        connection = connect_inventory(target, uri=readonly, timeout=5)
        if self._running:
            self._connection = connection
            self._connection_readonly = readonly
            yield connection
        else:
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def scan(self, root: Path, recursive: bool) -> Iterator["InventorySession"]:
        with self.connection() as connection:
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
            session = InventorySession(connection, root.resolve(), recursive)
            try:
                yield session
                session.flush()
                # Only a successfully completed enumeration may remove missing records.
                prefix = session.root if session.is_directory else session.root.parent
                start = str(prefix) + os.sep
                rows = connection.execute(
                    "SELECT DISTINCT path FROM inventory_headers WHERE path=? OR (path>=? AND path<?)",
                    (str(session.root), start, start + "\uffff"),
                )
                with connection:
                    for (value,) in rows:
                        candidate = Path(value)
                        belongs = candidate == session.root or candidate.parent in session.visited
                        if belongs and value not in session.seen:
                            connection.execute("DELETE FROM inventory_headers WHERE path=?", (value,))
                    report = session.report()
                    connection.execute(
                        "INSERT OR REPLACE INTO inventory_scans VALUES(?,?,?,?)",
                        (str(session.root), int(recursive), report["completed"], json.dumps(report)),
                    )
                self.reports.append(report)
            except BaseException:
                connection.rollback()
                raise

    def diagnostics(self) -> dict:
        """Expose scan failures and actual header operations, not integrity claims."""
        records = {row["path"]: row for report in self.reports for row in report["files"]}
        return {
            "inventory_file": str(self.path),
            "pipeline": pipeline_report(),
            "scanned_candidates": len(records),
            "unreadable_images": sum(row["status"] == "unreadable" for row in records.values()),
            "headers_reused": sum(r["headers_reused"] for r in self.reports),
            "headers_inspected": sum(r["headers_inspected"] for r in self.reports),
            "scan_scopes": [{key: value for key, value in report.items() if key != "files"} for report in self.reports],
        }

    @timed("publication")
    def save_sample(self, plan, root: Path) -> dict:
        """Persist selection provenance separately from completed compression trials."""
        root = root.resolve()
        is_directory = root.is_dir()
        population = [
            (
                str(i.path.relative_to(root)) if is_directory else i.path.name,
                i.size_bytes,
                i.mtime_ns,
                i.format,
                i.width,
                i.height,
                key,
            )
            for key, members in plan.groups.items()
            for i in members
        ]
        provenance = (
            [2, population]
            if plan.allocation_method == "balanced"
            else [3, population, plan.allocation_method, plan.profile_identity]
        )
        identity = hashlib.sha256(json.dumps(provenance).encode()).hexdigest()
        report = plan.summary()
        report.update(
            population_identity=identity,
            created=datetime.now(timezone.utc).isoformat(),
            selected_files=[str(i.path.relative_to(root)) if is_directory else i.path.name for i in plan.images],
        )
        with self.connection() as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS inventory_samples "
                "(root TEXT, seed TEXT, population TEXT, count INTEGER, report TEXT, "
                "PRIMARY KEY(root,seed,population,count))"
            )
            connection.execute(
                "INSERT OR REPLACE INTO inventory_samples VALUES(?,?,?,?,?)",
                (str(root), str(plan.seed), identity, len(plan.images), json.dumps(report)),
            )
        return {
            "population_identity": identity,
            "sampling_revision": report["sampling_revision"],
            "inventory_file": str(self.path),
        }


class InventorySession:
    def __init__(self, connection: sqlite3.Connection, root: Path, recursive: bool):
        self.connection = connection
        self.root = root
        self.recursive = recursive
        self.is_directory = root.is_dir()
        self.visited: set[Path] = set()
        self._pending: list[tuple] = []
        self.seen: dict[str, dict] = {}
        self.reused = 0
        self.inspected = 0

    @timed("metadata_lookup")
    def get_metadata(self, path: Path, check_grayscale: bool = False) -> ImageMetadata | None:
        stat = path.stat()
        fingerprint = json.dumps(header_fingerprint(stat))
        self.seen[str(path)] = {
            "path": str(path),
            "relative_path": str(path.relative_to(self.root)) if self.is_directory else path.name,
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

    @timed("metadata_lookup")
    def get_many(self, observations, check_grayscale: bool = False) -> dict[Path, ImageMetadata]:
        """Selection-scoped <=256-key queries; SQL always stays on the coordinator."""
        if len(observations) > 256:
            raise ValueError("Header lookup batch exceeds256 observations")
        if not observations:
            return {}
        marks = ",".join("?" for _ in observations)
        rows = {
            path: (fingerprint, metadata)
            for path, fingerprint, metadata in self.connection.execute(
                f"SELECT path,fingerprint,metadata FROM inventory_headers WHERE grayscale=? AND path IN ({marks})",
                (int(check_grayscale), *(str(item.path) for item in observations)),
            )
        }
        found = {}
        for item in observations:
            info = item.info
            fingerprint = json.dumps(header_fingerprint(info))
            self.seen[str(item.path)] = {
                "path": str(item.path),
                "relative_path": str(item.path.relative_to(self.root)) if self.is_directory else item.path.name,
                "extension": item.path.suffix.lower(),
                "bytes": info.st_size,
                "fingerprint": fingerprint,
                "status": "unreadable",
            }
            row = rows.get(str(item.path))
            if row and row[0] == fingerprint:
                # The scanner validates the observation immediately before
                # accepting this hint; do not repeat that filesystem lookup here.
                data = json.loads(row[1])
                data["path"] = Path(data["path"])
                meta = ImageMetadata(**data)
                found[item.path] = meta
                self.seen[str(item.path)].update(
                    status="header_verified", format=meta.format, width=meta.width, height=meta.height
                )
                self.reused += 1
            else:
                self.inspected += 1
        return found

    @timed("header_publication")
    def set_metadata(self, meta: ImageMetadata, check_grayscale: bool = False) -> None:
        stat = meta.path.stat()
        entry = self.seen[str(meta.path)]
        fingerprint = json.dumps(header_fingerprint(stat))
        if fingerprint != entry["fingerprint"] or stat.st_size != meta.size_bytes or stat.st_mtime_ns != meta.mtime_ns:
            raise RuntimeError(f"Source changed during inventory: {meta.path}")
        self._pending.append((str(meta.path), int(check_grayscale), fingerprint, json.dumps(asdict(meta), default=str)))
        if len(self._pending) >= 256:
            self.flush()
        entry.update(status="header_verified", format=meta.format, width=meta.width, height=meta.height)

    def flush(self) -> None:
        """Cache batches are reusable hints, never a completed-population marker."""
        if self._pending:
            with self.connection:
                self.connection.executemany("INSERT OR REPLACE INTO inventory_headers VALUES(?,?,?,?)", self._pending)
            self._pending.clear()

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
