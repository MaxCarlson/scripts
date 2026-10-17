"""Analysis-only external SSD scratch workspace with ownership manifest and verified staging."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import uuid

from .cancellation import check_cancelled
from .models import ImageMetadata
from .timing import phase

SCRATCH_MANIFEST = ".compresser_scratch_manifest.json"
DEFAULT_MAX_STAGED_BYTES = 512 * 1024 * 1024
COPY_CHUNK_BYTES = 64 * 1024


def _unlinked_ancestors(path: Path) -> None:
    for candidate in (path.expanduser().absolute(), *path.expanduser().absolute().parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError(f"Scratch cannot use linked source/directory: {candidate}")


def validate_scratch_dir(scratch_dir: Path, target_root: Path) -> Path:
    expanded = scratch_dir.expanduser()
    _unlinked_ancestors(expanded)
    _unlinked_ancestors(target_root)
    resolved_scratch = expanded.resolve()
    resolved_target = target_root.expanduser().resolve()
    target_tree = resolved_target if resolved_target.is_dir() else resolved_target.parent
    if (
        resolved_scratch == resolved_target
        or resolved_scratch == target_tree
        or target_tree in resolved_scratch.parents
        or resolved_scratch in target_tree.parents
    ):
        raise ValueError("Scratch directory must be outside the input/destination tree")
    return resolved_scratch


class ScratchWorkspace:
    """Owned per-run scratch staging directory for read-only analysis."""

    def __init__(
        self,
        scratch_dir: Path,
        target_root: Path,
        *,
        max_staged_bytes: int = DEFAULT_MAX_STAGED_BYTES,
    ) -> None:
        self.scratch_root = validate_scratch_dir(scratch_dir, target_root)
        self.target_root = target_root.expanduser().resolve()
        if isinstance(max_staged_bytes, bool) or not isinstance(max_staged_bytes, int) or max_staged_bytes < 1:
            raise ValueError("Scratch byte budget must be positive")
        self.max_staged_bytes = max_staged_bytes
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.scratch_root / f"compresser-scratch-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self.run_dir.mkdir(parents=False, exist_ok=False)
        info = self.run_dir.stat()
        self._run_identity = (info.st_dev, info.st_ino)
        self.manifest_path = self.run_dir / SCRATCH_MANIFEST
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._counter = 0
        self._owned_files: dict[Path, int] = {}
        self._manifest_temps: set[Path] = set()
        self._current_bytes = 0
        self.peak_staged_bytes = 0
        self.staged_images = 0
        self.staged_bytes = 0
        self.copy_seconds = 0.0
        self.wait_seconds = 0.0
        self.cleanup_errors: list[str] = []
        self._failed: str | None = None
        self.cleaned_up = False
        try:
            self._write_manifest()
        except BaseException:
            self.close()
            raise

    def _assert_run_identity(self) -> None:
        _unlinked_ancestors(self.run_dir)
        info = self.run_dir.stat()
        if (info.st_dev, info.st_ino) != self._run_identity:
            raise RuntimeError("Scratch run directory identity changed; refusing cleanup")

    def _cleanup_error(self, error: Exception) -> None:
        message = str(error)
        if message not in self.cleanup_errors and len(self.cleanup_errors) < 20:
            self.cleanup_errors.append(message)

    def _write_manifest(self) -> None:
        self._assert_run_identity()
        payload = {
            "schema": 2,
            "owner": "compresser-scratch",
            "pid": os.getpid(),
            "target_root": str(self.target_root),
            "created_at": self.created_at,
            "staged_files": [{"name": path.name, "reserved_bytes": size} for path, size in self._owned_files.items()],
        }
        fd, name = tempfile.mkstemp(prefix="manifest-", suffix=".tmp", dir=self.run_dir)
        temporary = Path(name)
        self._manifest_temps.add(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.manifest_path)
        finally:
            if temporary.exists():
                temporary.unlink()
            self._manifest_temps.discard(temporary)

    def stage_image(self, meta: ImageMetadata) -> Path:
        check_cancelled()
        path = meta.path
        _unlinked_ancestors(path)
        before = path.stat()
        stamp = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        if before.st_size != meta.size_bytes or (meta.mtime_ns and before.st_mtime_ns != meta.mtime_ns):
            raise RuntimeError("Source changed since scan; rescan before compression")
        if before.st_size > self.max_staged_bytes:
            raise OSError("Input exceeds scratch staging byte budget")
        waiting = time.monotonic()
        with self._condition, phase("scratch_wait"):
            while self._current_bytes + before.st_size > self.max_staged_bytes:
                if self._failed:
                    raise OSError(f"Scratch cleanup failed; staging aborted: {self._failed}")
                check_cancelled()
                self._condition.wait(timeout=0.1)
            check_cancelled()
            if self._failed:
                raise OSError(f"Scratch cleanup failed; staging aborted: {self._failed}")
            if self.cleaned_up:
                raise RuntimeError("Scratch workspace is closed")
            self.wait_seconds += time.monotonic() - waiting
            self._counter += 1
            staged_path = self.run_dir / f"{self._counter:06d}-{uuid.uuid4().hex[:12]}{path.suffix.lower() or '.img'}"
            self._owned_files[staged_path] = before.st_size
            self._current_bytes += before.st_size
            self.peak_staged_bytes = max(self.peak_staged_bytes, self._current_bytes)
        started = time.monotonic()
        try:
            with self._lock:
                self._write_manifest()  # Ownership is durable before any source bytes are written.
            digest = hashlib.sha256()
            with phase("scratch_copy"), path.open("rb") as source, staged_path.open("xb") as destination:
                remaining = before.st_size
                while remaining:
                    check_cancelled()
                    chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise RuntimeError("Source shrank while staging to scratch")
                    if destination.write(chunk) != len(chunk):
                        raise OSError("Short write while staging to scratch")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise RuntimeError("Source grew while staging to scratch")
            after = path.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != stamp:
                raise RuntimeError("Source changed while staging to scratch; result discarded")
            verified = hashlib.sha256()
            with phase("scratch_copy"), staged_path.open("rb") as staged:
                remaining = before.st_size
                while remaining:
                    check_cancelled()
                    chunk = staged.read(min(COPY_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise OSError("Scratch copy verification failed")
                    verified.update(chunk)
                    remaining -= len(chunk)
                if staged.read(1) or verified.digest() != digest.digest():
                    raise OSError("Scratch copy verification failed")
            with self._lock:
                self.staged_images += 1
                self.staged_bytes += before.st_size
            return staged_path
        except BaseException:
            self.release_image(staged_path)
            raise
        finally:
            with self._lock:
                self.copy_seconds += time.monotonic() - started

    def release_image(self, staged_path: Path | None) -> None:
        if staged_path is None:
            return
        with self._condition:
            size = self._owned_files.get(staged_path)
            if size is not None:
                try:
                    self._assert_run_identity()
                    staged_path.unlink(missing_ok=True)
                except (OSError, RuntimeError, ValueError) as exc:
                    self._cleanup_error(exc)
                    self._failed = str(exc)
                    self._condition.notify_all()
                    return
                self._owned_files.pop(staged_path)
                self._current_bytes = max(0, self._current_bytes - size)
                self._condition.notify_all()
                try:
                    self._write_manifest()
                except (OSError, RuntimeError, ValueError) as exc:
                    self._cleanup_error(exc)

    def close(self) -> None:
        with self._lock:
            if self.cleaned_up:
                return
            try:
                self._assert_run_identity()
                for staged_path in list(self._owned_files):
                    self.release_image(staged_path)
                if self._owned_files:
                    return  # Preserve ownership manifest for files we could not remove.
                for temporary in list(self._manifest_temps):
                    temporary.unlink(missing_ok=True)
                    self._manifest_temps.discard(temporary)
                unowned = set(self.run_dir.iterdir()) - {self.manifest_path}
                if unowned:
                    raise OSError("Unowned scratch entries remain; preserving manifest")
                self.manifest_path.unlink(missing_ok=True)
                try:
                    self.run_dir.rmdir()
                except OSError:
                    self._write_manifest()
                    raise
                self.cleaned_up = True
            except (OSError, RuntimeError, ValueError) as exc:
                self._cleanup_error(exc)

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "scratch_dir": str(self.scratch_root),
                "run_dir": str(self.run_dir),
                "staged_images": self.staged_images,
                "staged_bytes": self.staged_bytes,
                "peak_staged_bytes": self.peak_staged_bytes,
                "copy_seconds": round(self.copy_seconds, 4),
                "wait_seconds": round(self.wait_seconds, 4),
                "cleanup_errors": list(self.cleanup_errors),
                "cleaned_up": self.cleaned_up,
            }

    def __enter__(self) -> ScratchWorkspace:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        if not self.cleaned_up and exc_type is None:
            raise RuntimeError(f"Scratch cleanup incomplete; ownership evidence retained at {self.run_dir}")
