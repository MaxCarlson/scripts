#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified downloader wrapper for yt-dlp and aebndl with live NDJSON events and logs.

Key behaviors:
- Defaults mirror your earlier scripts:
  • URL files default roots:
      AEBN:   ./files/downloads/ae-stars/
      yt-dlp: ./files/downloads/stars/
  • Output default: ./stars/{urlfile_stem}/
  • yt-dlp naming: "%(title)s.%(ext)s"
- Real-time parsing using procparsers (handles '\r' progress).
- Two logs:
  • Program log (your format): START/FINISH_* lines.
  • Raw tool logs per-URL (exact stdout/stderr).

Argument style: short -k, long --full-words-with-dashes
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from procparsers import iter_parsed_events

try:
    from . import _partial_utils
    from . import yt_grid
    from . import __version__ as YTAEDL_VERSION
    from .urlfile_lock import LOCK_ERROR_RC, LOCK_HELD_RC, LockAttempt, UrlFileLock
except ImportError:  # pragma: no cover - used when downloader.py is executed by file path.
    import importlib.util

    def _load_sibling(name: str, filename: str):
        path = Path(__file__).with_name(filename)
        spec = importlib.util.spec_from_file_location(f"ytaedl_{name}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {filename}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    _partial_utils = _load_sibling("_partial_utils", "_partial_utils.py")
    yt_grid = _load_sibling("yt_grid", "yt_grid.py")
    _urlfile_lock = _load_sibling("urlfile_lock", "urlfile_lock.py")
    LOCK_ERROR_RC = _urlfile_lock.LOCK_ERROR_RC
    LOCK_HELD_RC = _urlfile_lock.LOCK_HELD_RC
    LockAttempt = _urlfile_lock.LockAttempt
    UrlFileLock = _urlfile_lock.UrlFileLock
    YTAEDL_VERSION = "unknown"

MAX_RESOLUTION_CHOICES = ("4k", "2k", "1080", "720", "480")
_MAX_RESOLUTION_HEIGHTS = {
    "4k": 2160,
    "2k": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
}


def _max_height_for_label(label: Optional[str]) -> Optional[int]:
    if not label:
        return None
    return _MAX_RESOLUTION_HEIGHTS.get(label.lower())


# ---- CLI --------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytaedler.py",
        description=f"ytaedl {YTAEDL_VERSION} worker - unified downloader for yt-dlp and aebndl with live JSON events and logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-f", "--url-file", required=True, help="Path to a URL file (one URL per line).")
    p.add_argument("-m", "--mode", default="auto", choices=["auto", "yt", "aebn"],
                   help="Which downloader to use; 'auto' chooses per-URL.")
    p.add_argument("-o", "--output-dir", help="Output directory; defaults to ./stars/{urlfile_stem}/")
    p.add_argument("-P", "--proxy-dl-location", help="Download into this root (per url file subfolder) while checking duplicates in the canonical location.")
    p.add_argument("-Y", "--ytdlp-url-dir", default="./files/downloads/stars", help="Default folder for yt-dlp URL files.")
    p.add_argument("-A", "--aebn-url-dir", default="./files/downloads/ae-stars", help="Default folder for AEBN URL files.")
    p.add_argument("-w", "--work-dir", default="./tmp", help="Work dir for aebndl (segments, temp).")
    p.add_argument("-g", "--program-log", default="./logs/ytaedler.log", help="Program log file (START/FINISH lines).")
    p.add_argument("-r", "--raw-log-dir", default="./logs/raw", help="Directory to store raw tool stdout logs.")
    p.add_argument("-t", "--timeout-seconds", type=int, default=None, help="Per-URL timeout for the tool process.")
    p.add_argument("-R", "--retries", type=int, default=1, help="Retries per URL when tool exits non-zero.")
    p.add_argument("-n", "--dry-run", action="store_true", help="Do not call external tools; print planned commands.")
    p.add_argument("-q", "--quiet", action="store_true", help="Reduce wrapper verbosity (still emits NDJSON events).")
    p.add_argument("-p", "--progress-log-freq", type=int, default=30,
                   help="Every N seconds, append a PROGRESS line to the program log (0 to disable).")
    p.add_argument("-U", "--max-ndjson-rate", type=float, default=5.0,
                   help="Max NDJSON progress events printed per second (-1 for unlimited). Applies to 'progress' events.")
    p.add_argument("-a", "--archive-dir", type=str, default=None, help="Directory to store per-urlfile archive status files.")
    p.add_argument("-O", "--archive-source-file", type=str, default=None,
                   help="Original URL file used for archive naming and status lookup; defaults to --url-file.")
    p.add_argument("-S", "--stall-seconds", type=int, default=4, help="If no non-heartbeat events arrive for N seconds, treat URL as stalled and try fallback methods.")
    p.add_argument("-C", "--complete-stall-seconds", type=int, default=300, help="If download is stuck at >=99%% for N seconds (progress events still arriving), treat as stalled.")
    p.add_argument("-E", "--exit-at-time", type=int, default=-1, help="Exit the program after N seconds (<=0 disables).")
    p.add_argument("-X", "--max-dl-speed", type=float, default=None,
                   help="Limit download speed to MiB/s (per process). Applies to yt-dlp via --limit-rate; aebndl currently not limited.")
    p.add_argument("-H", "--max-resolution", choices=MAX_RESOLUTION_CHOICES, default=None,
                   help="Highest video resolution to allow (yt-dlp uses format filters; aebndl requests nearest available <= target).")
    p.add_argument("-B", "--stop-sentinel", type=str, default=None,
                   help="If this file exists before a URL starts, exit cleanly without starting more URLs.")
    p.add_argument("-N", "--no-extdl-fallback", action="store_true",
                   help="Disable the extdl static-HTML and Playwright fallback when yt-dlp fails.")
    p.add_argument("-j", "--extdl-max-candidates", type=int, default=5,
                   help="Max fallback media candidates to try per method (0 = all).")
    p.add_argument("-J", "--extdl-browser-wait", type=float, default=12.0,
                   help="Seconds to collect browser network traffic in the Playwright fallback.")
    p.add_argument("-Q", "--extdl-capture-browser", default="auto",
                   choices=["auto", "chromium", "firefox", "webkit"],
                   help="Playwright browser backend for the network capture fallback.")
    p.add_argument("-K", "--skip-simulate-check", action="store_true",
                   help="Skip the yt-dlp --simulate pre-download duplicate check.")
    p.add_argument("-G", "--ytdlp-grid-config-file", default=None,
                   help="JSON trial/config file with yt-dlp options selected by ytaedl grid search.")
    p.add_argument("-b", "--ytdlp-cookies-from-browser", default="firefox",
                   help="Browser to read cookies from for yt-dlp (firefox, chrome, etc.). Use 'none' to disable.")
    p.add_argument("-i", "--ytdlp-impersonate", default="chrome",
                   help="Browser to impersonate for yt-dlp TLS/UA fingerprint. Use 'none' to disable.")
    p.add_argument("-d", "--ytdlp-downloader", default="aria2c",
                   help="External downloader for yt-dlp (e.g. aria2c). Use 'native' or '' for the built-in downloader.")
    p.add_argument("-W", "--worker-slot", type=int, default=0,
                   help=argparse.SUPPRESS)  # set by manager; not user-facing
    p.add_argument("-Z", "--extra-canonical-roots", action="append", default=None,
                   help=argparse.SUPPRESS)  # additional canonical dirs to check for dupes; set by manager
    p.add_argument("-F", "--wait-for-url-file-lock", action="store_true",
                   help=argparse.SUPPRESS)  # exact-file manager workers wait instead of exiting
    p.add_argument("-c", "--manager-pid", type=int, default=None,
                   help=argparse.SUPPRESS)  # diagnostic lock-owner metadata
    p.add_argument("-V", "--url-file-lock-dir", default="./archive/locks",
                   help=argparse.SUPPRESS)  # manager-selected shared lock directory

    return p

# ---- Utils ------------------------------------------------------------------

def _read_urls(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # full-line comments
        if s.startswith("#") or s.startswith(";") or s.startswith("]"):
            continue
        # inline comments (only if preceded by whitespace)
        # Keep URL fragments like '#scene-123'
        out.append(s.split("  #", 1)[0].split("  ;", 1)[0].strip())
    # stable de-dup
    return list(dict.fromkeys(out))

def _is_aebn(url: str) -> bool:
    try:
        host = url.split("/")[2].lower()
    except Exception:
        return False
    return host.endswith(".aebn.com")

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _hms_ms(elapsed_s: float) -> str:
    ms = int(round((elapsed_s - int(elapsed_s)) * 1000))
    s = int(elapsed_s) % 60
    m = (int(elapsed_s) // 60) % 60
    h = int(elapsed_s) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def _looks_supported_video(url: str) -> bool:
    """Heuristic: return True if URL looks like a direct video page we can hand to the tool.
    Avoid known listing pages that yt-dlp often rejects without playlist flags.
    """
    try:
        host = url.split("/")[2].lower()
        path = "/" + "/".join(url.split("/")[3:])
    except Exception:
        return False
    # PornHub
    if host.endswith("pornhub.com"):
        return "view_video.php" in url or "/view_video.php" in url
    # Eporner
    if host.endswith("eporner.com"):
        # Typical video pages: /video-... or /video/... or /hd-porn/...
        if "/video-" in path or "/video/" in path or "/hd-porn/" in path:
            return True
        # Avoid pornstar/listing pages
        if "/pornstar/" in path or "/channels/" in path or "/category/" in path:
            return False
        # Fallback: unknown shapes treated as unsupported to be safe
        return False
    # AEBN video pages handled by aebndl
    if host.endswith("aebn.com"):
        return True
    # Default: allow
    return True

@dataclass
class ProgLogger:
    path: Path
    t0: float
    counter: int = 0

    def _wall(self) -> str:
        """Return current local time as HH:MM:SS for log prefixes."""
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _write(self, msg: str) -> None:
        _ensure_dir(self.path.parent)
        # Cross-process safe append (best effort): lock during write
        # Use msvcrt on Windows, fcntl on POSIX. Fallback to no lock.
        try:
            import msvcrt  # type: ignore
        except Exception:
            msvcrt = None  # type: ignore
        try:
            import fcntl  # type: ignore
        except Exception:
            fcntl = None  # type: ignore

        with self.path.open("a", encoding="utf-8") as f:  # text append
            try:
                if msvcrt and os.name == "nt":
                    # Lock a large region from current position
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1_000_000)
                elif fcntl and os.name != "nt":
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                f.write(msg + "\n")
                f.flush()
            finally:
                try:
                    if msvcrt and os.name == "nt":
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1_000_000)
                    elif fcntl and os.name != "nt":
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def start(self, url_index: int, url_total: int, url: str) -> None:
        self.counter += 1
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] START  [{url_index}/{url_total}] {url}")

    def finish(self, url_index: int, elapsed_url_s: float, status: str, reason: str = "") -> None:
        elapsed_prog = _hms_ms(time.time() - self.t0)
        elapsed_url = _hms_ms(elapsed_url_s)
        reason_part = f"  ({reason})" if reason else ""
        self._write(
            f"[{self._wall()}][{elapsed_prog}] {status} [{url_index}]"
            f" Elapsed {elapsed_url}, Status={status.replace('FINISH_', '')}{reason_part}"
        )

    def fallback_start(self, method: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] FALLBACK_START  method={method}")

    def fallback_attempt(self, method: str, attempt: int, total: int, kind: str, candidate_url: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        short_url = candidate_url[:100] + "…" if len(candidate_url) > 100 else candidate_url
        self._write(
            f"[{self._wall()}][{elapsed}] FALLBACK_TRY    "
            f"attempt {attempt}/{total}  method={method}  kind={kind}\n"
            f"                        url: {short_url}"
        )

    def fallback_result(self, method: str, attempt: int, total: int, rc: int) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        ok = rc == 0
        status_word = "SUCCESS" if ok else f"FAILED (rc={rc})"
        self._write(
            f"[{self._wall()}][{elapsed}] FALLBACK_RESULT "
            f"attempt {attempt}/{total}  method={method}  {status_word}"
        )

    def fallback_skip(self, method: str, reason: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] FALLBACK_SKIP   method={method}  {reason}")

    def fallback_exhausted(self) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] FALLBACK_EXHAUSTED  all methods failed – URL marked BAD")

    def attempt_start(self, attempt_num: int, description: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] ATTEMPT_{attempt_num}_START  {description}")

    def attempt_fail(self, attempt_num: int, description: str, reason: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(
            f"[{self._wall()}][{elapsed}] ATTEMPT_{attempt_num}_FAIL   "
            f"{description}  ({reason})"
        )

    def attempt_success(self, attempt_num: int, description: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] ATTEMPT_{attempt_num}_OK    {description}")

    def simulate_start(self, url: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self._wall()}][{elapsed}] SIMULATE_START  {url}")

    def simulate_skip(self, url: str, existing_path: Optional[str]) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(
            f"[{self._wall()}][{elapsed}] SIMULATE_SKIP   "
            f"DUPLICATE FOUND – skipping download\n"
            f"                        existing: {existing_path or '?'}\n"
            f"                        url:      {url}"
        )

    def simulate_ok(self, url: str, predicted_name: Optional[str]) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(
            f"[{self._wall()}][{elapsed}] SIMULATE_OK     "
            f"no conflict – proceeding with download\n"
            f"                        predicted: {predicted_name or '?'}\n"
            f"                        url:       {url}"
        )

    def program_start(self, urlfile: Path, out_dir: Path, mode: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"PROGRAM_START [{elapsed}] urlfile={urlfile} out_dir={out_dir} mode={mode}")

    def program_force_exit(self) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"FORCE_EXIT_PROGRAM [{elapsed}]")

    def controlled_stop(self, next_url_index: int, url_total: int, sentinel: Path) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(
            f"CONTROLLED_STOP [{elapsed}] next_url={next_url_index}/{url_total} sentinel={sentinel}"
        )

    def force_exit(self, url_index: int, elapsed_url_s: float, last_progress: dict | None) -> None:
        elapsed_prog = _hms_ms(time.time() - self.t0)
        elapsed_url = _hms_ms(elapsed_url_s)
        pct = last_progress.get("percent") if last_progress else None
        downloaded = last_progress.get("downloaded") if last_progress else None
        total = last_progress.get("total") if last_progress else None
        speed_bps = last_progress.get("speed_bps") if last_progress else None
        eta_s = last_progress.get("eta_s") if last_progress else None
        # format helpers
        def _fmt_bytes(b: int | None) -> str:
            if b is None:
                return "?"
            units = ["B", "KiB", "MiB", "GiB", "TiB"]
            v = float(b)
            i = 0
            while v >= 1024 and i < len(units) - 1:
                v /= 1024.0
                i += 1
            return f"{v:.2f}{units[i]}"
        def _fmt_eta(s: int | None) -> str:
            if s is None:
                return "?"
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"
        pct_s = f"{pct:.2f}%" if isinstance(pct, (int, float)) else "?%"
        sp_s = f"{_fmt_bytes(int(speed_bps))}/s" if isinstance(speed_bps, (int, float)) else "?/s"
        dl_s = _fmt_bytes(downloaded)
        tot_s = _fmt_bytes(total)
        eta_str = _fmt_eta(eta_s)
        self._write(f"[{self._wall()}][{elapsed_prog}] FORCE_EXIT [{url_index}] {pct_s} {dl_s}/{tot_s} {sp_s} ETA {eta_str} Elapsed {elapsed_url}")

    def progress(self, url_index: int, pct: float | None, downloaded: int | None,
                 total: int | None, speed_bps: float | None, eta_s: int | None) -> None:
        def _fmt_bytes(b: int | None) -> str:
            if b is None:
                return "?"
            units = ["B", "KiB", "MiB", "GiB", "TiB"]
            v = float(b)
            i = 0
            while v >= 1024 and i < len(units) - 1:
                v /= 1024.0
                i += 1
            return f"{v:.2f}{units[i]}"

        def _fmt_eta(s: int | None) -> str:
            if s is None:
                return "?"
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"

        elapsed_prog = _hms_ms(time.time() - self.t0)
        pct_s = f"{pct:.2f}%" if pct is not None else "?%"
        sp_s = f"{_fmt_bytes(int(speed_bps))}/s" if speed_bps else "?/s"
        dl_s = _fmt_bytes(downloaded)
        tot_s = _fmt_bytes(total)
        eta_str = _fmt_eta(eta_s)
        self._write(f"[{self._wall()}][{elapsed_prog}] PROGRESS [{url_index}] {pct_s} {dl_s}/{tot_s} {sp_s} ETA {eta_str}")

# ---- Runner -----------------------------------------------------------------

def _raw_log_path(raw_dir: Path, tool: str, idx: int, stem: str) -> Path:
    safe_stem = "".join(c for c in stem if c.isalnum() or c in ("-", "_"))[:80] or "item"
    return raw_dir / f"{tool}-{idx:04d}-{safe_stem}.log"

def _urlfile_stem(path: Path) -> str:
    return path.stem

def _default_outdir_for(urlfile: Path) -> Path:
    return Path("./stars") / _urlfile_stem(urlfile)

def _extract_video_id(url: str) -> str:
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        if 'pornhub.com' in (p.netloc or ''):
            # viewkey param
            qs = {}
            for part in (p.query or '').split('&'):
                if '=' in part:
                    k,v = part.split('=',1)
                    qs[k]=v
            return qs.get('viewkey') or ''
        if 'eporner.com' in (p.netloc or ''):
            path = p.path or ''
            # patterns: /video-<ID>/<slug>/ or /hd-porn/<ID>/<slug>/
            for token in path.split('/'):
                if '-' in token and token.strip():
                    return token
            return ''
        if 'aebn.com' in (p.netloc or ''):
            # look for #scene-<id>
            frag = p.fragment or ''
            if 'scene-' in frag:
                try:
                    return frag.split('scene-')[1]
                except Exception:
                    return ''
        return ''
    except Exception:
        return ''

def _format_selector_for_height(height: int) -> str:
    # Prefer best video/audio up to the requested height; fallback to global best.
    return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"


def _find_stem_in_dir(stem: str, directory: Path) -> Optional[Path]:
    """Return the first file in *directory* whose stem matches *stem* (case-insensitive).

    Used to detect same-content files regardless of container extension
    (e.g. canonical has .webm, proxy is downloading .mp4 with the same title).
    Returns None if the directory doesn't exist or no match is found.
    """
    try:
        stem_lower = stem.lower()
        for p in directory.iterdir():
            if p.is_file() and p.stem.lower() == stem_lower:
                return p
    except Exception:
        pass
    return None




def _format_archive_line(status: str, elapsed_s: float, when: str, downloaded_mib: float, video_id: str, url: str) -> str:
    return "	".join([
        status,
        f"{elapsed_s:.3f}",
        when,
        f"{downloaded_mib:.2f}MiB",
        video_id or '',
        url,
    ])


ARCHIVE_PROCESSED_STATUSES = {"downloaded", "already", "preexisting"}


def _archive_status_rank(status: str) -> int:
    return 2 if status.lower() in ARCHIVE_PROCESSED_STATUSES else 1


def _merge_archive_status(statuses: Dict[str, str], url: str, status: str) -> None:
    normalized_status = status.strip().lower()
    if not url or not normalized_status:
        return
    previous = statuses.get(url)
    if previous is None or _archive_status_rank(normalized_status) > _archive_status_rank(previous):
        statuses[url] = normalized_status


def _ensure_archive_line_has_url(line: str, url: str) -> str:
    if not line.strip():
        return ''
    parts = line.split('	')
    if len(parts) < 6:
        parts = (parts + [''] * 6)[:6]
    parts[5] = url
    return '	'.join(parts)


def _archive_prefix_for(path: Path) -> str:
    return "ae" if "ae-stars" in str(path.parent) else "yt"


def _parse_archive_line(line: str) -> Optional[Tuple[str, str]]:
    if not line.strip():
        return None
    parts = line.rstrip("\n").split("	")
    if not parts:
        return None
    status = parts[0].strip().lower()
    url = parts[-1].strip() if len(parts) >= 6 else ""
    if not status or not url:
        return None
    return status, url


def _read_archive_statuses(archive_file: Path, source_urls: List[str]) -> Tuple[Dict[str, str], List[str], bool]:
    statuses: Dict[str, str] = {}
    normalized_lines: List[str] = []
    changed = False
    try:
        raw_lines = archive_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return statuses, normalized_lines, changed

    for idx, line in enumerate(raw_lines):
        if not line.strip():
            continue
        normalized = line
        parsed = _parse_archive_line(line)
        if parsed is None and idx < len(source_urls):
            normalized = _ensure_archive_line_has_url(line, source_urls[idx])
            parsed = _parse_archive_line(normalized)
            changed = changed or normalized != line
        normalized_lines.append(normalized)
        if parsed:
            status, url = parsed
            _merge_archive_status(statuses, url, status)
    return statuses, normalized_lines, changed


def _locked_append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import msvcrt  # type: ignore
    except Exception:
        msvcrt = None  # type: ignore
    try:
        import fcntl  # type: ignore
    except Exception:
        fcntl = None  # type: ignore
    with path.open("a", encoding="utf-8") as fh:
        try:
            if msvcrt and os.name == "nt":
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1_000_000)
            elif fcntl and os.name != "nt":
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        try:
            fh.write(line + "\n")
            fh.flush()
        finally:
            try:
                if msvcrt and os.name == "nt":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1_000_000)
                elif fcntl and os.name != "nt":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _ytdlp_exe() -> List[str]:
    """Return the yt-dlp command prefix that uses the same Python env as ytaedl.

    Using sys.executable ensures the venv's yt-dlp is always invoked, even
    when the shell PATH resolves to a different (global) yt-dlp binary.
    """
    return [sys.executable, "-m", "yt_dlp"]


def _ytdlp_auth_args(
    cookies_from_browser: Optional[str] = "firefox",
    impersonate: Optional[str] = "chrome",
) -> List[str]:
    """Return yt-dlp args for cookie/TLS auth that bypass bot-detection."""
    args: List[str] = []
    if cookies_from_browser and cookies_from_browser.lower() not in ("none", ""):
        args += ["--cookies-from-browser", cookies_from_browser]
    if impersonate and impersonate.lower() not in ("none", ""):
        args += ["--impersonate", impersonate]
    return args


def _build_ytdlp_cmd(
    urls: List[str],
    out_dir: Path,
    max_mibs: Optional[float] = None,
    max_height: Optional[int] = None,
    temp_dir: Optional[Path] = None,
    grid_config: Optional[dict] = None,
    cookies_from_browser: Optional[str] = "firefox",
    impersonate: Optional[str] = "chrome",
    ytdlp_downloader: Optional[str] = "aria2c",
) -> List[str]:
    # no --print; --newline ensures line-terminated progress
    cmd = [
        *_ytdlp_exe(),
        "--newline",
        "-o", str(out_dir / "%(title)s.%(ext)s"),
    ]
    cmd += _ytdlp_auth_args(cookies_from_browser, impersonate)
    # grid_config can override the downloader; only apply default if grid doesn't specify one
    _grid_overrides_downloader = grid_config and grid_config.get("downloader")
    if not _grid_overrides_downloader and ytdlp_downloader and ytdlp_downloader.lower() not in ("native", ""):
        cmd += ["--downloader", ytdlp_downloader]
    if isinstance(max_mibs, (int, float)) and max_mibs and max_mibs > 0:
        rate_arg = f"{max_mibs:.2f}M"
        cmd += ["--limit-rate", rate_arg]
    if isinstance(max_height, int) and max_height > 0:
        cmd += ["--format", _format_selector_for_height(max_height)]
    if grid_config:
        cmd += yt_grid.build_ytdlp_grid_args(grid_config, allow_format=not (isinstance(max_height, int) and max_height > 0))
    if temp_dir:
        cmd += ["--paths", f"temp:{temp_dir}"]
    cmd += [*urls]
    return cmd


SHORT_PREVIEW_MAX_SECONDS = 95.0


def _probe_media_duration_s(path: Path) -> Optional[float]:
    """Return media duration from ffprobe, or None when probing is unavailable."""
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return None
    except OSError:
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _is_raw_media_variant_name(value: str) -> bool:
    stem = Path(unquote(value)).stem.lower()
    if not stem:
        return False
    if re.search(r"(?:^|[_-])(?:hq|lq|pv)$", stem):
        return True
    # Raw CDN media names are commonly just an opaque video id.  Human titles
    # have spaces/punctuation and should not match this fallback guard.
    return (
        re.fullmatch(r"\d{4,}(?:[-_]\d+)?", stem) is not None
        or re.fullmatch(r"[a-z0-9]{8,}", stem) is not None
    )


def _safe_fallback_filename_stem(value: str) -> str:
    stem = unquote(value).strip()
    stem = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", stem)
    stem = re.sub(r"[\s._-]+", " ", stem).strip(" ._-")
    return stem[:140].strip() or "download"


def _identifier_from_path_part(part: str) -> str:
    lowered = part.lower()
    if re.fullmatch(r"\d{3,}", lowered):
        return part
    match = re.fullmatch(r"(?:video|watch|movie|movies|hdporn)[-_]?([a-z0-9]{5,})", lowered)
    if match:
        return match.group(1)
    return ""


def _fallback_filename_stem_for_url(url: str) -> str:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    generic_parts = {"video", "videos", "watch", "embed", "player", "view_video.php", "index.php"}

    for idx in range(len(path_parts) - 1, -1, -1):
        part = path_parts[idx]
        lowered = part.lower()
        if lowered in generic_parts:
            continue
        if re.fullmatch(r"\d+", lowered):
            continue
        if "." in lowered and lowered.rsplit(".", 1)[-1] in {"php", "html", "htm", "aspx"}:
            continue
        prefix = ""
        if idx > 0:
            identifier = _identifier_from_path_part(path_parts[idx - 1])
            if identifier and not lowered.startswith(identifier.lower()):
                prefix = f"{identifier} "
        return _safe_fallback_filename_stem(prefix + part)

    query = dict((k.lower(), v[-1]) for k, v in parse_qs(parsed.query).items() if v)
    for key in ("q", "search", "query", "viewkey", "v", "id"):
        if query.get(key):
            return _safe_fallback_filename_stem(query[key])

    host = parsed.netloc.lower().removeprefix("www.")
    return _safe_fallback_filename_stem(f"{host} {parsed.path or parsed.query or 'download'}")


def _fallback_output_template_for_url(url: str, out_dir: Path) -> Path:
    return out_dir / f"{_fallback_filename_stem_for_url(url)}.%(ext)s"


def _looks_like_preview_source(candidate_url: str, destination: Optional[Path]) -> bool:
    lowered = candidate_url.lower()
    parsed = urlparse(candidate_url)
    path_name = Path(unquote(parsed.path)).name
    query = parsed.query.lower()
    if any(token in lowered for token in ("/preview", "/trailer", "/teaser", "/sample", "/pv/")):
        return True
    if "ispreview=true" in query:
        return True
    if _is_raw_media_variant_name(path_name):
        return True
    if destination is not None and _is_raw_media_variant_name(destination.name):
        return True
    return False


def _temp_sibling_for_destination(destination: Path) -> Optional[Path]:
    if destination.name.lower().endswith(".mp4.temp"):
        return destination
    candidate = destination.with_name(destination.name + ".temp")
    if candidate.name.lower().endswith(".mp4.temp"):
        return candidate
    return None


def _promote_finished_temp_file(temp_path: Path) -> Optional[Path]:
    """Promote or remove a completed ``.mp4.temp`` file when it is probeable."""
    if not temp_path.name.lower().endswith(".mp4.temp"):
        return None
    final_path = temp_path.with_name(temp_path.name[:-5])
    if final_path.exists():
        if _probe_media_duration_s(temp_path) is not None and _probe_media_duration_s(final_path) is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        return None
    if _probe_media_duration_s(temp_path) is None:
        return None
    try:
        temp_path.replace(final_path)
        return final_path
    except OSError:
        return None


def _promote_finished_temp_sibling(destination: Optional[Path]) -> Optional[Path]:
    if destination is None:
        return None
    temp_path = _temp_sibling_for_destination(destination)
    if temp_path is None or not temp_path.exists():
        return None
    return _promote_finished_temp_file(temp_path)


def _promote_finished_temp_files(directory: Path) -> List[Path]:
    promoted: List[Path] = []
    try:
        entries = list(directory.glob("*.mp4.temp"))
    except OSError:
        return promoted
    for temp_path in entries:
        final_path = _promote_finished_temp_file(temp_path)
        if final_path is not None:
            promoted.append(final_path)
    return promoted


def _reject_short_preview_candidate(candidate_url: str, destination: Optional[Path]) -> tuple[bool, Optional[float], Optional[Path]]:
    """Return True for a downloaded fallback candidate that is probably a preview clip."""
    promoted = _promote_finished_temp_sibling(destination)
    path = promoted or destination
    if path is None:
        return False, None, None
    if path.name.lower().endswith(".mp4.temp"):
        final_path = _promote_finished_temp_file(path)
        path = final_path or path
    duration_s = _probe_media_duration_s(path)
    if duration_s is None:
        return False, None, path
    if duration_s <= SHORT_PREVIEW_MAX_SECONDS and _looks_like_preview_source(candidate_url, path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        return True, duration_s, path
    return False, duration_s, path


def _extract_aebn_scene_id(url: str) -> str:
    """Return the AEBN scene ID from a URL fragment like #scene-1310191, or empty string."""
    try:
        from urllib.parse import urlparse
        frag = urlparse(url).fragment or ""
        if "scene-" in frag:
            return frag.split("scene-")[1].strip()
    except Exception:
        pass
    return ""


# Movie-level scene-list cache: {movie_url_without_fragment: [(ordinal, scene_id), ...]}
_aebn_scene_list_cache: dict[str, list[tuple[int, str]]] = {}


def _aebn_scene_ordinal(url: str) -> Optional[int]:
    """Resolve an AEBN scene URL fragment (#scene-XXXXXXXX) to its 1-based ordinal position.

    Makes one HTTP request per unique movie URL (cached for the process lifetime).
    Returns None if the URL has no scene fragment, the lookup fails, or the scene is not found.
    """
    scene_id = _extract_aebn_scene_id(url)
    if not scene_id:
        return None
    movie_url = url.split("#")[0]
    scenes = _aebn_scene_list_cache.get(movie_url)
    if scenes is None:
        try:
            from aebn_dl.custom_session import CustomSession as _AEBNSession
            from lxml import html as _lhtml
            _s = _AEBNSession(impersonate="chrome")
            _s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            })
            _s.cookies.update({"ageGated": "true", "terms": "true"})
            _resp = _s.get(movie_url, timeout=15)
            _content = _lhtml.fromstring(_resp.content)
            _sections = _content.xpath('//section[@id[starts-with(., "scene-")]]')
            scenes = [(i, sec.get("id", "").replace("scene-", "", 1)) for i, sec in enumerate(_sections, start=1)]
        except Exception:
            scenes = []
        _aebn_scene_list_cache[movie_url] = scenes
    for ordinal, sid in scenes:
        if sid == scene_id:
            return ordinal
    return None


def _build_aebndl_cmd(
    url: str,
    out_dir: Path,
    work_dir: Path,
    max_height: Optional[int] = None,
    scene: Optional[int] = None,
) -> List[str]:
    # Keep default logging level (INFO) to have progress; do NOT pass -c by default
    cmd = ["aebndl", "--json", "-o", str(out_dir), "-w", str(work_dir)]
    if isinstance(max_height, int) and max_height >= 0:
        cmd += ["-r", str(max_height)]
    if isinstance(scene, int) and scene >= 1:
        cmd += ["-s", str(scene)]
    cmd.append(url)
    return cmd
def _coerce_progress_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if any(ch in s for ch in (".", "e", "E")):
                return float(s)
            return int(s)
        except Exception:
            return None
    return None


def _active_stall_seconds(stall_seconds: int | None) -> Optional[int]:
    if not stall_seconds or stall_seconds <= 0:
        return None
    return max(30, int(stall_seconds) * 5)


def _aebn_pre_transfer_stall_seconds(stall_seconds: int | None) -> Optional[int]:
    if not stall_seconds or stall_seconds <= 0:
        return None
    return max(120, int(stall_seconds) * 30)



def _clamp_progress(evt: dict, *, terminal: bool = False) -> dict:
    """Normalize progress values without trusting impossible in-flight totals."""
    if evt.get("event") != "progress":
        return evt

    clamped = evt.copy()
    dl_raw = _coerce_progress_number(evt.get("downloaded"))
    tot_raw = _coerce_progress_number(evt.get("total"))
    pct_raw = _coerce_progress_number(evt.get("percent"))
    speed_raw = _coerce_progress_number(evt.get("speed_bps"))

    dl = int(dl_raw) if isinstance(dl_raw, (int, float)) else None
    tot = int(tot_raw) if isinstance(tot_raw, (int, float)) else None
    pct = float(pct_raw) if isinstance(pct_raw, (int, float)) else None
    speed = float(speed_raw) if isinstance(speed_raw, (int, float)) else None

    if dl is not None:
        clamped["downloaded"] = dl
    if tot is not None:
        clamped["total"] = tot
    if speed is not None:
        clamped["speed_bps"] = speed

    if not terminal and dl is not None and tot is not None and tot > 0 and dl >= tot:
        clamped["total"] = None
        clamped["percent"] = None
        clamped["eta_s"] = None
        clamped["unreliable_total"] = True
    elif dl is not None and tot is not None and tot > 0:
        clamped["total"] = tot
        pct_calc = (dl / tot) * 100.0
        pct_value = min(100.0, max(0.0, pct_calc))
        clamped["percent"] = pct_value
    elif pct is not None:
        pct_value = min(100.0, max(0.0, pct))
        if not terminal and pct_value >= 100.0:
            clamped["percent"] = None
            clamped["eta_s"] = None
            clamped["unreliable_total"] = True
            return clamped
        clamped["percent"] = pct_value

    return clamped


@dataclass
class _ProgressActivity:
    stall_seconds: int | None
    complete_stall_seconds: int
    started_at: float
    last_real_event_t: float
    pre_transfer_stall_seconds: Optional[int] = None
    last_progress_event_t: Optional[float] = None
    last_progress_growth_t: Optional[float] = None
    last_progress_bytes: Optional[int] = None
    active_started: bool = False
    near_complete_since: Optional[float] = None
    last_mux_activity_t: Optional[float] = None

    @property
    def active_stall_seconds(self) -> Optional[int]:
        return _active_stall_seconds(self.stall_seconds)

    def observe(self, evt: dict, now: float) -> None:
        ev = evt.get("event")
        if ev != "heartbeat":
            self.last_real_event_t = now

        # aebndl emits segments_complete when all segment downloads finish and
        # concat/mux is about to begin. Switch to mux-liveness tracking:
        # last_mux_activity_t is updated by every event and heartbeat from here on,
        # so complete_stall_seconds measures inactivity (process silent/dead) rather
        # than total mux wall time.
        if ev == "segments_complete":
            self.last_progress_growth_t = now
            if self.near_complete_since is None:
                self.near_complete_since = now
            self.last_mux_activity_t = now
            return

        # During mux phase, any sign of process life (including heartbeats, which
        # stream.py emits every 0.5 s while the subprocess stdout is open) resets
        # the inactivity timer.  This lets mux run indefinitely as long as aebndl
        # is alive, and only fires complete_stall_seconds after true process death
        # or a genuine hang where stdout closes.
        if self.near_complete_since is not None:
            self.last_mux_activity_t = now
            if ev == "heartbeat":
                return

        if ev != "progress":
            return

        self.last_progress_event_t = now
        dl_raw = _coerce_progress_number(evt.get("downloaded"))
        pct_raw = _coerce_progress_number(evt.get("percent"))
        speed_raw = _coerce_progress_number(evt.get("speed_bps"))
        dl = int(dl_raw) if isinstance(dl_raw, (int, float)) else None
        pct = float(pct_raw) if isinstance(pct_raw, (int, float)) else None
        speed = float(speed_raw) if isinstance(speed_raw, (int, float)) else None

        if dl is not None or (speed is not None and speed > 0):
            if not self.active_started:
                self.active_started = True
                self.last_progress_growth_t = now

        if dl is not None:
            if self.last_progress_bytes is None or dl > self.last_progress_bytes:
                self.last_progress_growth_t = now
            self.last_progress_bytes = max(dl, self.last_progress_bytes or 0)

        if speed is not None and speed > 0 and (pct is None or pct < 99.0):
            self.last_progress_growth_t = now

        if isinstance(pct, (int, float)) and pct >= 99.0:
            if self.near_complete_since is None:
                self.near_complete_since = now
        else:
            self.near_complete_since = None

    def stall(self, now: float) -> Optional[tuple[int, str]]:
        if self.near_complete_since is not None and self.complete_stall_seconds > 0:
            # Use last_mux_activity_t (liveness-based: reset on every heartbeat/event
            # while muxing) when available; fall back to near_complete_since for
            # downloads that entered near-complete before this field existed.
            mux_ref = self.last_mux_activity_t if self.last_mux_activity_t is not None else self.near_complete_since
            if (now - mux_ref) > self.complete_stall_seconds:
                return self.complete_stall_seconds, "near_complete_stall"

        if not self.stall_seconds or self.stall_seconds <= 0:
            return None

        if not self.active_started:
            pre_transfer_stall_s = self.pre_transfer_stall_seconds or int(self.stall_seconds)
            if (now - self.last_real_event_t) > pre_transfer_stall_s:
                return int(pre_transfer_stall_s), "pre_transfer_no_output"
            return None

        active_stall_s = self.active_stall_seconds
        if active_stall_s and self.last_progress_growth_t is not None:
            if self.near_complete_since is None and (now - self.last_progress_growth_t) > active_stall_s:
                return active_stall_s, "active_no_byte_growth"
        return None

def _emit_json(d: dict) -> None:
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _attempt_id(worker_slot: int, url_index: int, phase: str, ordinal: int = 1) -> str:
    slot = worker_slot if isinstance(worker_slot, int) and worker_slot > 0 else 0
    return f"w{slot:02d}:u{url_index}:{phase}:{ordinal}"


def _stop_sentinel_active(path: Optional[Path]) -> bool:
    if not path:
        return False
    try:
        return path.exists()
    except Exception:
        return False


@dataclass
class _SimulateResult:
    is_duplicate: bool
    existing_path: Optional[str] = None
    predicted_name: Optional[str] = None
    timed_out: bool = False


def _simulate_check(
    url: str,
    canonical_out_dirs: "list[Path]",
    *,
    timeout_seconds: int = 15,
    cookies_from_browser: Optional[str] = "firefox",
    impersonate: Optional[str] = "chrome",
) -> _SimulateResult:
    """Run yt-dlp --simulate to predict filename/size and check for an existing duplicate.

    Checks every directory in *canonical_out_dirs* (exact match then stem match).
    Returns a ``_SimulateResult`` indicating whether the file already exists.
    If yt-dlp --simulate fails (unsupported site, network error, etc.) returns
    ``is_duplicate=False`` so the caller proceeds with the normal download.
    """
    try:
        proc = subprocess.Popen(
            [
                *_ytdlp_exe(),
                "--simulate",
                "--print", "%(title)s.%(ext)s",
                "--print", "%(filesize,filesize_approx)s",
                *_ytdlp_auth_args(cookies_from_browser, impersonate),
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return _SimulateResult(is_duplicate=False, timed_out=True)

        if proc.returncode != 0:
            return _SimulateResult(is_duplicate=False)

        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        if not lines:
            return _SimulateResult(is_duplicate=False)

        predicted_name = lines[0]
        raw_size = lines[1] if len(lines) > 1 else "NA"
        try:
            predicted_size = int(raw_size)
        except (ValueError, TypeError):
            predicted_size = None

        # Check all canonical dirs in order
        for canonical_out_dir in canonical_out_dirs:
            predicted_file = canonical_out_dir / predicted_name

            # Exact filename match
            if predicted_file.exists():
                if predicted_size is None:
                    return _SimulateResult(is_duplicate=True, existing_path=str(predicted_file),
                                           predicted_name=predicted_name)
                existing_size = predicted_file.stat().st_size
                # Allow 1% tolerance to handle minor muxing size differences
                if predicted_size > 0 and abs(existing_size - predicted_size) / predicted_size <= 0.01:
                    return _SimulateResult(is_duplicate=True, existing_path=str(predicted_file),
                                           predicted_name=predicted_name)
                # File exists but sizes differ significantly in this root. Keep
                # checking later canonical roots before declaring no duplicate.
                continue

            # Stem match (same video, different container e.g. .webm vs .mp4)
            stem_match = _find_stem_in_dir(Path(predicted_name).stem, canonical_out_dir)
            if stem_match is not None:
                if predicted_size is None:
                    return _SimulateResult(is_duplicate=True, existing_path=str(stem_match),
                                           predicted_name=predicted_name)
                existing_size = stem_match.stat().st_size
                if predicted_size > 0 and abs(existing_size - predicted_size) / predicted_size <= 0.01:
                    return _SimulateResult(is_duplicate=True, existing_path=str(stem_match),
                                           predicted_name=predicted_name)

        return _SimulateResult(is_duplicate=False, predicted_name=predicted_name)

    except Exception:
        return _SimulateResult(is_duplicate=False)


def _is_abort_rc(rc: int) -> bool:
    """True only for explicit user/program stop signals that should bypass the extdl fallback.

    rc=124 (stall/timeout) is intentionally excluded: a stalled yt-dlp download means yt-dlp
    could not fetch the video, which is exactly the case where the static-HTML and browser-
    capture fallbacks should be attempted.
    """
    return rc in (130, 131)


def _run_extdl_fallback(
    url: str,
    out_dir: Path,
    url_index: int,
    *,
    extdl_max_candidates: int = 5,
    extdl_browser_wait: float = 12.0,
    extdl_capture_browser: str = "auto",
    yt_dlp_executable: Optional[List[str]] = None,
    max_dl_speed: Optional[float] = None,
    max_height: Optional[int] = None,
    dry_run: bool = False,
    proglog: Optional["ProgLogger"] = None,
    first_attempt_num: int = 2,
    stall_seconds: int | None = None,
    attempt_prefix: str = "",
) -> tuple[int, Optional[dict]]:
    """Try Method 2 (static HTML) then Method 3 (Playwright) for *url*.

    Emits ``fallback_*`` NDJSON events for the manager TUI and, when *proglog*
    is provided, writes each attempt and its result to the worker's prog log.
    Returns 0 on any successful download, non-zero if all methods exhausted.
    """
    # Load extdl by file path so it works whether downloader.py is run as a
    # standalone script (subprocess mode) or imported as part of the package.
    # A plain `from . import extdl` fails in standalone mode because there is
    # no parent package context.
    _yt_exe = yt_dlp_executable if yt_dlp_executable is not None else _ytdlp_exe()
    try:
        import importlib.util as _ilu
        _extdl_path = Path(__file__).parent / "extdl.py"
        _spec = _ilu.spec_from_file_location("ytaedl_extdl", _extdl_path)
        assert _spec is not None and _spec.loader is not None
        _extdl = _ilu.module_from_spec(_spec)
        # Register before exec so Python 3.12 dataclass __module__ lookup succeeds
        import sys as _sys
        _sys.modules.setdefault("ytaedl_extdl", _extdl)
        _spec.loader.exec_module(_extdl)  # type: ignore[union-attr]
    except Exception as _load_exc:
        msg = f"extdl could not be loaded: {_load_exc}"
        fallback_attempt_id = f"{attempt_prefix}:fallback:load" if attempt_prefix else None
        _emit_json({"event": "fallback_skip", "method": "all", "reason": msg,
                    "url_index": url_index, "url": url,
                    **({"attempt_id": fallback_attempt_id} if fallback_attempt_id else {})})
        if proglog:
            proglog.fallback_skip("all", msg)
        return 1, None

    referer = url
    try:
        origin = _extdl.infer_origin(url)
    except Exception:
        origin = ""

    # Running attempt counter across all methods, starting from first_attempt_num
    # so the log mirrors ytdlp-extdl.py's "Attempt 1 / Attempt 2 / …" framing.
    _global_attempt = [first_attempt_num - 1]
    output_template = _fallback_output_template_for_url(url, out_dir)

    def _try_candidates(candidates, method_name: str) -> tuple[int, Optional[dict]]:
        limited = candidates[:extdl_max_candidates] if extdl_max_candidates > 0 else candidates
        for idx_in_method, candidate in enumerate(limited, start=1):
            _global_attempt[0] += 1
            global_num = _global_attempt[0]
            candidate_attempt_id = (
                f"{attempt_prefix}:fallback:{global_num}"
                if attempt_prefix
                else f"fallback:{url_index}:{global_num}"
            )
            _emit_json({
                "event": "fallback_attempt",
                "attempt_id": candidate_attempt_id,
                "method": method_name,
                "attempt": idx_in_method,
                "total": len(limited),
                "kind": candidate.kind,
                "candidate_url": candidate.url,
                "url_index": url_index,
                "url": url,
            })
            if proglog:
                proglog.attempt_start(
                    global_num,
                    f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}",
                )
                proglog.fallback_attempt(
                    method_name, idx_in_method, len(limited),
                    candidate.kind, candidate.url,
                )
            cmd = _extdl.build_yt_dlp_command_for_candidate(
                candidate.url,
                out_dir=out_dir,
                referer=referer,
                origin=origin,
                yt_dlp_executable=_yt_exe,
                max_dl_speed=max_dl_speed,
                max_height=max_height,
                output_template=output_template,
            )
            if dry_run:
                import shlex
                _emit_json({"event": "fallback_dryrun", "method": method_name,
                            "attempt_id": candidate_attempt_id,
                            "attempt": idx_in_method, "cmd": shlex.join(cmd),
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.fallback_result(method_name, idx_in_method, len(limited), 0)
                    proglog.attempt_success(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}")
                return 0, None
            candidate_last_progress: Optional[dict] = None
            candidate_destination: Optional[Path] = None
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                )
                assert proc.stdout is not None
                # Parse yt-dlp's --newline output via procparsers so the manager
                # receives live progress events (speed, %, ETA) for fallback downloads.
                try:
                    _cand_now = time.time()
                    _cand_activity = _ProgressActivity(
                        stall_seconds=stall_seconds,
                        complete_stall_seconds=120,
                        started_at=_cand_now,
                        last_real_event_t=_cand_now,
                    )
                    _cand_stall_s = _active_stall_seconds(stall_seconds) or 120
                    _cand_stall_reason = "pre_transfer_no_output"
                    _cand_stalled = False
                    for evt in iter_parsed_events("yt-dlp", proc.stdout,
                                                  raw_log_path=None, heartbeat_secs=0.2):
                        _cand_now = time.time()
                        ev = evt.get("event")
                        if ev == "progress":
                            evt = _clamp_progress(evt)
                            evt["attempt_id"] = candidate_attempt_id
                            candidate_last_progress = evt
                        _cand_activity.observe(evt, _cand_now)
                        if ev == "progress":
                            _emit_json({**evt, "downloader": "yt-dlp",
                                        "attempt_id": candidate_attempt_id,
                                        "url_index": url_index, "url": url})
                        elif ev == "already":
                            # Candidate URL already downloaded — treat as success
                            rc = 0
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            break
                        elif ev in ("destination", "finish"):
                            if ev == "destination" and evt.get("path"):
                                try:
                                    candidate_destination = Path(str(evt.get("path"))).expanduser().resolve()
                                except Exception:
                                    candidate_destination = Path(str(evt.get("path"))).expanduser()
                            _emit_json({**evt, "downloader": "yt-dlp",
                                        "attempt_id": candidate_attempt_id,
                                        "url_index": url_index, "url": url})
                        stalled = _cand_activity.stall(_cand_now)
                        if stalled is not None:
                            _cand_stall_s, _cand_stall_reason = stalled
                            _cand_stalled = True
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            break
                except Exception:
                    # procparsers unavailable or parse error — drain silently
                    try:
                        for _ in proc.stdout:
                            pass
                    except Exception:
                        pass
                if _cand_stalled:
                    _emit_json({"event": "fallback_stalled", "method": method_name,
                                "attempt_id": candidate_attempt_id,
                                "attempt": idx_in_method, "stall_seconds": _cand_stall_s,
                                "reason": _cand_stall_reason,
                                "url_index": url_index, "url": url})
                try:
                    rc = proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    rc = 124
            except Exception as exc:
                rc = 1
                _emit_json({"event": "fallback_failure", "method": method_name,
                            "attempt_id": candidate_attempt_id,
                            "attempt": idx_in_method, "rc": rc, "error": str(exc),
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.fallback_result(method_name, idx_in_method, len(limited), rc)
                    proglog.attempt_fail(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}", f"exception: {exc}")
                continue
            if proglog:
                proglog.fallback_result(method_name, idx_in_method, len(limited), rc)
            if rc == 0:
                rejected, duration_s, rejected_path = _reject_short_preview_candidate(candidate.url, candidate_destination)
                if rejected:
                    _emit_json({
                        "event": "fallback_rejected",
                        "method": method_name,
                        "attempt_id": candidate_attempt_id,
                        "attempt": idx_in_method,
                        "reason": "short_preview_duration",
                        "duration_s": duration_s,
                        "path": str(rejected_path) if rejected_path else None,
                        "candidate_url": candidate.url,
                        "url_index": url_index,
                        "url": url,
                    })
                    if proglog:
                        proglog.attempt_fail(
                            global_num,
                            f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}",
                            f"rejected short preview ({duration_s:.1f}s)",
                        )
                    continue
                if candidate_last_progress is None:
                    candidate_last_progress = {"attempt_id": candidate_attempt_id}
                if candidate_destination is not None:
                    promoted_path = _promote_finished_temp_sibling(candidate_destination)
                    if promoted_path is not None:
                        _emit_json({
                            "event": "temp_promoted",
                            "attempt_id": candidate_attempt_id,
                            "path": str(promoted_path),
                            "url_index": url_index,
                            "url": url,
                        })
                _emit_json({"event": "fallback_success", "method": method_name,
                            "attempt_id": candidate_attempt_id,
                            "attempt": idx_in_method, "candidate_url": candidate.url,
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.attempt_success(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}")
                return 0, candidate_last_progress
            _emit_json({"event": "fallback_failure", "method": method_name,
                        "attempt_id": candidate_attempt_id,
                        "attempt": idx_in_method, "rc": rc,
                        "url_index": url_index, "url": url})
            if proglog:
                proglog.attempt_fail(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}", f"exit code {rc}")
        return 1, None

    # Method 2: static HTML scan
    static_attempt_id = f"{attempt_prefix}:fallback:static_html" if attempt_prefix else f"fallback:{url_index}:static_html"
    _emit_json({"event": "fallback_start", "method": "static_html",
                "attempt_id": static_attempt_id, "url_index": url_index, "url": url})
    if proglog:
        proglog.fallback_start("static_html")
    try:
        static_candidates = _extdl.discover_static_media_candidates(url)
    except Exception as exc:
        static_candidates = []
        _emit_json({"event": "fallback_failure", "method": "static_html", "rc": -1,
                    "attempt_id": static_attempt_id, "error": str(exc), "url_index": url_index, "url": url})

    if static_candidates:
        static_rc, static_progress = _try_candidates(static_candidates, "static_html")
        if static_rc == 0:
            return 0, static_progress

    # Method 3: Playwright browser capture
    browser_attempt_id = f"{attempt_prefix}:fallback:browser" if attempt_prefix else f"fallback:{url_index}:browser"
    _emit_json({"event": "fallback_start", "method": "browser",
                "attempt_id": browser_attempt_id, "url_index": url_index, "url": url})
    if proglog:
        proglog.fallback_start("browser_network")
    try:
        browser_candidates = _extdl.discover_browser_media_candidates(
            url,
            wait_seconds=extdl_browser_wait,
            capture_browser=extdl_capture_browser,
        )
    except RuntimeError as exc:
        msg = str(exc)
        _emit_json({"event": "fallback_skip", "method": "browser",
                    "attempt_id": browser_attempt_id, "reason": msg, "url_index": url_index, "url": url})
        if proglog:
            proglog.fallback_skip("browser_network", msg)
        browser_candidates = []
    except Exception as exc:
        _emit_json({"event": "fallback_failure", "method": "browser", "rc": -1,
                    "attempt_id": browser_attempt_id, "error": str(exc), "url_index": url_index, "url": url})
        browser_candidates = []

    if browser_candidates:
        browser_rc, browser_progress = _try_candidates(browser_candidates, "browser_network")
        if browser_rc == 0:
            return 0, browser_progress

    exhausted_attempt_id = f"{attempt_prefix}:fallback:exhausted" if attempt_prefix else f"fallback:{url_index}:exhausted"
    _emit_json({"event": "fallback_exhausted", "attempt_id": exhausted_attempt_id, "url_index": url_index, "url": url})
    if proglog:
        proglog.fallback_exhausted()
    return 1, None


def _run_one(
    tool: str,
    urls: List[str],
    out_dir: Path,
    canonical_out_dir: Path,
    partial_root: Path,
    raw_dir: Path,
    url_index: int,
    proglog: ProgLogger,
    timeout: Optional[int],
    retries: int,
    quiet: bool,
    dry_run: bool,
    progress_freq_s: Optional[int],
    max_ndjson_rate: float,
    extra_canonical_dirs: Optional[List[Path]] = None,
    stall_seconds: int | None = None,
    program_deadline: float | None = None,
    max_dl_speed: Optional[float] = None,
    max_height: Optional[int] = None,
    complete_stall_seconds: int = 300,
    extdl_fallback: bool = True,
    extdl_max_candidates: int = 5,
    extdl_browser_wait: float = 12.0,
    extdl_capture_browser: str = "auto",
    skip_simulate_check: bool = False,
    ytdlp_grid_config: Optional[dict] = None,
    worker_slot: int = 0,
    url_file_path: str = "",
    url_line_num: int = 0,
    ytdlp_cookies_from_browser: Optional[str] = "firefox",
    ytdlp_impersonate: Optional[str] = "chrome",
    ytdlp_downloader: Optional[str] = "aria2c",
) -> tuple[int, dict]:
    """
    Returns rc (0 on success). Emits NDJSON to stdout during run.

    ``partial_root`` is the ``_partial/`` directory for this channel.  A
    per-URL subdirectory ``partial_root/<hash>/`` is created before the
    download starts and deleted on success.
    """
    assert len(urls) == 1
    url = urls[0]
    stem = _urlfile_stem(Path(url))
    simulate_attempt_id = _attempt_id(worker_slot, url_index, "simulate", 1)
    normal_attempt_id = _attempt_id(worker_slot, url_index, "normal", 1)
    active_attempt_id = normal_attempt_id

    # Per-URL isolated working directory for yt-dlp temp files / aebndl segments
    url_work_dir = _partial_utils.partial_dir_for(url, partial_root)
    if not dry_run:
        url_work_dir.mkdir(parents=True, exist_ok=True)
        _partial_utils.write_partial_meta(
            url_work_dir,
            url=url,
            file_path=url_file_path,
            line_num=url_line_num,
            slot=worker_slot,
        )
        for promoted_path in _promote_finished_temp_files(out_dir):
            _emit_json({
                "event": "temp_promoted",
                "attempt_id": simulate_attempt_id,
                "path": str(promoted_path),
                "url_index": url_index,
                "url": url,
                "source": "startup",
            })

    # Pre-download simulate check: run yt-dlp --simulate to predict filename/size
    # and skip if the file already exists at the canonical destination.
    _canonical_resolved = canonical_out_dir.expanduser().resolve()
    _all_canonical_dirs = [_canonical_resolved] + [d.expanduser().resolve() for d in (extra_canonical_dirs or [])]
    if not dry_run and tool == "yt-dlp" and not skip_simulate_check:
        proglog.simulate_start(url)
        _emit_json({"event": "simulate_start", "attempt_id": simulate_attempt_id, "url_index": url_index, "url": url})
        sim = _simulate_check(url, _all_canonical_dirs,
                              cookies_from_browser=ytdlp_cookies_from_browser,
                              impersonate=ytdlp_impersonate)
        if sim.is_duplicate:
            # Clean up partial dir created before simulate check — it's unused for duplicates.
            # Without this the partial dir would leak since the early return below bypasses
            # the normal cleanup block at the end of _run_one().
            if not dry_run and url_work_dir.exists():
                try:
                    shutil.rmtree(url_work_dir)
                except Exception:
                    pass
            proglog.simulate_skip(url, sim.existing_path)
            _emit_json({
                "event": "simulate_result",
                "attempt_id": simulate_attempt_id,
                "is_duplicate": True,
                "existing_path": sim.existing_path,
                "predicted_name": sim.predicted_name,
                "url_index": url_index,
                "url": url,
            })
            _emit_json({
                "event": "canonical_duplicate",
                "attempt_id": simulate_attempt_id,
                "canonical_path": sim.existing_path,
                "url_index": url_index,
                "url": url,
                "source": "simulate_check",
            })
            _emit_json({
                "event": "finish",
                "attempt_id": simulate_attempt_id,
                "downloader": tool,
                "url_index": url_index,
                "url": url,
                "rc": 0,
                "reason": "pre-download simulate found existing canonical file",
                "elapsed_s": 0.0,
                "downloaded": None,
                "total": None,
                "already": True,
                "raw_log_path": None,
            })
            return 0, {"elapsed_s": 0.0, "downloaded": None, "total": None, "already": True, "downloader": tool}
        else:
            proglog.simulate_ok(url, sim.predicted_name)
            _emit_json({
                "event": "simulate_result",
                "attempt_id": simulate_attempt_id,
                "is_duplicate": False,
                "predicted_name": sim.predicted_name,
                "url_index": url_index,
                "url": url,
            })

    proglog.start(url_index, len(urls), url)
    if tool == "yt-dlp":
        proglog.attempt_start(1, "normal yt-dlp page download")
    t_url_start = time.time()

    canonical_out_dir = canonical_out_dir.expanduser().resolve()
    cleanup_proxy_path: Optional[Path] = None
    terminate_for_canonical_duplicate = False

    # choose command
    if tool == "aebndl":
        _scene_n = _aebn_scene_ordinal(url)
        cmd = _build_aebndl_cmd(url, out_dir, url_work_dir, max_height, scene=_scene_n)
    else:
        cmd = _build_ytdlp_cmd(
            [url],
            out_dir,
            max_dl_speed,
            max_height,
            temp_dir=url_work_dir,
            grid_config=ytdlp_grid_config,
            cookies_from_browser=ytdlp_cookies_from_browser,
            impersonate=ytdlp_impersonate,
            ytdlp_downloader=ytdlp_downloader,
        )

    _emit_json({"event": "start", "downloader": tool, "url_index": url_index, "url_total": None,
                "attempt_id": normal_attempt_id,
                "url": url, "out_dir": str(out_dir), "cmd": None,
                "ytdlp_grid_config": ytdlp_grid_config if tool == "yt-dlp" else None})

    if dry_run:
        if not quiet:
            print("DRY RUN:", " ".join(shlex.quote(x) for x in cmd))
        _emit_json({
            "event": "finish",
            "attempt_id": normal_attempt_id,
            "downloader": tool,
            "url_index": url_index,
            "url": url,
            "rc": 0,
            "reason": "dry run",
            "elapsed_s": 0.0,
            "downloaded": 0,
            "total": 0,
            "already": False,
            "raw_log_path": None,
        })
        proglog.finish(url_index, time.time() - t_url_start, "FINISH_SUCCESS")
        info = {"elapsed_s": 0.0, "downloaded": 0, "total": 0, "already": False, "downloader": tool}
        return 0, info

    # launch
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # line-buffered (still handle '\r' via reader)
        cwd=str(url_work_dir),  # redirect CWD so tools (e.g. aebndl) don't litter the launch directory
    )

    already_seen = False
    last_progress: Optional[dict] = None
    last_proglog_t = time.time()
    # rate limit for stdout NDJSON (progress events)
    min_progress_interval = 0.0 if (max_ndjson_rate is None or max_ndjson_rate < 0) else (1.0 / max_ndjson_rate if max_ndjson_rate > 0 else 0.0)
    last_emit_progress_t = 0.0
    pending_progress: Optional[dict] = None
    raw_path = _raw_log_path(raw_dir, tool, url_index, stem)
    rc: Optional[int] = None
    last_destination_path: Optional[Path] = None
    last_error_event: Optional[dict] = None
    complete_event: Optional[dict] = None

    try:
        # internal heartbeat for scheduling; also used for stall detection
        hb = 0.2 if (max_ndjson_rate is not None and max_ndjson_rate > 0) else 0.5
        activity_start = time.time()
        activity = _ProgressActivity(
            stall_seconds=stall_seconds,
            complete_stall_seconds=complete_stall_seconds,
            started_at=activity_start,
            last_real_event_t=activity_start,
            pre_transfer_stall_seconds=(
                _aebn_pre_transfer_stall_seconds(stall_seconds)
                if tool == "aebndl"
                else None
            ),
        )
        for evt in iter_parsed_events(tool, proc.stdout, raw_log_path=raw_path, heartbeat_secs=hb):
            # track 'already' to classify FINISH_DUPLICATE later for yt-dlp
            if evt.get("event") == "already":
                already_seen = True
                # Short-circuit this URL: file already exists at destination
                try:
                    proc.terminate()
                except Exception:
                    pass
                rc = 0
                # still emit the event below for downstream
            if evt.get("event") == "preview_fallback" and tool == "aebndl":
                # aebndl is about to download a preview clip instead of the full movie.
                # Reject it: kill the process and treat as a non-retryable access failure.
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 77  # "preview_only" — full delivery not available
            if evt.get("event") == "destination":
                raw_dest = evt.get("path")
                if raw_dest:
                    candidate = Path(raw_dest).expanduser().resolve()
                    last_destination_path = candidate
                    # Check all canonical dirs for an existing duplicate
                    existing = None
                    for _c_dir in _all_canonical_dirs:
                        if _c_dir != out_dir:
                            try:
                                rel = candidate.relative_to(out_dir)
                            except ValueError:
                                rel = Path(candidate.name)
                            canonical_candidate = (_c_dir / rel).resolve()
                        else:
                            canonical_candidate = candidate
                        if canonical_candidate.exists():
                            existing = canonical_candidate
                            break
                        stem_found = _find_stem_in_dir(canonical_candidate.stem, canonical_candidate.parent)
                        if stem_found is not None:
                            existing = stem_found
                            break
                    # Keep canonical_out_dir reference for the proxy-cleanup block below
                    canonical_candidate = (_all_canonical_dirs[0] / candidate.name).resolve()
                    if existing is not None:
                        already_seen = True
                        _emit_json({
                            "event": "canonical_duplicate",
                            "attempt_id": active_attempt_id,
                            "canonical_path": str(existing),
                            "proxy_path": str(candidate),
                            "url_index": url_index,
                            "url": url,
                        })
                        if canonical_out_dir != out_dir:
                            # proxy mode: clean up the partially-written temp file after termination
                            terminate_for_canonical_duplicate = True
                            cleanup_proxy_path = candidate
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        rc = 0
            if evt.get("event") == "progress":
                evt = _clamp_progress(evt)
                last_progress = evt
            if evt.get("event") == "complete":
                complete_event = dict(evt)
            if evt.get("event") in {"error", "manifest_error"}:
                last_error_event = dict(evt)
            now = time.time()
            activity.observe(evt, now)
            # Emit non-progress events immediately (except heartbeats and log noise)
            _ev = evt.get("event")
            if _ev not in ("progress", "heartbeat", "log"):
                _emit_json({**evt, "downloader": tool, "attempt_id": active_attempt_id, "url_index": url_index, "url": url})
            # Rate-limited progress scheduling
            if evt.get("event") == "progress":
                pending_progress = {**evt}
            if min_progress_interval <= 0 and evt.get("event") == "progress":
                clamped_evt = _clamp_progress(evt)
                _emit_json({**clamped_evt, "downloader": tool, "attempt_id": active_attempt_id, "url_index": url_index, "url": url})
                last_emit_progress_t = now
                pending_progress = None
            elif min_progress_interval > 0 and pending_progress and (now - last_emit_progress_t) >= min_progress_interval:
                clamped_progress = _clamp_progress(pending_progress)
                _emit_json({**clamped_progress, "downloader": tool, "attempt_id": active_attempt_id, "url_index": url_index, "url": url})
                last_emit_progress_t = now
                pending_progress = None
            if rc is not None:
                # We decided to end early (e.g., 'already'); stop consuming events
                break
            # Program deadline enforcement
            if program_deadline and now >= program_deadline:
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 131
                _emit_json({"event": "deadline", "attempt_id": active_attempt_id, "url_index": url_index, "url": url})
                break
            stalled = activity.stall(now)
            if stalled is not None:
                stalled_s, stalled_reason = stalled
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 124
                _emit_json({"event": "stalled", "url_index": url_index, "url": url,
                            "attempt_id": active_attempt_id,
                            "stall_seconds": stalled_s, "reason": stalled_reason})
                break
            if timeout and (time.time() - t_url_start) > timeout:
                proc.kill()
                rc = 124
                break

            # periodic PROGRESS logging to program log
            if progress_freq_s and progress_freq_s > 0:
                now = time.time()
                if now - last_proglog_t >= progress_freq_s and last_progress:
                    proglog.progress(
                        url_index=url_index,
                        pct=last_progress.get("percent"),
                        downloaded=last_progress.get("downloaded"),
                        total=last_progress.get("total"),
                        speed_bps=last_progress.get("speed_bps"),
                        eta_s=last_progress.get("eta_s"),
                    )
                    last_proglog_t = now
            # On heartbeat we do not print; but use it to time-slice emissions evenly
            if evt.get("event") == "heartbeat" and pending_progress and min_progress_interval > 0 and (now - last_emit_progress_t) >= min_progress_interval:
                clamped_progress = _clamp_progress(pending_progress)
                _emit_json({**clamped_progress, "downloader": tool, "attempt_id": active_attempt_id, "url_index": url_index, "url": url})
                last_emit_progress_t = now
                pending_progress = None
        if rc is None:
            rc = proc.wait()
        else:
            # We terminated early (e.g., 'already'); drain process quickly
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    except KeyboardInterrupt:
        try:
            proc.terminate()
        except Exception:
            pass
        _emit_json({"event": "aborted", "attempt_id": active_attempt_id, "reason": "keyboard_interrupt"})
        # write FORCE_EXIT line with last seen progress
        proglog.force_exit(url_index, time.time() - t_url_start, last_progress)
        # Treat as non-fatal for the file: return 130 so caller can advance to next URL
        info = {"elapsed_s": time.time() - t_url_start, "downloaded": (last_progress or {}).get("downloaded"), "total": (last_progress or {}).get("total"), "already": False, "downloader": tool}
        return 130, info

    if terminate_for_canonical_duplicate and cleanup_proxy_path:
        try:
            if cleanup_proxy_path.exists():
                cleanup_proxy_path.unlink()
                parent = cleanup_proxy_path.parent
                while parent != out_dir and parent != parent.parent and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        except Exception:
            pass

    if rc == 0 and not dry_run:
        promoted_path = _promote_finished_temp_sibling(last_destination_path)
        if promoted_path is not None:
            _emit_json({
                "event": "temp_promoted",
                "attempt_id": active_attempt_id,
                "path": str(promoted_path),
                "url_index": url_index,
                "url": url,
                "source": "post_run",
            })

    # Log the outcome of the initial yt-dlp attempt (Attempt 1) before fallback begins
    if tool == "yt-dlp":
        if rc == 0:
            proglog.attempt_success(1, "normal yt-dlp page download")
        else:
            _attempt1_reason = (
                "stalled (no network progress)" if rc == 124 else
                "user interrupt" if rc == 130 else
                "program deadline" if rc == 131 else
                f"exit code {rc}"
            )
            proglog.attempt_fail(1, "normal yt-dlp page download", _attempt1_reason)

    # extdl fallback: when yt-dlp fails (not a user/deadline abort) try static HTML
    # scan then Playwright browser capture before retrying or giving up.
    _fallback_tried = False
    if rc != 0 and tool == "yt-dlp" and extdl_fallback and not _is_abort_rc(rc):
        _fallback_tried = True
        fallback_rc, fallback_progress = _run_extdl_fallback(
            url, out_dir, url_index,
            extdl_max_candidates=extdl_max_candidates,
            extdl_browser_wait=extdl_browser_wait,
            extdl_capture_browser=extdl_capture_browser,
            max_dl_speed=max_dl_speed,
            max_height=max_height,
            dry_run=dry_run,
            proglog=proglog,
            first_attempt_num=2,  # Attempt 1 was the normal yt-dlp try
            stall_seconds=stall_seconds,
            attempt_prefix=normal_attempt_id,
        )
        if fallback_rc == 0:
            rc = 0
            if fallback_progress:
                last_progress = fallback_progress
                active_attempt_id = str(fallback_progress.get("attempt_id") or active_attempt_id)

    # classify status and build a human-readable failure reason
    if rc == 0:
        status = "FINISH_DUPLICATE" if (tool == "yt-dlp" and already_seen) else "FINISH_SUCCESS"
    elif rc == 77:
        status = "FINISH_PREVIEW_ONLY"
    elif rc == 124:
        status = "FINISH_STALLED"
    else:
        status = "FINISH_BAD"
    if rc == 0 and already_seen and tool == "aebndl":
        status = "FINISH_DUPLICATE"

    _finish_reason = ""
    if status in {"FINISH_BAD", "FINISH_STALLED", "FINISH_PREVIEW_ONLY"}:
        if rc == 77:
            _finish_reason = "aebndl preview-only access; full delivery not available"
        elif rc == 124:
            _finish_reason = "stalled / download timed out"
        elif rc == 130:
            _finish_reason = "user interrupt (Ctrl-C)"
        elif rc == 131:
            _finish_reason = "program deadline reached"
        elif _fallback_tried:
            _finish_reason = f"yt-dlp failed (rc={rc}) and all extdl fallback methods also exhausted"
        else:
            _finish_reason = f"{tool} exited with code {rc} (no fallback attempted)"

    elapsed_s = time.time() - t_url_start
    _emit_json({
        "event": "finish",
        "attempt_id": active_attempt_id,
        "downloader": tool,
        "url_index": url_index,
        "url": url,
        "rc": rc,
        "reason": _finish_reason,
        "elapsed_s": elapsed_s,
        "downloaded": (complete_event or {}).get("file_size") or (last_progress or {}).get("downloaded"),
        "total": (complete_event or {}).get("file_size") or (last_progress or {}).get("total"),
        "already": bool(already_seen),
        "raw_log_path": str(raw_path),
        "error_type": (last_error_event or {}).get("error_type"),
        "error_message": (last_error_event or {}).get("message"),
    })
    proglog.finish(url_index, elapsed_s, status, reason=_finish_reason)

    # retry if bad — partial_root is passed through so yt-dlp resumes the same dir
    info = {
        "elapsed_s": elapsed_s,
        "downloaded": (complete_event or {}).get("file_size") or (last_progress or {}).get("downloaded"),
        "total": (complete_event or {}).get("file_size") or (last_progress or {}).get("total"),
        "already": bool(already_seen),
        "downloader": tool,
        "error_type": (last_error_event or {}).get("error_type"),
        "error_message": (last_error_event or {}).get("message"),
    }
    if rc != 0 and retries > 0:
        return _run_one(
            tool,
            urls,
            out_dir,
            canonical_out_dir,
            partial_root,
            raw_dir,
            url_index,
            proglog,
            timeout,
            retries - 1,
            quiet,
            dry_run,
            progress_freq_s,
            max_ndjson_rate,
            extra_canonical_dirs=extra_canonical_dirs,
            stall_seconds=stall_seconds,
            program_deadline=program_deadline,
            max_dl_speed=max_dl_speed,
            max_height=max_height,
            complete_stall_seconds=complete_stall_seconds,
            extdl_fallback=extdl_fallback,
            extdl_max_candidates=extdl_max_candidates,
            extdl_browser_wait=extdl_browser_wait,
            extdl_capture_browser=extdl_capture_browser,
            skip_simulate_check=True,
            ytdlp_grid_config=ytdlp_grid_config,
            worker_slot=worker_slot,
            url_file_path=url_file_path,
            url_line_num=url_line_num,
            ytdlp_cookies_from_browser=ytdlp_cookies_from_browser,
            ytdlp_impersonate=ytdlp_impersonate,
            ytdlp_downloader=ytdlp_downloader,
        )

    # On final success, delete the per-URL partial directory (removes .part fragments)
    if rc == 0 and not dry_run:
        try:
            if url_work_dir.exists():
                shutil.rmtree(url_work_dir)
        except Exception:
            pass

    return rc, info

def _main_with_urlfile_lock_held(argv: Optional[List[str]] = None) -> int:
    # Ensure stdout uses UTF-8 regardless of terminal locale (avoids cp1252 UnicodeEncodeError
    # when URLs or filenames contain replacement characters from UTF-8 decode errors).
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = make_parser().parse_args(argv)
    ytdlp_grid_config = yt_grid.load_trial_config(args.ytdlp_grid_config_file)

    urlfile = Path(args.url_file)
    if not urlfile.exists():
        print(f"[ERROR] URL file not found: {urlfile}", file=sys.stderr)
        return 2

    archive_source_file = Path(args.archive_source_file).expanduser() if args.archive_source_file else urlfile
    archive_source_file = archive_source_file.resolve()

    # Canonical output (where files normally live)
    canonical_out_dir = Path(args.output_dir) if args.output_dir else _default_outdir_for(archive_source_file)
    canonical_out_dir = canonical_out_dir.expanduser().resolve()

    raw_dir = Path(args.raw_log_dir).expanduser().resolve()

    proxy_location: Optional[Path] = None
    download_out_dir = canonical_out_dir
    if args.proxy_dl_location:
        proxy_location = Path(args.proxy_dl_location).expanduser().resolve()
        # Use the canonical output dir's name (original urlfile stem) so that proxy
        # downloads land in B:\stars\upperfloor2\ even when the urlfile passed by the
        # manager is a single-URL temp file (e.g. w05_217_27.txt in domain-index mode).
        proxy_subdir = archive_source_file.stem or canonical_out_dir.name or urlfile.stem
        download_out_dir = (proxy_location / proxy_subdir).expanduser().resolve()
        _ensure_dir(proxy_location)

    # partial_root: per-channel _partial/ directory for all temp files
    partial_root = (download_out_dir / _partial_utils.PARTIAL_DIR_NAME).resolve()

    _ensure_dir(download_out_dir)
    _ensure_dir(partial_root)
    # Write Jellyfin .ignore so it skips the _partial/ working directory
    _partial_utils.ensure_jellyfin_ignore(partial_root)
    _ensure_dir(raw_dir)
    if download_out_dir != canonical_out_dir:
        canonical_out_dir.mkdir(parents=True, exist_ok=True)

    # Write/check version file for this partial root
    _partial_utils.write_partial_version(partial_root)

    if not args.quiet:
        print(f"[INFO] URL file: {urlfile.resolve()}")
        print(f"[INFO] Canonical dir: {canonical_out_dir}")
        if download_out_dir != canonical_out_dir:
            print(f"[INFO] Proxy download dir: {download_out_dir}")
        print(f"[INFO] Mode: {args.mode}")

    # Program log
    proglog = ProgLogger(path=Path(args.program_log).expanduser().resolve(), t0=time.time())
    proglog.program_start(urlfile.resolve(), canonical_out_dir, args.mode)
    stop_sentinel = Path(args.stop_sentinel).expanduser().resolve() if args.stop_sentinel else None

    urls = _read_urls(urlfile)

    # Prioritize URLs that already have a _partial/<hash>/ directory (resumable)
    if partial_root.is_dir():
        partial_url_set = {u for u, _ in _partial_utils.scan_partial_dirs(partial_root)}
        if partial_url_set:
            urls = sorted(urls, key=lambda u: (0 if u in partial_url_set else 1))

    # Archive support
    archive_dir = Path(args.archive_dir).expanduser().resolve() if args.archive_dir else None
    archive_file: Optional[Path] = None
    archive_statuses: Dict[str, str] = {}
    archive_processed_urls: Set[str] = set()
    if archive_dir:
        try:
            prefix = _archive_prefix_for(archive_source_file)
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_file = archive_dir / f"{prefix}-{archive_source_file.stem}.txt"
        except Exception:
            archive_file = None
    # Read existing archive entries by URL, not by line count. This keeps
    # domain-index temp files from creating one archive per generated URL file.
    if archive_file and archive_file.exists():
        source_urls = _read_urls(archive_source_file) if archive_source_file.exists() else urls
        archive_statuses, normalized_lines, archive_changed = _read_archive_statuses(archive_file, source_urls)
        archive_processed_urls = {
            url for url, status in archive_statuses.items()
            if status.lower() in ARCHIVE_PROCESSED_STATUSES
        }
        if archive_changed and normalized_lines:
            try:
                archive_file.write_text('\n'.join(normalized_lines) + '\n', encoding='utf-8')
            except Exception:
                pass
    if not urls:
        print("[ERROR] No URLs found.", file=sys.stderr)
        return 3

    overall_rc = 0
    try:
        for i, url in enumerate(urls, 1):
            # Skip successfully processed URLs based on archive status.
            if archive_file and url in archive_processed_urls:
                continue
            if _stop_sentinel_active(stop_sentinel):
                _emit_json(
                    {
                        "event": "controlled_stop",
                        "url_index": i,
                        "url_total": len(urls),
                        "sentinel": str(stop_sentinel),
                    }
                )
                if stop_sentinel:
                    proglog.controlled_stop(i, len(urls), stop_sentinel)
                break
            # Quick pre-filter: skip known unsupported listing pages
            if not _looks_supported_video(url):
                _emit_json({"event": "skipped", "reason": "unsupported_url_shape", "url_index": i, "url": url})
                # Do not write to archive for skipped; just log and continue
                proglog.finish(i, 0.0, "FINISH_BAD")
                continue
            # pick tool
            if args.mode == "yt":
                tool = "yt-dlp"
            elif args.mode == "aebn":
                tool = "aebndl"
            else:
                tool = "aebndl" if _is_aebn(url) else "yt-dlp"

            rc, info = _run_one(
                tool=tool,
                urls=[url],
                out_dir=download_out_dir,
                canonical_out_dir=canonical_out_dir,
                partial_root=partial_root,
                raw_dir=raw_dir,
                url_index=i,
                proglog=proglog,
                timeout=args.timeout_seconds,
                retries=args.retries,
                quiet=args.quiet,
                dry_run=args.dry_run,
                progress_freq_s=args.progress_log_freq,
                max_ndjson_rate=args.max_ndjson_rate,
                stall_seconds=args.stall_seconds,
                complete_stall_seconds=args.complete_stall_seconds,
                program_deadline=(time.time() + args.exit_at_time) if (args.exit_at_time and args.exit_at_time > 0) else None,
                max_dl_speed=args.max_dl_speed,
                max_height=_max_height_for_label(args.max_resolution),
                extdl_fallback=not getattr(args, "no_extdl_fallback", False),
                extdl_max_candidates=getattr(args, "extdl_max_candidates", 5),
                extdl_browser_wait=getattr(args, "extdl_browser_wait", 12.0),
                extdl_capture_browser=getattr(args, "extdl_capture_browser", "auto"),
                skip_simulate_check=getattr(args, "skip_simulate_check", False),
                ytdlp_grid_config=ytdlp_grid_config if tool == "yt-dlp" else None,
                url_file_path=str(archive_source_file.resolve()),
                url_line_num=i,
                worker_slot=getattr(args, "worker_slot", 0),
                extra_canonical_dirs=[
                    Path(r).expanduser().resolve()
                    for r in (getattr(args, "extra_canonical_roots", None) or [])
                ],
                ytdlp_cookies_from_browser=getattr(args, "ytdlp_cookies_from_browser", "firefox"),
                ytdlp_impersonate=getattr(args, "ytdlp_impersonate", "chrome"),
                ytdlp_downloader=getattr(args, "ytdlp_downloader", "aria2c"),
            )
            # Update archive status (skip marking on Ctrl-C abort rc==130)
            if archive_file:
                if rc == 0:
                    status = 'already' if info.get('already') else 'downloaded'
                elif rc == 77:
                    status = 'preview-only'
                elif rc == 124:
                    status = 'stalled'
                elif rc in (130, 131):
                    status = ''  # do not write on Ctrl+C/deadline
                else:
                    status = 'bad-url'
                if status:
                    elapsed_s = float(info.get('elapsed_s') or 0.0)
                    when = time.strftime('%Y-%m-%dT%H:%M:%S')
                    downloaded = float(info.get('downloaded') or 0.0)
                    downloaded_mib = downloaded / (1024*1024)
                    vid = _extract_video_id(url)
                    line = _format_archive_line(status, elapsed_s, when, downloaded_mib, vid, url)
                    try:
                        _locked_append_line(archive_file, line)
                        archive_statuses[url] = status
                        if status in ARCHIVE_PROCESSED_STATUSES:
                            archive_processed_urls.add(url)
                        _emit_json({"event": "archive_write", "status": status, "url_index": i, "url": url, "archive_path": str(archive_file)})
                    except Exception:
                        _emit_json({"event": "archive_write_failed", "status": status, "url_index": i, "url": url, "archive_path": str(archive_file)})
                else:
                    _emit_json({"event": "archive_skip", "url_index": i, "url": url, "archive_path": str(archive_file), "reason": "status_suppressed"})

            if rc != 0:
                overall_rc = rc  # remember last non-zero
                # If user aborted (rc==130), stop processing further URLs
                if rc == 130:
                    break
        return overall_rc
    except KeyboardInterrupt:
        try:
            proglog.program_force_exit()
        except Exception:
            pass
        raise


def _lock_owner_payload(attempt: LockAttempt) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "lock_path": str(attempt.lock_path),
        "source_path": str(attempt.source_path),
    }
    if attempt.owner:
        payload["owner"] = attempt.owner
    if attempt.error:
        payload["error"] = attempt.error
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    args = make_parser().parse_args(argv)
    urlfile = Path(args.url_file).expanduser()
    if not urlfile.exists():
        print(f"[ERROR] URL file not found: {urlfile}", file=sys.stderr)
        return 2

    source_file = Path(args.archive_source_file).expanduser() if args.archive_source_file else urlfile
    source_file = source_file.resolve()
    stop_sentinel = Path(args.stop_sentinel).expanduser().resolve() if args.stop_sentinel else None
    lock = UrlFileLock(
        source_file,
        worker_slot=args.worker_slot,
        manager_pid=args.manager_pid,
        mode="manager-worker" if args.manager_pid else "standalone-worker",
        lock_dir=Path(args.url_file_lock_dir),
    )
    wait_emitted = False

    def stop_requested() -> bool:
        return _stop_sentinel_active(stop_sentinel)

    def on_wait(attempt: LockAttempt) -> None:
        nonlocal wait_emitted
        if wait_emitted:
            return
        _emit_json({"event": "urlfile_lock_wait", **_lock_owner_payload(attempt)})
        wait_emitted = True

    if args.wait_for_url_file_lock:
        attempt = lock.acquire_waiting(stop_requested, on_wait=on_wait)
    else:
        attempt = lock.try_acquire()

    if attempt.status == "stopped":
        _emit_json({"event": "controlled_stop", "reason": "urlfile_lock_wait"})
        return 0
    if not attempt.acquired:
        payload = _lock_owner_payload(attempt)
        _emit_json({"event": "urlfile_lock_failed", "status": attempt.status, **payload})
        owner_pid = (attempt.owner or {}).get("pid")
        owner_text = f" by pid {owner_pid}" if owner_pid else ""
        print(
            f"[WARNING] URL file lock unavailable{owner_text}: {source_file}",
            file=sys.stderr,
        )
        return LOCK_HELD_RC if attempt.status == "held" else LOCK_ERROR_RC

    _emit_json(
        {
            "event": "urlfile_lock_acquired",
            "lock_path": str(attempt.lock_path),
            "source_path": str(source_file),
        }
    )
    try:
        return _main_with_urlfile_lock_held(argv)
    finally:
        lock.release()
        _emit_json(
            {
                "event": "urlfile_lock_released",
                "lock_path": str(attempt.lock_path),
                "source_path": str(source_file),
            }
        )

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Program-level exit code only; logging handled inside main/_run_one
        sys.exit(130)



