"""Dedicated background recording pipeline for persistent inference history.

Provides bounded asynchronous persistence to TelemetryStore without blocking
the gateway event loop or inference forwarding.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Sequence

from .inference_models import ContentSegment, HardwareSample, InferenceRequest
from .storage import TelemetryStore

_LOGGER = logging.getLogger(__name__)


class InferenceRecorder:
    """Asynchronous, bounded recorder for local inference requests."""

    def __init__(
        self,
        store: TelemetryStore,
        *,
        mode: str = "metadata",
        queue_size: int = 1000,
    ) -> None:
        if mode not in {"metadata", "content"}:
            raise ValueError(f"invalid recording mode {mode!r}, must be 'metadata' or 'content'")
        self.store = store
        self.mode = mode
        self._content_authorized_at: str | None = (
            datetime.now(timezone.utc).isoformat() if mode == "content" else None
        )
        self._active_request_modes: dict[str, str] = {}
        self.queue_size = queue_size
        self._queue: queue.Queue[tuple[str, Any, str, Any, Any] | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_healthy = True
        self._last_error: str | None = None
        self._persisted_count = 0
        self._dropped_count = 0
        self._lock = threading.Lock()

    @property
    def is_healthy(self) -> bool:
        with self._lock:
            return self._is_healthy and self._thread is not None and self._thread.is_alive()

    @property
    def database_path(self) -> str:
        return str(self.store.path)

    def set_mode(self, mode: str) -> None:
        """Switch recording mode at runtime (metadata vs content)."""
        if mode not in {"metadata", "content"}:
            raise ValueError(f"invalid recording mode {mode!r}, must be 'metadata' or 'content'")
        with self._lock:
            if mode == "content" and self.mode != "content":
                self._content_authorized_at = datetime.now(timezone.utc).isoformat()
            elif mode == "metadata":
                self._content_authorized_at = None
            self.mode = mode
            _LOGGER.info("Inference recorder mode changed to %s", self.mode)

    def start(self) -> None:
        """Start the background writer worker."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="llm-monitor-recorder",
                daemon=True,
            )
            self._thread.start()
            _LOGGER.info("Inference recorder started in %s mode (database: %s)", self.mode, self.store.path)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal worker to stop, drain pending items, and wait."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._stop_event.set()
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            thread = self._thread

        thread.join(timeout=timeout)
        _LOGGER.info("Inference recorder stopped (persisted: %d, dropped: %d)", self._persisted_count, self._dropped_count)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until all currently queued items are processed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty():
                return
            time.sleep(0.02)

    def record_request_start(self, request: InferenceRequest) -> None:
        """Queue a request start notification."""
        if self._stop_event.is_set():
            return
        with self._lock:
            self._active_request_modes[request.request_id] = self.mode
            mode_at_start = self.mode
        # Privacy: Never forward contents at start
        self._enqueue(request, mode_at_start, None, None)

    def record_request_final(
        self,
        request: InferenceRequest,
        *,
        contents: Sequence[ContentSegment] | None = None,
        hardware_samples: Sequence[HardwareSample] | None = None,
    ) -> None:
        """Queue a completed, failed, or cancelled request for persistence."""
        if self._stop_event.is_set():
            return

        with self._lock:
            # Privacy invariant: Check mode authorized when this request began.
            mode_at_start = self._active_request_modes.pop(request.request_id, None)
            current_mode = self.mode

        if current_mode == "metadata":
            effective_mode = "metadata"
        elif mode_at_start is not None:
            # If registered at start, respect the mode that was active when request started
            effective_mode = mode_at_start
        else:
            effective_mode = current_mode

        # Privacy guarantee: In metadata mode, discard contents immediately
        safe_contents = contents if effective_mode == "content" else None
        self._enqueue(request, effective_mode, safe_contents, hardware_samples)

    def _enqueue(
        self,
        request: InferenceRequest,
        effective_mode: str,
        contents: Sequence[ContentSegment] | None,
        hardware_samples: Sequence[HardwareSample] | None,
    ) -> None:
        try:
            self._queue.put_nowait(("record", request, effective_mode, contents, hardware_samples))
        except queue.Full:
            with self._lock:
                self._dropped_count += 1
                self._is_healthy = False
                self._last_error = "Recorder queue capacity exceeded; record dropped"
            _LOGGER.warning("Inference recorder queue full; dropping observation for request %s", request.request_id)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            action, request, rec_mode, contents, hw_samples = item
            try:
                if action == "record":
                    self.store.record_inference(
                        request,
                        rec_mode,
                        contents=contents,
                        hardware_samples=hw_samples,
                    )
                    with self._lock:
                        self._persisted_count += 1
                        self._is_healthy = True
                        self._last_error = None
            except Exception as error:
                _LOGGER.exception("Failed to persist inference request %s: %s", getattr(request, "request_id", "?"), error)
                with self._lock:
                    self._is_healthy = False
                    self._last_error = str(error)
            finally:
                self._queue.task_done()

    def status(self) -> dict[str, Any]:
        """Return the current recorder configuration and operational health."""
        with self._lock:
            worker_running = self._thread is not None and self._thread.is_alive()
            healthy = self._is_healthy and worker_running
            return {
                "recording_enabled": True,
                "metadata": True,
                "content": self.mode == "content",
                "mode": self.mode,
                "database_path": str(self.store.path),
                "is_healthy": healthy,
                "healthy": healthy,
                "worker_running": worker_running,
                "persisted_requests_count": self._persisted_count,
                "pending_queue_size": self._queue.qsize(),
                "dropped_count": self._dropped_count,
                "last_error": self._last_error or (None if worker_running else "Recorder worker is not running"),
            }
