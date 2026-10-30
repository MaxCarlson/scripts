"""Bounded, process-local observations. This store never writes to disk."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from threading import RLock
from typing import Any

from .inference_models import InferenceRequest, ModelInventoryEntry


class LiveInferenceStore:
    """Retain bounded request content and the latest inventory in memory only."""

    def __init__(self, *, max_requests: int = 500, max_content_bytes: int = 2_000_000) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if max_content_bytes < 0:
            raise ValueError("max_content_bytes must not be negative")
        self.max_requests = max_requests
        self.max_content_bytes = max_content_bytes
        self._lock = RLock()
        self._requests: OrderedDict[str, InferenceRequest] = OrderedDict()
        self._server: dict[str, Any] | None = None
        self._models: tuple[ModelInventoryEntry, ...] = ()

    def add_request(self, request: InferenceRequest) -> None:
        with self._lock:
            self._requests.pop(request.request_id, None)
            while len(self._requests) >= self.max_requests:
                self._requests.popitem(last=False)
            remaining = max(0, self.max_content_bytes - self._content_bytes())
            content = []
            for segment in request.content:
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
