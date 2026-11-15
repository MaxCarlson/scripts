"""Read-only Windows Scheduled Task, Startup, Run-key, and Default Terminal auditor."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

from procwatch.config import get_data_dir
from procwatch.correlator.terminal_session import read_console_delegation_status
from procwatch.models import utc_now_iso
from procwatch.redactor import redact_text
from procwatch.storage import FlightRecorderStorage

_CONSOLE_RISK_IMAGES = frozenset({"python.exe", "cmd.exe", "pwsh.exe", "powershell.exe", "node.exe"})
_TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


@dataclass(slots=True)
class AuditFinding:
    """Single audit finding across Task Scheduler, Startup, Registry Run, or DefTerm."""

    source_type: str  # task | startup_folder | registry_run | defterm
    target_name: str
    enabled: bool = True
    executable: str | None = None
    arguments_redacted: str | None = None
    working_dir: str | None = None
    principal: str | None = None
    trigger_summary: str = ""
    hidden_flag: bool = False
    evidence_rank: str = "configured_only"  # configured_only | observed_triggered | popup_linked
    linked_incident_ids: list[int] = field(default_factory=list)
    confidence: str = "low"  # high | medium | low
    risk_summary: str = ""
    remediation: str = ""
    remediation_status: str = "manual_review"  # manual_review | preview_available | not_applicable_yet
    raw_xml_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditReport:
    """Aggregated read-only system trigger audit report."""

    schema_version: int = 1
    target_type: str = "all"
    findings: list[AuditFinding] = field(default_factory=list)
    defterm_status: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_type": self.target_type,
            "finding_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "defterm_status": dict(self.defterm_status),
            "errors": list(self.errors),
        }


def _find_text(root: ET.Element, path: str) -> str:
    node = root.find(path, _TASK_NS)
    if node is None:
        node = root.find(path.replace("t:", ""))
    return (node.text or "").strip() if node is not None else ""


def parse_task_definition_xml(xml_str: str, *, task_path: str) -> AuditFinding | None:
    """Parse a Windows Scheduled Task XML definition without modifying system state."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    enabled_str = _find_text(root, "./t:Settings/t:Enabled").lower()
    enabled = enabled_str != "false"
    hidden = _find_text(root, "./t:Settings/t:Hidden").lower() == "true"
    principal = _find_text(root, "./t:Principals/t:Principal/t:UserId") or None
    run_level = _find_text(root, "./t:Principals/t:Principal/t:RunLevel")
    if run_level:
        principal = f"{principal or 'unknown'} ({run_level})"

    triggers: list[str] = []
    trig_parent = root.find("./t:Triggers", _TASK_NS)
    if trig_parent is None:
        trig_parent = root.find("./Triggers")
    if trig_parent is not None:
        for child in trig_parent:
            tag = child.tag.split("}")[-1]
            triggers.append(tag)
    trigger_summary = ", ".join(triggers) if triggers else "none"

    exe = _find_text(root, "./t:Actions/t:Exec/t:Command") or None
    args = _find_text(root, "./t:Actions/t:Exec/t:Arguments") or None
    workdir = _find_text(root, "./t:Actions/t:Exec/t:WorkingDirectory") or None
    red_args = redact_text(args, escape_controls=True) if args else None

    exe_name = Path(exe).name.lower() if exe else ""
    is_console_risk = exe_name in _CONSOLE_RISK_IMAGES
    if is_console_risk:
        risk_summary = f"Configured to run console runtime ({exe_name}); static risk only unless linked to triggers/popups."
        remediation = (
            "Review script for CREATE_NO_WINDOW or headless wrapper; Phase 4 `procwatch exec` "
            "wrapper is not_applicable_yet in Phase 3."
        )
        rem_status = "not_applicable_yet"
    else:
        risk_summary = "Configured executable action."
        remediation = "No console-runtime risk flagged."
        rem_status = "manual_review"

    return AuditFinding(
        source_type="task",
        target_name=task_path,
        enabled=enabled,
        executable=exe,
        arguments_redacted=red_args,
        working_dir=workdir,
        principal=principal,
        trigger_summary=trigger_summary,
        hidden_flag=hidden,
        evidence_rank="configured_only",
        confidence="low",
        risk_summary=risk_summary,
        remediation=remediation,
        remediation_status=rem_status,
        raw_xml_sha256=hashlib.sha256(xml_str.encode("utf-8", errors="replace")).hexdigest(),
    )


def _enumerate_scheduled_tasks_com(*, task_filter: str | None = None) -> tuple[list[AuditFinding], list[str]]:
    """Read-only enumeration of Windows Task Scheduler via Schedule.Service COM."""
    if sys.platform != "win32":
        return [], ["Task Scheduler COM audit is Windows-only."]
    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError:
        return [], ["pywin32 win32com.client unavailable for Task Scheduler COM audit."]

    findings: list[AuditFinding] = []
    errors: list[str] = []
    try:
        svc = win32com.client.Dispatch("Schedule.Service")
        svc.Connect()
        stack = [svc.GetFolder("\\")]
        while stack:
            folder = stack.pop()
            try:
                for sub in folder.GetFolders(0):
                    stack.append(sub)
            except Exception as exc:
                errors.append(f"Folder access denied ({getattr(folder, 'Path', '?')}): {exc}")
            try:
                for task in folder.GetTasks(1):
                    tpath = str(task.Path)
                    if task_filter and task_filter.lower() not in tpath.lower():
                        continue
                    try:
                        xml_str = str(task.Xml)
                        parsed = parse_task_definition_xml(xml_str, task_path=tpath)
                        if parsed is not None:
                            findings.append(parsed)
                    except Exception as exc:
                        errors.append(f"Task XML read error ({tpath}): {exc}")
            except Exception as exc:
                errors.append(f"Task enumeration error ({getattr(folder, 'Path', '?')}): {exc}")
    except Exception as exc:
        errors.append(f"Schedule.Service connect failed: {exc}")
    return findings, errors


def _audit_registry_run() -> tuple[list[AuditFinding], list[str]]:
    """Read-only inspection of HKCU/HKLM Run and RunOnce keys."""
    if sys.platform != "win32":
        return [], []
    import winreg

    findings: list[AuditFinding] = []
    errors: list[str] = []
    locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU\\...\\Run"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU\\...\\RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM\\...\\Run"),
    ]
    for hive, subkey, label in locations:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                idx = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, idx)
                        idx += 1
                    except OSError:
                        break
                    red_val = redact_text(str(val), escape_controls=True)
                    findings.append(
                        AuditFinding(
                            source_type="registry_run",
                            target_name=f"{label}\\{name}",
                            executable=red_val,
                            evidence_rank="configured_only",
                            confidence="low",
                            risk_summary="Registry startup Run/RunOnce entry.",
                            remediation="Verify whether console visibility is expected at logon.",
                        )
                    )
        except PermissionError:
            errors.append(f"Access denied reading {label}")
        except OSError:
            pass
    return findings, errors


def _audit_startup_folders() -> list[AuditFinding]:
    """Read-only inspection of User and Common Startup folders."""
    findings: list[AuditFinding] = []
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")
    progdata = os.environ.get("PROGRAMDATA")
    if progdata:
        candidates.append(Path(progdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")

    shell = None
    if sys.platform == "win32":
        try:
            import win32com.client  # type: ignore[import-untyped]

            shell = win32com.client.Dispatch("WScript.Shell")
        except Exception:
            shell = None

    for folder in candidates:
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.name.lower() == "desktop.ini":
                continue
            target_exe = str(entry)
            args_red: str | None = None
            workdir: str | None = None
            if entry.suffix.lower() == ".lnk" and shell is not None:
                try:
                    sc = shell.CreateShortCut(str(entry))
                    target_exe = sc.Targetpath or target_exe
                    args_red = redact_text(sc.Arguments, escape_controls=True) if sc.Arguments else None
                    workdir = sc.WorkingDirectory or None
                except Exception:
                    pass
            findings.append(
                AuditFinding(
                    source_type="startup_folder",
                    target_name=str(entry),
                    executable=target_exe,
                    arguments_redacted=args_red,
                    working_dir=workdir,
                    evidence_rank="configured_only",
                    confidence="low",
                    risk_summary="Startup folder entry executed at user logon.",
                    remediation="Inspect target script/binary if unexpected console appears on login.",
                )
            )
    return findings


def _correlate_audit_with_storage(findings: list[AuditFinding], db_path: Path | None) -> None:
    """Elevate evidence_rank when task_events or popup incidents corroborate a task."""
    resolved = (db_path or (get_data_dir() / "events.db")).expanduser()
    if not resolved.exists():
        return
    try:
        storage = FlightRecorderStorage(resolved, read_only=True)
        try:
            incidents = storage.query_history(limit=300)
            gaps = storage.get_ingest_gaps("task_events")
            del gaps
            with storage._read_conn() as conn:
                task_edges = conn.execute(
                    "SELECT to_node_id, from_node_id FROM evidence_edges WHERE relation = 'triggered_by'"
                ).fetchall()
        finally:
            storage.close()
    except Exception:
        return

    triggered_tasks = {str(r["to_node_id"]).removeprefix("task:").lower() for r in task_edges}
    for f in findings:
        if f.source_type != "task":
            continue
        tlow = f.target_name.lower()
        if tlow in triggered_tasks:
            f.evidence_rank = "observed_triggered"
            f.confidence = "medium"
        exe_name = Path(f.executable).name.lower() if f.executable else ""
        for inc in incidents:
            summary = str(inc.get("summary_text") or "").lower()
            if tlow in summary or (exe_name and exe_name in summary and tlow in triggered_tasks):
                inc_id = inc.get("incident_id")
                if isinstance(inc_id, int):
                    f.linked_incident_ids.append(inc_id)
        if f.linked_incident_ids:
            f.evidence_rank = "popup_linked"
            f.confidence = "high"


def run_audit(
    *,
    target_type: str = "all",
    task_name: str | None = None,
    db_path: Path | None = None,
) -> AuditReport:
    """Execute strictly read-only system trigger audit across selected targets."""
    report = AuditReport(target_type=target_type)
    defterm = read_console_delegation_status()
    report.defterm_status = {
        "default_host": defterm.default_host,
        "delegation_console": defterm.delegation_console,
        "delegation_terminal": defterm.delegation_terminal,
    }

    if target_type in ("all", "tasks"):
        t_findings, t_errors = _enumerate_scheduled_tasks_com(task_filter=task_name)
        report.findings.extend(t_findings)
        report.errors.extend(t_errors)

    if target_type in ("all", "startup"):
        r_findings, r_errors = _audit_registry_run()
        report.findings.extend(r_findings)
        report.errors.extend(r_errors)
        report.findings.extend(_audit_startup_folders())

    if target_type in ("all", "defterm"):
        report.findings.append(
            AuditFinding(
                source_type="defterm",
                target_name=r"HKCU\Console\%%Startup",
                executable=defterm.default_host,
                evidence_rank="configured_only",
                confidence="medium",
                risk_summary=f"Default terminal delegation is '{defterm.default_host}' (diagnostic context only, not a root cause).",
                remediation="Do not alter global terminal delegation to silence a single background script.",
            )
        )

    _correlate_audit_with_storage(report.findings, db_path)
    rank_order = {"popup_linked": 0, "observed_triggered": 1, "configured_only": 2}
    report.findings.sort(key=lambda f: (rank_order.get(f.evidence_rank, 3), f.source_type, f.target_name))
    return report


def apply_task_fix_preview_or_xml(
    *,
    task_path: str,
    original_xml: str,
    proposed_command: str,
    proposed_arguments: str | None = None,
    expected_sha256: str,
    apply_fix: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate, backup, and optionally rewrite a Scheduled Task XML action (never Phase 4 exec)."""
    if "procwatch" in proposed_command.lower() and "exec" in (proposed_arguments or "").lower():
        return {
            "status": "not_applicable_yet",
            "reason": "Phase 4 `procwatch exec` supervisor is not implemented yet; refusing dangling action.",
        }

    actual_sha = hashlib.sha256(original_xml.encode("utf-8", errors="replace")).hexdigest()
    if actual_sha != expected_sha256:
        return {
            "status": "aborted_hash_mismatch",
            "reason": "Task XML changed since audit preview.",
        }

    try:
        root = ET.fromstring(original_xml)
    except ET.ParseError as exc:
        return {"status": "error", "reason": f"Invalid task XML: {exc}"}

    cmd_node = root.find("./t:Actions/t:Exec/t:Command", _TASK_NS)
    if cmd_node is None:
        cmd_node = root.find("./Actions/Exec/Command")
    if cmd_node is None:
        return {"status": "unsupported", "reason": "Task has no <Exec><Command> action."}

    old_cmd = cmd_node.text or ""
    args_node = root.find("./t:Actions/t:Exec/t:Arguments", _TASK_NS)
    if args_node is None:
        args_node = root.find("./Actions/Exec/Arguments")
    old_args = args_node.text if args_node is not None else None

    if not apply_fix:
        return {
            "status": "dry_run_preview",
            "task_path": task_path,
            "original_command": old_cmd,
            "original_arguments": old_args,
            "proposed_command": proposed_command,
            "proposed_arguments": proposed_arguments,
        }

    bdir = (backup_dir or (get_data_dir() / "backups")).expanduser()
    bdir.mkdir(parents=True, exist_ok=True)
    safe_name = task_path.strip("\\").replace("\\", "_") or "task"
    ts_tag = utc_now_iso().replace(":", "").replace("-", "")
    backup_file = bdir / f"{safe_name}.{ts_tag}.{actual_sha[:10]}.xml"
    backup_file.write_text(original_xml, encoding="utf-8")

    cmd_node.text = proposed_command
    if proposed_arguments is not None:
        if args_node is None:
            exec_node = root.find("./t:Actions/t:Exec", _TASK_NS)
            if exec_node is None:
                exec_node = root.find("./Actions/Exec")
            if exec_node is not None:
                args_node = ET.SubElement(exec_node, "Arguments")
        if args_node is not None:
            args_node.text = proposed_arguments

    updated_xml = ET.tostring(root, encoding="unicode")
    return {
        "status": "prepared_with_backup",
        "task_path": task_path,
        "backup_path": str(backup_file),
        "backup_sha256": actual_sha,
        "updated_xml": updated_xml,
        "rollback_command": f'schtasks /Create /TN "{task_path}" /XML "{backup_file}" /F',
    }
