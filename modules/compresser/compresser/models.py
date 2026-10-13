#!/usr/bin/env python3
"""
Data structures for the image compression module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Mode = Literal["lossless", "lossy", "perceptual"]
TargetFormat = Literal["auto", "webp", "jpeg", "avif", "png", "keep"]

WEBP_MAX_DIMENSION = 16383
JPEG_MAX_DIMENSION = 65535


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    """Metadata describing a single image on disk."""

    path: Path
    format: str
    width: int
    height: int
    size_bytes: int
    is_grayscale: bool = False
    mtime_ns: int = 0

    @property
    def aspect_ratio(self) -> float:
        return self.width / max(1, self.height)

    @property
    def is_tall_for_webp(self) -> bool:
        return self.width > WEBP_MAX_DIMENSION or self.height > WEBP_MAX_DIMENSION


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Aggregated statistics for a scanned directory or image set."""

    target_path: Path
    total_images: int
    total_bytes: int
    format_counts: dict[str, int] = field(default_factory=dict)
    format_bytes: dict[str, int] = field(default_factory=dict)
    tall_images_count: int = 0
    grayscale_count: int = 0


@dataclass(frozen=True, slots=True)
class CompressionStrategy:
    """Settings defining a compression approach."""

    name: str
    format: TargetFormat = "auto"
    mode: Mode = "lossless"
    quality: int = 80
    perceptual_target: float = 0.990
    method: int = 6
    progressive: bool = True
    allow_larger: bool = False
    allow_lossy: bool = False
    extra_params: dict[str, Any] = field(default_factory=dict)
    encoder: str = "auto"


@dataclass(frozen=True, slots=True)
class ImageResult:
    """Result of analyzing or compressing a single image."""

    input_path: Path
    output_path: Path
    original_bytes: int
    compressed_bytes: int
    original_format: str
    output_format: str
    ssim: float | None = None
    elapsed_s: float = 0.0
    applied: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None
    encoder: str | None = None
    cache_hit: bool = False
    candidate_bytes: int | None = None
    phase_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_bytes - self.compressed_bytes)

    @property
    def savings_percent(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return max(0.0, ((self.original_bytes - self.compressed_bytes) / self.original_bytes) * 100.0)


@dataclass(slots=True)
class BatchResult:
    """Aggregated outcome of an analysis or compression batch."""

    strategy_name: str
    total_images: int
    processed_images: int
    original_bytes: int
    compressed_bytes: int
    saved_bytes: int
    savings_percent: float
    average_ssim: float | None
    elapsed_seconds: float
    throughput_images_per_s: float
    throughput_bytes_per_s: float
    applied_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool
    results: list[ImageResult] = field(default_factory=list)
    worker_diagnostics: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """Row in a multi-strategy comparison table."""

    strategy_name: str
    output_format: str
    mode: str
    quality_display: str
    compressed_bytes: int
    saved_bytes: int
    savings_percent: float
    average_ssim: float | None
    throughput_images_per_s: float
    measured_images: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    cache_hits: int = 0
    error_summary: tuple[str, ...] = ()
    candidate_bytes: int | None = None
    original_bytes: int = 0
    worker_diagnostics: dict = field(default_factory=dict)
