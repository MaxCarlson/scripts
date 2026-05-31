from __future__ import annotations


class DriveManagerError(Exception):
    """Base exception for drive-manager."""


class BackendError(DriveManagerError):
    """Raised when a platform backend cannot complete an operation."""


class DiskNotFoundError(DriveManagerError):
    """Raised when a requested disk cannot be found."""


class SafetyRefusalError(DriveManagerError):
    """Raised when the safety policy refuses an operation."""


class ConfirmationError(DriveManagerError):
    """Raised when required typed confirmation fails."""
