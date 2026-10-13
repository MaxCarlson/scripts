"""Cross-process ownership for coordinated library writes."""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from compresser.transactions import library_write_guard as _shared_guard, managed_library_root


def library_root(destination: Path) -> Path:
    return managed_library_root(destination) or destination.expanduser().resolve()


@contextmanager
def library_write_guard(destination: Path) -> Iterator[None]:
    """Hold OS ownership for the whole operation, reentrant only on this thread.

    Repair invokes the normal manager on the owning thread. Other threads and
    processes must still acquire the persistent inode and cannot bypass it.
    """
    root = library_root(destination)
    with _shared_guard(root):
        yield
