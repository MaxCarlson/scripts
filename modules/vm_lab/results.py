"""Structured backend results, redaction, and exit-code classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from vm_lab.exceptions import (
    EXIT_AUTH_REQUIRED,
    EXIT_ERROR,
    EXIT_INCOMPLETE,
    EXIT_INPUT_ERROR,
    EXIT_INTERACTION_REQUIRED,
    EXIT_SUCCESS,
)

_SECRET_PATTERN = re.compile(
    r"(?i)(password|secret|token|credential)\s*[:=]\s*(['\"]?)[^\s,'\";]+\2"
)


def redact_sensitive(text: str) -> str:
    """Redact credential-like key=value pairs from diagnostic text."""
    if not text:
        return text
    return _SECRET_PATTERN.sub(r"\1=[REDACTED]", text)


def classify_exit_code(payload: Any, backend_returncode: int) -> int:
    """Map backend JSON status/reason_code and process returncode to vm_lab exit taxonomy."""
    if isinstance(payload, dict):
        status = str(payload.get("status", "")).upper()
        reason = str(payload.get("reason_code", "")).lower()
        if status in {"PLANNED", "SUCCEEDED", "VERIFIED", "CREATED", "STARTED", "STOPPED", "ALREADY_RUNNING", "ALREADY_STOPPED", "CHECKPOINT_CREATED", "BOOTSTRAPPED", "EVIDENCE_COMPLETE"}:
            return EXIT_SUCCESS
        if status == "AWAITING_INTERACTION":
            return EXIT_INTERACTION_REQUIRED
        if status == "AWAITING_AUTHORIZATION" or (status == "BLOCKED" and ("authorization" in reason or "capability" in reason or "consent" in reason)):
            return EXIT_AUTH_REQUIRED
        if status in {"PARTIAL", "INCOMPLETE", "EVIDENCE_PARTIAL", "REBOOT_REQUIRED"}:
            return EXIT_INCOMPLETE
        if status == "ERROR":
            return EXIT_INPUT_ERROR if "invalid" in reason else EXIT_ERROR
        if status in {"FAILED", "FAIL", "BLOCKED", "INVALIDATED", "EVIDENCE_FAILED"}:
            return EXIT_ERROR
    return EXIT_SUCCESS if backend_returncode == 0 else (backend_returncode if backend_returncode > 0 else EXIT_ERROR)


@dataclass(frozen=True)
class BackendResult:
    """Typed result returned by BackendAdapter."""

    returncode: int
    exit_code: int
    stdout: str
    stderr: str
    data: Any = None
    command: tuple[str, ...] = ()
