#!/usr/bin/env python3
"""
Compresser — Reusable image compression, analysis, and perceptual optimization module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .cache import AnalysisCache
from .codecs import discover_available_codecs
from .engine import CompressionEngine
from .models import (
    BatchResult,
    ComparisonRow,
    CompressionStrategy,
    ImageMetadata,
    ImageResult,
    ScanSummary,
)
from .sampling import GallerySample, confirmation_sample, gallery_sample
from .scanner import inspect_image_file, scan_directory, select_sample
from .ui import recommend_comparison_strategies

__version__ = "1.2.0"


def analyze_collection(
    target_path: Path,
    *,
    recursive: bool = True,
    sample_size: int | None = None,
) -> tuple[ScanSummary, list[ImageMetadata]]:
    """Recursively scan an image collection and return metadata and summary statistics."""
    summary, images = scan_directory(target_path, recursive=recursive)
    if sample_size and len(images) > sample_size:
        images = select_sample(images, sample_size)
    return summary, images


def compare_strategies(
    images: Sequence[ImageMetadata],
    strategies: Sequence[CompressionStrategy],
    *,
    threads: int = 4,
    cache: AnalysisCache | None = None,
) -> list[ComparisonRow]:
    """Benchmark multiple compression strategies against an image collection."""
    engine = CompressionEngine(cache=cache)
    rows: list[ComparisonRow] = []

    for strat in strategies:
        res = engine.compress_batch(images, strat, write_mode=False, threads=threads)
        q_disp = (
            f"SSIM>={strat.perceptual_target:.3f}"
            if strat.mode == "perceptual"
            else (f"q={strat.quality}" if strat.mode == "lossy" else "lossless")
        )
        rows.append(
            ComparisonRow(
                strategy_name=strat.name,
                output_format=strat.format,
                mode=strat.mode,
                quality_display=q_disp,
                compressed_bytes=res.compressed_bytes,
                saved_bytes=res.saved_bytes,
                savings_percent=res.savings_percent,
                average_ssim=res.average_ssim,
                throughput_images_per_s=res.throughput_images_per_s,
                measured_images=res.processed_images,
                failed_count=res.failed_count,
                skipped_count=res.skipped_count,
                cache_hits=sum(item.cache_hit for item in res.results),
            )
        )
    return rows


def compress_collection(
    images: Sequence[ImageMetadata],
    strategy: CompressionStrategy,
    *,
    write_mode: bool = False,
    threads: int = 4,
    cache: AnalysisCache | None = None,
) -> BatchResult:
    """Execute analysis or compression across an image collection using the chosen strategy."""
    engine = CompressionEngine(cache=cache)
    return engine.compress_batch(images, strategy, write_mode=write_mode, threads=threads)


__all__ = [
    "__version__",
    "analyze_collection",
    "compare_strategies",
    "compress_collection",
    "inspect_image_file",
    "scan_directory",
    "select_sample",
    "AnalysisCache",
    "CompressionEngine",
    "CompressionStrategy",
    "ImageMetadata",
    "ImageResult",
    "BatchResult",
    "ComparisonRow",
    "ScanSummary",
    "GallerySample",
    "gallery_sample",
    "confirmation_sample",
    "recommend_comparison_strategies",
    "discover_available_codecs",
]
