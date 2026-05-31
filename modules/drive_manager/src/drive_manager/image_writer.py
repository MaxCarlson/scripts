from __future__ import annotations

from pathlib import Path

from .archive import extract_image_from_zip, is_zip
from .downloads import download_to_cache
from .hashing import verify_checksum
from .models import DiskInfo, OperationResult
from .platform_base import PlatformBackend
from .raw_io import RawDevice, close_volume_handles, lock_and_dismount_volumes, sector_pad


def resolve_image_path(image_path: Path | None, image_url: str | None, checksum: str | None = None) -> Path:
    if image_path is None and image_url is None:
        raise ValueError("Either image_path or image_url is required.")
    if image_url is not None:
        # URL always triggers a download; image_path (if given) is the target save location.
        path = download_to_cache(str(image_url), target_path=image_path)
    else:
        path = image_path
    assert path is not None
    path = path.expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    # Transparently extract a single image file from ZIP archives.
    if is_zip(path):
        path = extract_image_from_zip(path)
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

    # Lock and dismount volumes FIRST (while drive letters still exist), then
    # remove access paths.  Keeping the lock handles open prevents Windows from
    # re-mounting the volumes and blocking the raw write with ERROR_ACCESS_DENIED.
    vol_handles = lock_and_dismount_volumes(list(disk.drive_letters or []))
    backend.unmount_disk(disk)

    written = 0
    try:
        with RawDevice(raw_path, write=True) as dst:
            with image_path.open("rb") as src:
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(sector_pad(chunk))
                    written += len(chunk)
            dst.flush()
    finally:
        close_volume_handles(vol_handles)

    written = total  # report actual image bytes, not padded size

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
    with RawDevice(raw_path, write=False) as src_dev:
        with image_path.open("rb") as src:
            while True:
                src_chunk = src.read(chunk_size)
                if not src_chunk:
                    break
                dev_chunk = src_dev.read(len(src_chunk))
                if src_chunk != dev_chunk:
                    raise IOError("Image verification failed: read-back bytes differ from image.")

