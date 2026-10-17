#!/usr/bin/env python3
"""
Recursive directory scanner for manga/manhwa image collections.
"""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from .models import ImageMetadata, ScanSummary
from .cache import AnalysisCache
from .inventory import InventoryStore
from .perceptual import is_grayscale_image
from .timing import increment, phase, timed

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png", ".avif", ".bmp"}


def is_image_file(path: Path) -> bool:
    """Check if file has a recognized image extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


@timed("header_read")
def inspect_image_file(path: Path, *, check_grayscale: bool = False) -> ImageMetadata | None:
    """Extract metadata for a single image file without loading pixel buffer."""
    increment("headers_inspected")
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
    inventory: InventoryStore | None = None,
    progress: Any | None = None,
    gallery_key: Path | None = None,
) -> tuple[ScanSummary, list[ImageMetadata]]:
    """Refresh membership and reuse unchanged headers from a durable inventory."""
    if inventory is None:
        return _scan_directory(
            target_path,
            recursive=recursive,
            check_grayscale=check_grayscale,
            progress_callback=progress_callback,
            cache=cache,
            progress=progress,
            gallery_key=gallery_key,
        )
    with inventory.scan(target_path, recursive) as session:
        return _scan_directory(
            target_path,
            recursive=recursive,
            check_grayscale=check_grayscale,
            progress_callback=progress_callback,
            cache=session,
            progress=progress,
            gallery_key=gallery_key,
        )


def _scan_directory(
    target_path: Path,
    *,
    recursive: bool = True,
    check_grayscale: bool = False,
    progress_callback: Callable[[int, Path], None] | None = None,
    cache: AnalysisCache | None = None,
    progress: Any | None = None,
    gallery_key: Path | None = None,
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

    with phase("enumeration"):
        if target.is_file():
            file_candidates = [target] if is_image_file(target) else []
        elif recursive:
            file_candidates = []

            def walk_error(error):
                raise error

            for directory, dirs, names in os.walk(target, followlinks=False, onerror=walk_error):
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

        file_candidates.sort(key=lambda p: str(p).casefold())
    increment("scanned_candidates", len(file_candidates))
    group_keys = {}
    group_counts = defaultdict(int)
    group_done = defaultdict(int)
    target_is_directory = target.is_dir()
    for path in file_candidates:
        relative = path.relative_to(target) if target_is_directory else Path(path.name)
        key = gallery_key or (
            target / relative.parts[0]
            if len(relative.parts) > 1
            else (target if target_is_directory else target.parent)
        )
        group_keys[path] = key
        group_counts[key] += 1
    if progress is not None:
        if gallery_key is None:
            progress.set_folder_total(len(group_counts))
        elif progress.total_folders is None:
            progress.set_folder_total(1)
        if gallery_key is not None and not file_candidates:
            progress.start_gallery(gallery_key, total_files=0)
            progress.finish_gallery(gallery_key)
    if progress is not None and file_candidates:
        progress.add_total_files(len(file_candidates))

    for idx, path in enumerate(file_candidates, 1):
        key = group_keys[path]
        if progress is not None and group_done[key] == 0:
            progress.start_gallery(key, total_files=group_counts[key])
        meta = cache.get_metadata(path, check_grayscale) if cache else None
        reused = meta is not None
        if reused:
            increment("headers_reused")
        inspected = False
        if meta is None:
            inspected = True
            meta = inspect_image_file(path, check_grayscale=check_grayscale)
            if meta and cache:
                cache.set_metadata(meta, check_grayscale)
        if meta is None:
            increment("unreadable_images")
            if progress is not None:
                try:
                    raw_size = path.stat().st_size
                except OSError:
                    raw_size = 0
                progress.advance_file(
                    path,
                    size_bytes=raw_size,
                    reused=False,
                    inspected=inspected,
                    unreadable=True,
                    gallery_key=key,
                )
            group_done[key] += 1
            if progress is not None and group_done[key] == group_counts[key]:
                progress.finish_gallery(key)
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

        if progress is not None:
            progress.advance_file(
                path,
                size_bytes=meta.size_bytes,
                reused=reused,
                inspected=inspected,
                unreadable=False,
                gallery_key=key,
            )
        group_done[key] += 1
        if progress is not None and group_done[key] == group_counts[key]:
            progress.finish_gallery(key)
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
