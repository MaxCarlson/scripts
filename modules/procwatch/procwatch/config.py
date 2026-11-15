"""Configuration models, defaults, and path helpers for ProcWatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re


class GuardMode(StrEnum):
    """Supported window guard operating modes."""

    OBSERVE = "observe"
    SMART = "smart"
    ALL_CONSOLES = "all-consoles"
    ALL_WINDOWS = "all-windows"


CONSOLE_WINDOW_CLASSES: frozenset[str] = frozenset(
    {
        "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
        "ConsoleWindowClass",  # Classic conhost.exe / OpenConsole
    }
)

DEFAULT_AUTOMATION_TITLE_PATTERN = (
    r"(\.venv\\Scripts\\|pythonw?3?\.exe|pwsh\.exe|powershell\.exe|cmd\.exe|conhost\.exe|node\.exe|wsl\.exe)"
)

DEFAULT_INTERACTIVE_TITLE_PATTERN = (
    r"^(Windows PowerShell|PowerShell \d|Command Prompt|Developer Command Prompt|Developer PowerShell|Ubuntu|Debian)"
)

DEFAULT_DATA_DIR_ENV = "PROCWATCH_DATA_DIR"
DEFAULT_MUTEX_NAME = r"Local\ProcWatchCollectorMutex"


class ConfigValidationError(ValueError):
    """Raised when configuration values fail validation."""


def get_data_dir(override: Path | str | None = None) -> Path:
    """Return the per-user ProcWatch data directory."""
    if override is not None:
        return Path(override).expanduser().resolve()
    env_dir = os.environ.get(DEFAULT_DATA_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return (Path.home() / ".procwatch").resolve()


def compile_optional_regex(pattern: str | None, *, flags: int = re.IGNORECASE) -> re.Pattern[str] | None:
    """Compile a regex string, raising ConfigValidationError on invalid syntax."""
    if pattern is None or pattern == "":
        return None
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise ConfigValidationError(f"Invalid regular expression {pattern!r}: {exc}") from exc


@dataclass(slots=True)
class GuardConfig:
    """Configuration for the NeutralizeEngine window guard."""

    mode: GuardMode = GuardMode.OBSERVE
    restore_focus: bool = True
    title_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(DEFAULT_AUTOMATION_TITLE_PATTERN, re.IGNORECASE)
    )
    exclude_pattern: re.Pattern[str] | None = None
    interactive_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(DEFAULT_INTERACTIVE_TITLE_PATTERN, re.IGNORECASE)
    )
    suppress_window_seconds: float = 0.6
    allow_all_windows_experimental: bool = False
    quiet: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.mode, GuardMode):
            self.mode = GuardMode(str(self.mode))
        if self.mode == GuardMode.ALL_WINDOWS and not self.allow_all_windows_experimental:
            raise ConfigValidationError(
                "Mode 'all-windows' is experimental/unsafe and requires explicit opt-in."
            )
        if self.suppress_window_seconds <= 0 or self.suppress_window_seconds > 10.0:
            raise ConfigValidationError(
                f"suppress_window_seconds must be in (0, 10.0], got {self.suppress_window_seconds}."
            )


@dataclass(slots=True)
class WatchConfig:
    """Configuration for live `procwatch watch` observation and correlation."""

    popups_only: bool = False
    guard_windows: bool = False
    guard_mode: GuardMode = GuardMode.OBSERVE
    collapse_bursts: bool = False
    show_headless: bool = False
    filter_regex: re.Pattern[str] | None = None
    output_file: Path | None = None
    correlation_window_ms: float = 1500.0
    event_queue_maxsize: int = 4096
    process_cache_max_entries: int = 8192
    process_cache_ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not isinstance(self.guard_mode, GuardMode):
            self.guard_mode = GuardMode(str(self.guard_mode))
        if self.correlation_window_ms <= 0:
            raise ConfigValidationError("correlation_window_ms must be positive.")
        if self.event_queue_maxsize < 16:
            raise ConfigValidationError("event_queue_maxsize must be at least 16.")
        if self.process_cache_max_entries < 64:
            raise ConfigValidationError("process_cache_max_entries must be at least 64.")


@dataclass(slots=True)
class StorageConfig:
    """Configuration for SQLite WAL flight recorder persistence and retention."""

    db_path: Path | None = None
    max_age_days: int = 14
    max_size_mb: int = 256
    busy_timeout_ms: int = 5000

    def __post_init__(self) -> None:
        if self.max_age_days < 1:
            raise ConfigValidationError("max_age_days must be at least 1.")
        if self.max_size_mb < 1:
            raise ConfigValidationError("max_size_mb must be at least 1.")
        if self.busy_timeout_ms < 100:
            raise ConfigValidationError("busy_timeout_ms must be at least 100.")

    def resolved_db_path(self, data_dir: Path) -> Path:
        if self.db_path is not None:
            return Path(self.db_path).expanduser().resolve()
        return (data_dir / "events.db").resolve()


@dataclass(slots=True)
class ProcWatchConfig:
    """Top-level configuration container."""

    data_dir: Path = field(default_factory=get_data_dir)
    guard: GuardConfig = field(default_factory=GuardConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    mutex_name: str = DEFAULT_MUTEX_NAME
    max_decoded_bytes: int = 16384
    max_decode_depth: int = 3
