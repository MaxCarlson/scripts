"""Typed failures raised while validating or submitting terminal launch plans."""


class TerminalLauncherError(Exception):
    """Base class for terminal launcher failures."""


class InvalidPlanError(TerminalLauncherError, ValueError):
    """The supplied plan is malformed for the selected backend."""


class UnsupportedPlatformError(TerminalLauncherError):
    """The selected terminal backend cannot run on this platform."""


class TerminalNotFoundError(TerminalLauncherError, FileNotFoundError):
    """The requested terminal executable could not be located."""


class UnsupportedLayoutError(TerminalLauncherError):
    """The backend cannot represent the requested pane layout."""
