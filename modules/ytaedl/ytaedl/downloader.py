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
    p.add_argument("-S", "--stall-seconds", type=int, default=60, help="If no non-heartbeat events arrive for N seconds, treat URL as stalled and move to next.")
    p.add_argument("-E", "--exit-at-time", type=int, default=-1, help="Exit the program after N seconds (<=0 disables).")
    p.add_argument("-X", "--max-dl-speed", type=float, default=None,
                   help="Limit download speed to MiB/s (per process). Applies to yt-dlp via --limit-rate; aebndl currently not limited.")
    p.add_argument("-H", "--max-resolution", choices=MAX_RESOLUTION_CHOICES, default=None,
                   help="Highest video resolution to allow (yt-dlp uses format filters; aebndl requests nearest available <= target).")

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

    def start(self, url_index: int, url: str) -> None:
        self.counter += 1
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"[{self.counter:04d}][{elapsed}] START  [{url_index}] {url}")

    def finish(self, url_index: int, elapsed_url_s: float, status: str) -> None:
        elapsed_prog = _hms_ms(time.time() - self.t0)
        elapsed_url = _hms_ms(elapsed_url_s)
        # FINISH_SUCCESS | FINISH_BAD | FINISH_DUPLICATE
        self._write(f"[{self.counter:04d}][{elapsed_prog}] {status} [{url_index}] Elapsed {elapsed_url}, Status={status.replace('FINISH_', '')}")

    def program_start(self, urlfile: Path, out_dir: Path, mode: str) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"PROGRAM_START [{elapsed}] urlfile={urlfile} out_dir={out_dir} mode={mode}")

    def program_force_exit(self) -> None:
        elapsed = _hms_ms(time.time() - self.t0)
        self._write(f"FORCE_EXIT_PROGRAM [{elapsed}]")

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
            v = float(b); i = 0
            while v >= 1024 and i < len(units) - 1:
                v /= 1024.0; i += 1
            return f"{v:.2f}{units[i]}"
        def _fmt_eta(s: int | None) -> str:
            if s is None:
                return "?"
            h = s // 3600; m = (s % 3600) // 60; sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"
        pct_s = f"{pct:.2f}%" if isinstance(pct, (int, float)) else "?%"
        sp_s = f"{_fmt_bytes(int(speed_bps))}/s" if isinstance(speed_bps, (int, float)) else "?/s"
        dl_s = _fmt_bytes(downloaded)
        tot_s = _fmt_bytes(total)
        eta_str = _fmt_eta(eta_s)
        self._write(f"[{self.counter:04d}][{elapsed_prog}] FORCE_EXIT [{url_index}] {pct_s} {dl_s}/{tot_s} {sp_s} ETA {eta_str} Elapsed {elapsed_url}")

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
            h = s // 3600; m = (s % 3600) // 60; sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"

        elapsed_prog = _hms_ms(time.time() - self.t0)
        pct_s = f"{pct:.2f}%" if pct is not None else "?%"
        sp_s = f"{_fmt_bytes(int(speed_bps))}/s" if speed_bps else "?/s"
        dl_s = _fmt_bytes(downloaded)
        tot_s = _fmt_bytes(total)
        eta_str = _fmt_eta(eta_s)
        self._write(f"[{self.counter:04d}][{elapsed_prog}] PROGRESS [{url_index}] {pct_s} {dl_s}/{tot_s} {sp_s} ETA {eta_str}")

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




def _format_archive_line(status: str, elapsed_s: float, when: str, downloaded_mib: float, video_id: str, url: str) -> str:
    return "	".join([
        status,
        f"{elapsed_s:.3f}",
        when,
        f"{downloaded_mib:.2f}MiB",
        video_id or '',
        url,
    ])


def _ensure_archive_line_has_url(line: str, url: str) -> str:
    if not line.strip():
        return ''
    parts = line.split('	')
    if len(parts) < 6:
        parts = (parts + [''] * 6)[:6]
    parts[5] = url
    return '	'.join(parts)

def _build_ytdlp_cmd(
    urls: List[str],
    out_dir: Path,
    max_mibs: Optional[float] = None,
    max_height: Optional[int] = None,
    temp_dir: Optional[Path] = None,
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
def _emit_json(d: dict) -> None:
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def _run_one(
    tool: str,
    urls: List[str],
    out_dir: Path,
    canonical_out_dir: Path,
    work_dir: Path,
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
) -> tuple[int, dict]:
    """
    Returns rc (0 on success). Emits NDJSON to stdout during run.
    """
    # For aebndl we run per-URL. For yt-dlp we can batch, but to keep consistent eventing,
    # we run one-at-a-time here too so your master gets clean URL boundaries.
    assert len(urls) == 1
    url = urls[0]
    stem = _urlfile_stem(Path(url))

    proglog.start(url_index, url)
    t_url_start = time.time()

    canonical_out_dir = canonical_out_dir.expanduser().resolve()
    cleanup_proxy_path: Optional[Path] = None
    terminate_for_canonical_duplicate = False

    # choose command
    if tool == "aebndl":
        cmd = _build_aebndl_cmd(url, out_dir, work_dir, max_height)
    else:
        cmd = _build_ytdlp_cmd([url], out_dir, max_dl_speed, max_height, temp_dir=work_dir)

    _emit_json({"event": "start", "downloader": tool, "url_index": url_index, "url_total": None,
                "url": url, "out_dir": str(out_dir), "cmd": None})

    if dry_run:
        if not quiet:
            print("DRY RUN:", " ".join(shlex.quote(x) for x in cmd))
        _emit_json({"event": "finish", "downloader": tool, "url_index": url_index, "url": url, "rc": 0})
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
    )

    already_seen = False
    dest_path: Optional[Path] = None
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
        last_real_event_t = time.time()
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
                    dest_path = candidate
                    if canonical_out_dir != out_dir:
                        try:
                            rel = candidate.relative_to(out_dir)
                        except ValueError:
                            rel = Path(candidate.name)
                        canonical_candidate = (canonical_out_dir / rel).resolve()
                        if canonical_candidate.exists():
                            already_seen = True
                            terminate_for_canonical_duplicate = True
                            cleanup_proxy_path = candidate
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            rc = 0
            if evt.get("event") == "progress":
                last_progress = evt
            now = time.time()
            # Update last activity time for any non-heartbeat event
            if evt.get("event") != "heartbeat":
                last_real_event_t = now
            # Emit non-progress events immediately (except heartbeats)
            if evt.get("event") != "progress" and evt.get("event") != "heartbeat":
                _emit_json({**evt, "downloader": tool, "url_index": url_index, "url": url})
            # Rate-limited progress scheduling
            if evt.get("event") == "progress":
                pending_progress = {**evt}
            if min_progress_interval <= 0 and evt.get("event") == "progress":
                _emit_json({**evt, "downloader": tool, "url_index": url_index, "url": url})
                last_emit_progress_t = now
                pending_progress = None
            elif min_progress_interval > 0 and pending_progress and (now - last_emit_progress_t) >= min_progress_interval:
                _emit_json({**pending_progress, "downloader": tool, "url_index": url_index, "url": url})
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
            # Stall detection: if no non-heartbeat events for S seconds, kill and mark as stalled
            stall_s = stall_seconds
            if stall_s and stall_s > 0 and (now - last_real_event_t) > stall_s:
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 124
                _emit_json({"event": "stalled", "url_index": url_index, "url": url, "stall_seconds": stall_s})
                break
            # Stall detection: if no real events for S seconds, kill and mark as stalled
            stall_s = stall_seconds
            if stall_s and stall_s > 0 and (now - last_real_event_t) > stall_s:
                try:
                    proc.kill()
                except Exception:
                    pass
                rc = 124
                _emit_json({"event": "stalled", "url_index": url_index, "url": url, "stall_seconds": stall_s})
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
                _emit_json({**pending_progress, "downloader": tool, "url_index": url_index, "url": url})
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

    # classify status
    status = "FINISH_SUCCESS" if rc == 0 else "FINISH_BAD"
    if rc == 0 and tool == "yt-dlp" and already_seen:
        status = "FINISH_DUPLICATE"

    _emit_json({"event": "finish", "downloader": tool, "url_index": url_index, "url": url, "rc": rc})
    elapsed_s = time.time() - t_url_start
    proglog.finish(url_index, elapsed_s, status)

    # retry if bad
    info = {"elapsed_s": elapsed_s, "downloaded": (last_progress or {}).get("downloaded"), "total": (last_progress or {}).get("total"), "already": bool(already_seen), "downloader": tool}
    if rc != 0 and retries > 0:
        return _run_one(tool, urls, out_dir, canonical_out_dir, work_dir, raw_dir, url_index, proglog, timeout, retries - 1, quiet, dry_run, progress_freq_s, max_ndjson_rate, stall_seconds, program_deadline, max_dl_speed, max_height)
    return rc, info

def main() -> int:
    args = make_parser().parse_args()

    urlfile = Path(args.url_file)
    if not urlfile.exists():
        print(f"[ERROR] URL file not found: {urlfile}", file=sys.stderr)
        return 2

    # Canonical output (where files normally live)
    canonical_out_dir = Path(args.output_dir) if args.output_dir else _default_outdir_for(urlfile)
    canonical_out_dir = canonical_out_dir.expanduser().resolve()

    work_dir_arg = Path(args.work_dir).expanduser()
    raw_dir = Path(args.raw_log_dir).expanduser().resolve()

    proxy_root: Optional[Path] = None
    download_out_dir = canonical_out_dir
    if args.proxy_dl_location:
        proxy_root = Path(args.proxy_dl_location).expanduser().resolve()
        download_out_dir = (proxy_root / urlfile.stem).expanduser().resolve()
        _ensure_dir(proxy_root)
        if args.work_dir == './tmp':
            work_dir = (download_out_dir / '_tmp').resolve()
        else:
            work_dir = work_dir_arg.resolve()
    else:
        work_dir = work_dir_arg.resolve()

    _ensure_dir(download_out_dir)
    _ensure_dir(work_dir)
    _ensure_dir(raw_dir)
    if download_out_dir != canonical_out_dir:
        canonical_out_dir.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print(f"[INFO] URL file: {urlfile.resolve()}")
        print(f"[INFO] Canonical dir: {canonical_out_dir}")
        if download_out_dir != canonical_out_dir:
            print(f"[INFO] Proxy download dir: {download_out_dir}")
        print(f"[INFO] Mode: {args.mode}")

    # Program log
    proglog = ProgLogger(path=Path(args.program_log).expanduser().resolve(), t0=time.time())
    proglog.program_start(urlfile.resolve(), canonical_out_dir, args.mode)

    urls = _read_urls(urlfile)
    # Archive support
    archive_dir = Path(args.archive_dir).expanduser().resolve() if args.archive_dir else None
    archive_file: Optional[Path] = None
    if archive_dir:
        try:
            prefix = 'ae' if 'ae-stars' in str(urlfile.parent) else 'yt'
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_file = archive_dir / f"{prefix}-{urlfile.stem}.txt"
        except Exception:
            archive_file = None
    # Read existing archive entries and compute starting index
    processed_lines: list[str] = []
    if archive_file and archive_file.exists():
        try:
            raw_lines = archive_file.read_text(encoding='utf-8').splitlines()
        except Exception:
            raw_lines = []
        for idx, ln in enumerate(raw_lines):
            if not ln.strip():
                continue
            url_for_line = urls[idx] if idx < len(urls) else ''
            processed_lines.append(_ensure_archive_line_has_url(ln, url_for_line))
        if processed_lines and processed_lines != [ln for ln in raw_lines if ln.strip()]:
            try:
                archive_file.write_text('\n'.join(processed_lines) + '\n', encoding='utf-8')
            except Exception:
                pass
    first_unprocessed = (len(processed_lines) + 1) if archive_file else 1
    if not urls:
        print("[ERROR] No URLs found.", file=sys.stderr)
        return 3

    overall_rc = 0
    try:
        for i, url in enumerate(urls, 1):
            # Skip already processed based on archive
            if archive_file and i < first_unprocessed:
                continue
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
                work_dir=work_dir,
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
                program_deadline=(time.time() + args.exit_at_time) if (args.exit_at_time and args.exit_at_time > 0) else None,
                max_dl_speed=args.max_dl_speed,
                max_height=_max_height_for_label(args.max_resolution),
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
                    processed_lines.append(line)
                    try:
                        with archive_file.open('a', encoding='utf-8') as fh:
                            fh.write(line + "\n")
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



