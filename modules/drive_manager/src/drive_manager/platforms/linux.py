from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from drive_manager.compat import SystemUtils
from drive_manager.errors import BackendError, DiskNotFoundError
from drive_manager.models import DependencyCheck, DependencyReport, DiskInfo, OperationResult, PartitionInfo, VolumeInfo
from drive_manager.platform_base import PlatformBackend


class LinuxBackend(PlatformBackend):
    name = "linux"

    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds
        self.sysu = SystemUtils()

    def _run(self, args: list[str], *, timeout_seconds: int | None = None, sudo: bool = False) -> str:
        command = list(args)
        if sudo:
            command.insert(0, "sudo")
        cp = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds or self.timeout_seconds,
        )
        if cp.returncode != 0:
            raise BackendError(f"Command failed ({cp.returncode}): {' '.join(command)}\n{cp.stderr.strip()}")
        return cp.stdout.strip()

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _child_list(node: dict[str, Any]) -> list[dict[str, Any]]:
        children = node.get("children")
        if isinstance(children, list):
            return children
        return []

    def _root_source(self) -> str | None:
        try:
            out = self._run(["findmnt", "-no", "SOURCE", "/"], timeout_seconds=10)
            return out.splitlines()[0].strip() if out else None
        except Exception:
            return None

    def _parent_disk_for_source(self, source: str | None) -> str | None:
        if not source:
            return None
        path = source
        if path.startswith("/dev/mapper/"):
            try:
                out = self._run(["lsblk", "-no", "PKNAME", path], timeout_seconds=10)
                if out.strip():
                    return "/dev/" + out.strip().splitlines()[0]
            except Exception:
                return None
        try:
            out = self._run(["lsblk", "-no", "PKNAME", path], timeout_seconds=10)
            if out.strip():
                return "/dev/" + out.strip().splitlines()[0]
        except Exception:
            pass
        return path

    def _disk_from_node(self, node: dict[str, Any], os_disk_path: str | None) -> DiskInfo:
        path = str(node.get("path") or f"/dev/{node.get('name')}")
        children = self._child_list(node)
        partitions: list[PartitionInfo] = []
        for idx, child in enumerate(children, start=1):
            if child.get("type") not in ("part", "crypt", "lvm", "rom"):
                continue
            mount_points = []
            mps = child.get("mountpoints")
            if isinstance(mps, list):
                mount_points = [str(mp) for mp in mps if mp]
            elif child.get("mountpoint"):
                mount_points = [str(child.get("mountpoint"))]
            volume = VolumeInfo(
                drive_letter=None,
                mount_point=mount_points[0] if mount_points else None,
                label=child.get("label"),
                filesystem=child.get("fstype"),
                size_bytes=self._to_int(child.get("size")),
            )
            partitions.append(
                PartitionInfo(
                    partition_id=str(child.get("path") or child.get("name") or f"{path}{idx}"),
                    disk_id=path,
                    number=idx,
                    path=child.get("path"),
                    size_bytes=self._to_int(child.get("size")),
                    type_name=child.get("parttypename") or child.get("type"),
                    filesystem=child.get("fstype"),
                    label=child.get("label"),
                    mount_points=mount_points,
                    is_boot="/boot" in mount_points,
                    is_system="/" in mount_points,
                    is_mounted=bool(mount_points),
                    volume=volume,
                )
            )
        tran = str(node.get("tran") or "").lower()
        rm = str(node.get("rm") or "0") in ("1", "true", "True")
        return DiskInfo(
            disk_id=path,
            path=path,
            friendly_name=" ".join(str(x) for x in [node.get("vendor"), node.get("model")] if x).strip() or path,
            model=node.get("model"),
            vendor=node.get("vendor"),
            serial_number=node.get("serial"),
            bus_type=tran.upper() if tran else None,
            media_type=node.get("type"),
            size_bytes=int(node.get("size") or 0),
            partition_style=node.get("pttype"),
            operational_status="Online" if Path(path).exists() else "Missing",
            health_status=None,
            is_usb=tran == "usb",
            is_removable=rm or tran == "usb",
            is_system_disk=(path == os_disk_path),
            is_boot_disk=any(p.is_boot or p.is_system for p in partitions),
            partitions=partitions,
            raw=node,
        )

    def list_disks(self) -> list[DiskInfo]:
        columns = "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,SERIAL,TRAN,RM,RO,PTTYPE,FSTYPE,LABEL,MOUNTPOINTS,PARTTYPENAME"
        output = self._run(["lsblk", "--json", "--bytes", "--output", columns], timeout_seconds=30)
        data = json.loads(output)
        os_disk_path = self._parent_disk_for_source(self._root_source())
        disks: list[DiskInfo] = []
        for node in data.get("blockdevices", []):
            if node.get("type") == "disk":
                disks.append(self._disk_from_node(node, os_disk_path))
        return disks

    def get_disk(self, disk_id: str) -> DiskInfo:
        normalized = str(disk_id).strip()
        if normalized.isdigit():
            normalized = f"/dev/sd{chr(ord('a') + int(normalized))}"
        for disk in self.list_disks():
            ids = {disk.disk_id, disk.path or "", Path(disk.path or disk.disk_id).name}
            if normalized in ids or f"/dev/{normalized}" in ids:
                return disk
        raise DiskNotFoundError(f"Disk not found: {disk_id}")

    def get_os_disk_id(self) -> str | None:
        for disk in self.list_disks():
            if disk.is_system_disk:
                return disk.disk_id
        return None

    def doctor_dependencies(self) -> DependencyReport:
        checks = [
            DependencyCheck("lsblk", shutil.which("lsblk") is not None, "required for disk inventory", shutil.which("lsblk")),
            DependencyCheck("findmnt", shutil.which("findmnt") is not None, "required for OS disk detection", shutil.which("findmnt")),
            DependencyCheck("mount", shutil.which("mount") is not None, "required for mounting", shutil.which("mount")),
            DependencyCheck("umount", shutil.which("umount") is not None, "required for unmounting", shutil.which("umount")),
            DependencyCheck("wipefs", shutil.which("wipefs") is not None, "optional for signature inspection/wipe", shutil.which("wipefs")),
            DependencyCheck("partprobe", shutil.which("partprobe") is not None, "optional for partition reread", shutil.which("partprobe")),
            DependencyCheck("smartctl", shutil.which("smartctl") is not None, "optional for SMART health", shutil.which("smartctl")),
            DependencyCheck("udisksctl", shutil.which("udisksctl") is not None, "optional for safe USB power-off", shutil.which("udisksctl")),
        ]
        return DependencyReport(platform=self.name, checks=checks)

    def build_restore_normal_steps(self, disk: DiskInfo, filesystem: str, label: str) -> list[str]:
        fs = filesystem.lower()
        if fs == "fat32":
            mkfs = f"mkfs.vfat -F 32 -n {label!r} {disk.path}1"
        elif fs == "exfat":
            mkfs = f"mkfs.exfat -n {label!r} {disk.path}1"
        elif fs == "ext4":
            mkfs = f"mkfs.ext4 -L {label!r} {disk.path}1"
        else:
            mkfs = f"mkfs.{fs} {disk.path}1"
        return [
            f"umount all mounted partitions on {disk.path}",
            f"wipefs -a {disk.path}",
            f"parted -s {disk.path} mklabel msdos",
            f"parted -s {disk.path} mkpart primary 1MiB 100%",
            mkfs,
        ]

    def restore_normal(self, disk: DiskInfo, filesystem: str, label: str) -> OperationResult:
        self.unmount_disk(disk)
        commands = [
            ["wipefs", "-a", disk.path or disk.disk_id],
            ["parted", "-s", disk.path or disk.disk_id, "mklabel", "msdos"],
            ["parted", "-s", disk.path or disk.disk_id, "mkpart", "primary", "1MiB", "100%"],
        ]
        output_parts: list[str] = []
        for cmd in commands:
            output_parts.append(self._run(cmd, sudo=True, timeout_seconds=300))
        part_path = f"{disk.path}1"
        fs = filesystem.lower()
        if fs == "fat32":
            mkfs = ["mkfs.vfat", "-F", "32", "-n", label, part_path]
        elif fs == "exfat":
            mkfs = ["mkfs.exfat", "-n", label, part_path]
        elif fs == "ext4":
            mkfs = ["mkfs.ext4", "-L", label, part_path]
        else:
            mkfs = [f"mkfs.{fs}", part_path]
        output_parts.append(self._run(mkfs, sudo=True, timeout_seconds=600))
        return OperationResult(True, False, "Disk restored to normal storage.", self.build_restore_normal_steps(disk, filesystem, label), {"output": "\n".join(output_parts)})

    def clear_disk(self, disk: DiskInfo) -> OperationResult:
        self.unmount_disk(disk)
        out = self._run(["wipefs", "-a", disk.path or disk.disk_id], sudo=True, timeout_seconds=300)
        return OperationResult(True, False, "Disk signatures cleared.", [f"wipefs -a {disk.path}"], {"output": out})

    def unmount_disk(self, disk: DiskInfo) -> OperationResult:
        steps: list[str] = []
        outputs: list[str] = []
        for partition in disk.partitions:
            if partition.mount_points:
                for mount_point in partition.mount_points:
                    steps.append(f"umount {mount_point}")
                    outputs.append(self._run(["umount", mount_point], sudo=True, timeout_seconds=120))
            elif partition.path and partition.is_mounted:
                steps.append(f"umount {partition.path}")
                outputs.append(self._run(["umount", partition.path], sudo=True, timeout_seconds=120))
        if not steps:
            return OperationResult(True, False, "No mounted partitions found.", [])
        return OperationResult(True, False, "Partitions unmounted.", steps, {"output": "\n".join(outputs)})

    def eject_disk(self, disk: DiskInfo) -> OperationResult:
        path = disk.path or disk.disk_id
        if shutil.which("udisksctl"):
            out = self._run(["udisksctl", "power-off", "-b", path], timeout_seconds=120)
            return OperationResult(True, False, "Power-off requested.", [f"udisksctl power-off -b {path}"], {"output": out})
        if shutil.which("eject"):
            out = self._run(["eject", path], timeout_seconds=120)
            return OperationResult(True, False, "Eject requested.", [f"eject {path}"], {"output": out})
        return OperationResult(False, False, "No eject tool found.", [])

    def reset_usb_device(self, disk: DiskInfo) -> OperationResult:
        return OperationResult(False, False, "Linux USB reset is not implemented safely without device-specific sysfs paths.", [])

    def rescan(self) -> OperationResult:
        steps: list[str] = []
        outputs: list[str] = []
        if shutil.which("udevadm"):
            steps.append("udevadm settle")
            outputs.append(self._run(["udevadm", "settle"], timeout_seconds=60))
        if shutil.which("partprobe"):
            steps.append("partprobe")
            outputs.append(self._run(["partprobe"], sudo=True, timeout_seconds=120))
        return OperationResult(True, False, "Rescan requested.", steps, {"output": "\n".join(outputs)})

    def raw_device_path(self, disk: DiskInfo) -> Path:
        if not disk.path:
            raise BackendError("Linux raw disk path missing.")
        return Path(disk.path)

    def health_summary(self) -> OperationResult:
        if not shutil.which("smartctl"):
            return OperationResult(False, False, "smartctl not found. Install smartmontools for SMART health data.", [])
        outputs: list[str] = []
        for item in self.list_disks():
            outputs.append(self._run(["smartctl", "-H", item.path or item.disk_id], sudo=True, timeout_seconds=60))
        return OperationResult(True, False, "SMART health summary.", ["smartctl -H <disk>"], {"output": "\n".join(outputs)})

    def health_smart(self, disk: DiskInfo | None = None) -> OperationResult:
        if not shutil.which("smartctl"):
            return OperationResult(False, False, "smartctl not found. Install smartmontools for SMART health data.", [])
        if disk is None:
            outputs: list[str] = []
            for item in self.list_disks():
                outputs.append(self._run(["smartctl", "-a", item.path or item.disk_id], sudo=True, timeout_seconds=60))
            return OperationResult(True, False, "SMART full report (all disks).", ["smartctl -a <disk>"], {"output": "\n".join(outputs)})
        out = self._run(["smartctl", "-a", disk.path or disk.disk_id], sudo=True, timeout_seconds=120)
        return OperationResult(True, False, f"SMART report for {disk.disk_id}.", [f"smartctl -a {disk.path}"], {"output": out})
