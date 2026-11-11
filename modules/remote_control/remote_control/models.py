"""Data models and schemas for remote control service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class OperatorModel:
    operator_id: str
    username: str
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "username": self.username,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SessionModel:
    session_id: str
    operator_id: str
    device_id: str
    csrf_token: str
    created_at: str
    expires_at: str
    last_seen_at: str
    revoked_at: Optional[str] = None
    user_agent: str = ""
    ip_address: str = ""

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return self.expires_at > now_iso

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "device_id": self.device_id,
            "csrf_token": self.csrf_token,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
            "revoked_at": self.revoked_at,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class DeviceModel:
    device_id: str
    operator_id: str
    device_name: str
    first_seen_at: str
    last_seen_at: str
    is_revoked: bool = False
    revoked_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "operator_id": self.operator_id,
            "device_name": self.device_name,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "is_revoked": self.is_revoked,
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str
    actor_id: str
    action: str
    decision: str  # "allow", "deny", "error"
    ip_address: str = ""
    device_id: Optional[str] = None
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "actor_id": self.actor_id,
            "device_id": self.device_id,
            "action": self.action,
            "decision": self.decision,
            "ip_address": self.ip_address,
            "details": self.details,
        }
