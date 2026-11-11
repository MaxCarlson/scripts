"""Independent, read-only polling observer for Resource Coordinator monitoring.

Polls Resource Coordinator's loopback status endpoints, detects modern vs legacy contracts,
persists normalized operational observations, preserves uncertainty, and reconciles state into
durable notification incidents using the IncidentLifecycleEngine.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from notifications.models import EventEnvelopeV1, Incident, PublishResult
from notifications.publisher import Publisher
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_STATUS_URL = "http://127.0.0.1:1235/_coordinator/status"
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_STATUS_PATHS = {"/_coordinator/status", "/status"}
MAX_STATUS_RESPONSE_BYTES = 512 * 1024  # 512 KB
COORDINATOR_TASK_NAME = "ScriptsNotificationsCoordinatorObserver"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deterministic_incident_id(source: str, incident_key: str) -> str:
    """Compute deterministic SHA256 incident ID matching EventEnvelopeV1."""
    return hashlib.sha256(f"{source}\0{incident_key}".encode("utf-8")).hexdigest()


def _sanitize_error_message(exc: Exception | str) -> str:
    """Sanitize error messages removing file paths, tokens, and bounding length."""
    msg = str(exc).strip()
    msg = re.sub(r"[a-zA-Z]:\\[^\s]+", "[path]", msg)
    msg = re.sub(r"/(?:home|Users)/[^\s]+", "[path]", msg)
    msg = re.sub(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [redacted]", msg)
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    if len(msg) > 200:
        msg = msg[:197] + "..."
    return msg or "Observer request failed"


class LockError(Exception):
    """Base exception for observer advisory lock failures."""


class LockAcquisitionError(LockError):
    """Raised when an observer advisory lock cannot be acquired."""


class LockContentionError(LockAcquisitionError):
    """Raised when the lock is held by another process or observer."""


class LockSetupError(LockError):
    """Raised when lock file creation, directory setup, or filesystem permissions fail."""


class ObserverLock:
    """Advisory single-writer lock for observer executions."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[Any] = None

    def __enter__(self) -> ObserverLock:
        # 1. Directory and file setup
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self.lock_path, "a+")
        except (PermissionError, OSError) as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Failed to access or create observer lock file at {self.lock_path}: {exc}"
            ) from exc
        except Exception as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Unexpected error creating observer lock file at {self.lock_path}: {exc}"
            ) from exc

        # 2. Acquire exclusive advisory lock
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fd.seek(0)
                try:
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                except (OSError, PermissionError) as exc:
                    self._cleanup_fd()
                    raise LockContentionError(
                        f"Another observer is currently running (lock held at {self.lock_path})."
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError) as exc:
                    self._cleanup_fd()
                    import errno

                    if (
                        isinstance(exc, BlockingIOError)
                        or getattr(exc, "errno", None)
                        in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)
                    ):
                        raise LockContentionError(
                            f"Another observer is currently running (lock held at {self.lock_path})."
                        ) from exc
                    raise LockSetupError(
                        f"Unexpected error acquiring lock at {self.lock_path}: {exc}"
                    ) from exc
        except LockError:
            raise
        except Exception as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Unexpected locking API error for {self.lock_path}: {exc}"
            ) from exc

        return self

    def _cleanup_fd(self) -> None:
        if self._fd is not None:
            try:
                self._fd.close()
            except Exception:
                pass
            self._fd = None

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    try:
                        self._fd.seek(0)
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                self._cleanup_fd()


class SafeLoopbackRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that validates any redirect target against loopback security rules."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        ResourceCoordinatorObserver._validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
        providers: Optional[list[str]] = None,
    ) -> None:
        self.status_url = self._validate_url(status_url)
        self.poll_interval = max(1.0, float(poll_interval_seconds))
        self.timeout = max(0.5, float(timeout_seconds))
        self.storage = storage
        if publisher is not None:
            self.publisher = publisher
        elif storage is not None:
            self.publisher = Publisher(storage, default_providers=providers)
        else:
            self.publisher = None

        self._transport_fn = transport_fn
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
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

        norm_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        if norm_path not in ALLOWED_STATUS_PATHS:
            raise ValueError(
                f"Security Error: Prohibited status path '{parsed.path}'. "
                f"Observer restricts polling strictly to canonical status routes: {sorted(ALLOWED_STATUS_PATHS)}."
            )
        return url

    def fetch_raw_status(self) -> Dict[str, Any]:
        """Fetch raw JSON status over loopback using bounded timeouts, size limits, and safe proxy handling."""
        if self._transport_fn:
            return self._transport_fn(self.status_url, self.timeout)

        # Build opener that ignores external proxy environment variables (http_proxy, etc.)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # Disables proxy for loopback
            SafeLoopbackRedirectHandler(),
        )

        req = urllib.request.Request(
            self.status_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Scripts-Notifications-Observer/1.0",
            },
        )
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise urllib.error.HTTPError(
                        self.status_url, resp.status, f"HTTP {resp.status}", resp.headers, None
                    )

                # Validate Content-Type
                ct = resp.headers.get("Content-Type", "").lower()
                if ct and not any(
                    valid in ct for valid in ("application/json", "text/json", "application/problem+json")
                ):
                    raise ValueError(f"Unexpected Content-Type '{ct}'. Expected JSON response.")

                # Read with strict size limit
                content_bytes = resp.read(MAX_STATUS_RESPONSE_BYTES + 1)
                if len(content_bytes) > MAX_STATUS_RESPONSE_BYTES:
                    raise ValueError(
                        f"Response payload exceeded maximum allowed size of {MAX_STATUS_RESPONSE_BYTES} bytes."
                    )
                content = content_bytes.decode("utf-8")
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("Root JSON payload must be a dictionary object.")
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, ValueError) as exc:
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
        gpu_inference = raw_data.get("gpu_inference")
        if gpu_inference is not None and not isinstance(gpu_inference, dict):
            return RCObservation(
                observed_at=ts,
                status="degraded",
                contract_version="unknown",
                has_recovery_contract=False,
                recovery_required=None,
                inhibition_active=None,
                error_message="Malformed gpu_inference sub-object in status response.",
            )

        gpu_inference = gpu_inference or {}
        recovery = gpu_inference.get("recovery")

        has_recovery_contract = isinstance(recovery, dict)
        contract_ver = "modern_v1" if has_recovery_contract else "legacy"

        recovery_required: Optional[bool] = None
        inhibition_active: Optional[bool] = None
        inhibition_reason: Optional[str] = None
        journal_status: Optional[str] = None
        is_degraded = False
        degraded_reasons: List[str] = []

        if has_recovery_contract and isinstance(recovery, dict):
            # ── Modern contract fields ───────────────────────────────────────
            # Section 4.1: Explicit distinction between missing, null, invalid, and boolean
            if "required" in recovery:
                raw_req = recovery["required"]
                if raw_req is True:
                    recovery_required = True
                elif raw_req is False:
                    recovery_required = False
                elif raw_req is None:
                    recovery_required = None
                else:
                    recovery_required = None
                    is_degraded = True
                    degraded_reasons.append(f"Invalid non-boolean type for recovery.required: {type(raw_req).__name__}")
            else:
                # Missing 'required' field -> must remain None (unknown)
                recovery_required = None

            # Inhibition in modern contract: check recovery.inhibition or fallback to gpu_inference.inhibition
            inh_obj = recovery.get("inhibition") if "inhibition" in recovery else gpu_inference.get("inhibition")
            if inh_obj is None and ("inhibition" in recovery or "inhibition" in gpu_inference):
                inhibition_active = False
            elif isinstance(inh_obj, dict):
                inhibition_active = bool(inh_obj.get("active", True)) if "active" in inh_obj else True
                raw_reason = inh_obj.get("reason")
                inhibition_reason = str(raw_reason)[:200] if raw_reason is not None else None
            elif inh_obj is True:
                inhibition_active = True
            elif inh_obj is False:
                inhibition_active = False
            elif inh_obj is not None:
                inhibition_active = None
                is_degraded = True
                degraded_reasons.append("Invalid inhibition field format.")

            # Journal status validation
            raw_js = recovery.get("journal_status")
            if raw_js in ("available", "not_configured", "unavailable"):
                journal_status = raw_js
            elif raw_js is not None:
                journal_status = "unknown"
                is_degraded = True
                degraded_reasons.append(f"Unexpected journal_status '{raw_js}'.")
            else:
                journal_status = None

            # Validate requests structure
            requests_list = recovery.get("requests")
            has_uncertain_requests = False
            if requests_list is not None:
                if not isinstance(requests_list, list):
                    is_degraded = True
                    degraded_reasons.append("Malformed requests field in recovery contract.")
                else:
                    for req_item in requests_list:
                        if isinstance(req_item, dict) and req_item.get("phase") in ("uncertain", "recovery_required"):
                            has_uncertain_requests = True

            # Section 4.1: Conservative handling of contradictory recovery fields
            if recovery_required is False and inhibition_active is True:
                recovery_required = None
                is_degraded = True
                degraded_reasons.append(
                    "Contradictory state: recovery.required is false but restart inhibition is active."
                )

            if recovery_required is False and has_uncertain_requests:
                recovery_required = None
                is_degraded = True
                degraded_reasons.append(
                    "Contradictory state: recovery.required is false but unresolved uncertain requests remain."
                )

            if recovery_required is True and inhibition_active is False:
                is_degraded = True
                degraded_reasons.append(
                    "Contradictory state: recovery.required is true but restart inhibition is false."
                )

        else:
            # ── Legacy contract fields ───────────────────────────────────────
            # MANDATORY RULE B4: Do not interpret missing recovery as required=False!
            recovery_required = None
            inh_obj = gpu_inference.get("inhibition")
            if inh_obj is not None:
                if isinstance(inh_obj, dict):
                    inhibition_active = bool(inh_obj.get("active", True)) if "active" in inh_obj else True
                    raw_reason = inh_obj.get("reason")
                    inhibition_reason = str(raw_reason)[:200] if raw_reason is not None else None
                elif inh_obj is True:
                    inhibition_active = True
                elif inh_obj is False:
                    inhibition_active = False
                else:
                    inhibition_active = None
            elif "inhibition" in gpu_inference:
                inhibition_active = False
            else:
                inhibition_active = None

        # 2. Inspect Miner state
        miner_obj = raw_data.get("miner")
        miner_state = None
        if isinstance(miner_obj, dict):
            raw_state = miner_obj.get("state")
            miner_state = str(raw_state) if raw_state is not None else None

        # Build safe details
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

        obs_status = "degraded" if is_degraded else "available"
        err_msg = "; ".join(degraded_reasons) if degraded_reasons else None

        return RCObservation(
            observed_at=ts,
            status=obs_status,
            contract_version=contract_ver,
            has_recovery_contract=has_recovery_contract,
            recovery_required=recovery_required,
            inhibition_active=inhibition_active,
            inhibition_reason=inhibition_reason,
            journal_status=journal_status,
            miner_state=miner_state,
            error_message=err_msg,
            details=safe_details,
        )

    def _get_durable_incident(self, incident_key: str) -> Optional[Incident]:
        """Fetch current incident state directly from persistent SQLite storage."""
        if not self.storage:
            return None
        inc_id = deterministic_incident_id("resource_coordinator", incident_key)
        return self.storage.get_incident(inc_id)

    def reconcile_incidents(self, obs: RCObservation) -> List[PublishResult]:
        """
        Reconcile current observation with incident lifecycle engine.
        Enforces durable restart safety (4.2), uncertainty rules (4.1), and deduplication.
        """
        if not self.publisher:
            return []

        results: List[PublishResult] = []

        # ── Condition 1: Service Availability ────────────────────────────────────
        key_avail = "rc_service_unavailable"
        inc_avail = self._get_durable_incident(key_avail)
        avail_is_active = inc_avail is not None and inc_avail.status in ("open", "reopened", "acknowledged")

        if obs.status in ("unavailable", "degraded") and obs.error_message and obs.status == "unavailable":
            if not avail_is_active:
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

            # MANDATORY RULE B4: When coordinator is unavailable, NEVER resolve safety holds!
            return results

        if obs.status == "available" or (obs.status == "degraded" and obs.status != "unavailable"):
            if avail_is_active:
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

        # ── Condition 2: Recovery Required / Restart Inhibition ──────────────────
        key_recovery = "gpu_inference_recovery"
        inc_recovery = self._get_durable_incident(key_recovery)
        rec_is_active = inc_recovery is not None and inc_recovery.status in ("open", "reopened", "acknowledged")

        # Determine hold states
        is_hold_active = (obs.recovery_required is True) or (
            obs.recovery_required is None and obs.inhibition_active is True
        )
        is_hold_cleared = (obs.recovery_required is False and obs.inhibition_active is not True) or (
            not obs.has_recovery_contract and obs.inhibition_active is False
        )

        if is_hold_active:
            raw_reason = obs.inhibition_reason or "recovery required"
            clean_reason = raw_reason.replace("\n", " ").replace("\r", " ").strip()[:180]
            target_severity = "critical" if obs.recovery_required is True else "warning"

            if rec_is_active:
                # Check for severity escalation (e.g. legacy warning -> modern critical)
                if inc_recovery is not None and inc_recovery.severity != "critical" and target_severity == "critical":
                    res = self.publisher.create_and_publish(
                        source="resource_coordinator",
                        kind="recovery_required",
                        incident_key=key_recovery,
                        severity=target_severity,
                        summary=f"GPU inference restart inhibited: {clean_reason}",
                        lifecycle="open",
                        occurred_at=obs.observed_at,
                    )
                    results.append(res)
                # If already active at critical or same severity: DO NOT REPUBLISH!
                # Keeps acknowledgement intact, avoids duplicate outbox items across observer restarts.
            else:
                # New hold
                res = self.publisher.create_and_publish(
                    source="resource_coordinator",
                    kind="recovery_required" if obs.has_recovery_contract else "restart_inhibited",
                    incident_key=key_recovery,
                    severity=target_severity,
                    summary=f"GPU inference restart inhibited: {clean_reason}",
                    lifecycle="open",
                    occurred_at=obs.observed_at,
                )
                results.append(res)

        elif is_hold_cleared:
            if rec_is_active:
                res = self.publisher.create_and_publish(
                    source="resource_coordinator",
                    kind="recovery_required" if obs.has_recovery_contract else "restart_inhibited",
                    incident_key=key_recovery,
                    severity="info",
                    summary="Resource Coordinator confirmed GPU inference recovery hold cleared.",
                    lifecycle="resolve",
                    occurred_at=obs.observed_at,
                )
                results.append(res)

        # If uncertain: do nothing! Open hold remains open.

        # ── Condition 3: Recovery Journal Availability ───────────────────────────
        key_journal = "rc_recovery_journal_unavailable"
        inc_journal = self._get_durable_incident(key_journal)
        jour_is_active = inc_journal is not None and inc_journal.status in ("open", "reopened", "acknowledged")

        if obs.journal_status == "unavailable":
            if not jour_is_active:
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
        elif obs.journal_status in ("available", "not_configured"):
            if jour_is_active:
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

        return results

    def poll_once(self) -> RCObservation:
        """Perform a single read-only status poll, record observation, and reconcile incidents."""
        ts = _now_iso()

        # Single-writer lock across process boundaries
        lock_ctx: Any = nullcontext()
        if self.storage and self.storage.db_path:
            lock_path = self.storage.db_path.parent / ".rc_observer.lock"
            lock_ctx = ObserverLock(lock_path)

        with lock_ctx:
            try:
                raw_data = self.fetch_raw_status()
                obs = self.parse_status_payload(raw_data, observed_at=ts)
            except Exception as exc:
                clean_err = _sanitize_error_message(exc)
                logger.warning("Resource Coordinator poll failed: %s", clean_err)
                obs = RCObservation(
                    observed_at=ts,
                    status="unavailable",
                    contract_version="unknown",
                    has_recovery_contract=False,
                    recovery_required=None,
                    inhibition_active=None,
                    error_message=clean_err,
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
            except LockContentionError as exc:
                logger.warning("Observer cycle skipped due to lock contention: %s", exc)
            except LockError as exc:
                logger.error("Observer cycle failed due to lock error: %s", exc)
            except Exception as exc:
                logger.error("Error in observer polling loop: %s", exc, exc_info=True)
            self._stop_event.wait(self.poll_interval)


# ── Scheduled Task Lifecycle Management (Windows 11) ─────────────────────────


def get_coordinator_task_status() -> dict[str, Any]:
    """Query current status of the Coordinator Observer Scheduled Task."""
    if sys.platform != "win32":
        return {
            "ok": True,
            "platform": sys.platform,
            "supported": False,
            "task_installed": False,
            "message": "Scheduled Tasks are only supported on Windows.",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    $action = $task.Actions | Select-Object -First 1
    [PSCustomObject]@{
        Installed = $true
        State = $task.State.ToString()
        LastRunTime = $info.LastRunTime.ToString('o')
        LastTaskResult = $info.LastTaskResult
        NextRunTime = $info.NextRunTime.ToString('o')
        Executable = $action.Execute
        Arguments = $action.Arguments
    } | ConvertTo-Json -Compress
} catch [Microsoft.PowerShell.Cmdletization.MethodInvocationException], [System.Management.Automation.ItemNotFoundException] {
    [PSCustomObject]@{
        Installed = $false
        State = "NotInstalled"
    } | ConvertTo-Json -Compress
} catch {
    [PSCustomObject]@{
        Installed = $false
        State = "Error"
        Error = $_.Exception.Message
    } | ConvertTo-Json -Compress
}
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=json.dumps({"TaskName": COORDINATOR_TASK_NAME}),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            return {
                "ok": True,
                "task_name": COORDINATOR_TASK_NAME,
                "task_installed": data.get("Installed", False),
                "state": data.get("State", "Unknown"),
                "last_run_time": data.get("LastRunTime"),
                "next_run_time": data.get("NextRunTime"),
                "last_task_result": data.get("LastTaskResult"),
                "executable": data.get("Executable"),
                "arguments": data.get("Arguments"),
            }
        return {
            "ok": True,
            "task_name": COORDINATOR_TASK_NAME,
            "task_installed": False,
            "state": "NotInstalled",
        }
    except Exception as exc:
        return {
            "ok": False,
            "task_name": COORDINATOR_TASK_NAME,
            "task_installed": False,
            "error": str(exc),
        }


def install_coordinator_task(
    apply: bool = False,
    interval_minutes: int = 2,
    status_url: str = DEFAULT_COORDINATOR_STATUS_URL,
    db_path: Optional[Union[str, Path]] = None,
    executable: Optional[Union[str, Path]] = None,
    working_directory: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    """Register the Coordinator Observer as a Windows Scheduled Task."""
    # 1. Parameter validation
    try:
        eff_interval = int(interval_minutes)
        if eff_interval < 1 or eff_interval > 1440:
            return {
                "ok": False,
                "error": f"Invalid interval_minutes: {interval_minutes}. Must be between 1 and 1440.",
            }
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": f"Invalid interval_minutes: {interval_minutes}. Must be an integer between 1 and 1440.",
        }

    try:
        ResourceCoordinatorObserver._validate_url(status_url)
    except ValueError as exc:
        return {"ok": False, "error": f"Invalid status URL: {exc}"}

    for val_name, val in [
        ("status_url", status_url),
        ("db_path", str(db_path or "")),
        ("executable", str(executable or "")),
        ("working_directory", str(working_directory or "")),
    ]:
        if any(c in val for c in ("\x00", "\r", "\n")):
            return {
                "ok": False,
                "error": f"Invalid characters in {val_name}: newlines and null bytes are forbidden.",
            }

    python_exe = Path(executable).resolve() if executable else Path(sys.executable).resolve()

    # Durable default working directory (avoids hardcoding ephemeral git worktree)
    work_dir = Path(working_directory).resolve() if working_directory else Path.home().resolve()

    # Safe argument vector quoting via list2cmdline
    args_list = ["-m", "notifications.cli", "coordinator", "poll", "-u", status_url]
    if db_path:
        args_list.extend(["-d", str(Path(db_path))])
    runner_args = subprocess.list2cmdline(args_list)

    preview = {
        "ok": True,
        "action": "install_coordinator_task",
        "dry_run": not apply,
        "task_name": COORDINATOR_TASK_NAME,
        "executable": str(python_exe),
        "arguments": runner_args,
        "working_directory": str(work_dir),
        "interval_minutes": eff_interval,
        "requires_apply": not apply,
    }

    if not apply:
        return preview

    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "Scheduled Task installation is only supported on Windows.",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
$exe = $in.Executable
$argsStr = $in.Arguments
$workDir = $in.WorkingDirectory
$intervalMin = [int]$in.IntervalMinutes

$action = New-ScheduledTaskAction -Execute $exe -Argument $argsStr -WorkingDirectory $workDir
$timespan = New-TimeSpan -Minutes $intervalMin
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $timespan

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Independent Resource Coordinator Read-Only Observer' `
    -Force | Out-Null
"""
    input_payload = json.dumps({
        "TaskName": COORDINATOR_TASK_NAME,
        "Executable": str(python_exe),
        "Arguments": runner_args,
        "WorkingDirectory": str(work_dir),
        "IntervalMinutes": eff_interval,
    })

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=input_payload,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": f"Failed to register scheduled task: {proc.stderr.strip() or proc.stdout.strip()}",
            }
        preview["installed"] = True
        return preview
    except Exception as exc:
        return {"ok": False, "error": f"Exception executing task registration: {exc}"}


def uninstall_coordinator_task(apply: bool = False) -> dict[str, Any]:
    """Unregister the Coordinator Observer Scheduled Task."""
    preview = {
        "ok": True,
        "action": "uninstall_coordinator_task",
        "dry_run": not apply,
        "task_name": COORDINATOR_TASK_NAME,
        "requires_apply": not apply,
    }

    if not apply:
        return preview

    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "Scheduled Task uninstallation is only supported on Windows.",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    [PSCustomObject]@{ Uninstalled = $true } | ConvertTo-Json -Compress
} catch [Microsoft.PowerShell.Cmdletization.MethodInvocationException], [System.Management.Automation.ItemNotFoundException] {
    [PSCustomObject]@{ Uninstalled = $true; AlreadyAbsent = $true } | ConvertTo-Json -Compress
} catch {
    [PSCustomObject]@{ Uninstalled = $false; Error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=json.dumps({"TaskName": COORDINATOR_TASK_NAME}),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip() or "{}")
            if data.get("Uninstalled", False):
                preview["uninstalled"] = True
                preview["already_absent"] = data.get("AlreadyAbsent", False)
                return preview
            return {"ok": False, "error": data.get("Error", "Unknown error unregistering task")}
        return {"ok": False, "error": f"Failed unregistering task: {proc.stderr.strip()}"}
    except Exception as exc:
        return {"ok": False, "error": f"Exception unregistering task: {exc}"}
