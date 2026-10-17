#!/usr/bin/env python3
"""
Recursive directory scanner for manga/manhwa image collections.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from .models import ImageMetadata, ScanSummary
from .cache import AnalysisCache
from .inventory import InventoryStore
from .perceptual import is_grayscale_image
from .timing import configure_pipeline, increment, phase, timed
from .inventory_pipeline import FileObservation, HeaderPipeline, linked, observe_files

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png", ".avif", ".bmp"}


def is_image_file(path: Path) -> bool:
    """Check if file has a recognized image extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


@timed("header_read")
def inspect_image_file(
    path: Path, *, check_grayscale: bool = False, observation: FileObservation | None = None
) -> ImageMetadata | None:
    """Extract metadata for a single image file without loading pixel buffer."""
    increment("headers_inspected")
    try:
        stat = observation.info if observation is not None else path.stat()
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
    threads: int = 4,
    _root_entries=None,
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
            threads=threads,
            _root_entries=_root_entries,
        )
    with inventory.scan(target_path, recursive) as session, inventory.header_pipeline(threads) as pipeline:
        return _scan_directory(
            target_path,
            recursive=recursive,
            check_grayscale=check_grayscale,
            progress_callback=progress_callback,
            cache=session,
            progress=progress,
            gallery_key=gallery_key,
            threads=threads,
            pipeline=pipeline,
            _root_entries=_root_entries,
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
    threads: int = 4,
    pipeline: HeaderPipeline | None = None,
    _root_entries=None,
) -> tuple[ScanSummary, list[ImageMetadata]]:
    """
    Recursively scan target_path for all image files and compile aggregate statistics.
    """
    original = target_path.expanduser().absolute()
    if original.exists() and linked(original.lstat()):
        raise ValueError(f"Linked inventory source is not allowed: {original}")
    target = original.resolve()
    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target}")

    if threads < 1:
        raise ValueError("Inventory threads must be positive")
    with phase("enumeration"):
        observations = observe_files(
            target,
            recursive=recursive,
            extensions=IMAGE_EXTENSIONS,
            gallery=gallery_key,
            visited=getattr(cache, "visited", None),
            root_entries=_root_entries,
        )
    increment("scanned_candidates", len(observations))
    # P0/P2 generated64-file scans are faster serial than with pool overhead.
    # Larger scopes may benefit from I/O overlap; requested threads remain a cap.
    effective = 1 if len(observations) <= 64 else min(threads, len(observations))
    configure_pipeline(
        inventory_effective_workers=effective,
        inventory_worker_policy=(
            "small scope (<=64 candidates): avoid measured pool overhead"
            if len(observations) <= 64
            else "requested upper bound; changed headers only"
        ),
    )
    group_counts = defaultdict(int)
    group_done = defaultdict(int)
    for item in observations:
        group_counts[item.gallery] += 1
    if progress is not None:
        if gallery_key is None:
            progress.set_folder_total(len(group_counts))
        elif progress.total_folders is None:
            progress.set_folder_total(1)
        if gallery_key is not None and not observations:
            progress.start_gallery(gallery_key, total_files=0)
            progress.finish_gallery(gallery_key)
        progress.add_total_files(len(observations))

    images = []
    completed = 0
    started = set()

    def start_gallery(item):
        if progress is not None and item.gallery not in started:
            progress.start_gallery(item.gallery, total_files=group_counts[item.gallery])
            started.add(item.gallery)

    def accept(item, meta, reused):
        nonlocal completed
        start_gallery(item)
        path, key = item.path, item.gallery
        if reused:
            increment("headers_reused")
        elif meta is not None and cache:
            cache.set_metadata(meta, check_grayscale)
        if meta is None:
            increment("unreadable_images")
        else:
            images.append(meta)
        if progress is not None:
            progress.advance_file(
                path,
                size_bytes=item.info.st_size,
                reused=reused,
                inspected=not reused,
                unreadable=meta is None,
                gallery_key=key,
            )
        group_done[key] += 1
        if progress is not None and group_done[key] == group_counts[key]:
            progress.finish_gallery(key)
        completed += 1
        if progress_callback and meta is not None:
            progress_callback(completed, path)

    def read(item):
        return inspect_image_file(item.path, check_grayscale=check_grayscale, observation=item)

    # One serial fast path for a single candidate; reuse one selection pool otherwise.
    context = nullcontext(pipeline) if pipeline is not None and effective > 1 else HeaderPipeline(effective)
    with context as headers:
        for start in range(0, len(observations), 256):
            batch = observations[start : start + 256]
            if cache and hasattr(cache, "get_many"):
                cached = cache.get_many(batch, check_grayscale)
            else:
                cached = {item.path: cache.get_metadata(item.path, check_grayscale) for item in batch} if cache else {}
            changed = []
            for item in batch:
                meta = cached.get(item.path)
                if meta is not None:
                    item.validate()
                    accept(item, meta, True)
                else:
                    changed.append(item)
            for item, meta in headers.inspect(changed, read, on_submit=start_gallery):
                accept(item, meta, False)

    images.sort(key=lambda item: str(item.path).casefold())
    format_counts: dict[str, int] = defaultdict(int)
    format_bytes: dict[str, int] = defaultdict(int)
    for image in images:
        format_counts[image.format.upper()] += 1
        format_bytes[image.format.upper()] += image.size_bytes

    summary = ScanSummary(
        target_path=target,
        total_images=len(images),
        total_bytes=sum(image.size_bytes for image in images),
        format_counts=dict(format_counts),
        format_bytes=dict(format_bytes),
        tall_images_count=sum(image.is_tall_for_webp for image in images),
        grayscale_count=sum(image.is_grayscale for image in images),
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
