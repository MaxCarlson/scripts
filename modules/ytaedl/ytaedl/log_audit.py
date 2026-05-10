#!/usr/bin/env python3
"""Read-only audit helpers for copied ytaedl run artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse

try:
    from . import __version__ as YTAEDL_VERSION
except Exception:  # pragma: no cover - direct file execution fallback
    YTAEDL_VERSION = "unknown"


EVENT_RE = re.compile(
    r"\b(?P<event>SIMULATE_START|SIMULATE_OK|SIMULATE_SKIP|FALLBACK_START|FALLBACK_ATTEMPT|"
    r"FALLBACK_STALLED|FALLBACK_FAILURE|FALLBACK_SUCCESS|FALLBACK_EXHAUSTED|PROGRESS|"
    r"COMPLETE|FINISH|DOWNLOAD_START|DOWNLOAD_DONE|DOWNLOAD_FAIL|REQUEUE_FAILED|ARCHIVE_[A-Z_]+)\b"
)
URL_RE = re.compile(r"\burl=(?P<url>https?://\S+)")


@dataclass
class LogAuditSummary:
    log_dir: str
    archive_dir: str
    manager_logs: int = 0
    worker_logs: int = 0
    archive_files: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    archive_status_counts: dict[str, int] = field(default_factory=dict)
    fallback_exhausted_domains: dict[str, int] = field(default_factory=dict)
    tpl_destination_hits: list[str] = field(default_factory=list)
    traceback_hits: list[str] = field(default_factory=list)
    domain_index_present: bool = False
    domain_index_summary: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def internally_consistent(self) -> bool:
        return not self.traceback_hits and bool(self.manager_logs or self.worker_logs)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower() or "-"
    except Exception:
        return "-"


def _audit_domain_index(path: Path) -> tuple[bool, dict[str, int]]:
    if not path.exists():
        return False, {}
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return True, {"parse_errors": 1}
    summary: dict[str, int] = {}
    if isinstance(data, dict):
        summary["top_level_keys"] = len(data)
        for key in ("urls", "entries", "files", "finished", "domains"):
            value = data.get(key)
            if isinstance(value, dict):
                summary[key] = len(value)
            elif isinstance(value, list):
                summary[key] = len(value)
    return True, summary


def audit_logs(log_dir: Path, archive_dir: Path) -> LogAuditSummary:
    log_dir = log_dir.expanduser().resolve()
    archive_dir = archive_dir.expanduser().resolve()
    events: Counter[str] = Counter()
    archive_statuses: Counter[str] = Counter()
    exhausted_domains: Counter[str] = Counter()
    tpl_hits: list[str] = []
    traceback_hits: list[str] = []

    manager_logs = sorted(log_dir.glob("dlmanager-*.log")) if log_dir.exists() else []
    worker_logs = sorted(log_dir.glob("ytaedler-worker-*.log")) if log_dir.exists() else []

    for path in [*manager_logs, *worker_logs]:
        try:
            lines = _read_text(path).splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in EVENT_RE.finditer(line):
                events[match.group("event")] += 1
            if "_TPL_" in line:
                tpl_hits.append(f"{path.name}:{line_no}: {line[:240]}")
            if "Traceback" in line or "traceback" in line:
                traceback_hits.append(f"{path.name}:{line_no}: {line[:240]}")
            if "FALLBACK_EXHAUSTED" in line:
                url_match = URL_RE.search(line)
                if url_match:
                    exhausted_domains[_domain(url_match.group("url"))] += 1

    archive_files = sorted(archive_dir.glob("*.txt")) if archive_dir.exists() else []
    for path in archive_files:
        try:
            for line in _read_text(path).splitlines():
                if not line.strip():
                    continue
                status = line.split("\t", 1)[0].strip().lower()
                if status:
                    archive_statuses[status] += 1
        except OSError:
            continue

    domain_present, domain_summary = _audit_domain_index(log_dir / "domain_index.json")
    summary = LogAuditSummary(
        log_dir=str(log_dir),
        archive_dir=str(archive_dir),
        manager_logs=len(manager_logs),
        worker_logs=len(worker_logs),
        archive_files=len(archive_files),
        event_counts=dict(sorted(events.items())),
        archive_status_counts=dict(sorted(archive_statuses.items())),
        fallback_exhausted_domains=dict(
            sorted((k, v) for k, v in exhausted_domains.items() if v > 1)
        ),
        tpl_destination_hits=tpl_hits,
        traceback_hits=traceback_hits,
        domain_index_present=domain_present,
        domain_index_summary=domain_summary,
    )
    if not manager_logs:
        summary.warnings.append("No manager logs found.")
    if not worker_logs:
        summary.warnings.append("No worker logs found.")
    if tpl_hits:
        summary.warnings.append(f"Found {len(tpl_hits)} _TPL_ destination/reference hit(s).")
    if traceback_hits:
        summary.warnings.append(f"Found {len(traceback_hits)} traceback hit(s).")
    if not archive_files:
        summary.warnings.append("No archive files found.")
    if not domain_present:
        summary.warnings.append("No domain_index.json found under log dir.")
    return summary


def format_audit(summary: LogAuditSummary) -> str:
    lines = [
        f"ytaedl log audit {YTAEDL_VERSION}",
        f"logs: {summary.log_dir}",
        f"archive: {summary.archive_dir}",
        f"manager_logs={summary.manager_logs} worker_logs={summary.worker_logs} archive_files={summary.archive_files}",
        f"events={summary.event_counts}",
        f"archive_statuses={summary.archive_status_counts}",
        f"fallback_exhausted_domains={summary.fallback_exhausted_domains}",
        f"tpl_hits={len(summary.tpl_destination_hits)} tracebacks={len(summary.traceback_hits)}",
        f"domain_index_present={summary.domain_index_present} domain_index_summary={summary.domain_index_summary}",
        f"internally_consistent={summary.internally_consistent}",
    ]
    if summary.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {warning}" for warning in summary.warnings)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ytaedl.log_audit",
        description=f"ytaedl {YTAEDL_VERSION} - read-only audit of copied ytaedl logs and archives.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-g", "--log-dir", type=Path, default=Path("modules/ytaedl/logs/new_logs"))
    parser.add_argument("-a", "--archive-dir", type=Path, default=Path("modules/ytaedl/logs/new_archive"))
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    summary = audit_logs(args.log_dir, args.archive_dir)
    if args.json:
        print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    else:
        print(format_audit(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
