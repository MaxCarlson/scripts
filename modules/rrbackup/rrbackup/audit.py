"""Comprehensive read-only backup audit collection and rendering."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .command_contract import AUDIT_SECTION_NAMES
from .health import HealthReport, evaluate_health
from .locking import ProcessLock
from .models import utc_now
from .profile import BackupProfile, discover_legacy_config, read_path_list
from .repository_ops import RepositoryClient, operation_to_dict
from .schedule_discovery import ScheduleDiscovery, discover_schedules
from .snapshots import SnapshotRecord
from .state import RunStateStore
from .version import __version__


_RELEVANT_ENVIRONMENT_NAMES = (
    "BACKUP_MODULE_CONFIG",
    "BACKUP_MODULE_REPOSITORY",
    "BACKUP_MODULE_PASSWORD_FILE",
    "BACKUP_MODULE_SOURCES_FILE",
    "BACKUP_MODULE_EXCLUDES_FILE",
    "BACKUP_MODULE_STATUS_FILE",
    "BACKUP_MODULE_LOG_FILE",
    "BACKUP_MODULE_LOCK_FILE",
    "BACKUP_MODULE_TAG",
    "BACKUP_MODULE_RESTIC_EXECUTABLE",
    "BACKUP_MODULE_DEFAULT_RESTORE_ROOT",
    "RRBACKUP_CONFIG",
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD_FILE",
    "RESTIC_PASSWORD_COMMAND",
    "RESTIC_PASSWORD",
)

_SECRET_ENVIRONMENT_NAMES = {
    "RESTIC_PASSWORD",
    "RESTIC_PASSWORD_COMMAND",
}


@dataclass(frozen=True)
class AuditReport:
    """Structured result emitted by ``backup view audit``."""

    generated_utc: datetime
    profile: str
    sections: Mapping[str, Any]
    warnings: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the audit report."""

        return {
            "generated_utc": self.generated_utc.isoformat(),
            "profile": self.profile,
            "sections": dict(self.sections),
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        """Render a compact Markdown diagnostic artifact."""

        lines = [
            "# Backup Audit",
            "",
            "- Generated: `{0}`".format(self.generated_utc.isoformat()),
            "- Profile: `{0}`".format(self.profile),
            "",
        ]
        for name in AUDIT_SECTION_NAMES:
            if name not in self.sections:
                continue
            lines.extend(
                [
                    "## {0}".format(name.replace("-", " ").title()),
                    "",
                    "```json",
                    _json_text(self.sections[name]),
                    "```",
                    "",
                ]
            )
        if self.warnings:
            lines.extend(["## Warnings", ""])
            lines.extend("- {0}".format(value) for value in self.warnings)
            lines.append("")
        return "\n".join(lines)


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _path_metadata(path_value: Optional[str], *, sensitive: bool = False) -> Dict[str, Any]:
    if not path_value:
        return {
            "configured": False,
            "path": None,
            "exists": False,
        }

    path = Path(path_value)
    metadata: Dict[str, Any] = {
        "configured": True,
        "path": str(path),
        "exists": path.exists(),
        "sensitive": sensitive,
    }
    if not path.exists():
        return metadata

    try:
        stat = path.stat()
        metadata.update(
            {
                "is_file": path.is_file(),
                "is_directory": path.is_dir(),
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).astimezone().isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            }
        )
    except OSError as exc:
        metadata["metadata_error"] = str(exc)
    return metadata


def _environment_metadata(environment: Mapping[str, str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name in _RELEVANT_ENVIRONMENT_NAMES:
        if name not in environment:
            continue
        result[name] = {
            "scope": "process",
            "defined": True,
            "value": "<redacted>" if name in _SECRET_ENVIRONMENT_NAMES else environment[name],
            "sensitive": name in _SECRET_ENVIRONMENT_NAMES,
        }
    return result


def _command_metadata() -> Dict[str, Any]:
    names = ("backup", "rrb", "rrbackup", "backup_module", "restic", "python", "pwsh")
    return {
        name: {
            "resolved": shutil.which(name),
        }
        for name in names
    }


def _runtime_metadata() -> Dict[str, Any]:
    return {
        "rrbackup_version": __version__,
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "operating_system": os.name,
        "hostname": socket.gethostname(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER"),
    }


def _state_root(profile: BackupProfile) -> Path:
    return Path(profile.status_file).parent / "rrbackup-state"


def collect_audit(
    profile: BackupProfile,
    *,
    selected_sections: Sequence[str] = (),
    include_legacy_evidence: bool = False,
    environment: Optional[Mapping[str, str]] = None,
    repository_client: Optional[RepositoryClient] = None,
    schedule_discovery: Optional[ScheduleDiscovery] = None,
) -> AuditReport:
    """Collect all available backup evidence without mutating repository state."""

    requested = set(selected_sections or AUDIT_SECTION_NAMES)
    unsupported = requested.difference(AUDIT_SECTION_NAMES)
    if unsupported:
        raise ValueError(
            "Unsupported audit section(s): {0}".format(
                ", ".join(sorted(unsupported))
            )
        )

    generated = utc_now()
    env = dict(os.environ if environment is None else environment)
    client = repository_client or RepositoryClient(profile)
    state_store = RunStateStore(_state_root(profile))
    lock = ProcessLock(profile.lock_file).inspect()
    warnings: List[str] = []
    sections: Dict[str, Any] = {}
    snapshots: List[SnapshotRecord] = []
    snapshot_error: Optional[str] = None

    if "commands" in requested:
        sections["commands"] = _command_metadata()
    if "runtime" in requested:
        sections["runtime"] = _runtime_metadata()
    if "configuration" in requested:
        sections["configuration"] = profile.to_public_dict()
    if "environment" in requested:
        sections["environment"] = _environment_metadata(env)
    if "config-files" in requested:
        discovered = discover_legacy_config(environment=env)
        sections["config-files"] = {
            "legacy_config": None if discovered is None else str(discovered),
            "rrbackup_config": env.get("RRBACKUP_CONFIG"),
        }
    if "paths" in requested:
        sections["paths"] = {
            "repository": _path_metadata(profile.repository),
            "password_file": _path_metadata(profile.password_file, sensitive=True),
            "sources_file": _path_metadata(profile.sources_file),
            "excludes_file": _path_metadata(profile.excludes_file),
            "status_file": _path_metadata(profile.status_file),
            "log_file": _path_metadata(profile.log_file),
            "lock_file": _path_metadata(profile.lock_file),
            "restore_root": _path_metadata(profile.restore_root),
        }
    if "inputs" in requested:
        input_payload: Dict[str, Any] = {"sources": [], "excludes": []}
        try:
            input_payload["sources"] = read_path_list(profile.sources_file)
        except OSError as exc:
            input_payload["sources_error"] = str(exc)
        try:
            input_payload["excludes"] = read_path_list(profile.excludes_file)
        except OSError as exc:
            input_payload["excludes_error"] = str(exc)
        sections["inputs"] = input_payload

    needs_snapshots = bool(
        requested.intersection({"snapshots", "health", "provenance", "recommendations"})
    )
    if needs_snapshots:
        try:
            snapshots, snapshot_result = client.snapshots(
                tags=(() if not profile.tag else (profile.tag,))
            )
            if snapshot_result.return_code != 0:
                snapshot_error = "Restic snapshots exited with code {0}.".format(
                    snapshot_result.return_code
                )
        except Exception as exc:
            snapshot_error = str(exc)
        if snapshot_error:
            warnings.append(snapshot_error)

    if "repository" in requested:
        try:
            sections["repository"] = operation_to_dict(client.status())
        except Exception as exc:
            sections["repository"] = {"available": False, "error": str(exc)}
            warnings.append("Repository status failed: {0}".format(exc))
    if "keys" in requested:
        try:
            sections["keys"] = operation_to_dict(client.keys())
        except Exception as exc:
            sections["keys"] = {"available": False, "error": str(exc)}
            warnings.append("Repository key listing failed: {0}".format(exc))
    if "snapshots" in requested:
        sections["snapshots"] = {
            "count": len(snapshots),
            "records": [snapshot.to_dict() for snapshot in snapshots],
            "error": snapshot_error,
        }

    latest_run = state_store.load_latest()
    if "runs" in requested:
        run_files = []
        if state_store.runs_root.exists():
            run_files = [str(path) for path in sorted(state_store.runs_root.glob("*.json"))]
        sections["runs"] = {
            "state_root": str(state_store.state_root),
            "latest": None if latest_run is None else latest_run.to_dict(),
            "last_success": (
                None
                if state_store.load_last_success() is None
                else state_store.load_last_success().to_dict()
            ),
            "run_files": run_files,
        }
    if "logs" in requested:
        sections["logs"] = {
            "log": _path_metadata(profile.log_file),
        }
    if "locks" in requested:
        sections["locks"] = {
            "exists": lock.exists,
            "active": lock.active,
            "stale": lock.stale,
            "valid": lock.valid,
            "reason": lock.reason,
            "pid": None if lock.identity is None else lock.identity.pid,
        }

    schedules = schedule_discovery or discover_schedules()
    if "schedules" in requested:
        sections["schedules"] = schedules.to_dict()
    if "schedule-history" in requested:
        sections["schedule-history"] = {
            "available": False,
            "reason": "Detailed scheduler event-history parsing is planned for Stage 3.",
        }
    if "launchers" in requested:
        sections["launchers"] = {
            "schedules": schedules.to_dict(),
            "services": {"available": False, "reason": "Service discovery is planned."},
            "startup": {"available": False, "reason": "Startup discovery is planned."},
        }

    health_report: Optional[HealthReport] = None
    if requested.intersection({"health", "provenance", "recommendations"}):
        health_report = evaluate_health(
            profile,
            snapshots=snapshots,
            latest_run=latest_run,
            lock=lock,
            now=generated,
        )
    if "health" in requested and health_report is not None:
        sections["health"] = health_report.to_dict()
    if "provenance" in requested:
        sections["provenance"] = {
            "latest_snapshot_id": (
                None if not snapshots else snapshots[0].snapshot_id
            ),
            "latest_run_snapshot_id": (
                None if latest_run is None else latest_run.snapshot_id
            ),
            "structured_run_history_present": latest_run is not None,
            "conclusion": (
                "Structured RRBackup run history is available."
                if latest_run is not None
                else "Snapshots exist without structured RRBackup run history; they may predate the merged engine."
            ),
        }
    if "legacy-evidence" in requested:
        sections["legacy-evidence"] = {
            "included": include_legacy_evidence,
            "available": False,
            "reason": (
                "Legacy shell-history inspection is not enabled in this build."
                if include_legacy_evidence
                else "Use --include-legacy-evidence to opt in."
            ),
        }
    if "recommendations" in requested:
        recommendations: List[str] = []
        if health_report is not None:
            recommendations.extend(
                issue.recommendation
                for issue in health_report.issues
                if issue.recommendation
            )
        recommendations.extend(warnings)
        sections["recommendations"] = list(dict.fromkeys(recommendations))

    return AuditReport(
        generated_utc=generated,
        profile=profile.name,
        sections=sections,
        warnings=tuple(dict.fromkeys(warnings)),
    )
