#!/usr/bin/env python3
"""
Compression & I/O operations.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from .analysis import Plan


@dataclass
class CompressResult:
    input_path: Path
    output_path: Path
    before_bytes: int
    after_bytes: int
    width_before: int
    height_before: int
    width_after: int
    height_after: int
    elapsed_s: float


def make_backup(src: Path, enable: bool, suffix: str = ".orig") -> Optional[Path]:
    if not enable:
        return None
    dst = src.with_suffix(src.suffix + suffix)
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def resize_image(im: Image.Image, ratio: float) -> Image.Image:
    if ratio >= 0.999:
        return im
    w, h = im.size
    nw = max(1, int(w * ratio))
    nh = max(1, int(h * ratio))
    return im.resize((nw, nh), Image.LANCZOS)


def choose_output_format(src: Path, plan: Plan) -> str:
    if plan.target_format:
        return plan.target_format.lower()
    ext = src.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "jpeg"
    if ext == ".webp":
        return "webp"
    if ext == ".png":
        return "png"
    return "jpeg"


def save_with_format(im: Image.Image, dest: Path, fmt: str, plan: Plan) -> None:
    fmt = fmt.lower()
    kwargs = {}

    if fmt in ("jpg", "jpeg"):
        kwargs["quality"] = plan.jpeg_quality
        kwargs["optimize"] = True
        fmt = "JPEG"
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
    elif fmt == "webp":
        kwargs["quality"] = plan.webp_quality
        kwargs["method"] = 6
        kwargs["lossless"] = False
        fmt = "WEBP"
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
    elif fmt == "png":
        kwargs["optimize"] = True
        fmt = "PNG"
        if plan.png_quantize_colors:
            im = im.convert("RGB").quantize(colors=plan.png_quantize_colors, method=Image.MEDIANCUT)
    else:
        kwargs["quality"] = plan.jpeg_quality
        kwargs["optimize"] = True
        fmt = "JPEG"
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")

    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, format=fmt, **kwargs)


def compress_one(src: Path, out_dir: Optional[Path], plan: Plan,
                 overwrite: bool = False, backup: bool = False) -> CompressResult:
    """
    Compress a single image using plan. Returns result with timings and sizes.
    If out_dir is None and overwrite=True, writes back to src.
    """
    t0 = time.time()
    src = src.resolve()
    before = src.stat().st_size

    with Image.open(src) as im:
        w0, h0 = im.size
        im2 = resize_image(im, plan.downsample_ratio)

        fmt = choose_output_format(src, plan)
        if out_dir:
            # Ensure we *only* create a single level _compressed, not nested repeatedly.
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = (out_dir / src.name).with_suffix("." + fmt if fmt != src.suffix.lstrip(".") else src.suffix)
        else:
            dest = src if overwrite else src.with_name(src.stem + "_shrink" + src.suffix)

        if overwrite and backup:
            make_backup(src, True)

        save_with_format(im2, dest, fmt, plan)

    after = dest.stat().st_size
    t1 = time.time()
    with Image.open(dest) as imout:
        w1, h1 = imout.size

    return CompressResult(
        input_path=src,
        output_path=dest,
        before_bytes=before,
        after_bytes=after,
        width_before=w0,
        height_before=h0,
        width_after=w1,
        height_after=h1,
        elapsed_s=(t1 - t0),
    )