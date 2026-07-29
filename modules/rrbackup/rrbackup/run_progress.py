"""Structured parsing and presentation helpers for Restic backup progress."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

from .models import datetime_to_text, ensure_utc, utc_now


@dataclass(frozen=True)
class BackupProgress:
    """One normalized Restic status update."""

    seconds_elapsed: float
    percent_done: float
    total_files: int
    files_done: int
    total_bytes: int
    bytes_done: int
    current_files: Tuple[str, ...]
    updated_utc: datetime

    @property
    def percent_display(self) -> float:
        """Return completion percentage in the human 0-100 range."""

        return max(0.0, min(100.0, self.percent_done * 100.0))

    @property
    def bytes_per_second(self) -> float:
        """Return average processed bytes per elapsed second."""

        if self.seconds_elapsed <= 0:
            return 0.0
        return max(0.0, self.bytes_done / self.seconds_elapsed)

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimate remaining seconds from Restic's aggregate byte counters."""

        speed = self.bytes_per_second
        remaining = max(0, self.total_bytes - self.bytes_done)
        if speed <= 0 or self.total_bytes <= 0:
            return None
        return remaining / speed

    def to_dict(self) -> Dict[str, Any]:
        """Serialize progress for persisted run metadata."""

        return {
            "message_type": "status",
            "seconds_elapsed": self.seconds_elapsed,
            "percent_done": self.percent_done,
            "percent_display": self.percent_display,
            "total_files": self.total_files,
            "files_done": self.files_done,
            "total_bytes": self.total_bytes,
            "bytes_done": self.bytes_done,
            "bytes_per_second": self.bytes_per_second,
            "eta_seconds": self.eta_seconds,
            "current_files": list(self.current_files),
            "updated_utc": datetime_to_text(self.updated_utc),
        }

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> Optional["BackupProgress"]:
        """Normalize one Restic JSON status object."""

        if payload.get("message_type") != "status":
            return None
        try:
            return cls(
                seconds_elapsed=max(0.0, float(payload.get("seconds_elapsed", 0.0))),
                percent_done=max(0.0, float(payload.get("percent_done", 0.0))),
                total_files=max(0, int(payload.get("total_files", 0))),
                files_done=max(0, int(payload.get("files_done", 0))),
                total_bytes=max(0, int(payload.get("total_bytes", 0))),
                bytes_done=max(0, int(payload.get("bytes_done", 0))),
                current_files=tuple(str(value) for value in payload.get("current_files", []) or []),
                updated_utc=ensure_utc(now or utc_now()),
            )
        except (TypeError, ValueError):
            return None


def parse_progress_line(
    line: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[BackupProgress]:
    """Parse one Restic JSON line, ignoring summaries and malformed output."""

    try:
        payload = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return BackupProgress.from_mapping(payload, now=now)
