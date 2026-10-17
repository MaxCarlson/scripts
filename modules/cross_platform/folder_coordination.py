"""User-scoped, cross-process reader/writer coordination for overlapping trees."""

from contextlib import contextmanager
from pathlib import Path
import os
import threading
import time

from .locks import _external_lock_root, _READ_SEQ, directory_lock, probe_byte_range_lock

_WRITE_OWNERS = threading.local()


def overlapping(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


@contextmanager
def _gate(registry: Path):
    # Retry only short acquisition-bookkeeping contention, not operation conflicts.
    deadline = time.monotonic() + 5
    while True:
        guard = directory_lock(registry, filename="gate.lock", operation="lock acquisition")
        try:
            guard.__enter__()
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


def registry_records(target: Path, state_root: Path | None = None):
    """Return active overlapping operation slots, ignoring released crash debris."""
    registry = _external_lock_root(state_root) / "operations"
    if not registry.is_dir():
        return
    for slot in sorted(registry.glob("*.lock")):
        if not slot.name.startswith(("read-", "write-")):
            continue
        kind = slot.name.split("-", 1)[0]
        record = probe_byte_range_lock(slot, kind=kind, mode=kind, auto_clean_stale_metadata=False)
        if not record.engaged:
            continue
        if not record.holder or not record.holder.get("target"):
            raise RuntimeError(f"Unverifiable active folder lock: {slot}. Not waiting.")
        if overlapping(target, Path(record.holder["target"])):
            yield record


def _check_legacy_writers(target: Path) -> None:
    # Existing operations keep their legacy inode locks. Stop old binaries before
    # upgrading: they cannot participate in the new acquisition protocol.
    for scope in (target, *target.parents):
        for lock in (scope / ".mangadl" / "operation.lock", scope / ".compress.lock"):
            if lock.exists() and probe_byte_range_lock(lock, auto_clean_stale_metadata=False).engaged:
                raise RuntimeError(f"Target is locked by an existing writer: {lock}. Not waiting.")


@contextmanager
def coordinated_folder_lock(target: Path, *, mode: str, operation: str, state_root: Path | None = None):
    """Atomically check conflicts and publish kernel-owned operation metadata."""
    target = target.expanduser().resolve()
    state = _external_lock_root(state_root)
    held = getattr(_WRITE_OWNERS, "scopes", {})
    if mode == "write":
        for (namespace, root), slot in held.items():
            if namespace == state and (root == target or root in target.parents):
                yield slot
                return
    registry = state / "operations"
    registry.mkdir(parents=True, exist_ok=True)
    slot = registry / f"{mode}-{os.getpid()}-{threading.get_ident()}-{next(_READ_SEQ)}.lock"
    owned = None
    try:
        with _gate(registry):
            for record in registry_records(target, state_root):
                if mode == "write" or record.mode == "write":
                    raise RuntimeError(
                        f"Target is {record.mode}-locked by PID {record.holder.get('pid')}: "
                        f"{record.target}. Not waiting; retry after it finishes."
                    )
            _check_legacy_writers(target)
            guard = directory_lock(registry, filename=slot.name, mode=mode, operation=operation, target=target)
            guard.__enter__()
            owned = guard
        if mode == "write":
            held[(state, target)] = slot
            _WRITE_OWNERS.scopes = held
        yield slot
    finally:
        if owned is not None:
            if mode == "write":
                held.pop((state, target), None)
            owned.__exit__(None, None, None)
            slot.unlink(missing_ok=True)
