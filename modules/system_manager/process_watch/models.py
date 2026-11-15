"""Core data models, redaction, and unit formatting for process_watch."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

SENSITIVE_FLAG_RE = re.compile(
    r"(?i)(--?(?:token|password|passwd|pwd|secret|api[-_]?key|auth|bearer|credential|private[-_]?key|access[-_]?key)[=:\s]+)([^\s\"']+)"
)
SENSITIVE_ENV_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_KEY|AUTH|CREDENTIAL|PRIVATE_KEY)[A-Z0-9_]*)=([^\s]+)"
)
URL_CRED_RE = re.compile(r"(https?://[^:/\s]+:)([^@/\s]+)(@)")
BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-+/=]+)")

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def redact_sensitive_text(text: str) -> str:
    """Redact credentials, tokens, and secrets from command-line or summary text."""
    if not text:
        return ""
    redacted = URL_CRED_RE.sub(r"\1***\3", text)
    redacted = SENSITIVE_FLAG_RE.sub(r"\1***", redacted)
    redacted = SENSITIVE_ENV_RE.sub(r"\1=***", redacted)
    redacted = BEARER_RE.sub(r"\1***", redacted)
    return redacted


def format_bytes_iec(value: Optional[float]) -> str:
    """Format byte count using IEC units (B, KiB, MiB, GiB, TiB), or '-' if unavailable."""
    if value is None:
        return "-"
    num = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num) < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TiB"


def format_rate_iec(value: Optional[float]) -> str:
    """Format byte/s rate using IEC units, or '-' if unavailable."""
    if value is None:
        return "-"
    return f"{format_bytes_iec(value)}/s"


def format_percent(value: Optional[float]) -> str:
    """Format percentage or '-' if unavailable."""
    if value is None:
        return "-"
    return f"{value:.1f}%"


def format_duration(seconds: Optional[float]) -> str:
    """Format elapsed seconds into a compact human-readable duration."""
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}h"
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def make_sparkline(values: Sequence[Optional[float]], width: int = 12) -> str:
    """Render a compact Unicode sparkline for a sequence of numeric readings."""
    if not values:
        return ""
    window = list(values)[-width:]
    numeric = [v for v in window if v is not None]
    if not numeric:
        return "·" * len(window)
    low = min(numeric)
    high = max(numeric)
    span = high - low
    chars: List[str] = []
    for val in window:
        if val is None:
            chars.append("·")
        elif span <= 1e-12:
            chars.append(SPARK_CHARS[0] if val == 0 else SPARK_CHARS[3])
        else:
            idx = int((val - low) / span * (len(SPARK_CHARS) - 1))
            idx = max(0, min(len(SPARK_CHARS) - 1, idx))
            chars.append(SPARK_CHARS[idx])
    return "".join(chars)


@dataclass(frozen=True, order=True)
class ProcessIdentity:
    """Stable process identity combining PID and creation timestamp."""

    pid: int
    create_time: float

    @property
    def key(self) -> str:
        return f"{self.pid}:{self.create_time:.6f}"


@dataclass
class ProcessSample:
    """Point-in-time process measurement and computed topology/history fields."""

    identity: ProcessIdentity
    pid: int
    ppid: int
    name: str
    exe: str = ""
    cmdline_redacted: str = ""
    cmdline_raw: str = field(default="", repr=False)
    cwd: str = ""
    username: str = ""
    status: str = ""
    create_time: float = 0.0
    uptime_seconds: Optional[float] = None

    cpu_percent: Optional[float] = None
    cpu_percent_normalized: Optional[float] = None
    cpu_time_seconds: Optional[float] = None

    rss_bytes: Optional[int] = None
    private_bytes: Optional[int] = None
    vms_bytes: Optional[int] = None

    io_read_bytes: Optional[int] = None
    io_write_bytes: Optional[int] = None
    io_read_rate: Optional[float] = None
    io_write_rate: Optional[float] = None
    io_total_rate: Optional[float] = None

    num_threads: Optional[int] = None
    num_handles: Optional[int] = None

    gpu_memory_bytes: Optional[int] = None
    gpu_id: Optional[int] = None
    gpu_util_percent: Optional[float] = None
    gpu_provenance: Optional[str] = None

    is_new: bool = False
    is_exited: bool = False
    access_denied: bool = False
    first_seen_monotonic: float = 0.0
    last_seen_monotonic: float = 0.0

    # Topology & subtree aggregation
    child_count: int = 0
    descendant_count: int = 0
    depth: int = 0
    subtree_cpu_percent: Optional[float] = None
    subtree_rss_bytes: Optional[int] = None
    subtree_io_read_rate: Optional[float] = None
    subtree_io_write_rate: Optional[float] = None

    # Peaks from bounded history
    peak_cpu_percent: Optional[float] = None
    peak_cpu_at: Optional[float] = None
    peak_rss_bytes: Optional[int] = None
    peak_rss_at: Optional[float] = None
    peak_io_rate: Optional[float] = None
    peak_io_at: Optional[float] = None

    def to_export_dict(self, *, aggregated: bool = False) -> Dict[str, Any]:
        """Serialize sample into a sanitized, unit-explicit dictionary for JSON/CSV export."""
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "create_time": self.create_time,
            "identity_key": self.identity.key,
            "name": self.name,
            "status": "exited" if self.is_exited else (self.status or "unknown"),
            "username": self.username,
            "exe": self.exe,
            "cmdline_redacted": self.cmdline_redacted,
            "uptime_seconds": self.uptime_seconds,
            "measurement_scope": "subtree_aggregate" if aggregated else "process",
            "cpu_percent": self.subtree_cpu_percent if aggregated else self.cpu_percent,
            "cpu_percent_individual": self.cpu_percent,
            "cpu_percent_normalized": self.cpu_percent_normalized,
            "rss_bytes": self.subtree_rss_bytes if aggregated else self.rss_bytes,
            "rss_bytes_individual": self.rss_bytes,
            "private_bytes": self.private_bytes,
            "vms_bytes": self.vms_bytes,
            "io_read_bytes_per_sec": self.subtree_io_read_rate if aggregated else self.io_read_rate,
            "io_write_bytes_per_sec": self.subtree_io_write_rate if aggregated else self.io_write_rate,
            "io_total_bytes_per_sec": self.io_total_rate,
            "num_threads": self.num_threads,
            "num_handles": self.num_handles,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "gpu_id": self.gpu_id,
            "gpu_util_percent": self.gpu_util_percent,
            "gpu_provenance": self.gpu_provenance,
            "peak_cpu_percent": self.peak_cpu_percent,
            "peak_rss_bytes": self.peak_rss_bytes,
            "child_count": self.child_count,
            "descendant_count": self.descendant_count,
            "access_denied": self.access_denied,
        }


def format_sanitized_summary(sample: ProcessSample, ancestry: Optional[Sequence[ProcessSample]] = None) -> str:
    """Build a sanitized multi-line summary safe for clipboard/sharing."""
    lines = [
        f"Process: {sample.name} (PID {sample.pid}, Identity {sample.identity.key})",
        f"Status: {'exited' if sample.is_exited else sample.status or 'unknown'} | User: {sample.username or '-'} | Uptime: {format_duration(sample.uptime_seconds)}",
        f"Executable: {sample.exe or '-'}",
        f"Cmdline (sanitized): {sample.cmdline_redacted or '-'}",
        f"CPU: {format_percent(sample.cpu_percent)} (norm {format_percent(sample.cpu_percent_normalized)}, peak {format_percent(sample.peak_cpu_percent)})",
        f"Memory: RSS {format_bytes_iec(sample.rss_bytes)} | Private {format_bytes_iec(sample.private_bytes)} | VMS {format_bytes_iec(sample.vms_bytes)}",
        f"Process I/O: Read {format_rate_iec(sample.io_read_rate)} | Write {format_rate_iec(sample.io_write_rate)}",
        f"GPU Memory: {format_bytes_iec(sample.gpu_memory_bytes)} (backend: {sample.gpu_provenance or 'unavailable'})",
        f"Threads: {sample.num_threads if sample.num_threads is not None else '-'} | Handles: {sample.num_handles if sample.num_handles is not None else '-'} | Descendants: {sample.descendant_count}",
    ]
    if ancestry:
        chain = " -> ".join(f"{p.name}({p.pid})" for p in ancestry)
        lines.append(f"Ancestry: {chain}")
    return "\n".join(lines)


@dataclass
class HostSummary:
    """Compact host-level telemetry for header and export metadata."""

    cpu_percent: float = 0.0
    cpu_count: int = 1
    mem_used_bytes: int = 0
    mem_total_bytes: int = 0
    mem_percent: float = 0.0
    disk_read_rate: Optional[float] = None
    disk_write_rate: Optional[float] = None
    gpu_backend: str = "unavailable"
    gpu_age_seconds: Optional[float] = None
    gpu_devices: List[Dict[str, Any]] = field(default_factory=list)
    gpu_limitations: Optional[str] = None
    sample_duration_ms: float = 0.0
    total_processes: int = 0
    matched_processes: int = 0


@dataclass(frozen=True)
class LifecycleEvent:
    """Observed process start/exit event between polling cycles."""

    timestamp_epoch: float
    identity: ProcessIdentity
    name: str
    event_type: str  # "started" | "exited"

    @property
    def time_label(self) -> str:
        return datetime.fromtimestamp(self.timestamp_epoch, tz=timezone.utc).astimezone().strftime("%H:%M:%S")


@dataclass
class ProcessGroup:
    """Grouped summary of processes by name, executable, parent, or root ancestor."""

    group_key: str
    label: str
    members: List[ProcessSample]
    cpu_percent: Optional[float] = None
    rss_bytes: Optional[int] = None
    io_read_rate: Optional[float] = None
    io_write_rate: Optional[float] = None
    gpu_memory_bytes: Optional[int] = None

    @property
    def member_count(self) -> int:
        return len(self.members)


@dataclass
class MonitoringSnapshot:
    """Complete result of one sampling cycle."""

    sampled_at_epoch: float
    sampled_at_monotonic: float
    host: HostSummary
    processes: List[ProcessSample]
    by_identity: Dict[ProcessIdentity, ProcessSample]
    children_map: Dict[int, List[int]]
    events: List[LifecycleEvent] = field(default_factory=list)
