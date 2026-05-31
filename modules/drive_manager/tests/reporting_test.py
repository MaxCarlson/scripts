"""Tests for reporting.py."""
from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from drive_manager.models import (
    DependencyCheck,
    DependencyReport,
    DiskInfo,
    OperationKind,
    OperationPlan,
    OperationResult,
    PartitionInfo,
    SafetyDecision,
    Severity,
    UsbDiagnosis,
    VolumeInfo,
)
from drive_manager.reporting import (
    _status_color,
    print_dependency_report,
    print_diagnosis,
    print_disk_detail,
    print_disk_table,
    print_health_smart,
    print_health_summary,
    print_operation_plan,
    print_operation_result,
    print_volumes_table,
)


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _disk(**kw) -> DiskInfo:
    base: dict = dict(disk_id="1", friendly_name="Test Disk", size_bytes=16 * 1024**3)
    base.update(kw)
    return DiskInfo(**base)


# ── _status_color ─────────────────────────────────────────────────────────────

def test_status_color_online():
    assert _status_color("Online") == "green"


def test_status_color_healthy():
    assert _status_color("Healthy") == "green"


def test_status_color_offline():
    assert _status_color("Offline") == "red"


def test_status_color_warning():
    assert _status_color("Warning") == "yellow"


def test_status_color_unknown():
    assert _status_color("Unknown") == "yellow"


def test_status_color_empty():
    assert _status_color("") == ""


# ── print_disk_table ──────────────────────────────────────────────────────────

def test_disk_table_contains_disk_id():
    out = _capture(print_disk_table, [_disk()])
    assert "1" in out


def test_disk_table_contains_name():
    out = _capture(print_disk_table, [_disk(friendly_name="MyDisk")])
    assert "MyDisk" in out


def test_disk_table_shows_usb_flag():
    out = _capture(print_disk_table, [_disk(is_usb=True)])
    assert "USB" in out


def test_disk_table_shows_os_flag():
    out = _capture(print_disk_table, [_disk(is_system_disk=True)])
    assert "OS" in out


def test_disk_table_shows_virt_flag():
    out = _capture(print_disk_table, [_disk(is_virtual=True)])
    assert "VIRT" in out


def test_disk_table_shows_no_media_flag():
    out = _capture(print_disk_table, [_disk(size_bytes=0)])
    assert "NO-MEDIA" in out


def test_disk_table_shows_drive_letters():
    p = PartitionInfo(partition_id="p1", disk_id="1", drive_letter="D")
    d = DiskInfo(disk_id="1", friendly_name="HDD", size_bytes=1 * 1024**4, partitions=[p])
    out = _capture(print_disk_table, [d])
    assert "D" in out


def test_disk_table_multiple_disks():
    disks = [_disk(disk_id="1", friendly_name="A"), _disk(disk_id="2", friendly_name="B")]
    out = _capture(print_disk_table, disks)
    assert "A" in out
    assert "B" in out


def test_disk_table_empty_list():
    out = _capture(print_disk_table, [])
    assert out  # header still printed


# ── print_disk_detail ─────────────────────────────────────────────────────────

def test_disk_detail_shows_id_and_name():
    out = _capture(print_disk_detail, _disk(friendly_name="WDC"))
    assert "1" in out
    assert "WDC" in out


def test_disk_detail_shows_size():
    out = _capture(print_disk_detail, _disk(size_bytes=16 * 1024**3))
    assert "GiB" in out


def test_disk_detail_shows_virtual():
    out = _capture(print_disk_detail, _disk(is_virtual=True))
    assert "True" in out


def test_disk_detail_image_path_shown():
    d = _disk(is_virtual=True, raw={"image_path": "C:\\images\\test.iso"})
    out = _capture(print_disk_detail, d)
    assert "test.iso" in out


def test_disk_detail_partitions_none():
    out = _capture(print_disk_detail, _disk())
    assert "none" in out.lower() or "Partitions" in out


def test_disk_detail_partitions_shown():
    p = PartitionInfo(partition_id="Disk1-Partition1", disk_id="1", number=1,
                      size_bytes=1024**3, filesystem="NTFS", drive_letter="C")
    d = DiskInfo(disk_id="1", friendly_name="Test", size_bytes=1024**3, partitions=[p])
    out = _capture(print_disk_detail, d)
    assert "NTFS" in out
    assert "C" in out


# ── print_volumes_table ───────────────────────────────────────────────────────

def test_volumes_table_empty():
    out = _capture(print_volumes_table, [])
    assert "No volumes" in out


def test_volumes_table_shows_letter():
    p = PartitionInfo(partition_id="p1", disk_id="2", drive_letter="E",
                      filesystem="FAT32", size_bytes=16 * 1024**3)
    out = _capture(print_volumes_table, [p])
    assert "E:" in out
    assert "FAT32" in out


# ── print_diagnosis ───────────────────────────────────────────────────────────

def test_diagnosis_output_contains_code():
    d = UsbDiagnosis(disk_id="6", diagnosis="USB_MEDIA_PRESENT", severity=Severity.OK,
                     evidence=["present"], likely_causes=[], recommended_actions=["use it"])
    out = _capture(print_diagnosis, d)
    assert "USB_MEDIA_PRESENT" in out
    assert "ok" in out


def test_diagnosis_shows_evidence():
    d = UsbDiagnosis(disk_id="6", diagnosis="DISK_PRESENT", severity=Severity.INFO,
                     evidence=["Disk is present"], likely_causes=[], recommended_actions=[])
    out = _capture(print_diagnosis, d)
    assert "Disk is present" in out


def test_diagnosis_shows_causes():
    d = UsbDiagnosis(disk_id="6", diagnosis="BAD_MEDIA_OR_EMPTY_READER", severity=Severity.ERROR,
                     evidence=[], likely_causes=["NAND failure"], recommended_actions=[])
    out = _capture(print_diagnosis, d)
    assert "NAND failure" in out


def test_diagnosis_shows_actions():
    d = UsbDiagnosis(disk_id="6", diagnosis="BAD_MEDIA_OR_EMPTY_READER", severity=Severity.ERROR,
                     evidence=[], likely_causes=[], recommended_actions=["Replace the drive."])
    out = _capture(print_diagnosis, d)
    assert "Replace the drive" in out


# ── print_health_summary ──────────────────────────────────────────────────────

def test_health_summary_parses_json():
    data = [{"Number": "2", "Name": "WDC Drive", "MediaType": "HDD", "BusType": "SATA",
              "Size": 10 * 1024**4, "OperationalStatus": "OK", "HealthStatus": "Healthy"}]
    out = _capture(print_health_summary, json.dumps(data))
    assert "WDC Drive" in out
    assert "Healthy" in out


def test_health_summary_empty():
    out = _capture(print_health_summary, "[]")
    assert "No physical disks" in out


def test_health_summary_invalid_json():
    out = _capture(print_health_summary, "not json")
    assert "not json" in out


def test_health_summary_single_object_not_list():
    data = {"Number": "0", "Name": "Disk", "MediaType": "SSD", "BusType": "NVMe",
             "Size": 512 * 1024**3, "OperationalStatus": "OK", "HealthStatus": "Healthy"}
    out = _capture(print_health_summary, json.dumps(data))
    assert "Disk" in out


# ── print_health_smart ────────────────────────────────────────────────────────

def test_health_smart_shows_disk_name():
    data = [{"Number": "3", "Name": "CT4000T710SSD8", "MediaType": "SSD",
              "BusType": "NVMe", "Size": 4 * 1024**4,
              "OperationalStatus": "OK", "HealthStatus": "Healthy",
              "Temperature": 35, "Wear": 0, "PowerOnHours": 1234}]
    out = _capture(print_health_smart, json.dumps(data))
    assert "CT4000T710SSD8" in out
    assert "35" in out  # temperature


def test_health_smart_empty():
    out = _capture(print_health_smart, "[]")
    assert "No SMART data" in out


# ── print_dependency_report ───────────────────────────────────────────────────

def test_dependency_report_shows_name():
    report = DependencyReport(platform="windows", checks=[
        DependencyCheck("pwsh", True, "required for backend", "C:\\Windows\\pwsh.exe")
    ])
    out = _capture(print_dependency_report, report)
    assert "pwsh" in out
    assert "yes" in out


def test_dependency_report_missing_required():
    report = DependencyReport(platform="windows", checks=[
        DependencyCheck("missing-tool", False, "required for something")
    ])
    out = _capture(print_dependency_report, report)
    assert "no" in out
    assert "1 required" in out.lower() or "missing" in out.lower()


def test_dependency_report_all_satisfied():
    report = DependencyReport(platform="windows", checks=[
        DependencyCheck("pwsh", True, "required for backend")
    ])
    out = _capture(print_dependency_report, report)
    assert "satisfied" in out.lower() or "All required" in out


# ── print_operation_plan ──────────────────────────────────────────────────────

def _dry_decision() -> SafetyDecision:
    return SafetyDecision(allowed=True, dry_run=True, refused_reasons=[], warnings=[], required_confirmations=[])


def test_operation_plan_dry_run_label():
    plan = OperationPlan(kind=OperationKind.WIPE, title="Wipe disk 6", steps=["step1"])
    out = _capture(print_operation_plan, plan, _dry_decision())
    assert "DRY RUN" in out


def test_operation_plan_shows_steps():
    plan = OperationPlan(kind=OperationKind.WIPE, title="t", steps=["Clear-Disk -Number 6"])
    out = _capture(print_operation_plan, plan, _dry_decision())
    assert "Clear-Disk" in out


def test_operation_plan_shows_refused():
    decision = SafetyDecision(allowed=False, dry_run=False, refused_reasons=["OS disk"],
                               warnings=[], required_confirmations=[])
    plan = OperationPlan(kind=OperationKind.WIPE, title="t", steps=[])
    out = _capture(print_operation_plan, plan, decision)
    assert "OS disk" in out


def test_operation_plan_shows_warnings():
    decision = SafetyDecision(allowed=True, dry_run=True, refused_reasons=[],
                               warnings=["Large disk"], required_confirmations=[])
    plan = OperationPlan(kind=OperationKind.WIPE, title="t", steps=[])
    out = _capture(print_operation_plan, plan, decision)
    assert "Large disk" in out


# ── print_operation_result ────────────────────────────────────────────────────

def test_operation_result_ok():
    r = OperationResult(ok=True, dry_run=False, message="Done.", steps=["step1"])
    out = _capture(print_operation_result, r)
    assert "Done." in out


def test_operation_result_shows_output():
    r = OperationResult(ok=True, dry_run=False, message="ok", details={"output": "some output text"})
    out = _capture(print_operation_result, r)
    assert "some output text" in out
