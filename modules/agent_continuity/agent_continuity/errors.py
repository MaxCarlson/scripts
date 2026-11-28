"""Structured error taxonomy for agent_continuity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ErrorCode:
    """Canonical error codes aligned with Master Plan §12.8."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_VERSION_UNSUPPORTED = "provider_version_unsupported"
    HOOKS_MISSING = "hooks_missing"
    HOOKS_UNTRUSTED = "hooks_untrusted"
    HOOK_SCHEMA_MISMATCH = "hook_schema_mismatch"
    METADATA_INACCESSIBLE = "metadata_inaccessible"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_ORPHANED = "session_orphaned"
    ASSOCIATION_UNKNOWN = "association_unknown"
    ASSOCIATION_CONFLICT = "association_conflict"
    RESUME_UNSUPPORTED = "resume_unsupported"
    EVENT_SPOOL_UNAVAILABLE = "event_spool_unavailable"
    MATERIALIZER_FAILED = "materializer_failed"
    REGISTRY_REBUILD_REQUIRED = "registry_rebuild_required"
    REGISTRY_UPGRADE_BLOCKED = "registry_upgrade_blocked"
    CROSS_ENVIRONMENT_UNAVAILABLE = "cross_environment_unavailable"

    INVALID_INPUT = "invalid_input"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    WORKFLOW_ALREADY_EXISTS = "workflow_already_exists"
    ENVIRONMENT_AMBIGUOUS = "environment_ambiguous"
    ENVIRONMENT_NOT_FOUND = "environment_not_found"


@dataclass
class ContinuityError(Exception):
    """Structured exception carrying an error code, user message, and optional context."""

    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 1

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }
