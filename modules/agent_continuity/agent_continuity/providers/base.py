"""Provider-neutral adapter contract for native coding-agent integrations."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..hooks import NormalizedHookEvent


@dataclass(slots=True)
class ProviderInstallation:
    """Detected executable and native metadata directory state."""

    provider: str
    installed: bool
    runnable: bool
    executable_path: str | None
    version: str | None
    native_home: str | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderCapabilities:
    """Explicit capability report for a provider adapter."""

    provider: str
    phase: str
    install_detection: bool = True
    resume_command_generation: bool = True
    hook_event_normalization: bool = False
    hook_installation: bool = False
    session_discovery: bool = False
    history_scan: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResumePlan:
    """Constructed native resume command (never executed automatically)."""

    provider: str
    native_session_id: str
    environment_id: str
    argv: list[str]
    cwd: str | None
    display_command: str
    supported: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderHealth:
    """Diagnostic health summary for one provider."""

    provider: str
    status: str  # ready_manual | unavailable | degraded
    installation: ProviderInstallation
    capabilities: ProviderCapabilities
    error_code: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "installation": self.installation.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "error_code": self.error_code,
            "message": self.message,
        }


class ProviderAdapter(ABC):
    """Abstract base class isolating provider-specific CLI and storage details."""

    provider_name: str

    def find_executable(self) -> str | None:
        """Resolve the provider path without running it (safe for previews and tests)."""
        return shutil.which(self.provider_name)

    @abstractmethod
    def detect_installation(self) -> ProviderInstallation:
        """Inspect executable presence, runnability, and native store path without modifying config."""

    def get_version(self) -> str | None:
        """Return detected provider version string or None."""
        return self.detect_installation().version

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Report explicitly supported and unsupported capabilities."""

    def normalize_hook_event(
        self,
        raw_event: dict[str, Any],
        *,
        environment_id: str,
        observed_timestamp: str | None = None,
        event_name_hint: str | None = None,
    ) -> NormalizedHookEvent:
        """Normalize a native hook payload into a NormalizedHookEvent."""
        raise NotImplementedError(f"{self.provider_name} hook normalization is not implemented.")

    def safe_hook_response(self, normalized: NormalizedHookEvent | None = None) -> dict[str, Any]:
        """Return the provider-safe stdout JSON response for a telemetry hook."""
        return {}

    def discover_sessions(self) -> list[dict[str, Any]]:
        """Discover native sessions read-only (deferred to Phase 2/3)."""
        return []

    def get_session_metadata(self, native_session_id: str) -> dict[str, Any] | None:
        """Read bounded metadata for a single native session (deferred to Phase 2/3)."""
        return None

    def scan_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Bounded historical scan (deferred to Phase 3)."""
        return []

    @abstractmethod
    def resolve_resume_command(
        self,
        native_session_id: str,
        *,
        cwd: str | None = None,
        environment_id: str = "",
        runtime_kind: str = "",
        native_args: Sequence[str] = (),
    ) -> ResumePlan:
        """Construct a verified native resume command array without executing it."""

    def get_health_status(self) -> ProviderHealth:
        """Return structured health diagnostics for this provider."""
        install = self.detect_installation()
        caps = self.get_capabilities()
        if not install.installed:
            return ProviderHealth(
                provider=self.provider_name,
                status="unavailable",
                installation=install,
                capabilities=caps,
                error_code="provider_unavailable",
                message=install.detail or f"{self.provider_name} executable not found on PATH.",
            )
        if not install.runnable:
            return ProviderHealth(
                provider=self.provider_name,
                status="degraded",
                installation=install,
                capabilities=caps,
                error_code="provider_unavailable",
                message=install.detail or f"{self.provider_name} executable found but failed version probe.",
            )
        return ProviderHealth(
            provider=self.provider_name,
            status="ready_manual",
            installation=install,
            capabilities=caps,
            message="Executable verified; manual linking and resume command generation available (hooks deferred to Phase 2).",
        )
