#!/usr/bin/env python3
"""
Core compression engine, strategy routing, and atomic file application.
"""

from __future__ import annotations

import io
import os
import time
import threading
from dataclasses import replace
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from .cache import AnalysisCache
from .codecs import (
    BaseCodec,
    discover_available_codecs,
)
from .models import (
    BatchResult,
    CompressionStrategy,
    ImageMetadata,
    ImageResult,
)
from .transactions import JOURNAL_FILENAME, digest, directory_lock, publish, recover

# Conservative allowance for source/decoded copies, verification and metrics.
MEMORY_BUDGET_BYTES = 512 * 1024 * 1024
ESTIMATED_BYTES_PER_PIXEL = 48


def resolve_output_format(meta: ImageMetadata, strategy: CompressionStrategy) -> str:
    """Determine the target format for an image based on strategy and dimensions."""
    req_fmt = strategy.format.lower()
    orig_fmt = meta.format.lower()

    if req_fmt == "keep":
        return orig_fmt

    if req_fmt == "auto":
        # Tall manhwa strips cannot be encoded as WebP (16383px limit)
        if meta.is_tall_for_webp:
            return "jpeg" if orig_fmt not in ("png",) else orig_fmt
        # Default auto format for manga/manhwa is WebP
        return "webp"

    if req_fmt == "webp" and meta.is_tall_for_webp:
        raise ValueError("Explicit WebP target exceeds its dimension limit; choose auto or another format")

    return req_fmt


def validate_image_file(path: Path, expected_size: tuple[int, int] | None = None) -> bool:
    """Ensure written image file is non-empty and decodes completely without corruption."""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with Image.open(path) as im:
            im.load()  # Full pixel decode check to catch truncation or bad frames
            if expected_size is not None and im.size != expected_size:
                return False
        return True
    except Exception:
        return False


def recover_interrupted_transactions(directory: Path, *, apply: bool = False) -> int:
    """
    Check for an uncommitted .compress_journal.json in directory and recover cleanly.
    Returns the count of resolved transaction items.
    """
    return recover(directory, apply=apply)


class CompressionEngine:
    """Engine managing codec dispatch, benchmark caching, and atomic application."""

    def __init__(self, cache: AnalysisCache | None = None) -> None:
        self.codecs = discover_available_codecs()
        self.cache = cache or AnalysisCache()
        self._publication_lock = threading.Lock()

    def _select_codec(self, target_format: str, strategy: CompressionStrategy) -> BaseCodec:
        fmt = target_format.upper()
        if strategy.encoder != "auto":
            codec = self.codecs.get(strategy.encoder)
            if codec is None or not codec.is_available() or fmt not in codec.supported_formats:
                raise ValueError(f"Encoder {strategy.encoder} is unavailable or does not support {target_format}")
            return codec
        if fmt in ("WEBP",):
            return self.codecs["pillow-webp"]
        elif fmt in ("JPEG", "JPG"):
            if strategy.mode == "lossless" and "cli-jpegtran" in self.codecs:
                return self.codecs["cli-jpegtran"]
            return self.codecs["pillow-jpeg"]
        elif fmt in ("AVIF",) and "pillow-avif" in self.codecs:
            return self.codecs["pillow-avif"]
        elif fmt == "PNG":
            return self.codecs["pillow-png"]
        raise ValueError(f"No verified encoder for target format {target_format}")

    def _encode_verified(
        self, im: Image.Image, target_fmt: str, strategy: CompressionStrategy
    ) -> tuple[bytes, float | None, str]:
        codec = self._select_codec(target_fmt, strategy)
        encoded, ssim = codec.encode(im, target_fmt, strategy)
        if strategy.mode == "perceptual" and (ssim is None or ssim < strategy.perceptual_target):
            raise ValueError("No encoded candidate meets the requested perceptual threshold")
        with Image.open(io.BytesIO(encoded)) as verified:
            verified.load()
            if verified.format.lower() != ("jpeg" if target_fmt == "jpg" else target_fmt):
                raise ValueError("Encoder returned a different format from the requested target")
            if verified.size != im.size:
                raise ValueError("Encoder changed image dimensions")
            if strategy.mode == "lossless" and verified.convert("RGBA").tobytes() != im.convert("RGBA").tobytes():
                raise ValueError("Lossless encoder changed decoded samples")
            if "A" in im.getbands() or "transparency" in im.info:
                if verified.convert("RGBA").getchannel("A").tobytes() != im.convert("RGBA").getchannel("A").tobytes():
                    raise ValueError("Encoder did not preserve image transparency")
            for key in ("icc_profile", "exif", "xmp"):
                actual = verified.info.get(key)
                if key == "xmp" and verified.format == "PNG":
                    actual = verified.info.get("XML:com.adobe.xmp")
                    if isinstance(actual, str) and isinstance(im.info.get(key), bytes):
                        actual = actual.encode("utf-8")
                if im.info.get(key) and actual != im.info[key]:
                    raise ValueError(f"Encoder did not preserve {key} metadata")
        return encoded, ssim, codec.name

    def _encode_auto(
        self, im: Image.Image, meta: ImageMetadata, strategy: CompressionStrategy
    ) -> tuple[str, bytes, float | None, str]:
        formats = ["png", "jpeg"] if meta.is_tall_for_webp else ["webp", "png", "jpeg"]
        if strategy.encoder != "auto":
            codec = self.codecs.get(strategy.encoder)
            if codec is None:
                raise ValueError(f"Requested encoder is unavailable: {strategy.encoder}")
            formats = [fmt for fmt in formats if fmt.upper() in codec.supported_formats]
            if strategy.encoder == "pillow-avif" and strategy.mode == "lossy":
                formats = ["avif"]
        best = None
        failures = []
        for fmt in formats:
            # PNG is always pixel-lossless, including in mixed lossy/perceptual searches.
            candidate = replace(strategy, format=fmt, mode="lossless" if fmt == "png" else strategy.mode)
            try:
                encoded, score, encoder = self._encode_verified(im, fmt, candidate)
            except (ValueError, RuntimeError, OSError) as exc:
                failures.append(f"{fmt}: {exc}")
                continue
            if best is None or len(encoded) < len(best[1]):
                best = (fmt, encoded, score, encoder)
        if best is None:
            raise ValueError("No valid auto candidate: " + "; ".join(failures))
        return best

    def compress_image(
        self,
        meta: ImageMetadata,
        strategy: CompressionStrategy,
        *,
        write_mode: bool = False,
    ) -> ImageResult:
        """Analyze or compress a single image."""
        start_time = time.monotonic()
        path = meta.path
        orig_bytes = meta.size_bytes

        # Guard: In write mode, refuse lossy operations without explicit opt-in
        if write_mode and strategy.mode in ("lossy", "perceptual") and not strategy.allow_lossy:
            return ImageResult(
                input_path=path,
                output_path=path,
                original_bytes=orig_bytes,
                compressed_bytes=orig_bytes,
                original_format=meta.format,
                output_format=meta.format,
                ssim=1.0,
                elapsed_s=0.0,
                applied=False,
                skipped=True,
                skip_reason="lossy compression in write mode requires explicit permission (--allow-lossy)",
            )

        # Check cache if in read-only / analysis mode
        if not write_mode:
            cached = self.cache.get(path, strategy)
            if cached is not None:
                return cached

        target_fmt = meta.format.lower()
        ext_map = {"jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp", "avif": ".avif", "png": ".png"}
        new_ext = ext_map.get(target_fmt.lower(), f".{target_fmt.lower()}")
        output_path = path.with_suffix(new_ext)

        try:
            if not 1 <= strategy.quality <= 100 or not 0.80 <= strategy.perceptual_target <= 1.0:
                raise ValueError("Quality must be 1..100 and perceptual target 0.80..1.00")
            if strategy.mode not in ("lossless", "lossy", "perceptual") or not 0 <= strategy.method <= 6:
                raise ValueError("Unsupported compression mode or method")
            target_fmt = resolve_output_format(meta, strategy)
            new_ext = ext_map.get(target_fmt.lower(), f".{target_fmt.lower()}")
            output_path = path if strategy.format == "keep" else path.with_suffix(new_ext)
            if write_mode and strategy.format != "auto" and output_path != path and output_path.exists():
                raise FileExistsError(f"Compression target already exists: {output_path}")
            if path.is_symlink():
                raise RuntimeError("Refusing linked input image")
            stat = path.stat()
            if meta.mtime_ns and (stat.st_mtime_ns != meta.mtime_ns or stat.st_size != meta.size_bytes):
                raise RuntimeError("Source changed since scan; rescan before compression")
            source_digest = digest(path) if write_mode else ""
            with Image.open(path) as im:
                if im.width * im.height > 40_000_000:
                    raise ValueError("Image exceeds enforced 40-million-pixel decode limit")
                if im.width * im.height * ESTIMATED_BYTES_PER_PIXEL > MEMORY_BUDGET_BYTES:
                    raise ValueError("Image exceeds conservative 512MiB working-memory budget")
                if getattr(im, "n_frames", 1) != 1 or im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
                    raise ValueError("Unsupported animation or pixel/color mode; source preserved")
                im.load()
                if strategy.format == "auto":
                    target_fmt, encoded_bytes, ssim, encoder = self._encode_auto(im, meta, strategy)
                    output_path = path if target_fmt == meta.format.lower() else path.with_suffix(ext_map[target_fmt])
                else:
                    encoded_bytes, ssim, encoder = self._encode_verified(im, target_fmt, strategy)

            after = path.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ):
                raise RuntimeError("Source changed while evaluating compression; result discarded")
            compressed_bytes = len(encoded_bytes)
            elapsed = time.monotonic() - start_time

            # Size Guard: Refuse replacement if larger than original unless explicitly permitted
            if compressed_bytes >= orig_bytes and not strategy.allow_larger:
                res = ImageResult(
                    input_path=path,
                    output_path=path,
                    original_bytes=orig_bytes,
                    compressed_bytes=orig_bytes,
                    original_format=meta.format,
                    output_format=meta.format,
                    ssim=1.0,
                    elapsed_s=elapsed,
                    applied=False,
                    skipped=True,
                    skip_reason=f"compressed output ({compressed_bytes} B) is not smaller than original ({orig_bytes} B)",
                )
                self.cache.set(path, strategy, res)
                return res

            # Apply Changes Safely
            if write_mode:
                with self._publication_lock, directory_lock(path.parent):
                    publish(
                        path,
                        output_path,
                        encoded_bytes,
                        source_digest,
                        lambda p: validate_image_file(p, (meta.width, meta.height)),
                    )
                return ImageResult(
                    input_path=path,
                    output_path=output_path,
                    original_bytes=orig_bytes,
                    compressed_bytes=compressed_bytes,
                    original_format=meta.format,
                    output_format=target_fmt.upper(),
                    ssim=ssim,
                    elapsed_s=elapsed,
                    applied=True,
                    skipped=False,
                    encoder=encoder,
                )

            res = ImageResult(
                input_path=path,
                output_path=output_path,
                original_bytes=orig_bytes,
                compressed_bytes=compressed_bytes,
                original_format=meta.format,
                output_format=target_fmt.upper(),
                ssim=ssim,
                elapsed_s=elapsed,
                applied=False,
                skipped=False,
                encoder=encoder,
            )
            self.cache.set(path, strategy, res)
            return res

        except Exception as exc:
            return ImageResult(
                input_path=path,
                output_path=path,
                original_bytes=orig_bytes,
                compressed_bytes=orig_bytes,
                original_format=meta.format,
                output_format=meta.format,
                ssim=None,
                elapsed_s=time.monotonic() - start_time,
                applied=False,
                skipped=True,
                error=str(exc),
            )

    def compress_batch(
        self,
        images: Sequence[ImageMetadata],
        strategy: CompressionStrategy,
        *,
        write_mode: bool = False,
        threads: int = 4,
        progress_callback: Callable[[int, int, ImageResult], None] | None = None,
    ) -> BatchResult:
        """Process a collection of images using thread concurrency."""
        if threads < 1:
            raise ValueError("Thread count must be positive")
        total = len(images)
        if total == 0:
            return BatchResult(
                strategy_name=strategy.name,
                total_images=0,
                processed_images=0,
                original_bytes=0,
                compressed_bytes=0,
                saved_bytes=0,
                savings_percent=0.0,
                average_ssim=None,
                elapsed_seconds=0.0,
                throughput_images_per_s=0.0,
                throughput_bytes_per_s=0.0,
                applied_count=0,
                skipped_count=0,
                failed_count=0,
                dry_run=not write_mode,
            )

        start_time = time.monotonic()
        results: list[ImageResult] = []
        orig_bytes_total = 0
        comp_bytes_total = 0
        applied_cnt = 0
        skipped_cnt = 0
        failed_cnt = 0
        ssim_scores: list[float] = []

        # Analysis is strictly read-only, including when a journal exists.
        if write_mode:
            for directory in {img.path.parent for img in images}:
                if (directory / JOURNAL_FILENAME).exists():
                    raise RuntimeError(f"Pending compression transaction requires explicit recovery: {directory}")

        largest_working_set = max(img.width * img.height * ESTIMATED_BYTES_PER_PIXEL for img in images)
        memory_workers = max(1, MEMORY_BUDGET_BYTES // max(1, largest_working_set))
        max_workers = max(1, min(threads, os.cpu_count() or 4, memory_workers))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            remaining_images = iter(images)

            def submit_next() -> None:
                img = next(remaining_images, None)
                if img is not None:
                    futures.add(pool.submit(self.compress_image, img, strategy, write_mode=write_mode))

            futures = set()
            for _ in range(max_workers):
                submit_next()
            while futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                fut = next(iter(completed))
                futures.remove(fut)
                res = fut.result()
                results.append(res)
                orig_bytes_total += res.original_bytes
                comp_bytes_total += res.compressed_bytes

                if res.error:
                    failed_cnt += 1
                elif res.skipped:
                    skipped_cnt += 1
                elif res.applied:
                    applied_cnt += 1

                if res.ssim is not None:
                    ssim_scores.append(res.ssim)

                if progress_callback:
                    progress_callback(len(results), total, res)
                submit_next()

        elapsed = time.monotonic() - start_time
        saved = max(0, orig_bytes_total - comp_bytes_total)
        savings_pct = (saved / orig_bytes_total * 100.0) if orig_bytes_total > 0 else 0.0
        avg_ssim = (sum(ssim_scores) / len(ssim_scores)) if ssim_scores else None
        rate_img = (total / elapsed) if elapsed > 0 else 0.0
        rate_bytes = (orig_bytes_total / elapsed) if elapsed > 0 else 0.0

        return BatchResult(
            strategy_name=strategy.name,
            total_images=total,
            processed_images=len(results),
            original_bytes=orig_bytes_total,
            compressed_bytes=comp_bytes_total,
            saved_bytes=saved,
            savings_percent=savings_pct,
            average_ssim=avg_ssim,
            elapsed_seconds=elapsed,
            throughput_images_per_s=rate_img,
            throughput_bytes_per_s=rate_bytes,
            applied_count=applied_cnt,
            skipped_count=skipped_cnt,
            failed_count=failed_cnt,
            dry_run=not write_mode,
            results=results,
        )
