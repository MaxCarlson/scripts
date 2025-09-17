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
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,bit_rate,format_name",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,bit_rate",
            "-of", "json",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return json.loads(out.decode("utf-8", errors="ignore"))
    except Exception:
        return None
