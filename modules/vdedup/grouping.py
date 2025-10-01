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
    Enhanced sliding alignment average Hamming distance with adaptive thresholds.
    Supports cross-resolution matching by normalizing threshold based on content complexity.
    """
    if not a_sig or not b_sig:
        return None

    # Ensure A is the shorter sequence
    A, B = (a_sig, b_sig) if len(a_sig) <= len(b_sig) else (b_sig, a_sig)

    if len(A) < 2:  # Need at least 2 frames for meaningful comparison
        return None

    best_distance = None

    # Calculate content complexity for adaptive thresholding
    def _estimate_complexity(sig):
        if len(sig) < 2:
            return 1.0
        # Estimate complexity based on frame-to-frame variation
        variations = []
        for i in range(len(sig) - 1):
            x = int(sig[i]) ^ int(sig[i + 1])
            variations.append(x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1"))
        return max(1.0, sum(variations) / len(variations) / 16.0)  # Normalize to 0-4 range

    complexity_factor = min(2.0, _estimate_complexity(A))
    adaptive_threshold = per_frame_thresh * complexity_factor

    # Try different alignment strategies
    strategies = [
        (1, 0),      # Standard 1:1 alignment
        (2, 0),      # Skip every other frame in B (handles different frame rates)
        (1, 1),      # Skip first frame in B (handles intro/outro differences)
    ]

    for step, start_offset in strategies:
        max_positions = (len(B) - start_offset - 1) // step + 1
        if max_positions < len(A):
            continue

        for base_offset in range(0, max_positions - len(A) + 1):
            total_distance = 0
            valid_comparisons = 0

            for i in range(len(A)):
                b_idx = start_offset + base_offset + (i * step)
                if b_idx >= len(B):
                    break

                x = int(A[i]) ^ int(B[b_idx])
                frame_distance = x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
                total_distance += frame_distance
                valid_comparisons += 1

            if valid_comparisons >= min(3, len(A)):  # Need minimum valid comparisons
                avg_distance = total_distance / valid_comparisons
                if best_distance is None or avg_distance < best_distance:
                    best_distance = avg_distance

    return best_distance if (best_distance is not None and best_distance <= adaptive_threshold) else None


def group_by_same_size(files: Iterable[FileMeta]) -> Dict[str, List[FileMeta]]:
    bucket: Dict[int, List[FileMeta]] = defaultdict(list)
    for m in files:
        bucket[m.size].append(m)
    out: Dict[str, List[FileMeta]] = {}
    for size, lst in bucket.items():
        if len(lst) > 1:
            out[f"size:{size}"] = lst
    return out
