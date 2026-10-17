#!/usr/bin/env python3
"""
Recursive directory scanner for manga/manhwa image collections.
"""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from .models import ImageMetadata, ScanSummary
from .cache import AnalysisCache
from .perceptual import is_grayscale_image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png", ".avif", ".bmp"}


def is_image_file(path: Path) -> bool:
    """Check if file has a recognized image extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


def inspect_image_file(path: Path, *, check_grayscale: bool = False) -> ImageMetadata | None:
    """Extract metadata for a single image file without loading pixel buffer."""
    try:
        stat = path.stat()
        size = stat.st_size
        if size <= 0:
            return None
        with Image.open(path) as im:
            fmt = str(im.format or path.suffix.lstrip(".").upper())
            w, h = im.size
            is_gray = is_grayscale_image(im) if check_grayscale else (im.mode in ("1", "L", "LA"))
            return ImageMetadata(
                path=path,
                format=fmt,
                width=w,
                height=h,
                size_bytes=size,
                is_grayscale=is_gray,
                mtime_ns=stat.st_mtime_ns,
            )
    except Exception:
        return None


def scan_directory(
    target_path: Path,
    *,
    recursive: bool = True,
    check_grayscale: bool = False,
    progress_callback: Callable[[int, Path], None] | None = None,
    cache: AnalysisCache | None = None,
) -> tuple[ScanSummary, list[ImageMetadata]]:
    """
    Recursively scan target_path for all image files and compile aggregate statistics.
    """
    target = target_path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target}")

    images: list[ImageMetadata] = []
    format_counts: dict[str, int] = defaultdict(int)
    format_bytes: dict[str, int] = defaultdict(int)
    total_bytes = 0
    tall_count = 0
    gray_count = 0

    if target.is_file():
        file_candidates = [target] if is_image_file(target) else []
    elif recursive:
        file_candidates = []
        for directory, dirs, names in os.walk(target, followlinks=False):
            dirs[:] = [
                name
                for name in dirs
                if not name.startswith(".") and name != "_partial" and not (Path(directory) / name).is_symlink()
            ]
            file_candidates.extend(
                Path(directory) / name
                for name in names
                if not name.startswith(".")
                and is_image_file(Path(directory) / name)
                and not (Path(directory) / name).is_symlink()
            )
    else:
        file_candidates = [p for p in target.glob("*") if is_image_file(p)]

    # Sort files naturally for consistent batch ordering
    file_candidates.sort(key=lambda p: str(p).casefold())

    for idx, path in enumerate(file_candidates, 1):
        meta = cache.get_metadata(path, check_grayscale) if cache else None
        if meta is None:
            meta = inspect_image_file(path, check_grayscale=check_grayscale)
            if meta and cache:
                cache.set_metadata(meta, check_grayscale)
        if meta is None:
            continue
        images.append(meta)
        fmt = meta.format.upper()
        format_counts[fmt] += 1
        format_bytes[fmt] += meta.size_bytes
        total_bytes += meta.size_bytes
        if meta.is_tall_for_webp:
            tall_count += 1
        if meta.is_grayscale:
            gray_count += 1

        if progress_callback:
            progress_callback(idx, path)

    summary = ScanSummary(
        target_path=target,
        total_images=len(images),
        total_bytes=total_bytes,
        format_counts=dict(format_counts),
        format_bytes=dict(format_bytes),
        tall_images_count=tall_count,
        grayscale_count=gray_count,
    )

    return summary, images


def select_sample(images: Sequence[ImageMetadata], sample_size: int) -> list[ImageMetadata]:
    """Balance a deterministic sample across format, size and WebP-limit strata."""
    if sample_size <= 0:
        raise ValueError("Sample size must be positive")
    if not images or len(images) <= sample_size:
        return list(images)

    groups: dict[tuple, list[ImageMetadata]] = defaultdict(list)
    for image in images:
        groups[sample_stratum(image)].append(image)
    groups = dict(sorted(groups.items()))
    quotas = {key: 0 for key in groups}
    allocated = 0
    while allocated < sample_size:
        for key, members in groups.items():
            if quotas[key] < len(members):
                quotas[key] += 1
                allocated += 1
                if allocated == sample_size:
                    break
    sampled = []
    for key, members in groups.items():
        count = quotas[key]
        if count:
            sampled.extend(
                members[min(len(members) - 1, int((index + 0.5) * len(members) / count))] for index in range(count)
            )
    return sorted(sampled, key=lambda image: str(image.path).casefold())


def sample_stratum(image: ImageMetadata) -> tuple[str, int, bool]:
    return image.format.upper(), max(1, image.size_bytes).bit_length(), image.is_tall_for_webp
