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
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from procparsers import iter_parsed_events

try:
    from . import _partial_utils
    from . import yt_grid
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
        description="Unified downloader for yt-dlp and aebndl with live JSON events and logs.",
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
    p.add_argument("--no-extdl-fallback", action="store_true",
                   help="Disable the extdl static-HTML and Playwright fallback when yt-dlp fails.")
    p.add_argument("--extdl-max-candidates", type=int, default=5,
                   help="Max fallback media candidates to try per method (0 = all).")
    p.add_argument("--extdl-browser-wait", type=float, default=12.0,
                   help="Seconds to collect browser network traffic in the Playwright fallback.")
    p.add_argument("--extdl-capture-browser", default="auto",
                   choices=["auto", "chromium", "firefox", "webkit"],
                   help="Playwright browser backend for the network capture fallback.")
    p.add_argument("--skip-simulate-check", action="store_true",
                   help="Skip the yt-dlp --simulate pre-download duplicate check.")
    p.add_argument("-G", "--ytdlp-grid-config-file", default=None,
                   help="JSON trial/config file with yt-dlp options selected by ytaedl grid search.")

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


def _build_ytdlp_cmd(
    urls: List[str],
    out_dir: Path,
    max_mibs: Optional[float] = None,
    max_height: Optional[int] = None,
    temp_dir: Optional[Path] = None,
    grid_config: Optional[dict] = None,
) -> List[str]:
    # no --print; --newline ensures line-terminated progress
    cmd = [
        "yt-dlp",
        "--newline",
        "-o", str(out_dir / "%(title)s.%(ext)s"),
    ]
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


def _build_aebndl_cmd(
    url: str,
    out_dir: Path,
    work_dir: Path,
    max_height: Optional[int] = None,
) -> List[str]:
    # Keep default logging level (INFO) to have progress; do NOT pass -c by default
    cmd = ["aebndl", "--json", "-o", str(out_dir), "-w", str(work_dir)]
    if isinstance(max_height, int) and max_height > 0:
        cmd += ["-r", str(max_height)]
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
    last_progress_event_t: Optional[float] = None
    last_progress_growth_t: Optional[float] = None
    last_progress_bytes: Optional[int] = None
    active_started: bool = False
    near_complete_since: Optional[float] = None

    @property
    def active_stall_seconds(self) -> Optional[int]:
        return _active_stall_seconds(self.stall_seconds)

    def observe(self, evt: dict, now: float) -> None:
        ev = evt.get("event")
        if ev != "heartbeat":
            self.last_real_event_t = now
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
        if (
            self.near_complete_since is not None
            and self.complete_stall_seconds > 0
            and (now - self.near_complete_since) > self.complete_stall_seconds
        ):
            return self.complete_stall_seconds, "near_complete_stall"

        if not self.stall_seconds or self.stall_seconds <= 0:
            return None

        if not self.active_started:
            if (now - self.last_real_event_t) > self.stall_seconds:
                return int(self.stall_seconds), "pre_transfer_no_output"
            return None

        active_stall_s = self.active_stall_seconds
        if active_stall_s and self.last_progress_growth_t is not None:
            if self.near_complete_since is None and (now - self.last_progress_growth_t) > active_stall_s:
                return active_stall_s, "active_no_byte_growth"
        return None

def _emit_json(d: dict) -> None:
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()


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


def _simulate_check(
    url: str,
    canonical_out_dir: Path,
    *,
    timeout_seconds: int = 15,
) -> _SimulateResult:
    """Run yt-dlp --simulate to predict filename/size and check for an existing duplicate.

    Returns a ``_SimulateResult`` indicating whether the file already exists.
    If yt-dlp --simulate fails (unsupported site, network error, etc.) returns
    ``is_duplicate=False`` so the caller proceeds with the normal download.
    """
    try:
        proc = subprocess.Popen(
            [
                "yt-dlp",
                "--simulate",
                "--print", "%(title)s.%(ext)s",
                "--print", "%(filesize,filesize_approx)s",
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
            return _SimulateResult(is_duplicate=False)

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

        predicted_file = canonical_out_dir / predicted_name

        # Check exact filename match
        if predicted_file.exists():
            if predicted_size is None:
                return _SimulateResult(is_duplicate=True, existing_path=str(predicted_file),
                                       predicted_name=predicted_name)
            existing_size = predicted_file.stat().st_size
            # Allow 1% tolerance to handle minor muxing size differences
            if predicted_size > 0 and abs(existing_size - predicted_size) / predicted_size <= 0.01:
                return _SimulateResult(is_duplicate=True, existing_path=str(predicted_file),
                                       predicted_name=predicted_name)
            # File exists but sizes differ significantly — not a duplicate
            return _SimulateResult(is_duplicate=False, predicted_name=predicted_name)

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
    yt_dlp_executable: str = "yt-dlp",
    max_dl_speed: Optional[float] = None,
    max_height: Optional[int] = None,
    dry_run: bool = False,
    proglog: Optional["ProgLogger"] = None,
    first_attempt_num: int = 2,
    stall_seconds: int | None = None,
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
        _emit_json({"event": "fallback_skip", "method": "all", "reason": msg,
                    "url_index": url_index, "url": url})
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

    def _try_candidates(candidates, method_name: str) -> tuple[int, Optional[dict]]:
        limited = candidates[:extdl_max_candidates] if extdl_max_candidates > 0 else candidates
        for idx_in_method, candidate in enumerate(limited, start=1):
            _global_attempt[0] += 1
            global_num = _global_attempt[0]
            _emit_json({
                "event": "fallback_attempt",
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
                yt_dlp_executable=yt_dlp_executable,
                max_dl_speed=max_dl_speed,
                max_height=max_height,
            )
            if dry_run:
                import shlex
                _emit_json({"event": "fallback_dryrun", "method": method_name,
                            "attempt": idx_in_method, "cmd": shlex.join(cmd),
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.fallback_result(method_name, idx_in_method, len(limited), 0)
                    proglog.attempt_success(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}")
                return 0, None
            candidate_last_progress: Optional[dict] = None
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
                        complete_stall_seconds=300,
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
                            candidate_last_progress = evt
                        _cand_activity.observe(evt, _cand_now)
                        if ev == "progress":
                            _emit_json({**evt, "downloader": "yt-dlp",
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
                            _emit_json({**evt, "downloader": "yt-dlp",
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
                            "attempt": idx_in_method, "rc": rc, "error": str(exc),
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.fallback_result(method_name, idx_in_method, len(limited), rc)
                    proglog.attempt_fail(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}", f"exception: {exc}")
                continue
            if proglog:
                proglog.fallback_result(method_name, idx_in_method, len(limited), rc)
            if rc == 0:
                _emit_json({"event": "fallback_success", "method": method_name,
                            "attempt": idx_in_method, "candidate_url": candidate.url,
                            "url_index": url_index, "url": url})
                if proglog:
                    proglog.attempt_success(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}")
                return 0, candidate_last_progress
            _emit_json({"event": "fallback_failure", "method": method_name,
                        "attempt": idx_in_method, "rc": rc,
                        "url_index": url_index, "url": url})
            if proglog:
                proglog.attempt_fail(global_num, f"{method_name} {candidate.kind} candidate {idx_in_method}/{len(limited)}", f"exit code {rc}")
        return 1, None

    # Method 2: static HTML scan
    _emit_json({"event": "fallback_start", "method": "static_html",
                "url_index": url_index, "url": url})
    if proglog:
        proglog.fallback_start("static_html")
    try:
        static_candidates = _extdl.discover_static_media_candidates(url)
    except Exception as exc:
        static_candidates = []
        _emit_json({"event": "fallback_failure", "method": "static_html", "rc": -1,
                    "error": str(exc), "url_index": url_index, "url": url})

    if static_candidates:
        static_rc, static_progress = _try_candidates(static_candidates, "static_html")
        if static_rc == 0:
            return 0, static_progress

    # Method 3: Playwright browser capture
    _emit_json({"event": "fallback_start", "method": "browser",
                "url_index": url_index, "url": url})
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
                    "reason": msg, "url_index": url_index, "url": url})
        if proglog:
            proglog.fallback_skip("browser_network", msg)
        browser_candidates = []
    except Exception as exc:
        _emit_json({"event": "fallback_failure", "method": "browser", "rc": -1,
                    "error": str(exc), "url_index": url_index, "url": url})
        browser_candidates = []

    if browser_candidates:
        browser_rc, browser_progress = _try_candidates(browser_candidates, "browser_network")
        if browser_rc == 0:
            return 0, browser_progress

    _emit_json({"event": "fallback_exhausted", "url_index": url_index, "url": url})
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

    # Pre-download simulate check: run yt-dlp --simulate to predict filename/size
    # and skip if the file already exists at the canonical destination.
    _canonical_resolved = canonical_out_dir.expanduser().resolve()
    if not dry_run and tool == "yt-dlp" and not skip_simulate_check:
        proglog.simulate_start(url)
        _emit_json({"event": "simulate_start", "url_index": url_index, "url": url})
        sim = _simulate_check(url, _canonical_resolved)
        if sim.is_duplicate:
            proglog.simulate_skip(url, sim.existing_path)
            _emit_json({
                "event": "simulate_result",
                "is_duplicate": True,
                "existing_path": sim.existing_path,
                "predicted_name": sim.predicted_name,
                "url_index": url_index,
                "url": url,
            })
            _emit_json({
                "event": "canonical_duplicate",
                "canonical_path": sim.existing_path,
                "url_index": url_index,
                "url": url,
                "source": "simulate_check",
            })
            _emit_json({
                "event": "finish",
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
        cmd = _build_aebndl_cmd(url, out_dir, url_work_dir, max_height)
    else:
        cmd = _build_ytdlp_cmd(
            [url],
            out_dir,
            max_dl_speed,
            max_height,
            temp_dir=url_work_dir,
            grid_config=ytdlp_grid_config,
        )

    _emit_json({"event": "start", "downloader": tool, "url_index": url_index, "url_total": None,
                "url": url, "out_dir": str(out_dir), "cmd": None,
                "ytdlp_grid_config": ytdlp_grid_config if tool == "yt-dlp" else None})

    if dry_run:
        if not quiet:
            print("DRY RUN:", " ".join(shlex.quote(x) for x in cmd))
        _emit_json({
            "event": "finish",
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

    try:
        # internal heartbeat for scheduling; also used for stall detection
        hb = 0.2 if (max_ndjson_rate is not None and max_ndjson_rate > 0) else 0.5
        activity_start = time.time()
        activity = _ProgressActivity(
            stall_seconds=stall_seconds,
            complete_stall_seconds=complete_stall_seconds,
            started_at=activity_start,
            last_real_event_t=activity_start,
        )
        for evt in iter_parsed_events(tool, proc.stdout, raw_log_path=raw_path, heartbeat_secs=hb):
            # track 'already' to classify FINISH_DUPLICATE later for yt-dlp
            if evt.get("event") == "already":
                already_seen = True
                # For yt-dlp, short-circuit this URL: terminate process and proceed to next URL
                try:
                    proc.terminate()
                except Exception:
                    pass
                rc = 0
                # still emit the event below for downstream
            if evt.get("event") == "destination":
                raw_dest = evt.get("path")
                if raw_dest:
                    candidate = Path(raw_dest).expanduser().resolve()
                    # Resolve the canonical destination path (works in both proxy and non-proxy mode)
                    if canonical_out_dir != out_dir:
                        try:
                            rel = candidate.relative_to(out_dir)
                        except ValueError:
                            rel = Path(candidate.name)
                        canonical_candidate = (canonical_out_dir / rel).resolve()
                    else:
                        canonical_candidate = candidate
                    # Check exact filename match, then fall back to stem match
                    # (catches re-downloads where container extension differs, e.g. .webm vs .mp4)
                    existing = None
                    if canonical_candidate.exists():
                        existing = canonical_candidate
                    else:
                        existing = _find_stem_in_dir(canonical_candidate.stem, canonical_candidate.parent)
                    if existing is not None:
                        already_seen = True
                        _emit_json({
                            "event": "canonical_duplicate",
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
            now = time.time()
            activity.observe(evt, now)
            # Emit non-progress events immediately (except heartbeats)
            if evt.get("event") != "progress" and evt.get("event") != "heartbeat":
                _emit_json({**evt, "downloader": tool, "url_index": url_index, "url": url})
            # Rate-limited progress scheduling
            if evt.get("event") == "progress":
                pending_progress = {**evt}
            if min_progress_interval <= 0 and evt.get("event") == "progress":
                clamped_evt = _clamp_progress(evt)
                _emit_json({**clamped_evt, "downloader": tool, "url_index": url_index, "url": url})
                last_emit_progress_t = now
                pending_progress = None
            elif min_progress_interval > 0 and pending_progress and (now - last_emit_progress_t) >= min_progress_interval:
                clamped_progress = _clamp_progress(pending_progress)
                _emit_json({**clamped_progress, "downloader": tool, "url_index": url_index, "url": url})
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
                _emit_json({"event": "deadline", "url_index": url_index, "url": url})
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
                _emit_json({**clamped_progress, "downloader": tool, "url_index": url_index, "url": url})
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
        _emit_json({"event": "aborted", "reason": "keyboard_interrupt"})
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
        )
        if fallback_rc == 0:
            rc = 0
            if fallback_progress:
                last_progress = fallback_progress

    # classify status and build a human-readable failure reason
    status = "FINISH_SUCCESS" if rc == 0 else "FINISH_BAD"
    if rc == 0 and tool == "yt-dlp" and already_seen:
        status = "FINISH_DUPLICATE"

    _finish_reason = ""
    if status == "FINISH_BAD":
        if rc == 124:
            _finish_reason = "stalled / download timed out"
        elif rc == 130:
            _finish_reason = "user interrupt (Ctrl-C)"
        elif rc == 131:
            _finish_reason = "program deadline reached"
        elif _fallback_tried:
            _finish_reason = f"yt-dlp failed (rc={rc}) and all extdl fallback methods also exhausted"
        else:
            _finish_reason = f"yt-dlp exited with code {rc} (no fallback attempted)"

    elapsed_s = time.time() - t_url_start
    _emit_json({
        "event": "finish",
        "downloader": tool,
        "url_index": url_index,
        "url": url,
        "rc": rc,
        "reason": _finish_reason,
        "elapsed_s": elapsed_s,
        "downloaded": (last_progress or {}).get("downloaded"),
        "total": (last_progress or {}).get("total"),
        "already": bool(already_seen),
        "raw_log_path": str(raw_path),
    })
    proglog.finish(url_index, elapsed_s, status, reason=_finish_reason)

    # retry if bad — partial_root is passed through so yt-dlp resumes the same dir
    info = {"elapsed_s": elapsed_s, "downloaded": (last_progress or {}).get("downloaded"), "total": (last_progress or {}).get("total"), "already": bool(already_seen), "downloader": tool}
    if rc != 0 and retries > 0:
        return _run_one(tool, urls, out_dir, canonical_out_dir, partial_root, raw_dir, url_index, proglog, timeout, retries - 1, quiet, dry_run, progress_freq_s, max_ndjson_rate, stall_seconds, program_deadline, max_dl_speed, max_height, complete_stall_seconds, extdl_fallback, extdl_max_candidates, extdl_browser_wait, extdl_capture_browser, skip_simulate_check=True, ytdlp_grid_config=ytdlp_grid_config, worker_slot=worker_slot, url_file_path=url_file_path, url_line_num=url_line_num)

    # On final success, delete the per-URL partial directory (removes .part fragments)
    if rc == 0 and not dry_run:
        try:
            if url_work_dir.exists():
                shutil.rmtree(url_work_dir)
        except Exception:
            pass

    return rc, info

def main() -> int:
    # Ensure stdout uses UTF-8 regardless of terminal locale (avoids cp1252 UnicodeEncodeError
    # when URLs or filenames contain replacement characters from UTF-8 decode errors).
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = make_parser().parse_args()
    ytdlp_grid_config = yt_grid.load_trial_config(args.ytdlp_grid_config_file)

    urlfile = Path(args.url_file)
    if not urlfile.exists():
        print(f"[ERROR] URL file not found: {urlfile}", file=sys.stderr)
        return 2

    # Canonical output (where files normally live)
    canonical_out_dir = Path(args.output_dir) if args.output_dir else _default_outdir_for(urlfile)
    canonical_out_dir = canonical_out_dir.expanduser().resolve()

    raw_dir = Path(args.raw_log_dir).expanduser().resolve()

    proxy_location: Optional[Path] = None
    download_out_dir = canonical_out_dir
    if args.proxy_dl_location:
        proxy_location = Path(args.proxy_dl_location).expanduser().resolve()
        # Use the canonical output dir's name (original urlfile stem) so that proxy
        # downloads land in B:\stars\upperfloor2\ even when the urlfile passed by the
        # manager is a single-URL temp file (e.g. w05_217_27.txt in domain-index mode).
        proxy_subdir = canonical_out_dir.name if canonical_out_dir.name else urlfile.stem
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
    archive_source_file = Path(args.archive_source_file).expanduser() if args.archive_source_file else urlfile
    archive_source_file = archive_source_file.resolve()
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
                url_file_path=str(urlfile.resolve()),
                url_line_num=i,
            )
            # Update archive status (skip marking on Ctrl-C abort rc==130)
            if archive_file:
                if rc == 0:
                    status = 'already' if info.get('already') else 'downloaded'
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

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Program-level exit code only; logging handled inside main/_run_one
        sys.exit(130)



