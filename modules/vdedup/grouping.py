#!/usr/bin/env python3
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .models import FileMeta, VideoMeta
from .phash import phash_distance

Meta = Union[FileMeta, VideoMeta]


def make_keep_key(order: Sequence[str]):
    def key(m: Meta):
        duration = m.duration if isinstance(m, VideoMeta) and m.duration is not None else -1.0
        res = m.resolution_area if isinstance(m, VideoMeta) else 0
        vbr = m.video_bitrate if isinstance(m, VideoMeta) and m.video_bitrate else 0
        newer = m.mtime
        smaller = -m.size
        depth = len(m.path.parts)
        mapping = {
            "longer": duration,
            "resolution": res,
            "video-bitrate": vbr,
            "newer": newer,
            "smaller": smaller,
            "deeper": depth,
        }
        return tuple(mapping.get(k, 0) for k in order)
    return key


def choose_winners(groups: Dict[str, List[Meta]], keep_order: Sequence[str]) -> Dict[str, Tuple[Meta, List[Meta]]]:
    keep_key = make_keep_key(keep_order)
    out: Dict[str, Tuple[Meta, List[Meta]]] = {}
    for gid, members in groups.items():
        sorted_members = sorted(members, key=lambda m: (keep_key(m), -len(m.path.as_posix())), reverse=True)
        out[gid] = (sorted_members[0], sorted_members[1:])
    return out


def alignable_avg_distance(a_sig: Sequence[int], b_sig: Sequence[int], per_frame_thresh: int) -> Optional[float]:
    """
    Sliding alignment average Hamming distance (per aligned frame). None if not alignable under threshold.
    """
    if not a_sig or not b_sig:
        return None
    A, B = (a_sig, b_sig) if len(a_sig) <= len(b_sig) else (b_sig, a_sig)
    best = None
    for offset in range(0, len(B) - len(A) + 1):
        dist = 0
        for i in range(len(A)):
            x = int(A[i]) ^ int(B[i + offset])
            dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
        avg = dist / len(A)
        if best is None or avg < best:
            best = avg
    return best if (best is not None and best <= per_frame_thresh) else None


def group_by_same_size(files: Iterable[FileMeta]) -> Dict[str, List[FileMeta]]:
    bucket: Dict[int, List[FileMeta]] = defaultdict(list)
    for m in files:
        bucket[m.size].append(m)
    out: Dict[str, List[FileMeta]] = {}
    for size, lst in bucket.items():
        if len(lst) > 1:
            out[f"size:{size}"] = lst
    return out
