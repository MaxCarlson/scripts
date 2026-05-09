"""Jellyfin log parsing and diagnosis."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

SQLITE_LOCK_RE = re.compile(
    r"(SQLite Error 5: 'database is locked'|database is locked|Failed executing DbCommand)",
    re.I,
)
OPTIMIZE_START_RE = re.compile(r"Optimizing and vacuuming jellyfin\.db", re.I)
OPTIMIZE_SUCCESS_RE = re.compile(r"(jellyfin\.db optimized successfully|Optimize database\" Completed)", re.I)
MIGRATION_MISSING_RE = re.compile(r"no such table: __EFMigrationsHistory", re.I)
DUPLICATE_PATH_RE = re.compile(r"Found duplicate path:", re.I)
ITEMS_QUERY_RE = re.compile(r"/Users/[^/\s]+/Items\?.*ParentId=.*SortBy=IsFolder%2CSortName", re.I)
SCAN_COMPLETED_RE = re.compile(r'"Scan Media Library"\s+Completed', re.I)
SCAN_FAILED_RE = re.compile(r'"Scan Media Library"\s+(Failed|Cancelled|Canceled|Aborted)', re.I)
STARTUP_OK_RE = re.compile(r"(Startup complete|Core startup complete)", re.I)
FATAL_RE = re.compile(r"(Unhandled Exception|FTL|Fatal)", re.I)
SUBTITLE_FFPROBE_RE = re.compile(r"(SubtitleResolver|ffprobe|\.srt)", re.I)
WARNING_RE = re.compile(r"(Error|Exception|Failed|Access denied|Unauthorized)", re.I)


RECOMMENDATIONS = {
    "sqlite_lock": (
        "A database lock was detected. If Optimize Database is running, stop interacting with the UI and wait. "
        "If the lock persists after 20 minutes or after restart, stop Jellyfin and run offline DB checks."
    ),
    "migration_missing": (
        "Missing __EFMigrationsHistory usually means a partial DB reset. Run reset full, not reset db."
    ),
    "duplicate_path": (
        "Duplicate library paths were found. Reset root or inspect library configuration before rebuilding."
    ),
    "items_query": (
        "A stuck /Items query may require resetting display state or recreating libraries one root at a time."
    ),
    "subtitle_ffprobe": (
        "Subtitle or ffprobe errors can come from invalid sidecar files; quarantine suspect .srt files."
    ),
    "scan_failed": (
        "The media library scan did not complete successfully. Review nearby errors before restarting scans."
    ),
    "fatal": "Fatal startup errors were detected. Stop Jellyfin and diagnose logs/database before retrying.",
}


@dataclass(frozen=True)
class LogFinding:
    """One classified log line."""

    kind: str
    line: str
    recommendation: str = ""


@dataclass
class LogSummary:
    """Aggregated log diagnosis."""

    findings: list[LogFinding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, finding: LogFinding) -> None:
        """Add a finding and increment its count."""
        self.findings.append(finding)
        self.counts[finding.kind] = self.counts.get(finding.kind, 0) + 1

    @property
    def recommended_next_action(self) -> str:
        """Return the highest-priority recommendation."""
        for kind in ("migration_missing", "fatal", "sqlite_lock", "duplicate_path", "scan_failed", "items_query"):
            if self.counts.get(kind):
                return RECOMMENDATIONS[kind]
        return "No known Jellyfin recovery pattern was detected in the inspected log lines."

    def to_dict(self) -> dict[str, object]:
        """Return a stable dictionary for CLI and tests."""
        return {
            "counts": dict(self.counts),
            "findings": [finding.__dict__ for finding in self.findings],
            "recommended_next_action": self.recommended_next_action,
        }


def classify_line(line: str) -> list[LogFinding]:
    """Classify one Jellyfin log line."""
    checks = [
        ("optimize_start", OPTIMIZE_START_RE, ""),
        ("optimize_success", OPTIMIZE_SUCCESS_RE, ""),
        ("sqlite_lock", SQLITE_LOCK_RE, RECOMMENDATIONS["sqlite_lock"]),
        ("migration_missing", MIGRATION_MISSING_RE, RECOMMENDATIONS["migration_missing"]),
        ("duplicate_path", DUPLICATE_PATH_RE, RECOMMENDATIONS["duplicate_path"]),
        ("items_query", ITEMS_QUERY_RE, RECOMMENDATIONS["items_query"]),
        ("scan_completed", SCAN_COMPLETED_RE, ""),
        ("scan_failed", SCAN_FAILED_RE, RECOMMENDATIONS["scan_failed"]),
        ("startup_ok", STARTUP_OK_RE, ""),
        ("fatal", FATAL_RE, RECOMMENDATIONS["fatal"]),
        ("subtitle_ffprobe", SUBTITLE_FFPROBE_RE, RECOMMENDATIONS["subtitle_ffprobe"]),
        ("warning", WARNING_RE, ""),
    ]
    return [
        LogFinding(kind, line.rstrip(), recommendation)
        for kind, pattern, recommendation in checks
        if pattern.search(line)
    ]


def analyze_lines(lines: Iterable[str]) -> LogSummary:
    """Analyze iterable log lines."""
    summary = LogSummary()
    for line in lines:
        for finding in classify_line(line):
            summary.add(finding)
    return summary


def read_recent_lines(path: Path, *, lines: int = 500) -> list[str]:
    """Read the last ``lines`` lines from a UTF-8-ish log file."""
    if lines <= 0:
        return []
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-lines:]
