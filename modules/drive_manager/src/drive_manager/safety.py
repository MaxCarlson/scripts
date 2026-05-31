from __future__ import annotations

from dataclasses import dataclass

from .models import DiskInfo, OperationPlan, SafetyDecision, format_bytes_binary

DEFAULT_MAX_DESTRUCTIVE_BYTES = 256 * 1024**3


@dataclass(frozen=True)
class SafetyOptions:
    execute: bool = False
    allow_non_usb: bool = False
    allow_large_disk: bool = False
    yes: bool = False
    max_destructive_bytes: int = DEFAULT_MAX_DESTRUCTIVE_BYTES


class SafetyPolicy:
    """Centralized safety gate for every destructive or write operation."""

    def evaluate(self, plan: OperationPlan, options: SafetyOptions) -> SafetyDecision:
        refused: list[str] = []
        warnings: list[str] = []
        required: list[str] = []

        dry_run = not options.execute
        if not plan.destructive and not plan.writes_raw_disk:
            return SafetyDecision(True, dry_run=False, refused_reasons=[], warnings=[], required_confirmations=[])

        disk = plan.target_disk
        if disk is None:
            refused.append("No target disk was resolved for a destructive/write operation.")
            return SafetyDecision(False, dry_run=dry_run, refused_reasons=refused, warnings=warnings, required_confirmations=required)

        if disk.is_system_disk or disk.is_boot_disk:
            refused.append(
                f"Disk {disk.disk_id} appears to contain the active OS/boot volume. Destructive operations are permanently refused."
            )

        if disk.size_bytes <= 0:
            refused.append(
                f"Disk {disk.disk_id} reports size {disk.size_bytes} bytes. Refusing destructive operations against zero-size/no-media disks."
            )

        if disk.size_bytes > options.max_destructive_bytes and not options.allow_large_disk:
            refused.append(
                "Target disk is larger than the default destructive limit: "
                f"{format_bytes_binary(disk.size_bytes)} > {format_bytes_binary(options.max_destructive_bytes)}. "
                "Add -L / --allow-large-disk only if intentional."
            )

        if not (disk.is_usb or disk.is_removable):
            warnings.append("Target disk is not classified as USB/removable.")
            if not options.allow_non_usb:
                refused.append("Non-USB destructive operations require -U / --allow-non-usb.")
            required.extend([
                f"disk-name:{disk.name_for_confirmation}",
                f"disk-id:{disk.disk_id}",
                self._letter_or_serial_confirmation(disk),
                f"ack:ERASE DISK {disk.disk_id} {disk.name_for_confirmation} {self._letter_or_serial_value(disk)}",
            ])

        if dry_run:
            warnings.append("Dry run mode: no changes will be made. Add -x / --execute to perform the operation.")
            return SafetyDecision(True, dry_run=True, refused_reasons=refused, warnings=warnings, required_confirmations=required)

        allowed = len(refused) == 0
        return SafetyDecision(allowed, dry_run=False, refused_reasons=refused, warnings=warnings, required_confirmations=required)

    def _letter_or_serial_value(self, disk: DiskInfo) -> str:
        letters = disk.drive_letters
        if letters:
            return ",".join(letters)
        return disk.serial_number or "NO-SERIAL"

    def _letter_or_serial_confirmation(self, disk: DiskInfo) -> str:
        value = self._letter_or_serial_value(disk)
        if disk.drive_letters:
            return f"drive-letters:{value}"
        return f"serial:{value}"
