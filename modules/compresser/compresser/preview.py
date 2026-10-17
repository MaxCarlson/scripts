"""External, full-resolution compression previews. Never publishes to sources."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence
from uuid import uuid4

from PIL import Image

from .engine import CompressionEngine, ESTIMATED_BYTES_PER_PIXEL, MEMORY_BUDGET_BYTES
from .models import CompressionStrategy, ImageMetadata
from .transactions import digest as file_digest


def parse_preview_quality(value: str) -> int:
    """Accept integer quality 1..100 or exact decimal fractions, e.g.0.9 ->90."""
    try:
        number = Decimal(value)
        if "." in value and 0 < number <= 1:
            number *= 100
        if not number.is_finite() or number != number.to_integral_value() or not 1 <= number <= 100:
            raise ValueError
        return int(number)
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError("Use quality 1..100 or a fraction such as 0.9 (90)") from None


def add_preview_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-O",
        "--preview-dir",
        type=Path,
        help="Generate lossless/lossy preview copies in a new run folder outside the source tree.",
    )
    parser.add_argument(
        "-n",
        "--preview-count",
        type=int,
        help="Number of preview source images (default: 3); not a whole-library estimate.",
    )
    parser.add_argument(
        "-Q",
        "--qualities",
        "--preview-qualities",
        dest="preview_qualities",
        type=parse_preview_quality,
        nargs="+",
        help="Preview/comparison lossy qualities, e.g.90 80 or0.9 0.8. Preview default:90 80; comparison default:-q.",
    )


def validate_preview_arguments(args: argparse.Namespace) -> None:
    output = getattr(args, "preview_dir", None)
    count = getattr(args, "preview_count", None)
    qualities = getattr(args, "preview_qualities", None)
    if not output:
        if count is not None:
            raise ValueError("--preview-count requires --preview-dir")
        if qualities is not None and not (
            getattr(args, "compare_both", False) or (args.compare and args.mode == "lossy")
        ):
            raise ValueError("--qualities requires preview, --compare-both, or --compare -m lossy")
        return
    if count is not None and count < 1:
        raise ValueError("Preview count must be positive")
    if (
        args.write
        or args.compare
        or getattr(args, "compare_both", False)
        or getattr(args, "inventory_only", False)
        or getattr(args, "recover", False)
        or args.sample is not None
        or getattr(args, "sample_percent", None) is not None
    ):
        raise ValueError(
            "Preview cannot be combined with write, comparison, recovery, inventory-only or sampling; use -n"
        )
    if args.mode != "lossless":
        raise ValueError("Preview includes lossless and fixed lossy qualities; omit -m and use -Q")
    if args.format not in ("auto", "webp", "jpeg", "avif"):
        raise ValueError("Preview target must be auto, webp, jpeg or avif; PNG has no lossy-quality setting")
    source = getattr(args, "input", None) or getattr(args, "destination", None)
    if source is not None:
        root = source.expanduser().resolve()
        destination = output.expanduser().resolve()
        if destination == root or (root.is_dir() and root in destination.parents):
            raise ValueError("Preview output must be outside the source tree")


def _fingerprint(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _save_manifest(path: Path, report: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _select_sources(images: Sequence[ImageMetadata], root: Path, count: int, seed: int) -> list[ImageMetadata]:
    directory = root.is_dir()
    return sorted(
        images,
        key=lambda image: hashlib.sha256(
            f"{seed}\0{image.path.relative_to(root) if directory else image.path.name}".encode()
        ).digest(),
    )[:count]


def run_preview_cli(args: argparse.Namespace, images: Sequence[ImageMetadata], root: Path) -> int:
    """Generate independently verified candidates, originals and a durable manifest."""
    root = root.expanduser().resolve()
    base = args.preview_dir.expanduser().resolve()
    if base == root or (root.is_dir() and root in base.parents):
        raise ValueError("Preview output must be outside the source tree")
    selected = _select_sources(images, root, args.preview_count or 3, getattr(args, "sample_seed", 0))
    if not selected:
        raise ValueError("No eligible images available for preview")
    qualities = list(dict.fromkeys(args.preview_qualities or [90, 80]))
    base.mkdir(parents=True, exist_ok=True)
    run = base / (datetime.now(timezone.utc).strftime("preview-%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    run.mkdir()
    manifest = run / "manifest.json"
    report = {
        "schema": 1,
        "status": "running",
        "source_root": str(root),
        "output_directory": str(run),
        "created": datetime.now(timezone.utc).isoformat(),
        "seed": getattr(args, "sample_seed", 0),
        "selection": "seeded preview subset, not a representative savings estimate",
        "execution": "serial, one source and candidate at a time; -t does not affect previews",
        "note": "Full-resolution candidates, including larger outputs. Quality is not a fidelity percentage. "
        "Cached analysis sizes cannot supply preview image bytes.",
        "images": [],
    }
    _save_manifest(manifest, report)
    if not args.json:
        print(f"Preview output: {run}\n{report['execution']}")
    engine = CompressionEngine(memory_budget_bytes=args.memory_budget_mib * 1024**2)
    failed = False
    try:
        for index, meta in enumerate(selected, 1):
            folder = run / f"{index:04d}"
            folder.mkdir()
            row = {"source": str(meta.path), "status": "running", "variants": []}
            report["images"].append(row)
            _save_manifest(manifest, report)
            try:
                if meta.path.is_symlink():
                    raise ValueError("Linked preview sources are not supported")
                before = _fingerprint(meta.path)
                if before[0] != meta.size_bytes or (meta.mtime_ns and before[1] != meta.mtime_ns):
                    raise ValueError("Source changed since inventory; rescan before preview")
                cost = meta.width * meta.height * ESTIMATED_BYTES_PER_PIXEL
                if (
                    meta.width <= 0
                    or meta.height <= 0
                    or meta.width * meta.height > 40_000_000
                    or cost > min(MEMORY_BUDGET_BYTES, engine.memory_budget_bytes)
                ):
                    raise ValueError("Preview source exceeds configured image/memory safety limits")
                original = folder / ("original" + meta.path.suffix.lower())
                digest = hashlib.sha256()
                with meta.path.open("rb") as source, original.open("xb") as target:
                    remaining = before[0]
                    while remaining:
                        chunk = source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError("Source shrank while copying preview original")
                        digest.update(chunk)
                        target.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ValueError("Source grew while copying preview original")
                if _fingerprint(meta.path) != before:
                    raise ValueError("Source changed while copying preview original")
                if file_digest(original) != digest.hexdigest():
                    raise ValueError("Preview original copy failed checksum verification")
                row.update(
                    original=str(original.relative_to(run)),
                    original_bytes=before[0],
                    original_sha256=digest.hexdigest(),
                )
                with Image.open(original) as image:
                    if image.size != (meta.width, meta.height) or getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Changed dimensions or unsupported animation")
                    if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
                        raise ValueError("Unsupported pixel/color mode")
                    image.load()
                    variants = [("lossless", "lossless", 100)] + [(f"lossy-q{q}", "lossy", q) for q in qualities]
                    for label, mode, quality in variants:
                        variant = {
                            "name": label,
                            "mode": mode,
                            "quality": quality if mode == "lossy" else None,
                            "status": "running",
                        }
                        row["variants"].append(variant)
                        try:
                            strategy = CompressionStrategy(
                                label,
                                format=args.format,
                                mode=mode,
                                quality=quality,
                                method=args.effort,
                                encoder=args.algorithm,
                            )
                            if args.format == "auto":
                                fmt, encoded, score, encoder = engine._encode_auto(image, meta, strategy)
                            else:
                                fmt = args.format
                                encoded, score, encoder = engine._encode_verified(image, fmt, strategy)
                            destination = folder / f"{label}.{'jpg' if fmt == 'jpeg' else fmt}"
                            with destination.open("xb") as stream:
                                stream.write(encoded)
                            variant.update(
                                status="complete",
                                file=str(destination.relative_to(run)),
                                bytes=len(encoded),
                                format=fmt,
                                encoder=encoder,
                                ssim=score,
                                savings_percent=100 * (before[0] - len(encoded)) / max(1, before[0]),
                            )
                        except (ValueError, RuntimeError, OSError) as exc:
                            failed = True
                            variant.update(status="failed", error=str(exc))
                        _save_manifest(manifest, report)
                        if not args.json:
                            print(f"Preview [{index}/{len(selected)}] {meta.path.name}: {label} {variant['status']}")
                if _fingerprint(meta.path) != before:
                    raise ValueError(
                        "Source changed after preview snapshot; output represents the copied original only"
                    )
                row["status"] = "complete" if all(v["status"] == "complete" for v in row["variants"]) else "failed"
            except (ValueError, RuntimeError, OSError) as exc:
                failed = True
                row.update(status="failed", error=str(exc))
            _save_manifest(manifest, report)
        report["status"] = "completed_with_errors" if failed else "complete"
    except KeyboardInterrupt:
        report["status"] = "cancelled"
        for item in report["images"]:
            if item["status"] == "running":
                item["status"] = "cancelled"
            for variant in item["variants"]:
                if variant["status"] == "running":
                    variant["status"] = "cancelled"
        raise
    except BaseException:
        report["status"] = "failed"
        raise
    finally:
        _save_manifest(manifest, report)
        engine.cache.close()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Preview {report['status']}: {manifest}")
    return 1 if failed else 0
