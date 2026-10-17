#!/usr/bin/env python3
"""
Pillow-based AVIF codec.
"""

from __future__ import annotations

import io
from PIL import Image

from .base import BaseCodec
from ..models import CompressionStrategy
from ..perceptual import calculate_ssim


class PillowAvifCodec(BaseCodec):
    """Encodes AVIF images using Pillow's AVIF plugin."""

    @property
    def name(self) -> str:
        return "pillow-avif"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("AVIF",)

    def is_available(self) -> bool:
        from PIL import features

        return bool(features.check("avif"))

    def encode(
        self,
        im: Image.Image,
        target_format: str,
        strategy: CompressionStrategy,
    ) -> tuple[bytes, float | None]:
        if not self.is_available():
            raise RuntimeError("AVIF encoding is not supported by the current Pillow installation")
        if strategy.mode != "lossy":
            raise ValueError("AVIF adapter supports explicit lossy mode only; quality 100 is not lossless")

        target_im = im
        if target_im.mode not in ("RGB", "RGBA"):
            target_im = target_im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")

        buf = io.BytesIO()
        target_im.save(
            buf,
            format="AVIF",
            quality=int(strategy.quality),
            max_threads=1,
            **{key: im.info[key] for key in ("icc_profile", "exif", "xmp") if key in im.info},
        )
        encoded = buf.getvalue()

        decoded = self.decode_bytes(encoded)
        ssim = calculate_ssim(target_im, decoded)
        return encoded, ssim
