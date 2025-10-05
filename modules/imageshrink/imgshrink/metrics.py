#!/usr/bin/env python3
"""
Lightweight image "quality" and content metrics with no heavy deps.

We deliberately avoid OpenCV/scikit-image to keep Termux/WSL/Windows easy.
These are *proxies* for fidelity/complexity, not absolute truth:

- entropy: Shannon entropy over 256-level grayscale histogram
- laplacian_var: variance of a 3x3 Laplacian filter (proxy for sharpness)
"""

from __future__ import annotations

import math
from typing import Tuple

from PIL import Image
import numpy as np


def to_gray(im: Image.Image) -> np.ndarray:
    """Return grayscale image as float32 numpy array normalized to [0,1]."""
    g = im.convert("L")
    a = np.asarray(g, dtype=np.float32) / 255.0
    return a


def entropy(im: Image.Image) -> float:
    """Shannon entropy (bits) of grayscale histogram (256 bins)."""
    g = im.convert("L")
    hist = g.histogram()  # 256 bins
    total = float(sum(hist)) or 1.0
    ent = 0.0
    for c in hist:
        if c <= 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return ent  # 0..8 for 8-bit images


def laplacian_var(im: Image.Image) -> float:
    """
    Variance of 3x3 Laplacian filter response (proxy for sharpness).
    The higher the variance, typically the "sharper" the image.
    """
    a = to_gray(im)
    # 3x3 Laplacian kernel
    k = np.array([[0, 1, 0],
                  [1, -4, 1],
                  [0, 1, 0]], dtype=np.float32)
    # simple convolution (valid area)
    from numpy.lib.stride_tricks import as_strided

    H, W = a.shape
    kh, kw = k.shape
    out_h, out_w = H - kh + 1, W - kw + 1
    if out_h <= 0 or out_w <= 0:
        return 0.0
    s0, s1 = a.strides
    windows = as_strided(a, shape=(out_h, out_w, kh, kw), strides=(s0, s1, s0, s1))
    resp = (windows * k).sum(axis=(2, 3))
    return float(resp.var())


def quick_quality_tuple(im: Image.Image) -> Tuple[float, float]:
    """
    Return (entropy_bits, laplacian_var) for reporting and per-folder stats.
    """
    return entropy(im), laplacian_var(im)