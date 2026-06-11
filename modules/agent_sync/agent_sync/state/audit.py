"""Audit log writer for delegated work."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any

from agent_sync.paths import audit_dir


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_audit_id() -> str:
    """Return a readable audit ID."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


@dataclass(frozen=True)
class AuditRecord:
    """A single delegated worker call record."""

    audit_id: str
    created_at: str
    worker: str
    task_type: str
    context_level: str
    high_stakes: bool
    repo_root: str
    prompt_path: str
    output_path: str
    status: str
    exit_code: int | None
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert this record to JSON data."""
        return {
            "audit_id": self.audit_id,
            "created_at": self.created_at,
            "worker": self.worker,
            "task_type": self.task_type,
            "context_level": self.context_level,
            "high_stakes": self.high_stakes,
            "repo_root": self.repo_root,
            "prompt_path": self.prompt_path,
            "output_path": self.output_path,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


def write_audit_artifacts(
    *,
    repo_root: Path,
    audit_id: str,
    prompt: str,
    output: str,
    record: AuditRecord,
) -> Path:
    """Write prompt, output, and metadata files for a delegated call."""
    root = audit_dir(repo_root) / audit_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "prompt.md").write_text(prompt, encoding="utf-8")
    (root / "output.md").write_text(output, encoding="utf-8")
    (root / "record.json").write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return root


def list_audit_records(repo_root: Path) -> list[AuditRecord]:
    """Return audit records, newest first."""
    root = audit_dir(repo_root)
    if not root.exists():
        return []
    records: list[AuditRecord] = []
    for record_path in root.glob("*/record.json"):
        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
            records.append(AuditRecord(**data))
        except (OSError, TypeError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda record: record.created_at, reverse=True)


def load_audit_record(repo_root: Path, audit_id: str) -> tuple[AuditRecord, str, str]:
    """Load a single audit record and its prompt/output."""
    root = audit_dir(repo_root) / audit_id
    record_path = root / "record.json"
    if not record_path.exists():
        raise FileNotFoundError(f"Audit record not found: {audit_id}")
    data = json.loads(record_path.read_text(encoding="utf-8"))
    prompt = (root / "prompt.md").read_text(encoding="utf-8") if (root / "prompt.md").exists() else ""
    output = (root / "output.md").read_text(encoding="utf-8") if (root / "output.md").exists() else ""
    return AuditRecord(**data), prompt, output
