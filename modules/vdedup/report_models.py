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


# ---------------------------------------------------------------------------
# Legacy inference helpers (used when loading reports written by older versions
# that lack explicit actionable / match_type fields)
# ---------------------------------------------------------------------------

_ACTIONABLE_PREFIXES = frozenset({"hash"})
_REVIEW_PREFIXES = frozenset({"phash"})  # old phash = actionable but check for safety
_CANDIDATE_PREFIXES = frozenset({"size", "meta", "size_candidate", "meta_candidate"})

_MATCH_TYPE_BY_PREFIX_LEGACY: Dict[str, str] = {
    "hash":         "exact_byte_duplicate",
    "phash":        "perceptual_duplicate",
    "subset":       "subset_of_longer",
    "scene":        "perceptual_duplicate",
    "scene-sub":    "subset_of_longer",
    "audio":        "perceptual_duplicate",
    "audio-sub":    "subset_of_longer",
    "timeline":     "perceptual_duplicate",
    "timeline-sub": "subset_of_longer",
    "meta":         "metadata_candidate",
    "size":         "size_candidate",
    "meta_candidate":  "metadata_candidate",
    "size_candidate":  "size_candidate",
}


def _legacy_infer_actionable(gid: str, payload: Dict[str, Any]) -> bool:
    prefix = gid.split(":", 1)[0]
    method = (payload.get("method") or "").lower()
    if prefix in _ACTIONABLE_PREFIXES or method in {"hash", "sha256", "blake3"}:
        return True
    if prefix in _CANDIDATE_PREFIXES or method in {"meta", "metadata", "size"}:
        return False
    if prefix in _REVIEW_PREFIXES:
        return True  # old phash groups were actionable
    return False


def _legacy_infer_match_type(gid: str) -> str:
    prefix = gid.split(":", 1)[0]
    return _MATCH_TYPE_BY_PREFIX_LEGACY.get(prefix, "unknown")


@dataclass(slots=True)
class DuplicateGroup:
    group_id: str
    method: str
    keep: FileStats
    losers: List[FileStats] = field(default_factory=list)
    confidence: str = "verified"       # "exact" | "verified" | "low"
    review_required: bool = False
    actionable: bool = True            # False = not safe to apply without -F
    match_type: str = "unknown"        # e.g. "exact_byte_duplicate", "perceptual_duplicate"
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

    def evidence(self) -> Dict[str, Any]:
        payload = self.raw_payload or {}
        evidence = payload.get("evidence")
        return evidence if isinstance(evidence, dict) else {}


@dataclass(slots=True)
class CandidateGroup:
    """
    A candidate cluster produced by Q1 (size) or Q3 (metadata).
    Has members-only semantics — no keep/losers, never directly apply-safe.
    """
    candidate_id: str
    method: str
    members: List[Path] = field(default_factory=list)
    candidate_only: bool = True
    actionable: bool = False
    review_required: bool = True
    match_type: str = "unknown"        # "size_candidate" | "metadata_candidate"
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommended_next_stage: Optional[str] = None
    source_report: Optional["ReportDocument"] = None
    raw_payload: Optional[Dict[str, Any]] = None


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
    candidate_groups: List[CandidateGroup] = field(default_factory=list)

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")


def load_report_documents(report_paths: Sequence[Path]) -> List[ReportDocument]:
    documents: List[ReportDocument] = []
    for rp in report_paths:
        data = json.loads(Path(rp).read_text(encoding="utf-8"))
        groups_raw: Dict[str, Dict[str, Any]] = data.get("groups", {}) or {}
        groups: List[DuplicateGroup] = []
        has_explicit_safety = False

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
            confidence = str(payload.get("confidence") or ("exact" if gid.startswith("hash:") else "verified"))
            review_required = bool(payload.get("review_required", False))
            if "actionable" in payload:
                actionable = bool(payload["actionable"])
                has_explicit_safety = True
            else:
                actionable = _legacy_infer_actionable(gid, payload)
            match_type = str(payload.get("match_type") or _legacy_infer_match_type(gid))
            groups.append(
                DuplicateGroup(
                    group_id=gid,
                    method=method,
                    keep=keep_stats,
                    losers=loser_stats,
                    confidence=confidence,
                    review_required=review_required,
                    actionable=actionable,
                    match_type=match_type,
                    source_report=None,  # patched below
                    raw_payload=payload,
                )
            )

        # Load candidate groups (Q1/Q3 clusters with members-only semantics)
        candidates_raw: Dict[str, Dict[str, Any]] = data.get("candidate_groups", {}) or {}
        candidates: List[CandidateGroup] = []
        for cid, payload in candidates_raw.items():
            members = [Path(p).expanduser() for p in (payload.get("members") or [])]
            candidates.append(CandidateGroup(
                candidate_id=cid,
                method=str(payload.get("method") or "unknown"),
                members=members,
                candidate_only=True,
                actionable=False,
                review_required=True,
                match_type=str(payload.get("match_type") or "unknown"),
                evidence=payload.get("evidence") or {},
                recommended_next_stage=payload.get("recommended_next_stage"),
                raw_payload=payload,
            ))

        document = ReportDocument(
            path=Path(rp),
            data=data,
            groups=groups,
            candidate_groups=candidates,
        )
        for group in groups:
            group.source_report = document
        for cg in candidates:
            cg.source_report = document
        # Stash whether this report has new-style safety fields (for apply warning)
        document.data["_has_explicit_safety"] = has_explicit_safety
        documents.append(document)
    return documents


def load_report_groups(report_path: Path) -> List[DuplicateGroup]:
    """
    Load a dedupe report JSON and return structured groups with basic file stats.
    """
    docs = load_report_documents([report_path])
    return docs[0].groups if docs else []
