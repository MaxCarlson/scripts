from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any

from .models import (
    DependencyReport,
    DiskInfo,
    OperationPlan,
    OperationResult,
    PartitionInfo,
    SafetyDecision,
    Severity,
    UsbDiagnosis,
    dataclass_to_dict,
    format_bytes_binary,
)

# ── ANSI colors ───────────────────────────────────────────────────────────────

_COLORS: dict[str, str] = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
    "white":   "\033[97m",
    "gray":    "\033[90m",
}


def _use_color() -> bool:
    return sys.stdout.isatty()


def _c(color: str, text: str) -> str:
    if not _use_color():
        return text
    return _COLORS.get(color, "") + text + _COLORS["reset"]


def _bold(text: str) -> str:
    return _c("bold", text)


# ── Table helpers ─────────────────────────────────────────────────────────────

def _row(cols: list[str], widths: list[int], colors: list[str] | None = None) -> str:
    parts = []
    for i, (col, width) in enumerate(zip(cols, widths)):
        cell = str(col).ljust(width)
        if colors and i < len(colors) and colors[i]:
            cell = _c(colors[i], cell)
        parts.append(cell)
    return "  ".join(parts)


def _table(
    headers: list[str],
    rows: list[list[str]],
    row_colors: list[list[str]] | None = None,
) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    header_colored = [_c("bold", h) for h in headers]
    print("  ".join(h.ljust(w) for h, w in zip(header_colored, widths)))
    print("  ".join(_c("dim", "-" * w) for w in widths))
    for idx, row in enumerate(rows):
        colors = row_colors[idx] if row_colors else None
        print(_row(row, widths, colors))


def print_json(value: Any) -> None:
    print(json.dumps(dataclass_to_dict(value), indent=2, sort_keys=True))


# ── Disk table ────────────────────────────────────────────────────────────────

def _disk_row_color(disk: DiskInfo) -> str:
    if disk.is_system_disk or disk.is_boot_disk:
        return "yellow"
    if disk.is_virtual:
        return "magenta"
    if disk.is_usb or disk.is_removable:
        return "cyan"
    return ""


def _status_color(status: str) -> str:
    s = status.lower()
    if "online" in s or "ok" in s or "healthy" in s:
        return "green"
    if "offline" in s or "fail" in s or "error" in s or "degraded" in s:
        return "red"
    if "warning" in s or "unknown" in s:
        return "yellow"
    return ""


def print_disk_table(disks: list[DiskInfo]) -> None:
    headers = ["ID", "Name", "Bus", "Size", "Style", "Status", "Letters", "Flags"]
    rows: list[list[str]] = []
    row_colors: list[list[str]] = []

    for disk in disks:
        flags: list[str] = []
        if disk.is_virtual:
            flags.append("VIRT")
        if disk.is_usb:
            flags.append("USB")
        if disk.is_removable:
            flags.append("REM")
        if disk.is_system_disk:
            flags.append("OS")
        if disk.is_boot_disk:
            flags.append("BOOT")
        if disk.is_read_only:
            flags.append("RO")
        if disk.size_bytes == 0:
            flags.append("NO-MEDIA")

        status = disk.operational_status or ""
        letters = ",".join(disk.drive_letters) if disk.drive_letters else ""
        name = disk.name_for_confirmation

        disk_color = _disk_row_color(disk)
        status_col_color = _status_color(status) if _use_color() else ""

        rows.append([
            disk.disk_id,
            name,
            disk.bus_type or "",
            format_bytes_binary(disk.size_bytes),
            disk.partition_style or "",
            status,
            letters,
            ",".join(flags),
        ])
        # Per-column color overrides: most cols use disk_color, status gets its own
        row_colors.append([
            disk_color, disk_color, disk_color, disk_color,
            disk_color,
            status_col_color or disk_color,
            disk_color, disk_color,
        ])

    _table(headers, rows, row_colors if _use_color() else None)


def print_disk_detail(disk: DiskInfo) -> None:
    label_color = _disk_row_color(disk)
    heading = f"Disk {disk.disk_id}: {disk.name_for_confirmation}"
    print(_c(label_color or "bold", heading) if label_color else _bold(heading))

    def _kv(label: str, value: str) -> None:
        print(f"  {_c('dim', label + ':')}  {value}")

    _kv("Path              ", disk.path or "")
    _kv("Serial            ", disk.serial_number or "")
    _kv("Bus               ", disk.bus_type or "")
    _kv("Media             ", disk.media_type or "")
    _kv("Size              ", f"{format_bytes_binary(disk.size_bytes)} ({disk.size_bytes:,} bytes)")
    _kv("Partition style   ", disk.partition_style or "")
    status = disk.operational_status or ""
    _kv("Operational       ", _c(_status_color(status), status) if status else "")
    health = disk.health_status or ""
    _kv("Health            ", _c(_status_color(health), health) if health else "")
    _kv("USB/removable     ", f"{disk.is_usb}/{disk.is_removable}")
    _kv("OS/boot disk      ", f"{disk.is_system_disk}/{disk.is_boot_disk}")
    _kv("Virtual disk      ", str(disk.is_virtual))
    _kv("Read-only/offline ", f"{disk.is_read_only}/{disk.is_offline}")
    if disk.is_virtual and disk.raw.get("image_path"):
        _kv("Image path        ", disk.raw["image_path"])
    print()

    if not disk.partitions:
        print(_c("dim", "  Partitions: none"))
        return

    headers = ["#", "ID", "Size", "FS", "Label", "Letter", "Mounts", "Flags"]
    rows: list[list[str]] = []
    for partition in disk.partitions:
        flags: list[str] = []
        if partition.is_boot:
            flags.append("BOOT")
        if partition.is_system:
            flags.append("SYSTEM")
        if partition.is_mounted:
            flags.append("MOUNTED")
        rows.append([
            str(partition.number or ""),
            partition.partition_id,
            format_bytes_binary(partition.size_bytes),
            partition.filesystem or "",
            partition.label or "",
            partition.drive_letter or "",
            ",".join(partition.mount_points),
            ",".join(flags),
        ])
    print(_bold("Partitions:"))
    _table(headers, rows)


def print_volumes_table(partitions: list[PartitionInfo]) -> None:
    """Print a clean table of all partitions/volumes."""
    if not partitions:
        print(_c("dim", "No volumes found."))
        return
    headers = ["Disk", "Part#", "Letter", "FS", "Label", "Size", "Mounts", "Flags"]
    rows: list[list[str]] = []
    row_colors: list[list[str]] = []
    for p in partitions:
        flags: list[str] = []
        if p.is_boot:
            flags.append("BOOT")
        if p.is_system:
            flags.append("SYSTEM")
        if p.is_mounted:
            flags.append("MNT")
        letter = f"{p.drive_letter}:" if p.drive_letter else ""
        mounts = ";".join(m for m in p.mount_points if not m.startswith(letter))
        col = "cyan" if p.drive_letter else ""
        rows.append([
            p.disk_id,
            str(p.number or ""),
            letter,
            p.filesystem or "",
            p.label or "",
            format_bytes_binary(p.size_bytes),
            mounts,
            ",".join(flags),
        ])
        row_colors.append([col] * len(headers))
    _table(headers, rows, row_colors if _use_color() else None)


def print_diagnosis(diagnosis: UsbDiagnosis) -> None:
    sev_color = {
        Severity.OK: "green",
        Severity.INFO: "cyan",
        Severity.WARNING: "yellow",
        Severity.ERROR: "red",
        Severity.REFUSED: "red",
    }.get(diagnosis.severity, "")

    print(f"{_bold('Diagnosis:')} {_c(sev_color, diagnosis.diagnosis)}")
    print(f"{_bold('Severity: ')} {_c(sev_color, diagnosis.severity.value)}")
    print()
    print(_bold("Evidence:"))
    for item in diagnosis.evidence:
        print(f"  {_c('dim', '-')} {item}")
    if diagnosis.likely_causes:
        print()
        print(_bold("Likely causes:"))
        for item in diagnosis.likely_causes:
            print(f"  {_c('dim', '-')} {item}")
    if diagnosis.recommended_actions:
        print()
        print(_bold("Recommended actions:"))
        for item in diagnosis.recommended_actions:
            print(f"  {_c('dim', '-')} {item}")


def print_health_summary(rows_json: str) -> None:
    """Render structured JSON from health_summary() as a colored table."""
    try:
        data = json.loads(rows_json) if rows_json else []
    except Exception:
        print(rows_json)
        return
    if not isinstance(data, list):
        data = [data]
    if not data:
        print(_c("dim", "No physical disks found."))
        return

    headers = ["#", "Name", "Type", "Bus", "Size", "Operational", "Health"]
    rows: list[list[str]] = []
    row_colors: list[list[str]] = []
    for d in data:
        status = str(d.get("OperationalStatus") or "")
        health = str(d.get("HealthStatus") or "")
        s_color = _status_color(status)
        h_color = _status_color(health)
        rows.append([
            str(d.get("Number") or ""),
            str(d.get("Name") or ""),
            str(d.get("MediaType") or ""),
            str(d.get("BusType") or ""),
            format_bytes_binary(d.get("Size")),
            status,
            health,
        ])
        row_colors.append(["", "", "", "", "", s_color, h_color])
    _table(headers, rows, row_colors if _use_color() else None)


def print_health_smart(rows_json: str, disk_id: str | None = None) -> None:
    """Render SMART/reliability JSON from health_smart()."""
    try:
        data = json.loads(rows_json) if rows_json else {}
    except Exception:
        print(rows_json)
        return
    if not isinstance(data, list):
        data = [data]
    if not data:
        print(_c("dim", "No SMART data available."))
        return

    for d in data:
        health = str(d.get("HealthStatus") or "")
        status = str(d.get("OperationalStatus") or "")
        print(_bold(f"Disk {d.get('Number', '?')}: {d.get('Name', '')}"))
        pairs = [
            ("Media type   ", str(d.get("MediaType") or "")),
            ("Bus          ", str(d.get("BusType") or "")),
            ("Size         ", format_bytes_binary(d.get("Size"))),
            ("Operational  ", _c(_status_color(status), status) if status else ""),
            ("Health       ", _c(_status_color(health), health) if health else ""),
            ("Temperature  ", _fmt_smart(d.get("Temperature"), "°C")),
            ("Wear         ", _fmt_smart(d.get("Wear"), "%")),
            ("Read errors  ", _fmt_smart(d.get("ReadErrorsTotal"))),
            ("Write errors ", _fmt_smart(d.get("WriteErrorsTotal"))),
            ("Power-on hrs ", _fmt_smart(d.get("PowerOnHours"))),
        ]
        for label, value in pairs:
            if value:
                print(f"  {_c('dim', label + ':')}  {value}")
        print()


def _fmt_smart(value: Any, unit: str = "") -> str:
    if value is None:
        return ""
    return f"{value}{unit}"


def print_dependency_report(report: DependencyReport) -> None:
    headers = ["Name", "Available", "Required for", "Path/Note"]
    rows: list[list[str]] = []
    row_colors: list[list[str]] = []
    for c in report.checks:
        avail = "yes" if c.available else "no"
        avail_color = "green" if c.available else ("red" if c.required_for.lower().startswith("required") else "yellow")
        rows.append([c.name, avail, c.required_for, c.path or c.note or ""])
        row_colors.append(["", avail_color, "", "dim"])

    print(_bold(f"Dependency report: {report.platform}"))
    _table(headers, rows, row_colors if _use_color() else None)

    missing = report.missing_required
    if missing:
        print()
        print(_c("red", f"  {len(missing)} required dependency missing: " + ", ".join(m.name for m in missing)))
    else:
        print()
        print(_c("green", "  All required dependencies satisfied."))


def print_operation_plan(plan: OperationPlan, decision: SafetyDecision) -> None:
    title_color = "yellow" if decision.dry_run else "red"
    mode = "DRY RUN" if decision.dry_run else "EXECUTE"
    print(_c(title_color, _bold(f"{mode}: {plan.title}")))
    print()
    if plan.target_disk:
        disk = plan.target_disk
        print(_bold("Target:"))
        print(f"  Disk:       {disk.disk_id}")
        print(f"  Name:       {disk.name_for_confirmation}")
        print(f"  Serial:     {disk.serial_number or ''}")
        print(f"  Bus:        {disk.bus_type or ''}")
        print(f"  Size:       {format_bytes_binary(disk.size_bytes)}")
        print(f"  OS Disk:    {'Yes' if disk.is_system_disk else 'No'}")
        print(f"  Boot Disk:  {'Yes' if disk.is_boot_disk else 'No'}")
        print(f"  USB:        {'Yes' if disk.is_usb else 'No'}")
        print(f"  Letters:    {','.join(disk.drive_letters)}")
        print()
    if plan.image_path or plan.image_url:
        print(_bold("Image:"))
        if plan.image_path:
            print(f"  Path:       {plan.image_path}")
        if plan.image_url:
            print(f"  URL:        {plan.image_url}")
        print(f"  Verify:     {'Yes' if plan.verify else 'No'}")
        print()
    if decision.refused_reasons:
        print(_c("red", _bold("Refused:")))
        for reason in decision.refused_reasons:
            print(f"  {_c('red', '-')} {reason}")
        print()
    if decision.warnings:
        print(_c("yellow", _bold("Warnings:")))
        for warning in decision.warnings:
            print(f"  {_c('yellow', '-')} {warning}")
        print()
    if decision.required_confirmations:
        print(_bold("Required confirmations:"))
        for item in decision.required_confirmations:
            print(f"  - {item}")
        print()
    print(_bold("Planned actions:"))
    for index, step in enumerate(plan.steps, start=1):
        print(f"  {_c('dim', str(index) + '.')} {step}")
    if decision.dry_run:
        print()
        print(_c("yellow", "Result: No changes were made. Add -x / --execute to perform this operation."))


def print_operation_result(result: OperationResult) -> None:
    color = "green" if result.ok else "red"
    print(_c(color, result.message))
    if result.steps:
        print(_bold("Steps:"))
        for step in result.steps:
            print(f"  {_c('dim', '-')} {step}")
    output = result.details.get("output") if result.details else None
    if output:
        print(_bold("Output:"))
        print(output)
