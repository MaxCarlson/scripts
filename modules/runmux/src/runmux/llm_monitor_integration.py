"""Optional, lazily imported LLM Monitor integration wrapper for Runmux.

This module provides a host-owned wrapper around the read-only LLM Monitor
adapter, observability service, and telemetry storage. It preserves Python 3.10
compatibility for ordinary Runmux, disables monitoring by default, validates
server-side configurations, and ensures no browser request can specify arbitrary
provider URLs or file paths.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_OPENCODE_URL = "http://127.0.0.1:4096"
DEFAULT_LMSTUDIO_URL = "http://127.0.0.1:1234"
DEFAULT_REFRESH_INTERVAL_SECONDS = 5.0
DEFAULT_MAX_SESSIONS = 200
METADATA_CACHE_TTL_SECONDS = 300.0


class MonitoringServiceUnavailableError(Exception):
    """Raised when the monitoring integration or provider is disabled or unavailable."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        self.message = message or f"Monitoring service is unavailable ({reason})"
        super().__init__(self.message)


class MonitoringSessionNotFoundError(Exception):
    """Raised when an LLM session is not found in either live or historical data."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"LLM session '{session_id}' not found")


def validate_provider_url(url: str) -> str:
    """Validate that a provider URL is a safe HTTP(S) endpoint without userinfo, query, or fragment.

    Correctly handles and preserves IPv6 bracketed hosts, validates ports (1-65535),
    and rejects credentials without leaking them in error messages.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Provider URL must be a non-empty string.")
    raw = url.strip()
    try:
        parsed = urlsplit(raw)
    except Exception as exc:
        raise ValueError("Provider URL is not a valid URL.") from exc

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid scheme '{parsed.scheme}'; only http and https are allowed.")

    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Provider URL must have a valid host.")

    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("Provider URL must not contain credentials.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Provider URL has an invalid port.") from exc

    if port is not None and not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is out of range (1-65535).")

    if parsed.query:
        raise ValueError("Provider URL must not contain query parameters.")
    if parsed.fragment:
        raise ValueError("Provider URL must not contain URL fragments.")

    clean_path = parsed.path.rstrip("/")
    host_part = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port_part = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{host_part}{port_part}{clean_path}"


@dataclass(frozen=True)
class LLMMonitorConfig:
    """Server-side configuration for the optional LLM Monitor integration."""

    enabled: bool = False
    opencode_url: str = DEFAULT_OPENCODE_URL
    lmstudio_url: str | None = DEFAULT_LMSTUDIO_URL
    database_path: Path | None = None
    explicit_database: bool = False
    directory: str | None = None
    refresh_interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS
    max_sessions: int = DEFAULT_MAX_SESSIONS
    invalid_config_error: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMMonitorConfig:
        """Parse configuration from server-side environment variables.

        When disabled, configuration parsing is completely inert and will not fail
        due to malformed URLs or missing monitor packages.
        """
        source = os.environ if env is None else env
        raw_enabled = source.get("RUNMUX_LLM_MONITOR_ENABLED", "").strip().lower()
        enabled = raw_enabled in {"1", "true", "yes"}

        if not enabled:
            return cls(enabled=False)

        # Integration is explicitly enabled; parse and validate settings safely
        raw_opencode = source.get("RUNMUX_LLM_MONITOR_OPENCODE_URL", DEFAULT_OPENCODE_URL).strip()
        try:
            opencode_url = validate_provider_url(raw_opencode) if raw_opencode else DEFAULT_OPENCODE_URL
        except ValueError:
            return cls(enabled=True, invalid_config_error="invalid_opencode_url")

        raw_lmstudio = source.get("RUNMUX_LLM_MONITOR_LMSTUDIO_URL", DEFAULT_LMSTUDIO_URL)
        lmstudio_url: str | None = None
        if raw_lmstudio and raw_lmstudio.strip() not in {"0", "none", "false", ""}:
            try:
                lmstudio_url = validate_provider_url(raw_lmstudio.strip())
            except ValueError:
                return cls(enabled=True, invalid_config_error="invalid_lmstudio_url")

        raw_db = source.get("RUNMUX_LLM_MONITOR_DATABASE")
        database_path: Path | None = None
        explicit_database = False
        if raw_db and raw_db.strip():
            candidate = Path(raw_db.strip()).resolve()
            database_path = candidate
            explicit_database = True
        else:
            # Check if platform default DB exists; never create one
            with contextlib.suppress(Exception):
                if sys.version_info >= (3, 11):
                    from llm_monitor.storage import default_database_path

                    default_path = default_database_path()
                    database_path = default_path

        raw_dir = source.get("RUNMUX_LLM_MONITOR_DIRECTORY")
        directory = raw_dir.strip() if raw_dir and raw_dir.strip() else None

        refresh_interval = DEFAULT_REFRESH_INTERVAL_SECONDS
        if raw_interval := source.get("RUNMUX_LLM_MONITOR_REFRESH_INTERVAL"):
            with contextlib.suppress(ValueError):
                parsed_interval = float(raw_interval)
                if parsed_interval > 0:
                    refresh_interval = min(max(parsed_interval, 0.5), 60.0)

        max_sessions = DEFAULT_MAX_SESSIONS
        if raw_max := source.get("RUNMUX_LLM_MONITOR_MAX_SESSIONS"):
            with contextlib.suppress(ValueError):
                parsed_max = int(raw_max)
                if parsed_max > 0:
                    max_sessions = min(max(parsed_max, 1), 1000)

        return cls(
            enabled=True,
            opencode_url=opencode_url,
            lmstudio_url=lmstudio_url,
            database_path=database_path,
            explicit_database=explicit_database,
            directory=directory,
            refresh_interval_seconds=refresh_interval,
            max_sessions=max_sessions,
        )


def check_monitor_availability() -> tuple[bool, str | None]:
    """Check if the Python runtime and optional llm_monitor package are compatible."""
    if sys.version_info < (3, 11):
        return False, "python_incompatible"
    try:
        from llm_monitor.runmux_adapter import RunmuxMonitoringAdapter  # noqa: F401
    except ImportError:
        return False, "package_missing"
    except Exception:
        return False, "adapter_unsupported"
    return True, None


def create_model_metadata_provider(
    client: Any,
    lmstudio: Any | None,
    directory: str | None = None,
) -> Callable[[str, dict[str, Any]], tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    """Create a thread-safe, cached model metadata provider callback."""
    cache_lock = threading.Lock()
    limits_cache: dict[tuple[str | None, str | None], tuple[float, dict[str, Any] | None]] = {}
    models_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])

    def metadata_provider(
        session_id: str,
        snapshot: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        nonlocal models_cache
        info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
        model_id = info.get("model") if isinstance(info.get("model"), str) else None
        provider_id = info.get("provider") if isinstance(info.get("provider"), str) else None

        now = time.monotonic()
        key = (model_id, provider_id)

        with cache_lock:
            cached_limit = limits_cache.get(key)
            if cached_limit is not None and now - cached_limit[0] < METADATA_CACHE_TTL_SECONDS:
                limits = cached_limit[1]
            else:
                limits = None
                if model_id:
                    with contextlib.suppress(Exception):
                        from llm_monitor.providers import extract_opencode_model_limits

                        limits_response = client.get_json("/config/providers", directory)
                        limits = extract_opencode_model_limits(limits_response.data, model_id, provider_id=provider_id)
                limits_cache[key] = (now, limits)

            if lmstudio is not None:
                if now - models_cache[0] < METADATA_CACHE_TTL_SECONDS:
                    models = models_cache[1]
                else:
                    try:
                        models = lmstudio.list_models()
                    except Exception:
                        models = []
                    models_cache = (now, models)
            else:
                models = []

        loaded = next(
            (m for m in models if isinstance(m, dict) and m.get("id") == model_id and m.get("state") == "loaded"),
            None,
        )
        return limits, loaded

    return metadata_provider


def create_hardware_provider() -> Callable[[], dict[str, Any]]:
    """Create a hardware metric sampling callback."""

    def hardware_snapshot() -> dict[str, Any]:
        try:
            from resource_metrics.gpu import gpu_devices, gpu_process_memory

            devices = gpu_devices()
            process_memory = gpu_process_memory()
            return {
                "available": bool(devices or process_memory),
                "scope": "point_in_time",
                "devices": devices,
                "process_memory": process_memory,
            }
        except ImportError:
            return {
                "available": False,
                "reason_code": "not_installed",
                "scope": "point_in_time",
                "devices": [],
                "process_memory": [],
            }
        except Exception:
            return {
                "available": False,
                "reason_code": "unavailable",
                "scope": "point_in_time",
                "devices": [],
                "process_memory": [],
            }

    return hardware_snapshot


class LLMMonitorIntegration:
    """Runmux host wrapper for optional LLM Monitor integration."""

    def __init__(
        self,
        config: LLMMonitorConfig | None = None,
        *,
        adapter: Any | None = None,
        service: Any | None = None,
    ) -> None:
        self.config = config or LLMMonitorConfig.from_env()
        self._injected_adapter = adapter
        self._injected_service = service
        self._adapter = adapter
        self._service = service
        self._init_lock = threading.RLock()
        self._initialized = adapter is not None
        self._last_force_refresh = 0.0

    def status(self) -> dict[str, Any]:
        """Return the host configuration and availability status without performing provider I/O.

        Does not expose raw provider endpoint URLs or sensitive paths.
        """
        if not self.config.enabled:
            return {
                "schema_version": 1,
                "availability": "disabled",
                "reason": "disabled",
                "capabilities": [],
                "max_sessions": self.config.max_sessions,
                "refresh_interval_seconds": self.config.refresh_interval_seconds,
            }

        if self.config.invalid_config_error:
            return {
                "schema_version": 1,
                "availability": "unavailable",
                "reason": self.config.invalid_config_error,
                "capabilities": [],
                "max_sessions": self.config.max_sessions,
                "refresh_interval_seconds": self.config.refresh_interval_seconds,
            }

        compatible, reason = check_monitor_availability()
        if not compatible and self._injected_adapter is None:
            return {
                "schema_version": 1,
                "availability": "unavailable",
                "reason": reason,
                "capabilities": [],
                "max_sessions": self.config.max_sessions,
                "refresh_interval_seconds": self.config.refresh_interval_seconds,
            }

        return {
            "schema_version": 1,
            "availability": "available",
            "reason": None,
            "capabilities": ["snapshot", "session_detail", "timeline", "alerts", "hardware"],
            "max_sessions": self.config.max_sessions,
            "refresh_interval_seconds": self.config.refresh_interval_seconds,
        }

    def get_adapter(self) -> Any | None:
        """Lazily initialize and return the shared RunmuxMonitoringAdapter."""
        if not self.config.enabled or self.config.invalid_config_error:
            return None
        with self._init_lock:
            if self._adapter is not None:
                return self._adapter

            compatible, _ = check_monitor_availability()
            if not compatible:
                return None

            try:
                from llm_monitor.observability import ObservabilityService
                from llm_monitor.opencode import OpenCodeClient
                from llm_monitor.providers import LMStudioClient
                from llm_monitor.runmux_adapter import RunmuxMonitoringAdapter

                client = OpenCodeClient(self.config.opencode_url)
                lmstudio = LMStudioClient(self.config.lmstudio_url) if self.config.lmstudio_url else None
                model_provider = create_model_metadata_provider(client, lmstudio, self.config.directory)
                hardware_provider = create_hardware_provider()

                self._service = ObservabilityService(
                    client,
                    directory=self.config.directory,
                    database_path=self.config.database_path,
                    max_sessions=self.config.max_sessions,
                    hardware_provider=hardware_provider,
                    model_metadata_provider=model_provider,
                )
                self._adapter = RunmuxMonitoringAdapter(
                    self._service,
                    database_path=self.config.database_path,
                    refresh_interval_seconds=self.config.refresh_interval_seconds,
                )
                self._initialized = True
                return self._adapter
            except Exception:
                return None

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return the shared system and session snapshot envelope.

        Rate-limits force_refresh to avoid flooding OpenCode with serial session polling.
        """
        adapter = self.get_adapter()
        if adapter is None:
            st = self.status()
            return {
                "schema_version": 1,
                "availability": st["availability"],
                "reason": st["reason"],
                "snapshot": None,
            }

        now = time.monotonic()
        with self._init_lock:
            effective_force = False
            if force_refresh and now - self._last_force_refresh >= self.config.refresh_interval_seconds:
                effective_force = True
                self._last_force_refresh = now

            try:
                raw_snapshot = adapter.snapshot(force_refresh=effective_force)
                return {
                    "schema_version": 1,
                    "availability": "available",
                    "reason": None,
                    "snapshot": raw_snapshot,
                }
            except Exception as exc:
                return {
                    "schema_version": 1,
                    "availability": "unavailable",
                    "reason": type(exc).__name__,
                    "snapshot": None,
                }

    def session_detail(self, provider_instance_id: str, session_id: str) -> dict[str, Any] | None:
        """Return provider-scoped session detail, refreshing snapshot first to ensure currency.

        Raises MonitoringServiceUnavailableError if the integration or provider is offline.
        Raises MonitoringSessionNotFoundError if the session is genuinely absent.
        """
        st = self.status()
        if st["availability"] == "disabled":
            raise MonitoringServiceUnavailableError("disabled", "LLM monitor integration is disabled")
        if st["availability"] == "unavailable":
            raise MonitoringServiceUnavailableError(
                st["reason"] or "unavailable",
                f"LLM monitor integration is unavailable ({st['reason']})",
            )

        adapter = self.get_adapter()
        if adapter is None:
            raise MonitoringServiceUnavailableError("adapter_unavailable", "LLM monitor adapter is unavailable")

        # Refresh snapshot to ensure service state is seeded/current
        snap_env = self.snapshot(force_refresh=False)
        if snap_env.get("availability") != "available":
            raise MonitoringServiceUnavailableError(
                snap_env.get("reason", "provider_unavailable"),
                "OpenCode provider snapshot failed",
            )

        detail = adapter.session_detail(provider_instance_id, session_id)
        if detail is not None:
            return detail

        # Check if provider had an error during snapshot discovery
        snap_payload = snap_env.get("snapshot") or {}
        provider_info = snap_payload.get("provider") or {}
        if provider_info.get("status") == "unavailable":
            error_msg = provider_info.get("error") or "provider unavailable"
            raise MonitoringServiceUnavailableError(
                "provider_unavailable",
                f"OpenCode provider is offline: {error_msg}",
            )

        raise MonitoringSessionNotFoundError(session_id)

    def timeline(
        self,
        provider_instance_id: str,
        session_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return a chronological page of stored session events."""
        adapter = self.get_adapter()
        if adapter is None:
            st = self.status()
            return {
                "schema_version": 1,
                "availability": st["availability"],
                "reason": st["reason"],
                "provider_instance_id": provider_instance_id,
                "session_id": session_id,
                "events": [],
                "next_cursor": None,
                "limit": limit,
            }
        return adapter.timeline(provider_instance_id, session_id, limit=limit, cursor=cursor)

    def alerts(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        provider_instance_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Return persisted alert states."""
        adapter = self.get_adapter()
        if adapter is None:
            st = self.status()
            return {
                "schema_version": 1,
                "availability": st["availability"],
                "reason": st["reason"],
                "alerts": [],
                "limit": limit,
            }
        return adapter.alerts(
            status=status,
            limit=limit,
            provider_instance_id=provider_instance_id,
            session_id=session_id,
        )

    def hardware(self) -> dict[str, Any]:
        """Return point-in-time hardware metrics projected from the current snapshot."""
        snap_env = self.snapshot()
        if snap_env.get("availability") != "available" or not snap_env.get("snapshot"):
            return {
                "schema_version": 1,
                "availability": snap_env.get("availability", "unavailable"),
                "reason": snap_env.get("reason", "hardware_unavailable"),
                "hardware": None,
            }
        hw = snap_env["snapshot"].get("hardware")
        if hw is None:
            return {
                "schema_version": 1,
                "availability": "unavailable",
                "reason": "hardware_unavailable",
                "hardware": None,
            }
        return {
            "schema_version": 1,
            "availability": "available",
            "reason": None,
            "hardware": hw,
        }
