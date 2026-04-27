#!/usr/bin/env python3
from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class FileMeta:
    path: Path
    size: int
    mtime: float
    sha256: Optional[str] = None
    # Partial-hash signatures (hex) for cascade
    ph_head: Optional[str] = None
    ph_tail: Optional[str] = None
    ph_mid: Optional[str] = None
    ph_algo: Optional[str] = None  # "blake3" | "sha256" | "none"


@dataclasses.dataclass(frozen=True)
class VideoMeta(FileMeta):
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    container: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    overall_bitrate: Optional[int] = None
    video_bitrate: Optional[int] = None
    phash_signature: Optional[Tuple[int, ...]] = None  # tuple of 64-bit ints

    @property
    def resolution_area(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return 0


@dataclasses.dataclass(slots=True)
class FrameSignature:
    path: Path
    video_id: str
    frame_index: int
    timestamp_seconds: float
    phash64: int
    entropy: float
    mean_luma: float
    valid_for_matching: bool

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "video_id": self.video_id,
            "frame_index": self.frame_index,
            "timestamp_seconds": self.timestamp_seconds,
            "phash64": self.phash64,
            "entropy": self.entropy,
            "mean_luma": self.mean_luma,
            "valid_for_matching": self.valid_for_matching,
        }

    @classmethod
    def from_json_dict(cls, payload: Dict[str, Any]) -> "FrameSignature":
        return cls(
            path=Path(str(payload["path"])),
            video_id=str(payload["video_id"]),
            frame_index=int(payload["frame_index"]),
            timestamp_seconds=float(payload["timestamp_seconds"]),
            phash64=int(payload["phash64"]),
            entropy=float(payload["entropy"]),
            mean_luma=float(payload["mean_luma"]),
            valid_for_matching=bool(payload["valid_for_matching"]),
        )


@dataclasses.dataclass(slots=True)
class VideoSignature:
    path: Path
    video_id: str
    duration_seconds: Optional[float]
    sampled_frame_count: int
    valid_frame_count: int
    signatures: List[FrameSignature]
    extraction_backend: str
    sampling_profile: str

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "video_id": self.video_id,
            "duration_seconds": self.duration_seconds,
            "sampled_frame_count": self.sampled_frame_count,
            "valid_frame_count": self.valid_frame_count,
            "signatures": [frame.to_json_dict() for frame in self.signatures],
            "extraction_backend": self.extraction_backend,
            "sampling_profile": self.sampling_profile,
        }

    @classmethod
    def from_json_dict(cls, payload: Dict[str, Any]) -> "VideoSignature":
        signatures = [FrameSignature.from_json_dict(frame) for frame in payload.get("signatures", [])]
        return cls(
            path=Path(str(payload["path"])),
            video_id=str(payload["video_id"]),
            duration_seconds=(
                None if payload.get("duration_seconds") is None else float(payload["duration_seconds"])
            ),
            sampled_frame_count=int(payload.get("sampled_frame_count", len(signatures))),
            valid_frame_count=int(
                payload.get("valid_frame_count", sum(1 for frame in signatures if frame.valid_for_matching))
            ),
            signatures=signatures,
            extraction_backend=str(payload["extraction_backend"]),
            sampling_profile=str(payload["sampling_profile"]),
        )
