#!/usr/bin/env python3
"""
Pillow-based JPEG codec (wrapping libjpeg-turbo).
"""

from __future__ import annotations

import io
from typing import Any
from PIL import Image

from .base import BaseCodec
from ..models import CompressionStrategy
from ..perceptual import find_optimal_quality, calculate_ssim
from ..trial_budget import trial_entry


class PillowJpegCodec(BaseCodec):
    """Encodes JPEG images using Pillow's libjpeg-turbo backend."""

    @property
    def name(self) -> str:
        return "pillow-jpeg"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("JPEG", "JPG")

    def is_available(self) -> bool:
        return True

    def _raw_encode(self, im: Image.Image, quality: int, progressive: bool) -> bytes:
        target_im = im
        if target_im.mode in ("RGBA", "LA", "P"):
            target_im = target_im.convert("RGB")
        buf = io.BytesIO()
        save_kwargs: dict[str, Any] = {
            "format": "JPEG",
            "quality": int(quality),
            "optimize": True,
            "progressive": progressive,
        }
        if "icc_profile" in im.info:
            save_kwargs["icc_profile"] = im.info["icc_profile"]
        if "exif" in im.info:
            save_kwargs["exif"] = im.info["exif"]
        if "xmp" in im.info:
            save_kwargs["xmp"] = im.info["xmp"]

        with trial_entry("jpeg"):
            target_im.save(buf, **save_kwargs)
        return buf.getvalue()

    def encode(
        self,
        im: Image.Image,
        target_format: str,
        strategy: CompressionStrategy,
    ) -> tuple[bytes, float | None]:
        target_im = im
        if target_im.mode in ("RGBA", "LA", "P"):
            target_im = target_im.convert("RGB")

        if strategy.mode == "lossless":
            # Pillow decoding and re-saving JPEG is NOT lossless.
            # True lossless JPEG optimization requires jpegtran to optimize DCT Huffman tables directly.
            raise RuntimeError(
                "Lossless JPEG optimization is not supported by Pillow without recompression loss. "
                "Install jpegtran for DCT-level lossless JPEG optimization."
            )

        if strategy.mode == "perceptual":
            # Measure bounded candidates; reject if no quality meets the floor.
            def encode_fn(img: Image.Image, q: int) -> bytes:
                return self._raw_encode(img, q, strategy.progressive)

            def decode_fn(data: bytes) -> Image.Image:
                return self.decode_bytes(data)

            q, encoded, achieved_ssim = find_optimal_quality(
                target_im, encode_fn, decode_fn, strategy.perceptual_target
            )
            return encoded, achieved_ssim

        # Explicit lossy mode
        encoded = self._raw_encode(target_im, strategy.quality, strategy.progressive)
        decoded = self.decode_bytes(encoded)
        ssim = calculate_ssim(target_im, decoded)
        return encoded, ssim
