"""
Structured FFprobe inspection and stream layout extraction.
Follows INTEGRATION_CONTRACTS.md §7 and MEDIA_SAFETY_CONTRACT.md §2.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from .contracts import VideoAsset, VideoStream


def _parse_fraction(frac_str: str | None) -> tuple[int | None, int | None]:
    """Parse a fraction string like '24000/1001' into (numerator, denominator)."""
    if not frac_str or "/" not in frac_str:
        return None, None
    try:
        num, den = frac_str.split("/", 1)
        return int(num), int(den)
    except (ValueError, TypeError):
        return None, None


def _extract_rotation(stream_dict: Mapping[str, Any]) -> int:
    """Extract display rotation degrees from stream tags or side data."""
    # 1. tags.rotate (case-insensitive)
    tags = stream_dict.get("tags", {})
    if isinstance(tags, dict):
        for k, v in tags.items():
            if str(k).lower() == "rotate":
                try:
                    return int(float(v)) % 360
                except (ValueError, TypeError):
                    pass

    # 2. side_data_list (e.g. displaymatrix)
    side_data_list = stream_dict.get("side_data_list", [])
    if isinstance(side_data_list, list):
        for sd in side_data_list:
            if isinstance(sd, dict):
                if "rotation" in sd:
                    try:
                        return int(float(sd["rotation"])) % 360
                    except (ValueError, TypeError):
                        pass
    return 0


def _is_hdr_stream(stream_dict: Mapping[str, Any]) -> bool:
    """Detect High Dynamic Range (HDR10, HLG, Dolby Vision) stream characteristics."""
    trc = str(stream_dict.get("color_transfer", "")).lower()
    primaries = str(stream_dict.get("color_primaries", "")).lower()

    if trc in ("smpte2084", "arib-std-b67"):  # PQ (HDR10) or HLG
        return True
    if primaries in ("bt2020",):
        return True

    # Side data check for mastering display or DOVI
    side_data = stream_dict.get("side_data_list", [])
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict):
                sd_type = str(item.get("side_data_type", "")).lower()
                if "mastering display" in sd_type or "content light level" in sd_type or "dovi" in sd_type:
                    return True
    return False


def parse_ffprobe_json(
    source_id: str,
    relative_path: str,
    file_bytes: int,
    data: Mapping[str, Any],
) -> VideoAsset:
    """Parse raw ffprobe JSON dict into typed VideoAsset."""
    format_data = data.get("format", {})
    container_format = format_data.get("format_name", "unknown")
    try:
        duration_seconds = float(format_data.get("duration", 0.0))
    except (ValueError, TypeError):
        duration_seconds = 0.0

    raw_streams = data.get("streams", [])
    parsed_streams: list[VideoStream] = []

    for s in raw_streams:
        if not isinstance(s, dict):
            continue
        stream_type = str(s.get("codec_type", "unknown")).lower()
        codec_name = str(s.get("codec_name", "unknown"))
        stream_index = int(s.get("index", len(parsed_streams)))

        # Stream bitrate
        bit_rate_bps: int | None = None
        bitrate_provenance = "missing"
        raw_bitrate = s.get("bit_rate")
        if raw_bitrate:
            try:
                parsed_bps = int(raw_bitrate)
                if parsed_bps > 0:
                    bit_rate_bps = parsed_bps
                    bitrate_provenance = "ffprobe_stream"
            except (ValueError, TypeError):
                pass

        # FPS
        fps_num, fps_den = _parse_fraction(s.get("r_frame_rate"))

        # Stream duration
        st_duration: float | None = None
        if "duration" in s:
            try:
                st_duration = float(s["duration"])
            except (ValueError, TypeError):
                st_duration = None

        # Bit depth
        bit_depth: int | None = None
        if "bits_per_raw_sample" in s:
            try:
                bit_depth = int(s["bits_per_raw_sample"])
            except (ValueError, TypeError):
                pass
        if bit_depth is None and "pix_fmt" in s:
            pix = str(s["pix_fmt"]).lower()
            if "10le" in pix or "10be" in pix or "p10" in pix:
                bit_depth = 10
            elif "12le" in pix or "12be" in pix or "p12" in pix:
                bit_depth = 12
            else:
                bit_depth = 8

        # Tags
        tags = s.get("tags", {})
        language = tags.get("language") if isinstance(tags, dict) else None
        title = tags.get("title") if isinstance(tags, dict) else None

        # Dispositions
        disposition = s.get("disposition", {})
        is_attached = bool(disposition.get("attached_pic", 0)) if isinstance(disposition, dict) else False

        parsed_streams.append(
            VideoStream(
                stream_index=stream_index,
                stream_type=stream_type,
                codec_name=codec_name,
                bit_rate_bps=bit_rate_bps,
                bitrate_provenance=bitrate_provenance,
                profile=s.get("profile"),
                level=int(s["level"]) if "level" in s and str(s["level"]).isdigit() else None,
                width=int(s["width"]) if "width" in s else None,
                height=int(s["height"]) if "height" in s else None,
                sample_aspect_ratio=s.get("sample_aspect_ratio"),
                display_aspect_ratio=s.get("display_aspect_ratio"),
                rotation_degrees=_extract_rotation(s),
                fps_num=fps_num,
                fps_den=fps_den,
                duration_seconds=st_duration or duration_seconds,
                pix_fmt=s.get("pix_fmt"),
                bit_depth=bit_depth,
                color_range=s.get("color_range"),
                color_primaries=s.get("color_primaries"),
                color_transfer=s.get("color_transfer"),
                color_space=s.get("color_space"),
                is_hdr=_is_hdr_stream(s),
                is_attached_pic=is_attached,
                channels=int(s["channels"]) if "channels" in s else None,
                channel_layout=s.get("channel_layout"),
                sample_rate=int(s["sample_rate"]) if "sample_rate" in s else None,
                language=language,
                title=title,
                disposition=dict(disposition) if isinstance(disposition, dict) else {},
            )
        )

    return VideoAsset(
        source_id=source_id,
        relative_path=relative_path,
        file_bytes=file_bytes,
        container_format=container_format,
        duration_seconds=duration_seconds,
        streams=tuple(parsed_streams),
        chapters_count=len(data.get("chapters", [])),
        probe_status="complete",
        probe_tool="ffprobe",
        errors=(),
    )


def probe_video_file(
    file_path: Path | str,
    relative_path: str | None = None,
    ffprobe_bin: str | None = None,
    timeout_seconds: int = 15,
) -> VideoAsset:
    """
    Execute ffprobe on target file and return structured VideoAsset.
    Captures video, audio, subtitle, chapter, and disposition metadata.
    """
    path = Path(file_path).expanduser().resolve()
    rel = relative_path or path.name

    try:
        st = path.stat()
        file_bytes = st.st_size
    except OSError as e:
        return VideoAsset(
            source_id=hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
            relative_path=rel,
            file_bytes=0,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=(f"Filesystem error: {e}",),
        )

    canonical_str = str(path).lower() if os.name == "nt" else str(path)
    source_id = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]

    probe_exe = ffprobe_bin or shutil.which("ffprobe")
    if not probe_exe:
        return VideoAsset(
            source_id=source_id,
            relative_path=rel,
            file_bytes=file_bytes,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=("FFprobe binary not found on system PATH.",),
        )

    cmd = [
        probe_exe,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        "-print_format", "json",
        str(path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return VideoAsset(
            source_id=source_id,
            relative_path=rel,
            file_bytes=file_bytes,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=(f"FFprobe timed out after {timeout_seconds} seconds.",),
        )
    except Exception as e:
        return VideoAsset(
            source_id=source_id,
            relative_path=rel,
            file_bytes=file_bytes,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=(f"Subprocess launch error: {e}",),
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or f"FFprobe exited with code {proc.returncode}"
        return VideoAsset(
            source_id=source_id,
            relative_path=rel,
            file_bytes=file_bytes,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=(err_msg,),
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return VideoAsset(
            source_id=source_id,
            relative_path=rel,
            file_bytes=file_bytes,
            container_format="unknown",
            duration_seconds=0.0,
            streams=(),
            probe_status="failed",
            errors=(f"Invalid JSON from FFprobe: {e}",),
        )

    return parse_ffprobe_json(
        source_id=source_id,
        relative_path=rel,
        file_bytes=file_bytes,
        data=data,
    )
