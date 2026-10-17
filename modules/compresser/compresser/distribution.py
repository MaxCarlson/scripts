"""Versioned descriptive inventory profiles, separate from estimation designs."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean, variance


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SamplingProfile:
    data: dict

    @property
    def identity(self) -> str:
        return _digest({key: value for key, value in self.data.items() if key != "completed"})

    @classmethod
    def from_images(cls, images, root: Path, *, gallery_keys=None, policy="") -> "SamplingProfile":
        root = root.absolute()
        grouped = defaultdict(list)
        population = []
        directory = root.is_dir()
        for image in sorted(images, key=lambda image: str(image.path).casefold()):
            relative = image.path.relative_to(root) if directory else Path(image.path.name)
            key = (
                str(gallery_keys[image.path])
                if gallery_keys is not None
                else str(root / relative.parts[0] if len(relative.parts) > 1 else root)
            )
            grouped[key].append(image)
            population.append(
                [str(relative), key, image.size_bytes, image.mtime_ns, image.format, image.width, image.height]
            )
        galleries = {}
        for key, members in sorted(grouped.items()):
            sizes = [image.size_bytes for image in members]
            average = mean(sizes)
            spread = variance(sizes) if len(sizes) > 1 else 0
            galleries[key] = {
                "count": len(members),
                "bytes": sum(sizes),
                "mean_bytes": average,
                "size_variance": spread,
                "formats": dict(sorted(Counter(image.format for image in members).items())),
                "tall_webp_images": sum(image.is_tall_for_webp for image in members),
                "dimensions": {
                    "min_width": min(image.width for image in members),
                    "max_width": max(image.width for image in members),
                    "min_height": min(image.height for image in members),
                    "max_height": max(image.height for image in members),
                },
            }
        return cls(
            {
                "schema": 1,
                "profile_revision": 2,
                "root": str(root),
                "policy": policy,
                "depth": "headers",
                "completed": datetime.now(timezone.utc).isoformat(),
                "population_identity": _digest(population),
                "galleries": galleries,
                "method": "descriptive_metadata",
                "limitations": "File metadata summarizes the inventory; it does not predict compression outcomes, estimate savings, or recommend sample sizes.",
            }
        )

    def validate(self, images, root: Path, gallery_keys=None) -> None:
        expected = self.from_images(images, root, gallery_keys=gallery_keys, policy=self.data.get("policy", ""))
        if self.identity != expected.identity:
            raise ValueError("Sampling profile is stale or incompatible; use -U refresh")

    def save(self, db) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS inventory_sampling_profiles (root TEXT,policy TEXT,identity TEXT,report TEXT,PRIMARY KEY(root,policy))"
        )
        db.execute(
            "INSERT OR REPLACE INTO inventory_sampling_profiles VALUES(?,?,?,?)",
            (self.data["root"], self.data["policy"], self.identity, json.dumps(self.data, allow_nan=False)),
        )

    @classmethod
    def from_file_report(cls, report, policy) -> "SamplingProfile":
        groups = defaultdict(list)
        for row in report["files"]:
            groups[row["gallery"]].append(row)
        galleries = {}
        for name, members in sorted(groups.items()):
            sizes = [row["bytes"] for row in members if row["bytes"] is not None]
            known = len(sizes) == len(members)
            spread = variance(sizes) if len(sizes) > 1 else 0
            galleries[name] = {
                "count": len(members),
                "bytes": sum(sizes) if known else None,
                "size_variance": spread if known else None,
                "formats": None,
                "tall_webp_images": None,
                "dimensions": None,
                "extensions": dict(Counter(row["extension"] for row in members)),
            }
        return cls(
            {
                "schema": 1,
                "profile_revision": 2,
                "root": report["root"],
                "policy": "files:" + policy,
                "depth": "files",
                "completed": report["completed"],
                "population_identity": _digest(report["files"]),
                "galleries": galleries,
                "method": "descriptive_metadata_unverified",
                "limitations": "Extension and size candidates only; formats and dimensions are unknown. This profile does not predict compression outcomes, estimate savings, or recommend sample sizes.",
            }
        )
