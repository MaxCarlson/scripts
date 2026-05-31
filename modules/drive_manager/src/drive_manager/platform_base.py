from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .models import DependencyReport, DiskInfo, OperationResult, PartitionInfo


class PlatformBackend(ABC):
    name: str

    @abstractmethod
    def list_disks(self) -> list[DiskInfo]:
        raise NotImplementedError

    @abstractmethod
    def get_disk(self, disk_id: str) -> DiskInfo:
        raise NotImplementedError

    def list_usb_disks(self) -> list[DiskInfo]:
        return [disk for disk in self.list_disks() if disk.is_usb or disk.is_removable]

    def list_volumes(self) -> list[PartitionInfo]:
        volumes: list[PartitionInfo] = []
        for disk in self.list_disks():
            volumes.extend(disk.partitions)
        return volumes

    @abstractmethod
    def get_os_disk_id(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def doctor_dependencies(self) -> DependencyReport:
        raise NotImplementedError

    @abstractmethod
    def build_restore_normal_steps(self, disk: DiskInfo, filesystem: str, label: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def restore_normal(self, disk: DiskInfo, filesystem: str, label: str) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def clear_disk(self, disk: DiskInfo) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def unmount_disk(self, disk: DiskInfo) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def eject_disk(self, disk: DiskInfo) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def reset_usb_device(self, disk: DiskInfo) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def rescan(self) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def raw_device_path(self, disk: DiskInfo) -> Path:
        raise NotImplementedError

    @abstractmethod
    def health_summary(self) -> OperationResult:
        raise NotImplementedError

    @abstractmethod
    def health_smart(self, disk: DiskInfo | None = None) -> OperationResult:
        raise NotImplementedError

    def mount_image(self, image_path: Path, drive_letter: str | None = None) -> OperationResult:
        raise NotImplementedError("Image mounting not supported on this platform.")

    def dismount_image(self, image_path: Path) -> OperationResult:
        raise NotImplementedError("Image dismounting not supported on this platform.")

    def list_mounted_images(self) -> list[dict[str, Any]]:
        return []
