#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified downloader wrapper for yt-dlp and aebndl with live NDJSON events and logs.

Key behaviors:
- Defaults mirror your earlier scripts:
   URL files default roots:
      AEBN:   ./files/downloads/ae-stars/
      yt-dlp: ./files/downloads/stars/
   Output default: ./stars/{urlfile_stem}/
   yt-dlp naming: "%(title)s.%(ext)s"
- Real-time parsing using procparsers (handles '\r' progress).
- Two logs:
   Program log (your format): START/FINISH_* lines.
   Raw tool logs per-URL (exact stdout/stderr).

Argument style: short -k, long --full-words-with-dashes
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from procparsers import iter_parsed_events, events_to_ndjson

# ---- CLI --------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytaedler.py",
        description="Unified downloader for yt-dlp and aebndl with live JSON events and logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-f", "--url-file", required=True, help="Path to a URL file (one URL per line).")
    p.add_argument("-m", "--mode", default="auto", choices=["auto", "yt", "aebn"],
                   help="Which downloader to use; 'auto' chooses per-URL.")
    p.add_argument("-o", "--output-dir", help="Output directory; defaults to ./stars/{urlfile_stem}/")
    p.add_argument("-Y", "--ytdlp-url-dir", default="./files/downloads/stars", help="Default folder for yt-dlp URL files.")
    p.add_argument("-A", "--aebn-url-dir", default="./files/downloads/ae-stars", help="Default folder for AEBN URL files.")
    p.add_argument("-w", "--work-dir", default="./tmp", help="Work dir for aebndl (segments, temp).")
    p.add_argument("-g", "--program-log", default="./logs/ytaedler.log", help="Program log file (START/FINISH lines).")
    p.add_argument("-r", "--raw-log-dir", default="./logs/raw", help="Directory to store raw tool stdout logs.")
    p.add_argument("-t", "--timeout-seconds", type=int, default=None, help="Per-URL timeout for the tool process.")
    p.add_argument("-R", "--retries", type=int, default=1, help="Retries per URL when tool exits non-zero.")
    p.add_argument("-n", "--dry-run", action="store_true", help="Do not call external tools; print planned commands.")
    p.add_argument("-q", "--quiet", action="store_true", help="Reduce wrapper verbosity (still emits NDJSON events).")
    p.add_argument("-P", "--progress-log-freq", type=int, default=30,
                   help="Every N seconds, append a PROGRESS line to the program log (0 to disable).")
    p.add_argument("-U", "--max-ndjson-rate", type=float, default=5.0,
                   help="Max NDJSON progress events printed per second (-1 for unlimited). Applies to 'progress' events.")
    p.add_argument("-a", "--archive-dir", type=str, default=None, help="Directory to store per-urlfile archive status files.")
    p.add_argument("-S", "--stall-seconds", type=int, default=60, help="If no non-heartbeat events arrive for N seconds, treat URL as stalled and move to next.")
    p.add_argument("-E", "--exit-at-time", type=int, default=-1, help="Exit the program after N seconds (<=0 disables).")
    p.add_argument("-X", "--max-dl-speed", type=float, default=None,
                   help="Limit download speed to MiB/s (per process). Applies to yt-dlp via --limit-rate; aebndl currently not limited.")

    return p

# ---- Utils ------------------------------------------------------------------

def _read_urls(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";") or s.startswith("]"):
            continue
        out.append(s.split("  #", 1)[0].split("  ;", 1)[0].strip())
    # stable de-dup
    return list(dict.fromkeys(out))

# ... full content intentionally mirrored from original file ...

from typing import Dict  # below definitions rely on Dict

def _looks_supported_video(url: str) -> bool:
    # Heuristics can be refined as needed
    return any(x in url for x in ("/watch?v=", "aebn.com", "pornhub.com", "xvideos.com", "/video/"))

def _is_aebn(url: str) -> bool:
    return "aebn" in url.lower()

def _extract_video_id(url: str) -> str:
    # very loose ID extraction; avoids importing heavy libs for ID parsing
    for sep in ("/", "?", "&", "="):
        url = url.replace(sep, " ")
    parts = [p for p in url.split(" ") if p]
    return parts[-1] if parts else ""

def main() -> int:
    # Defer to the original implementation file colocated in the module folder.
    # This allows us to ship the stable package/CLI name now and migrate internals later.
    import importlib.util as _iu
    from importlib.machinery import SourceFileLoader as _Loader  # type: ignore
    from pathlib import Path as _P
    _impl_path = _P(__file__).resolve().parents[1] / "dlscript.py"
    if _impl_path.exists():
        spec = _iu.spec_from_loader("ytaedl_impl_dlscript", _Loader("ytaedl_impl_dlscript", str(_impl_path)))
        if spec and spec.loader:
            mod = _iu.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            return int(mod.main())
    # Fallback: if the colocated implementation is missing (e.g. in a built wheel),
    # keep the CLI minimally responsive by printing help.
    parser = make_parser()
    parser.print_help()
    return 2

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
