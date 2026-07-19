from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    SKIPPED_ARCHIVE = "skipped_archive"
    FAILED_BAD_URL = "failed_bad_url"
    FAILED_UNSUPPORTED = "failed_unsupported"
    FAILED_AUTH = "failed_auth"
    FAILED_HTTP = "failed_http"
    FAILED_RATE_LIMIT = "failed_rate_limit"
    FAILED_FILESYSTEM = "failed_filesystem"
    FAILED_ARCHIVE = "failed_archive"
    FAILED_BACKEND = "failed_backend"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


TERMINAL_STATES = {
    JobState.SUCCEEDED,
    JobState.SKIPPED_ARCHIVE,
    JobState.FAILED_BAD_URL,
    JobState.FAILED_UNSUPPORTED,
    JobState.FAILED_AUTH,
    JobState.FAILED_HTTP,
    JobState.FAILED_RATE_LIMIT,
    JobState.FAILED_FILESYSTEM,
    JobState.FAILED_ARCHIVE,
    JobState.FAILED_BACKEND,
    JobState.CANCELED,
}


@dataclass(slots=True)
class InputUrl:
    url: str
    canonical_url: str
    source: str
    line: int


@dataclass(slots=True)
class WorkerEvent:
    event: str
    run_id: str
    job_id: int
    attempt_id: str
    worker: int
    url: str
    wall_time: float
    monotonic: float
    data: dict[str, Any] = field(default_factory=dict)
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkerSnapshot:
    slot: int
    state: str = "idle"
    url: str = ""
    title: str = ""
    site: str = ""
    attempt: int = 0
    images_done: int = 0
    images_total: int | None = None
    bytes_done: int = 0
    bytes_total: int | None = None
    current_bps: float = 0.0
    average_bps: float = 0.0
    current_ips: float = 0.0
    average_ips: float = 0.0
    elapsed: float = 0.0
    message: str = ""
