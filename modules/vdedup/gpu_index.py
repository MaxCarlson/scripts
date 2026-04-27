from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, List, Tuple

from vdedup.models import VideoSignature


@dataclass(frozen=True, slots=True)
class HashBandKey:
    band_index: int
    band_value: int


@dataclass(frozen=True, slots=True)
class FrameHashRef:
    video_id: str
    path: Path
    frame_index: int
    timestamp_seconds: float
    hash_value: int


def _frame_hash_value(frame: object, hash_field: str) -> int | None:
    field = "phash64" if hash_field == "auto" else hash_field
    value = getattr(frame, field, None)
    if value is None:
        return None
    try:
        return int(value) & ((1 << 64) - 1)
    except (TypeError, ValueError):
        return None


class HashBandIndex:
    def __init__(self, *, bands: int = 4, bits_per_band: int = 16) -> None:
        if bands <= 0 or bits_per_band <= 0 or bands * bits_per_band != 64:
            raise ValueError("HashBandIndex requires a positive band layout covering exactly 64 bits")
        self.bands = int(bands)
        self.bits_per_band = int(bits_per_band)
        self._mask = (1 << self.bits_per_band) - 1
        self._buckets: DefaultDict[HashBandKey, List[FrameHashRef]] = defaultdict(list)
        self._refs_by_video: DefaultDict[str, List[FrameHashRef]] = defaultdict(list)

    def add_video(self, signature: VideoSignature, *, hash_field: str = "phash64") -> None:
        for frame in signature.signatures:
            if not frame.valid_for_matching:
                continue
            hash_value = _frame_hash_value(frame, hash_field)
            if hash_value is None:
                continue
            ref = FrameHashRef(
                video_id=signature.video_id,
                path=signature.path,
                frame_index=int(frame.frame_index),
                timestamp_seconds=float(frame.timestamp_seconds),
                hash_value=hash_value,
            )
            self._refs_by_video[signature.video_id].append(ref)
            for band_index in range(self.bands):
                band_value = (hash_value >> (band_index * self.bits_per_band)) & self._mask
                self._buckets[HashBandKey(band_index, band_value)].append(ref)

    def candidate_video_pairs(self) -> Dict[Tuple[str, str], int]:
        votes: Dict[Tuple[str, str], int] = {}
        seen_in_bucket: set[Tuple[HashBandKey, str, str]] = set()
        for key, refs in self._buckets.items():
            if len(refs) < 2:
                continue
            for i, left in enumerate(refs):
                for right in refs[i + 1 :]:
                    if left.video_id == right.video_id:
                        continue
                    pair = tuple(sorted((left.video_id, right.video_id)))
                    bucket_pair = (key, pair[0], pair[1])
                    if bucket_pair in seen_in_bucket:
                        continue
                    seen_in_bucket.add(bucket_pair)
                    votes[pair] = votes.get(pair, 0) + 1
        return dict(sorted(votes.items(), key=lambda item: item[0]))

    def frame_refs_for_video(self, video_id: str) -> List[FrameHashRef]:
        return list(self._refs_by_video.get(video_id, []))
