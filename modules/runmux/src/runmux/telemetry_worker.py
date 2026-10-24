"""In-process background telemetry collection and rollup maintenance worker for Runmux Web."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from runmux.constants import TERMINAL_STATUSES
from runmux.models import RunRecord
from runmux.stats import TelemetrySampler
from runmux.web_adapter import ReadOnlyRunmux
from runmux.telemetry_store import TelemetryStore

logger = logging.getLogger(__name__)

DEFAULT_SAMPLING_CADENCE_SECONDS = 5.0
DEFAULT_MAINTENANCE_CADENCE_SECONDS = 900.0 # 15 minutes


class TelemetryHistoryWorker:
    """Asynchronous in-process worker that periodically collects active run metrics and runs rollups."""

    def __init__(
        self,
        state_dir: Path | str,
        *,
        cadence_seconds: float = DEFAULT_SAMPLING_CADENCE_SECONDS,
        maintenance_cadence_seconds: float = DEFAULT_MAINTENANCE_CADENCE_SECONDS,
        sampler: TelemetrySampler | None = None,
        telemetry_store: TelemetryStore | None = None,
        psutil_module: Any = None,
    ) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.cadence_seconds = cadence_seconds
        self.maintenance_cadence_seconds = maintenance_cadence_seconds
        self.sampler = sampler or TelemetrySampler(child_cache_ttl=30.0)
        self.telemetry_store = telemetry_store or TelemetryStore(self.state_dir, auto_init=False)
        self.psutil_module = psutil_module
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_maintenance_at = time.time()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runmux-telemetry-worker")

    async def start(self) -> None:
        """Start the background sampling task."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="runmux-telemetry-history-worker")

    async def stop(self, *, timeout: float = 2.0) -> None:
        """Signal the worker to stop and wait for loop termination."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._executor.shutdown(wait=False)

    def _verify_store_integrity_sync(self) -> None:
        """Verify store health and quarantine corrupt database without interrupting Runmux operations."""
        try:
            if not self.telemetry_store.check_integrity():
                logger.warning("Corrupt telemetry database detected. Quarantining and resetting store.")
                quarantined = self.telemetry_store.quarantine_and_reset()
                if quarantined is not None:
                    logger.info("Successfully quarantined corrupt telemetry database to %s", quarantined)
                else:
                    logger.warning("Quarantine deferred (database files may be locked by an active reader).")
        except Exception as error:
            logger.error("Error checking or resetting telemetry store integrity: %s", error)

    def _sample_and_persist_sync(self, records: list[RunRecord]) -> None:
        """Synchronously sample active runs and write to SQLite."""
        if not self.state_dir.exists():
            return
        active = [r for r in records if r.status not in TERMINAL_STATUSES]
        stats, host = self.sampler.sample_active_runs(active, psutil_module=self.psutil_module)
        try:
            if stats:
                self.telemetry_store.insert_process_samples(stats)
            if host:
                self.telemetry_store.insert_host_sample(host)
        except Exception as error:
            logger.error("Failed persisting telemetry samples: %s", error)
            self._verify_store_integrity_sync()

    def _run_maintenance_sync(self, now: float) -> None:
        """Synchronously run rollup generation, retention pruning, and budget enforcement."""
        try:
            self.telemetry_store.generate_rollups(now=now)
            self.telemetry_store.prune_retention(now=now)
            self.telemetry_store.checkpoint_wal()
            self.telemetry_store.enforce_storage_budget()
        except Exception as error:
            logger.error("Telemetry maintenance error: %s", error)
            self._verify_store_integrity_sync()

    async def _run_loop(self) -> None:
        """Continuous sampling loop executing every cadence_seconds."""
        loop = asyncio.get_running_loop()
        backend = ReadOnlyRunmux(self.state_dir)

        # Pre-flight integrity verification at worker startup
        if self.state_dir.exists():
            await loop.run_in_executor(self._executor, self._verify_store_integrity_sync)

        while self._running:
            start_time = time.monotonic()
            now_wall = time.time()

            try:
                if self.state_dir.exists():
                    records = await loop.run_in_executor(self._executor, backend.list_runs)
                    await loop.run_in_executor(self._executor, self._sample_and_persist_sync, records)

                    if (now_wall - self._last_maintenance_at) >= self.maintenance_cadence_seconds:
                        await loop.run_in_executor(self._executor, self._run_maintenance_sync, now_wall)
                        self._last_maintenance_at = now_wall

            except Exception as error:
                logger.error("Error in telemetry collection cycle: %s", error)

            # Sleep remaining time until next tick or until stop_event is set
            elapsed = time.monotonic() - start_time
            sleep_time = max(0.05, self.cadence_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_time)
                break # stop_event was set
            except asyncio.TimeoutError:
                pass
