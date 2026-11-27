"""GUI-Agent Session Continuity Module."""

from __future__ import annotations

__version__ = "2.3.0"

from .dispatcher import DispatcherService
from .errors import ContinuityError, ErrorCode
from .models import (
    AssociationRecord,
    AssociationStatus,
    EnvironmentInfo,
    EventEnvelope,
    EventType,
    EvidenceLevel,
    GuiConversation,
    Provider,
    RuntimeKind,
    SessionLifecycleStatus,
    SessionRecord,
    Workflow,
    WorkflowStatus,
)
from .service import ContinuityService, MutationPreview

__all__ = [
    "__version__",
    "AssociationRecord",
    "AssociationStatus",
    "ContinuityError",
    "ContinuityService",
    "DispatcherService",
    "EnvironmentInfo",
    "ErrorCode",
    "EventEnvelope",
    "EventType",
    "EvidenceLevel",
    "GuiConversation",
    "MutationPreview",
    "Provider",
    "RuntimeKind",
    "SessionLifecycleStatus",
    "SessionRecord",
    "Workflow",
    "WorkflowStatus",
]
