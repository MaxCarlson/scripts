#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

def run_ffprobe_json(path: Path) -> Optional[Dict[str, Any]]:
    """
    Optimized ffprobe metadata extraction with minimal fields for speed.

    Only extracts fields actually used in the pipeline:
    - Format: duration, format_name, bit_rate
    - Video stream (v:0): width, height, codec_name, r_frame_rate, bit_rate

    Using -select_streams v:0 targets only the first video stream for faster execution.
    Returns None on error/timeout (30s max).
    """
    if not path or not path.exists():
        return None

    try:
        # Optimized: Use -select_streams v:0 to only query first video stream (faster)
        # Only request fields actually used in pipeline
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",  # Only first video stream
            "-show_entries", "stream=width,height,codec_name,r_frame_rate,bit_rate,codec_type",
            "-show_entries", "format=duration,format_name,bit_rate",
            "-of", "json",
            str(path),
        ]

        # Use timeout to prevent hanging on corrupted files
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,  # 30-second timeout
            text=True
        )

        if result.returncode != 0:
            return None

        if not result.stdout.strip():
            return None

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        # Log timeout but don't raise - return None for consistency
        return None
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        # Expected errors that should not crash the pipeline
        return None
    except Exception:
        # Catch-all for unexpected errors
        return None
