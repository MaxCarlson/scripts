#!/usr/bin/env python3
"""
Analysis & planning for image compression.

- Detect leaf "manga/chapter" folders that contain images but whose subdirs do not.
- Collect per-image metadata (size, resolution, proxy quality metrics).
- Compute per-folder statistics: count, size stats, resolution stats,
  most-common resolution, quality stats (min/max/avg/median).
- Decide a compression plan per folder given heuristics and phone display constraints
  or user goals (target size / reduction).
"""

from __future__ import annotations

import os
import statistics
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image

from .metrics import quick_quality_tuple

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class ImageInfo:
    path: Path
    bytes: int
    width: int
    height: int
    mode: str
    entropy_bits: float
    lap_var: float

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000.0


@dataclass
class FolderStats:
    count: int
    bytes_min: int
    bytes_max: int
    bytes_avg: float
    bytes_median: float
    width_min: int
    width_max: int
    width_avg: float
    height_min: int
    height_max: int
    height_avg: float
    q_entropy_min: float
    q_entropy_max: float
    q_entropy_avg: float
    q_entropy_median: float
    q_lap_min: float
    q_lap_max: float
    q_lap_avg: float
    q_lap_median: float
    modes: Counter[str]
    common_res: Optional[Tuple[int, int]] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        if self.common_res is not None:
            d["common_res"] = {"width": self.common_res[0], "height": self.common_res[1]}
        return d


@dataclass
class Plan:
    downsample_ratio: float  # 0<r<=1
    target_format: Optional[str]  # None keeps original; or "jpeg"|"webp"|"png"
    jpeg_quality: int  # 1..95 (safe Pillow range)
    webp_quality: int  # 1..100
    png_quantize_colors: Optional[int]  # e.g., 256 or None
    note: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def bytes_human(n: int) -> str:
    step = 1024.0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(n)
    for u in units:
        if x < step:
            return f"{x:.0f}{u}" if u == 'B' else f"{x:.2f}{u}"
        x /= step
    return f"{x:.2f}PiB"


def collect_images(folder: Path) -> List[Path]:
    out: List[Path] = []
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
            out.append(p)
    return out


def is_leaf_dir(dirpath: Path, *, exclude_names: Tuple[str, ...] = ("_compressed", "_tmp", ".Hentoid")) -> bool:
    """A leaf dir contains at least one image, and none of its subdirs contain images.
       Also skip any directory whose name starts with '_' or matches exclude_names.
    """
    name = dirpath.name
    if name.startswith("_") or name in exclude_names:
        return False
    try:
        entries = list(dirpath.iterdir())
    except PermissionError:
        return False
    has_images = any(e.is_file() and e.suffix.lower() in SUPPORTED_EXT for e in entries)
    if not has_images:
        return False
    for sub in entries:
        if sub.is_dir():
            subname = sub.name
            if subname.startswith("_") or subname in exclude_names:
                continue
            try:
                if any(child.is_file() and child.suffix.lower() in SUPPORTED_EXT for child in sub.iterdir()):
                    return False
            except PermissionError:
                continue
    return True


def find_leaf_image_dirs(root: Path) -> List[Path]:
    leaves: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        p = Path(dirpath)
        if is_leaf_dir(p):
            leaves.append(p)
    return sorted(leaves)


def analyze_images(images: Iterable[Path]) -> Tuple[List[ImageInfo], Optional[FolderStats]]:
    infos: List[ImageInfo] = []
    for path in images:
        try:
            size = path.stat().st_size
            with Image.open(path) as im:
                w, h = im.size
                mode = im.mode
                ent, lap = quick_quality_tuple(im)
            infos.append(ImageInfo(path=path, bytes=size, width=w, height=h, mode=mode, entropy_bits=ent, lap_var=lap))
        except Exception:
            # Skip unreadables
            continue

    if not infos:
        return [], None

    sizes = [i.bytes for i in infos]
    widths = [i.width for i in infos]
    heights = [i.height for i in infos]
    ents = [i.entropy_bits for i in infos]
    laps = [i.lap_var for i in infos]
    modes = Counter(i.mode for i in infos)
    res_counter = Counter((i.width, i.height) for i in infos)
    common_res = None
    if res_counter:
        (w, h), _ = res_counter.most_common(1)[0]
        common_res = (w, h)

    stats = FolderStats(
        count=len(infos),
        bytes_min=min(sizes),
        bytes_max=max(sizes),
        bytes_avg=sum(sizes) / len(sizes),
        bytes_median=statistics.median(sizes),
        width_min=min(widths),
        width_max=max(widths),
        width_avg=sum(widths) / len(widths),
        height_min=min(heights),
        height_max=max(heights),
        height_avg=sum(heights) / len(heights),
        q_entropy_min=min(ents),
        q_entropy_max=max(ents),
        q_entropy_avg=sum(ents) / len(ents),
        q_entropy_median=statistics.median(ents),
        q_lap_min=min(laps),
        q_lap_max=max(laps),
        q_lap_avg=sum(laps) / len(laps),
        q_lap_median=statistics.median(laps),
        modes=modes,
        common_res=common_res,
    )
    return infos, stats


def _auto_target_format(prefer_format: Optional[str], ext: str) -> Optional[str]:
    if prefer_format:
        return prefer_format.lower()
    ext = ext.lower()
    if ext in (".jpg", ".jpeg"):
        return None  # keep
    if ext == ".webp":
        return None  # keep
    if ext == ".png":
        # PNG defaults to keep; quantization parameter controls size
        return None
    return None


def decide_plan(stats: FolderStats, *,
                phone_max_dim: Optional[int] = None,
                prefer_format: Optional[str] = None,
                png_quantize_colors: Optional[int] = None) -> Plan:
    """
    Heuristic: larger average files → smaller ratio + lower lossy quality.
    - If phone_max_dim provided, also cap the ratio to avoid exceeding display utility.
    - Target format is auto when not specified (keep original).
    """
    avg_mb = stats.bytes_avg / (1024 * 1024)

    # Base downsample ratio by average size bucket.
    if avg_mb > 6:
        ratio = 0.5
        jpeg_q = 70
        webp_q = 68
    elif avg_mb > 3:
        ratio = 0.65
        jpeg_q = 78
        webp_q = 75
    elif avg_mb > 1.5:
        ratio = 0.8
        jpeg_q = 85
        webp_q = 82
    else:
        ratio = 1.0
        jpeg_q = 90
        webp_q = 88

    # Respect phone max dimension (long edge).
    if phone_max_dim:
        max_edge = max(stats.width_max, stats.height_max)
        if max_edge > 0:
            ratio = min(ratio, max(0.1, float(phone_max_dim) / float(max_edge)))

    fmt = prefer_format.lower() if prefer_format else None
    note = "heuristic plan"

    return Plan(
        downsample_ratio=max(0.1, min(1.0, ratio)),
        target_format=fmt,
        jpeg_quality=max(1, min(95, jpeg_q)),
        webp_quality=max(1, min(100, webp_q)),
        png_quantize_colors=png_quantize_colors,
        note=note,
    )


def predict_after_bytes(infos: List[ImageInfo], plan: Plan) -> int:
    """
    Rough sizing model:
    new_bytes ≈ old_bytes * (ratio^2) * quality_factor (lossy) or ~0.6 (png optimize/quant).
    """
    total = 0
    for info in infos:
        factor = plan.downsample_ratio ** 2
        ext = info.path.suffix.lower()
        if (plan.target_format or ext in {".jpg", ".jpeg", ".webp"}) and ext != ".png":
            # lossy factor
            q = plan.webp_quality if (plan.target_format == "webp" or ext == ".webp") else plan.jpeg_quality
            factor *= (q / 100.0)
            factor = max(factor, 0.08)  # clamp
        else:
            # png-ish lossless/quant
            factor *= 0.6 if plan.png_quantize_colors else 0.85
            factor = max(factor, 0.2)
        total += int(info.bytes * factor)
    return total


def tune_plan_for_target(infos: List[ImageInfo],
                         base_plan: Plan,
                         *,
                         target_ratio: Optional[float] = None,
                         target_total_bytes: Optional[int] = None) -> Plan:
    """
    Adjust plan's downsample_ratio (and slightly quality) to approach a target ratio or total bytes.
    Use a coarse binary search over ratio in [0.1, base_ratio].
    """
    want = None
    total_before = sum(i.bytes for i in infos) or 1
    if target_total_bytes is not None:
        want = max(1, int(target_total_bytes))
    elif target_ratio is not None:
        want = max(1, int(total_before * max(0.05, min(1.0, target_ratio))))
    else:
        return base_plan

    lo, hi = 0.1, base_plan.downsample_ratio
    best = base_plan
    for _ in range(12):
        mid = (lo + hi) / 2.0
        cand = Plan(
            downsample_ratio=mid,
            target_format=base_plan.target_format,
            jpeg_quality=base_plan.jpeg_quality,
            webp_quality=base_plan.webp_quality,
            png_quantize_colors=base_plan.png_quantize_colors,
            note="tuned",
        )
        est = predict_after_bytes(infos, cand)
        if est <= want:
            best = cand
            hi = mid
        else:
            lo = mid
    return best
