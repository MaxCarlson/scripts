"""
Tests for FFprobe structured JSON extraction and stream parsing.
Uses real FFmpeg/FFprobe to generate synthetic sample files.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import pytest

from videocompress.probe import parse_ffprobe_json, probe_video_file


def _has_ffmpeg() -> bool:
    try:
        p = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return p.returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _has_ffmpeg(), reason="FFmpeg not available")
def test_probe_standard_video_with_audio(tmp_path: Path):
    target = tmp_path / "standard.mp4"
    # Generate 1s test video with h264 and aac
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=24:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-c:v", "libx264", "-b:v", "2000k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(target)
    ]
    subprocess.run(cmd, check=True)

    asset = probe_video_file(target)
    assert asset.probe_status == "complete"
    assert asset.container_format in ("mov,mp4,m4a,3gp,3g2,mj2", "mp4")
    assert asset.duration_seconds >= 0.9

    # Check streams
    assert len(asset.streams) >= 2
    pv = asset.primary_video_stream
    assert pv is not None
    assert pv.stream_type == "video"
    assert pv.codec_name == "h264"
    assert pv.width == 1920
    assert pv.height == 1080
    assert pv.rotation_degrees == 0
    assert pv.is_hdr is False
    assert pv.is_attached_pic is False

    # Video stream bitrate must be distinct from container
    # In MP4 container with lavfi, stream bit_rate or format bit_rate exists
    assert pv.bitrate_provenance in ("ffprobe_stream", "missing")

    # Check audio stream
    audio_streams = [s for s in asset.streams if s.stream_type == "audio"]
    assert len(audio_streams) == 1
    assert audio_streams[0].codec_name == "aac"
    assert audio_streams[0].channels == 1 or audio_streams[0].channels == 2


@pytest.mark.skipif(not _has_ffmpeg(), reason="FFmpeg not available")
def test_probe_rotated_video(tmp_path: Path):
    target = tmp_path / "rotated.mkv"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=24:duration=1",
        "-c:v", "libx264", "-metadata:s:v:0", "rotate=90",
        str(target)
    ]
    subprocess.run(cmd, check=True)

    asset = probe_video_file(target)
    pv = asset.primary_video_stream
    assert pv is not None
    assert pv.rotation_degrees == 90
    assert pv.width == 1920
    assert pv.height == 1080


@pytest.mark.skipif(not _has_ffmpeg(), reason="FFmpeg not available")
def test_probe_hdr_metadata(tmp_path: Path):
    target = tmp_path / "hdr.mkv"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=1",
        "-c:v", "libx265", "-pix_fmt", "yuv420p10le",
        "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
        str(target)
    ]
    subprocess.run(cmd, check=True)

    asset = probe_video_file(target)
    pv = asset.primary_video_stream
    assert pv is not None
    assert pv.color_primaries == "bt2020"
    assert pv.color_transfer == "smpte2084"
    assert pv.is_hdr is True


def test_probe_corrupted_file(tmp_path: Path):
    target = tmp_path / "corrupt.mp4"
    target.write_bytes(b"RANDOM_CORRUPTED_BYTES_NOT_A_VIDEO")

    asset = probe_video_file(target)
    assert asset.probe_status == "failed"
    assert len(asset.errors) > 0
    assert asset.primary_video_stream is None


def test_parse_ffprobe_json_missing_stream_bitrate():
    # Synthetic JSON payload where stream bit_rate is missing
    payload = {
        "format": {
            "format_name": "matroska,webm",
            "duration": "100.5",
            "size": "50000000",
            "bit_rate": "3980099",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "24/1",
                "avg_frame_rate": "24/1",
                "pix_fmt": "yuv420p",
                "disposition": {"default": 1, "attached_pic": 0},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "bit_rate": "192000",
                "channels": 2,
                "sample_rate": "48000",
            }
        ],
        "chapters": []
    }
    asset = parse_ffprobe_json(
        source_id="src-1",
        relative_path="test.mkv",
        file_bytes=50000000,
        data=payload,
    )
    pv = asset.primary_video_stream
    assert pv is not None
    assert pv.bit_rate_bps is None
    assert pv.bitrate_provenance == "missing"
    # Never substitute format bit_rate into stream bit_rate
    assert pv.bit_rate_bps != 3980099
