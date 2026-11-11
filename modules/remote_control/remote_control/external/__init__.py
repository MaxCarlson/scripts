"""Tailscale Funnel lifecycle management, preflight diagnostics, and barrier reconciliation."""

from __future__ import annotations

from remote_control.external.client import (
    SimulatedTailscaleClient,
    TailscaleClientProtocol,
    TailscaleStatus,
    get_tailscale_client,
)
from remote_control.external.doctor import ExternalDoctor
from remote_control.external.service import ExternalExposureService

__all__ = [
    "ExternalDoctor",
    "ExternalExposureService",
    "SimulatedTailscaleClient",
    "TailscaleClientProtocol",
    "TailscaleStatus",
    "get_tailscale_client",
]
