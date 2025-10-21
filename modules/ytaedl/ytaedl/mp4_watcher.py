from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

MP4_OPERATION_CHOICES = ("copy", "move")
_MP4_SYNC_IMPORT_CANDIDATES = ("mp4_sync", "ytaedl.mp4_sync")
_mp4_sync_module: Optional[ModuleType] = None


def _load_mp4_sync() -> ModuleType:
    """Import the mp4_sync module from known locations."""
    global _mp4_sync_module
    if _mp4_sync_module is None:
        for module_name in _MP4_SYNC_IMPORT_CANDIDATES:
            try:
                _mp4_sync_module = import_module(module_name)
                break
            except ImportError:
                continue
        if _mp4_sync_module is None:
            candidates = ", ".join(_MP4_SYNC_IMPORT_CANDIDATES)
            raise ImportError(f"MP4 watcher requires one of these modules to be importable: {candidates}")
    return _mp4_sync_module


LOGGER = logging.getLogger(__name__)

GIB = 1024 ** 3


@dataclass(frozen=True)
class WatcherConfig:
    """Static configuration for the MP4 watcher integration."""

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
    """Snapshot of a completed watcher run."""

    completed_at: float
    duration_s: float
    operation: str
    dry_run: bool
    trigger: str
    planned_actions: int
    processed_actions: int
    plan_bytes: int
    processed_bytes: int
    summary_rows: Dict[str, Dict[str, Any]]
    totals: Dict[str, int]


@dataclass
class WatcherSnapshot:
    """Dynamic state snapshot returned to the manager UI."""

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
    bytes_since_last: int
    download_trigger_bytes: Optional[int]
    free_space_bytes: Optional[int]
    free_space_trigger_bytes: Optional[int]


class MP4Watcher:
    """Coordinate MP4 synchronisation runs and expose status for the manager UI."""

    def __init__(self, *, config: WatcherConfig, enabled: bool) -> None:
        self._config = config
        self._enabled = enabled
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._progress: Optional[Any] = None
        self._last_result: Optional[WatcherRunSummary] = None
        self._last_error: Optional[str] = None
        self._current_operation: Optional[str] = None
        self._current_dry_run = False
        self._trigger_reason: Optional[str] = None
        self._start_time: Optional[float] = None
        self._plan_actions: Optional[int] = None
        self._plan_bytes: Optional[int] = None
        self._known_download_bytes = 0
        self._bytes_at_last_run = 0
        self._free_space_bytes: Optional[int] = None
        self._log_ready = False
        self._mp4_sync: Optional[ModuleType] = None

        staging = config.staging_root
        dest = config.destination_root
        self._config_ok = staging.exists() and staging.is_dir() and dest.exists() and dest.is_dir()
        if not self._config_ok:
            missing = []
            if not staging.exists():
                missing.append(f"staging root '{staging}' missing")
            if not dest.exists():
                missing.append(f"destination root '{dest}' missing")
            LOGGER.warning("MP4 watcher disabled: %s", ", ".join(missing))
        else:
            # Seed counters so the first automatic trigger does not fire immediately.
            self._bytes_at_last_run = 0
            self._known_download_bytes = 0
            if self._enabled:
                try:
                    self._mp4_sync = _load_mp4_sync()
                except ImportError as exc:
                    self._last_error = str(exc)
                    LOGGER.error("MP4 watcher disabled: %s", exc)
                    self._enabled = False
                    self._config_ok = False

    def is_enabled(self) -> bool:
        return self._enabled and self._config_ok and self._mp4_sync is not None

    @property
    def config(self) -> WatcherConfig:
        return self._config

    def _mp4_sync_module(self) -> ModuleType:
        if self._mp4_sync is None:
            self._mp4_sync = _load_mp4_sync()
        return self._mp4_sync

    def update_download_progress(self, total_download_bytes: int) -> Optional[str]:
        """Record aggregate download progress and auto-trigger runs when thresholds hit."""
        if not self.is_enabled():
            with self._lock:
                self._known_download_bytes = total_download_bytes
            return None

        free_bytes = self._refresh_free_bytes()
        with self._lock:
            self._known_download_bytes = total_download_bytes
            in_progress = self._thread is not None and self._thread.is_alive()
            if in_progress:
                return None

            trigger_reason: Optional[str] = None
            if (
                self._config.download_trigger_bytes
                and total_download_bytes - self._bytes_at_last_run >= self._config.download_trigger_bytes
            ):
                gib = (total_download_bytes - self._bytes_at_last_run) / GIB
                trigger_reason = f"auto: {gib:.1f} GiB downloaded since last sync"
            elif (
                self._config.free_space_trigger_bytes is not None
                and free_bytes is not None
                and free_bytes <= self._config.free_space_trigger_bytes
            ):
                gib = free_bytes / GIB
                trigger_reason = f"auto: staging free space low ({gib:.1f} GiB)"

        if trigger_reason:
            started = self._start_run(
                operation=self._config.default_operation,
                dry_run=False,
                trigger=trigger_reason,
                max_files=self._config.max_files,
            )
            return trigger_reason if started else None
        return None

    def manual_run(
        self,
        *,
        operation: Optional[str] = None,
        dry_run: bool,
        trigger: str,
        max_files: Optional[int] = None,
    ) -> bool:
        """Try to start a manual run; returns True when launched."""
        op = (operation or self._config.default_operation).lower()
        if op not in MP4_OPERATION_CHOICES:
            raise ValueError(f"Unsupported MP4 operation '{operation}'")
        return self._start_run(operation=op, dry_run=dry_run, trigger=trigger, max_files=max_files)

    def snapshot(self) -> WatcherSnapshot:
        """Return current watcher state for UI purposes."""
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            progress_snapshot = self._progress.snapshot() if self._progress else None
            bytes_since_last = self._known_download_bytes - self._bytes_at_last_run
            snap = WatcherSnapshot(
                enabled=self._enabled,
                config_ok=self._config_ok,
                running=running,
                current_operation=self._current_operation,
                dry_run=self._current_dry_run,
                trigger_reason=self._trigger_reason,
                start_time=self._start_time,
                progress=progress_snapshot,
                plan_actions=self._plan_actions,
                plan_bytes=self._plan_bytes,
                last_error=self._last_error,
                last_result=self._last_result,
                bytes_since_last=bytes_since_last if bytes_since_last >= 0 else 0,
                download_trigger_bytes=self._config.download_trigger_bytes,
                free_space_bytes=self._free_space_bytes,
                free_space_trigger_bytes=self._config.free_space_trigger_bytes,
            )
        return snap

    def _refresh_free_bytes(self) -> Optional[int]:
        try:
            free_bytes = shutil.disk_usage(self._config.staging_root).free
        except Exception as exc:  # pragma: no cover - defensive: shutil may fail on uncommon FS
            LOGGER.debug("Failed to inspect free space for %s: %s", self._config.staging_root, exc)
            free_bytes = None
        with self._lock:
            self._free_space_bytes = free_bytes
        return free_bytes

    def _prepare_logging(self) -> None:
        if self._log_ready:
            return
        self._mp4_sync_module().configure_logging(self._config.log_path)
        self._log_ready = True

    def _start_run(
        self,
        *,
        operation: str,
        dry_run: bool,
        trigger: str,
        max_files: Optional[int],
    ) -> bool:
        if not self.is_enabled():
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._current_operation = operation.lower()
            self._current_dry_run = dry_run
            self._trigger_reason = trigger
            self._start_time = time.time()
            self._plan_actions = None
            self._plan_bytes = None
            self._last_error = None
            sync_module = self._mp4_sync_module()
            progress = sync_module.ProgressState()
            progress.set_ui_enabled(True)
            self._progress = progress
            args = (
                progress,
                operation.lower(),
                dry_run,
                trigger,
                max_files if max_files is not None else self._config.max_files,
            )
            self._thread = threading.Thread(target=self._run, args=args, daemon=True)
            self._thread.start()
            LOGGER.info("MP4 watcher run started: %s (dry_run=%s)", trigger, dry_run)
            return True

    def _run(
        self,
        progress: Any,
        operation: str,
        dry_run: bool,
        trigger: str,
        max_files: Optional[int],
    ) -> None:
        self._prepare_logging()
        t_start = time.perf_counter()
        plan_bytes = 0
        processed_bytes = 0
        processed_actions: List[Any] = []
        sync_module = self._mp4_sync_module()
        try:
            plan, folder_totals = sync_module.build_plan(
                self._config.staging_root,
                self._config.destination_root,
                operation,
                progress=progress,
            )
            progress.set_folder_totals(folder_totals)
            file_actions = [
                action for action in plan.actions if action.action != sync_module.ACTION_CREATE_DIR
            ]
            plan_actions_count = len(file_actions)
            plan_bytes = sum(action.source_size or 0 for action in file_actions)
            progress.set_total_files(plan_actions_count)
            progress.set_total_bytes(plan_bytes)
            with self._lock:
                self._plan_actions = plan_actions_count
                self._plan_bytes = plan_bytes
            effective_max = max_files if max_files is not None and max_files > 0 else None
            if plan_actions_count and effective_max:
                progress.set_total_files(min(plan_actions_count, effective_max))

            if plan_actions_count == 0:
                progress.set_message("No MP4 transfers required")
            else:
                processed_actions = sync_module.execute_plan(
                    plan,
                    dry_run=dry_run,
                    progress=progress,
                    confirm=False,
                    no_delete=self._config.keep_source,
                    max_files=effective_max,
                )

            processed_bytes = sum(action.source_size or 0 for action in processed_actions)
            summary = sync_module.compute_summary(
                processed_actions, delete_source=not self._config.keep_source
            )
            totals = {
                "transfer": summary.total_transfer_size,
                "source_deleted": summary.total_source_deleted_size,
                "destination_added": summary.total_destination_added_size,
                "destination_deleted": summary.total_destination_deleted_size,
                "skipped": summary.total_skipped_size,
            }
            run_summary = WatcherRunSummary(
                completed_at=time.time(),
                duration_s=time.perf_counter() - t_start,
                operation=operation,
                dry_run=dry_run,
                trigger=trigger,
                planned_actions=plan_actions_count,
                processed_actions=len(processed_actions),
                plan_bytes=plan_bytes,
                processed_bytes=processed_bytes,
                summary_rows=summary.rows,
                totals=totals,
            )
            with self._lock:
                self._last_result = run_summary
                self._bytes_at_last_run = self._known_download_bytes
        except Exception as exc:  # pragma: no cover - error paths depend on runtime environment
            LOGGER.exception("MP4 watcher run failed: %s", exc)
            with self._lock:
                self._last_error = str(exc)
        finally:
            progress.set_running(False)
            with self._lock:
                self._thread = None
                self._progress = None
                self._current_operation = None
                self._trigger_reason = None
                self._plan_actions = None
                self._plan_bytes = None
                self._start_time = None
            try:
                sync_module.log_event("INFO", f"MP4 watcher run finished (trigger={trigger}, dry_run={dry_run})")
            except Exception:
                LOGGER.debug("Failed to record mp4_sync log event for watcher completion.")
