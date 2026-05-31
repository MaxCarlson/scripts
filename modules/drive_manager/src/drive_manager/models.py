from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class OperationKind(str, Enum):
    READ_ONLY = "read-only"
    FORMAT = "format"
    WIPE = "wipe"
    IMAGE_WRITE = "image-write"
    RESTORE = "restore"
    MOUNT = "mount"
    UNMOUNT = "unmount"
    USB_RESET = "usb-reset"
    HEALTH = "health"


class Severity(str, Enum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    REFUSED = "refused"


@dataclass(frozen=True)
class VolumeInfo:
    drive_letter: str | None = None
    mount_point: str | None = None
    label: str | None = None
    filesystem: str | None = None
    size_bytes: int | None = None
    size_remaining_bytes: int | None = None
    health_status: str | None = None

    def display_id(self) -> str:
        if self.drive_letter:
            return f"{self.drive_letter}:"
        return self.mount_point or ""


@dataclass(frozen=True)
class PartitionInfo:
    partition_id: str
    disk_id: str
    number: int | None = None
    path: str | None = None
    size_bytes: int | None = None
    offset_bytes: int | None = None
    type_name: str | None = None
    filesystem: str | None = None
    label: str | None = None
    drive_letter: str | None = None
    mount_points: list[str] = field(default_factory=list)
    is_boot: bool = False
    is_system: bool = False
    is_read_only: bool = False
    is_mounted: bool = False
    volume: VolumeInfo | None = None


@dataclass(frozen=True)
class DiskInfo:
    disk_id: str
    number: int | None = None
    path: str | None = None
    friendly_name: str | None = None
    model: str | None = None
    vendor: str | None = None
    serial_number: str | None = None
    bus_type: str | None = None
    media_type: str | None = None
    size_bytes: int = 0
    partition_style: str | None = None
    operational_status: str | None = None
    health_status: str | None = None
    is_usb: bool = False
    is_removable: bool = False
    is_system_disk: bool = False
    is_boot_disk: bool = False
    is_offline: bool = False
    is_read_only: bool = False
    is_virtual: bool = False
    partitions: list[PartitionInfo] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def name_for_confirmation(self) -> str:
        return self.friendly_name or self.model or self.path or self.disk_id

    @property
    def display_size(self) -> str:
        return format_bytes_binary(self.size_bytes)

    @property
    def drive_letters(self) -> list[str]:
        letters: list[str] = []
        for partition in self.partitions:
            if partition.drive_letter:
                letters.append(partition.drive_letter.rstrip(":"))
            if partition.volume and partition.volume.drive_letter:
                letters.append(partition.volume.drive_letter.rstrip(":"))
        return sorted(set(letters))

    @property
    def mount_points(self) -> list[str]:
        points: list[str] = []
        for partition in self.partitions:
            points.extend(partition.mount_points)
            if partition.volume and partition.volume.mount_point:
                points.append(partition.volume.mount_point)
        return sorted(set(p for p in points if p))


@dataclass(frozen=True)
class UsbDiagnosis:
    disk_id: str
    diagnosis: str
    severity: Severity
    evidence: list[str]
    likely_causes: list[str]
    recommended_actions: list[str]
    is_probably_bad: bool = False


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    available: bool
    required_for: str
    path: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class DependencyReport:
    platform: str
    checks: list[DependencyCheck]

    @property
    def missing_required(self) -> list[DependencyCheck]:
        return [c for c in self.checks if not c.available and c.required_for.lower().startswith("required")]


@dataclass(frozen=True)
class OperationPlan:
    kind: OperationKind
    title: str
    target_disk: DiskInfo | None = None
    target_partition: PartitionInfo | None = None
    image_path: Path | None = None
    image_url: str | None = None
    filesystem: str | None = None
    label: str | None = None
    verify: bool = False
    force_unmount: bool = False
    steps: list[str] = field(default_factory=list)
    destructive: bool = False
    writes_raw_disk: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    dry_run: bool
    refused_reasons: list[str]
    warnings: list[str]
    required_confirmations: list[str]


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    dry_run: bool
    message: str
    steps: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def format_bytes_binary(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    n = float(max(0, int(size_bytes)))
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024
        idx += 1
    if idx == 0:
        return f"{int(n)} B"
    return f"{n:.2f} {units[idx]}"


def dataclass_to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [dataclass_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: dataclass_to_dict(v) for k, v in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value
