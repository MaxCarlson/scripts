#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fast metadata probing for web videos.

Strategies:
- YouTube → Invidious API (if available).
- Direct media (mp4/webm/m3u8) → ffprobe.
- Fallback → yt-dlp --print.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from typing import Dict, Optional

YOUTUBE_REGEX = re.compile(r"(youtube\.com|youtu\.be)")

# -------------------- Invidious --------------------

def _invidious_metadata(url: str, instance: str = "https://yewtu.be") -> Optional[Dict]:
    """
    Try Invidious API for YouTube URLs.
    Returns dict with title, lengthSeconds, etc. or None if fails.
    """
    try:
        if not YOUTUBE_REGEX.search(url):
            return None
        # extract video ID
        if "v=" in url:
            vid = url.split("v=")[-1].split("&")[0]
        else:
            vid = url.rstrip("/").split("/")[-1]
        api_url = f"{instance}/api/v1/videos/{vid}"
        with urllib.request.urlopen(api_url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

# -------------------- ffprobe --------------------

def _ffprobe_metadata(url: str) -> Optional[Dict]:
    """
    Run ffprobe on a direct media URL. Requires ffprobe in PATH.
    Returns dict with codec, width, height, duration, bit_rate.
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,bit_rate:stream=codec_name,width,height",
            "-of", "json", url,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=10)
        return json.loads(out)
    except Exception:
        return None

# -------------------- yt-dlp --------------------

def _ytdlp_metadata(url: str) -> Optional[Dict]:
    """
    Fallback: yt-dlp --dump-json --skip-download.
    """
    if not shutil.which("yt-dlp"):
        return None
    try:
        cmd = ["yt-dlp", "--dump-json", "--no-warnings", "--skip-download", url]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=20)
        return json.loads(out)
    except Exception:
        return None

# -------------------- Public API --------------------

def get_metadata(url: str) -> Dict:
    """
    Try multiple strategies in order:
      1. Invidious (YouTube only)
      2. ffprobe (direct media)
      3. yt-dlp (universal fallback)
    Returns a dict (may be empty if all fail).
    """
    data = _invidious_metadata(url)
    if data:
        return {"source": "invidious", **data}
    data = _ffprobe_metadata(url)
    if data:
        return {"source": "ffprobe", **data}
    data = _ytdlp_metadata(url)
    if data:
        return {"source": "yt-dlp", **data}
    return {"source": "none"}
