"""Validated models for Windows user-session scheduled tasks."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Literal


SID_PATTERN = re.compile(r"^S-1-(?:[0-9]+-)*[0-9]+$", re.IGNORECASE)
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ISO_DURATION_PATTERN = re.compile(
    r"^P(?=\d|T\d)(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
)
SCHEDULER_INTERVAL_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
SID_RE = re.compile(r"S-1-(?:[0-9]+-)*[0-9]+", re.IGNORECASE)


class RuntimeLifecycleError(RuntimeError):
    """Base exception for lifecycle errors."""


class UnsupportedPlatformError(RuntimeLifecycleError):
    """Raised when a Windows-only operation is requested on another OS."""


class OwnershipConflictError(RuntimeLifecycleError):
    """Raised when an existing task cannot be proven to belong to a caller."""


class ElevationRequiredError(RuntimeLifecycleError):
    """Raised when a requested task principal requires an elevated caller."""


class TaskBackendError(RuntimeLifecycleError):
    """Raised when Task Scheduler rejects or cannot report an operation."""


@dataclass(frozen=True, slots=True)
class PreviewResult:
    action: Literal["create", "update", "noop", "conflict"]
    task_path: str
    xml: str
    diff: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ApplyResult:
    action: Literal["created", "updated", "unchanged"]
    task_path: str
    status: TaskStatus | None = None


@dataclass(frozen=True, slots=True)
class TaskStatus:
    task_path: str
    registration_state: Literal["registered", "missing", "drifted", "conflict"]
    state: str | None = None
    enabled: bool | None = None
    principal_sid: str | None = None
    logon_type: str | None = None
    run_level: str | None = None
    logged_off_capable: bool | None = None
    executable: str | None = None
    arguments: str | None = None
    working_dir: str | None = None
    last_run: str | None = None
    next_run: str | None = None
    missed_runs: int | None = None
    last_result: int | None = None
    last_result_hresult: str | None = None
    executable_exists: bool | None = None
    working_dir_exists: bool | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskSummary:
    task_path: str
    owner: str
    name: str
    state: str | None
    enabled: bool
    last_result: int | None
    last_result_hresult: str | None
    logged_off_capable: bool
    executable: str | None
    executable_exists: bool | None
    working_dir: str | None
    working_dir_exists: bool | None


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_path: str
    owner: str
    name: str
    principal_sid: str
    xml: bytes
    sha256: str
    enabled: bool


def normalize_sid(value: str) -> str:
    """Validate and normalize a Windows SID string."""
    normalized = value.strip().upper()
    if not SID_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid Windows SID: {value!r}")
    return normalized


def resolve_account_sid(value: str) -> str | None:
    """Resolve a SID or Windows account name (e.g. DOMAIN\\user) to a normalized SID."""
    stripped = value.strip()
    if not stripped:
        return None
    if SID_PATTERN.fullmatch(stripped):
        return normalize_sid(stripped)
    import os

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.LookupAccountNameW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.LookupAccountNameW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    sid_size = wintypes.DWORD(0)
    domain_size = wintypes.DWORD(0)
    sid_type = wintypes.DWORD(0)
    advapi32.LookupAccountNameW(
        None, stripped, None, ctypes.byref(sid_size), None, ctypes.byref(domain_size), ctypes.byref(sid_type)
    )
    if not sid_size.value:
        return None
    sid_buf = ctypes.create_string_buffer(sid_size.value)
    domain_buf = ctypes.create_unicode_buffer(max(1, domain_size.value))
    if not advapi32.LookupAccountNameW(
        None, stripped, sid_buf, ctypes.byref(sid_size), domain_buf, ctypes.byref(domain_size), ctypes.byref(sid_type)
    ):
        return None
    sid_ptr = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid_buf, ctypes.byref(sid_ptr)):
        return None
    try:
        return normalize_sid(sid_ptr.value) if sid_ptr.value else None
    finally:
        if sid_ptr:
            kernel32.LocalFree(ctypes.cast(sid_ptr, ctypes.c_void_p))


def current_user_sid() -> str:
    """Resolve the current account SID without third-party dependencies."""
    import os

    if os.name != "nt":
        raise UnsupportedPlatformError("Resolving a Windows user SID is supported on Windows only")
    result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise TaskBackendError(f"Could not resolve current Windows user SID: {result.stderr.strip()}")
    match = SID_RE.search(result.stdout)
    if not match:
        raise TaskBackendError("whoami.exe did not return a valid Windows user SID")
    return normalize_sid(match.group(0))


def _validate_duration(value: str, field_name: str) -> None:
    if not ISO_DURATION_PATTERN.fullmatch(value) or value in {"P", "PT"}:
        raise ValueError(f"{field_name} must be an ISO-8601 duration, got {value!r}")


def _validate_xml_text(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise ValueError(f"{field_name} contains a character that XML cannot represent")


def _validate_optional_duration(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_duration(value, field_name)


def _validate_scheduler_interval(value: str, field_name: str) -> None:
    match = SCHEDULER_INTERVAL_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"{field_name} must use days/hours/minutes/seconds only")
    seconds = (
        int(match.group("days") or 0) * 86400
        + int(match.group("hours") or 0) * 3600
        + int(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
    if not 60 <= seconds <= 31 * 86400:
        raise ValueError(f"{field_name} must be between PT1M and P31D")


@dataclass(frozen=True, slots=True)
class TaskPrincipal:
    """Scheduled task user identity and logon/run-level policy."""

    mode: Literal["current_user", "system_service"] = "current_user"
    logon_type: Literal["interactive", "service_account"] = "interactive"
    run_level: Literal["limited", "highest"] = "limited"
    sid: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"current_user", "system_service"}:
            raise ValueError("principal mode must be 'current_user' or 'system_service'")
        if self.logon_type not in {"interactive", "service_account"}:
            raise ValueError("logon_type must be 'interactive' or 'service_account'")
        if self.run_level not in {"limited", "highest"}:
            raise ValueError("run_level must be 'limited' or 'highest'")
        if self.mode == "system_service":
            if self.sid is not None and normalize_sid(self.sid) != "S-1-5-18":
                raise ValueError("system_service principal SID must be S-1-5-18")
            object.__setattr__(self, "sid", "S-1-5-18")
            if self.logon_type != "service_account":
                object.__setattr__(self, "logon_type", "service_account")
        elif self.sid is None:
            object.__setattr__(self, "sid", current_user_sid())
        else:
            object.__setattr__(self, "sid", normalize_sid(self.sid))

    @classmethod
    def current_user_limited(cls, sid: str | None = None) -> TaskPrincipal:
        """Create a standard current-user principal, resolving its SID on Windows."""
        return cls(sid=sid if sid is not None else current_user_sid())

    @classmethod
    def system(cls, *, run_level: Literal["limited", "highest"] = "highest") -> TaskPrincipal:
        """Create a LocalSystem service-account principal."""
        return cls(mode="system_service", logon_type="service_account", run_level=run_level, sid="S-1-5-18")

    @property
    def task_logon_type(self) -> str:
        return "ServiceAccount" if self.logon_type == "service_account" else "InteractiveToken"

    @property
    def task_run_level(self) -> str:
        return "HighestAvailable" if self.run_level == "highest" else "LeastPrivilege"


@dataclass(frozen=True, slots=True)
class LogonTrigger:
    delay: str | None = "PT5S"
    user_id: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_duration(self.delay, "logon delay")
        if self.user_id is not None:
            object.__setattr__(self, "user_id", normalize_sid(self.user_id))


@dataclass(frozen=True, slots=True)
class BootTrigger:
    delay: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_duration(self.delay, "boot delay")


@dataclass(frozen=True, slots=True)
class RepeatingIntervalTrigger:
    interval: str
    start_boundary: str = "2020-01-01T00:00:00"
    duration: str | None = None

    def __post_init__(self) -> None:
        _validate_duration(self.interval, "repetition interval")
        _validate_scheduler_interval(self.interval, "repetition interval")
        _validate_optional_duration(self.duration, "repetition duration")
        if self.duration is not None:
            _validate_scheduler_interval(self.duration, "repetition duration")
        try:
            datetime.fromisoformat(self.start_boundary)
        except ValueError as exc:
            raise ValueError("start_boundary must be an ISO-8601 date/time") from exc


@dataclass(frozen=True, slots=True)
class CalendarTrigger:
    schedule: Literal["once", "daily", "weekly", "monthly"]
    start_time: str = "02:00"
    interval: int = 1
    days_of_week: tuple[str, ...] = ()
    days_of_month: tuple[int, ...] = ()
    months: tuple[int, ...] = ()
    start_date: str = "2020-01-01"

    def __post_init__(self) -> None:
        object.__setattr__(self, "days_of_week", tuple(self.days_of_week))
        object.__setattr__(self, "days_of_month", tuple(self.days_of_month))
        object.__setattr__(self, "months", tuple(self.months))
        if self.schedule not in {"once", "daily", "weekly", "monthly"}:
            raise ValueError("calendar schedule must be once, daily, weekly, or monthly")
        if self.interval < 1:
            raise ValueError("calendar interval must be at least 1")
        try:
            time.fromisoformat(self.start_time)
            date.fromisoformat(self.start_date)
        except ValueError as exc:
            raise ValueError("calendar start_time/start_date must be valid ISO date/time values") from exc
        valid_days = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}
        if any(day not in valid_days for day in self.days_of_week):
            raise ValueError("days_of_week contains an invalid weekday")
        if any(day < 1 or day > 31 for day in self.days_of_month):
            raise ValueError("days_of_month values must be between 1 and 31")
        if any(month < 1 or month > 12 for month in self.months):
            raise ValueError("months values must be between 1 and 12")
        if self.schedule == "weekly" and not self.days_of_week:
            raise ValueError("weekly calendar triggers require at least one weekday")
        if self.schedule == "monthly" and not self.days_of_month:
            raise ValueError("monthly calendar triggers require at least one day of month")


Trigger = LogonTrigger | BootTrigger | RepeatingIntervalTrigger | CalendarTrigger


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Complete, immutable desired state for one scheduled task."""

    owner: str
    name: str
    executable: Path
    args: tuple[str, ...] = ()
    working_dir: Path | None = None
    triggers: tuple[Trigger, ...] = field(default_factory=tuple)
    principal: TaskPrincipal = field(default_factory=TaskPrincipal.current_user_limited)
    folder: str = "\\Scripts"
    task_name_override: str | None = None
    hidden: bool = True
    execution_time_limit: str = "PT2M"
    multiple_instances: Literal["Parallel", "Queue", "IgnoreNew", "StopExisting"] = "IgnoreNew"
    allow_on_battery: bool = True
    start_when_available: bool = True
    wake_to_run: bool = False
    restart_count: int = 0
    restart_interval: str = "PT1M"
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "triggers", tuple(self.triggers))
        if not IDENTIFIER_PATTERN.fullmatch(self.owner):
            raise ValueError("owner must use lowercase ASCII letters, digits, hyphens, or underscores")
        if not IDENTIFIER_PATTERN.fullmatch(self.name):
            raise ValueError("name must use lowercase ASCII letters, digits, hyphens, or underscores")
        executable = Path(self.executable)
        if not executable.is_absolute():
            raise ValueError("executable path must be absolute")
        if len(str(executable)) > 260:
            raise ValueError("executable path exceeds Task Scheduler's 260-character path limit")
        _validate_xml_text(str(executable), "executable")
        object.__setattr__(self, "executable", executable)
        if self.working_dir is None:
            raise ValueError("working_dir must be an explicit absolute directory")
        working_dir = Path(self.working_dir)
        if not working_dir.is_absolute():
            raise ValueError("working_dir path must be absolute")
        if len(str(working_dir)) > 260:
            raise ValueError("working_dir path exceeds Task Scheduler's 260-character path limit")
        _validate_xml_text(str(working_dir), "working_dir")
        object.__setattr__(self, "working_dir", working_dir)
        if not self.triggers:
            raise ValueError("at least one task trigger is required")
        if any(
            not isinstance(trigger, (LogonTrigger, BootTrigger, RepeatingIntervalTrigger, CalendarTrigger))
            for trigger in self.triggers
        ):
            raise ValueError("triggers contain an unsupported trigger type")
        if self.multiple_instances not in {"Parallel", "Queue", "IgnoreNew", "StopExisting"}:
            raise ValueError("multiple_instances has an unsupported value")
        if not isinstance(self.restart_count, int) or self.restart_count < 0:
            raise ValueError("restart_count must be a non-negative integer")
        _validate_duration(self.execution_time_limit, "execution_time_limit")
        _validate_duration(self.restart_interval, "restart_interval")
        if self.restart_count:
            _validate_scheduler_interval(self.restart_interval, "restart_interval")
        if not self.folder.casefold().startswith("\\scripts") or self.folder.endswith("\\"):
            raise ValueError("folder must be under \\Scripts and have no trailing slash")
        _validate_xml_text(self.folder, "folder")
        if self.folder.casefold() != "\\scripts" and not self.folder.casefold().startswith("\\scripts\\"):
            raise ValueError("folder must be under \\Scripts")
        if any(part in {"", ".", ".."} for part in self.folder.lstrip("\\").split("\\")):
            raise ValueError("folder must not contain empty, current-directory, or parent-directory segments")
        if any(any(char in part for char in ':*?"<>|/') for part in self.folder.lstrip("\\").split("\\")):
            raise ValueError("folder contains an invalid Task Scheduler name character")
        if self.task_name_override is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_. -]*", self.task_name_override
        ):
            raise ValueError("task_name_override contains invalid Task Scheduler name characters")
        if any(not isinstance(arg, str) for arg in self.args):
            raise ValueError("task arguments must be strings")
        for arg in self.args:
            _validate_xml_text(arg, "task argument")
        _validate_xml_text(self.description, "description")

    @property
    def task_name(self) -> str:
        return self.task_name_override or f"{self.owner}-{self.name}"

    @property
    def task_path(self) -> str:
        return f"{self.folder}\\{self.task_name}"

    @property
    def principal_sid(self) -> str:
        if self.principal.sid is None:
            raise ValueError("principal SID has not been resolved")
        return self.principal.sid

    def canonical_data(self) -> dict[str, object]:
        """Return normalized semantic fields used for hashing."""
        value = asdict(self)
        value.pop("description", None)

        def normalize(item: object) -> object:
            if isinstance(item, Path):
                return str(item).replace("/", "\\")
            if is_dataclass(item):
                return {key: normalize(val) for key, val in asdict(item).items()}
            if isinstance(item, (tuple, list)):
                return [normalize(val) for val in item]
            if isinstance(item, dict):
                return {key: normalize(val) for key, val in sorted(item.items())}
            return item

        return normalize(value)  # type: ignore[return-value]
