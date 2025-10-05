#!/usr/bin/env python3
"""
Additional image/content metrics to guide perceptual compression.

Zero heavy deps: Pillow + NumPy only.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from typing import Tuple, Dict, Any

import numpy as np
from PIL import Image, ImageStat


@dataclass(frozen=True)
class BasicDims:
    width: int
    height: int
    bytes: int  # on-disk bytes

    @property
    def pixels(self) -> int:
        return max(1, self.width * self.height)

    @property
    def megapixels(self) -> float:
        return self.pixels / 1_000_000.0

    @property
    def file_bits_per_pixel(self) -> float:
        """Container-level bpp = (8 * file_bytes) / pixels."""
        return (8.0 * max(1, self.bytes)) / float(self.pixels)

    @property
    def bytes_per_megapixel(self) -> float:
        return max(1, self.bytes) / max(1e-6, self.megapixels)


def _to_rgb_np(im: Image.Image) -> np.ndarray:
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    arr = np.asarray(im, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]  # drop alpha
    return arr


def _to_gray_np(im: Image.Image) -> np.ndarray:
    # sRGB luminance coefficients
    g = im.convert("L")
    return np.asarray(g, dtype=np.float32)


def colorfulness_hasler_susstrunk(im: Image.Image) -> float:
    """Hasler–Süsstrunk colorfulness metric.
    https://www.epfl.ch/labs/ivrl/research/artificial-color/
    """
    rgb = _to_rgb_np(im)
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    rg = R - G
    yb = 0.5 * (R + G) - B
    std_rg, mean_rg = float(np.std(rg)), float(np.mean(rg))
    std_yb, mean_yb = float(np.std(yb)), float(np.mean(yb))
    return math.sqrt(std_rg ** 2 + std_yb ** 2) + 0.3 * math.sqrt(mean_rg ** 2 + mean_yb ** 2)


def is_effectively_grayscale(im: Image.Image, threshold: float = 8.0) -> bool:
    """Return True if colorfulness is below threshold (rough heuristic)."""
    return colorfulness_hasler_susstrunk(im) < threshold


def sobel_edge_density(im: Image.Image, threshold: float | None = None) -> float:
    """Fraction of pixels with gradient magnitude above a threshold."""
    rgb = _to_rgb_np(im)
    gray = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    H, W = gray.shape
    # Sobel kernels
    kx = np.array([[-1, 0, 1],
                   [-2, 0, 2],
                   [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[1, 2, 1],
                   [0, 0, 0],
                   [-1, -2, -1]], dtype=np.float32)
    # Convolve (valid region)
    from numpy.lib.stride_tricks import as_strided
    kh, kw = kx.shape
    out_h, out_w = H - kh + 1, W - kw + 1
    if out_h <= 0 or out_w <= 0:
        return 0.0
    s0, s1 = gray.strides
    windows = as_strided(gray, shape=(out_h, out_w, kh, kw), strides=(s0, s1, s0, s1))
    gx = (windows * kx).sum(axis=(2, 3))
    gy = (windows * ky).sum(axis=(2, 3))
    mag = np.hypot(gx, gy)
    if threshold is None:
        # adaptive: mean + 0.5*std
        t = float(mag.mean() + 0.5 * mag.std())
    else:
        t = float(threshold)
    active = (mag >= t).sum()
    total = mag.size
    return float(active) / float(max(1, total))


def otsu_separability(gray: np.ndarray | Image.Image) -> float:
    """Otsu separability measure (between-class variance / total variance)."""
    if isinstance(gray, Image.Image):
        gray = _to_gray_np(gray)
    hist, _ = np.histogram(gray, bins=256, range=(0, 255))
    hist = hist.astype(np.float64)
    prob = hist / max(1.0, hist.sum())
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]
    sigma_b2 = (mu_t * omega - mu) ** 2 / np.maximum(omega * (1.0 - omega), 1e-9)
    sigma_t2 = ((np.arange(256) - mu_t) ** 2 * prob).sum()
    if sigma_t2 <= 1e-12:
        return 0.0
    return float(np.max(sigma_b2) / sigma_t2)


def noise_proxy_highpass(im: Image.Image) -> float:
    """High-pass MAD as a robust noise proxy (bigger = noisier)."""
    g = _to_gray_np(im)
    k = np.array([[0, -1, 0],
                  [-1, 4, -1],
                  [0, -1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import as_strided
    H, W = g.shape
    kh, kw = k.shape
    out_h, out_w = H - kh + 1, W - kw + 1
    if out_h <= 0 or out_w <= 0:
        return 0.0
    s0, s1 = g.strides
    windows = as_strided(g, shape=(out_h, out_w, kh, kw), strides=(s0, s1, s0, s1))
    resp = (windows * k).sum(axis=(2, 3))
    med = np.median(resp)
    mad = np.median(np.abs(resp - med))
    return float(mad)


def jpeg_quant_summary(im: Image.Image) -> Dict[str, Any] | None:
    """Summarize JPEG quantization to detect low-quality sources."""
    if (im.format or "").upper() != "JPEG":
        return None
    qtables = getattr(im, "quantization", None)
    if not qtables:
        return None
    # Flatten all tables
    vals = []
    for _, tbl in qtables.items() if isinstance(qtables, dict) else enumerate(qtables):
        vals.extend(list(tbl))
    arr = np.asarray(vals, dtype=np.float32)
    return {
        "q_min": float(arr.min()),
        "q_max": float(arr.max()),
        "q_mean": float(arr.mean()),
        "q_median": float(np.median(arr)),
        "q_std": float(arr.std()),
    }


def estimate_jpeg_quality_level(im: Image.Image) -> float | None:
    """Very rough estimate: map average quantizer to a 0..100-like score."""
    s = jpeg_quant_summary(im)
    if not s:
        return None
    m = s["q_mean"]
    # Empirical monotonic mapping: lower avg q -> higher 'quality'
    val = 120.0 - 20.0 * math.log2(max(1.0, m))
    return float(max(1.0, min(100.0, val)))


def classify_content_simple(
    im: Image.Image,
    colorfulness_thresh: float = 8.0,
    edge_density_thresh: float = 0.06,
    otsu_thresh: float = 0.5,
) -> str:
    """Return 'lineart' or 'photo' based on lightweight cues."""
    cf = colorfulness_hasler_susstrunk(im)
    ed = sobel_edge_density(im)
    ots = otsu_separability(im.convert("L"))
    # line-art tends to low colorfulness + decent edge density + binarizable
    if cf < colorfulness_thresh and ed >= edge_density_thresh and ots >= otsu_thresh:
        return "lineart"
    return "photo"


def quick_content_metrics(im: Image.Image, file_bytes: int) -> Dict[str, float]:
    """Pack the metrics into a single dict for logging/aggregation."""
    dims = BasicDims(width=im.width, height=im.height, bytes=file_bytes)
    colorfulness = colorfulness_hasler_susstrunk(im)
    edgecov = sobel_edge_density(im)
    otsu = otsu_separability(im.convert("L"))
    noise = noise_proxy_highpass(im)
    jpeg_q = estimate_jpeg_quality_level(im)
    is_gray = 1.0 if is_effectively_grayscale(im) else 0.0
    d = {
        "megapixels": dims.megapixels,
        "file_bpp": dims.file_bits_per_pixel,
        "bytes_per_mp": dims.bytes_per_megapixel,
        "colorfulness": float(colorfulness),
        "edge_density": float(edgecov),
        "otsu_sep": float(otsu),
        "noise_proxy": float(noise),
        "jpeg_q_est": float(jpeg_q) if jpeg_q is not None else -1.0,
        "is_grayscale": is_gray,
    }
    return d
