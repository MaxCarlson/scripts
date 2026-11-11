"""Independent, read-only polling observer for Resource Coordinator monitoring.

Polls Resource Coordinator's loopback status endpoints, detects modern vs legacy contracts,
persists normalized operational observations, and reconciles state into durable notification
incidents using the IncidentLifecycleEngine.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from notifications.models import EventEnvelopeV1, PublishResult
from notifications.publisher import Publisher
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_STATUS_URL = "http://127.0.0.1:1235/_coordinator/status"
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RCObservation:
    """Normalized operational observation snapshot of Resource Coordinator."""

    observed_at: str
    status: str  # "available", "unavailable", "degraded"
    contract_version: str  # "modern_v1", "legacy", "unknown"
    has_recovery_contract: bool
    recovery_required: Optional[bool]
    inhibition_active: Optional[bool]
    inhibition_reason: Optional[str] = None
    journal_status: Optional[str] = None  # "available", "not_configured", "unavailable", None
    miner_state: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RCObservation:
        return cls(
            observed_at=data["observed_at"],
            status=data["status"],
            contract_version=data["contract_version"],
            has_recovery_contract=bool(data.get("has_recovery_contract")),
            recovery_required=data.get("recovery_required"),
            inhibition_active=data.get("inhibition_active"),
            inhibition_reason=data.get("inhibition_reason"),
            journal_status=data.get("journal_status"),
            miner_state=data.get("miner_state"),
            error_message=data.get("error_message"),
            details=data.get("details", {}),
        )


class ResourceCoordinatorObserver:
    """
    Independent out-of-process observer that polls Resource Coordinator over loopback,
    normalizes observations, preserves uncertainty, and publishes incident transitions.
    """

    def __init__(
        self,
        status_url: str = DEFAULT_COORDINATOR_STATUS_URL,
        poll_interval_seconds: float = 30.0,
        timeout_seconds: float = 5.0,
        storage: Optional[StorageEngine] = None,
        publisher: Optional[Publisher] = None,
        transport_fn: Optional[Callable[[str, float], Dict[str, Any]]] = None,
    ) -> None:
        self.status_url = self._validate_url(status_url)
        self.poll_interval = max(1.0, float(poll_interval_seconds))
        self.timeout = max(0.5, float(timeout_seconds))
        self.storage = storage
        self.publisher = publisher
        self._transport_fn = transport_fn
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Tracks last published state per incident_key: key -> (status, severity_or_reason)
        self._last_incident_states: Dict[str, tuple[str, Optional[str]]] = {}
        self._last_observation: Optional[RCObservation] = None

    @staticmethod
    def _validate_url(url: str) -> str:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme '{scheme}'. Must be 'http' or 'https'.")

        host = (parsed.hostname or "").lower()
        if host not in ALLOWED_LOOPBACK_HOSTS:
            raise ValueError(
                f"Security Error: Resource Coordinator target host '{host}' is prohibited. "
                f"Observer binds strictly to trusted loopback addresses: {sorted(ALLOWED_LOOPBACK_HOSTS)}."
            )
        return url

    def fetch_raw_status(self) -> Dict[str, Any]:
        """Fetch raw JSON status over loopback using bounded timeouts."""
        if self._transport_fn:
            return self._transport_fn(self.status_url, self.timeout)

        req = urllib.request.Request(
            self.status_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Scripts-Notifications-Observer/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise urllib.error.HTTPError(
                        self.status_url, resp.status, f"HTTP {resp.status}", resp.headers, None
                    )
                content = resp.read().decode("utf-8")
                return json.loads(content)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
            raise exc

    def parse_status_payload(self, raw_data: Dict[str, Any], observed_at: Optional[str] = None) -> RCObservation:
        """Parse raw status dictionary, detecting modern vs legacy contracts safely."""
        ts = observed_at or _now_iso()

        if not isinstance(raw_data, dict):
            return RCObservation(
                observed_at=ts,
                status="degraded",
                contract_version="unknown",
                has_recovery_contract=False,
                recovery_required=None,
                inhibition_active=None,
                error_message="Received malformed non-dictionary status response.",
            )

        # 1. Inspect GPU Inference & Recovery contract
        gpu_inference = raw_data.get("gpu_inference") or {}
        recovery = gpu_inference.get("recovery")

        has_recovery_contract = isinstance(recovery, dict)
        contract_ver = "modern_v1" if has_recovery_contract else "legacy"

        recovery_required: Optional[bool] = None
        inhibition_active: Optional[bool] = None
        inhibition_reason: Optional[str] = None
        journal_status: Optional[str] = None

        if has_recovery_contract and isinstance(recovery, dict):
            # Modern contract fields
            recovery_required = bool(recovery.get("required"))
            inh_obj = recovery.get("inhibition") or gpu_inference.get("inhibition")
            inhibition_active = inh_obj is not None
            if isinstance(inh_obj, dict):
                inhibition_reason = inh_obj.get("reason")

            journal_status = recovery.get("journal_status")
            if journal_status not in ("available", "not_configured", "unavailable"):
                journal_status = "unknown"
        else:
            # Legacy contract: missing recovery details entirely
            # MANDATORY RULE B4: Do not interpret missing recovery as required=False!
            recovery_required = None
            inh_obj = gpu_inference.get("inhibition")
            if inh_obj is not None:
                inhibition_active = True
                if isinstance(inh_obj, dict):
                    inhibition_reason = inh_obj.get("reason")
            elif "inhibition" in gpu_inference:
                inhibition_active = False
            else:
                inhibition_active = None

        # 2. Inspect Miner state
        miner_obj = raw_data.get("miner") or {}
        miner_state = miner_obj.get("state") if isinstance(miner_obj, dict) else None

        # Safe operational details allowlist
        safe_details = {
            "contract_version": contract_ver,
            "has_recovery_contract": has_recovery_contract,
            "journal_status": journal_status,
            "miner_state": miner_state,
        }
        if has_recovery_contract and isinstance(recovery, dict):
            requests_list = recovery.get("requests")
            if isinstance(requests_list, list):
                safe_details["unresolved_requests_count"] = len(requests_list)

        return RCObservation(
            observed_at=ts,
            status="available",
            contract_version=contract_ver,
            has_recovery_contract=has_recovery_contract,
            recovery_required=recovery_required,
            inhibition_active=inhibition_active,
            inhibition_reason=inhibition_reason,
            journal_status=journal_status,
            miner_state=miner_state,
            details=safe_details,
        )

    def reconcile_incidents(self, obs: RCObservation) -> List[PublishResult]:
        """
        Reconcile current observation with incident lifecycle engine.
        Enforces uncertainty rules (B4) and deduplication (B3).
        """
        if not self.publisher:
            return []

        results: List[PublishResult] = []

        # ── Condition 1: Service Availability ────────────────────────────────────
        key_avail = "rc_service_unavailable"
        if obs.status == "unavailable":
            # Coordinator unreachable: open service unavailable incident
            if self._last_incident_states.get(key_avail) != ("open", "warning"):
                res = self.publisher.create_and_publish(
                    source="resource_coordinator",
                    kind="service_unavailable",
                    incident_key=key_avail,
                    severity="warning",
                    summary="Resource Coordinator service is unavailable on loopback.",
                    lifecycle="open",
                    occurred_at=obs.observed_at,
                )
                results.append(res)
                self._last_incident_states[key_avail] = ("open", "warning")

            # MANDATORY RULE B4: When coordinator is unavailable, NEVER resolve safety holds!
            return results

        # Coordinator is available: resolve service unavailability if previously open
        if self._last_incident_states.get(key_avail) == ("open", "warning"):
            res = self.publisher.create_and_publish(
                source="resource_coordinator",
                kind="service_unavailable",
                incident_key=key_avail,
                severity="info",
                summary="Resource Coordinator service connectivity restored on loopback.",
                lifecycle="resolve",
                occurred_at=obs.observed_at,
            )
            results.append(res)
            self._last_incident_states[key_avail] = ("resolved", None)

        # ── Condition 2: Recovery Required / Restart Inhibition ──────────────────
        key_recovery = "gpu_inference_recovery"

        if obs.has_recovery_contract:
            # Modern contract evaluation
            if obs.recovery_required is True:
                reason = obs.inhibition_reason or "recovery required"
                state_tuple = ("open", reason)
                if self._last_incident_states.get(key_recovery) != state_tuple:
                    res = self.publisher.create_and_publish(
                        source="resource_coordinator",
                        kind="recovery_required",
                        incident_key=key_recovery,
                        severity="critical",
                        summary=f"GPU inference restart inhibited: {reason}",
                        lifecycle="open",
                        occurred_at=obs.observed_at,
                    )
                    results.append(res)
                    self._last_incident_states[key_recovery] = state_tuple
            elif obs.recovery_required is False:
                # Authoritatively cleared
                if self._last_incident_states.get(key_recovery, ("resolved", None))[0] != "resolved":
                    res = self.publisher.create_and_publish(
                        source="resource_coordinator",
                        kind="recovery_required",
                        incident_key=key_recovery,
                        severity="info",
                        summary="Resource Coordinator confirmed GPU inference recovery hold cleared.",
                        lifecycle="resolve",
                        occurred_at=obs.observed_at,
                    )
                    results.append(res)
                    self._last_incident_states[key_recovery] = ("resolved", None)
        else:
            # Legacy contract evaluation
            # MANDATORY RULE B4: Do not interpret missing recovery as required=False!
            if obs.inhibition_active is True:
                reason = obs.inhibition_reason or "inhibition hold active"
                state_tuple = ("open", reason)
                if self._last_incident_states.get(key_recovery) != state_tuple:
                    res = self.publisher.create_and_publish(
                        source="resource_coordinator",
                        kind="restart_inhibited",
                        incident_key=key_recovery,
                        severity="warning",
                        summary=f"GPU inference restart inhibited: {reason}",
                        lifecycle="open",
                        occurred_at=obs.observed_at,
                    )
                    results.append(res)
                    self._last_incident_states[key_recovery] = state_tuple
            elif obs.inhibition_active is False:
                # Authoritatively cleared in legacy
                if self._last_incident_states.get(key_recovery, ("resolved", None))[0] != "resolved":
                    res = self.publisher.create_and_publish(
                        source="resource_coordinator",
                        kind="restart_inhibited",
                        incident_key=key_recovery,
                        severity="info",
                        summary="Resource Coordinator confirmed restart inhibition cleared.",
                        lifecycle="resolve",
                        occurred_at=obs.observed_at,
                    )
                    results.append(res)
                    self._last_incident_states[key_recovery] = ("resolved", None)

        # ── Condition 3: Recovery Journal Availability ───────────────────────────
        key_journal = "rc_recovery_journal_unavailable"
        if obs.journal_status == "unavailable":
            if self._last_incident_states.get(key_journal) != ("open", "warning"):
                res = self.publisher.create_and_publish(
                    source="resource_coordinator",
                    kind="journal_unavailable",
                    incident_key=key_journal,
                    severity="warning",
                    summary="Resource Coordinator durable recovery journal is unavailable.",
                    lifecycle="open",
                    occurred_at=obs.observed_at,
                )
                results.append(res)
                self._last_incident_states[key_journal] = ("open", "warning")
        elif obs.journal_status in ("available", "not_configured"):
            if self._last_incident_states.get(key_journal) == ("open", "warning"):
                res = self.publisher.create_and_publish(
                    source="resource_coordinator",
                    kind="journal_unavailable",
                    incident_key=key_journal,
                    severity="info",
                    summary=f"Resource Coordinator recovery journal status is now '{obs.journal_status}'.",
                    lifecycle="resolve",
                    occurred_at=obs.observed_at,
                )
                results.append(res)
                self._last_incident_states[key_journal] = ("resolved", None)

        return results

    def poll_once(self) -> RCObservation:
        """Perform a single read-only status poll, record observation, and reconcile incidents."""
        ts = _now_iso()
        try:
            raw_data = self.fetch_raw_status()
            obs = self.parse_status_payload(raw_data, observed_at=ts)
        except Exception as exc:
            logger.warning("Resource Coordinator poll failed: %s", exc)
            obs = RCObservation(
                observed_at=ts,
                status="unavailable",
                contract_version="unknown",
                has_recovery_contract=False,
                recovery_required=None,
                inhibition_active=None,
                error_message=str(exc),
            )

        # Persist normalized observation
        if self.storage:
            try:
                self.storage.save_rc_observation(obs.to_dict())
            except Exception as exc:
                logger.error("Failed persisting RC observation: %s", exc)

        # Reconcile incident lifecycle
        self.reconcile_incidents(obs)
        self._last_observation = obs
        return obs

    def start(self) -> None:
        """Start the observer in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="RCObserverThread", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background observer thread cleanly."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("Error in observer polling loop: %s", exc, exc_info=True)
            self._stop_event.wait(self.poll_interval)
