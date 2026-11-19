"""Versioned protocol v1 request/response helpers for the privexec CLI."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
DEFAULT_PIPE_NAME = "privexec-broker-v1"

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CAPABILITY_RE = re.compile(r"^[a-z0-9._-]{1,64}$")
_TARGET_TYPE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

FORBIDDEN_CLIENT_KEYS = frozenset(
    {
        "authorized",
        "approval",
        "approved",
        "sid",
        "user",
        "username",
        "role",
        "executable",
        "executable_path",
        "script",
        "script_path",
        "script_block",
        "command",
        "credential",
        "password",
        "secret",
    }
)


class ProtocolValidationError(ValueError):
    """Raised when client-side request construction fails validation."""


def generate_request_id() -> str:
    """Return a unique client request identifier."""
    return f"req-{uuid.uuid4().hex[:16]}"


def validate_request_id(request_id: str) -> str:
    """Validate client request_id format."""
    if not _REQUEST_ID_RE.match(request_id):
        raise ProtocolValidationError(
            f"Invalid request_id '{request_id}'. Must match ^[A-Za-z0-9._:-]{{1,128}}$."
        )
    return request_id


def validate_capability(capability: str) -> str:
    """Validate capability identifier format."""
    if not _CAPABILITY_RE.match(capability):
        raise ProtocolValidationError(
            f"Invalid capability '{capability}'. Must match ^[a-z0-9._-]{{1,64}}$."
        )
    return capability


def validate_target(target_id: str, target_type: str) -> dict[str, str]:
    """Validate target identifier and type."""
    if not target_id or len(target_id) > 256 or any(ch.isspace() for ch in target_id):
        raise ProtocolValidationError("Target ID must be a non-empty non-whitespace string (max 256 chars).")
    if not _TARGET_TYPE_RE.match(target_type):
        raise ProtocolValidationError(
            f"Invalid target type '{target_type}'. Must match ^[a-z0-9_-]{{1,32}}$."
        )
    return {"type": target_type, "id": target_id}


def validate_operation_id(operation_id: str) -> str:
    """Validate operation_id format."""
    if not _OPERATION_ID_RE.match(operation_id):
        raise ProtocolValidationError(
            f"Invalid operation_id '{operation_id}'. Must match ^[A-Za-z0-9._:-]{{1,128}}$."
        )
    return operation_id


def _reject_forbidden_keys(obj: Any, *, context: str) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ProtocolValidationError(f"{context} keys must be strings.")
            if key.lower() in FORBIDDEN_CLIENT_KEYS:
                raise ProtocolValidationError(
                    f"Forbidden property '{key}' is not allowed in {context}."
                )
            _reject_forbidden_keys(value, context=f"{context}.{key}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _reject_forbidden_keys(item, context=f"{context}[{idx}]")


def load_params_file(params_file: Path) -> dict[str, Any]:
    """Load an untrusted JSON parameter object from disk."""
    if not params_file.is_file():
        raise ProtocolValidationError(f"Parameters file not found: {params_file}")
    try:
        raw_text = params_file.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolValidationError(f"Failed to parse parameters JSON '{params_file}': {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolValidationError("Parameters JSON root must be an object.")
    _reject_forbidden_keys(data, context="parameters")
    return data


def build_status_request() -> dict[str, Any]:
    """Construct a protocol v1 status request."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": "status",
    }


def build_run_request(
    *,
    capability: str,
    target_id: str,
    target_type: str = "hyperv_vm",
    mode: str = "dry_run",
    request_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a protocol v1 run request."""
    if mode not in {"dry_run", "apply"}:
        raise ProtocolValidationError(f"Invalid mode '{mode}'; expected 'dry_run' or 'apply'.")
    req_id = validate_request_id(request_id or generate_request_id())
    cap = validate_capability(capability)
    target = validate_target(target_id, target_type)
    params = parameters if parameters is not None else {}
    if not isinstance(params, dict):
        raise ProtocolValidationError("parameters must be a JSON object.")
    _reject_forbidden_keys(params, context="parameters")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": "run",
        "request_id": req_id,
        "capability": cap,
        "target": target,
        "mode": mode,
        "parameters": params,
    }


def build_result_request(operation_id: str) -> dict[str, Any]:
    """Construct a protocol v1 result lookup request."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": "result",
        "operation_id": validate_operation_id(operation_id),
    }


def build_stop_request() -> dict[str, Any]:
    """Construct an operator-only broker shutdown request."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": "shutdown",
    }
