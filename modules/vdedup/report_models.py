from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass(slots=True)
class FileStats:
    path: Path
    size: int = 0
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    overall_bitrate: Optional[int] = None
    video_bitrate: Optional[int] = None


@dataclass(slots=True)
class DuplicateGroup:
    group_id: str
    method: str
    keep: FileStats
    losers: List[FileStats] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.losers)

    @property
    def total_duplicate_size(self) -> int:
        return sum(l.size for l in self.losers)

    @property
    def reclaimable_bytes(self) -> int:
        return self.total_duplicate_size


def _safe_stat(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _build_stats(path: Path) -> FileStats:
    return FileStats(path=path, size=_safe_stat(path))


def load_report_groups(report_path: Path) -> List[DuplicateGroup]:
    """
    Load a dedupe report JSON and return structured groups with basic file stats.
    """
    data = json.loads(report_path.read_text(encoding="utf-8"))
    groups_raw: Dict[str, Dict[str, Iterable[str]]] = data.get("groups", {}) or {}
    groups: List[DuplicateGroup] = []

    for gid, payload in groups_raw.items():
        keep_path = Path(payload.get("keep", "")).expanduser()
        losers = [Path(p).expanduser() for p in (payload.get("losers") or [])]
        method = str(payload.get("method") or "unknown")
        keep_stats = _build_stats(keep_path)
        loser_stats = [_build_stats(lp) for lp in losers]
        groups.append(DuplicateGroup(group_id=gid, method=method, keep=keep_stats, losers=loser_stats))

    return groups
