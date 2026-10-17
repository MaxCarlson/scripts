"""External, full-resolution compression previews. Never publishes to sources."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence
from uuid import uuid4

from .models import ImageMetadata


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
    formats = getattr(args, "preview_formats", ()) or (args.format,)
    if any(image_format not in ("auto", "webp", "jpeg", "avif", "png") for image_format in formats):
        raise ValueError("Preview formats must be auto, webp, jpeg, avif or png")
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
    formats = tuple(dict.fromkeys(getattr(args, "preview_formats", ()) or (args.format,)))
    base.mkdir(parents=True, exist_ok=True)
    run = base / (datetime.now(timezone.utc).strftime("preview-%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    run.mkdir()
    variants = []
    for image_format in formats:
        prefix = f"{image_format}-" if len(formats) > 1 else ""
        variants.append(
            {"name": f"{prefix}lossless", "format": image_format, "mode": "lossless", "quality": None, "status": "pending"}
        )
        if image_format != "png":
            variants.extend(
                {
                    "name": f"{prefix}lossy-q{quality}",
                    "format": image_format,
                    "mode": "lossy",
                    "quality": quality,
                    "status": "pending",
                }
                for quality in qualities
            )
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
    from .report_session import current_session
    from .reporting import build_preview_report

    session = current_session()
    if session:
        report["report_artifacts"] = session.save(build_preview_report(report, context=session.context))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Preview {report['status']}: {run / 'manifest.json'}")
        if session:
            session.print_artifacts()
    return status
