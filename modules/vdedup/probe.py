#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

def run_ffprobe_json(path: Path) -> Optional[Dict[str, Any]]:
    """
    Fast container/stream metadata via ffprobe (no full decode).
    ffprobe duration is quick and suitable for coarse grouping.  # 4
    """
    if not path or not path.exists():
        return None

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,bit_rate,format_name",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,bit_rate",
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
