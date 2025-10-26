from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
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
    download_trigger_bytes: Optional[int]
    free_space_trigger_bytes: Optional[int]


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

    def manual_run(self, *, dry_run: bool, trigger: str, operation: Optional[str] = None, max_files: Optional[int] = None) -> bool:
        if not self.is_enabled():
            return False
        op = (operation or self._config.default_operation)
        eff_max = max_files if max_files is not None else self._config.max_files
        return self._start_run(operation=op, dry_run=dry_run, trigger=trigger, max_files=eff_max)

    def update_download_progress(self, total_download_bytes: int) -> Optional[str]:
        with self._lock:
            self._known_download_bytes = total_download_bytes
            if not self.is_enabled() or self._running:
                return None
            trigger: Optional[str] = None
            if self._config.download_trigger_bytes:
                delta = total_download_bytes - self._bytes_at_last_run
                if delta >= self._config.download_trigger_bytes:
                    trigger = f"{delta / (1024 ** 3):.2f} GiB downloaded since last sync"
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

            effective_max = max_files if (max_files and max_files > 0) else self._config.max_files
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
            with self._lock:
                self._last_result = run_summary
                self._bytes_at_last_run = self._known_download_bytes
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
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

