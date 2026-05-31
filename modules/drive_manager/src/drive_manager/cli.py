from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .compat import PrivilegesManager, SystemUtils
from .confirmation import confirm_non_usb_disk
from .diagnose import diagnose_disk
from .errors import ConfirmationError, DriveManagerError, SafetyRefusalError
from .image_writer import resolve_image_path, write_image_to_disk
from .models import OperationKind, OperationPlan, OperationResult
from .platforms import get_backend
from .reporting import (
    print_dependency_report,
    print_diagnosis,
    print_disk_detail,
    print_disk_table,
    print_health_smart,
    print_health_summary,
    print_json,
    print_operation_plan,
    print_operation_result,
    print_volumes_table,
)
from .safety import SafetyOptions, SafetyPolicy


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="Output JSON instead of human-readable text.")
    parser.add_argument("-o", "--output-path", default=None, help="Optional output path for future report export support.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")
    parser.add_argument("-D", "--debug", action="store_true", help="Debug output.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet output.")
    parser.add_argument("-t", "--timeout-seconds", type=int, default=120, help="Timeout for backend commands.")
    parser.add_argument("-P", "--plain", action="store_true", help="Disable enhanced terminal UI.")


def add_destructive_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-x", "--execute", action="store_true", help="Actually perform the operation. Default is dry-run.")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip safe confirmations where allowed.")
    parser.add_argument("-L", "--allow-large-disk", action="store_true", help="Allow operation on disks larger than 256 GiB.")
    parser.add_argument("-U", "--allow-non-usb", action="store_true", help="Allow operation on non-USB disks with typed confirmation.")
    parser.add_argument("-F", "--force-unmount", action="store_true", help="Unmount target volumes before writing/formatting.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drive-manager",
        description="Cross-platform disk and USB manager with safety-first dry runs.",
    )
    add_common_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    # ── scan ──────────────────────────────────────────────────────────────────
    scan = sub.add_parser("scan", help="Read-only disk, USB, volume, and drive-letter inspection.")
    scan_sub = scan.add_subparsers(dest="scan_cmd", required=True)

    scan_list = scan_sub.add_parser("list", help="List all disks (one row per physical disk).")
    scan_list.set_defaults(func=cmd_scan_list)

    scan_usb = scan_sub.add_parser("usb", help="List USB/removable disks.")
    scan_usb.set_defaults(func=cmd_scan_usb)

    scan_volumes = scan_sub.add_parser("volumes", help="List all partitions/volumes across all disks.")
    scan_volumes.set_defaults(func=cmd_scan_volumes)

    scan_virtual = scan_sub.add_parser("virtual", help="List mounted virtual disk images.")
    scan_virtual.set_defaults(func=cmd_scan_virtual)

    scan_detail = scan_sub.add_parser("detail", help="Show detailed information about one disk.")
    scan_detail.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    scan_detail.set_defaults(func=cmd_scan_detail)

    scan_letters = scan_sub.add_parser("letters", help="Show drive letters/mountpoints for one disk.")
    scan_letters.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    scan_letters.set_defaults(func=cmd_scan_letters)

    # ── diagnose ──────────────────────────────────────────────────────────────
    diagnose = sub.add_parser("diagnose", help="Diagnose disks and USB media.")
    diagnose_sub = diagnose.add_subparsers(dest="diagnose_cmd", required=True)

    diag_disk = diagnose_sub.add_parser("disk", help="Diagnose a specific disk.")
    diag_disk.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    diag_disk.set_defaults(func=cmd_diagnose_disk)

    diag_usb = diagnose_sub.add_parser("usb", help="Diagnose all USB/removable disks.")
    diag_usb.set_defaults(func=cmd_diagnose_usb)

    # ── mount ─────────────────────────────────────────────────────────────────
    mount = sub.add_parser("mount", help="Mount, unmount, and eject operations.")
    mount_sub = mount.add_subparsers(dest="mount_cmd", required=True)

    mount_list = mount_sub.add_parser("list", help="List mounted partitions/volumes.")
    mount_list.set_defaults(func=cmd_scan_volumes)

    mount_unmount = mount_sub.add_parser("unmount", help="Unmount/dismount a disk's volumes.")
    mount_unmount.add_argument("-d", "--disk-id", default=None, help="Disk number/path/identifier.")
    mount_unmount.add_argument("-p", "--partition-id", default=None, help="Partition, mount path, or drive letter.")
    add_destructive_flags(mount_unmount)
    mount_unmount.set_defaults(func=cmd_mount_unmount)

    mount_eject = mount_sub.add_parser("eject", help="Safely eject/power off a disk.")
    mount_eject.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    mount_eject.set_defaults(func=cmd_mount_eject)

    # ── format ────────────────────────────────────────────────────────────────
    fmt = sub.add_parser("format", help="Format USB media. Dry-run by default.")
    fmt_sub = fmt.add_subparsers(dest="format_cmd", required=True)

    fmt_usb = fmt_sub.add_parser("usb", help="Clear, partition, and format a disk as normal storage.")
    fmt_usb.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    fmt_usb.add_argument("-f", "--filesystem", default="FAT32", help="Filesystem: FAT32, exFAT, NTFS, ext4.")
    fmt_usb.add_argument("-l", "--label", default="USB", help="Filesystem label.")
    add_destructive_flags(fmt_usb)
    fmt_usb.set_defaults(func=cmd_restore_normal)

    # ── wipe ──────────────────────────────────────────────────────────────────
    wipe = sub.add_parser("wipe", help="Wipe disk layout/signatures. Dry-run by default.")
    wipe_sub = wipe.add_subparsers(dest="wipe_cmd", required=True)

    wipe_clear = wipe_sub.add_parser("clear", help="Clear partition data/signatures from a disk.")
    wipe_clear.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    add_destructive_flags(wipe_clear)
    wipe_clear.set_defaults(func=cmd_wipe_clear)

    # ── image ─────────────────────────────────────────────────────────────────
    image = sub.add_parser("image", help="Image download, write, mount, and verification.")
    image_sub = image.add_subparsers(dest="image_cmd", required=True)

    image_write = image_sub.add_parser("write", help="Write a raw image file or URL to a physical disk. Dry-run by default.")
    image_write.add_argument("-d", "--disk-id", required=True, help="Target disk number/path/identifier.")
    image_write.add_argument("-i", "--image-path", default=None, help="Local image path.")
    image_write.add_argument("-u", "--image-url", default=None, help="Image download URL.")
    image_write.add_argument("-H", "--checksum", default=None, help="Expected checksum, e.g. sha256:abc123.")
    image_write.add_argument("-V", "--verify", action="store_true", help="Verify written bytes after writing.")
    add_destructive_flags(image_write)
    image_write.set_defaults(func=cmd_image_write)

    image_mount = image_sub.add_parser("mount", help="Mount an ISO/image as a virtual disk drive.")
    image_mount.add_argument("-i", "--image-path", required=True, help="Local image path (.iso, .vhd, .vhdx, .img).")
    image_mount.add_argument("-u", "--image-url", default=None, help="Download URL for the image (cached locally first).")
    image_mount.add_argument("-H", "--checksum", default=None, help="Expected checksum to verify before mounting.")
    image_mount.add_argument("-l", "--drive-letter", default=None, metavar="LETTER",
                             help="Drive letter to assign (Windows only, e.g. Z or Z:).")
    image_mount.set_defaults(func=cmd_image_mount)

    image_eject = image_sub.add_parser("eject", help="Dismount/eject a mounted virtual disk image.")
    image_eject.add_argument("-i", "--image-path", default=None, help="Original image path used when mounting.")
    image_eject.add_argument("-d", "--disk-id", default=None, help="Virtual disk ID from scan list.")
    image_eject.set_defaults(func=cmd_image_eject)

    image_list = image_sub.add_parser("list", help="List currently mounted disk images.")
    image_list.set_defaults(func=cmd_image_list)

    image_verify = image_sub.add_parser("verify", help="Verify checksum of a local image file.")
    image_verify.add_argument("-i", "--image-path", required=True, help="Local image path.")
    image_verify.add_argument("-H", "--checksum", required=True, help="Expected checksum, e.g. sha256:abc123.")
    image_verify.set_defaults(func=cmd_image_verify)

    # ── usb ───────────────────────────────────────────────────────────────────
    usb = sub.add_parser("usb", help="USB rescan/reset helpers.")
    usb_sub = usb.add_subparsers(dest="usb_cmd", required=True)

    usb_rescan = usb_sub.add_parser("rescan", help="Request storage/udev rescan.")
    usb_rescan.set_defaults(func=cmd_usb_rescan)

    usb_reset = usb_sub.add_parser("reset-device", help="Best-effort reset/query of a USB device.")
    usb_reset.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    usb_reset.set_defaults(func=cmd_usb_reset_device)

    # ── health ────────────────────────────────────────────────────────────────
    health = sub.add_parser("health", help="Disk health and SMART data.")
    health_sub = health.add_subparsers(dest="health_cmd", required=True)

    health_summary = health_sub.add_parser("summary", help="Overview health table for all physical disks.")
    health_summary.set_defaults(func=cmd_health_summary)

    health_smart = health_sub.add_parser("smart", help="Detailed SMART/reliability data for one or all disks.")
    health_smart.add_argument("-d", "--disk-id", default=None, help="Disk number/path/identifier (omit for all disks).")
    health_smart.set_defaults(func=cmd_health_smart)

    # ── restore ───────────────────────────────────────────────────────────────
    restore = sub.add_parser("restore", help="Restore media to normal storage. Dry-run by default.")
    restore_sub = restore.add_subparsers(dest="restore_cmd", required=True)

    restore_normal = restore_sub.add_parser("normal", help="Clear, partition, and format a disk as normal storage.")
    restore_normal.add_argument("-d", "--disk-id", required=True, help="Disk number/path/identifier.")
    restore_normal.add_argument("-f", "--filesystem", default="FAT32", help="Filesystem: FAT32, exFAT, NTFS, ext4.")
    restore_normal.add_argument("-l", "--label", default="USB", help="Filesystem label.")
    add_destructive_flags(restore_normal)
    restore_normal.set_defaults(func=cmd_restore_normal)

    # ── doctor ────────────────────────────────────────────────────────────────
    doctor = sub.add_parser("doctor", help="Dependency, permission, and platform diagnostics.")
    doctor_sub = doctor.add_subparsers(dest="doctor_cmd", required=True)

    doctor_all = doctor_sub.add_parser("all", help="Run all diagnostics (deps + permissions + platform).")
    doctor_all.set_defaults(func=cmd_doctor_all)

    doctor_deps = doctor_sub.add_parser("deps", help="Check backend dependencies.")
    doctor_deps.set_defaults(func=cmd_doctor_deps)

    doctor_permissions = doctor_sub.add_parser("permissions", help="Check administrator/root permissions.")
    doctor_permissions.set_defaults(func=cmd_doctor_permissions)

    doctor_platform = doctor_sub.add_parser("platform", help="Show detected platform.")
    doctor_platform.set_defaults(func=cmd_doctor_platform)

    return parser


def safety_options(args: argparse.Namespace) -> SafetyOptions:
    return SafetyOptions(
        execute=bool(getattr(args, "execute", False)),
        allow_non_usb=bool(getattr(args, "allow_non_usb", False)),
        allow_large_disk=bool(getattr(args, "allow_large_disk", False)),
        yes=bool(getattr(args, "yes", False)),
    )


def evaluate_or_raise(plan: OperationPlan, args: argparse.Namespace):
    decision = SafetyPolicy().evaluate(plan, safety_options(args))
    print_operation_plan(plan, decision)
    if decision.refused_reasons:
        raise SafetyRefusalError("Operation refused by safety policy.")
    if decision.dry_run:
        return decision, False
    disk = plan.target_disk
    if disk and not (disk.is_usb or disk.is_removable):
        confirm_non_usb_disk(disk)
    PrivilegesManager().require_admin()
    return decision, True


# ── scan commands ─────────────────────────────────────────────────────────────

def cmd_scan_list(args: argparse.Namespace) -> int:
    disks = get_backend().list_disks()
    if args.json:
        print_json(disks)
    else:
        print_disk_table(disks)
    return 0


def cmd_scan_usb(args: argparse.Namespace) -> int:
    disks = get_backend().list_usb_disks()
    if args.json:
        print_json(disks)
    else:
        print_disk_table(disks)
    return 0


def cmd_scan_volumes(args: argparse.Namespace) -> int:
    partitions = get_backend().list_volumes()
    if args.json:
        print_json(partitions)
    else:
        print_volumes_table(partitions)
    return 0


def cmd_scan_virtual(args: argparse.Namespace) -> int:
    backend = get_backend()
    if args.json:
        print_json(backend.list_mounted_images())
        return 0
    images = backend.list_mounted_images()
    if not images:
        print("No virtual disk images currently mounted.")
        return 0
    from .reporting import _bold, _c
    print(_bold("Mounted images:"))
    for img in images:
        letter = img.get("DriveLetter") or ""
        size = img.get("Size") or 0
        from .models import format_bytes_binary
        print(f"  {_c('magenta', img.get('ImagePath', ''))}  {letter + ':' if letter else ''}  {format_bytes_binary(size)}")
    return 0


def cmd_scan_detail(args: argparse.Namespace) -> int:
    disk = get_backend().get_disk(args.disk_id)
    if args.json:
        print_json(disk)
    else:
        print_disk_detail(disk)
    return 0


def cmd_scan_letters(args: argparse.Namespace) -> int:
    disk = get_backend().get_disk(args.disk_id)
    result = {"disk_id": disk.disk_id, "drive_letters": disk.drive_letters, "mount_points": disk.mount_points}
    if args.json:
        print_json(result)
    else:
        from .reporting import _bold, _c
        print(_bold(f"Disk {disk.disk_id}: {disk.name_for_confirmation}"))
        letters = ", ".join(f"{l}:" for l in disk.drive_letters) if disk.drive_letters else _c("dim", "(none)")
        mounts = ", ".join(disk.mount_points) if disk.mount_points else _c("dim", "(none)")
        print(f"  Drive letters:  {letters}")
        print(f"  Mount points:   {mounts}")
    return 0


# ── diagnose commands ─────────────────────────────────────────────────────────

def cmd_diagnose_disk(args: argparse.Namespace) -> int:
    disk = get_backend().get_disk(args.disk_id)
    diagnosis = diagnose_disk(disk)
    if args.json:
        print_json(diagnosis)
    else:
        print_diagnosis(diagnosis)
    return 0


def cmd_diagnose_usb(args: argparse.Namespace) -> int:
    backend = get_backend()
    diagnoses = [diagnose_disk(disk) for disk in backend.list_usb_disks()]
    if not diagnoses:
        print("No USB/removable disks found.")
        return 0
    if args.json:
        print_json(diagnoses)
    else:
        for diagnosis in diagnoses:
            print_diagnosis(diagnosis)
            print()
    return 0


# ── mount commands ────────────────────────────────────────────────────────────

def cmd_mount_unmount(args: argparse.Namespace) -> int:
    backend = get_backend()
    if not args.disk_id:
        raise DriveManagerError("For safety, unmount requires -d / --disk-id.")
    disk = backend.get_disk(args.disk_id)
    plan = OperationPlan(
        kind=OperationKind.UNMOUNT,
        title=f"Unmount disk {disk.disk_id}",
        target_disk=disk,
        destructive=False,
        steps=[f"Unmount/dismount volumes for disk {disk.disk_id}"],
    )
    print_operation_plan(plan, SafetyPolicy().evaluate(plan, safety_options(args)))
    if not getattr(args, "execute", False):
        print("Result: No changes were made. Add -x / --execute to unmount.")
        return 0
    result = backend.unmount_disk(disk)
    print_operation_result(result)
    return 0


def cmd_mount_eject(args: argparse.Namespace) -> int:
    result = get_backend().eject_disk(get_backend().get_disk(args.disk_id))
    print_operation_result(result)
    return 0


# ── restore/format/wipe commands ──────────────────────────────────────────────

def cmd_restore_normal(args: argparse.Namespace) -> int:
    backend = get_backend()
    disk = backend.get_disk(args.disk_id)
    steps = backend.build_restore_normal_steps(disk, args.filesystem, args.label)
    plan = OperationPlan(
        kind=OperationKind.RESTORE,
        title=f"Restore disk {disk.disk_id} to normal {args.filesystem} storage",
        target_disk=disk,
        filesystem=args.filesystem,
        label=args.label,
        force_unmount=bool(getattr(args, "force_unmount", False)),
        steps=steps,
        destructive=True,
    )
    _, should_execute = evaluate_or_raise(plan, args)
    if not should_execute:
        return 0
    result = backend.restore_normal(disk, args.filesystem, args.label)
    print_operation_result(result)
    return 0


def cmd_wipe_clear(args: argparse.Namespace) -> int:
    backend = get_backend()
    disk = backend.get_disk(args.disk_id)
    plan = OperationPlan(
        kind=OperationKind.WIPE,
        title=f"Clear disk {disk.disk_id}",
        target_disk=disk,
        steps=[f"Unmount target disk {disk.disk_id}", "Remove partition/filesystem signatures or partition table"],
        destructive=True,
    )
    _, should_execute = evaluate_or_raise(plan, args)
    if not should_execute:
        return 0
    result = backend.clear_disk(disk)
    print_operation_result(result)
    return 0


# ── image commands ────────────────────────────────────────────────────────────

def cmd_image_write(args: argparse.Namespace) -> int:
    backend = get_backend()
    disk = backend.get_disk(args.disk_id)
    image_path_for_plan = Path(args.image_path).expanduser() if args.image_path else None
    steps = [
        "Resolve local image path or download image URL to cache",
        "Verify checksum before writing if -H / --checksum was supplied",
        f"Unmount target disk volumes for disk {disk.disk_id}",
        f"Open raw target {backend.raw_device_path(disk)}",
        "Stream image bytes to target disk",
        "Flush disk buffers",
    ]
    if args.verify:
        steps.append("Read back image-sized prefix and compare to source image")
    plan = OperationPlan(
        kind=OperationKind.IMAGE_WRITE,
        title=f"Write raw image to disk {disk.disk_id}",
        target_disk=disk,
        image_path=image_path_for_plan,
        image_url=args.image_url,
        verify=args.verify,
        force_unmount=bool(getattr(args, "force_unmount", False)),
        steps=steps,
        destructive=True,
        writes_raw_disk=True,
    )
    _, should_execute = evaluate_or_raise(plan, args)
    if not should_execute:
        return 0
    image_path = resolve_image_path(image_path_for_plan, args.image_url, args.checksum)
    result = write_image_to_disk(backend, disk, image_path, verify=args.verify)
    print_operation_result(result)
    return 0


def cmd_image_mount(args: argparse.Namespace) -> int:
    backend = get_backend()
    # Resolve path — download if URL given
    local_path: Path | None = Path(args.image_path).expanduser().resolve() if args.image_path else None
    if args.image_url or not local_path:
        local_path = resolve_image_path(local_path, getattr(args, "image_url", None), getattr(args, "checksum", None))
    elif args.checksum:
        from .hashing import hash_file, parse_checksum_spec, verify_checksum
        if not verify_checksum(local_path, args.checksum):
            algorithm, expected = parse_checksum_spec(args.checksum)
            actual = hash_file(local_path, algorithm)
            print(f"Checksum mismatch for {local_path}: expected {expected}, got {actual}", file=sys.stderr)
            return 1

    drive_letter = getattr(args, "drive_letter", None)
    result = backend.mount_image(local_path, drive_letter)
    print_operation_result(result)
    return 0 if result.ok else 1


def cmd_image_eject(args: argparse.Namespace) -> int:
    backend = get_backend()
    image_path_arg = getattr(args, "image_path", None)
    disk_id_arg = getattr(args, "disk_id", None)

    if not image_path_arg and not disk_id_arg:
        print("Provide -i / --image-path or -d / --disk-id.", file=sys.stderr)
        return 1

    if image_path_arg:
        image_path = Path(image_path_arg).expanduser().resolve()
    else:
        # Look up image path from virtual disk
        disk = backend.get_disk(disk_id_arg)
        img_path_str = disk.raw.get("image_path")
        if not img_path_str:
            print(f"Disk {disk_id_arg} does not appear to be a mounted virtual image.", file=sys.stderr)
            return 1
        image_path = Path(img_path_str)

    result = backend.dismount_image(image_path)
    print_operation_result(result)
    return 0 if result.ok else 1


def cmd_image_list(args: argparse.Namespace) -> int:
    return cmd_scan_virtual(args)


def cmd_image_verify(args: argparse.Namespace) -> int:
    from .hashing import hash_file, parse_checksum_spec

    image_path = Path(args.image_path).expanduser().resolve()
    algorithm, expected = parse_checksum_spec(args.checksum)
    actual = hash_file(image_path, algorithm)
    ok = actual.lower() == expected.lower()
    result = {"ok": ok, "algorithm": algorithm, "expected": expected, "actual": actual, "path": str(image_path)}
    if args.json:
        print_json(result)
    else:
        from .reporting import _bold, _c
        print(f"  Path:      {image_path}")
        print(f"  Algorithm: {algorithm}")
        print(f"  Expected:  {expected}")
        print(f"  Actual:    {actual}")
        outcome = _c("green", "OK") if ok else _c("red", "FAILED")
        print(f"  Result:    {outcome}")
    return 0 if ok else 1


# ── usb commands ──────────────────────────────────────────────────────────────

def cmd_usb_rescan(args: argparse.Namespace) -> int:
    result = get_backend().rescan()
    print_operation_result(result)
    return 0 if result.ok else 1


def cmd_usb_reset_device(args: argparse.Namespace) -> int:
    backend = get_backend()
    result = backend.reset_usb_device(backend.get_disk(args.disk_id))
    print_operation_result(result)
    return 0 if result.ok else 1


# ── health commands ───────────────────────────────────────────────────────────

def cmd_health_summary(args: argparse.Namespace) -> int:
    backend = get_backend()
    result = backend.health_summary()
    if args.json:
        print_json(result)
        return 0 if result.ok else 1
    if not result.ok:
        print_operation_result(result)
        return 1
    # result.message signals how to render
    if result.message == "health_summary_json":
        print_health_summary(result.details.get("output", ""))
    else:
        print_operation_result(result)
    return 0


def cmd_health_smart(args: argparse.Namespace) -> int:
    backend = get_backend()
    disk = backend.get_disk(args.disk_id) if getattr(args, "disk_id", None) else None
    result = backend.health_smart(disk)
    if args.json:
        print_json(result)
        return 0 if result.ok else 1
    if not result.ok:
        print_operation_result(result)
        return 1
    if result.message == "health_smart_json":
        disk_id_str = disk.disk_id if disk else None
        print_health_smart(result.details.get("output", ""), disk_id_str)
    else:
        print_operation_result(result)
    return 0


# ── doctor commands ───────────────────────────────────────────────────────────

def cmd_doctor_deps(args: argparse.Namespace) -> int:
    report = get_backend().doctor_dependencies()
    if args.json:
        print_json(report)
    else:
        print_dependency_report(report)
    return 0 if not report.missing_required else 1


def cmd_doctor_permissions(args: argparse.Namespace) -> int:
    pm = PrivilegesManager()
    is_admin = pm.is_admin()
    result = {"is_admin_or_root": is_admin}
    if args.json:
        print_json(result)
    else:
        from .reporting import _c
        status = _c("green", "yes") if is_admin else _c("yellow", "no (some operations require elevation)")
        print(f"Administrator/root: {status}")
    return 0 if is_admin else 1


def cmd_doctor_platform(args: argparse.Namespace) -> int:
    sysu = SystemUtils()
    result = {
        "os_name": sysu.os_name,
        "is_windows": sysu.is_windows(),
        "is_linux": sysu.is_linux(),
        "is_wsl2": sysu.is_wsl2(),
        "is_termux": sysu.is_termux(),
    }
    if args.json:
        print_json(result)
    else:
        from .reporting import _bold, _c
        print(_bold(f"Platform: {sysu.os_name}"))
        for key, value in result.items():
            if key == "os_name":
                continue
            val_str = _c("green", "yes") if value else _c("dim", "no")
            print(f"  {key}: {val_str}")
    return 0


def cmd_doctor_all(args: argparse.Namespace) -> int:
    rc = 0
    print()
    rc |= cmd_doctor_platform(args)
    print()
    rc |= cmd_doctor_permissions(args)
    print()
    rc |= cmd_doctor_deps(args)
    return rc


# ── entry point ───────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfirmationError as exc:
        print(f"Confirmation failed: {exc}", file=sys.stderr)
        return 2
    except SafetyRefusalError as exc:
        print(f"Safety refusal: {exc}", file=sys.stderr)
        return 3
    except PermissionError as exc:
        print(f"Permission error: {exc}", file=sys.stderr)
        return 4
    except DriveManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
