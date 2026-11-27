"""vm_lab — Reusable Hyper-V disposable Windows VM lab manager and workflow CLI."""

from __future__ import annotations

from vm_lab.backend import BackendAdapter, resolve_backend_root, resolve_powershell_exe
from vm_lab.exceptions import (
    BackendExecutionError,
    BackendResourceError,
    PowerShellNotFoundError,
    UnsupportedPlatformError,
    VmLabError,
)
from vm_lab.results import BackendResult, classify_exit_code, redact_sensitive

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "BackendAdapter",
    "BackendResult",
    "BackendExecutionError",
    "BackendResourceError",
    "PowerShellNotFoundError",
    "UnsupportedPlatformError",
    "VmLabError",
    "classify_exit_code",
    "redact_sensitive",
    "resolve_backend_root",
    "resolve_powershell_exe",
]
