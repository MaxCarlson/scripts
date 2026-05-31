"""Tests for models.py."""
from __future__ import annotations

from pathlib import Path

from drive_manager.models import (
    DiskInfo,
    OperationKind,
    OperationPlan,
    OperationResult,
    PartitionInfo,
    Severity,
    UsbDiagnosis,
    VolumeInfo,
    dataclass_to_dict,
    format_bytes_binary,
)


def test_format_bytes_binary_zero():
    assert format_bytes_binary(0) == "0 B"


def test_format_bytes_binary_bytes():
    assert format_bytes_binary(512) == "512 B"


def test_format_bytes_binary_kib():
    assert format_bytes_binary(1024) == "1.00 KiB"


def test_format_bytes_binary_gib():
    assert "GiB" in format_bytes_binary(16 * 1024 ** 3)


def test_format_bytes_binary_tib():
    assert "TiB" in format_bytes_binary(10 * 1024 ** 4)


def test_format_bytes_binary_none():
    assert format_bytes_binary(None) == "unknown"


def test_disk_info_name_for_confirmation_friendly():
    d = DiskInfo(disk_id="1", friendly_name="MyDisk")
    assert d.name_for_confirmation == "MyDisk"


def test_disk_info_name_for_confirmation_fallback_chain():
    d = DiskInfo(disk_id="1", model="TOSHIBA X300")
    assert d.name_for_confirmation == "TOSHIBA X300"
    d2 = DiskInfo(disk_id="1", path="\\\\.\\PhysicalDrive1")
    assert d2.name_for_confirmation == "\\\\.\\PhysicalDrive1"
    d3 = DiskInfo(disk_id="1")
    assert d3.name_for_confirmation == "1"


def test_disk_info_drive_letters_deduped():
    p1 = PartitionInfo(partition_id="p1", disk_id="1", drive_letter="D")
    p2 = PartitionInfo(partition_id="p2", disk_id="1", volume=VolumeInfo(drive_letter="D"))
    d = DiskInfo(disk_id="1", partitions=[p1, p2])
    assert d.drive_letters == ["D"]


def test_disk_info_drive_letters_multiple():
    p1 = PartitionInfo(partition_id="p1", disk_id="1", drive_letter="C")
    p2 = PartitionInfo(partition_id="p2", disk_id="1", drive_letter="E")
    d = DiskInfo(disk_id="1", partitions=[p1, p2])
    assert d.drive_letters == ["C", "E"]


def test_disk_info_mount_points():
    p = PartitionInfo(partition_id="p1", disk_id="1", mount_points=["/mnt/data"])
    d = DiskInfo(disk_id="1", partitions=[p])
    assert "/mnt/data" in d.mount_points


def test_disk_info_is_virtual_default_false():
    d = DiskInfo(disk_id="1")
    assert d.is_virtual is False


def test_disk_info_is_virtual_set():
    d = DiskInfo(disk_id="1", is_virtual=True)
    assert d.is_virtual is True


def test_dataclass_to_dict_disk():
    d = DiskInfo(disk_id="1", friendly_name="Test", size_bytes=1024)
    result = dataclass_to_dict(d)
    assert result["disk_id"] == "1"
    assert result["size_bytes"] == 1024


def test_dataclass_to_dict_path():
    plan = OperationPlan(kind=OperationKind.WIPE, title="test", image_path=Path("/tmp/test.iso"))
    result = dataclass_to_dict(plan)
    # asdict() preserves Path objects; dataclass_to_dict converts at the top level
    assert str(result["image_path"]).endswith("test.iso")


def test_dataclass_to_dict_enum():
    result = dataclass_to_dict(Severity.WARNING)
    assert result == "warning"


def test_dataclass_to_dict_list():
    disks = [DiskInfo(disk_id="1"), DiskInfo(disk_id="2")]
    result = dataclass_to_dict(disks)
    assert isinstance(result, list)
    assert len(result) == 2


def test_operation_result_fields():
    r = OperationResult(ok=True, dry_run=False, message="done", steps=["step1"], details={"output": "x"})
    assert r.ok
    assert r.message == "done"
    assert r.steps == ["step1"]


def test_volume_info_display_id_letter():
    v = VolumeInfo(drive_letter="C")
    assert v.display_id() == "C:"


def test_volume_info_display_id_mount():
    v = VolumeInfo(mount_point="/mnt/data")
    assert v.display_id() == "/mnt/data"


def test_usb_diagnosis_fields():
    d = UsbDiagnosis(
        disk_id="6",
        diagnosis="USB_MEDIA_PRESENT",
        severity=Severity.OK,
        evidence=["present"],
        likely_causes=[],
        recommended_actions=["use it"],
    )
    assert d.disk_id == "6"
    assert d.is_probably_bad is False
