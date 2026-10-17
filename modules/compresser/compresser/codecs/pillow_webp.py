#!/usr/bin/env python3
"""
Pillow-based WebP codec (wrapping libwebp).
"""

from __future__ import annotations

import io
from typing import Any
from PIL import Image

from .base import BaseCodec
from ..models import CompressionStrategy, WEBP_MAX_DIMENSION
from ..perceptual import find_optimal_quality, calculate_ssim


from ..trial_budget import trial_entry


class PillowWebpCodec(BaseCodec):
    """Encodes WebP images using Pillow's libwebp backend."""

    @property
    def name(self) -> str:
        return "pillow-webp"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("WEBP",)

    def is_available(self) -> bool:
        from PIL import features

        return bool(features.check("webp"))

    def _raw_encode(self, im: Image.Image, quality: int, method: int) -> bytes:
        target_im = im
        if target_im.mode not in ("RGB", "RGBA"):
            target_im = target_im.convert("RGBA" if "A" in im.mode or "transparency" in im.info else "RGB")
        buf = io.BytesIO()
        save_kwargs: dict[str, Any] = {
            "format": "WEBP",
            "quality": int(quality),
            "method": int(method),
            "lossless": False,
        }
        if "icc_profile" in im.info:
            save_kwargs["icc_profile"] = im.info["icc_profile"]
        if "exif" in im.info:
            save_kwargs["exif"] = im.info["exif"]
        if "xmp" in im.info:
            save_kwargs["xmp"] = im.info["xmp"]

        with trial_entry("webp"):
            target_im.save(buf, **save_kwargs)
        return buf.getvalue()

    def encode(
        self,
        im: Image.Image,
        target_format: str,
        strategy: CompressionStrategy,
    ) -> tuple[bytes, float | None]:
        w, h = im.size
        if w > WEBP_MAX_DIMENSION or h > WEBP_MAX_DIMENSION:
            raise ValueError(f"Image dimension ({w}x{h}) exceeds WebP maximum limit of {WEBP_MAX_DIMENSION}px")

        target_im = im
        if target_im.mode not in ("RGB", "RGBA"):
            target_im = target_im.convert("RGBA" if "A" in im.mode or "transparency" in im.info else "RGB")

        if strategy.mode == "lossless":
            buf = io.BytesIO()
            save_kwargs: dict[str, Any] = {
                "format": "WEBP",
                "lossless": True,
                "method": strategy.method,
                "quality": 100,
                "exact": True,
            }
            if "icc_profile" in im.info:
                save_kwargs["icc_profile"] = im.info["icc_profile"]
            if "exif" in im.info:
                save_kwargs["exif"] = im.info["exif"]
            if "xmp" in im.info:
                save_kwargs["xmp"] = im.info["xmp"]

            with trial_entry(strategy.name or "webp"):
                target_im.save(buf, **save_kwargs)
            return buf.getvalue(), 1.0

        if strategy.mode == "perceptual":

            def encode_fn(img: Image.Image, q: int) -> bytes:
                return self._raw_encode(img, q, strategy.method)

            def decode_fn(data: bytes) -> Image.Image:
                return self.decode_bytes(data)

            q, encoded, achieved_ssim = find_optimal_quality(
                target_im, encode_fn, decode_fn, strategy.perceptual_target
            )
            return encoded, achieved_ssim

        # Explicit lossy mode
        encoded = self._raw_encode(target_im, strategy.quality, strategy.method)
        decoded = self.decode_bytes(encoded)
        ssim = calculate_ssim(target_im, decoded)
        return encoded, ssim
