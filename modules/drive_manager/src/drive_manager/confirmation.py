from __future__ import annotations

from .errors import ConfirmationError
from .models import DiskInfo


def confirm_non_usb_disk(disk: DiskInfo) -> None:
    """Require GitHub-style typed confirmation for non-USB destructive changes."""
    expected_name = disk.name_for_confirmation
    letters = disk.drive_letters
    expected_letter_or_serial = ",".join(letters) if letters else (disk.serial_number or "NO-SERIAL")
    expected_ack = f"ERASE DISK {disk.disk_id} {expected_name} {expected_letter_or_serial}"

    print("Non-USB destructive operation confirmation required.")
    print(f"Disk:   {disk.disk_id}")
    print(f"Name:   {expected_name}")
    print(f"Serial: {disk.serial_number or 'unknown'}")
    print(f"Letters/Mounts: {expected_letter_or_serial}")
    print()

    got_name = input(f"Type disk name exactly [{expected_name}]: ")
    if got_name != expected_name:
        raise ConfirmationError("Disk name confirmation did not match.")

    got_letter = input(f"Type drive letters or serial exactly [{expected_letter_or_serial}]: ")
    if got_letter != expected_letter_or_serial:
        raise ConfirmationError("Drive-letter/serial confirmation did not match.")

    got_ack = input(f"Type acknowledgment exactly [{expected_ack}]: ")
    if got_ack != expected_ack:
        raise ConfirmationError("Destructive acknowledgment did not match.")
