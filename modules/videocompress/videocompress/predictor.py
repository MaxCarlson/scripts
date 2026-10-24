"""
Zero-encode metadata-based feasibility screening and container arithmetic.
Follows IMPLEMENTATION_PLAN.md §5, §6 and MEDIA_SAFETY_CONTRACT.md §1.

This module is strictly non-destructive and contains pure mathematical logic.
It NEVER invokes FFmpeg, executes subprocesses, or modifies media files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence

from .contracts import Prediction, VideoAsset, VideoRecipe, VideoStream

# Standard video quality bitrate floors (bps) by resolution tier for acceptable fidelity.
# Bitrate required to reach minimum acceptable quality without severe blockiness/artifacts.
QUALITY_FLOOR_AV1_BPS = {
    "4k": 2_200_000,    # >= 3840x2160
    "1440p": 1_400_000, # >= 2560x1440
    "1080p": 750_000,   # >= 1920x1080
    "720p": 400_000,    # >= 1280x720
    "sd": 200_000,      # < 720p
}

# Codec efficiency multipliers relative to AV1 quality floor:
CODEC_FLOOR_MULTIPLIERS = {
    "av1": 1.0,
    "hevc": 1.25,
    "h264": 1.85,
}

# Empirical codec transition priors: (p10, p50, p90) output-to-input video bitrate ratios.
# Lower ratio = greater savings. p10 = optimistic savings, p90 = conservative/pessimistic savings.
CODEC_PRIORS: dict[tuple[str, str], tuple[float, float, float]] = {
    ("h264", "av1"): (0.45, 0.60, 0.75),
    ("h264", "hevc"): (0.55, 0.70, 0.85),
    ("h264", "h264"): (0.85, 0.98, 1.10),
    ("hevc", "av1"): (0.65, 0.78, 0.90),
    ("hevc", "hevc"): (0.85, 0.98, 1.10),
    ("av1", "av1"): (0.90, 1.02, 1.15),  # Re-compressing AV1 usually yields negative/trivial savings
    ("vp9", "av1"): (0.65, 0.80, 0.95),
}

FALLBACK_PRIOR = (0.55, 0.75, 1.00)


@dataclass(frozen=True, slots=True)
class StreamPayloadBreakdown:
    """Exact byte accounting for non-video elementary streams and container overhead."""

    audio_bytes: int
    subtitle_bytes: int
    attachment_bytes: int
    mux_overhead_bytes: int
    total_nonvideo_bytes: int
    audio_provenance: str  # exact_probed, estimated_fallback, omitted
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FeasibilityAssessment:
    """Detailed feasibility analysis for an asset under a target recipe and savings policy."""

    source_id: str
    recipe_id: str
    source_bytes: int
    duration_seconds: float
    video_bitrate_bps: int | None
    bitrate_provenance: str  # ffprobe_stream, container_derived_approximation, missing
    breakdown: StreamPayloadBreakdown

    # Allowable budget under required savings
    max_output_container_bytes: int
    max_video_elementary_bytes: int
    max_video_bitrate_bps: int | None
    quality_floor_bps: int

    # Predicted range (p10 = optimistic savings/lowest size, p50 = expected, p90 = conservative)
    p10_output_bytes: int
    p50_output_bytes: int
    p90_output_bytes: int
    p10_savings_bytes: int
    p50_savings_bytes: int
    p90_savings_bytes: int
    p10_savings_pct: float
    p50_savings_pct: float
    p90_savings_pct: float

    decision: str  # eligible_promising, eligible_uncertain, eligible_unlikely, infeasible, abstained
    confidence: str  # high, medium, low, abstain
    is_hard_infeasible: bool
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    calibration_status: str = "uncalibrated_metadata_prior"

    @property
    def prediction(self) -> Prediction:
        """Convert to standard domain Prediction contract."""
        interval = (self.p10_output_bytes, self.p90_output_bytes)
        unknowns_list = []
        if self.bitrate_provenance == "container_derived_approximation":
            unknowns_list.append("video_bitrate_approximated_from_container")
        elif self.bitrate_provenance == "missing":
            unknowns_list.append("video_bitrate_missing")
        if self.breakdown.audio_provenance == "estimated_fallback":
            unknowns_list.append("audio_bitrate_estimated")

        return Prediction(
            source_id=self.source_id,
            recipe_id=self.recipe_id,
            tier="metadata",
            source_container_bytes=self.source_bytes,
            predicted_video_bytes=max(0, self.p50_output_bytes - self.breakdown.total_nonvideo_bytes),
            predicted_nonvideo_bytes=self.breakdown.audio_bytes + self.breakdown.subtitle_bytes + self.breakdown.attachment_bytes,
            predicted_mux_overhead_bytes=self.breakdown.mux_overhead_bytes,
            predicted_output_container_bytes=self.p50_output_bytes,
            predicted_gross_saved_bytes=self.p50_savings_bytes,
            decision=self.decision,
            prediction_interval=interval,
            interval_status=self.calibration_status,
            unknowns=tuple(unknowns_list),
            errors=self.rejection_reasons if self.decision == "infeasible" else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "recipe_id": self.recipe_id,
            "source_bytes": self.source_bytes,
            "duration_seconds": self.duration_seconds,
            "video_bitrate_bps": self.video_bitrate_bps,
            "bitrate_provenance": self.bitrate_provenance,
            "breakdown": asdict(self.breakdown),
            "max_output_container_bytes": self.max_output_container_bytes,
            "max_video_elementary_bytes": self.max_video_elementary_bytes,
            "max_video_bitrate_bps": self.max_video_bitrate_bps,
            "quality_floor_bps": self.quality_floor_bps,
            "predictions": {
                "p10_output_bytes": self.p10_output_bytes,
                "p50_output_bytes": self.p50_output_bytes,
                "p90_output_bytes": self.p90_output_bytes,
                "p10_savings_bytes": self.p10_savings_bytes,
                "p50_savings_bytes": self.p50_savings_bytes,
                "p90_savings_bytes": self.p90_savings_bytes,
                "p10_savings_pct": round(self.p10_savings_pct, 2),
                "p50_savings_pct": round(self.p50_savings_pct, 2),
                "p90_savings_pct": round(self.p90_savings_pct, 2),
            },
            "decision": self.decision,
            "confidence": self.confidence,
            "is_hard_infeasible": self.is_hard_infeasible,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
            "calibration_status": self.calibration_status,
        }


def compute_nonvideo_payload(
    asset: VideoAsset,
    recipe: VideoRecipe,
) -> StreamPayloadBreakdown:
    """
    Perform exact size decomposition of non-video streams and container overhead.
    Preserves all compatible audio, subtitle, and font attachments by default.
    """
    duration = max(0.0, asset.duration_seconds)
    audio_bytes = 0
    audio_prov = "exact_probed"
    warnings = []

    # 1. Audio stream payload
    if recipe.audio_policy == "copy":
        for s in asset.streams:
            if s.stream_type == "audio":
                if s.bit_rate_bps and s.bit_rate_bps > 0 and duration > 0:
                    audio_bytes += int(s.bit_rate_bps * duration / 8.0)
                else:
                    # Estimate based on audio codec and channel layout
                    audio_prov = "estimated_fallback"
                    ch = s.channels or 2
                    c_name = (s.codec_name or "").lower()
                    if "aac" in c_name:
                        rate_bps = 96_000 * ch
                    elif "ac3" in c_name or "eac3" in c_name:
                        rate_bps = 224_000 if ch <= 2 else 448_000
                    elif "dts" in c_name:
                        rate_bps = 768_000 if ch <= 6 else 1_536_000
                    elif "flac" in c_name:
                        rate_bps = 400_000 * ch
                    elif "opus" in c_name:
                        rate_bps = 64_000 * ch
                    else:
                        rate_bps = 96_000 * ch
                    audio_bytes += int(rate_bps * duration / 8.0) if duration > 0 else 0
                    warnings.append(f"Audio stream #{s.stream_index} bitrate missing; estimated at {rate_bps // 1000} kbps.")
    elif recipe.audio_policy == "omit":
        audio_prov = "omitted"
        audio_bytes = 0

    # 2. Subtitle stream payload
    subtitle_bytes = 0
    if recipe.subtitle_policy == "copy":
        for s in asset.streams:
            if s.stream_type == "subtitle":
                c_name = (s.codec_name or "").lower()
                if "pgs" in c_name or "dvd" in c_name:
                    # Bitmap subtitles: ~15 MB per hour (~4200 B/s)
                    subtitle_bytes += int(4_200 * duration)
                else:
                    # Text subtitles (SRT, ASS, VTT): ~50 KB per hour (~15 B/s)
                    subtitle_bytes += int(15 * duration)

    # 3. Attachment stream payload (fonts, poster art)
    attachment_bytes = 0
    if recipe.attachment_policy == "copy":
        for s in asset.streams:
            if s.stream_type == "attachment":
                # Average font attachment in Matroska ~150 KB
                attachment_bytes += 150_000

    # 4. Container muxing overhead
    # Matroska / MP4 muxing overhead:
    # Baseline index, cues, chapter markers, moov atom, cluster headers:
    # 0.8% of payload + minimum 128 KB for seekhead/cues
    raw_payload = audio_bytes + subtitle_bytes + attachment_bytes
    mux_overhead = max(131_072, int(raw_payload * 0.008) + int(asset.file_bytes * 0.005))

    total_nonvideo = audio_bytes + subtitle_bytes + attachment_bytes + mux_overhead

    return StreamPayloadBreakdown(
        audio_bytes=audio_bytes,
        subtitle_bytes=subtitle_bytes,
        attachment_bytes=attachment_bytes,
        mux_overhead_bytes=mux_overhead,
        total_nonvideo_bytes=total_nonvideo,
        audio_provenance=audio_prov,
        warnings=tuple(warnings),
    )


def determine_quality_floor(stream: VideoStream, target_codec: str) -> int:
    """Calculate minimum viable video bitrate (bps) for acceptable visual quality."""
    width = stream.width or 1920
    height = stream.height or 1080
    dim_max = max(width, height)

    if dim_max >= 3800:
        base_floor = QUALITY_FLOOR_AV1_BPS["4k"]
    elif dim_max >= 2500:
        base_floor = QUALITY_FLOOR_AV1_BPS["1440p"]
    elif dim_max >= 1800:
        base_floor = QUALITY_FLOOR_AV1_BPS["1080p"]
    elif dim_max >= 1200:
        base_floor = QUALITY_FLOOR_AV1_BPS["720p"]
    else:
        base_floor = QUALITY_FLOOR_AV1_BPS["sd"]

    multiplier = CODEC_FLOOR_MULTIPLIERS.get(target_codec.lower(), 1.0)
    return int(base_floor * multiplier)


def evaluate_feasibility(
    asset: VideoAsset,
    recipe: VideoRecipe,
    min_savings_pct: float | None = None,
    min_savings_bytes: int | None = None,
    savings_policy: str = "both",  # "both" (% AND bytes) or "either" (% OR bytes)
    quality_floor_override_bps: int | None = None,
) -> FeasibilityAssessment:
    """
    Perform pure zero-encode metadata feasibility screening on a video asset.

    Evaluates:
    1. Container byte decomposition (video vs audio vs subtitles vs mux overhead).
    2. Missing video bitrate handling with explicit provenance labeling.
    3. Hard budget and quality impossibility constraints.
    4. Codec efficiency prior predictions with explicit [p10, p50, p90] uncertainty intervals.
    5. Rejection reasons and honest calibration caveats.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    duration = max(0.0, asset.duration_seconds)
    source_bytes = asset.file_bytes

    # 1. Inspect primary video stream
    pv = asset.primary_video_stream
    if not pv:
        return _make_ineligible_no_video(asset, recipe)

    # 2. Decompose non-video streams and overhead
    breakdown = compute_nonvideo_payload(asset, recipe)
    warnings.extend(breakdown.warnings)

    # 3. Determine video bitrate and provenance
    video_bitrate_bps = pv.bit_rate_bps
    if video_bitrate_bps and video_bitrate_bps > 0:
        bitrate_provenance = pv.bitrate_provenance or "ffprobe_stream"
    else:
        # Container fallback approximation:
        # Never substitute container bitrate without explicitly labeling it!
        if duration > 0 and source_bytes > breakdown.total_nonvideo_bytes:
            video_bitrate_bps = int((source_bytes - breakdown.total_nonvideo_bytes) * 8.0 / duration)
            bitrate_provenance = "container_derived_approximation"
            warnings.append(
                "Video stream bitrate was missing from stream headers; "
                f"approximated as {video_bitrate_bps // 1000} kbps from container size minus non-video streams."
            )
        else:
            video_bitrate_bps = None
            bitrate_provenance = "missing"
            reasons.append("Video stream bitrate is missing and cannot be approximated (missing duration or invalid size).")

    # 4. Target savings budget arithmetic
    pct_floor = min_savings_pct if min_savings_pct is not None else 0.0
    bytes_floor = min_savings_bytes if min_savings_bytes is not None else 0

    max_by_pct = int(source_bytes * (1.0 - (pct_floor / 100.0))) if min_savings_pct is not None else source_bytes
    max_by_bytes = max(0, source_bytes - bytes_floor) if min_savings_bytes is not None else source_bytes

    if min_savings_pct is not None and min_savings_bytes is not None:
        if savings_policy == "both":
            max_output_bytes = min(max_by_pct, max_by_bytes)
        else:
            max_output_bytes = max(max_by_pct, max_by_bytes)
    elif min_savings_pct is not None:
        max_output_bytes = max_by_pct
    elif min_savings_bytes is not None:
        max_output_bytes = max_by_bytes
    else:
        # No minimum savings specified: any non-negative savings
        max_output_bytes = source_bytes

    max_video_bytes = max_output_bytes - breakdown.total_nonvideo_bytes
    max_video_bitrate_bps = int(max_video_bytes * 8.0 / duration) if duration > 0 else None

    # Quality floor calculation
    quality_floor_bps = quality_floor_override_bps or determine_quality_floor(pv, recipe.codec)

    # 5. Check hard impossibility
    is_hard_infeasible = False
    if max_video_bytes <= 0:
        is_hard_infeasible = True
        reasons.append(
            f"Non-video payload ({breakdown.total_nonvideo_bytes:,} bytes) and mux overhead exceed "
            f"maximum allowable output budget ({max_output_bytes:,} bytes) for required savings."
        )

    if not is_hard_infeasible and max_video_bitrate_bps is not None and max_video_bitrate_bps < quality_floor_bps:
        is_hard_infeasible = True
        reasons.append(
            f"Maximum video bitrate to achieve savings ({max_video_bitrate_bps // 1000} kbps) "
            f"is below minimum viable quality floor ({quality_floor_bps // 1000} kbps) for "
            f"{recipe.codec.upper()} {pv.width or 0}x{pv.height or 0}."
        )

    # 6. Prior-based prediction interval calculation
    if video_bitrate_bps is None or duration <= 0:
        # Abstain: cannot make heuristic prediction without valid bitrate and duration
        return FeasibilityAssessment(
            source_id=asset.source_id,
            recipe_id=recipe.recipe_id,
            source_bytes=source_bytes,
            duration_seconds=duration,
            video_bitrate_bps=None,
            bitrate_provenance=bitrate_provenance,
            breakdown=breakdown,
            max_output_container_bytes=max_output_bytes,
            max_video_elementary_bytes=max_video_bytes,
            max_video_bitrate_bps=max_video_bitrate_bps,
            quality_floor_bps=quality_floor_bps,
            p10_output_bytes=source_bytes,
            p50_output_bytes=source_bytes,
            p90_output_bytes=source_bytes,
            p10_savings_bytes=0,
            p50_savings_bytes=0,
            p90_savings_bytes=0,
            p10_savings_pct=0.0,
            p50_savings_pct=0.0,
            p90_savings_pct=0.0,
            decision="abstained",
            confidence="abstain",
            is_hard_infeasible=is_hard_infeasible,
            rejection_reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    # Calculate plausible prior ratios
    src_codec = (pv.codec_name or "").lower()
    tgt_codec = (recipe.codec or "").lower()

    prior_key = (src_codec, tgt_codec)
    p10_r, p50_r, p90_r = CODEC_PRIORS.get(prior_key, FALLBACK_PRIOR)

    # Adjustments:
    # A. HDR / 10-bit preservation
    if pv.is_hdr or (pv.bit_depth and pv.bit_depth >= 10):
        p10_r += 0.05
        p50_r += 0.05
        p90_r += 0.05
        warnings.append("HDR10/10-bit content detected; prediction interval widened to account for color precision preservation.")

    # B. Already-low bits-per-pixel-per-frame (bpppf)
    width = pv.width or 1920
    height = pv.height or 1080
    fps = (pv.fps_num / pv.fps_den) if pv.fps_num and pv.fps_den else 24.0
    pixels_per_sec = width * height * fps

    if pixels_per_sec > 0:
        bpppf = video_bitrate_bps / pixels_per_sec
        if bpppf < 0.05:
            # Source is already heavily compressed
            p10_r += 0.15
            p50_r += 0.15
            p90_r += 0.15
            warnings.append(
                f"Source has low bits-per-pixel-per-frame ({bpppf:.4f}); "
                "further compression carries high visual artifact risk."
            )

    # C. CQ value delta adjustment from standard baseline
    if recipe.rate_control_mode == "cq":
        # Standard baseline CQ is 30 for AV1, 28 for HEVC, 24 for H.264
        base_cq = 30.0 if tgt_codec == "av1" else (28.0 if tgt_codec == "hevc" else 24.0)
        cq_delta = recipe.rate_control_value - base_cq
        # Each CQ step shifts bitrate by ~3.5%
        cq_factor = 1.0 - (cq_delta * 0.035)
        p10_r *= cq_factor
        p50_r *= cq_factor
        p90_r *= cq_factor

    # Compute predicted video elementary bytes
    source_video_bytes = int(video_bitrate_bps * duration / 8.0)
    p10_video_bytes = max(0, int(source_video_bytes * p10_r))
    p50_video_bytes = max(0, int(source_video_bytes * p50_r))
    p90_video_bytes = max(0, int(source_video_bytes * p90_r))

    # Output container bytes = video + nonvideo + overhead
    p10_out = p10_video_bytes + breakdown.total_nonvideo_bytes
    p50_out = p50_video_bytes + breakdown.total_nonvideo_bytes
    p90_out = p90_video_bytes + breakdown.total_nonvideo_bytes

    # Savings relative to source
    p10_sav_bytes = source_bytes - p90_out  # conservative savings = source - p90 out
    p50_sav_bytes = source_bytes - p50_out  # expected savings
    p90_sav_bytes = source_bytes - p10_out  # optimistic savings = source - p10 out

    p10_sav_pct = (p10_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0
    p50_sav_pct = (p50_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0
    p90_sav_pct = (p90_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0

    # 7. Decision categorization
    if is_hard_infeasible:
        decision = "infeasible"
        confidence = "high"
    else:
        # Check if optimistic savings meets the threshold
        opt_meets_pct = (min_savings_pct is None) or (p90_sav_pct >= min_savings_pct)
        opt_meets_bytes = (min_savings_bytes is None) or (p90_sav_bytes >= min_savings_bytes)
        opt_meets = (opt_meets_pct and opt_meets_bytes) if savings_policy == "both" else (opt_meets_pct or opt_meets_bytes)

        # Check if conservative savings meets the threshold
        cons_meets_pct = (min_savings_pct is None) or (p10_sav_pct >= min_savings_pct)
        cons_meets_bytes = (min_savings_bytes is None) or (p10_sav_bytes >= min_savings_bytes)
        cons_meets = (cons_meets_pct and cons_meets_bytes) if savings_policy == "both" else (cons_meets_pct or cons_meets_bytes)

        if not opt_meets:
            decision = "eligible_unlikely"
            confidence = "medium"
            reasons.append("Predicted savings under optimistic prior are below required savings threshold.")
        elif cons_meets:
            decision = "eligible_promising"
            confidence = "medium"
        else:
            decision = "eligible_uncertain"
            confidence = "low"
            reasons.append("Plausible savings interval straddles decision threshold; sample trial measurement required.")

    # Confidence rating
    if bitrate_provenance == "container_derived_approximation" and confidence != "abstain":
        confidence = "low"

    return FeasibilityAssessment(
        source_id=asset.source_id,
        recipe_id=recipe.recipe_id,
        source_bytes=source_bytes,
        duration_seconds=duration,
        video_bitrate_bps=video_bitrate_bps,
        bitrate_provenance=bitrate_provenance,
        breakdown=breakdown,
        max_output_container_bytes=max_output_bytes,
        max_video_elementary_bytes=max_video_bytes,
        max_video_bitrate_bps=max_video_bitrate_bps,
        quality_floor_bps=quality_floor_bps,
        p10_output_bytes=p10_out,
        p50_output_bytes=p50_out,
        p90_output_bytes=p90_out,
        p10_savings_bytes=p10_sav_bytes,
        p50_savings_bytes=p50_sav_bytes,
        p90_savings_bytes=p90_sav_bytes,
        p10_savings_pct=p10_sav_pct,
        p50_savings_pct=p50_sav_pct,
        p90_savings_pct=p90_sav_pct,
        decision=decision,
        confidence=confidence,
        is_hard_infeasible=is_hard_infeasible,
        rejection_reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def _make_ineligible_no_video(asset: VideoAsset, recipe: VideoRecipe) -> FeasibilityAssessment:
    breakdown = StreamPayloadBreakdown(
        audio_bytes=0,
        subtitle_bytes=0,
        attachment_bytes=0,
        mux_overhead_bytes=0,
        total_nonvideo_bytes=0,
        audio_provenance="omitted",
    )
    return FeasibilityAssessment(
        source_id=asset.source_id,
        recipe_id=recipe.recipe_id,
        source_bytes=asset.file_bytes,
        duration_seconds=asset.duration_seconds,
        video_bitrate_bps=None,
        bitrate_provenance="missing",
        breakdown=breakdown,
        max_output_container_bytes=asset.file_bytes,
        max_video_elementary_bytes=0,
        max_video_bitrate_bps=None,
        quality_floor_bps=0,
        p10_output_bytes=asset.file_bytes,
        p50_output_bytes=asset.file_bytes,
        p90_output_bytes=asset.file_bytes,
        p10_savings_bytes=0,
        p50_savings_bytes=0,
        p90_savings_bytes=0,
        p10_savings_pct=0.0,
        p50_savings_pct=0.0,
        p90_savings_pct=0.0,
        decision="infeasible",
        confidence="high",
        is_hard_infeasible=True,
        rejection_reasons=("No compatible video stream found in asset.",),
        warnings=(),
    )
