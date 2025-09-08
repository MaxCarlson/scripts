#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestrator — scan URL files and then download, with a Termdash UI.

Key changes in this build:
  • Scan phase now calls yt-dlp per URL to compute the expected filename and
    checks for it under <out_dir>/<stem>/ (dup-aware), so progress is realistic.
  • Top banner is driven with deltas via ui.scan_progress_delta(...) and per-file
    summaries via ui.scan_file_done(...). Calls are guarded for SimpleUI/older UI.
  • AE (aebndl) scanning is skipped for now (you asked to focus on yt-dlp).
  • Frozen dataclass fix: object.__setattr__(cfg, "_orchestrator_max_dl", ...)

The orchestrator keeps prior public surfaces used by tests.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .downloaders import (
    get_downloader,
    request_abort,
    terminate_all_active_procs,
)
from .io import read_urls_from_files
from .models import (
    DownloaderConfig,
    DownloadItem,
    URLSource,
    StartEvent,
    FinishEvent,
    LogEvent,
)
from .ui import SimpleUI, TermdashUI
from .url_parser import get_url_slug

# ---------------------------------------------------------------------------

DEF_URL_DIR = Path("files/downloads/stars")
DEF_AE_URL_DIR = Path("files/downloads/ae-stars")
DEF_OUT_DIR = Path("files/downloads/out")
DEF_COUNTS_FILE = Path("files/downloads/ytaedl-counts.json")
DEF_EXTS = {"mp4", "mkv", "webm", "mp3", "m4a", "wav"}

# ---------------------------------------------------------------------------

def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    s = max(0, int(seconds))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def _atomic_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)

# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class URLFileInfo:
    url_file: Path
    stem: str
    source: str  # "main" or "ae"
    out_dir: Path
    url_count: int
    downloaded: int
    bad: int
    remaining: int
    viable_checked: bool

@dataclass
class CountsSnapshot:
    version: int = 1
    computed_at: str = field(default_factory=_now_str)
    sources: Dict[str, Dict[str, str]] = field(default_factory=dict)
    files: Dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "computed_at": self.computed_at,
            "sources": self.sources,
            "files": self.files,
        }

# ---------------------------------------------------------------------------
# yt-dlp helpers used during the scan phase (main source)

_YTDLP_NOT_FOUND = 127

def _ytdlp_get_expected_filename(yt_dlp: str, url: str, template: str) -> Tuple[int, str]:
    """
    Return (rc, value). When rc==0, value is the expected output filename
    for the given template. Otherwise, value is a short error message.
    """
    cmd = [yt_dlp, "--simulate", "--get-filename", "-o", template, url]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore"
        )
    except FileNotFoundError:
        return (_YTDLP_NOT_FOUND, "yt-dlp not found")
    except Exception as ex:
        return (1, f"yt-dlp error: {ex}")

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0 and out:
        return (0, out.splitlines()[0].strip())
    msg = err if err else (out if out else "yt-dlp failed")
    return (proc.returncode, msg)

_DUP_SUFFIX_RE = re.compile(r"\s+\(\d+\)$")

def _exists_with_dup(dest_dir: Path, expected_filename: str) -> bool:
    """
    True if expected exists OR a common duplicate variant exists:
      "<stem> (N)<ext>"
    """
    target = dest_dir / expected_filename
    if target.exists():
        return True
    if not dest_dir.exists():
        return False
    exp = Path(expected_filename)
    for f in dest_dir.glob(f"*{exp.suffix.lower()}"):
        if not f.is_file() or f.suffix.lower() != exp.suffix.lower():
            continue
        # exact stem match or duplicate form
        stem = f.stem
        base = exp.stem
        if stem == base:
            return True
        if stem.startswith(base) and _DUP_SUFFIX_RE.search(stem[len(base):] or ""):
            return True
    return False

# ---------------------------------------------------------------------------

def _scan_one_file_main_with_ytdlp(
    url_file: Path,
    out_base: Path,
    *,
    yt_dlp: str,
    template: str,
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    ui_set_label,         # callable(text)
    ui_progress,          # callable(seen, total, already, bad, eta)
    log_fn,               # callable(str)
) -> URLFileInfo:
    """Slow & correct scan: query yt-dlp per URL and check presence."""
    urls = read_urls_from_files([url_file])
    total = len(urls)
    stem = url_file.stem
    dest = out_base / stem

    seen = 0
    already = 0
    bad = 0
    start = time.time()

    ui_set_label(f"main:{stem}")

    for url in urls:
        if stop_evt.is_set():
            break
        while pause_evt.is_set() and not stop_evt.is_set():
            time.sleep(0.05)

        rc, value = _ytdlp_get_expected_filename(yt_dlp, url, template)
        if rc == 0:
            expected = value
            ok = _exists_with_dup(dest, expected)
            if ok:
                already += 1
        else:
            bad += 1
            log_fn(f"SCAN main {url_file} yt-dlp rc={rc} msg={value}")

        seen += 1
        elapsed = max(0.001, time.time() - start)
        rate = seen / elapsed
        eta = (max(0, total - seen) / rate) if rate > 0 else None
        ui_progress(seen, total, already, bad, eta)

    remaining = max(0, total - already - bad)
    return URLFileInfo(
        url_file=url_file,
        stem=stem,
        source="main",
        out_dir=dest,
        url_count=total,
        downloaded=already,
        bad=bad,
        remaining=remaining,
        viable_checked=True,
    )

# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _WorkFile:
    url_file: Path
    stem: str
    source: str
    out_dir: Path
    urls: List[str]
    remaining: int

def _build_worklist(snap: CountsSnapshot) -> List[_WorkFile]:
    work: List[_WorkFile] = []
    for key, rec in snap.files.items():
        url_file = Path(key)
        try:
            urls = read_urls_from_files([url_file])
        except Exception:
            urls = []
        work.append(
            _WorkFile(
                url_file=url_file,
                stem=str(rec.get("stem") or url_file.stem),
                source=str(rec.get("source") or "main"),
                out_dir=Path(rec.get("out_dir") or DEF_OUT_DIR / url_file.stem),
                urls=urls,
                remaining=int(rec.get("remaining") or max(0, len(urls) - int(rec.get("downloaded", 0)))),
            )
        )
    return work

# ---------------------------------------------------------------------------

def _scan_all_parallel(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_base: Path,
    *,
    yt_dlp: str,
    ytdlp_template: str,
    n_workers: int,
    counts_path: Path,
    ui,
    log_fn,
    stop_evt: threading.Event,
    pause_evt: threading.Event,
) -> CountsSnapshot:
    """Scan MAIN using yt-dlp; AE is skipped (placeholder) for now."""
    def _iter_txt(d: Path) -> List[Path]:
        return [p for p in sorted(Path(d).glob("*.txt")) if p.is_file()]

    main_files: List[Path] = _iter_txt(main_url_dir)
    ae_files: List[Path] = _iter_txt(ae_url_dir)  # collected only to announce skip
    all_files: List[Tuple[Path, str]] = [(p, "main") for p in main_files] + [(p, "ae") for p in ae_files]

    snap = CountsSnapshot()
    snap.sources = {
        "main": {"url_dir": str(main_url_dir.resolve()), "out_dir": str(out_base.resolve())},
        "ae": {"url_dir": str(ae_url_dir.resolve()), "out_dir": str(out_base.resolve())},
    }

    # write stub counts early
    try:
        _atomic_json(counts_path, snap.to_json())
    except Exception:
        pass

    ui.begin_scan(n_workers, len(all_files))
    ui.set_footer("Keys: z pause/resume • q confirm quit • Q force quit")
    # optional TSV path for UI side (guarded)
    try:
        ui.set_scan_log_path(counts_path.with_name("ytaedl-scan-results.tsv"))
    except Exception:
        pass

    q: "queue.Queue[tuple[Path,str]]" = queue.Queue()
    for f, src in all_files:
        q.put((f, src))

    files_lock = threading.Lock()
    # per-slot running tallies to compute deltas for the banner
    banner_state: Dict[int, Dict[str, int]] = {}

    def worker(slot: int):
        while not stop_evt.is_set():
            try:
                f, src = q.get_nowait()
            except queue.Empty:
                break

            # UI hooks for this slot
            def set_label(text: str):
                ui.set_scan_slot(slot, text)

            def set_progress(seen: int, total: int, already: int, bad: int, eta: Optional[float]):
                # keep the slot label compact; let Termdash handle columns
                ui.set_scan_slot(slot, f"{src}:{f.stem} {seen}/{total} ✓{already} ✗{bad} {_fmt_hms(eta)}")
                # banner deltas (guarded)
                try:
                    prev = banner_state.setdefault(slot, {"seen": 0, "already": 0, "bad": 0})
                    d_seen = max(0, int(seen) - prev["seen"])
                    d_alr  = max(0, int(already) - prev["already"])
                    d_bad  = max(0, int(bad) - prev["bad"])
                    if d_seen or d_alr or d_bad:
                        if hasattr(ui, "scan_progress_delta"):
                            ui.scan_progress_delta(d_seen, d_alr, d_bad)
                    prev["seen"], prev["already"], prev["bad"] = int(seen), int(already), int(bad)
                except Exception:
                    pass

            if src == "ae":
                # For now, you asked to focus on yt-dlp. Mark AE as skipped.
                set_label(f"ae:{f.stem} (skipped)")
                ui.advance_scan(1)
                continue

            log_fn(f"SCAN start main {f}")

            try:
                info = _scan_one_file_main_with_ytdlp(
                    f, out_base,
                    yt_dlp=yt_dlp,
                    template=ytdlp_template,
                    pause_evt=pause_evt,
                    stop_evt=stop_evt,
                    ui_set_label=set_label,
                    ui_progress=set_progress,
                    log_fn=log_fn,
                )
            except Exception as ex:
                log_fn(f"SCAN error main {f}: {ex}")
                info = URLFileInfo(f, f.stem, "main", out_base / f.stem, 0, 0, 0, 0, False)

            with files_lock:
                try:
                    st = f.stat()
                    snap.files[str(f.resolve())] = {
                        "stem": info.stem,
                        "source": info.source,
                        "out_dir": str(info.out_dir.resolve()),
                        "url_count": info.url_count,
                        "downloaded": info.downloaded,
                        "bad": info.bad,
                        "remaining": info.remaining,
                        "viable_checked": info.viable_checked,
                        "url_mtime": int(st.st_mtime),
                        "url_size": int(st.st_size),
                    }
                    _atomic_json(counts_path, snap.to_json())
                except Exception:
                    pass

            # per-file summary to UI for TSV (guarded)
            try:
                ui.scan_file_done(f, total=info.url_count, downloaded=info.downloaded, bad=info.bad)
            except Exception:
                pass

            ui.advance_scan(1)
            log_fn(
                f"SCAN done  main {f} urls={info.url_count} dl={info.downloaded} bad={info.bad} rem={info.remaining}"
            )

            if stop_evt.is_set():
                break

    threads: List[threading.Thread] = []
    for i in range(max(1, n_workers)):
        t = threading.Thread(target=worker, args=(i,), daemon=True, name=f"scan-{i+1}")
        t.start()
        threads.append(t)

    # pump UI while workers run (keeps pause from misaligning)
    while any(t.is_alive() for t in threads):
        if stop_evt.is_set():
            break
        ui.pump()
        time.sleep(0.05)

    for t in threads:
        t.join(timeout=1.0)

    ui.end_scan()
    ui.pump()
    return snap

# ---------------------------------------------------------------------------

class _Coordinator:
    """Simple work balancer; prefers items with more remaining."""
    def __init__(self, work: List[_WorkFile]):
        self._lock = threading.Lock()
        self._work: Dict[str, _WorkFile] = {str(w.url_file.resolve()): w for w in work}
        self._assigned: Dict[str, int] = {}

    def acquire_next(self) -> Optional[_WorkFile]:
        with self._lock:
            candidates = sorted(self._work.values(), key=lambda w: (-w.remaining, w.stem))
            for w in candidates:
                key = str(w.url_file.resolve())
                if self._assigned.get(key, 0) > 0:
                    continue
                self._assigned[key] = 1
                return w
            return None

    def release(self, wf: _WorkFile, *, remaining_delta: int = 0) -> None:
        with self._lock:
            key = str(wf.url_file.resolve())
            if key not in self._work:
                return
            cur = self._work[key]
            new_remaining = max(0, int(cur.remaining) + int(remaining_delta))
            self._work[key] = dataclasses.replace(cur, remaining=new_remaining)
            if key in self._assigned:
                self._assigned[key] = max(0, self._assigned[key] - 1)

# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ytaedl-orchestrate",
        description="Orchestrate scanning and downloads with a Termdash UI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--threads", type=int, default=2, help="Concurrent worker slots.")
    p.add_argument("-m", "--max-dl", type=int, default=3, help="Max successful URLs per assignment.")
    p.add_argument("--url-dir", type=Path, default=DEF_URL_DIR, help="Main URL dir (stars).")
    p.add_argument("--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AE URL dir (ae-stars).")
    p.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Base output dir.")
    p.add_argument("-c", "--counts-file", type=Path, default=DEF_COUNTS_FILE, help="JSON counts file path.")
    p.add_argument("-e", "--exts", default=",".join(sorted(DEF_EXTS)), help="Extensions considered 'downloaded'.")
    p.add_argument("--no-ui", action="store_true", help="Disable Termdash UI.")
    p.add_argument("--ytdlp", default="yt-dlp", help="yt-dlp executable for scan.")
    p.add_argument("--ytdlp-template", default="%(title)s.%(ext)s", help="Template used to derive filenames.")
    # Downloader config (subset; unchanged)
    p.add_argument("-j", "--jobs", type=int, default=1, help="Per-process jobs for downloader.")
    p.add_argument("--archive", type=Path, default=None, help="Optional archive path.")
    p.add_argument("--log-file", "-L", type=Path, help="Append log to this file.")
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--rate-limit", default=None)
    p.add_argument("--buffer-size", default=None)
    p.add_argument("--retries", type=int, default=None)
    p.add_argument("--fragment-retries", type=int, default=None)
    p.add_argument("--ytdlp-connections", type=int, default=None)
    p.add_argument("--aria2-splits", type=int, default=None)
    p.add_argument("--aria2-x-conn", type=int, default=None)
    p.add_argument("--aria2-min-split", default=None)
    p.add_argument("--aria2-timeout", type=int, default=None)
    return p.parse_args(argv)

def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=args.output_dir,
        archive_path=args.archive,
        max_size_gb=10.0,
        keep_oversized=False,
        timeout_seconds=args.timeout,
        parallel_jobs=max(1, args.jobs),
        aebn_only=False,
        scene_from_url=True,
        save_covers=False,
        keep_covers_flag=False,
        extra_aebn_args=[],
        extra_ytdlp_args=[],
        ytdlp_connections=args.ytdlp_connections,
        ytdlp_rate_limit=args.rate_limit,
        ytdlp_retries=args.retries,
        ytdlp_fragment_retries=args.fragment_retries,
        ytdlp_buffer_size=args.buffer_size,
        aria2_splits=args.aria2_splits,
        aria2_x_conn=args.aria2_x_conn,
        aria2_min_split=args.aria2_min_split,
        aria2_timeout=args.aria2_timeout,
        log_file=args.log_file,
    )

# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # normalize paths
    args.url_dir = Path(args.url_dir)
    args.ae_url_dir = Path(args.ae_url_dir)
    args.output_dir = Path(args.output_dir)
    args.counts_file = Path(args.counts_file)

    # optional log file
    log_fp = None
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(args.log_file, "a", encoding="utf-8")
        except Exception:
            log_fp = None

    def olog(msg: str) -> None:
        if log_fp:
            try:
                log_fp.write(f"[{_now_str()}] {msg}\n")
                log_fp.flush()
            except Exception:
                pass

    # UI
    use_ui = not args.no_ui
    if use_ui:
        try:
            ui = TermdashUI(num_workers=max(1, args.threads), total_urls=0)
        except Exception as ex:
            olog(f"UI fallback: {ex}")
            try:
                ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
            except TypeError:
                ui = SimpleUI()
            use_ui = False
    else:
        try:
            ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
        except TypeError:
            ui = SimpleUI()

    stop_evt = threading.Event()
    pause_evt = threading.Event()

    # hotkeys (best effort)
    def _key_reader():
        if not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt
            while not stop_evt.is_set():
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("z", "Z"):
                        if pause_evt.is_set():
                            pause_evt.clear()
                            try: ui.set_paused(False)
                            except Exception: pass
                        else:
                            pause_evt.set()
                            try: ui.set_paused(True)
                            except Exception: pass
                    elif ch == "q":
                        stop_evt.set()
                        break
                    elif ch == "Q":
                        stop_evt.set()
                        request_abort()
                        terminate_all_active_procs()
                        break
                else:
                    time.sleep(0.1)
        else:
            import termios, tty, select
            fd = sys.stdin.fileno()
            try:
                old = termios.tcgetattr(fd)
            except Exception:
                return
            try:
                tty.setcbreak(fd)
                while not stop_evt.is_set():
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if not r:
                        continue
                    ch = os.read(fd, 1).decode(errors="ignore")
                    if ch in ("z", "Z"):
                        if pause_evt.is_set():
                            pause_evt.clear()
                            try: ui.set_paused(False)
                            except Exception: pass
                        else:
                            pause_evt.set()
                            try: ui.set_paused(True)
                            except Exception: pass
                    elif ch == "q":
                        stop_evt.set()
                        break
                    elif ch == "Q":
                        stop_evt.set()
                        request_abort()
                        terminate_all_active_procs()
                        break
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except Exception:
                    pass

    with ui:
        olog("orchestrator start")
        threading.Thread(target=_key_reader, daemon=True, name="keys").start()

        # ---- SCAN (yt-dlp per URL, main only) ----
        snap = _scan_all_parallel(
            args.url_dir,
            args.ae_url_dir,
            args.output_dir,
            yt_dlp=args.ytdlp,
            ytdlp_template=args.ytdlp_template,
            n_workers=max(1, args.threads),
            counts_path=args.counts_file,
            ui=ui,
            log_fn=olog,
            stop_evt=stop_evt,
            pause_evt=pause_evt,
        )
        if stop_evt.is_set():
            if log_fp:
                try: log_fp.close()
                except Exception: pass
            return 130

        # ---- Build work and run downloads (unchanged semantics) ----
        work = sorted(_build_worklist(snap), key=lambda w: (w.remaining, w.stem))
        coord = _Coordinator(work)

        cfg = _build_config(args)
        object.__setattr__(cfg, "_orchestrator_max_dl", int(args.max_dl))

        def worker(slot: int):
            while not stop_evt.is_set():
                wf = coord.acquire_next()
                if wf is None:
                    break
                ui.set_scan_slot(slot, f"{wf.source}:{wf.stem} downloading (rem {wf.remaining})")
                completed = 0
                cap = getattr(cfg, "_orchestrator_max_dl", 3)

                for idx, url in enumerate(wf.urls, start=1):
                    if stop_evt.is_set():
                        break
                    while pause_evt.is_set() and not stop_evt.is_set():
                        ui.pump()
                        time.sleep(0.1)
                    if stop_evt.is_set():
                        break

                    dest_dir = wf.out_dir
                    # fast skip if clearly present
                    try:
                        slug = get_url_slug(url)
                        # simple slug existence check — keep behavior stable
                        present = any(p.name.startswith(slug) for p in dest_dir.glob("*"))
                    except Exception:
                        present = False
                    if present:
                        try:
                            item = DownloadItem(id=idx, url=url,
                                                source=URLSource.MAIN if wf.source == "main" else URLSource.AE,
                                                out_dir=dest_dir)
                            ui.handle_event(LogEvent(item=item, message="already_exists"))
                            ui.pump()
                        except Exception:
                            pass
                        completed += 1
                        if completed >= cap:
                            break
                        continue

                    dl = get_downloader(url)
                    item = DownloadItem(
                        id=idx,
                        url=url,
                        source=URLSource.MAIN if wf.source == "main" else URLSource.AE,
                        out_dir=dest_dir,
                    )
                    try:
                        ui.handle_event(StartEvent(item=item))
                        ui.pump()
                        for ev in dl.download(item, cfg):
                            if stop_evt.is_set():
                                break
                            ui.handle_event(ev)
                            ui.pump()
                    except KeyboardInterrupt:
                        stop_evt.set()
                        break
                    except Exception as ex:
                        olog(f"DOWNLOAD error {url}: {ex}")
                    finally:
                        ui.pump()

                    completed += 1
                    if completed >= cap:
                        break

                coord.release(wf, remaining_delta=-(completed))

        threads: List[threading.Thread] = []
        for i in range(max(1, int(args.threads))):
            t = threading.Thread(target=worker, args=(i,), daemon=True, name=f"dl-{i+1}")
            t.start()
            threads.append(t)

        try:
            while any(t.is_alive() for t in threads) and not stop_evt.is_set():
                ui.pump()
                time.sleep(0.1)
        finally:
            for t in threads:
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass

        ui.summary({}, time.monotonic())

    if log_fp:
        try:
            log_fp.close()
        except Exception:
            pass
    return 0

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit(main())
