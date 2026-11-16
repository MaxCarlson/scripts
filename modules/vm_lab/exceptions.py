"""Typed exceptions and exit-code taxonomy for vm_lab."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INPUT_ERROR = 2
EXIT_AUTH_REQUIRED = 3
EXIT_INTERACTION_REQUIRED = 4
EXIT_INCOMPLETE = 5
EXIT_UNSUPPORTED_PLATFORM = 6


class VmLabError(Exception):
    """Base exception for vm_lab Python wrapper errors."""

    exit_code: int = EXIT_ERROR

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class UnsupportedPlatformError(VmLabError):
    """Raised when a Windows/Hyper-V-only operation is invoked on a non-Windows host."""

    exit_code = EXIT_UNSUPPORTED_PLATFORM


class PowerShellNotFoundError(VmLabError):
    """Raised when PowerShell 7 (pwsh) cannot be located."""

    exit_code = EXIT_ERROR


class BackendResourceError(VmLabError):
    """Raised when packaged PowerShell backend files cannot be resolved."""

    exit_code = EXIT_ERROR


class BackendExecutionError(VmLabError):
    """Raised when the PowerShell backend fails or returns malformed output."""

    exit_code = EXIT_ERROR
