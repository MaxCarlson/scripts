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

from .models import ImageMetadata


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
        nargs="?",
        const=Path("__workspace_preview__"),
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
        import time

        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 3:
                    raise
                time.sleep(0.05)
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
    """Generate independent source-owned previews with one manifest coordinator."""
    from .preview_pipeline import run_preview_pipeline

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
    variants = [{"name": "lossless", "mode": "lossless", "quality": None, "status": "pending"}] + [
        {"name": f"lossy-q{q}", "mode": "lossy", "quality": q, "status": "pending"} for q in qualities
    ]
    report = {
        "schema": 1,
        "status": "running",
        "source_root": str(root),
        "output_directory": str(run),
        "created": datetime.now(timezone.utc).isoformat(),
        "seed": getattr(args, "sample_seed", 0),
        "selection": "seeded preview subset, not a representative savings estimate",
        "execution": "bounded source workers; variants serial per source; coordinator-owned manifest",
        "note": "Full-resolution copies, including larger candidates. Quality is not a fidelity percentage. Size-only analysis cache cannot supply preview bytes.",
        "images": [
            {"source": str(meta.path), "status": "pending", "variants": [dict(item) for item in variants]}
            for meta in selected
        ],
    }
    if not args.json:
        print(f"Preview output: {run}\n{report['execution']}")
    status = run_preview_pipeline(args, selected, run, report, _save_manifest)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Preview {report['status']}: {run / 'manifest.json'}")
    return status
