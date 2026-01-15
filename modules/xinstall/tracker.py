from __future__ import annotations

import json
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class InstallRecord:
    command_name: str
    package_name: str
    manager: str
    executable_path: str
    version: str
    timestamp_utc: str


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_windows() -> bool:
    return os.name == "nt"


def _is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "").lower() or "TERMUX" in os.environ.get("PREFIX", "").upper()


def detect_os_tag() -> str:
    if _is_windows():
        return "windows"
    if _is_termux():
        return "termux"
    return "linux"


def detect_hostname() -> str:
    if _is_windows():
        return os.environ.get("COMPUTERNAME") or platform.node() or "unknown-host"
    return platform.node() or "unknown-host"


def default_root_dir() -> Path:
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "tool-install-manager"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "tool-install-manager"


def machine_dir(root_dir: Optional[Path] = None) -> Path:
    base = root_dir or default_root_dir()
    return base / detect_os_tag() / detect_hostname()


def installed_json_path(root_dir: Optional[Path] = None) -> Path:
    return machine_dir(root_dir) / "installed.json"


def installed_md_path(root_dir: Optional[Path] = None) -> Path:
    return machine_dir(root_dir) / "INSTALLED.md"


def load_db(root_dir: Optional[Path] = None) -> Dict[str, Any]:
    p = installed_json_path(root_dir)
    if not p.exists():
        return {"records": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}


def save_db(db: Dict[str, Any], root_dir: Optional[Path] = None) -> None:
    d = machine_dir(root_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = installed_json_path(root_dir)
    p.write_text(json.dumps(db, indent=2, sort_keys=True), encoding="utf-8")


def upsert_record(record: InstallRecord, root_dir: Optional[Path] = None) -> None:
    db = load_db(root_dir)
    records = db.get("records", [])
    if not isinstance(records, list):
        records = []

    updated = False
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            continue
        if r.get("command_name") == record.command_name:
            records[i] = {
                "command_name": record.command_name,
                "package_name": record.package_name,
                "manager": record.manager,
                "executable_path": record.executable_path,
                "version": record.version,
                "timestamp_utc": record.timestamp_utc,
            }
            updated = True
            break

    if not updated:
        records.append(
            {
                "command_name": record.command_name,
                "package_name": record.package_name,
                "manager": record.manager,
                "executable_path": record.executable_path,
                "version": record.version,
                "timestamp_utc": record.timestamp_utc,
            }
        )

    db["records"] = records
    db["meta"] = {
        "os": detect_os_tag(),
        "hostname": detect_hostname(),
        "updated_utc": _utc_iso(),
    }
    save_db(db, root_dir=root_dir)
    write_markdown(db, root_dir=root_dir)


def write_markdown(db: Dict[str, Any], root_dir: Optional[Path] = None) -> None:
    d = machine_dir(root_dir)
    d.mkdir(parents=True, exist_ok=True)

    meta = db.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}

    records = db.get("records", [])
    if not isinstance(records, list):
        records = []

    rows = []
    for r in records:
        if not isinstance(r, dict):
            continue
        rows.append(
            (
                str(r.get("command_name", "")),
                str(r.get("package_name", "")),
                str(r.get("manager", "")),
                str(r.get("version", "")),
                str(r.get("executable_path", "")),
                str(r.get("timestamp_utc", "")),
            )
        )

    rows.sort(key=lambda t: (t[2].lower(), t[0].lower()))

    md = []
    md.append("# Tool Install Manager Notebook")
    md.append("")
    md.append("## Machine")
    md.append("")
    md.append(f"- OS: `{meta.get('os', '')}`")
    md.append(f"- Hostname: `{meta.get('hostname', '')}`")
    md.append(f"- Updated: `{meta.get('updated_utc', '')}`")
    md.append("")
    md.append("## Installed Tools")
    md.append("")
    md.append("| Command | Package | Manager | Version | Path | Timestamp (UTC) |")
    md.append("|---|---|---|---|---|---|")
    for cmd, pkg, mgr, ver, path, ts in rows:
        md.append(f"| `{cmd}` | `{pkg}` | `{mgr}` | `{ver}` | `{path}` | `{ts}` |")
    md.append("")

    installed_md_path(root_dir).write_text("\n".join(md), encoding="utf-8")


def make_record(
    command_name: str,
    package_name: str,
    manager: str,
    executable_path: str,
    version: str,
) -> InstallRecord:
    return InstallRecord(
        command_name=command_name,
        package_name=package_name,
        manager=manager,
        executable_path=executable_path,
        version=version,
        timestamp_utc=_utc_iso(),
    )
