"""Versioned, in-memory execution provenance for benchmark inference requests.

Credentials are one-use secrets held only as hashes by this registry. The context
contains identifiers only; it is safe to serialize into inference metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
import secrets
import threading
import time
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SCHEMA_VERSION = 1


def _identifier(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a 1-128 character ASCII identifier")
    return value


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    task_id: str
    execution_id: str
    trial_id: str | None = None
    repetition_id: str | None = None
    variant_id: str | None = None
    verification_status: str = "verified"
    provenance_source: str = "llm_monitor_gateway_credential"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("run_id", "task_id", "execution_id"):
            _identifier(getattr(self, field), field)
        for field in ("trial_id", "repetition_id", "variant_id"):
            _identifier(getattr(self, field), field, optional=True)
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported execution correlation schema")
        if self.verification_status not in {"verified", "unavailable", "incomplete"}:
            raise ValueError("invalid correlation verification status")
        if self.provenance_source != "llm_monitor_gateway_credential":
            raise ValueError("invalid correlation provenance source")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionContext":
        if not isinstance(payload, dict):
            raise ValueError("execution context must be an object")
        fields = {
            key: payload[key]
            for key in ("run_id", "task_id", "execution_id")
            if key in payload
        }
        for key in (
            "trial_id",
            "repetition_id",
            "variant_id",
            "verification_status",
            "provenance_source",
            "schema_version",
        ):
            if key in payload:
                fields[key] = payload[key]
        return cls(**fields)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Execution:
    context: ExecutionContext
    token_hash: str
    expires_at: float
    request_ids: list[str]
    closed: bool = False


class ExecutionCredentialRegistry:
    """Thread-safe short-lived credential registry; raw credentials are never retained."""

    def __init__(self, *, ttl_seconds: float = 1800.0, clock=time.monotonic) -> None:
        self.ttl_seconds = max(1.0, min(float(ttl_seconds), 1800.0))
        self._clock = clock
        self._lock = threading.RLock()
        self._executions: dict[str, _Execution] = {}

    def register(
        self,
        run_id: str,
        task_id: str,
        execution_id: str,
        *,
        repetition_id: str | None = None,
        variant_id: str | None = None,
    ) -> tuple[ExecutionContext, str]:
        context = ExecutionContext(
            run_id,
            task_id,
            execution_id,
            repetition_id=repetition_id,
            variant_id=variant_id,
        )
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune()
            if execution_id in self._executions:
                raise ValueError("execution_id is already registered")
            self._executions[execution_id] = _Execution(
                context,
                hashlib.sha256(token.encode("ascii")).hexdigest(),
                self._clock() + self.ttl_seconds,
                [],
            )
        return context, token

    def verify_and_record(self, token: str, request_id: str) -> ExecutionContext | None:
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            for entry in self._executions.values():
                if entry.closed or self._clock() >= entry.expires_at:
                    continue
                if secrets.compare_digest(entry.token_hash, digest):
                    if not isinstance(request_id, str) or not _IDENTIFIER.fullmatch(
                        request_id
                    ):
                        return None
                    if request_id not in entry.request_ids:
                        entry.request_ids.append(request_id)
                    return entry.context
        return None

    def complete(self, execution_id: str, trial_id: str | None = None) -> None:
        if trial_id is not None:
            _identifier(trial_id, "trial_id")
        with self._lock:
            entry = self._executions.get(execution_id)
            if entry is None:
                raise KeyError("unknown execution")
            entry.context = ExecutionContext(
                **{**entry.context.to_dict(), "trial_id": trial_id}
            )
            entry.closed = True

    def requests(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._executions.get(execution_id)
            if entry is None:
                return {
                    "execution_id": execution_id,
                    "request_ids": [],
                    "trial_id": None,
                    "verification_status": "unavailable",
                }
            expired = self._clock() >= entry.expires_at
            return {
                "execution_id": execution_id,
                "request_ids": list(entry.request_ids),
                "trial_id": entry.context.trial_id,
                "verification_status": "incomplete"
                if expired and not entry.closed
                else "verified",
                "context": entry.context.to_dict(),
            }

    def _prune(self) -> None:
        now = self._clock()
        for key in [
            key
            for key, item in self._executions.items()
            if item.closed or now >= item.expires_at
        ]:
            del self._executions[key]
