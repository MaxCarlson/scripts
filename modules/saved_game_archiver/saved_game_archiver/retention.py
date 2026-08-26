from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .models import SnapshotManifest
from .utils import parse_iso


_RETENTION_RE = re.compile(r"^(\d+)([hdwm])$")
_INTERVAL_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhd])$")


@dataclass(frozen=True)
class RetentionPolicy:
    hourly: int = 0
    daily: int = 0
    weekly: int = 0
    monthly: int = 0


def parse_retention(value: str) -> RetentionPolicy:
    counts = {"h": 0, "d": 0, "w": 0, "m": 0}
    for token in value.split():
        match = _RETENTION_RE.fullmatch(token.strip().casefold())
        if not match:
            raise ValueError(f"Invalid retention token {token!r}; expected forms like 24h 7d 4w 12m")
        count = int(match.group(1))
        if count < 0:
            raise ValueError("Retention counts cannot be negative")
        counts[match.group(2)] = count
    if not any(counts.values()):
        raise ValueError("Retention policy cannot be empty")
    return RetentionPolicy(counts["h"], counts["d"], counts["w"], counts["m"])


def parse_interval(value: str) -> float:
    match = _INTERVAL_RE.fullmatch(value.strip().casefold())
    if not match:
        raise ValueError(f"Invalid interval {value!r}; expected e.g. 30s, 15m, 2h, 1d")
    number = float(match.group(1))
    unit = match.group(2)
    scale = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}[unit]
    return number * scale


def select_gfs_snapshot_ids(manifests: Iterable[SnapshotManifest], policy: RetentionPolicy) -> set[str]:
    snapshots = sorted(manifests, key=lambda item: parse_iso(item.created_at), reverse=True)
    keep: set[str] = set()
    rules = (
        (policy.hourly, lambda dt: (dt.year, dt.month, dt.day, dt.hour)),
        (policy.daily, lambda dt: (dt.year, dt.month, dt.day)),
        (policy.weekly, lambda dt: (dt.isocalendar().year, dt.isocalendar().week)),
        (policy.monthly, lambda dt: (dt.year, dt.month)),
    )
    for count, bucket_fn in rules:
        if count <= 0:
            continue
        seen: set[tuple[int, ...]] = set()
        for snapshot in snapshots:
            dt = parse_iso(snapshot.created_at)
            bucket = bucket_fn(dt)
            if bucket in seen:
                continue
            seen.add(bucket)
            keep.add(snapshot.snapshot_id)
            if len(seen) >= count:
                break
    return keep


def select_in_session_snapshot_ids(manifests: Iterable[SnapshotManifest], keep_cycles: int) -> set[str]:
    by_session: dict[str, list[SnapshotManifest]] = defaultdict(list)
    session_latest: dict[str, datetime] = {}
    for snapshot in manifests:
        if snapshot.reason != "in_session" or not snapshot.session_id:
            continue
        by_session[snapshot.session_id].append(snapshot)
        dt = parse_iso(snapshot.created_at)
        session_latest[snapshot.session_id] = max(session_latest.get(snapshot.session_id, dt), dt)
    sessions = sorted(session_latest, key=lambda session_id: session_latest[session_id], reverse=True)[: max(0, keep_cycles)]
    return {snapshot.snapshot_id for session_id in sessions for snapshot in by_session[session_id]}


def retained_snapshot_ids(
    manifests: Iterable[SnapshotManifest],
    *,
    policy: RetentionPolicy,
    in_session_keep_cycles: int,
    exit_snapshot_ids: Iterable[str],
) -> set[str]:
    items = list(manifests)
    standard = [item for item in items if item.reason != "in_session"]
    keep = select_gfs_snapshot_ids(standard, policy)
    keep.update(select_in_session_snapshot_ids(items, in_session_keep_cycles))
    keep.update(exit_snapshot_ids)
    if items:
        keep.add(max(items, key=lambda item: parse_iso(item.created_at)).snapshot_id)
    return keep
