"""Core data models for the downloader library."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional, Union


class DownloadStatus(Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    ALREADY_EXISTS = "already_exists"
    OVERSIZED = "oversized"


class EventType(Enum):
    START = "start"
    PROGRESS = "progress"
    LOG = "log"
    FINISH = "finish"


@dataclass(frozen=True)
class StartEvent:
    item: "DownloadItem"
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)


@dataclass(frozen=True)
class ProgressEvent:
    """
    Generic progress event.

    For yt-dlp (unit="bytes"):
      - downloaded_bytes/total_bytes are bytes
      - speed_bps is bytes per second

    For aebndl (unit="segments"):
      - downloaded_bytes/total_bytes are segments_done/segments_total
      - speed_bps is iterations (segments) per second
    """

    item: "DownloadItem"
    downloaded_bytes: int
    total_bytes: Optional[int]
    speed_bps: Optional[float]
    eta_seconds: Optional[int]
    unit: Literal["bytes", "segments"] = "bytes"


@dataclass(frozen=True)
class LogEvent:
    item: "DownloadItem"
    message: str
    level: str = "INFO"


@dataclass(frozen=True)
class MetaEvent:
    item: "DownloadItem"
    video_id: str
    title: str


@dataclass(frozen=True)
class DestinationEvent:
    item: "DownloadItem"
    path: Path


@dataclass(frozen=True)
class AlreadyEvent:
    item: "DownloadItem"


@dataclass(frozen=True)
class FinishEvent:
    item: "DownloadItem"
    result: "DownloadResult"
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)


DownloadEvent = Union[
    StartEvent,
    ProgressEvent,
    LogEvent,
    MetaEvent,
    DestinationEvent,
    AlreadyEvent,
    FinishEvent,
]


@dataclass(frozen=True)
class URLSource:
    file: Path
    line_number: int
    original_url: str


@dataclass
class DownloadItem:
    id: int
    url: str
    output_dir: Path
    source: Optional[URLSource] = None

    quality: str = "best"
    rate_limit: Optional[str] = None
    retries: int = 3

    is_scene: bool = False
    scene_index: Optional[int] = None

    # Legacy/general args bucket (still used in some places)
    extra_args: List[str] = field(default_factory=list)

    # NEW: match orchestrator + downloaders which look for these attrs via getattr(...)
    # Keeping them optional preserves backwards compatibility.
    extra_ytdlp_args: List[str] = field(default_factory=list)
    extra_aebn_args: List[str] = field(default_factory=list)


@dataclass
class DownloadResult:
    item: DownloadItem
    status: DownloadStatus
    final_path: Optional[Path] = None
    error_message: Optional[str] = None
    size_bytes: Optional[int] = None
    duration: float = 0.0
    log_output: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DownloaderConfig:
    work_dir: Path
    # None disables archival (default behavior requested)
    archive_path: Optional[Path] = None

    max_size_gb: float = 10.0
    keep_oversized: bool = False
    timeout_seconds: Optional[int] = None

    parallel_jobs: int = 1

    aebn_only: bool = False
    scene_from_url: bool = True
    save_covers: bool = False
    keep_covers_flag: bool = False

    extra_aebn_args: List[str] = field(default_factory=list)
    extra_ytdlp_args: List[str] = field(default_factory=list)

    # yt-dlp tuning
    ytdlp_connections: Optional[int] = None
    ytdlp_rate_limit: Optional[str] = None
    ytdlp_retries: Optional[int] = None
    ytdlp_fragment_retries: Optional[int] = None
    ytdlp_buffer_size: Optional[str] = None  # e.g. "16M"

    # aria2 (external downloader) tuning
    aria2_splits: Optional[int] = None  # e.g. 16
    aria2_x_conn: Optional[int] = None  # e.g. 8
    aria2_min_split: Optional[str] = None  # e.g. "1M"
    aria2_timeout: Optional[int] = None  # seconds

    # <— NEW: allow CLI to pass -L/--log-file without TypeError
    log_file: Optional[Path] = None
