"""Bounded, process-local observations. This store never writes to disk."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import replace
from threading import RLock
from typing import Any

from .inference_models import HardwareSample, InferenceRequest, ModelInventoryEntry


class LiveInferenceStore:
    """Retain bounded request content, hardware samples, and the latest inventory in memory only."""

    def __init__(
        self,
        *,
        max_requests: int = 500,
        max_content_bytes: int = 2_000_000,
        max_hardware_samples: int = 2000,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if max_content_bytes < 0:
            raise ValueError("max_content_bytes must not be negative")
        if max_hardware_samples < 1:
            raise ValueError("max_hardware_samples must be at least 1")
        self.max_requests = max_requests
        self.max_content_bytes = max_content_bytes
        self.max_hardware_samples = max_hardware_samples
        self._lock = RLock()
        self._requests: OrderedDict[str, InferenceRequest] = OrderedDict()
        self._hardware_samples: deque[HardwareSample] = deque(maxlen=max_hardware_samples)
        self._server: dict[str, Any] | None = None
        self._models: tuple[ModelInventoryEntry, ...] = ()

    def add_request(self, request: InferenceRequest) -> None:
        with self._lock:
            self._requests.pop(request.request_id, None)
            while len(self._requests) >= self.max_requests:
                self._requests.popitem(last=False)
            remaining = max(0, self.max_content_bytes - self._content_bytes())
            content = []
            for segment in _coalesce_segments(request.content):
                text = segment.text
                if text is None:
                    content.append(segment)
                    continue
                encoded = text.encode("utf-8")
                if len(encoded) <= remaining:
                    remaining -= len(encoded)
                    content.append(segment)
                    continue
                clipped = encoded[:remaining].decode("utf-8", errors="ignore")
                remaining = 0
                content.append(replace(segment, text=clipped, truncated=True))
            self._requests[request.request_id] = replace(request, content=tuple(content))

    def requests(self) -> tuple[InferenceRequest, ...]:
        with self._lock:
            return tuple(reversed(self._requests.values()))

    def get_request(self, request_id: str) -> InferenceRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def active_request_count(self) -> int:
        with self._lock:
            return sum(
                1
                for r in self._requests.values()
                if r.state in {"active", "generating", "running", "queued"}
            )

    def has_active_requests(self) -> bool:
        return self.active_request_count() > 0

    def add_hardware_sample(self, sample: HardwareSample) -> None:
        with self._lock:
            self._hardware_samples.append(sample)

    def hardware_samples(
        self,
        *,
        device_id: str | None = None,
        limit: int | None = None,
        since_timestamp: str | None = None,
        since_monotonic: float | None = None,
    ) -> list[HardwareSample]:
        with self._lock:
            samples = list(self._hardware_samples)
        if device_id is not None:
            samples = [s for s in samples if s.device_id == device_id]
        if since_timestamp is not None:
            samples = [s for s in samples if s.timestamp >= since_timestamp]
        if since_monotonic is not None:
            samples = [s for s in samples if s.timestamp_monotonic >= since_monotonic]
        if limit is not None and limit > 0:
            samples = samples[-limit:]
        return samples

    def latest_hardware_sample(self, device_id: str | None = None) -> HardwareSample | None:
        with self._lock:
            for s in reversed(self._hardware_samples):
                if device_id is None or s.device_id == device_id:
                    return s
            return None

    def append_content(self, request_id: str, segment: Any) -> None:
        """Append one captured segment under the same global content budget."""
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                return
            content = list(request.content)
            previous = content[-1] if content else None
            if previous and previous.kind == segment.kind and previous.role == segment.role and previous.source == segment.source and previous.text is not None and segment.text is not None:
                content[-1] = replace(previous, text=previous.text + segment.text, observed_at=segment.observed_at, sequence=segment.sequence or previous.sequence)
            else:
                content.append(segment)
            self._requests[request_id] = replace(request, content=tuple(content))
            self._trim_content()

    def _trim_content(self) -> None:
        remaining = self.max_content_bytes
        for request_id, request in reversed(self._requests.items()):
            segments = []
            for segment in reversed(request.content):
                if segment.text is None:
                    segments.append(segment)
                    continue
                encoded = segment.text.encode("utf-8")
                if len(encoded) <= remaining:
                    remaining -= len(encoded)
                    segments.append(segment)
                else:
                    clipped = encoded[:remaining].decode("utf-8", errors="ignore")
                    remaining = 0
                    segments.append(replace(segment, text=clipped, truncated=True))
            self._requests[request_id] = replace(request, content=tuple(reversed(segments)))

    def replace_inventory(self, server: dict[str, Any], models: list[ModelInventoryEntry]) -> None:
        with self._lock:
            self._server = dict(server)
            self._models = tuple(models)

    def inventory(self) -> tuple[dict[str, Any] | None, tuple[ModelInventoryEntry, ...]]:
        with self._lock:
            server = None if self._server is None else dict(self._server)
            return server, self._models

    def _content_bytes(self) -> int:
        return sum(
            len(segment.text.encode("utf-8"))
            for request in self._requests.values()
            for segment in request.content
            if segment.text is not None
        )


def _coalesce_segments(segments: tuple[Any, ...]) -> tuple[Any, ...]:
    result = []
    for segment in segments:
        previous = result[-1] if result else None
        if previous and previous.kind == segment.kind and previous.role == segment.role and previous.source == segment.source and previous.text is not None and segment.text is not None:
            result[-1] = replace(previous, text=previous.text + segment.text, observed_at=segment.observed_at, sequence=segment.sequence or previous.sequence, truncated=previous.truncated or segment.truncated)
        else:
            result.append(segment)
    return tuple(result)
