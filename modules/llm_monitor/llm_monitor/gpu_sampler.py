"""Dedicated background GPU sampling service using resource_metrics."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .inference_models import HardwareSample
from .live_store import LiveInferenceStore

_LOGGER = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GpuSampler:
    """Own bounded background sampling of GPU hardware telemetry.

    Single background worker per monitor process.
    Never blocks inference forwarding or the web event loop.
    """

    def __init__(
        self,
        store: LiveInferenceStore,
        *,
        active_interval_seconds: float = 0.8,
        idle_interval_seconds: float = 4.0,
        command_timeout_seconds: float = 1.5,
        publish_interval_seconds: float = 1.0,
        event_hub: Any | None = None,
        is_active_fn: Callable[[], bool] | None = None,
        query_fn: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        if active_interval_seconds <= 0:
            raise ValueError("active_interval_seconds must be positive")
        if idle_interval_seconds <= 0:
            raise ValueError("idle_interval_seconds must be positive")
        self.store = store
        self.active_interval_seconds = active_interval_seconds
        self.idle_interval_seconds = idle_interval_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.publish_interval_seconds = publish_interval_seconds
        self.event_hub = event_hub
        self.is_active_fn = is_active_fn or store.has_active_requests
        self.query_fn = query_fn or self._default_gpu_query

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sample_id = 0
        self._devices: list[dict[str, Any]] = []
        self._state = "idle"  # "running", "idle", "unavailable", "stopped"
        self._last_sample_at: str | None = None
        self._last_publish_monotonic = 0.0
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            # Probe once synchronously to discover devices and establish initial state
            self._probe_devices()
            self._thread = threading.Thread(target=self._run_loop, name="llm-monitor-gpu-sampler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.active_interval_seconds + 0.5))
        self._thread = None
        with self._lock:
            self._state = "stopped"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "device_count": len(self._devices),
                "devices": [dict(d) for d in self._devices],
                "last_sample_at": self._last_sample_at,
                "last_error": self._last_error,
                "is_active": bool(self.is_active_fn()),
            }

    @property
    def is_available(self) -> bool:
        with self._lock:
            return len(self._devices) > 0 and self._state != "unavailable"

    def sample_now(self) -> list[HardwareSample]:
        """Perform one immediate sample; used during active cycles or tests."""
        return self._collect_sample()

    def _default_gpu_query(self, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            from resource_metrics import gpu as rm_gpu
        except ImportError:
            return []

        timeout = kwargs.get("timeout", self.command_timeout_seconds)
        try:
            return rm_gpu.nvidia_gpus(timeout=timeout, include_power=True, include_uuid=True)
        except TypeError:
            try:
                return rm_gpu.nvidia_gpus(timeout=timeout, include_power=True)
            except Exception:
                return rm_gpu.gpu_devices(timeout=timeout)
        except Exception:
            return []

    def _probe_devices(self) -> None:
        try:
            raw_devices = self.query_fn(timeout=self.command_timeout_seconds)
            if raw_devices:
                self._devices = [
                    {
                        "device_id": str(d.get("uuid") or f"gpu-{d.get('id', i)}"),
                        "device_index": int(d.get("id", i)),
                        "device_name": str(d.get("name") or f"GPU {i}"),
                        "vram_total_bytes": d.get("mem_total"),
                    }
                    for i, d in enumerate(raw_devices)
                ]
                self._state = "running"
                self._last_error = None
            else:
                self._devices = []
                self._state = "unavailable"
                self._last_error = "No supported GPU devices detected"
        except Exception as error:
            _LOGGER.debug("GPU probe failed: %s", error)
            self._devices = []
            self._state = "unavailable"
            self._last_error = str(error)

    def _collect_sample(self) -> list[HardwareSample]:
        mono_time = time.monotonic()
        utc_time = _utc_now_iso()
        try:
            raw_devices = self.query_fn(timeout=self.command_timeout_seconds)
        except Exception as error:
            with self._lock:
                self._last_error = str(error)
            return []

        if not raw_devices:
            with self._lock:
                if not self._devices:
                    self._state = "unavailable"
            return []

        samples: list[HardwareSample] = []
        with self._lock:
            if not self._devices:
                self._devices = [
                    {
                        "device_id": str(d.get("uuid") or f"gpu-{d.get('id', i)}"),
                        "device_index": int(d.get("id", i)),
                        "device_name": str(d.get("name") or f"GPU {i}"),
                        "vram_total_bytes": d.get("mem_total"),
                    }
                    for i, d in enumerate(raw_devices)
                ]

            self._state = "running"
            self._last_error = None
            self._last_sample_at = utc_time

            for i, d in enumerate(raw_devices):
                self._sample_id += 1
                dev_id = str(d.get("uuid") or f"gpu-{d.get('id', i)}")
                dev_name = str(d.get("name") or f"GPU {i}")
                sample = HardwareSample(
                    sample_id=self._sample_id,
                    timestamp=utc_time,
                    timestamp_monotonic=mono_time,
                    device_id=dev_id,
                    device_name=dev_name,
                    source="resource_metrics.nvidia_smi",
                    gpu_utilization_percent=_safe_float(d.get("load")),
                    memory_controller_utilization_percent=_safe_float(d.get("memory_utilization")),
                    vram_used_bytes=_safe_float(d.get("mem_used")),
                    vram_total_bytes=_safe_float(d.get("mem_total")),
                    temperature_celsius=_safe_float(d.get("temp")),
                    power_watts=_safe_float(d.get("power_w")),
                    validity="valid",
                )
                self.store.add_hardware_sample(sample)
                samples.append(sample)

        # Publish throttled hardware update if event_hub is attached
        if self.event_hub is not None and samples:
            if mono_time - self._last_publish_monotonic >= self.publish_interval_seconds:
                self._last_publish_monotonic = mono_time
                for s in samples:
                    try:
                        self.event_hub.publish({
                            "type": "hardware.sample",
                            "timestamp": s.timestamp,
                            "sample": s.to_dict(),
                        })
                    except Exception:
                        _LOGGER.debug("Failed to publish hardware sample event")

        return samples

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            active = False
            try:
                active = bool(self.is_active_fn())
            except Exception:
                active = False

            interval = self.active_interval_seconds if active else self.idle_interval_seconds
            try:
                self._collect_sample()
            except Exception as error:
                _LOGGER.exception("Unexpected error in GPU sampling loop: %s", error)
                with self._lock:
                    self._last_error = str(error)

            if self._stop.wait(interval):
                break


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
        return val if (not val != val) else None
    except (TypeError, ValueError):
        return None
