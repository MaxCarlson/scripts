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
# Heuristic screening thresholds to flag potato-quality distortion, NOT mathematical impossibilities.
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

# Heuristic codec transition scenario ratios: (optimistic, expected, conservative) output-to-input video bitrate ratios.
# Note: These represent exploratory scenario assumptions, NOT statistically calibrated empirical probability distributions.
# Lower ratio = greater savings.
SCENARIO_RATIOS: dict[tuple[str, str], tuple[float, float, float]] = {
    ("h264", "av1"): (0.45, 0.60, 0.80),
    ("h264", "hevc"): (0.55, 0.70, 0.88),
    ("h264", "h264"): (0.85, 0.98, 1.15),
    ("hevc", "av1"): (0.65, 0.78, 0.92),
    ("hevc", "hevc"): (0.85, 0.98, 1.15),
    ("av1", "av1"): (0.90, 1.05, 1.25),  # Re-compressing AV1 usually yields negative/trivial savings or file bloat
    ("vp9", "av1"): (0.65, 0.80, 0.95),
}

FALLBACK_SCENARIO = (0.55, 0.75, 1.05)


@dataclass(frozen=True, slots=True)
class StreamPayloadBreakdown:
    """Estimated byte accounting for non-video elementary streams and container overhead."""

    audio_bytes: int
    subtitle_bytes: int
    attachment_bytes: int
    mux_overhead_bytes: int
    total_nonvideo_bytes: int
    audio_provenance: str  # exact_probed, estimated_fallback, omitted
    subtitle_provenance: str = "estimated_heuristic"
    attachment_provenance: str = "estimated_heuristic"
    mux_provenance: str = "estimated_container_model"
    decomposition_tier: str = "estimated_stream_heuristics"
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SizeReconciliation:
    """Detailed reconciliation of container file bytes versus stream bitrates."""

    source_bytes: int
    duration_seconds: float
    probed_video_bitrate_bps: int | None
    implied_video_bytes: int | None
    reconciled_video_bytes: int
    estimated_audio_bytes: int
    estimated_subtitle_bytes: int
    estimated_attachment_bytes: int
    estimated_mux_overhead_bytes: int
    total_estimated_nonvideo_bytes: int
    unaccounted_container_bytes: int
    unaccounted_ratio: float
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
    reconciliation: SizeReconciliation

    # Allowable budget under required savings
    max_output_container_bytes: int
    max_video_elementary_bytes: int
    max_video_bitrate_bps: int | None
    quality_floor_bps: int

    # Predicted range (p10 = optimistic scenario / lower size, p50 = expected, p90 = conservative / upper size)
    p10_output_bytes: int
    p50_output_bytes: int
    p90_output_bytes: int
    p10_savings_bytes: int
    p50_savings_bytes: int
    p90_savings_bytes: int
    p10_savings_pct: float
    p50_savings_pct: float
    p90_savings_pct: float

    decision: str  # eligible_promising, eligible_uncertain, eligible_unlikely, quality_floor_violation, infeasible, abstained
    confidence: str  # high, medium, low, abstain
    is_hard_infeasible: bool
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    calibration_status: str = "uncalibrated_scenario_assumptions"

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
        if abs(self.reconciliation.unaccounted_container_bytes) > (0.02 * self.source_bytes):
            unknowns_list.append("container_bitrate_discrepancy_unaccounted_bytes")

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
            "reconciliation": asdict(self.reconciliation),
            "max_output_container_bytes": self.max_output_container_bytes,
            "max_video_elementary_bytes": self.max_video_elementary_bytes,
            "max_video_bitrate_bps": self.max_video_bitrate_bps,
            "quality_floor_bps": self.quality_floor_bps,
            "predictions": {
                "scenarios": {
                    "optimistic": {
                        "output_bytes": self.p10_output_bytes,
                        "savings_bytes": self.p10_savings_bytes,
                        "savings_pct": round(self.p10_savings_pct, 2),
                    },
                    "expected": {
                        "output_bytes": self.p50_output_bytes,
                        "savings_bytes": self.p50_savings_bytes,
                        "savings_pct": round(self.p50_savings_pct, 2),
                    },
                    "conservative": {
                        "output_bytes": self.p90_output_bytes,
                        "savings_bytes": self.p90_savings_bytes,
                        "savings_pct": round(self.p90_savings_pct, 2),
                    },
                },
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
    Perform estimated decomposition of non-video streams and container overhead.
    Uses heuristic models when exact stream packet data is not probed.
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
                    warnings.append(f"Audio stream #{s.stream_index} bitrate missing; estimated via heuristic at {rate_bps // 1000} kbps.")
    elif recipe.audio_policy == "omit":
        audio_prov = "omitted"
        audio_bytes = 0

    # 2. Subtitle stream payload (heuristic estimates)
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

    # 4. Container muxing overhead (heuristic model)
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
        subtitle_provenance="estimated_heuristic",
        attachment_provenance="estimated_heuristic",
        mux_provenance="estimated_container_model",
        decomposition_tier="estimated_stream_heuristics",
        warnings=tuple(warnings),
    )


def determine_quality_floor(stream: VideoStream, target_codec: str) -> int:
    """Calculate minimum recommended video bitrate (bps) for acceptable visual quality."""
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
    1. Container byte decomposition and size reconciliation.
    2. Missing video bitrate handling with explicit provenance labeling.
    3. Hard budget impossibility constraints (physical byte overflows) vs quality floor screening.
    4. Codec efficiency scenario predictions with consistent [p10, p50, p90] ordering and output+savings=source identities.
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
    raw_video_bitrate = pv.bit_rate_bps
    if raw_video_bitrate and raw_video_bitrate > 0:
        video_bitrate_bps = raw_video_bitrate
        bitrate_provenance = pv.bitrate_provenance or "ffprobe_stream"
        implied_video_bytes = int(video_bitrate_bps * duration / 8.0) if duration > 0 else None
    else:
        # Container fallback approximation:
        # Never substitute container bitrate without explicitly labeling it!
        implied_video_bytes = None
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

    # 4. Container size reconciliation:
    # Reconciles probed stream bitrate vs container file bytes
    reconciled_video_bytes = max(0, source_bytes - breakdown.total_nonvideo_bytes)
    if implied_video_bytes is not None:
        unaccounted_bytes = source_bytes - (implied_video_bytes + breakdown.total_nonvideo_bytes)
        unaccounted_ratio = (unaccounted_bytes / source_bytes) if source_bytes > 0 else 0.0
        if abs(unaccounted_ratio) > 0.02:
            warnings.append(
                f"Container size discrepancy: probed stream bitrate implies {implied_video_bytes:,} video bytes, "
                f"leaving {unaccounted_bytes:,} unaccounted container bytes ({unaccounted_ratio:.1%}). "
                "Scenario predictions are conditioned on reconciled video payload."
            )
    else:
        unaccounted_bytes = 0
        unaccounted_ratio = 0.0

    reconciliation = SizeReconciliation(
        source_bytes=source_bytes,
        duration_seconds=duration,
        probed_video_bitrate_bps=raw_video_bitrate,
        implied_video_bytes=implied_video_bytes,
        reconciled_video_bytes=reconciled_video_bytes,
        estimated_audio_bytes=breakdown.audio_bytes,
        estimated_subtitle_bytes=breakdown.subtitle_bytes,
        estimated_attachment_bytes=breakdown.attachment_bytes,
        estimated_mux_overhead_bytes=breakdown.mux_overhead_bytes,
        total_estimated_nonvideo_bytes=breakdown.total_nonvideo_bytes,
        unaccounted_container_bytes=unaccounted_bytes,
        unaccounted_ratio=round(unaccounted_ratio, 4),
        warnings=tuple(w for w in warnings if "discrepancy" in w),
    )

    # 5. Target savings budget arithmetic
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
        max_output_bytes = source_bytes

    max_video_bytes = max_output_bytes - breakdown.total_nonvideo_bytes
    max_video_bitrate_bps = int(max_video_bytes * 8.0 / duration) if duration > 0 else None

    # Quality floor calculation (heuristic screening threshold)
    quality_floor_bps = quality_floor_override_bps or determine_quality_floor(pv, recipe.codec)

    # 6. Check hard impossibility vs quality screening
    # True mathematical impossibility ONLY occurs when non-video bytes exceed allowable output budget
    is_hard_infeasible = False
    if max_video_bytes <= 0:
        is_hard_infeasible = True
        reasons.append(
            f"Non-video payload ({breakdown.total_nonvideo_bytes:,} bytes) and mux overhead exceed "
            f"maximum allowable output budget ({max_output_bytes:,} bytes) for required savings."
        )

    # Quality floor violation is a heuristic quality risk signal, NOT a physical impossibility
    quality_floor_violated = False
    if not is_hard_infeasible and max_video_bitrate_bps is not None and max_video_bitrate_bps < quality_floor_bps:
        quality_floor_violated = True
        reasons.append(
            f"Maximum video bitrate to achieve savings ({max_video_bitrate_bps // 1000} kbps) "
            f"is below recommended visual quality floor ({quality_floor_bps // 1000} kbps) for "
            f"{recipe.codec.upper()} {pv.width or 0}x{pv.height or 0}."
        )

    # 7. Scenario prediction calculation
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
            reconciliation=reconciliation,
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

    # Calculate scenario ratios: (optimistic, expected, conservative)
    src_codec = (pv.codec_name or "").lower()
    tgt_codec = (recipe.codec or "").lower()

    prior_key = (src_codec, tgt_codec)
    r_opt, r_exp, r_cons = SCENARIO_RATIOS.get(prior_key, FALLBACK_SCENARIO)

    # Adjustments:
    # A. HDR / 10-bit preservation
    if pv.is_hdr or (pv.bit_depth and pv.bit_depth >= 10):
        r_opt += 0.05
        r_exp += 0.05
        r_cons += 0.05
        warnings.append("HDR10/10-bit content detected; scenario range widened to protect high dynamic range precision.")

    # B. Already-low bits-per-pixel-per-frame (bpppf)
    width = pv.width or 1920
    height = pv.height or 1080
    fps = (pv.fps_num / pv.fps_den) if pv.fps_num and pv.fps_den else 24.0
    pixels_per_sec = width * height * fps

    if pixels_per_sec > 0:
        bpppf = video_bitrate_bps / pixels_per_sec
        if bpppf < 0.05:
            r_opt += 0.15
            r_exp += 0.15
            r_cons += 0.15
            warnings.append(
                f"Source has low bits-per-pixel-per-frame ({bpppf:.4f}); "
                "further compression carries high visual artifact risk."
            )

    # C. CQ value delta adjustment from standard baseline
    if recipe.rate_control_mode == "cq":
        base_cq = 30.0 if tgt_codec == "av1" else (28.0 if tgt_codec == "hevc" else 24.0)
        cq_delta = recipe.rate_control_value - base_cq
        cq_factor = 1.0 - (cq_delta * 0.035)
        r_opt *= cq_factor
        r_exp *= cq_factor
        r_cons *= cq_factor

    # Ensure monotonic ordering of scenario ratios: r_opt <= r_exp <= r_cons
    r_opt = max(0.10, r_opt)
    r_exp = max(r_opt, r_exp)
    r_cons = max(r_exp, r_cons)

    # Base predicted video bytes on reconciled video payload
    base_video_bytes = reconciled_video_bytes
    v_opt_bytes = max(0, int(base_video_bytes * r_opt))
    v_exp_bytes = max(0, int(base_video_bytes * r_exp))
    v_cons_bytes = max(0, int(base_video_bytes * r_cons))

    # Output container sizes for each scenario
    # p10 = optimistic (smallest output size), p50 = expected, p90 = conservative (largest output size)
    p10_out = v_opt_bytes + breakdown.total_nonvideo_bytes
    p50_out = v_exp_bytes + breakdown.total_nonvideo_bytes
    p90_out = v_cons_bytes + breakdown.total_nonvideo_bytes

    # Clamping: output size cannot exceed source size in keep-original policy representation,
    # but underlying estimate allows showing potential expansion
    p10_out = max(breakdown.total_nonvideo_bytes, p10_out)
    p50_out = max(p10_out, p50_out)
    p90_out = max(p50_out, p90_out)

    # Quantile consistency:
    # output_bytes(q) + savings_bytes(q) == source_bytes for EVERY quantile q!
    p10_sav_bytes = source_bytes - p10_out
    p50_sav_bytes = source_bytes - p50_out
    p90_sav_bytes = source_bytes - p90_out

    p10_sav_pct = (p10_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0
    p50_sav_pct = (p50_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0
    p90_sav_pct = (p90_sav_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0

    # 8. Decision categorization
    if is_hard_infeasible:
        decision = "infeasible"
        confidence = "medium"  # Hard budget overflow is deterministic based on non-video bytes
    elif quality_floor_violated:
        decision = "quality_floor_violation"
        confidence = "low"
    else:
        # Check if optimistic savings meets user thresholds
        # Note: optimistic savings is p10_sav_bytes (since p10_out is the smallest output size)
        opt_meets_pct = (min_savings_pct is None) or (p10_sav_pct >= min_savings_pct)
        opt_meets_bytes = (min_savings_bytes is None) or (p10_sav_bytes >= min_savings_bytes)
        opt_meets = (opt_meets_pct and opt_meets_bytes) if savings_policy == "both" else (opt_meets_pct or opt_meets_bytes)

        # Check if conservative savings meets user thresholds
        # Note: conservative savings is p90_sav_bytes (since p90_out is the largest output size)
        cons_meets_pct = (min_savings_pct is None) or (p90_sav_pct >= min_savings_pct)
        cons_meets_bytes = (min_savings_bytes is None) or (p90_sav_bytes >= min_savings_bytes)
        cons_meets = (cons_meets_pct and cons_meets_bytes) if savings_policy == "both" else (cons_meets_pct or cons_meets_bytes)

        if not opt_meets:
            decision = "eligible_unlikely"
            confidence = "low"
            reasons.append("Predicted savings even under optimistic scenario assumption are below required threshold.")
        elif cons_meets:
            decision = "eligible_promising"
            confidence = "low"  # Uncalibrated metadata estimates must not claim high confidence
        else:
            decision = "eligible_uncertain"
            confidence = "low"
            reasons.append("Plausible savings interval straddles decision threshold; sample trial measurement required.")

    # Confidence must never overstate evidence on uncalibrated priors
    if bitrate_provenance == "container_derived_approximation" or breakdown.audio_provenance == "estimated_fallback":
        confidence = "low"

    return FeasibilityAssessment(
        source_id=asset.source_id,
        recipe_id=recipe.recipe_id,
        source_bytes=source_bytes,
        duration_seconds=duration,
        video_bitrate_bps=video_bitrate_bps,
        bitrate_provenance=bitrate_provenance,
        breakdown=breakdown,
        reconciliation=reconciliation,
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
        calibration_status="uncalibrated_scenario_assumptions",
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
    reconciliation = SizeReconciliation(
        source_bytes=asset.file_bytes,
        duration_seconds=asset.duration_seconds,
        probed_video_bitrate_bps=None,
        implied_video_bytes=None,
        reconciled_video_bytes=0,
        estimated_audio_bytes=0,
        estimated_subtitle_bytes=0,
        estimated_attachment_bytes=0,
        estimated_mux_overhead_bytes=0,
        total_estimated_nonvideo_bytes=0,
        unaccounted_container_bytes=asset.file_bytes,
        unaccounted_ratio=1.0,
    )
    return FeasibilityAssessment(
        source_id=asset.source_id,
        recipe_id=recipe.recipe_id,
        source_bytes=asset.file_bytes,
        duration_seconds=asset.duration_seconds,
        video_bitrate_bps=None,
        bitrate_provenance="missing",
        breakdown=breakdown,
        reconciliation=reconciliation,
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
        confidence="medium",
        is_hard_infeasible=True,
        rejection_reasons=("No compatible video stream found in asset.",),
        warnings=(),
        calibration_status="uncalibrated_scenario_assumptions",
    )
