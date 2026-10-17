"""Explicit, analysis-only reuse of completed header populations."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import stat

from PIL import __version__ as pillow_version

from .inventory import InventoryStore, header_fingerprint
from .models import ImageMetadata, ScanSummary
from .timing import timed

STALE_WARNING = (
    "Totals and projections describe the saved snapshot, not verified current library membership. "
    "New, removed or changed unselected files are not discovered. Use -U refresh to update."
)


def summarize_images(root: Path, images: list[ImageMetadata]) -> ScanSummary:
    """Build counts from eligible metadata, without touching source files."""
    counts = Counter(i.format.upper() for i in images)
    sizes = defaultdict(int)
    for image in images:
        sizes[image.format.upper()] += image.size_bytes
    return ScanSummary(
        root,
        len(images),
        sum(i.size_bytes for i in images),
        dict(counts),
        dict(sizes),
        sum(i.is_tall_for_webp for i in images),
        sum(i.is_grayscale for i in images),
    )


def _unlinked(path: Path) -> None:
    # lstat detects links/junctions before resolution could conceal the redirect.
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError(f"Linked snapshot source is not allowed: {candidate}; use -U refresh")


class SelectionSnapshot:
    """A whole CLI selection, distinct from per-directory or file-only inventories."""

    def __init__(self, store: InventoryStore, root: Path, *, owner: str, filters=()):
        self.store = store
        self.original_root = root.expanduser().absolute()
        self.root = self.original_root.resolve()
        # Increment the policy revision when scanner/exclusion/ownership rules change.
        self.policy = json.dumps([2, owner, sorted(set(filters)), pillow_version])
        self.report: dict = {}
        self.fingerprints: dict[Path, list[int]] = {}

    @timed("publication")
    def publish(self, images: list[ImageMetadata], gallery_keys: dict | None = None) -> None:
        """Publish only after every scope in this selection finished successfully."""
        records = {Path(row["path"]): row for scope in self.store.reports for row in scope["files"]}
        entries = []
        for image in images:
            row = records[image.path]
            fingerprint = json.loads(row["fingerprint"])
            if row["status"] != "header_verified" or fingerprint[1:3] != [image.size_bytes, image.mtime_ns]:
                raise ValueError(f"Inconsistent header snapshot: {image.path}; use -U refresh")
            entries.append(
                {
                    "metadata": asdict(image),
                    "fingerprint": fingerprint,
                    "gallery": str(gallery_keys[image.path]) if gallery_keys is not None else None,
                }
            )
        report = {
            "schema": 1,
            "status": "complete",
            "root": str(self.root),
            "policy": self.policy,
            "completed": datetime.now(timezone.utc).isoformat(),
            "images": entries,
        }
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        with self.store.connection() as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS inventory_selections "
                "(root TEXT, policy TEXT, report TEXT, PRIMARY KEY(root,policy))"
            )
            db.execute(
                "INSERT OR REPLACE INTO inventory_selections VALUES(?,?,?)",
                (str(self.root), self.policy, json.dumps(report, default=str)),
            )
        self.report = {"policy": "refresh", "completed": report["completed"], "membership_verified": True}

    @timed("snapshot_load")
    def load(self) -> tuple[list[ImageMetadata], dict | None]:
        """Load a compatible completed population; never enumerate the library."""
        try:
            _unlinked(self.original_root)
            with self.store.connection(readonly=True) as db:
                row = db.execute(
                    "SELECT report FROM inventory_selections WHERE root=? AND policy=?",
                    (str(self.root), self.policy),
                ).fetchone()
            if row is None:
                raise ValueError("No completed snapshot matches this root/selection/policy")
            data = json.loads(row[0])
            if (data["schema"], data["status"], data["root"], data["policy"]) != (
                1,
                "complete",
                str(self.root),
                self.policy,
            ):
                raise ValueError("Incompatible snapshot")
            completed = datetime.fromisoformat(data["completed"])
            if completed.tzinfo is None:
                raise ValueError("Snapshot timestamp has no timezone")
            images, keys = [], {}
            for entry in data["images"]:
                meta = dict(entry["metadata"])
                path = Path(meta["path"])
                if not path.is_absolute() or ".." in path.parts or not (path == self.root or self.root in path.parents):
                    raise ValueError("Snapshot source escapes input root")
                meta["path"] = path
                image = ImageMetadata(**meta)
                fingerprint = entry["fingerprint"]
                if (
                    len(fingerprint) != 6
                    or fingerprint[0] != 2
                    or fingerprint[1:3] != [image.size_bytes, image.mtime_ns]
                    or image.width < 1
                    or image.height < 1
                    or image.size_bytes < 1
                    or path in self.fingerprints
                ):
                    raise ValueError("Invalid snapshot metadata")
                self.fingerprints[path] = fingerprint
                images.append(image)
                if entry["gallery"] is not None:
                    gallery = Path(entry["gallery"])
                    if not (gallery == self.root or self.root in gallery.parents) or gallery not in path.parents:
                        raise ValueError("Invalid snapshot gallery ownership")
                    keys[path] = str(gallery)
            if keys and len(keys) != len(images):
                raise ValueError("Incomplete snapshot gallery ownership")
            self.report = {
                "policy": "trust",
                "completed": data["completed"],
                "age_seconds": max(0, (datetime.now(timezone.utc) - completed).total_seconds()),
                "membership_verified": False,
                "selected_files_validated": 0,
                "warning": STALE_WARNING,
            }
            return images, keys or None
        except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Cannot trust inventory snapshot: {exc}. Run with -U refresh first.") from exc

    @timed("validation")
    def validate_selected(self, images: list[ImageMetadata]) -> None:
        """Validate before any engine/cache fast path. No unselected-file probing."""
        if self.report.get("policy") != "trust":
            return
        for image in images:
            try:
                _unlinked(image.path)
                info = image.path.stat()
                fingerprint = header_fingerprint(info)
                if not stat.S_ISREG(info.st_mode) or fingerprint != self.fingerprints[image.path]:
                    raise ValueError("source changed")
            except (OSError, ValueError, KeyError) as exc:
                raise ValueError(f"Snapshot source no longer matches: {image.path} ({exc}); use -U refresh") from exc
        self.report["selected_files_validated"] = len(images)

    def print_warning(self) -> None:
        """Keep old-population caveats visible in human-readable reports."""
        if self.report.get("policy") == "trust":
            print(f"Trusted snapshot: {self.report['completed']} | age: {self.report['age_seconds']:.0f}s")
            print(f"WARNING: {STALE_WARNING}")
