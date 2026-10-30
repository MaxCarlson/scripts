"""Single-owner read-only inventory collection for the standalone inference view."""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .inference_models import CaptureCapabilities, ModelInventoryEntry
from .live_store import LiveInferenceStore


class InferenceMonitoringService:
    """Own one provider client and a bounded in-memory inventory snapshot."""

    def __init__(
        self,
        client: Any,
        *,
        endpoint: str,
        refresh_interval_seconds: float = 2.0,
        store: LiveInferenceStore | None = None,
    ) -> None:
        if refresh_interval_seconds <= 0:
            raise ValueError("refresh_interval_seconds must be positive")
        self.client = client
        self.endpoint = endpoint.rstrip("/")
        self.refresh_interval_seconds = refresh_interval_seconds
        self.store = store or LiveInferenceStore()
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._revision = 0
        self._first_observed_at: str | None = None
        self._state = self._unavailable_state("NotChecked")

    def refresh(self) -> dict[str, Any]:
        with self._refresh_lock:
            checked_at = _now()
            try:
                raw_models = self.client.list_models()
                if not isinstance(raw_models, list):
                    raise ValueError("unsupported_inventory")
                models = [_normalize_model(item, self.server_instance_id) for item in raw_models if isinstance(item, dict)]
                self._first_observed_at = self._first_observed_at or checked_at
                server = self._server("connected", checked_at, None)
                capabilities = CaptureCapabilities.passive_inventory(available=True).to_dict()
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                models = []
                server = self._server("unavailable", checked_at, type(error).__name__)
                capabilities = CaptureCapabilities.passive_inventory(available=False).to_dict()
            with self._state_lock:
                self._revision += 1
                self._state = {
                    "schema_version": 1,
                    "revision": self._revision,
                    "refreshed_at": checked_at,
                    "server": server,
                    "capabilities": capabilities,
                    "models": [model.to_dict() for model in models],
                    "requests": [request.to_dict() for request in self.store.requests()],
                    "recording": {"metadata": False, "content": False, "status": "disabled"},
                }
                self.store.replace_inventory(server, models)
                return _copy_snapshot(self._state)

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = _copy_snapshot(self._state)
            snapshot["requests"] = [request.to_dict() for request in self.store.requests()]
            return snapshot

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self.refresh()
            self._thread = threading.Thread(target=self._poll, name="llm-monitor-inventory", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.refresh_interval_seconds + 0.5))
        self._thread = None

    @property
    def server_instance_id(self) -> str:
        identity = hashlib.sha256(_safe_endpoint(self.endpoint).encode("utf-8")).hexdigest()[:16]
        return f"lmstudio-{identity}"

    def _poll(self) -> None:
        while not self._stop.wait(self.refresh_interval_seconds):
            self.refresh()

    def _server(self, connection_state: str, checked_at: str, error_code: str | None) -> dict[str, Any]:
        return {
            "server_instance_id": self.server_instance_id,
            "provider_type": "lmstudio",
            "endpoint_id": hashlib.sha256(_safe_endpoint(self.endpoint).encode("utf-8")).hexdigest()[:16],
            "endpoint": _safe_endpoint(self.endpoint),
            "observation_environment": "local",
            "provider_version": None,
            "connection_state": connection_state,
            "first_observed_at": self._first_observed_at,
            "last_observed_at": checked_at if connection_state == "connected" else None,
            "error_code": error_code,
        }

    def _unavailable_state(self, error_code: str) -> dict[str, Any]:
        checked_at = _now()
        return {
            "schema_version": 1,
            "revision": 0,
            "refreshed_at": checked_at,
            "server": self._server("unavailable", checked_at, error_code),
            "capabilities": CaptureCapabilities.passive_inventory(available=False).to_dict(),
            "models": [],
            "requests": [],
            "recording": {"metadata": False, "content": False, "status": "disabled"},
        }


def _normalize_model(raw: dict[str, Any], server_instance_id: str) -> ModelInventoryEntry:
    model_id = raw.get("id")
    if not isinstance(model_id, str) or not model_id:
        model_id = "unknown-model"
    context_lengths = raw.get("loaded_context_lengths")
    if not isinstance(context_lengths, list):
        context_lengths = []
    contexts = tuple(sorted({int(value) for value in context_lengths if _positive_int(value)}))
    context = raw.get("context_length") if _positive_int(raw.get("context_length")) else None
    count = raw.get("loaded_instance_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        count = None
    maximum = raw.get("max_context_length") if _positive_int(raw.get("max_context_length")) else None
    state = raw.get("state") if raw.get("state") in {"loaded", "not-loaded"} else "unknown"
    return ModelInventoryEntry(
        server_instance_id=server_instance_id,
        provider_model_id=model_id,
        name=model_id,
        state=state,
        loaded_instance_count=count,
        context_length=context,
        loaded_context_lengths=contexts,
        max_context_length=maximum,
        quantization=None,
        model_instance_id=None,
        identity_quality="provider_model_id_only",
        context_source=str(raw.get("context_source", "unavailable")),
    )


def _safe_endpoint(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "unknown"
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme.lower(), netloc, "", "", ""))
    except (TypeError, ValueError):
        return "unknown"


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        **snapshot,
        "server": dict(snapshot["server"]),
        "capabilities": {key: dict(value) for key, value in snapshot["capabilities"].items()},
        "models": [dict(item) for item in snapshot["models"]],
        "requests": [dict(item) for item in snapshot["requests"]],
        "recording": dict(snapshot["recording"]),
    }
