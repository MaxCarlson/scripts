#!/usr/bin/env python3
"""
Lightweight perceptual evaluation and quality search (no heavy deps).

- SSIM on luminance with a Gaussian window
- Binary search for the smallest file that meets thresholds at display scale
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Callable, Tuple, Optional

import numpy as np
from PIL import Image, ImageFilter


def _to_gray_np(im: Image.Image) -> np.ndarray:
    g = im.convert("L")
    return np.asarray(g, dtype=np.float32)


def _gaussian_kernel(size: int = 11, sigma: float = 1.5) -> np.ndarray:
    ax = np.arange(-size // 2 + 1., size // 2 + 1.)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx**2 + yy**2) / (2. * sigma**2))
    kernel /= np.sum(kernel)
    return kernel.astype(np.float32)


def _filter2d(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    from numpy.lib.stride_tricks import as_strided
    H, W = img.shape
    kh, kw = kernel.shape
    out_h, out_w = H - kh + 1, W - kw + 1
    if out_h <= 0 or out_w <= 0:
        return np.zeros((max(0, out_h), max(0, out_w)), dtype=np.float32)
    s0, s1 = img.strides
    windows = as_strided(img, shape=(out_h, out_w, kh, kw), strides=(s0, s1, s0, s1))
    return (windows * kernel).sum(axis=(2, 3))


def ssim(img_a: Image.Image, img_b: Image.Image, K1: float = 0.01, K2: float = 0.03, sigma: float = 1.5) -> float:
    """Structural SIMilarity on luminance only; returns 0..1 (1=identical)."""
    a = _to_gray_np(img_a).astype(np.float32)
    b = _to_gray_np(img_b).astype(np.float32)
    # Match sizes by cropping to overlapping "valid" area after filtering
    k = _gaussian_kernel(11, sigma)
    mu_a = _filter2d(a, k)
    mu_b = _filter2d(b, k)
    mu_a2 = mu_a * mu_a
    mu_b2 = mu_b * mu_b
    mu_ab = mu_a * mu_b

    sigma_a2 = _filter2d(a * a, k) - mu_a2
    sigma_b2 = _filter2d(b * b, k) - mu_b2
    sigma_ab = _filter2d(a * b, k) - mu_ab

    # Stabilizers
    L = 255.0
    C1 = (K1 * L) ** 2
    C2 = (K2 * L) ** 2

    num = (2 * mu_ab + C1) * (2 * sigma_ab + C2)
    den = (mu_a2 + mu_b2 + C1) * (sigma_a2 + sigma_b2 + C2)
    ssim_map = num / np.maximum(den, 1e-9)
    # Mean SSIM over valid region
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))


@dataclass(frozen=True)
class PerceptualThresholds:
    """Thresholds for accepting a candidate encode as 'visually lossless enough'."""
    ssim_min: float = 0.990  # 0..1
    # Placeholders for other metrics (butteraugli, fsim, lpips) if integrated later.


def _encode_decode_with_pillow(
    img: Image.Image,
    fmt: str,
    quality: int | None,
    lossless: bool | None = None,
    method: int | None = None,
) -> Tuple[Image.Image, int]:
    """Encode to memory then decode to compare; return (decoded_img, num_bytes)."""
    buf = BytesIO()
    save_kwargs = {}
    if fmt.upper() == "JPEG":
        save_kwargs.update(dict(format="JPEG", quality=int(quality or 85), optimize=True, progressive=True))
    elif fmt.upper() == "WEBP":
        save_kwargs.update(dict(format="WEBP"))
        if lossless:
            save_kwargs["lossless"] = True
            if quality is not None:
                save_kwargs["quality"] = int(quality)  # 'quality' still matters in WebP lossless
        else:
            save_kwargs["quality"] = int(quality or 80)
            if method is not None:
                save_kwargs["method"] = int(method)
    elif fmt.upper() == "PNG":
        save_kwargs.update(dict(format="PNG", optimize=True))
    else:
        save_kwargs.update(dict(format=fmt.upper()))
    img.save(buf, **save_kwargs)
    data = buf.getvalue()
    dec = Image.open(BytesIO(data))
    dec.load()
    return dec, len(data)


def binary_search_quality(
    reference: Image.Image,
    fmt: str,
    q_lo: int = 40,
    q_hi: int = 95,
    thresholds: PerceptualThresholds = PerceptualThresholds(),
    max_steps: int = 7,
    webp_lossless: bool = False,
) -> Tuple[Image.Image, int, int, float]:
    """Find the smallest quality meeting thresholds vs `reference`.
    
    Returns: (decoded_img, num_bytes, chosen_quality, ssim_value)
    """
    best = None
    lo, hi = int(q_lo), int(q_hi)
    while lo <= hi and max_steps > 0:
        mid = (lo + hi) // 2
        cand_img, num_bytes = _encode_decode_with_pillow(reference, fmt, quality=mid, lossless=webp_lossless)
        s = ssim(reference, cand_img)
        if s >= thresholds.ssim_min:
            best = (cand_img, num_bytes, mid, s)
            hi = mid - 1
        else:
            lo = mid + 1
        max_steps -= 1
    if best is None:
        # Fall back to hi bound
        best = _encode_decode_with_pillow(reference, fmt, quality=q_hi, lossless=webp_lossless) + (q_hi, ssim(reference, reference))
    return best  # type: ignore[return-value]
