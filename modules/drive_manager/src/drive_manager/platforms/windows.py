from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from drive_manager.errors import BackendError, DiskNotFoundError
from drive_manager.models import DependencyCheck, DependencyReport, DiskInfo, OperationResult, PartitionInfo, VolumeInfo
from drive_manager.platform_base import PlatformBackend


class WindowsBackend(PlatformBackend):
    name = "windows"

    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds
        self.pwsh = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"

    def _run_ps(self, script: str, *, json_output: bool = False, timeout_seconds: int | None = None) -> str:
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        command = [self.pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
        cp = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds or self.timeout_seconds,
        )
        if cp.returncode != 0:
            raise BackendError(f"PowerShell command failed ({cp.returncode}): {cp.stderr.strip()}")
        return cp.stdout.strip()

    @staticmethod
    def _as_list(data: Any) -> list[Any]:
        if data is None or data == "":
            return []
        if isinstance(data, list):
            return data
        return [data]

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _load_disks_json(self) -> list[dict[str, Any]]:
        script = r'''
$ErrorActionPreference = 'SilentlyContinue'
$systemDriveLetter = $env:SystemDrive.TrimEnd(':')
$systemDiskNumber = $null
try {
    $systemPartition = Get-Partition -DriveLetter $systemDriveLetter -ErrorAction Stop
    $systemDiskNumber = $systemPartition.DiskNumber
} catch {}

# Build mounted-image lookup: imagePath -> diskNumber
$mountedImagePaths = @{}
try {
    foreach ($img in (Get-DiskImage -ErrorAction SilentlyContinue | Where-Object Attached)) {
        if ($img.DevicePath) {
            $num = ($img.DevicePath -replace '.*PhysicalDrive','') -as [int]
            if ($null -ne $num) { $mountedImagePaths[[string]$num] = [string]$img.ImagePath }
        }
    }
} catch {}

$items = foreach ($disk in (Get-Disk -ErrorAction SilentlyContinue | Sort-Object Number)) {
    # Capture partitions into $parts WITHOUT leaking them into the outer pipeline.
    $parts = @(foreach ($partition in (Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | Sort-Object PartitionNumber)) {
        $volume = $null
        try { $volume = $partition | Get-Volume -ErrorAction SilentlyContinue } catch {}
        $accessPaths = @()
        try { $accessPaths = @($partition.AccessPaths | Where-Object { $_ }) } catch {}
        [pscustomobject]@{
            PartitionId  = "Disk$($disk.Number)-Partition$($partition.PartitionNumber)"
            DiskId       = [string]$disk.Number
            Number       = $partition.PartitionNumber
            Path         = ($accessPaths -join ';')
            SizeBytes    = [int64]$partition.Size
            OffsetBytes  = [int64]$partition.Offset
            TypeName     = [string]$partition.Type
            DriveLetter  = if ($partition.DriveLetter) { [string]$partition.DriveLetter } else { $null }
            MountPoints  = $accessPaths
            IsBoot       = [bool]$partition.IsBoot
            IsSystem     = [bool]$partition.IsSystem
            IsReadOnly   = [bool]$partition.IsReadOnly
            IsMounted    = [bool]($partition.DriveLetter -or $accessPaths.Count -gt 0)
            Volume       = if ($volume) {
                [pscustomobject]@{
                    DriveLetter        = if ($volume.DriveLetter) { [string]$volume.DriveLetter } else { $null }
                    MountPoint         = $null
                    Label              = [string]$volume.FileSystemLabel
                    FileSystem         = [string]$volume.FileSystem
                    SizeBytes          = if ($volume.Size) { [int64]$volume.Size } else { $null }
                    SizeRemainingBytes = if ($volume.SizeRemaining) { [int64]$volume.SizeRemaining } else { $null }
                    HealthStatus       = [string]$volume.HealthStatus
                }
            } else { $null }
        }
    })

    $diskNum = [string]$disk.Number
    [pscustomobject]@{
        DiskId           = $diskNum
        Number           = [int]$disk.Number
        Path             = "\\.\PhysicalDrive$($disk.Number)"
        FriendlyName     = [string]$disk.FriendlyName
        Model            = [string]$disk.Model
        Vendor           = [string]$disk.Manufacturer
        SerialNumber     = [string]$disk.SerialNumber
        BusType          = [string]$disk.BusType
        MediaType        = [string]$disk.MediaType
        SizeBytes        = [int64]$disk.Size
        PartitionStyle   = [string]$disk.PartitionStyle
        OperationalStatus= ($disk.OperationalStatus -join ',')
        HealthStatus     = [string]$disk.HealthStatus
        IsUsb            = ([string]$disk.BusType -eq 'USB')
        IsRemovable      = ([string]$disk.BusType -eq 'USB' -or [string]$disk.MediaType -eq 'RemovableMedia')
        IsSystemDisk     = ($null -ne $systemDiskNumber -and $disk.Number -eq $systemDiskNumber)
        IsBootDisk       = (($parts | Where-Object { $_.IsBoot -or $_.IsSystem }).Count -gt 0)
        IsOffline        = [bool]$disk.IsOffline
        IsReadOnly       = [bool]$disk.IsReadOnly
        IsVirtual        = $mountedImagePaths.ContainsKey($diskNum)
        ImagePath        = if ($mountedImagePaths.ContainsKey($diskNum)) { $mountedImagePaths[$diskNum] } else { $null }
        Partitions       = $parts
        Raw              = @{
            UniqueId  = [string]$disk.UniqueId
            Location  = [string]$disk.Location
            Signature = [string]$disk.Signature
        }
    }
}
$items | ConvertTo-Json -Depth 12
'''
        output = self._run_ps(script)
        if not output:
            return []
        data = json.loads(output)
        return self._as_list(data)

    def _partition_from_dict(self, item: dict[str, Any]) -> PartitionInfo:
        volume = item.get("Volume")
        volume_info = None
        if isinstance(volume, dict):
            volume_info = VolumeInfo(
                drive_letter=volume.get("DriveLetter"),
                mount_point=volume.get("MountPoint"),
                label=volume.get("Label"),
                filesystem=volume.get("FileSystem"),
                size_bytes=self._to_int(volume.get("SizeBytes")),
                size_remaining_bytes=self._to_int(volume.get("SizeRemainingBytes")),
                health_status=volume.get("HealthStatus"),
            )
        return PartitionInfo(
            partition_id=str(item.get("PartitionId") or ""),
            disk_id=str(item.get("DiskId") or ""),
            number=self._to_int(item.get("Number")),
            path=item.get("Path"),
            size_bytes=self._to_int(item.get("SizeBytes")),
            offset_bytes=self._to_int(item.get("OffsetBytes")),
            type_name=item.get("TypeName"),
            filesystem=volume_info.filesystem if volume_info else None,
            label=volume_info.label if volume_info else None,
            drive_letter=item.get("DriveLetter"),
            mount_points=[str(x) for x in self._as_list(item.get("MountPoints")) if x],
            is_boot=bool(item.get("IsBoot")),
            is_system=bool(item.get("IsSystem")),
            is_read_only=bool(item.get("IsReadOnly")),
            is_mounted=bool(item.get("IsMounted")),
            volume=volume_info,
        )

    def _disk_from_dict(self, item: dict[str, Any]) -> DiskInfo:
        partitions = [self._partition_from_dict(p) for p in self._as_list(item.get("Partitions"))]
        raw = item.get("Raw") or {}
        if item.get("ImagePath"):
            raw = {**raw, "image_path": item["ImagePath"]}
        return DiskInfo(
            disk_id=str(item.get("DiskId")),
            number=self._to_int(item.get("Number")),
            path=item.get("Path"),
            friendly_name=item.get("FriendlyName"),
            model=item.get("Model"),
            vendor=item.get("Vendor"),
            serial_number=item.get("SerialNumber"),
            bus_type=item.get("BusType"),
            media_type=item.get("MediaType"),
            size_bytes=int(item.get("SizeBytes") or 0),
            partition_style=item.get("PartitionStyle"),
            operational_status=item.get("OperationalStatus"),
            health_status=item.get("HealthStatus"),
            is_usb=bool(item.get("IsUsb")),
            is_removable=bool(item.get("IsRemovable")),
            is_system_disk=bool(item.get("IsSystemDisk")),
            is_boot_disk=bool(item.get("IsBootDisk")),
            is_offline=bool(item.get("IsOffline")),
            is_read_only=bool(item.get("IsReadOnly")),
            is_virtual=bool(item.get("IsVirtual")),
            partitions=partitions,
            raw=raw,
        )

    def list_disks(self) -> list[DiskInfo]:
        return [self._disk_from_dict(item) for item in self._load_disks_json()]

    def get_disk(self, disk_id: str) -> DiskInfo:
        normalized = str(disk_id).strip().lower().replace("physicaldrive", "").replace("\\\\.\\", "")
        for disk in self.list_disks():
            ids = {disk.disk_id.lower(), str(disk.number).lower() if disk.number is not None else ""}
            if disk.path:
                ids.add(disk.path.lower())
                ids.add(disk.path.lower().replace("\\\\.\\physicaldrive", ""))
            if normalized in ids:
                return disk
        raise DiskNotFoundError(f"Disk not found: {disk_id}")

    def get_os_disk_id(self) -> str | None:
        for disk in self.list_disks():
            if disk.is_system_disk:
                return disk.disk_id
        return None

    def doctor_dependencies(self) -> DependencyReport:
        # Probe optional PS cmdlets by attempting a quick call
        def _ps_cmdlet_available(cmdlet: str) -> bool:
            try:
                self._run_ps(f"Get-Command {cmdlet} -ErrorAction Stop | Out-Null", timeout_seconds=10)
                return True
            except Exception:
                return False

        has_mount = _ps_cmdlet_available("Mount-DiskImage")
        has_reliability = _ps_cmdlet_available("Get-StorageReliabilityCounter")
        checks = [
            DependencyCheck("pwsh/powershell", shutil.which("pwsh") is not None or shutil.which("powershell") is not None, "required for Windows backend", self.pwsh),
            DependencyCheck("Get-Disk", True, "required for disk inventory", note="PowerShell Storage module command"),
            DependencyCheck("Get-PhysicalDisk", True, "required for health summary/SMART", note="PowerShell Storage module command"),
            DependencyCheck("Clear-Disk", True, "required for wipe/restore", note="PowerShell Storage module command"),
            DependencyCheck("Format-Volume", True, "required for format/restore", note="PowerShell Storage module command"),
            DependencyCheck("Mount-DiskImage", has_mount, "optional for ISO virtual drive mount", note="PowerShell Storage module command"),
            DependencyCheck("Get-StorageReliabilityCounter", has_reliability, "optional for SMART detail", note="PowerShell Storage module command"),
            DependencyCheck("pnputil", shutil.which("pnputil") is not None, "optional for USB device reset", shutil.which("pnputil")),
        ]
        return DependencyReport(platform=self.name, checks=checks)

    def build_restore_normal_steps(self, disk: DiskInfo, filesystem: str, label: str) -> list[str]:
        return [
            f"Clear-Disk -Number {disk.disk_id} -RemoveData -RemoveOEM -Confirm:$false",
            f"New-Partition -DiskNumber {disk.disk_id} -UseMaximumSize -AssignDriveLetter",
            f"Format-Volume -FileSystem {filesystem} -NewFileSystemLabel {label!r} -Confirm:$false",
        ]

    def restore_normal(self, disk: DiskInfo, filesystem: str, label: str) -> OperationResult:
        script = f'''
$ErrorActionPreference = 'Stop'
$diskNumber = {int(disk.disk_id)}
Clear-Disk -Number $diskNumber -RemoveData -RemoveOEM -Confirm:$false
$partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -AssignDriveLetter
$partition | Format-Volume -FileSystem {filesystem} -NewFileSystemLabel {json.dumps(label)} -Confirm:$false
Get-Disk -Number $diskNumber | ConvertTo-Json -Depth 6
'''
        output = self._run_ps(script, timeout_seconds=600)
        return OperationResult(True, False, "Disk restored to normal storage.", self.build_restore_normal_steps(disk, filesystem, label), {"output": output})

    def clear_disk(self, disk: DiskInfo) -> OperationResult:
        script = f"Clear-Disk -Number {int(disk.disk_id)} -RemoveData -RemoveOEM -Confirm:$false"
        output = self._run_ps(script, timeout_seconds=300)
        return OperationResult(True, False, "Disk cleared.", [script], {"output": output})

    def unmount_disk(self, disk: DiskInfo) -> OperationResult:
        disk_id = int(disk.disk_id)
        # Remove all access paths (drive letters + mount points) from every
        # partition on the disk so Windows releases its handles before a raw
        # write.  Remove-PartitionAccessPath is available since Windows 8.
        script = f"""
$partitions = Get-Partition -DiskNumber {disk_id} -ErrorAction SilentlyContinue
if ($partitions) {{
    foreach ($p in $partitions) {{
        foreach ($ap in $p.AccessPaths) {{
            if ($ap -match '^[A-Za-z]:\\\\$') {{
                Remove-PartitionAccessPath -DiskNumber {disk_id} -PartitionNumber $p.PartitionNumber -AccessPath $ap -ErrorAction SilentlyContinue
            }}
        }}
    }}
}}
"""
        steps = [f"Remove-PartitionAccessPath -DiskNumber {disk_id} (all access paths)"]
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, "Volumes unmounted.", steps, {"output": output})

    def eject_disk(self, disk: DiskInfo) -> OperationResult:
        letters = disk.drive_letters
        if not letters:
            return OperationResult(False, False, "No drive letters available for eject.", [])
        steps = [f"Shell.Application Eject {letter}:" for letter in letters]
        script = "\n".join([
            "$shell = New-Object -ComObject Shell.Application",
            *[f"$shell.Namespace(17).ParseName('{letter}:').InvokeVerb('Eject')" for letter in letters],
        ])
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, "Eject requested.", steps, {"output": output})

    def reset_usb_device(self, disk: DiskInfo) -> OperationResult:
        note = "Windows USB reset is device-instance dependent. Use Device Manager if this fallback cannot restart it."
        script = f'''
Get-PnpDevice -PresentOnly | Where-Object {{ $_.FriendlyName -match [regex]::Escape({json.dumps(disk.friendly_name or disk.model or disk.disk_id)}) }} | Format-Table -AutoSize | Out-String
'''
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, note, ["Query matching PnP devices"], {"output": output})

    def rescan(self) -> OperationResult:
        script = "Update-HostStorageCache"
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, "Storage cache rescan requested.", [script], {"output": output})

    def raw_device_path(self, disk: DiskInfo) -> Path:
        if disk.number is None:
            raise BackendError("Windows raw disk path requires a disk number.")
        return Path(f"\\\\.\\PhysicalDrive{disk.number}")

    def health_summary(self) -> OperationResult:
        """Overview health table for all physical disks."""
        script = r'''
$disks = Get-PhysicalDisk -ErrorAction SilentlyContinue | Sort-Object DeviceId
$rows = foreach ($d in $disks) {
    [pscustomobject]@{
        Number           = $d.DeviceId
        Name             = $d.FriendlyName
        MediaType        = $d.MediaType
        Size             = [int64]$d.Size
        OperationalStatus= [string]$d.OperationalStatus
        HealthStatus     = [string]$d.HealthStatus
        BusType          = [string]$d.BusType
    }
}
$rows | ConvertTo-Json -Depth 4
'''
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, "health_summary_json", ["Get-PhysicalDisk"], {"output": output})

    def health_smart(self, disk: DiskInfo | None = None) -> OperationResult:
        """Detailed SMART/reliability data for one disk or all disks."""
        if disk is not None:
            script = f'''
$ErrorActionPreference = 'SilentlyContinue'
$pd = Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object DeviceId -eq {int(disk.disk_id)}
$rel = $pd | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
[pscustomobject]@{{
    Number            = $pd.DeviceId
    Name              = $pd.FriendlyName
    MediaType         = $pd.MediaType
    BusType           = $pd.BusType
    OperationalStatus = [string]$pd.OperationalStatus
    HealthStatus      = [string]$pd.HealthStatus
    Size              = [int64]$pd.Size
    Temperature       = if ($rel) {{ $rel.Temperature }} else {{ $null }}
    Wear              = if ($rel) {{ $rel.Wear }} else {{ $null }}
    ReadErrorsTotal   = if ($rel) {{ $rel.ReadErrorsTotal }} else {{ $null }}
    WriteErrorsTotal  = if ($rel) {{ $rel.WriteErrorsTotal }} else {{ $null }}
    PowerOnHours      = if ($rel) {{ $rel.PowerOnHours }} else {{ $null }}
    StartStopCycles   = if ($rel) {{ $rel.StartStopCycles }} else {{ $null }}
}} | ConvertTo-Json -Depth 4
'''
            output = self._run_ps(script, timeout_seconds=120)
            return OperationResult(True, False, "health_smart_json", [f"Get-StorageReliabilityCounter disk {disk.disk_id}"], {"output": output})
        # All disks
        script = r'''
$ErrorActionPreference = 'SilentlyContinue'
$rows = foreach ($pd in (Get-PhysicalDisk -ErrorAction SilentlyContinue | Sort-Object DeviceId)) {
    $rel = $pd | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Number            = $pd.DeviceId
        Name              = $pd.FriendlyName
        MediaType         = $pd.MediaType
        BusType           = $pd.BusType
        OperationalStatus = [string]$pd.OperationalStatus
        HealthStatus      = [string]$pd.HealthStatus
        Size              = [int64]$pd.Size
        Temperature       = if ($rel) { $rel.Temperature } else { $null }
        Wear              = if ($rel) { $rel.Wear } else { $null }
        ReadErrorsTotal   = if ($rel) { $rel.ReadErrorsTotal } else { $null }
        WriteErrorsTotal  = if ($rel) { $rel.WriteErrorsTotal } else { $null }
        PowerOnHours      = if ($rel) { $rel.PowerOnHours } else { $null }
    }
}
$rows | ConvertTo-Json -Depth 4
'''
        output = self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, "health_smart_json", ["Get-PhysicalDisk + Get-StorageReliabilityCounter"], {"output": output})

    def mount_image(self, image_path: Path, drive_letter: str | None = None) -> OperationResult:
        """Mount an ISO/image file as a virtual disk. Optionally assign a drive letter."""
        path_str = str(image_path).replace("\\", "\\\\")
        letter_block = ""
        if drive_letter:
            letter = drive_letter.rstrip(":").upper()
            letter_block = f"""
$vol = Get-DiskImage -ImagePath '{path_str}' | Get-Volume -ErrorAction SilentlyContinue
if ($vol -and $vol.DriveLetter -ne '{letter}') {{
    $vol | Set-Volume -NewDriveLetter '{letter}' -ErrorAction SilentlyContinue
}}
"""
        script = f"""
$ErrorActionPreference = 'Stop'
$img = Mount-DiskImage -ImagePath '{path_str}' -PassThru
{letter_block}
$img | ConvertTo-Json -Depth 4
"""
        output = self._run_ps(script, timeout_seconds=120)
        steps = [f"Mount-DiskImage -ImagePath '{image_path}' -PassThru"]
        if drive_letter:
            steps.append(f"Assign drive letter {drive_letter.rstrip(':').upper()}:")
        return OperationResult(True, False, f"Image mounted: {image_path}", steps, {"output": output})

    def dismount_image(self, image_path: Path) -> OperationResult:
        """Dismount a mounted ISO/image by its original path."""
        path_str = str(image_path).replace("\\", "\\\\")
        script = f"Dismount-DiskImage -ImagePath '{path_str}' -ErrorAction Stop | Out-Null"
        self._run_ps(script, timeout_seconds=120)
        return OperationResult(True, False, f"Image dismounted: {image_path}", [f"Dismount-DiskImage '{image_path}'"], {})

    def list_mounted_images(self) -> list[dict[str, Any]]:
        """Return list of currently mounted disk images."""
        script = r'''
$imgs = Get-DiskImage -ErrorAction SilentlyContinue | Where-Object Attached | ForEach-Object {
    $vol = $_ | Get-Volume -ErrorAction SilentlyContinue
    [pscustomobject]@{
        ImagePath   = [string]$_.ImagePath
        DevicePath  = [string]$_.DevicePath
        Attached    = [bool]$_.Attached
        DriveLetter = if ($vol) { [string]$vol.DriveLetter } else { $null }
        Size        = [int64]$_.Size
    }
}
$imgs | ConvertTo-Json -Depth 4
'''
        output = self._run_ps(script, timeout_seconds=60)
        if not output:
            return []
        data = json.loads(output)
        return self._as_list(data)
