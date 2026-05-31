from __future__ import annotations

from .models import DiskInfo, Severity, UsbDiagnosis, format_bytes_binary


def diagnose_disk(disk: DiskInfo) -> UsbDiagnosis:
    evidence: list[str] = []
    causes: list[str] = []
    actions: list[str] = []

    if disk.is_usb or disk.is_removable:
        evidence.append("Disk is present as a USB/removable mass-storage device.")
    else:
        evidence.append("Disk is not classified as USB/removable.")

    evidence.append(f"Reported size: {format_bytes_binary(disk.size_bytes)}.")
    if disk.operational_status:
        evidence.append(f"Operational status: {disk.operational_status}.")
    if disk.health_status:
        evidence.append(f"Health status: {disk.health_status}.")

    status_text = (disk.operational_status or "").lower()
    if disk.size_bytes == 0 or "no media" in status_text:
        causes.extend([
            "Failed flash NAND/media behind a still-enumerating USB controller.",
            "Empty card reader or adapter with no inserted card.",
            "Bad USB bridge, adapter, hub, or front-panel connection.",
        ])
        actions.extend([
            "Try one rear motherboard USB port once.",
            "If it still reports 0 bytes / No Media, replace the drive.",
            "Do not use this device for installers, MemTest86, or diagnostics.",
        ])
        return UsbDiagnosis(
            disk_id=disk.disk_id,
            diagnosis="BAD_MEDIA_OR_EMPTY_READER",
            severity=Severity.ERROR,
            evidence=evidence,
            likely_causes=causes,
            recommended_actions=actions,
            is_probably_bad=True,
        )

    if disk.is_system_disk or disk.is_boot_disk:
        actions.append("Do not target this disk for destructive operations; it appears to contain the OS/boot volume.")
        return UsbDiagnosis(
            disk_id=disk.disk_id,
            diagnosis="SYSTEM_OR_BOOT_DISK",
            severity=Severity.WARNING,
            evidence=evidence,
            likely_causes=["The disk contains the active operating system or boot partition."],
            recommended_actions=actions,
            is_probably_bad=False,
        )

    if (disk.is_usb or disk.is_removable) and disk.size_bytes > 0:
        actions.append("Disk appears usable. For boot media creation, run image write dry-run first and review the target identity.")
        return UsbDiagnosis(
            disk_id=disk.disk_id,
            diagnosis="USB_MEDIA_PRESENT",
            severity=Severity.OK,
            evidence=evidence,
            likely_causes=[],
            recommended_actions=actions,
            is_probably_bad=False,
        )

    return UsbDiagnosis(
        disk_id=disk.disk_id,
        diagnosis="DISK_PRESENT",
        severity=Severity.INFO,
        evidence=evidence,
        likely_causes=[],
        recommended_actions=["Use scan detail to inspect partitions and volumes."],
        is_probably_bad=False,
    )
