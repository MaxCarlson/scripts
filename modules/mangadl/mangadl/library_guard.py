"""Cross-process ownership for coordinated library writes."""

from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Iterator

from compresser.transactions import directory_lock

_owners = threading.local()


def library_root(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    for root in (destination, *destination.parents):
        if (root / ".mangadl").is_dir():
            return root
    return destination


@contextmanager
def library_write_guard(destination: Path) -> Iterator[None]:
    """Hold OS ownership for the whole operation, reentrant only on this thread.

    Repair invokes the normal manager on the owning thread. Other threads and
    processes must still acquire the persistent inode and cannot bypass it.
    """
    root = library_root(destination)
    held = getattr(_owners, "roots", None)
    if held is None:
        held = _owners.roots = set()
    if root in held:
        yield
        return
    controls = root / ".mangadl"
    if controls.is_symlink():
        raise ValueError(f"Refusing linked library controls: {controls}")
    controls.mkdir(parents=True, exist_ok=True)
    with directory_lock(controls, filename="operation.lock"):
        held.add(root)
        try:
            yield
        finally:
            held.remove(root)
