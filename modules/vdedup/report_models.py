from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(slots=True)
class FileStats:
    path: Path
    size: int = 0
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    overall_bitrate: Optional[int] = None
    video_bitrate: Optional[int] = None
    overlap_hint: Optional[float] = None

    def to_meta(self) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"size": self.size}
        if self.duration is not None:
            meta["duration"] = self.duration
        if self.width is not None:
            meta["width"] = self.width
        if self.height is not None:
            meta["height"] = self.height
        if self.overall_bitrate is not None:
            meta["overall_bitrate"] = self.overall_bitrate
        if self.video_bitrate is not None:
            meta["video_bitrate"] = self.video_bitrate
        if self.overlap_hint is not None:
            meta["overlap_hint"] = self.overlap_hint
        return meta


@dataclass(slots=True)
class DuplicateGroup:
    group_id: str
    method: str
    keep: FileStats
    losers: List[FileStats] = field(default_factory=list)
    source_report: Optional["ReportDocument"] = None
    raw_payload: Optional[Dict[str, Any]] = None

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


def _build_stats(path: Path, meta: Optional[Dict[str, Any]] = None) -> FileStats:
    meta = meta or {}
    return FileStats(
        path=path,
        size=int(meta.get("size") or _safe_stat(path)),
        duration=_safe_float(meta.get("duration")),
        width=_safe_int(meta.get("width")),
        height=_safe_int(meta.get("height")),
        overall_bitrate=_safe_int(meta.get("overall_bitrate")),
        video_bitrate=_safe_int(meta.get("video_bitrate")),
        overlap_hint=_safe_float(meta.get("overlap_hint")),
    )


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


@dataclass(slots=True)
class ReportDocument:
    path: Path
    data: Dict[str, Any]
    groups: List[DuplicateGroup]

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")


def load_report_documents(report_paths: Sequence[Path]) -> List[ReportDocument]:
    documents: List[ReportDocument] = []
    for rp in report_paths:
        data = json.loads(Path(rp).read_text(encoding="utf-8"))
        groups_raw: Dict[str, Dict[str, Any]] = data.get("groups", {}) or {}
        groups: List[DuplicateGroup] = []
        for gid, payload in groups_raw.items():
            keep_path = Path(payload.get("keep", "")).expanduser()
            losers = [Path(p).expanduser() for p in (payload.get("losers") or [])]
            method = str(payload.get("method") or "unknown")
            keep_meta = payload.get("keep_meta") or payload.get("keep_stats") or {}
            loser_meta_map = payload.get("loser_meta") or {}
            keep_stats = _build_stats(keep_path, keep_meta)
            loser_stats = [
                _build_stats(lp, loser_meta_map.get(str(lp), {})) for lp in losers
            ]
            groups.append(
                DuplicateGroup(
                    group_id=gid,
                    method=method,
                    keep=keep_stats,
                    losers=loser_stats,
                    source_report=None,  # patched below
                    raw_payload=payload,
                )
            )
        document = ReportDocument(path=Path(rp), data=data, groups=groups)
        for group in groups:
            group.source_report = document
        documents.append(document)
    return documents


def load_report_groups(report_path: Path) -> List[DuplicateGroup]:
    """
    Load a dedupe report JSON and return structured groups with basic file stats.
    """
    docs = load_report_documents([report_path])
    return docs[0].groups if docs else []
