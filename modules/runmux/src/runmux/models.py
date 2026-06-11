"""Data models for runmux."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runmux.constants import ACTIVE_STATUSES


def utc_now_iso() -> str:
    """Return a timezone-aware UTC ISO timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp saved by runmux."""

    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class RunRecord:
    """A single managed run stored in the registry."""

    id: str
    numeric_id: int
    name: str | None
    status: str
    created_at: str
    updated_at: str
    started_at: str | None
    ended_at: str | None
    exit_code: int | None
    pid: int | None
    supervisor_pid: int | None
    program: str
    argv_json: str
    cwd: str
    env_overrides_json: str
    port: int | None
    auth_token: str
    log_path: str
    command_line: str
    restart_of: str | None
    duplicate_of: str | None
    rows: int | None
    columns: int | None

    @classmethod
    def from_row(cls, row: Any) -> RunRecord:
        """Build a record from a sqlite row."""

        return cls(
            id=row["id"],
            numeric_id=row["numeric_id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            exit_code=row["exit_code"],
            pid=row["pid"],
            supervisor_pid=row["supervisor_pid"],
            program=row["program"],
            argv_json=row["argv_json"],
            cwd=row["cwd"],
            env_overrides_json=row["env_overrides_json"],
            port=row["port"],
            auth_token=row["auth_token"],
            log_path=row["log_path"],
            command_line=row["command_line"],
            restart_of=row["restart_of"],
            duplicate_of=row["duplicate_of"],
            rows=row["rows"],
            columns=row["columns"],
        )

    @property
    def is_active(self) -> bool:
        """Return whether this run is currently considered active."""

        return self.status in ACTIVE_STATUSES

    @property
    def log_file(self) -> Path:
        """Return the output log path."""

        return Path(self.log_path)

    @property
    def runtime_seconds(self) -> float:
        """Return runtime in seconds using start/end timestamps when available."""

        start = parse_iso_datetime(self.started_at) or parse_iso_datetime(self.created_at)
        end = parse_iso_datetime(self.ended_at)
        if start is None:
            return 0.0
        if end is None and self.is_active:
            end = datetime.now(timezone.utc)
        elif end is None:
            end = parse_iso_datetime(self.updated_at) or datetime.now(timezone.utc)
        return max(0.0, (end - start).total_seconds())

    @property
    def display_name(self) -> str:
        """Return the user-provided name or program name."""

        return self.name or self.program
