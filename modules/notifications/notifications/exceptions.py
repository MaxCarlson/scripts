"""Exception classes for the notifications module."""

from __future__ import annotations


class NotificationError(Exception):
    """Base exception for all notification-related errors."""


class ValidationError(NotificationError):
    """Raised when an event or model fails validation."""


class UnsupportedSchemaVersionError(ValidationError):
    """Raised when an event envelope has an unsupported schema version."""


class PayloadConflictError(NotificationError):
    """Raised when a reused event_id has conflicting payload content."""


class StorageError(NotificationError):
    """Base exception for database and persistence errors."""


class DatabaseBusyError(StorageError):
    """Raised when the SQLite database is locked or busy."""


class DatabaseFullError(StorageError):
    """Raised when the database disk or quota is exhausted."""


class DatabaseCorruptError(StorageError):
    """Raised when SQLite reports database corruption."""


class IncidentNotFoundError(NotificationError):
    """Raised when an incident ID cannot be found."""


class BrokerUnavailableError(NotificationError):
    """Raised when the notification broker is unreachable or offline."""


class AuthenticationError(NotificationError):
    """Raised when client authentication fails."""


class SecurityError(NotificationError):
    """Raised when file permissions or credential security restrictions fail."""


class InvalidTransitionError(NotificationError):
    """Raised when an illegal incident state transition is attempted."""


class ProviderError(NotificationError):
    """Base exception for delivery provider errors."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when an operation requires an unconfigured provider."""
