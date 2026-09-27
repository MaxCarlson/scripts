"""Optional SSD staging and guarded promotion into a slower library volume."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .partial_safety import PARTIAL_CONTROL_NAMES


def partial_root_for(destination: Path, scratch_dir: Path | None) -> Path:
    """Keep partials for separate libraries isolated under a shared scratch drive."""
    if scratch_dir is None:
        return destination / "_partial"
    library = str(destination.expanduser().resolve()).casefold()
    library_key = hashlib.sha256(library.encode("utf-8")).hexdigest()[:16]
    return scratch_dir.expanduser().resolve() / library_key / "_partial"


@contextmanager
def _promotion_lock(partial_root: Path) -> Iterator[None]:
    """Serialize promotions from one scratch root so HDD writes stay sequential."""
    lock_path = partial_root.parent / ".promotion.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            # LK_LOCK only retries for roughly ten seconds; a large HDD
            # promotion can take much longer than that.
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if (
                        exc.errno not in {errno.EACCES, errno.EAGAIN}
                        and getattr(exc, "winerror", None) != 33
                    ):
                        raise
                    time.sleep(0.25)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _same_contents(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as source, right.open("rb") as target:
        while True:
            source_block = source.read(1024 * 1024)
            target_block = target.read(1024 * 1024)
            if source_block != target_block:
                return False
            if not source_block:
                return True


def _promote_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or destination.is_symlink():
        raise ValueError(
            f"refusing to promote through a symbolic link: {source} -> {destination}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    for entry in list(source.iterdir()):
        if entry.name in PARTIAL_CONTROL_NAMES:
            continue
        target = destination / entry.name
        if entry.is_symlink() or target.is_symlink():
            raise ValueError(
                f"refusing to promote through a symbolic link: {entry} -> {target}"
            )
        if entry.is_dir():
            if target.exists() and not target.is_dir():
                raise FileExistsError(f"destination is not a directory: {target}")
            _promote_tree(entry, target)
            continue
        if not entry.is_file():
            raise ValueError(f"unsupported scratch entry: {entry}")
        if target.exists():
            if not target.is_file() or not _same_contents(entry, target):
                raise FileExistsError(
                    f"destination conflict; scratch copy retained: {target}"
                )
            entry.unlink()
            continue
        temporary = target.with_name(f".{target.name}.mangadl-{uuid.uuid4().hex}.tmp")
        try:
            with (
                entry.open("rb") as input_stream,
                temporary.open("xb") as output_stream,
            ):
                shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            if temporary.stat().st_size != entry.stat().st_size:
                raise OSError(f"scratch copy size changed during promotion: {entry}")
            if target.exists():
                raise FileExistsError(
                    f"destination appeared during promotion: {target}"
                )
            temporary.replace(target)
            entry.unlink()
        finally:
            temporary.unlink(missing_ok=True)
    if source.exists() and not any(source.iterdir()):
        source.rmdir()


def promote_partial(source: Path, destination: Path, partial_root: Path) -> None:
    """Copy to the destination atomically, retaining scratch data on any failure."""
    with _promotion_lock(partial_root):
        _promote_tree(source, destination)


def promote_gallery_partial(
    partial: Path, destination: Path, partial_root: Path, category: str
) -> None:
    """Match the scratch gallery path rule used for pre-download existence checks."""
    with _promotion_lock(partial_root):
        category_root = partial / category if category else None
        if category_root is not None and category_root.is_dir():
            for child in list(category_root.iterdir()):
                if child.is_dir():
                    _promote_tree(child, destination / child.name)
            if category_root.exists() and any(category_root.iterdir()):
                _promote_tree(category_root, destination / category)
            elif category_root.exists():
                category_root.rmdir()
        _promote_tree(partial, destination)


def staged_library_folders(
    partial: Path, destination: Path, category: str = ""
) -> tuple[Path, ...]:
    """Identify only folders touched by this staged job, before promotion removes them."""
    folders: set[Path] = set()
    if not partial.is_dir():
        return ()
    for entry in partial.iterdir():
        if entry.name in PARTIAL_CONTROL_NAMES or not entry.is_dir():
            continue
        if category and entry.name == category:
            children = list(entry.iterdir())
            folders.update(
                destination / child.name for child in children if child.is_dir()
            )
            if any(child.is_file() for child in children):
                folders.add(destination / category)
        else:
            folders.add(destination / entry.name)
    return tuple(sorted(folders))
