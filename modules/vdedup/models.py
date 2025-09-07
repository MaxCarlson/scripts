#!/usr/bin/env python3
from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import Optional, Tuple


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
