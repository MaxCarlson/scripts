"""Periodicity, burst grouping, and coverage-aware baseline analyzer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import statistics
from typing import Any

from procwatch.config import get_data_dir
from procwatch.storage import FlightRecorderStorage

_VOLATILE_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_VOLATILE_NUM_RE = re.compile(r"\b\d{4,}\b")
_TEMP_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"']*\\temp\\[^\s\"']+", re.IGNORECASE)


@dataclass(slots=True)
class PatternSummary:
    """Aggregated recurrence & burst metrics for one normalized command signature."""

    signature: str
    image_name: str
    observed_count: int
    popup_count: int
    process_only_count: int
    first_ts_utc: str
    last_ts_utc: str
    median_interval_seconds: float | None = None
    mean_interval_seconds: float | None = None
    stddev_interval_seconds: float | None = None
    is_periodic: bool = False
    is_bursty: bool = False
    confidence: str = "low"
    sample_incident_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BaselineComparison:
    """Coverage-normalized before/after popup rate comparison."""

    schema_version: int = 1
    current_window_hours: float = 0.0
    baseline_window_hours: float = 0.0
    current_count: int = 0
    baseline_count: int = 0
    current_rate_per_hour: float = 0.0
    baseline_rate_per_hour: float = 0.0
    rate_ratio: float | None = None
    outcome: str = "insufficient_coverage"  # improved | regressed | unchanged | insufficient_coverage
    coverage_warning: str | None = None
    patterns: list[PatternSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "current_window_hours": round(self.current_window_hours, 4),
            "baseline_window_hours": round(self.baseline_window_hours, 4),
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "current_rate_per_hour": round(self.current_rate_per_hour, 4),
            "baseline_rate_per_hour": round(self.baseline_rate_per_hour, 4),
            "rate_ratio": round(self.rate_ratio, 4) if self.rate_ratio is not None else None,
            "outcome": self.outcome,
            "coverage_warning": self.coverage_warning,
            "patterns": [p.to_dict() for p in self.patterns],
        }


def parse_utc_iso(ts: str) -> datetime | None:
    """Parse ISO-8601 UTC timestamp string cleanly."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_duration_seconds(spec: str | None, *, default_seconds: float = 86400.0) -> float:
    """Parse durations like '1h', '30m', '7d', '600s' into seconds."""
    if not spec:
        return default_seconds
    raw = spec.strip().lower()
    if raw.endswith("s"):
        return float(raw[:-1])
    if raw.endswith("m"):
        return float(raw[:-1]) * 60.0
    if raw.endswith("h"):
        return float(raw[:-1]) * 3600.0
    if raw.endswith("d"):
        return float(raw[:-1]) * 86400.0
    return float(raw)


def normalize_command_signature(image_name: str | None, command_line: str | None) -> str:
    """Create a stable signature stripping volatile PIDs/temp paths without collapsing commands."""
    img = (image_name or "<unknown>").strip().lower()
    cmd = (command_line or "").strip()
    if not cmd:
        return img
    norm = _TEMP_PATH_RE.sub("<TEMP>", cmd)
    norm = _VOLATILE_HEX_RE.sub("<HEX>", norm)
    norm = _VOLATILE_NUM_RE.sub("<NUM>", norm)
    return f"{img} :: {' '.join(norm.split())[:180]}"


def compute_pattern_summaries(incidents: list[dict[str, Any]]) -> list[PatternSummary]:
    """Group incidents/events by normalized signature and compute periodicity/burst stats."""
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for row in incidents:
        dt = parse_utc_iso(str(row.get("created_ts_utc") or ""))
        if dt is None:
            continue
        sig = normalize_command_signature(
            row.get("image_name"),
            row.get("cmdline_redacted") or row.get("summary_text"),
        )
        grouped.setdefault(sig, []).append((dt, row))

    summaries: list[PatternSummary] = []
    for sig, entries in grouped.items():
        entries.sort(key=lambda item: item[0])
        times = [e[0] for e in entries]
        rows = [e[1] for e in entries]

        intervals = [
            (times[i] - times[i - 1]).total_seconds()
            for i in range(1, len(times))
            if (times[i] - times[i - 1]).total_seconds() >= 0.0
        ]
        # Deduplicate near-simultaneous (<0.05s) duplicate-source reports for interval stats.
        distinct_intervals = [iv for iv in intervals if iv >= 0.05]

        med_iv = statistics.median(distinct_intervals) if distinct_intervals else None
        mean_iv = statistics.mean(distinct_intervals) if distinct_intervals else None
        std_iv = statistics.stdev(distinct_intervals) if len(distinct_intervals) >= 2 else None

        is_periodic = False
        if len(distinct_intervals) >= 2 and med_iv is not None and med_iv > 0:
            cv = (std_iv or 0.0) / mean_iv if mean_iv and mean_iv > 0 else 1.0
            is_periodic = cv <= 0.35

        is_bursty = any(iv < 2.0 for iv in distinct_intervals) and len(entries) >= 3
        popup_cnt = sum(
            1
            for r in rows
            if str(r.get("category") or "") in ("visible_popup", "suppressed_popup", "console_popup", "guard_action")
        )
        proc_only_cnt = len(rows) - popup_cnt
        img = str(rows[0].get("image_name") or "<unknown>")
        conf = "high" if (len(entries) >= 4 and is_periodic) else ("medium" if len(entries) >= 3 else "low")

        summaries.append(
            PatternSummary(
                signature=sig,
                image_name=img,
                observed_count=len(entries),
                popup_count=popup_cnt,
                process_only_count=proc_only_cnt,
                first_ts_utc=times[0].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                last_ts_utc=times[-1].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                median_interval_seconds=round(med_iv, 3) if med_iv is not None else None,
                mean_interval_seconds=round(mean_iv, 3) if mean_iv is not None else None,
                stddev_interval_seconds=round(std_iv, 3) if std_iv is not None else None,
                is_periodic=is_periodic,
                is_bursty=is_bursty,
                confidence=conf,
                sample_incident_ids=[
                    int(r["incident_id"]) for r in rows[:5] if isinstance(r.get("incident_id"), int)
                ],
            )
        )

    summaries.sort(key=lambda s: (-s.observed_count, s.signature))
    return summaries


def compare_incident_windows(
    incidents: list[dict[str, Any]],
    *,
    now_utc: datetime | None = None,
    window_seconds: float = 3600.0,
    baseline_seconds: float = 86400.0,
    ingest_gaps: list[dict[str, Any]] | None = None,
    collector_active: bool = True,
) -> BaselineComparison:
    """Compare current window against earlier baseline normalized by covered hours."""
    now = now_utc or datetime.now(UTC)
    cur_start = now - timedelta(seconds=window_seconds)
    base_start = cur_start - timedelta(seconds=baseline_seconds)

    cur_rows: list[dict[str, Any]] = []
    base_rows: list[dict[str, Any]] = []
    for row in incidents:
        dt = parse_utc_iso(str(row.get("created_ts_utc") or ""))
        if dt is None:
            continue
        if cur_start <= dt <= now:
            cur_rows.append(row)
        elif base_start <= dt < cur_start:
            base_rows.append(row)

    cur_hours = max(window_seconds / 3600.0, 1e-6)
    base_hours = max(baseline_seconds / 3600.0, 1e-6)
    cur_rate = len(cur_rows) / cur_hours
    base_rate = len(base_rows) / base_hours

    warning: str | None = None
    if not collector_active:
        warning = "Collector inactive/unavailable during current window; zero events does not prove fix."
    elif ingest_gaps:
        warning = f"{len(ingest_gaps)} ingest gap(s) recorded; coverage may be incomplete."

    if warning and len(cur_rows) == 0:
        outcome = "insufficient_coverage"
    elif len(base_rows) == 0 and len(cur_rows) == 0:
        outcome = "insufficient_coverage"
        warning = warning or "No baseline or current incidents recorded."
    elif base_rate == 0:
        outcome = "regressed" if cur_rate > 0 else "unchanged"
    else:
        ratio = cur_rate / base_rate
        if ratio <= 0.75:
            outcome = "improved"
        elif ratio >= 1.25:
            outcome = "regressed"
        else:
            outcome = "unchanged"

    ratio_val = (cur_rate / base_rate) if base_rate > 0 else None
    patterns = compute_pattern_summaries(cur_rows or incidents)
    return BaselineComparison(
        current_window_hours=cur_hours,
        baseline_window_hours=base_hours,
        current_count=len(cur_rows),
        baseline_count=len(base_rows),
        current_rate_per_hour=cur_rate,
        baseline_rate_per_hour=base_rate,
        rate_ratio=ratio_val,
        outcome=outcome,
        coverage_warning=warning,
        patterns=patterns,
    )


def analyze_patterns(
    *,
    db_path: Path | None = None,
    window_seconds: float = 3600.0,
    baseline_window: str = "24h",
    periodicity_only: bool = False,
) -> BaselineComparison:
    """Load persisted incidents/gaps from FlightRecorderStorage and run periodicity + baseline analysis."""
    resolved = (db_path or (get_data_dir() / "events.db")).expanduser()
    if not resolved.exists():
        return BaselineComparison(
            current_window_hours=window_seconds / 3600.0,
            baseline_window_hours=parse_duration_seconds(baseline_window) / 3600.0,
            outcome="insufficient_coverage",
            coverage_warning="Flight recorder DB not initialized.",
        )

    storage = FlightRecorderStorage(resolved, read_only=True)
    try:
        incidents = storage.query_history(limit=2000)
        gaps = storage.get_ingest_gaps()
        states = storage.get_collector_state()
    finally:
        storage.close()

    collector_active = any(s.get("status") == "active" for s in states) if states else True
    base_sec = parse_duration_seconds(baseline_window, default_seconds=86400.0)
    comp = compare_incident_windows(
        incidents,
        window_seconds=window_seconds,
        baseline_seconds=base_sec,
        ingest_gaps=gaps,
        collector_active=collector_active,
    )
    if periodicity_only:
        comp.patterns = [p for p in comp.patterns if p.is_periodic or p.is_bursty]
    return comp
