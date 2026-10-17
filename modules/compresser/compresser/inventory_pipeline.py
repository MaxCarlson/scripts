"""Short-lived no-follow observations and bounded, SQL-free header workers."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Callable, Iterable, Iterator

from .models import ImageMetadata
from .timing import current_pipeline, execution_role


def identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True, slots=True)
class FileObservation:
    path: Path
    gallery: Path
    info: os.stat_result

    def validate(self) -> None:
        current = self.path.lstat()
        if linked(current) or not stat.S_ISREG(current.st_mode) or identity(current) != identity(self.info):
            raise RuntimeError(f"Source changed during inventory: {self.path}")


def linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _observation(path: Path, gallery: Path, info: os.stat_result) -> FileObservation:
    # Windows DirEntry.stat has zero device/inode IDs; retain a real identity
    # lookup only for selected candidates rather than weaken replacement checks.
    if not info.st_ino:
        current = path.lstat()
        if linked(current) or identity(current)[2:] != identity(info)[2:]:
            raise RuntimeError(f"Source changed during inventory: {path}")
        info = current
    return FileObservation(path, gallery, info)


def observe_files(
    root: Path, *, recursive: bool, extensions: set[str], gallery: Path | None = None, visited: set[Path] | None = None
) -> list[FileObservation]:
    """Classify each scandir entry once; never follow directory links/junctions."""
    root_info = root.lstat()
    if linked(root_info):
        raise ValueError(f"Linked inventory source is not allowed: {root}")
    if stat.S_ISREG(root_info.st_mode):
        return [FileObservation(root, gallery or root.parent, root_info)] if root.suffix.lower() in extensions else []
    observations = []
    pending = [(root, root_info.st_ino)]
    while pending:
        directory, expected = pending.pop()
        current = directory.lstat()
        if linked(current) or not stat.S_ISDIR(current.st_mode) or current.st_ino != expected:
            raise RuntimeError(f"Directory changed during inventory: {directory}")
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                info = entry.stat(follow_symlinks=False)
                if linked(info):
                    continue
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    if recursive and entry.name.casefold() != "_partial":
                        pending.append((path, entry.inode()))
                elif stat.S_ISREG(info.st_mode) and path.suffix.lower() in extensions:
                    relative = path.relative_to(root)
                    key = gallery or (root / relative.parts[0] if len(relative.parts) > 1 else root)
                    observations.append(_observation(path, key, info))
        if visited is not None:
            visited.add(directory)
    return sorted(observations, key=lambda item: str(item.path).casefold())


class HeaderPipeline:
    """One pool per selection, with at most twice its workers awaiting collection."""

    def __init__(self, workers: int):
        if workers < 1:
            raise ValueError("Inventory threads must be positive")
        self.workers = workers
        self.pool: ThreadPoolExecutor | None = None

    def __enter__(self) -> "HeaderPipeline":
        return self

    def __exit__(self, *_exc) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def inspect(
        self, observations: Iterable[FileObservation], reader: Callable, *, on_submit: Callable | None = None
    ) -> Iterator[tuple[FileObservation, ImageMetadata | None]]:
        def read(item):
            item.validate()
            result = reader(item)
            item.validate()
            return result

        if self.workers == 1:
            for item in observations:
                if on_submit is not None:
                    on_submit(item)
                yield item, read(item)
            return
        if self.pool is None:
            self.pool = ThreadPoolExecutor(self.workers, thread_name_prefix="inventory-header")
        metrics = current_pipeline()

        def worker(item):
            with execution_role("worker"):
                return read(item)

        source = iter(observations)
        pending = {}
        try:
            while True:
                while len(pending) < 2 * self.workers:
                    item = next(source, None)
                    if item is None:
                        break
                    if on_submit is not None:
                        on_submit(item)
                    pending[self.pool.submit(copy_context().run, worker, item)] = item
                    if metrics is not None:
                        metrics.observe_max("inventory_pending_peak", len(pending))
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    item = pending.pop(future)
                    yield item, future.result()
        finally:
            for future in pending:
                future.cancel()
            # Do not release the run's source ownership while readers still run.
            if pending:
                wait(pending)
