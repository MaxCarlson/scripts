"""ProcWatch: Windows 11 live console/terminal popup guard and process catcher."""

__version__ = "0.2.0"

from procwatch.config import GuardMode, ProcWatchConfig
from procwatch.models import (
    CandidateInitiator,
    CapabilityFlags,
    CollectorStats,
    GuardDecision,
    LiveIncidentEvent,
    MissingMetadataReason,
    ProcessIdentity,
    ProcessObservation,
    WindowObservation,
    WindowState,
)

__all__ = [
    "__version__",
    "CandidateInitiator",
    "CapabilityFlags",
    "CollectorStats",
    "GuardDecision",
    "GuardMode",
    "LiveIncidentEvent",
    "MissingMetadataReason",
    "ProcessIdentity",
    "ProcessObservation",
    "ProcWatchConfig",
    "WindowObservation",
    "WindowState",
]
