"""Tests for diagnose.py."""
from __future__ import annotations

from drive_manager.diagnose import diagnose_disk
from drive_manager.models import DiskInfo, Severity


def _usb(size_bytes: int = 16 * 1024**3, status: str = "Online", **kw) -> DiskInfo:
    return DiskInfo(
        disk_id="6",
        friendly_name="Test USB",
        bus_type="USB",
        size_bytes=size_bytes,
        operational_status=status,
        health_status="Healthy",
        is_usb=True,
        is_removable=True,
        **kw,
    )


# ── existing tests (preserved) ────────────────────────────────────────────────

def test_bad_usb_no_media_diagnosis():
    disk = DiskInfo(disk_id="6", friendly_name="Lexar", bus_type="USB", size_bytes=0,
                    operational_status="No Media", is_usb=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "BAD_MEDIA_OR_EMPTY_READER"
    assert d.severity == Severity.ERROR
    assert d.is_probably_bad


def test_usable_usb_diagnosis():
    disk = DiskInfo(disk_id="6", friendly_name="PNY USB 3.0 FD", bus_type="USB",
                    size_bytes=16 * 1024**3, operational_status="Online", is_usb=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "USB_MEDIA_PRESENT"
    assert not d.is_probably_bad

# ── new tests ─────────────────────────────────────────────────────────────────

def test_zero_size_always_bad_media():
    d = diagnose_disk(_usb(size_bytes=0, status="No Media"))
    assert d.diagnosis == "BAD_MEDIA_OR_EMPTY_READER"
    assert d.severity == Severity.ERROR
    assert d.is_probably_bad


def test_usb_media_present_severity_ok():
    d = diagnose_disk(_usb())
    assert d.severity == Severity.OK


def test_usb_media_present_has_recommended_actions():
    d = diagnose_disk(_usb())
    assert d.recommended_actions


def test_system_disk_warning():
    disk = DiskInfo(disk_id="0", friendly_name="OS Disk", bus_type="NVMe",
                    size_bytes=512 * 1024**3, is_system_disk=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "SYSTEM_OR_BOOT_DISK"
    assert d.severity == Severity.WARNING
    assert not d.is_probably_bad


def test_boot_disk_warning():
    disk = DiskInfo(disk_id="0", friendly_name="Boot Disk", bus_type="NVMe",
                    size_bytes=512 * 1024**3, is_boot_disk=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "SYSTEM_OR_BOOT_DISK"
    assert d.severity == Severity.WARNING


def test_plain_sata_disk_info():
    disk = DiskInfo(disk_id="2", friendly_name="WDC HDD", bus_type="SATA",
                    size_bytes=10 * 1024**4, operational_status="Online")
    d = diagnose_disk(disk)
    assert d.diagnosis == "DISK_PRESENT"
    assert d.severity == Severity.INFO
    assert not d.is_probably_bad


def test_usb_flag_overrides_disk_present():
    disk = DiskInfo(disk_id="6", friendly_name="PNY", bus_type="USB",
                    size_bytes=16 * 1024**3, is_usb=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "USB_MEDIA_PRESENT"


def test_removable_without_usb_bus_still_gets_usb_diagnosis():
    disk = DiskInfo(disk_id="7", friendly_name="SD Card", size_bytes=8 * 1024**3, is_removable=True)
    d = diagnose_disk(disk)
    assert d.diagnosis == "USB_MEDIA_PRESENT"


def test_evidence_contains_usb_indicator():
    d = diagnose_disk(_usb())
    assert any("USB" in e or "removable" in e for e in d.evidence)


def test_non_usb_evidence_not_classified_usb():
    disk = DiskInfo(disk_id="2", friendly_name="HDD", bus_type="SATA", size_bytes=1 * 1024**4)
    d = diagnose_disk(disk)
    assert any("not classified" in e.lower() for e in d.evidence)


def test_evidence_includes_size():
    d = diagnose_disk(_usb(size_bytes=32 * 1024**3))
    assert any("size" in e.lower() or "GiB" in e for e in d.evidence)


def test_evidence_includes_operational_status():
    d = diagnose_disk(_usb(status="Online"))
    assert any("Online" in e for e in d.evidence)


def test_bad_media_has_causes():
    disk = DiskInfo(disk_id="6", bus_type="USB", size_bytes=0, operational_status="No Media", is_usb=True)
    d = diagnose_disk(disk)
    assert d.likely_causes


def test_bad_media_has_actions():
    disk = DiskInfo(disk_id="6", bus_type="USB", size_bytes=0, operational_status="No Media", is_usb=True)
    d = diagnose_disk(disk)
    assert d.recommended_actions


def test_disk_id_preserved_in_diagnosis():
    disk = DiskInfo(disk_id="42", bus_type="SATA", size_bytes=1 * 1024**4)
    d = diagnose_disk(disk)
    assert d.disk_id == "42"
