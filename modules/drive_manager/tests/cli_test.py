"""Tests for cli.py argument parsing and command dispatch."""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from drive_manager.cli import build_parser, main
from drive_manager.models import (
    DependencyCheck,
    DependencyReport,
    DiskInfo,
    OperationResult,
    PartitionInfo,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _usb(disk_id: str = "6") -> DiskInfo:
    return DiskInfo(disk_id=disk_id, friendly_name="PNY USB", bus_type="USB",
                    size_bytes=16 * 1024**3, is_usb=True, is_removable=True,
                    operational_status="Online", health_status="Healthy")


def _nvme(disk_id: str = "3") -> DiskInfo:
    return DiskInfo(disk_id=disk_id, friendly_name="CT4000T710SSD8", bus_type="NVMe",
                    size_bytes=4 * 1024**4, operational_status="Online",
                    health_status="Healthy", is_system_disk=True)


def _ok_result(message: str = "ok") -> OperationResult:
    return OperationResult(ok=True, dry_run=False, message=message)


def _run(argv: list[str], backend_mock: MagicMock) -> int:
    with patch("drive_manager.cli.get_backend", return_value=backend_mock):
        buf = StringIO()
        with patch("sys.stdout", buf):
            return main(argv)


def _backend(disks=None, usb_disks=None) -> MagicMock:
    m = MagicMock()
    m.list_disks.return_value = disks or [_nvme(), _usb()]
    m.list_usb_disks.return_value = usb_disks or [_usb()]
    m.list_volumes.return_value = []
    m.list_mounted_images.return_value = []
    return m


# ── parser structure (original tests preserved) ───────────────────────────────

def test_cli_parses_scan_detail():
    args = build_parser().parse_args(["scan", "detail", "-d", "6"])
    assert args.command == "scan"
    assert args.scan_cmd == "detail"
    assert args.disk_id == "6"


def test_cli_parses_image_write_flags():
    args = build_parser().parse_args(["image", "write", "-d", "6", "-i", "x.img", "-x", "-V", "-F"])
    assert args.image_cmd == "write"
    assert args.execute is True
    assert args.verify is True
    assert args.force_unmount is True


# ── new parser tests ──────────────────────────────────────────────────────────

def test_scan_list_parses():
    from drive_manager.cli import cmd_scan_list
    assert build_parser().parse_args(["scan", "list"]).func is cmd_scan_list


def test_scan_usb_parses():
    from drive_manager.cli import cmd_scan_usb
    assert build_parser().parse_args(["scan", "usb"]).func is cmd_scan_usb


def test_scan_virtual_parses():
    from drive_manager.cli import cmd_scan_virtual
    assert build_parser().parse_args(["scan", "virtual"]).func is cmd_scan_virtual


def test_scan_detail_requires_disk_id():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["scan", "detail"])


def test_image_mount_parses():
    args = build_parser().parse_args(["image", "mount", "-i", "/tmp/x.iso"])
    assert args.image_path == "/tmp/x.iso"


def test_image_mount_drive_letter():
    args = build_parser().parse_args(["image", "mount", "-i", "/tmp/x.iso", "-l", "Z"])
    assert args.drive_letter == "Z"


def test_image_eject_by_path():
    args = build_parser().parse_args(["image", "eject", "-i", "/tmp/x.iso"])
    assert args.image_path == "/tmp/x.iso"


def test_image_eject_by_disk_id():
    args = build_parser().parse_args(["image", "eject", "-d", "7"])
    assert args.disk_id == "7"


def test_image_list_parses():
    from drive_manager.cli import cmd_image_list
    assert build_parser().parse_args(["image", "list"]).func is cmd_image_list


def test_health_summary_parses():
    from drive_manager.cli import cmd_health_summary
    assert build_parser().parse_args(["health", "summary"]).func is cmd_health_summary


def test_health_smart_parses():
    from drive_manager.cli import cmd_health_smart
    assert build_parser().parse_args(["health", "smart"]).func is cmd_health_smart


def test_health_smart_with_disk_id():
    assert build_parser().parse_args(["health", "smart", "-d", "2"]).disk_id == "2"


def test_doctor_all_parses():
    from drive_manager.cli import cmd_doctor_all
    assert build_parser().parse_args(["doctor", "all"]).func is cmd_doctor_all


def test_json_flag_global():
    assert build_parser().parse_args(["-j", "scan", "list"]).json is True


def test_destructive_flags_all():
    args = build_parser().parse_args(["wipe", "clear", "-d", "6", "-x", "-L", "-U", "-y"])
    assert args.execute and args.allow_large_disk and args.allow_non_usb and args.yes


# ── command execution (mocked backend) ───────────────────────────────────────

def test_cmd_scan_list_returns_0():
    assert _run(["scan", "list"], _backend()) == 0


def test_cmd_scan_usb_returns_0():
    assert _run(["scan", "usb"], _backend()) == 0


def test_cmd_scan_volumes_returns_0():
    assert _run(["scan", "volumes"], _backend()) == 0


def test_cmd_scan_detail_returns_0():
    b = _backend()
    b.get_disk.return_value = _nvme()
    assert _run(["scan", "detail", "-d", "3"], b) == 0


def test_cmd_scan_letters_returns_0():
    b = _backend()
    b.get_disk.return_value = _usb()
    assert _run(["scan", "letters", "-d", "6"], b) == 0


def test_cmd_diagnose_disk_usb_returns_0():
    b = _backend()
    b.get_disk.return_value = _usb()
    assert _run(["diagnose", "disk", "-d", "6"], b) == 0


def test_cmd_diagnose_usb_returns_0():
    assert _run(["diagnose", "usb"], _backend()) == 0


def test_cmd_diagnose_usb_no_usb():
    assert _run(["diagnose", "usb"], _backend(usb_disks=[])) == 0


def test_cmd_health_summary_json_output():
    b = _backend()
    b.health_summary.return_value = OperationResult(
        ok=True, dry_run=False, message="health_summary_json",
        details={"output": json.dumps([{"Number": "2", "Name": "WDC", "MediaType": "HDD",
                                         "BusType": "SATA", "Size": 10 * 1024**4,
                                         "OperationalStatus": "OK", "HealthStatus": "Healthy"}])},
    )
    assert _run(["health", "summary"], b) == 0


def test_cmd_health_summary_fail():
    b = _backend()
    b.health_summary.return_value = OperationResult(ok=False, dry_run=False, message="smartctl not found.")
    assert _run(["health", "summary"], b) == 1


def test_cmd_health_smart_all():
    b = _backend()
    b.health_smart.return_value = OperationResult(
        ok=True, dry_run=False, message="health_smart_json",
        details={"output": json.dumps([{"Number": "3", "Name": "NVMe", "MediaType": "SSD",
                                         "BusType": "NVMe", "Size": 4 * 1024**4,
                                         "OperationalStatus": "OK", "HealthStatus": "Healthy"}])},
    )
    assert _run(["health", "smart"], b) == 0


def test_cmd_health_smart_one_disk():
    b = _backend()
    b.get_disk.return_value = _nvme()
    b.health_smart.return_value = OperationResult(
        ok=True, dry_run=False, message="health_smart_json",
        details={"output": json.dumps({"Number": "3", "Name": "NVMe", "MediaType": "SSD",
                                        "BusType": "NVMe", "Size": 4 * 1024**4,
                                        "OperationalStatus": "OK", "HealthStatus": "Healthy"})},
    )
    assert _run(["health", "smart", "-d", "3"], b) == 0


def test_cmd_doctor_deps_ok():
    b = _backend()
    b.doctor_dependencies.return_value = DependencyReport(
        platform="windows", checks=[DependencyCheck("pwsh", True, "required for backend")]
    )
    assert _run(["doctor", "deps"], b) == 0


def test_cmd_doctor_deps_missing():
    b = _backend()
    b.doctor_dependencies.return_value = DependencyReport(
        platform="windows", checks=[DependencyCheck("missing", False, "required for something")]
    )
    assert _run(["doctor", "deps"], b) == 1


def test_cmd_image_mount_ok(tmp_path):
    img = tmp_path / "test.iso"
    img.write_bytes(b"\x00" * 1024)
    b = _backend()
    b.mount_image.return_value = _ok_result(f"Image mounted: {img}")
    assert _run(["image", "mount", "-i", str(img)], b) == 0


def test_cmd_image_eject_by_path(tmp_path):
    img = tmp_path / "test.iso"
    img.write_bytes(b"\x00" * 1024)
    b = _backend()
    b.dismount_image.return_value = _ok_result(f"Image dismounted: {img}")
    assert _run(["image", "eject", "-i", str(img)], b) == 0


def test_cmd_image_eject_no_args_returns_1():
    assert _run(["image", "eject"], _backend()) == 1


def test_cmd_image_list_empty():
    assert _run(["image", "list"], _backend()) == 0


def test_cmd_image_verify_ok(tmp_path):
    import hashlib
    data = b"test image data"
    f = tmp_path / "img.iso"
    f.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert _run(["image", "verify", "-i", str(f), "-H", f"sha256:{digest}"], _backend()) == 0


def test_cmd_image_verify_fail(tmp_path):
    f = tmp_path / "img.iso"
    f.write_bytes(b"data")
    assert _run(["image", "verify", "-i", str(f), "-H", "sha256:wrongdigest"], _backend()) == 1


def test_cmd_wipe_dry_run():
    b = _backend()
    b.get_disk.return_value = _usb()
    assert _run(["wipe", "clear", "-d", "6"], b) == 0


def test_cmd_usb_rescan():
    b = _backend()
    b.rescan.return_value = _ok_result("Rescan done.")
    assert _run(["usb", "rescan"], b) == 0


# ── image write (bootable USB) ────────────────────────────────────────────────

def test_image_write_parses_url():
    args = build_parser().parse_args(["image", "write", "-d", "6", "-u", "https://example.com/ubuntu.iso"])
    assert args.image_url == "https://example.com/ubuntu.iso"
    assert args.disk_id == "6"
    assert args.image_path is None


def test_image_write_parses_checksum():
    args = build_parser().parse_args(["image", "write", "-d", "6", "-i", "x.img", "-H", "sha256:abc123"])
    assert args.checksum == "sha256:abc123"


def test_image_write_parses_all_flags():
    args = build_parser().parse_args([
        "image", "write", "-d", "6",
        "-u", "https://example.com/fedora.iso",
        "-H", "sha256:deadbeef",
        "-V", "-x", "-y", "-L", "-U", "-F",
    ])
    assert args.image_url == "https://example.com/fedora.iso"
    assert args.checksum == "sha256:deadbeef"
    assert args.verify is True
    assert args.execute is True
    assert args.yes is True
    assert args.allow_large_disk is True
    assert args.allow_non_usb is True
    assert args.force_unmount is True


def test_cmd_image_write_dry_run_returns_0(tmp_path):
    """Without -x the operation is a dry run: returns 0 and does not write."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\x00" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with patch("drive_manager.cli.write_image_to_disk") as mock_write:
        rc = _run(["image", "write", "-d", "6", "-i", str(img)], b)
    assert rc == 0
    mock_write.assert_not_called()


def test_cmd_image_write_execute_local_path(tmp_path):
    """With -x and a local image path, write_image_to_disk is called."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\xAB" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with (
        patch("drive_manager.cli.PrivilegesManager") as mock_pm,
        patch("drive_manager.cli.write_image_to_disk") as mock_write,
    ):
        mock_pm.return_value.require_admin.return_value = None
        mock_write.return_value = _ok_result("Wrote 512 bytes.")
        rc = _run(["image", "write", "-d", "6", "-i", str(img), "-x"], b)
    assert rc == 0
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs.get("verify") is False


def test_cmd_image_write_execute_with_url(tmp_path):
    """With -x and -u URL, resolve_image_path downloads it then write_image_to_disk is called."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\xAB" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with (
        patch("drive_manager.cli.PrivilegesManager") as mock_pm,
        patch("drive_manager.cli.resolve_image_path", return_value=img) as mock_resolve,
        patch("drive_manager.cli.write_image_to_disk") as mock_write,
    ):
        mock_pm.return_value.require_admin.return_value = None
        mock_write.return_value = _ok_result("Wrote 512 bytes.")
        rc = _run(["image", "write", "-d", "6", "-u", "https://example.com/ubuntu.iso", "-x"], b)
    assert rc == 0
    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args[0][1] == "https://example.com/ubuntu.iso"
    mock_write.assert_called_once()


def test_cmd_image_write_passes_verify_flag(tmp_path):
    """--verify / -V is forwarded to write_image_to_disk as verify=True."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\xAB" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with (
        patch("drive_manager.cli.PrivilegesManager") as mock_pm,
        patch("drive_manager.cli.write_image_to_disk") as mock_write,
    ):
        mock_pm.return_value.require_admin.return_value = None
        mock_write.return_value = _ok_result("Wrote and verified.")
        _run(["image", "write", "-d", "6", "-i", str(img), "-x", "-V"], b)
    _, kwargs = mock_write.call_args
    assert kwargs.get("verify") is True


def test_cmd_image_write_checksum_forwarded(tmp_path):
    """--checksum / -H is forwarded to resolve_image_path."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\xAB" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with (
        patch("drive_manager.cli.PrivilegesManager") as mock_pm,
        patch("drive_manager.cli.resolve_image_path", return_value=img) as mock_resolve,
        patch("drive_manager.cli.write_image_to_disk") as mock_write,
    ):
        mock_pm.return_value.require_admin.return_value = None
        mock_write.return_value = _ok_result("Wrote.")
        _run(["image", "write", "-d", "6", "-i", str(img), "-x", "-H", "sha256:aabbcc"], b)
    call_args = mock_resolve.call_args
    assert call_args[0][2] == "sha256:aabbcc"


def test_cmd_image_write_refused_on_system_disk(tmp_path):
    """Writing to a system/OS disk is always refused (rc=3 = SafetyRefusalError)."""
    b = _backend()
    b.get_disk.return_value = _nvme()  # is_system_disk=True
    b.raw_device_path.return_value = tmp_path / "fake_nvme"
    rc = _run(["image", "write", "-d", "3", "-i", "x.img", "-x"], b)
    assert rc == 3


def test_cmd_image_write_refused_on_large_non_usb_without_flag(tmp_path):
    """Large NVMe without -L and -U is refused (rc=3)."""
    b = _backend()
    b.get_disk.return_value = _nvme()
    b.raw_device_path.return_value = tmp_path / "fake_nvme"
    rc = _run(["image", "write", "-d", "3", "-i", "x.img", "-x", "-U"], b)
    assert rc == 3  # still refused because is_system_disk


def test_cmd_image_write_result_failure_returns_1(tmp_path):
    """If write_image_to_disk returns ok=False, rc=1."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\xAB" * 512)
    b = _backend()
    b.get_disk.return_value = _usb()
    b.raw_device_path.return_value = tmp_path / "fake_disk"
    with (
        patch("drive_manager.cli.PrivilegesManager") as mock_pm,
        patch("drive_manager.cli.write_image_to_disk") as mock_write,
    ):
        mock_pm.return_value.require_admin.return_value = None
        mock_write.return_value = OperationResult(ok=False, dry_run=False, message="Disk I/O error.")
        rc = _run(["image", "write", "-d", "6", "-i", str(img), "-x"], b)
    assert rc == 1


# ── image mount — URL and drive letter flows ──────────────────────────────────

def test_cmd_image_mount_with_url_downloads_and_mounts(tmp_path):
    """When -u URL is given, the image is downloaded then mounted."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\x00" * 512)
    b = _backend()
    b.mount_image.return_value = _ok_result("Mounted.")
    with patch("drive_manager.cli.resolve_image_path", return_value=img) as mock_resolve:
        rc = _run(["image", "mount", "-i", str(img), "-u", "https://example.com/ubuntu.iso"], b)
    assert rc == 0
    mock_resolve.assert_called_once()
    b.mount_image.assert_called_once()


def test_cmd_image_mount_drive_letter_passed_to_backend(tmp_path):
    """--drive-letter / -l is forwarded to backend.mount_image."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\x00" * 512)
    b = _backend()
    b.mount_image.return_value = _ok_result("Mounted as Z:.")
    rc = _run(["image", "mount", "-i", str(img), "-l", "Z"], b)
    assert rc == 0
    b.mount_image.assert_called_once_with(img.resolve(), "Z")


def test_cmd_image_mount_no_letter_passes_none(tmp_path):
    """Omitting -l passes drive_letter=None to backend."""
    img = tmp_path / "ubuntu.iso"
    img.write_bytes(b"\x00" * 512)
    b = _backend()
    b.mount_image.return_value = _ok_result("Mounted.")
    rc = _run(["image", "mount", "-i", str(img)], b)
    assert rc == 0
    b.mount_image.assert_called_once_with(img.resolve(), None)
