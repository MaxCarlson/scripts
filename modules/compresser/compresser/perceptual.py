#!/usr/bin/env python3
"""
Lightweight perceptual evaluation and SSIM quality search.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from PIL import Image
from .cancellation import check_cancelled
from .timing import timed


def _to_gray_np(im: Image.Image) -> np.ndarray:
    g = im.convert("L")
    return np.asarray(g, dtype=np.float32)


def _gaussian_kernel(size: int = 11, sigma: float = 1.5) -> np.ndarray:
    ax = np.arange(-size // 2 + 1.0, size // 2 + 1.0)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx**2 + yy**2) / (2.0 * sigma**2))
    kernel /= np.sum(kernel)
    return kernel.astype(np.float32)


def _filter2d(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Separable Gaussian filtering without an H*W*11*11 allocation."""
    H, W = img.shape
    kh, kw = kernel.shape
    out_h, out_w = H - kh + 1, W - kw + 1
    if out_h <= 0 or out_w <= 0:
        return np.zeros((max(0, out_h), max(0, out_w)), dtype=np.float32)
    horizontal = kernel.sum(axis=0)
    vertical = kernel.sum(axis=1)
    first = np.apply_along_axis(lambda row: np.convolve(row, horizontal, mode="valid"), 1, img)
    return np.apply_along_axis(lambda col: np.convolve(col, vertical, mode="valid"), 0, first)


def _channel_ssim(
    img_a: Image.Image,
    img_b: Image.Image,
    *,
    k1: float = 0.01,
    k2: float = 0.03,
    sigma: float = 1.5,
    max_eval_dim: int = 1024,
) -> float:
    """
    Compute Structural Similarity (SSIM) on luminance channel between two images.
    Returns float in range [0.0, 1.0] where 1.0 represents visual identity.
    """
    # Downscale large images for fast perceptual evaluation if necessary
    w_a, h_a = img_a.size
    w_b, h_b = img_b.size
    if (w_a, h_a) != (w_b, h_b):
        img_b = img_b.resize((w_a, h_a), Image.Resampling.BILINEAR)

    if max(w_a, h_a) > max_eval_dim:
        scale = max_eval_dim / max(w_a, h_a)
        target_size = (max(16, int(w_a * scale)), max(16, int(h_a * scale)))
        img_a = img_a.resize(target_size, Image.Resampling.BILINEAR)
        img_b = img_b.resize(target_size, Image.Resampling.BILINEAR)

    a = _to_gray_np(img_a).astype(np.float32)
    b = _to_gray_np(img_b).astype(np.float32)

    kernel_size = min(11, *a.shape)
    if kernel_size % 2 == 0:
        kernel_size -= 1
    k = _gaussian_kernel(max(1, kernel_size), sigma)
    mu_a = _filter2d(a, k)
    mu_b = _filter2d(b, k)
    mu_a2 = mu_a * mu_a
    mu_b2 = mu_b * mu_b
    mu_ab = mu_a * mu_b

    sigma_a2 = _filter2d(a * a, k) - mu_a2
    sigma_b2 = _filter2d(b * b, k) - mu_b2
    sigma_ab = _filter2d(a * b, k) - mu_ab

    L = 255.0
    c1 = (k1 * L) ** 2
    c2 = (k2 * L) ** 2

    num = (2 * mu_ab + c1) * (2 * sigma_ab + c2)
    den = (mu_a2 + mu_b2 + c1) * (sigma_a2 + sigma_b2 + c2)
    ssim_map = num / np.maximum(den, 1e-9)
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))


@timed("similarity")
def calculate_ssim(
    img_a: Image.Image,
    img_b: Image.Image,
    *,
    k1: float = 0.01,
    k2: float = 0.03,
    sigma: float = 1.5,
    max_eval_dim: int = 1024,
) -> float:
    """Conservative sampled RGB/detail SSIM, not a guarantee of visual identity.

    Worst channel protects equal-luminance color shifts; three native-resolution
    detail patches protect screentones erased by whole-page downsampling.
    """
    if img_a.size != img_b.size:
        raise ValueError("Perceptual comparison requires identical dimensions")
    if max_eval_dim < 16:
        raise ValueError("Metric evaluation dimension must be at least16")
    options = {"k1": k1, "k2": k2, "sigma": sigma, "max_eval_dim": max_eval_dim}
    first, second = img_a.convert("RGB"), img_b.convert("RGB")
    scores = [
        _channel_ssim(first.getchannel(channel), second.getchannel(channel), **options) for channel in ("R", "G", "B")
    ]
    if max(img_a.size) > max_eval_dim:
        width, height = img_a.size
        patch_w, patch_h = min(256, width), min(256, height)
        for ratio in (0, 0.5, 1):
            x, y = round((width - patch_w) * ratio), round((height - patch_h) * ratio)
            box = (x, y, x + patch_w, y + patch_h)
            scores.append(_channel_ssim(img_a.crop(box), img_b.crop(box), **options))
    return min(scores)


def is_grayscale_image(img: Image.Image) -> bool:
    """Quickly check if an image is effectively grayscale (e.g. manga line-art)."""
    if img.mode in ("1", "L", "LA"):
        return True
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Sample a small thumbnail to detect color saturation
    thumb = img.resize((64, 64), Image.Resampling.BOX)
    arr = np.asarray(thumb, dtype=np.int16)
    if arr.ndim < 3 or arr.shape[2] < 3:
        return True

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    diff = np.maximum(np.maximum(np.abs(r - g), np.abs(g - b)), np.abs(r - b))
    # If 98% of pixels have color difference <= 4, it is grayscale line-art
    return float(np.mean(diff <= 4)) >= 0.98


def binary_search_quality(
    original: Image.Image,
    encode_fn: Callable[[Image.Image, int], bytes],
    decode_fn: Callable[[bytes], Image.Image],
    target_ssim: float,
    *,
    q_min: int = 45,
    q_max: int = 95,
) -> tuple[int, bytes, float]:
    """
    Binary search for the lowest quality that achieves target SSIM.
    Returns (chosen_quality, encoded_bytes, achieved_ssim).
    """
    best_q = q_max
    best_bytes = b""
    best_ssim = 1.0

    low = q_min
    high = q_max

    while low <= high:
        mid = (low + high) // 2
        encoded = encode_fn(original, mid)
        decoded = decode_fn(encoded)
        current_ssim = calculate_ssim(original, decoded)

        if current_ssim >= target_ssim:
            best_q = mid
            best_bytes = encoded
            best_ssim = current_ssim
            # Try lower quality
            high = mid - 1
        else:
            # Quality too low, search higher
            low = mid + 1

    if not best_bytes:
        best_bytes = encode_fn(original, q_max)
        best_ssim = calculate_ssim(original, decode_fn(best_bytes))

    return best_q, best_bytes, best_ssim


def find_optimal_quality(
    original: Image.Image,
    encode_fn: Callable[[Image.Image, int], bytes],
    decode_fn: Callable[[bytes], Image.Image],
    target_ssim: float,
    *,
    candidates: tuple[int, ...] = (60, 70, 78, 85, 90, 95),
) -> tuple[int, bytes, float]:
    """
    Search discrete quality candidates to avoid non-monotonic binary search issues.
    Returns (chosen_quality, encoded_bytes, achieved_ssim).
    """
    if not candidates:
        raise ValueError("At least one quality candidate is required")
    best = None
    for q in sorted(set(candidates)):
        check_cancelled()
        encoded = encode_fn(original, q)
        check_cancelled()
        with decode_fn(encoded) as decoded:
            current_ssim = calculate_ssim(original, decoded)
        if current_ssim >= target_ssim and (best is None or len(encoded) < len(best[1])):
            best = (q, encoded, current_ssim)
    if best is None:
        raise ValueError("No quality candidate meets the requested perceptual threshold")
    return best
