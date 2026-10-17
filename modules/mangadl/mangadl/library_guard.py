"""Cross-process ownership and read/write lock inspection for coordinated library work."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from compresser.transactions import library_write_guard as _shared_guard, managed_library_root
from cross_platform.locks import (
    FolderLockReport,
    folder_read_lock,
    inspect_folder_locks,
    unlock_folder_locks,
)


def library_root(destination: Path) -> Path:
    return managed_library_root(destination) or destination.expanduser().resolve()


@contextmanager
def library_write_guard(destination: Path, *, operation: str = "") -> Iterator[None]:
    """Hold OS ownership for the whole operation, reentrant only on this thread.

    Repair invokes the normal manager on the owning thread. Other threads and
    processes must still acquire the persistent inode and cannot bypass it.
    """
    root = library_root(destination)
    with _shared_guard(root, operation=operation):
        yield


@contextmanager
def library_read_guard(destination: Path, *, operation: str = "read") -> Iterator[Path]:
    """Hold a shared, OS-backed read lock in external state without modifying ``destination``."""
    target = destination.expanduser().resolve()
    with folder_read_lock(target, operation=operation) as slot:
        yield slot


def inspect_library_locks(
    destination: Path,
    *,
    auto_clean: bool = True,
    discover_processes: bool = True,
) -> FolderLockReport:
    """Inspect write, read, repair, state-run, and live process locks for ``destination``."""
    target = destination.expanduser().resolve()
    root = library_root(target)
    return inspect_folder_locks(
        target,
        library_root=root,
        auto_clean=auto_clean,
        discover_processes=discover_processes,
    )


def unlock_library_locks(
    destination: Path,
    *,
    discover_processes: bool = True,
) -> dict[str, Any]:
    """Clear stale locks for ``destination`` only when no live process holds them."""
    target = destination.expanduser().resolve()
    root = library_root(target)
    return unlock_folder_locks(
        target,
        library_root=root,
        discover_processes=discover_processes,
    )
