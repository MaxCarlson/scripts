#!/usr/bin/env python3
"""
Base interface for compression codecs.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod

from PIL import Image

from ..models import CompressionStrategy


class BaseCodec(ABC):
    """Abstract codec base class."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the codec / encoder."""
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> tuple[str, ...]:
        """Tuple of image formats supported (e.g. ('JPEG', 'WEBP'))."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this codec is operational in the current environment."""
        ...

    @abstractmethod
    def encode(
        self,
        im: Image.Image,
        target_format: str,
        strategy: CompressionStrategy,
    ) -> tuple[bytes, float | None]:
        """
        Encode PIL image using the specified strategy.
        Returns (encoded_bytes, achieved_ssim_or_None).
        """
        ...

    @staticmethod
    def decode_bytes(data: bytes) -> Image.Image:
        """Decode raw bytes into a PIL Image."""
        buf = io.BytesIO(data)
        im = Image.open(buf)
        im.load()
        return im
