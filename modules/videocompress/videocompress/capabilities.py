"""
Host capability probing for FFmpeg, NVENC, filters, and curses.
Follows Stage 0 verification requirements.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


def probe_capabilities(check_encode: bool = False) -> dict[str, Any]:
    """Inspect and return verified host capabilities."""
    caps: dict[str, Any] = {
        "ffmpeg_available": False,
        "ffmpeg_path": None,
        "ffmpeg_version": None,
        "ffprobe_available": False,
        "ffprobe_path": None,
        "gpu_available": False,
        "gpu_name": None,
        "hardware_encoders": [],
        "software_encoders": [],
        "vmaf_available": False,
        "curses_available": False,
    }

    # 1. FFmpeg
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        caps["ffmpeg_available"] = True
        caps["ffmpeg_path"] = ffmpeg_bin
        try:
            p = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5)
            first_line = p.stdout.splitlines()[0] if p.stdout else ""
            caps["ffmpeg_version"] = first_line
        except Exception:
            pass

    # 2. FFprobe
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        caps["ffprobe_available"] = True
        caps["ffprobe_path"] = ffprobe_bin

    # 3. GPU via nvidia-smi
    smi_bin = shutil.which("nvidia-smi")
    if smi_bin:
        try:
            p = subprocess.run(
                [smi_bin, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if p.returncode == 0 and p.stdout.strip():
                parts = p.stdout.strip().split(",")
                caps["gpu_available"] = True
                caps["gpu_name"] = parts[0].strip()
                caps["driver_version"] = parts[1].strip() if len(parts) > 1 else None
                caps["vram_total"] = parts[2].strip() if len(parts) > 2 else None
        except Exception:
            pass

    # 4. Encoders from ffmpeg
    if ffmpeg_bin:
        try:
            p = subprocess.run([ffmpeg_bin, "-encoders"], capture_output=True, text=True, timeout=5)
            stdout = p.stdout or ""
            hw_candidates = ["av1_nvenc", "hevc_nvenc", "h264_nvenc"]
            sw_candidates = ["libsvtav1", "libx265", "libx264", "librav1e", "libaom-av1"]
            caps["hardware_encoders"] = [enc for enc in hw_candidates if enc in stdout]
            caps["software_encoders"] = [enc for enc in sw_candidates if enc in stdout]
        except Exception:
            pass

    # 5. Filters (vmaf)
    if ffmpeg_bin:
        try:
            p = subprocess.run([ffmpeg_bin, "-filters"], capture_output=True, text=True, timeout=5)
            caps["vmaf_available"] = "libvmaf" in (p.stdout or "")
        except Exception:
            pass

    # 6. Curses support
    try:
        import curses  # noqa: F401
        caps["curses_available"] = True
    except Exception:
        caps["curses_available"] = False

    return caps
