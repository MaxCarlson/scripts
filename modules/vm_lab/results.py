"""Structured backend results, redaction, formatting, and exit-code classification."""

from __future__ import annotations

import json
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

_SUCCESS_STATUSES = {
    "PLANNED",
    "SUCCEEDED",
    "VERIFIED",
    "CREATED",
    "STARTED",
    "STOPPED",
    "ALREADY_RUNNING",
    "ALREADY_STOPPED",
    "CHECKPOINT_CREATED",
    "BASELINE_CREATED",
    "BOOTSTRAPPED",
    "EVIDENCE_COMPLETE",
    "COPIED",
    "CONNECTED",
    "STARTED_AND_CONNECTED",
    "RECOVERED",
    "OK",
}


def redact_sensitive(text: str) -> str:
    """Redact credential-like key=value pairs from diagnostic text."""
    if not text:
        return text
    return _SECRET_PATTERN.sub(r"\1=[REDACTED]", text)


def classify_exit_code(payload: Any, backend_returncode: int) -> int:
    """Map backend JSON status/reason_code and process returncode to vm_lab exit taxonomy."""
    nonzero_rc = backend_returncode if backend_returncode > 0 else EXIT_ERROR
    if isinstance(payload, dict):
        status = str(payload.get("status", "")).upper()
        reason = str(payload.get("reason_code", "")).lower()
        if status == "AWAITING_INTERACTION":
            return EXIT_INTERACTION_REQUIRED
        if status == "AWAITING_AUTHORIZATION" or (
            status == "BLOCKED" and ("authorization" in reason or "capability" in reason or "consent" in reason)
        ):
            return EXIT_AUTH_REQUIRED
        if status in {"PARTIAL", "INCOMPLETE", "EVIDENCE_PARTIAL", "REBOOT_REQUIRED"}:
            return EXIT_INCOMPLETE
        if status == "ERROR":
            return EXIT_INPUT_ERROR if "invalid" in reason else EXIT_ERROR
        if status in {"FAILED", "FAIL", "BLOCKED", "INVALIDATED", "EVIDENCE_FAILED", "DECLINED"}:
            return EXIT_ERROR
        if status in _SUCCESS_STATUSES:
            return EXIT_SUCCESS if backend_returncode == 0 else nonzero_rc
    return EXIT_SUCCESS if backend_returncode == 0 else nonzero_rc


def format_human_output(data: Any) -> str:
    """Render structured JSON backend output in a concise human-readable form."""
    if data is None:
        return ""
    if isinstance(data, list):
        if not data:
            return "(0 items)"
        lines: list[str] = []
        for item in data:
            if isinstance(item, dict):
                parts = [
                    f"{k}={item[k]}"
                    for k in ("template_id", "name", "vm_name", "id", "state", "status", "owned", "snapshot_type")
                    if k in item and item[k] is not None
                ]
                lines.append(" | ".join(parts) if parts else json.dumps(item))
            else:
                lines.append(str(item))
        return "\n".join(lines)
    if isinstance(data, dict):
        lines = []
        for k in (
            "status",
            "reason_code",
            "operation",
            "operation_id",
            "workflow_id",
            "workflow_digest",
            "vm_name",
            "vm_id",
            "checkpoint_name",
            "checkpoint_id",
            "exit_code",
            "error",
            "detail",
            "next_action",
        ):
            if k in data and data[k] is not None and data[k] != "":
                lines.append(f"{k}: {data[k]}")
        if not lines:
            return json.dumps(data, indent=2)
        return "\n".join(lines)
    return str(data)


@dataclass(frozen=True)
class BackendResult:
    """Typed result returned by BackendAdapter."""

    returncode: int
    exit_code: int
    stdout: str
    stderr: str
    data: Any = None
    command: tuple[str, ...] = ()
