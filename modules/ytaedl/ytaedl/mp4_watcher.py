from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class WatcherConfig:
    staging_root: Path
    destination_root: Path
    log_path: Path
    default_operation: str
    max_files: Optional[int]
    keep_source: bool
    total_size_trigger_bytes: Optional[int]  # Auto-trigger when total MP4 size exceeds this
    free_space_trigger_bytes: Optional[int]  # Auto-trigger when free space drops below this


@dataclass
class WatcherRunSummary:
    completed_at: float
    duration_s: float
    operation: str
    dry_run: bool
    trigger: str
    planned_actions: int
    processed_actions: int
    plan_bytes: int
    processed_bytes: int
    summary_rows: Dict[str, Any]


@dataclass
class WatcherSnapshot:
    enabled: bool
    config_ok: bool
    running: bool
    current_operation: Optional[str]
    dry_run: bool
    trigger_reason: Optional[str]
    start_time: Optional[float]
    progress: Optional[Dict[str, Any]]
    plan_actions: Optional[int]
    plan_bytes: Optional[int]
    last_error: Optional[str]
    last_result: Optional[WatcherRunSummary]
    bytes_since_last: Optional[int]
    config: WatcherConfig


def _format_bytes(num_bytes: Optional[int | float]) -> str:
    if not isinstance(num_bytes, (int, float)) or num_bytes <= 0:
        return "0 B"
    value = float(num_bytes)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    precision = 0 if idx == 0 else 2
    return f"{value:.{precision}f} {units[idx]}"


def _format_duration(seconds: Optional[int | float]) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0:00:00.000"
    total = float(seconds)
    base = int(total)
    millis = int((total - base) * 1000)
    mins, secs = divmod(base, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:d}:{mins:02d}:{secs:02d}.{millis:03d}"


def _format_max_files(value: Optional[int]) -> str:
    return "unlimited" if not isinstance(value, int) or value <= 0 else str(value)


def _operation_mode_label(keep_source: bool) -> str:
    return "keep source" if keep_source else "delete source"


class MP4Watcher:
    def __init__(self, *, config: WatcherConfig, enabled: bool) -> None:
        self._config = config
        self._enabled = enabled
        self._config_ok = config.staging_root.exists() and config.destination_root.exists()
        if not self._config_ok:
            self._enabled = False

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._progress: Optional[Any] = None
        self._last_result: Optional[WatcherRunSummary] = None
        self._last_error: Optional[str] = None
        self._start_time: Optional[float] = None
        self._trigger_reason: Optional[str] = None
        self._current_operation: Optional[str] = None
        self._current_dry_run = False
        self._plan_actions: Optional[int] = None
        self._plan_bytes: Optional[int] = None
        self._running = False
        self._known_download_bytes = 0
        self._bytes_at_last_run = 0
        self._mp4_sync = None
        self._log_ready = False

    def is_enabled(self) -> bool:
        return self._enabled and self._config_ok

    @property
    def config(self) -> WatcherConfig:
        return self._config

    def config_snapshot(self) -> WatcherConfig:
        with self._lock:
            return replace(self._config)

    def _resolve_max_files(self, requested: Optional[int]) -> Optional[int]:
        if isinstance(requested, int) and requested > 0:
            return requested
        if isinstance(self._config.max_files, int) and self._config.max_files > 0:
            return self._config.max_files
        return None

    def _log_status(self, status: str, message: str) -> None:
        try:
            mp4_sync = self._load_mp4_sync()
            self._prepare_logging()
            mp4_sync.log_event(status, message)
        except Exception:
            # Logging must never interrupt watcher operation
            return

    def log_event(self, status: str, message: str) -> None:
        """Expose logging so callers (manager UI) can append watcher events."""
        self._log_status(status, message)

    def _apply_operation_locked(self, operation: str) -> str:
        normalized = operation.lower()
        if normalized not in {"copy", "move"}:
            raise ValueError(f"Unsupported MP4 operation: {operation}")
        self._config.default_operation = normalized
        self._config.keep_source = normalized == "copy"
        return normalized

    def set_default_operation(self, operation: str) -> str:
        with self._lock:
            return self._apply_operation_locked(operation)

    def toggle_operation(self) -> str:
        with self._lock:
            next_operation = "copy" if self._config.default_operation == "move" else "move"
            result = self._apply_operation_locked(next_operation)
            keep_source = self._config.keep_source
        self._log_status("MODE", f"Default operation set to {result} ({_operation_mode_label(keep_source)}).")
        return result

    def set_max_files(self, value: Optional[int]) -> Optional[int]:
        normalized = value if isinstance(value, int) and value > 0 else None
        with self._lock:
            self._config.max_files = normalized
            current = self._config.max_files
        if current:
            self._log_status("LIMIT", f"Max files per run set to {current}.")
        else:
            self._log_status("LIMIT", "Max files per run set to unlimited.")
        return current

    def set_free_space_trigger_gib(self, value: Optional[float]) -> Optional[int]:
        new_bytes: Optional[int]
        with self._lock:
            if value is None or (isinstance(value, (int, float)) and value <= 0):
                self._config.free_space_trigger_bytes = None
                new_bytes = None
            else:
                self._config.free_space_trigger_bytes = int(float(value) * (1024**3))
                new_bytes = self._config.free_space_trigger_bytes
        if new_bytes:
            gib = new_bytes / (1024**3)
            self._log_status("TRIGGER", f"Free-space trigger set to {gib:.1f} GiB.")
        else:
            self._log_status("TRIGGER", "Free-space trigger disabled.")
        return new_bytes

    def manual_run(
        self, *, dry_run: bool, trigger: str, operation: Optional[str] = None, max_files: Optional[int] = None
    ) -> bool:
        if not self.is_enabled():
            self._log_status("WARN", f"{'Dry-run' if dry_run else 'Run'} ignored: watcher disabled or misconfigured.")
            return False
        op = operation or self._config.default_operation
        eff_max = max_files if max_files is not None else self._config.max_files
        started = self._start_run(operation=op, dry_run=dry_run, trigger=trigger, max_files=eff_max)
        if not started:
            self._log_status("WARN", f"{'Dry-run' if dry_run else 'Run'} request ignored (already running).")
        return started

    def _calculate_total_mp4_size(self) -> int:
        """Calculate total size of all MP4 files in staging root subdirectories."""
        total_bytes = 0
        try:
            if not self._config.staging_root.exists():
                return 0
            for mp4_file in self._config.staging_root.rglob("*.mp4"):
                if mp4_file.is_file():
                    try:
                        total_bytes += mp4_file.stat().st_size
                    except Exception:
                        pass  # Skip files we can't read
        except Exception:
            pass
        return total_bytes

    def update_download_progress(self, total_download_bytes: int) -> Optional[str]:
        with self._lock:
            self._known_download_bytes = total_download_bytes
            if not self.is_enabled() or self._running:
                return None
            trigger: Optional[str] = None

            # Check total MP4 file size threshold
            if self._config.total_size_trigger_bytes:
                total_mp4_bytes = self._calculate_total_mp4_size()
                if total_mp4_bytes >= self._config.total_size_trigger_bytes:
                    trigger = f"total MP4 size {total_mp4_bytes / (1024 ** 3):.2f} GiB exceeds threshold"

            # Check free space threshold
            if trigger is None and self._config.free_space_trigger_bytes is not None:
                try:
                    free_bytes = shutil.disk_usage(self._config.staging_root).free
                except Exception:
                    free_bytes = None
                if free_bytes is not None and free_bytes <= self._config.free_space_trigger_bytes:
                    trigger = f"staging free space low ({free_bytes / (1024 ** 3):.2f} GiB)"

            if trigger:
                started = self._start_run(
                    operation=self._config.default_operation,
                    dry_run=False,
                    trigger=trigger,
                    max_files=self._config.max_files,
                )
                if started:
                    limit_desc = _format_max_files(self._resolve_max_files(self._config.max_files))
                    self._log_status(
                        "AUTO",
                        f"Auto-clean triggered ({trigger}); operation={self._config.default_operation}, max_files={limit_desc}.",
                    )
                    return trigger
        return None

    def snapshot(self) -> WatcherSnapshot:
        with self._lock:
            progress_snapshot = self._progress.snapshot() if self._progress else None
            bytes_since_last = max(0, self._known_download_bytes - self._bytes_at_last_run)
            return WatcherSnapshot(
                enabled=self._enabled,
                config_ok=self._config_ok,
                running=self._running,
                current_operation=self._current_operation,
                dry_run=self._current_dry_run,
                trigger_reason=self._trigger_reason,
                start_time=self._start_time,
                progress=progress_snapshot,
                plan_actions=self._plan_actions,
                plan_bytes=self._plan_bytes,
                last_error=self._last_error,
                last_result=self._last_result,
                bytes_since_last=bytes_since_last,
                config=replace(self._config),
            )

    def _load_mp4_sync(self):
        if self._mp4_sync is None:
            from . import mp4_sync  # lazy import to avoid circulars

            self._mp4_sync = mp4_sync
        return self._mp4_sync

    def _prepare_logging(self) -> None:
        if self._log_ready:
            return
        mp4_sync = self._load_mp4_sync()
        mp4_sync.configure_logging(self._config.log_path)
        self._log_ready = True

    def _start_run(self, *, operation: str, dry_run: bool, trigger: str, max_files: Optional[int]) -> bool:
        if not self.is_enabled():
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._start_time = time.time()
            self._trigger_reason = trigger
            self._current_operation = operation
            self._current_dry_run = dry_run
            self._plan_actions = None
            self._plan_bytes = None
            self._last_error = None
            self._thread = threading.Thread(
                target=self._run,
                args=(operation, dry_run, trigger, max_files),
                daemon=True,
            )
            self._thread.start()
            keep_source = self._config.keep_source
        run_label = "Dry-run" if dry_run else "Run"
        limit_desc = _format_max_files(self._resolve_max_files(max_files))
        self._log_status(
            "STATE",
            f"{run_label} started ({operation}, max_files={limit_desc}, {_operation_mode_label(keep_source)}) via {trigger}",
        )
        return True

    def _run(self, operation: str, dry_run: bool, trigger: str, max_files: Optional[int]) -> None:
        mp4_sync = self._load_mp4_sync()
        self._prepare_logging()
        progress = mp4_sync.ProgressState()
        if hasattr(progress, "set_ui_enabled"):
            progress.set_ui_enabled(True)  # type: ignore[attr-defined]
        with self._lock:
            self._progress = progress

        start_time = time.time()
        processed_actions = []
        total_files = 0
        total_bytes = 0
        try:
            plan, folder_totals = mp4_sync.build_plan(
                self._config.staging_root,
                self._config.destination_root,
                operation,
                progress=progress,
            )
            if hasattr(progress, "set_folder_totals"):
                progress.set_folder_totals(folder_totals)  # type: ignore[attr-defined]
            file_actions = [a for a in plan.actions if a.action != mp4_sync.ACTION_CREATE_DIR]
            total_files = len(file_actions)
            total_bytes = sum(a.source_size or 0 for a in file_actions)
            if hasattr(progress, "set_total_files"):
                progress.set_total_files(total_files)  # type: ignore[attr-defined]
            if hasattr(progress, "set_total_bytes"):
                progress.set_total_bytes(total_bytes)  # type: ignore[attr-defined]
            with self._lock:
                self._plan_actions = total_files
                self._plan_bytes = total_bytes

            effective_max = self._resolve_max_files(max_files)
            processed_actions = mp4_sync.execute_plan(
                plan,
                dry_run=dry_run,
                progress=progress,
                confirm=False,
                no_delete=self._config.keep_source,
                max_files=effective_max,
            )
            processed_bytes = sum(a.source_size or 0 for a in processed_actions)
            summary = mp4_sync.compute_summary(processed_actions, delete_source=not self._config.keep_source)
            run_summary = WatcherRunSummary(
                completed_at=time.time(),
                duration_s=time.time() - start_time,
                operation=operation,
                dry_run=dry_run,
                trigger=trigger,
                planned_actions=total_files,
                processed_actions=len(processed_actions),
                plan_bytes=total_bytes,
                processed_bytes=processed_bytes,
                summary_rows=summary.rows,
            )
            summary_bytes = processed_bytes if not dry_run else total_bytes
            mode_label = "Dry-run" if dry_run else "Run"
            action_desc = f"{len(processed_actions)}/{total_files} actions"
            bytes_desc = f"{'planned' if dry_run else 'moved'} {_format_bytes(summary_bytes)}"
            self._log_status(
                "STATE",
                f"{mode_label} complete in {_format_duration(run_summary.duration_s)} ({action_desc}, {bytes_desc}).",
            )
            with self._lock:
                self._last_result = run_summary
                self._bytes_at_last_run = self._known_download_bytes
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._log_status("ERROR", f"Watcher run failed: {exc}")
        finally:
            if hasattr(progress, "set_running"):
                progress.set_running(False)  # type: ignore[attr-defined]
            with self._lock:
                self._running = False
                self._progress = None
                self._thread = None
                self._trigger_reason = None
                self._start_time = None
                self._current_operation = None
                self._current_dry_run = False
                self._plan_actions = None
                self._plan_bytes = None
