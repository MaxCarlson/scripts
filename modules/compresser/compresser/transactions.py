"""Owned, fingerprinted image publication. Recovery is explicit, never analysis."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import sys
from contextlib import contextmanager, ExitStack
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image

try:
    from cross_platform.locks import directory_lock as _cross_platform_directory_lock
    from cross_platform.locks import folder_write_lock
except ModuleNotFoundError:  # pragma: no cover
    _modules_root = str(Path(__file__).resolve().parents[2])
    if _modules_root not in sys.path:
        sys.path.insert(0, _modules_root)
    from cross_platform.locks import directory_lock as _cross_platform_directory_lock
    from cross_platform.locks import folder_write_lock

JOURNAL_FILENAME = ".compress_journal.json"
LOCK_FILENAME = ".compress.lock"
_library_owners = threading.local()


def managed_library_root(directory: Path) -> Path | None:
    """Find an established MangaDL control root without creating anything."""
    directory = directory.expanduser().resolve()
    return next((root for root in (directory, *directory.parents) if (root / ".mangadl").is_dir()), None)


@contextmanager
def library_write_guard(root: Path, *, operation: str = "") -> Iterator[None]:
    """Shared operation ownership, reentrant only on the invoking thread."""
    root = root.expanduser().resolve()
    held = getattr(_library_owners, "roots", None)
    if held is None:
        held = _library_owners.roots = set()
    if root in held:
        yield
        return
    controls = root / ".mangadl"
    if controls.is_symlink():
        raise ValueError(f"Refusing linked library controls: {controls}")
    with folder_write_lock(root, operation=operation):
        controls.mkdir(parents=True, exist_ok=True)
        with directory_lock(controls, filename="operation.lock", operation=operation, target=root):
            held.add(root)
            try:
                yield
            finally:
                held.remove(root)


@contextmanager
def managed_write_guard(directories, *, operation: str = "") -> Iterator[None]:
    """Coordinate standalone writes with established MangaDL library owners."""
    roots = {managed_library_root(directory) or directory.expanduser().resolve() for directory in directories}
    with ExitStack() as owners:
        for root in sorted(roots):
            if (root / ".mangadl").is_dir():
                owners.enter_context(library_write_guard(root, operation=operation))
            else:
                owners.enter_context(folder_write_lock(root, operation=operation))
        yield


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        result = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
        return result.hexdigest()


@contextmanager
def directory_lock(
    directory: Path,
    *,
    create: bool = True,
    filename: str = LOCK_FILENAME,
    operation: str = "",
    target: Path | str | None = None,
) -> Iterator[None]:
    """Persistent lock inode with OS ownership, released even on process death.

    Never unlink a lock inode: another process may already have opened it.
    Read-only previews only open an existing lock and never create a control.
    """
    with _cross_platform_directory_lock(
        directory,
        create=create,
        filename=filename,
        mode="write",
        operation=operation,
        target=target if target is not None else directory,
    ):
        yield


def _save_record(journal: Path, record: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".compress-record-", suffix=".tmp", dir=journal.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, journal)
    finally:
        temp.unlink(missing_ok=True)


def publish(original: Path, output: Path, encoded: bytes, source_digest: str, validate: Callable[[Path], bool]) -> None:
    """Caller holds directory ownership; never clobber an unrelated target."""
    if original.parent.resolve() != output.parent.resolve() or original.stem != output.stem:
        raise RuntimeError("Publication must remain in the same image directory and preserve the page stem")
    journal = original.parent / JOURNAL_FILENAME
    if journal.exists():
        raise RuntimeError(f"Pending transaction requires explicit recovery: {journal}")
    if original.is_symlink() or output.is_symlink():
        raise RuntimeError("Refusing linked compression paths")
    if output != original and output.exists():
        raise FileExistsError(f"Compression target already exists: {output}")
    fd, name = tempfile.mkstemp(prefix=".compress-image-", suffix=".tmp", dir=original.parent)
    temp = Path(name)
    recorded = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if not validate(temp):
            raise RuntimeError("Compression output failed full decode/fidelity verification")
        if digest(original) != source_digest:
            raise RuntimeError(f"Source changed while encoding: {original}")
        record = {
            "version": 2,
            "original": original.name,
            "output": output.name,
            "temp": temp.name,
            "source_sha256": source_digest,
            "output_sha256": digest(temp),
        }
        _save_record(journal, record)
        recorded = True
        if output == original:
            os.replace(temp, output)
        else:
            # Hard-link publication is no-clobber on both Windows and POSIX.
            # The durable record covers the interval with both page extensions.
            os.link(temp, output)
            if digest(original) != source_digest:
                raise RuntimeError(f"Source changed during publication: {original}")
            original.unlink()
            temp.unlink()
        journal.unlink()
    finally:
        # After record publication keep all evidence on errors for recovery.
        if not recorded:
            temp.unlink(missing_ok=True)


def inspect_recovery(directory: Path) -> dict[str, Any] | None:
    """Validate a recovery candidate without creating controls or changing files."""
    directory = directory.resolve()
    journal = directory / JOURNAL_FILENAME
    if not journal.exists():
        return None
    if journal.is_symlink() or journal.stat().st_size > 64_000:
        raise RuntimeError("Linked or oversized compression journal refused")
    with directory_lock(directory, create=False):
        try:
            record = json.loads(journal.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"Cannot read compression journal: {journal}") from exc
        if not isinstance(record, dict):
            raise RuntimeError("Malformed compression journal")
        if record.get("version") != 2:
            raise RuntimeError("Legacy compression journal lacks ownership fingerprints; manual review required")
        paths = []
        for key in ("original", "output", "temp"):
            name = record.get(key)
            if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
                raise RuntimeError("Compression journal path escapes its directory")
            path = directory / name
            if path.is_symlink() or path.resolve().parent != directory:
                raise RuntimeError("Compression journal contains a linked/outside path")
            paths.append(path)
        original, output, temp = paths
        if original.stem != output.stem or original.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".webp",
            ".png",
            ".avif",
            ".bmp",
        }:
            raise RuntimeError("Journal does not describe a same-page image conversion")
        if output.suffix.lower() not in {".jpg", ".jpeg", ".webp", ".png", ".avif"}:
            raise RuntimeError("Journal target is not a supported image")
        if not temp.name.startswith(".compress-image-") or not temp.name.endswith(".tmp"):
            raise RuntimeError("Compression journal contains an unowned temp path")
        source_hash, output_hash = record.get("source_sha256"), record.get("output_sha256")
        for value in (source_hash, output_hash):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise RuntimeError("Invalid compression fingerprint")
        published = output.exists() and digest(output) == output_hash
        if original.exists() and not (original == output and published) and digest(original) != source_hash:
            raise RuntimeError("Original changed since transaction; recovery refused")
        if output != original and output.exists() and not published:
            raise RuntimeError("Output changed since transaction; recovery refused")
        if temp.exists() and digest(temp) != output_hash:
            raise RuntimeError("Temporary output changed; recovery refused")
        if not original.exists() and not published:
            raise RuntimeError("Neither verified original nor published output exists")
        if published:
            try:
                with Image.open(output) as image:
                    image.load()
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Unexpected multi-frame output")
                    if original.exists() and original != output:
                        with Image.open(original) as source:
                            if source.size != image.size:
                                raise ValueError("Replacement dimensions differ from original")
            except (OSError, ValueError) as exc:
                raise RuntimeError("Published recovery image fails decode/geometry validation") from exc
        journal_hash = digest(journal)
        return {
            "directory": str(directory),
            "journal": str(journal),
            "journal_sha256": journal_hash,
            "original": str(original),
            "output": str(output),
            "temp": str(temp),
            "source_sha256": source_hash,
            "output_sha256": output_hash,
            "published": published,
            "action": (
                "finish_conversion"
                if published and original != output and original.exists()
                else "clear_completed_record" if published else "discard_unpublished_temp"
            ),
        }


def recover(directory: Path, *, apply: bool = False, expected_journal_hash: str | None = None) -> int:
    """Validate v2 record and preview by default. Apply revalidates under ownership."""
    candidate = inspect_recovery(directory)
    if candidate is None:
        if expected_journal_hash:
            raise RuntimeError("Reviewed recovery journal disappeared")
        return 0
    if expected_journal_hash and candidate["journal_sha256"] != expected_journal_hash:
        raise RuntimeError("Journal changed since confirmed recovery preview")
    if not apply:
        return 1
    with managed_write_guard([directory]), directory_lock(directory):
        # Inspect without reacquiring our own OS lock; ownership must stay held.
        # The preview's hashes are rechecked individually before mutation.
        journal = Path(candidate["journal"])
        original, output, temp = (Path(candidate[key]) for key in ("original", "output", "temp"))
        if digest(journal) != candidate["journal_sha256"]:
            raise RuntimeError("Journal changed since recovery preview")
        published = candidate["published"]
        if published and digest(output) != candidate["output_sha256"]:
            raise RuntimeError("Output changed since recovery preview")
        if original.exists() and not (published and original == output):
            if digest(original) != candidate["source_sha256"]:
                raise RuntimeError("Original changed since recovery preview")
        elif not published:
            raise RuntimeError("Original disappeared since recovery preview")
        if temp.exists() and digest(temp) != candidate["output_sha256"]:
            raise RuntimeError("Temporary output changed since recovery preview")
        if not published and output != original and output.exists():
            raise RuntimeError("Unreviewed output appeared since recovery preview")
        for path in (original, output, temp, journal):
            if path.is_symlink() or path.resolve().parent != Path(candidate["directory"]):
                raise RuntimeError("Recovery path changed to a link or escaped its directory")
        if candidate["action"] == "finish_conversion":
            original.unlink()
        temp.unlink(missing_ok=True)
        journal.unlink()
    return 1
