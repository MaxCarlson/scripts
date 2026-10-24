"""
Configurable lower-bound eligibility and exclusion filtering.
Follows IMPLEMENTATION_PLAN.md §4.2 and MEDIA_SAFETY_CONTRACT.md §2.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .contracts import EligibilityDecision, VideoAsset, VideoStream


def parse_bitrate(value: str | int | float | None) -> int | None:
    """
    Parse a bitrate string (e.g. '4M', '2500k', '5000000') into bits per second.
    Supports decimal 'k' (1,000), 'M' (1,000,000), 'G' (1,000,000,000).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^([\d.]+)\s*([kmgKMG]?)$", s)
    if not m:
        raise ValueError(f"Invalid bitrate string: '{value}'")
    num_str, unit = m.groups()
    num = float(num_str)
    unit_lower = unit.lower()
    if unit_lower == "k":
        return int(num * 1_000)
    elif unit_lower == "m":
        return int(num * 1_000_000)
    elif unit_lower == "g":
        return int(num * 1_000_000_000)
    return int(num)


def parse_resolution(value: str | tuple[int, int] | None) -> tuple[int, int] | None:
    """Parse resolution string (e.g. '1920x1080') into (width, height)."""
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        return int(value[0]), int(value[1])
    s = str(value).strip().lower()
    if "x" not in s:
        raise ValueError(f"Invalid resolution format: '{value}' (expected WIDTHxHEIGHT, e.g. 1920x1080)")
    w_str, h_str = s.split("x", 1)
    return int(w_str), int(h_str)


def parse_size(value: str | int | None) -> int | None:
    """
    Parse a file size string (e.g. '100M', '1G', '500k') into bytes.
    Decimal units: k=10^3, M=10^6, G=10^9; KiB/MiB/GiB also supported.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^([\d.]+)\s*([kmgtKMGT]i?[bB]?)$", s)
    if not m:
        try:
            return int(s)
        except ValueError:
            raise ValueError(f"Invalid size string: '{value}'")
    num_str, unit = m.groups()
    num = float(num_str)
    unit_norm = unit.lower()
    if "mib" in unit_norm or "m" in unit_norm:
        mult = 1024 * 1024 if "mib" in unit_norm else 1_000_000
    elif "kib" in unit_norm or "k" in unit_norm:
        mult = 1024 if "kib" in unit_norm else 1_000
    elif "gib" in unit_norm or "g" in unit_norm:
        mult = 1024 * 1024 * 1024 if "gib" in unit_norm else 1_000_000_000
    else:
        mult = 1
    return int(num * mult)


def parse_duration(value: str | float | int | None) -> float | None:
    """Parse duration string (e.g. '60', '10m', '1.5h') into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if not s:
        return None
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m"):
        return float(s[:-1]) * 60.0
    if s.endswith("h"):
        return float(s[:-1]) * 3600.0
    return float(s)


def evaluate_eligibility(
    asset: VideoAsset,
    min_video_bitrate: int | str | None = None,
    min_resolution: str | tuple[int, int] | None = None,
    min_size: int | str | None = None,
    min_duration: float | str | None = None,
) -> EligibilityDecision:
    """
    Evaluate a VideoAsset against configured lower bounds and safety rules.
    Conservative handling: missing measurements yield 'unknown' status.
    """
    applied_thresholds: dict[str, Any] = {}
    reasons: list[str] = []
    unknowns: list[str] = []

    # 1. Probe failure check
    if asset.probe_status != "complete":
        return EligibilityDecision(
            stage="metadata",
            status="ineligible",
            reasons=("probe_failed", *asset.errors),
        )

    # 2. Video streams inspection
    real_video_streams = [s for s in asset.streams if s.stream_type == "video" and not s.is_attached_pic]
    if not real_video_streams:
        return EligibilityDecision(
            stage="metadata",
            status="ineligible",
            reasons=("no_video_streams_found",),
        )

    if len(real_video_streams) > 1:
        return EligibilityDecision(
            stage="metadata",
            status="unsupported",
            reasons=(f"multiple_video_streams_detected: count={len(real_video_streams)}",),
        )

    primary = real_video_streams[0]

    # 3. Minimum Bitrate Filter
    parsed_min_bps = parse_bitrate(min_video_bitrate)
    if parsed_min_bps is not None:
        applied_thresholds["min_video_bitrate_bps"] = parsed_min_bps
        if primary.bit_rate_bps is None:
            unknowns.append("unknown_video_bitrate")
            reasons.append("video_stream_bitrate_missing")
        elif primary.bit_rate_bps < parsed_min_bps:
            reasons.append(f"below_min_bitrate: {primary.bit_rate_bps} < {parsed_min_bps}")

    # 4. Minimum Resolution Filter
    parsed_res = parse_resolution(min_resolution)
    if parsed_res is not None:
        applied_thresholds["min_resolution"] = parsed_res
        min_w, min_h = parsed_res

        # Account for display rotation
        w = primary.width or 0
        h = primary.height or 0
        if primary.rotation_degrees in (90, 270):
            w, h = h, w

        if w < min_w or h < min_h:
            reasons.append(f"below_min_resolution: {w}x{h} < {min_w}x{min_h}")

    # 5. Minimum File Size Filter
    parsed_size = parse_size(min_size)
    if parsed_size is not None:
        applied_thresholds["min_file_bytes"] = parsed_size
        if asset.file_bytes < parsed_size:
            reasons.append(f"below_min_size: {asset.file_bytes} < {parsed_size}")

    # 6. Minimum Duration Filter
    parsed_dur = parse_duration(min_duration)
    if parsed_dur is not None:
        applied_thresholds["min_duration_seconds"] = parsed_dur
        if asset.duration_seconds < parsed_dur:
            reasons.append(f"below_min_duration: {asset.duration_seconds:.1f}s < {parsed_dur:.1f}s")

    # Final decision determination
    if unknowns:
        status = "unknown"
    elif reasons:
        status = "excluded"
    else:
        status = "eligible"
        reasons.append("all_thresholds_met")

    return EligibilityDecision(
        stage="metadata",
        status=status,
        reasons=tuple(reasons),
        applied_thresholds=applied_thresholds,
        unknowns=tuple(unknowns),
    )
