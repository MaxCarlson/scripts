"""Provider adapter registry."""

from __future__ import annotations

from .agy import AgyAdapter
from .base import ProviderAdapter, ProviderCapabilities, ProviderHealth, ProviderInstallation, ResumePlan
from .claude import ClaudeAdapter
from .codex import CodexAdapter


def default_adapters() -> dict[str, ProviderAdapter]:
    """Return the default Phase 1 provider adapters keyed by provider name."""
    return {
        "codex": CodexAdapter(),
        "agy": AgyAdapter(),
        "claude": ClaudeAdapter(),
    }


__all__ = [
    "AgyAdapter",
    "CodexAdapter",
    "ClaudeAdapter",
    "ProviderAdapter",
    "ProviderCapabilities",
    "ProviderHealth",
    "ProviderInstallation",
    "ResumePlan",
    "default_adapters",
]
