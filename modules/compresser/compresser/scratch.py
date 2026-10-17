"""Analysis-only external SSD scratch workspace with ownership manifest and verified staging."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .cancellation import check_cancelled
from .models import ImageMetadata
from .timing import phase

SCRATCH_MANIFEST = ".compresser_scratch_manifest.json"
DEFAULT_MAX_STAGED_BYTES = 512 * 1024 * 1024


def validate_scratch_dir(scratch_dir: Path, target_root: Path) -> Path:
    expanded = scratch_dir.expanduser()
    if expanded.is_symlink():
        raise ValueError("Scratch directory cannot be a symlink")
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
        self.max_staged_bytes = max(16 * 1024 * 1024, max_staged_bytes)
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.scratch_root / f"compresser-scratch-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self.run_dir.mkdir(parents=False, exist_ok=False)
        self.manifest_path = self.run_dir / SCRATCH_MANIFEST
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.RLock()
        self._counter = 0
        self._owned_files: dict[Path, int] = {}
        self._current_bytes = 0
        self.peak_staged_bytes = 0
        self.staged_images = 0
        self.staged_bytes = 0
        self.copy_seconds = 0.0
        self.cleaned_up = False
        self._write_manifest()

    def _write_manifest(self) -> None:
        payload = {
            "owner": "compresser-scratch",
            "pid": os.getpid(),
            "target_root": str(self.target_root),
            "created_at": self.created_at,
            "staged_files": [path.name for path in sorted(self._owned_files)],
        }
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def stage_image(self, meta: ImageMetadata) -> Path:
        check_cancelled()
        path = meta.path
        if path.is_symlink():
            raise RuntimeError("Refusing linked input image")
        stat = path.stat()
        if meta.mtime_ns and (stat.st_mtime_ns != meta.mtime_ns or stat.st_size != meta.size_bytes):
            raise RuntimeError("Source changed since scan; rescan before compression")
        with phase("scratch_copy"):
            t0 = time.monotonic()
            data = path.read_bytes()
            after = path.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ) or len(data) != stat.st_size:
                raise RuntimeError("Source changed while staging to scratch; result discarded")
            check_cancelled()
            source_hash = hashlib.sha256(data).hexdigest()
            with self._lock:
                if self._current_bytes + len(data) > self.max_staged_bytes:
                    raise OSError("Scratch staging budget exceeded")
                self._counter += 1
                suffix = path.suffix.lower() or ".img"
                staged_path = self.run_dir / f"{self._counter:06d}_{source_hash[:12]}{suffix}"
                staged_path.write_bytes(data)
                if (
                    staged_path.stat().st_size != len(data)
                    or hashlib.sha256(staged_path.read_bytes()).hexdigest() != source_hash
                ):
                    staged_path.unlink(missing_ok=True)
                    raise OSError("Scratch copy verification failed")
                self._owned_files[staged_path] = len(data)
                self._current_bytes += len(data)
                self.peak_staged_bytes = max(self.peak_staged_bytes, self._current_bytes)
                self.staged_images += 1
                self.staged_bytes += len(data)
                self.copy_seconds += time.monotonic() - t0
                self._write_manifest()
                return staged_path

    def release_image(self, staged_path: Path | None) -> None:
        if staged_path is None:
            return
        with self._lock:
            size = self._owned_files.pop(staged_path, None)
            if size is not None:
                self._current_bytes = max(0, self._current_bytes - size)
                staged_path.unlink(missing_ok=True)
                if self.manifest_path.exists():
                    self._write_manifest()

    def close(self) -> None:
        with self._lock:
            if self.cleaned_up:
                return
            if self.manifest_path.is_file():
                try:
                    data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                if data.get("owner") == "compresser-scratch":
                    for staged_path in list(self._owned_files):
                        staged_path.unlink(missing_ok=True)
                    self._owned_files.clear()
                    self._current_bytes = 0
                    self.manifest_path.unlink(missing_ok=True)
                    try:
                        self.run_dir.rmdir()
                        self.cleaned_up = True
                    except OSError:
                        self.cleaned_up = False

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "scratch_dir": str(self.scratch_root),
                "run_dir": str(self.run_dir),
                "staged_images": self.staged_images,
                "staged_bytes": self.staged_bytes,
                "peak_staged_bytes": self.peak_staged_bytes,
                "copy_seconds": round(self.copy_seconds, 4),
                "cleaned_up": self.cleaned_up,
            }

    def __enter__(self) -> ScratchWorkspace:
        return self

    def __exit__(self, *args) -> None:
        self.close()
