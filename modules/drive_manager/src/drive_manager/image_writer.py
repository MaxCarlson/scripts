from __future__ import annotations

import os
from pathlib import Path

from .downloads import download_to_cache
from .hashing import verify_checksum
from .models import DiskInfo, OperationResult
from .platform_base import PlatformBackend


def resolve_image_path(image_path: Path | None, image_url: str | None, checksum: str | None = None) -> Path:
    if image_path is None and image_url is None:
        raise ValueError("Either image_path or image_url is required.")
    path = image_path if image_path is not None else download_to_cache(str(image_url))
    assert path is not None
    path = path.expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    if checksum and not verify_checksum(path, checksum):
        raise ValueError(f"Checksum verification failed for {path}")
    return path


def write_image_to_disk(
    backend: PlatformBackend,
    disk: DiskInfo,
    image_path: Path,
    *,
    verify: bool = False,
    chunk_size: int = 4 * 1024 * 1024,
) -> OperationResult:
    raw_path = backend.raw_device_path(disk)
    total = image_path.stat().st_size
    steps = [
        f"Unmount target disk volumes on {disk.disk_id}",
        f"Open image {image_path}",
        f"Open raw target {raw_path}",
        f"Write {total:,} bytes in {chunk_size:,}-byte chunks",
        "Flush buffers",
    ]
    if verify:
        steps.append("Verify written image prefix against source image")

    backend.unmount_disk(disk)

    written = 0
    with image_path.open("rb") as src, open(str(raw_path), "r+b", buffering=0) as dst:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            dst.write(chunk)
            written += len(chunk)
        try:
            dst.flush()
        except Exception:
            pass
        try:
            os.fsync(dst.fileno())
        except Exception:
            pass

    if verify:
        _verify_written_prefix(raw_path, image_path, chunk_size=chunk_size)

    return OperationResult(
        ok=True,
        dry_run=False,
        message=f"Wrote image to disk {disk.disk_id}: {written:,} bytes.",
        steps=steps,
        details={"bytes_written": written, "image_path": str(image_path), "raw_device": str(raw_path)},
    )


def _verify_written_prefix(raw_path: Path, image_path: Path, *, chunk_size: int) -> None:
    with image_path.open("rb") as src, open(str(raw_path), "rb", buffering=0) as dst:
        while True:
            src_chunk = src.read(chunk_size)
            if not src_chunk:
                break
            dst_chunk = dst.read(len(src_chunk))
            if src_chunk != dst_chunk:
                raise IOError("Image verification failed: read-back bytes differ from image.")
