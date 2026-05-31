"""Tests for safety.py."""
from __future__ import annotations

from drive_manager.models import DiskInfo, OperationKind, OperationPlan
from drive_manager.safety import DEFAULT_MAX_DESTRUCTIVE_BYTES, SafetyOptions, SafetyPolicy


def _plan(disk: DiskInfo, kind: OperationKind = OperationKind.WIPE) -> OperationPlan:
    return OperationPlan(kind=kind, title="test", target_disk=disk, destructive=True, steps=["step"])


def _usb(**kw) -> DiskInfo:
    base: dict = dict(disk_id="6", friendly_name="USB", bus_type="USB",
                      size_bytes=16 * 1024**3, is_usb=True)
    base.update(kw)
    return DiskInfo(**base)


def _nvme(**kw) -> DiskInfo:
    # 128 GiB — stays under DEFAULT_MAX_DESTRUCTIVE_BYTES (256 GiB) for non-USB tests
    base: dict = dict(disk_id="3", friendly_name="NVMe", bus_type="NVMe",
                      size_bytes=128 * 1024**3)
    base.update(kw)
    return DiskInfo(**base)


# ── original tests (preserved) ────────────────────────────────────────────────

def test_usb_dry_run_allowed():
    decision = SafetyPolicy().evaluate(_plan(_usb()), SafetyOptions())
    assert decision.allowed
    assert decision.dry_run
    assert not decision.refused_reasons


def test_zero_size_refused_even_dry_run_reports_refusal():
    disk = _usb(size_bytes=0, operational_status="No Media")
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True))
    assert not decision.allowed
    assert any("zero" in r.lower() for r in decision.refused_reasons)


def test_os_disk_refused_no_override():
    disk = _nvme(is_system_disk=True)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True, allow_non_usb=True, allow_large_disk=True))
    assert not decision.allowed
    assert any("OS" in r or "boot" in r for r in decision.refused_reasons)


def test_large_disk_requires_flag():
    disk = _usb(size_bytes=DEFAULT_MAX_DESTRUCTIVE_BYTES + 1)
    assert not SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True)).allowed
    assert SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True, allow_large_disk=True)).allowed


def test_non_usb_requires_allow_and_confirmations():
    disk = _nvme()
    without = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True))
    assert not without.allowed
    assert without.required_confirmations

    with_flag = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True, allow_non_usb=True))
    assert with_flag.allowed
    assert with_flag.required_confirmations


# ── new tests ─────────────────────────────────────────────────────────────────

def test_dry_run_by_default():
    decision = SafetyPolicy().evaluate(_plan(_usb()), SafetyOptions())
    assert decision.dry_run


def test_execute_flag_removes_dry_run_for_usb():
    decision = SafetyPolicy().evaluate(_plan(_usb()), SafetyOptions(execute=True))
    assert not decision.dry_run


def test_boot_disk_refused():
    disk = DiskInfo(disk_id="0", friendly_name="Boot", bus_type="NVMe",
                    size_bytes=512 * 1024**3, is_boot_disk=True)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True, allow_non_usb=True))
    assert not decision.allowed


def test_read_only_plan_always_allowed():
    disk = _nvme(is_system_disk=True)
    plan = OperationPlan(kind=OperationKind.READ_ONLY, title="scan", target_disk=disk,
                         destructive=False, steps=["scan"])
    decision = SafetyPolicy().evaluate(plan, SafetyOptions())
    assert decision.allowed


def test_removable_treated_like_usb():
    disk = DiskInfo(disk_id="7", friendly_name="SD Card", size_bytes=8 * 1024**3,
                    is_removable=True)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True))
    assert decision.allowed


def test_safety_decision_has_required_fields():
    decision = SafetyPolicy().evaluate(_plan(_usb()), SafetyOptions())
    assert isinstance(decision.refused_reasons, list)
    assert isinstance(decision.warnings, list)
    assert isinstance(decision.required_confirmations, list)


def test_large_disk_warning_present_without_flag():
    disk = _usb(size_bytes=DEFAULT_MAX_DESTRUCTIVE_BYTES + 1)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions())
    # Refused because large + execute not set OR large + flag not set
    assert not decision.allowed or decision.warnings or decision.refused_reasons


def test_no_target_disk_plan_allowed():
    plan = OperationPlan(kind=OperationKind.HEALTH, title="health", steps=["Get-PhysicalDisk"])
    decision = SafetyPolicy().evaluate(plan, SafetyOptions())
    assert decision.allowed


def test_exact_max_size_not_refused():
    disk = _usb(size_bytes=DEFAULT_MAX_DESTRUCTIVE_BYTES)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True))
    assert decision.allowed


def test_one_byte_over_max_refused():
    disk = _usb(size_bytes=DEFAULT_MAX_DESTRUCTIVE_BYTES + 1)
    decision = SafetyPolicy().evaluate(_plan(disk), SafetyOptions(execute=True))
    assert not decision.allowed
