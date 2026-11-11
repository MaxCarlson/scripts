"""Canonical state fingerprinting, argument digests, and data redaction."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional


def compute_arguments_digest(args: Optional[Dict[str, Any]]) -> str:
    """Compute a canonical SHA-256 digest of action parameters."""
    normalized = json.dumps(args or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_rc_fingerprint(observation: Optional[Dict[str, Any]]) -> str:
    """Compute a canonical SHA-256 fingerprint of Resource Coordinator source state.

    Binds to status, contract, recovery requirements, inhibition state/reason,
    active/pending claims, and observation timestamp.
    """
    if not observation:
        return hashlib.sha256(b"rc:unavailable").hexdigest()

    canon = {
        "status": observation.get("status", "unknown"),
        "contract_version": observation.get("contract_version", "unknown"),
        "recovery_required": observation.get("recovery_required"),
        "inhibition_active": observation.get("inhibition_active"),
        "inhibition_reason": observation.get("inhibition_reason"),
        "active_request_id": observation.get("active_request_id"),
        "journal_status": observation.get("journal_status"),
        "observed_at": observation.get("observed_at"),
    }
    raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_incident_fingerprint(incident: Optional[Dict[str, Any]]) -> str:
    """Compute a canonical SHA-256 fingerprint of a notification incident."""
    if not incident:
        return hashlib.sha256(b"incident:absent").hexdigest()

    canon = {
        "incident_id": incident.get("incident_id"),
        "status": incident.get("status"),
        "occurrence_count": incident.get("occurrence_count", 1),
        "last_occurred_at": incident.get("last_occurred_at"),
    }
    raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def redact_sensitive_data(val: Any) -> Any:
    """Recursively scrub bearer tokens, secrets, passwords, and file paths from payloads."""
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            k_lower = k.lower()
            if any(s in k_lower for s in ("token", "secret", "password", "totp", "auth_header", "cookie")):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned

    if isinstance(val, list):
        return [redact_sensitive_data(i) for i in val]

    if isinstance(val, str):
        # Redact Bearer tokens
        s = re.sub(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", val)
        # Redact TOTP codes (6 digits standalone)
        s = re.sub(r"\b\d{6}\b", "[REDACTED_OTP]", s)
        # Redact Windows local user paths
        s = re.sub(r"(?i)c:\\users\\[^\\]+\\", "C:\\Users\\[REDACTED_USER]\\", s)
        return s

    return val
